"""Inspecionar a estrutura da lista de devedores (PDF do Portal das Finanças)."""
from __future__ import annotations

import sys

import pymupdf

caminho = sys.argv[1] if len(sys.argv) > 1 else "_tmp_devedores/listaFS1.pdf"
paginas = int(sys.argv[2]) if len(sys.argv) > 2 else 2

doc = pymupdf.open(caminho)
print(f"ficheiro={caminho} páginas={doc.page_count} metadados={doc.metadata}")
primeira = doc[0]
print(f"\n--- página 1 (tamanho {primeira.rect}) ---")
texto = primeira.get_text("text")
print(texto[:2500])
print(f"\n[linhas na página 1: {len(texto.splitlines())}]")

if doc.page_count > 1 and paginas > 1:
    print(f"\n--- página 2 (primeiras 1200 chars) ---")
    print(doc[1].get_text("text")[:1200])

# tabelas detetadas
for indice in range(min(paginas, doc.page_count)):
    tabelas = doc[indice].find_tables()
    print(f"\npágina {indice + 1}: {len(tabelas.tables)} tabela(s)")
    for t in tabelas.tables[:1]:
        print("  colunas:", t.col_count, "linhas:", t.row_count)
        for linha in t.extract()[:6]:
            print("   ", linha)
