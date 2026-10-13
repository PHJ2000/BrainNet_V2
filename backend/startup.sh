#!/bin/bash
set -euo pipefail

echo "Waiting for PostgreSQL to be ready..."
: "${DATABASE_URL:?DATABASE_URL must be set}"
DATABASE_READY_URL="${DATABASE_URL/postgresql+asyncpg:/postgresql:}"
while ! pg_isready --dbname="$DATABASE_READY_URL" >/dev/null 2>&1; do
  sleep 1
done

# Database migrations are owned by Spring/Flyway.


echo "Starting server..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
