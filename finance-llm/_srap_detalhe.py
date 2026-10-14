"""Detalhe (temporário) das linhas da coluna da esquerda e dos marcadores."""
from __future__ import annotations

import io
import os
import sys

import pymupdf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _srap_explorar import PASTA, linhas_da_pagina  # noqa: E402

ficheiro = os.path.join(PASTA, "SRAP_2025.pdf")
doc = pymupdf.open(ficheiro)
saida = io.open(os.path.join(PASTA, "detalhe.txt"), "w", encoding="utf-8")
for pno in [int(a) for a in sys.argv[1:]] or [6, 8]:
    linhas = linhas_da_pagina(doc[pno - 1])
    saida.write(f"\n===== página {pno} =====\n")
    for linha in linhas:
        if linha["y"] < 55 or linha["y"] > 800:
            continue
        esquerda = [w[4] for w in linha["palavras"] if w[2] < 150]
        marcador = [w[4] for w in linha["palavras"] if 150 <= w[0] < 400]
        direita = [w[4] for w in linha["palavras"] if w[0] >= 400]
        saida.write(
            f"y={linha['y']:6.1f} esq={(' '.join(esquerda))[:60]:60} "
            f"marc={(' '.join(marcador))[:46]:46} dir={(' '.join(direita))[:60]}\n"
        )
saida.close()
print("escrito", os.path.join(PASTA, "detalhe.txt"))
