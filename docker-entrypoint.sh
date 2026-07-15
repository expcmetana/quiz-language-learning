#!/bin/sh
set -e

DATA_DIR=$(dirname "$DATABASE_PATH")
mkdir -p "$DATA_DIR"
chown -R appuser:appuser "$DATA_DIR"

exec setpriv --reuid=appuser --regid=appuser --init-groups /bin/sh -c '
    set -e
    export HOME=/home/appuser
    uv run alembic upgrade head
    exec uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
'
