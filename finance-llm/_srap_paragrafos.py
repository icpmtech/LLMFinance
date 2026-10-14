"""Imprime os parágrafos da coluna da esquerda de uma página (temporário)."""
from __future__ import annotations

import io
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))

from api import remuneracoes_ap_service as servico  # noqa: E402

import pymupdf  # noqa: E402

doc = pymupdf.open(servico.PASTA / "pdf" / servico.FICHEIROS[2025])
saida = io.open(Path(os.environ["TEMP"]) / "srap_paragrafos.txt", "w", encoding="utf-8")
for pno in [int(a) for a in sys.argv[1:]]:
    saida.write(f"\n===== página {pno} =====\n")
    for paragrafo in servico._paragrafos_da_coluna(doc[pno - 1]):
        saida.write(f"y0={paragrafo['y0']:6.1f} y1={paragrafo['y1']:6.1f} {paragrafo['texto']!r}\n")
saida.close()
print("escrito", Path(os.environ["TEMP"]) / "srap_paragrafos.txt")
