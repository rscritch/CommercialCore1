#!/usr/bin/env sh
set -eu

DATA_DIR="${COMMERCIALCORE_DATA_DIR:-/data}"
mkdir -p "$DATA_DIR/uploads" "$DATA_DIR/reports"

if [ ! -f "$DATA_DIR/commercialcore.db" ] && [ -f "/app/seed/commercialcore.db" ]; then
  echo "Initializing CommercialCore demo database..."
  cp /app/seed/commercialcore.db "$DATA_DIR/commercialcore.db"
fi

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
