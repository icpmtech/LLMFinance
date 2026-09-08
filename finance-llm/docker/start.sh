#!/bin/sh
# Entrypoint legado para compatibilidade
set -e

mkdir -p /app/data/raw /app/data/processed /app/data/final /app/data/forecasting /app/data/documents/uploads /app/data/rag/markdown /app/data/rag/chunks

exec python -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --workers 1 --log-level info
