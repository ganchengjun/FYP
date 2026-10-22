#!/usr/bin/env bash
# Local MySQL 8.4 for development. Credentials are generated once in ignored files.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
PYTHON_BIN="${IRICE_PYTHON:-.venv/bin/python}"
command -v docker >/dev/null || { echo 'Docker is required for the local MySQL service.' >&2; exit 1; }
"$PYTHON_BIN" - <<'PY'
from pathlib import Path
from urllib.parse import quote_plus
import secrets
path = Path('instance')
path.mkdir(exist_ok=True)
credential_file = path / 'mysql.env'
app_file = path / '.env'
if not credential_file.exists():
    if app_file.exists():
        raise SystemExit('Existing instance/.env preserved. Configure your own MySQL, or move it aside before initializing local MySQL.')
    root_password = secrets.token_urlsafe(32)
    password = secrets.token_urlsafe(32)
    with credential_file.open('x') as file:
        credential_file.chmod(0o600)
        file.write(f'MYSQL_ROOT_PASSWORD={root_password}\nMYSQL_DATABASE=irice\nMYSQL_USER=irice\nMYSQL_PASSWORD={password}\n')
    with app_file.open('x') as file:
        app_file.chmod(0o600)
        file.write(f'DATABASE_URL=mysql+pymysql://irice:{quote_plus(password)}@127.0.0.1:3307/irice?charset=utf8mb4\n')
        file.write('SECRET_KEY=' + secrets.token_hex(32) + '\n')
elif not app_file.exists():
    raise SystemExit('Local database credentials exist but instance/.env is missing. Restore that file; credentials were not replaced.')
PY
if docker container inspect irice-mysql >/dev/null 2>&1; then
  docker start irice-mysql >/dev/null
else
  mkdir -p instance/mysql-data
  docker run -d --name irice-mysql --restart unless-stopped \
    --env-file instance/mysql.env -p 127.0.0.1:3307:3306 \
    -v "$PWD/instance/mysql-data:/var/lib/mysql" \
    mysql:8.4@sha256:76f0358884cb92d9a086d24e5671c38048d3fef40f2588703d73eb55392d6b69 >/dev/null
fi
for attempt in {1..45}; do
  if docker exec irice-mysql sh -c 'MYSQL_PWD="$MYSQL_PASSWORD" mysql -uirice -N -e "SELECT 1" irice' >/dev/null 2>&1; then
    echo 'MySQL is ready on 127.0.0.1:3307.'
    exit 0
  fi
  sleep 1
done
echo 'MySQL did not become ready. Inspect: docker logs irice-mysql' >&2
exit 1
