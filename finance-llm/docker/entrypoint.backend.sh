#!/bin/sh
set -e

# Garantir que diretórios de dados existem
mkdir -p /app/data/raw /app/data/processed /app/data/final /app/data/forecasting /app/data/documents/uploads /app/data/rag/markdown /app/data/rag/chunks

# Iniciar uvicorn
exec python -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --workers 1 --log-level info
