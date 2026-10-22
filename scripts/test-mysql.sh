#!/usr/bin/env bash
# Uses only irice_test; never points pytest at the application database.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
PYTHON_BIN="${IRICE_PYTHON:-.venv/bin/python}"
IRICE_PYTHON="$PYTHON_BIN" bash scripts/mysql.sh
docker exec irice-mysql sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot -e "CREATE DATABASE IF NOT EXISTS irice_test CHARACTER SET utf8mb4; GRANT ALL PRIVILEGES ON irice_test.* TO '\''irice'\''@'\''%'\'';"'
exec "$PYTHON_BIN" - <<'PY'
import os
import subprocess
import sys
from dotenv import dotenv_values
from sqlalchemy.engine import make_url
config = dotenv_values('instance/.env')
uri = make_url(config['DATABASE_URL']).set(database='irice_test')
environment = os.environ.copy()
environment['IRICE_TEST_DATABASE_URL'] = uri.render_as_string(hide_password=False)
raise SystemExit(subprocess.call([sys.executable, '-m', 'pytest', '-q'], env=environment))
PY
