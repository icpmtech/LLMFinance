"""Exploração (temporária) dos PDFs do Sistema Remuneratório da AP da DGAEP.

Serve para desenhar o parser: mostra, por página, a secção do rodapé, os blocos
`p)/n)/r)` e as linhas da coluna da esquerda (nomes de carreira/categoria),
para se confirmar a associação nome→bloco antes de a escrever no serviço.
"""
from __future__ import annotations

import os
import re
import sys
from typing import Any, Dict, List

import pymupdf

PASTA = os.path.join(os.environ.get("TEMP", ""), "srap")


def linhas_da_pagina(page: pymupdf.Page) -> List[Dict[str, Any]]:
    """Agrupa as palavras da página em linhas (por coordenada vertical)."""
    palavras = sorted(page.get_text("words"), key=lambda w: (round(w[1] / 2) * 2, w[0]))
    linhas: List[Dict[str, Any]] = []
    for w in palavras:
        y = w[1]
        alvo = next((linha for linha in linhas if abs(linha["y"] - y) <= 3.5), None)
        if alvo is None:
            alvo = {"y": y, "palavras": []}
            linhas.append(alvo)
        alvo["palavras"].append(w)
    for linha in linhas:
        linha["palavras"].sort(key=lambda w: w[0])
        linha["texto"] = " ".join(w[4] for w in linha["palavras"])
        linha["x0"] = min(w[0] for w in linha["palavras"])
        linha["x1"] = max(w[2] for w in linha["palavras"])
    linhas.sort(key=lambda linha: linha["y"])
    return linhas


def secao_da_pagina(page: pymupdf.Page) -> str:
    """Secção pelo rodapé (`Sistema Remuneratório da Administração Pública…`)."""
    for linha in reversed(linhas_da_pagina(page)):
        if "Sistema Remunerat" in linha["texto"]:
            return re.sub(r"^\s*Sistema Remunerat\w*\s+da\s+Administra\w*\s+P\w*\s+\d{4}\s*[-–]\s*", "", linha["texto"]).strip()
    return ""


def main() -> None:
    import io

    saida = io.open(os.path.join(PASTA, "exploracao.txt"), "w", encoding="utf-8")
    global print

    def escrever(*partes: Any, **_kwargs: Any) -> None:
        saida.write(" ".join(str(parte) for parte in partes) + "\n")

    print = escrever  # type: ignore[assignment]
    anos = sys.argv[1:] or ["2025"]
    for ano in anos:
        ficheiro = next(
            (nome for nome in os.listdir(PASTA) if ano in nome and nome.endswith(".pdf")),
            None,
        )
        if not ficheiro:
            print(f"[{ano}] sem PDF em {PASTA}")
            continue
        doc = pymupdf.open(os.path.join(PASTA, ficheiro))
        print(f"\n===== {ficheiro} · {doc.page_count} páginas =====")
        for i in range(doc.page_count):
            page = doc[i]
            linhas = linhas_da_pagina(page)
            texto = page.get_text()
            marcadores = [linha for linha in linhas if re.match(r"^(p|n|r|i)\)$", linha["texto"].split(" ")[0])]
            titulo = next((linha["texto"] for linha in linhas[:3] if linha["texto"].strip()), "")
            print(f"p{i + 1:3} | {secao_da_pagina(page)[:48]:48} | marcadores={len(marcadores):3} | {titulo[:60]}")
            if marcadores:
                for linha in marcadores[:3]:
                    valores = [w[4] for w in linha["palavras"][1:]]
                    print(f"        y={linha['y']:6.1f} x0={linha['x0']:5.1f} {linha['texto'][:70]}")
                    print(f"            valores: {' '.join(valores)[:110]}")
                nomes = [linha for linha in linhas if linha["x0"] < 150 and not re.search(r"\d{3,}", linha["texto"])]
                print(f"        nomes na coluna (x0<150): {[n['texto'][:34] for n in nomes if n['y'] > 60][:8]}")


if __name__ == "__main__":
    import io

    saida = io.open(os.path.join(PASTA, "exploracao.txt"), "w", encoding="utf-8")
    original = print

    def escrever(*partes: Any, **_kwargs: Any) -> None:
        saida.write(" ".join(str(parte) for parte in partes) + "\n")

    import builtins

    builtins.print = escrever
    try:
        main()
    finally:
        builtins.print = original
        saida.close()
        original(f"escrito: {os.path.join(PASTA, 'exploracao.txt')}")
