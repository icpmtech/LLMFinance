"""Diagnóstico rápido do leitor em streaming do Portal Base.

Uso: python -u /app/logs/_probe_base_iter.py [ano]
"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

sys.path.insert(0, "/app")

from api import base_impic  # noqa: E402

ano = sys.argv[1] if len(sys.argv) > 1 else "2026"
caminho = base_impic.caminho_local(ano, "zip")
print("zip:", caminho, "existe:", caminho.exists())

lidos = 0
primeiro = None
erros = 0
for bruto in base_impic.iter_registos(caminho, limite=5):
    lidos += 1
    if primeiro is None:
        primeiro = bruto

print("registos lidos:", lidos)
if primeiro:
    print("chaves:", list(primeiro)[:12])
    normalizar = base_impic._normalizador()
    try:
        doc = normalizar(primeiro)
        print("normalizado:", {k: doc.get(k) for k in ("idcontrato", "Ano", "precoContratual", "adjudicante")})
    except Exception:
        erros += 1
        traceback.print_exc()
print("erros de normalização:", erros)
