#!/bin/sh
set -e

# Migrations are opt-in. The hosted image leaves RUN_MIGRATIONS=false and runs
# `alembic upgrade head` as a separate one-off job, so a rolling restart or a
# second replica can never race a schema change. Local compose sets it to true.
if [ "${RUN_MIGRATIONS:-false}" = "true" ]; then
  echo "Running Alembic migrations..."
  alembic upgrade head
fi

echo "Starting uvicorn..."
# --proxy-headers is deliberately NOT used: client IP handling is done in the
# app from TRUSTED_PROXY_HOPS, which only trusts the right-most entries.
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
