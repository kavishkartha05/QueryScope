#!/bin/sh
set -e

# Run migrations before starting the server so the schema is always up-to-date
# without requiring a separate migration step in CI or on first deploy.
# `alembic upgrade head` is idempotent — safe to run on every container start.
export PYTHONPATH=/app

echo "Running Alembic migrations..."
poetry run alembic upgrade head

echo "Starting uvicorn..."
exec poetry run uvicorn app.main:app --host 0.0.0.0 --port 8000
