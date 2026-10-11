#!/usr/bin/env bash
# Passo de build da Vercel (deploy sem Docker).
#
# 1) Gera data/processed/eleicao.db a partir do .zip versionado em data/raw
#    (necessário porque data/processed/ é ignorado pelo Git — o banco é criado
#    no build e embutido no bundle da função).
# 2) Espelha app/static -> public/static: a Vercel ignora o static_folder do
#    Flask e serve os arquivos de public/ pela CDN.
set -euo pipefail

DB_PATH="${DB_PATH:-data/processed/eleicao.db}"

if [ "${FORCE_ETL:-0}" = "1" ] || [ ! -f "$DB_PATH" ]; then
  echo "[vercel-build] Gerando base agregada a partir do arquivo de origem..."
  python -m etl.etl
else
  echo "[vercel-build] Base agregada encontrada em $DB_PATH (FORCE_ETL=1 reprocessa)."
fi

echo "[vercel-build] Espelhando app/static -> public/static..."
rm -rf public/static
mkdir -p public
cp -r app/static public/static

# Em ambiente Vercel (VERCEL=1), o CSV extraído (94 MB) só é necessário durante
# o ETL acima; removê-lo reduz o bundle da função. O .zip continua versionado.
if [ "${VERCEL:-}" = "1" ]; then
  echo "[vercel-build] Removendo CSV extraído para reduzir o bundle..."
  rm -f data/raw/*.csv
fi

echo "[vercel-build] Build concluído."
