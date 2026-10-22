#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
PYTHON_BIN="${IRICE_PYTHON:-.venv/bin/python}"
# MySQL must already be running when DATABASE_URL points to it.
"$PYTHON_BIN" -m flask --app irice init-db
exec "$PYTHON_BIN" -m flask --app irice run --host "${IRICE_HOST:-127.0.0.1}" --port "${IRICE_PORT:-5000}"
