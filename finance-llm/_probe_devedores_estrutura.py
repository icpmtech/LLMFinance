"""Estrutura global do PDF dos devedores: cabeçalhos de escalão, contagens e amostras."""
from __future__ import annotations

import re
import sys
from collections import Counter

import pymupdf

caminho = sys.argv[1] if len(sys.argv) > 1 else "_tmp_devedores/listaFS1.pdf"
doc = pymupdf.open(caminho)

cabecalhos: Counter = Counter()
paginas_com_cabecalho: dict[str, list[int]] = {}
nif_re = re.compile(r"^\d{9}$")
linhas_nif = 0
colunas = Counter()

for indice in range(doc.page_count):
    texto = doc[indice].get_text("text")
    linhas = [l.strip() for l in texto.splitlines() if l.strip()]
    for linha in linhas:
        baixa = linha.lower()
        if baixa.startswith(("contribuintes", "devedores", "informação", "informaç", "nif", "nome", "valor")):
            cabecalhos[linha] += 1
            paginas_com_cabecalho.setdefault(linha, []).append(indice + 1)
        elif nif_re.match(linha):
            linhas_nif += 1
    # nº de "colunas" por linha (linhas com NIF + valor na mesma linha)
    for linha in linhas:
        if nif_re.match(linha.split()[0]) and len(linha.split()) > 1:
            colunas[linha.split()[-1][:14]] += 1

print(f"páginas={doc.page_count} linhas só-NIF={linhas_nif}")
print("\n--- cabeçalhos (top 25) ---")
for cabecalho, quantas in cabecalhos.most_common(25):
    paginas = paginas_com_cabecalho[cabecalho]
    print(f"  {quantas:>4}x  {cabecalho!r}  (1ª pág. {paginas[0]})")

print("\n--- linhas com NIF + mais alguma coisa (top 10) ---")
for valor, quantas in colunas.most_common(10):
    print(f"  {quantas:>4}x  {valor!r}")

print("\n--- última página (500 chars) ---")
print(doc[doc.page_count - 1].get_text("text")[:500])

print("\n--- tabelas por página (amostra de 6 páginas) ---")
for indice in range(0, doc.page_count, max(1, doc.page_count // 6)):
    tabelas = doc[indice].find_tables()
    print(f"  pág. {indice + 1}: {len(tabelas.tables)} tabela(s)")
    for tabela in tabelas.tables[:1]:
        for linha in tabela.extract()[:3]:
            print("     ", linha)
