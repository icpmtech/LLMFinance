"""Sondagem (temporária) da página da TRU e das tabelas de base legal."""
from __future__ import annotations

import io
import os

import pymupdf

PASTA = os.path.join(os.environ.get("TEMP", ""), "srap")
doc = pymupdf.open(os.path.join(PASTA, "SRAP_2025.pdf"))
saida = io.open(os.path.join(PASTA, "tru_e_notas.txt"), "w", encoding="utf-8")

saida.write("===== página 4 (TRU) — palavras por linha =====\n")
palavras = sorted(doc[3].get_text("words"), key=lambda w: (round(w[1] / 2) * 2, w[0]))
linhas: list = []
for w in palavras:
    alvo = next((linha for linha in linhas if abs(linha["y"] - w[1]) <= 3.5), None)
    if alvo is None:
        alvo = {"y": w[1], "palavras": []}
        linhas.append(alvo)
    alvo["palavras"].append(w)
for linha in sorted(linhas, key=lambda item: item["y"]):
    partes = [f"{w[4]}@{w[0]:.0f}" for w in sorted(linha["palavras"], key=lambda w: w[0])]
    saida.write(f"y={linha['y']:6.1f} " + " ".join(partes) + "\n")

for pno in (12, 29, 30, 46, 47):
    saida.write(f"\n===== página {pno} — find_tables =====\n")
    for tabela in doc[pno - 1].find_tables().tables:
        linhas_tabela = tabela.extract()
        saida.write(f"colunas={tabela.col_count} linhas={len(linhas_tabela)}\n")
        for linha in linhas_tabela[:6]:
            saida.write("  " + " | ".join((str(c) or "").replace("\n", " ")[:38] for c in linha) + "\n")

saida.close()
print("escrito", os.path.join(PASTA, "tru_e_notas.txt"))
