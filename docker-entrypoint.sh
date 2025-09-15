#!/bin/sh
set -e

# Wait for DB if needed
if [ -n "$DATABASE_URL" ]; then
  echo "Running Alembic migrations..."
  if alembic upgrade head; then
    echo "Ensuring tables via SQLAlchemy Base (for new models without migrations)"
    python -c "from app.core.database import init_db; init_db(); print('init_db done')"
  else
    echo "Alembic failed; will try to create tables via SQLAlchemy Base"
    python -c "from app.core.database import init_db; init_db(); print('init_db done')"
  fi
fi

exec uvicorn app.main:app --host 0.0.0.0 --port 8000
