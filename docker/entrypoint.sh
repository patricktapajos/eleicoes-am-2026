#!/usr/bin/env bash
set -euo pipefail

DB_PATH="${DB_PATH:-/app/data/processed/eleicao.db}"
FORCE_ETL="${FORCE_ETL:-0}"

if [ "$FORCE_ETL" = "1" ] || [ ! -f "$DB_PATH" ]; then
  echo "[entrypoint] Gerando base agregada a partir do arquivo de origem..."
  python -m etl.etl
else
  echo "[entrypoint] Base agregada encontrada em $DB_PATH (use FORCE_ETL=1 para reprocessar)."
fi

exec "$@"
