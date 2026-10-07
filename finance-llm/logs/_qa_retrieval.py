"""Inspeciona a recuperação de uma pergunta: consulta BM25, contagens por âmbito
e as fontes escolhidas com a respetiva pontuação.

Serve para perceber porque é que uma pergunta longa (linguagem natural) devolve
fontes piores do que a mesma pergunta reduzida ao essencial.

Uso:
    python logs/_qa_retrieval.py "Quantos contratos tem a CLARANET II SOLUTIONS?"
    QA_BACKEND=http://127.0.0.1:8011 python logs/_qa_retrieval.py "..." --modo hybrid
"""
from __future__ import annotations

import argparse
import os
from collections import Counter

import httpx

BACKEND = os.environ.get("QA_BACKEND", "http://127.0.0.1:8002").rstrip("/")


def inspecionar(pergunta: str, modo: str, max_sources: int) -> None:
    parametros = {"q": pergunta, "mode": modo, "max_sources": max_sources, "per_source": 12}
    resposta = httpx.get(f"{BACKEND}/deep-search/search", params=parametros, timeout=180)
    resposta.raise_for_status()
    dados = resposta.json()

    print(f"pergunta     : {pergunta!r}")
    print(f"consulta BM25: {dados.get('text_query')!r}")
    print(f"modo         : {dados.get('mode')} | listas texto={dados.get('text_lists')} vetor={dados.get('vector_lists')}")
    if dados.get("vector_skipped"):
        print(f"saltados     : {dados['vector_skipped']}")
    print(f"tempo        : {dados.get('took_ms')} ms | {len(dados.get('sources') or [])} fontes | sem limite={dados.get('unlimited')}")
    print(f"seguimentos  : {dados.get('suggestions')}")
    print()

    fontes = dados.get("sources") or []
    contagem = Counter(f.get("scope") for f in fontes)
    print("por âmbito   : " + ", ".join(f"{k}={v}" for k, v in contagem.most_common()))
    print()
    for fonte in fontes[:15]:
        titulo = (fonte.get("title") or "")[:64]
        sub = (fonte.get("subtitle") or "")[:40]
        print(f"  [{fonte.get('n'):>2}] {fonte.get('score'):>7.4f} {fonte.get('scope'):<12} {titulo}")
        if sub:
            print(f"       {'':>15} {sub}")


if __name__ == "__main__":
    analisador = argparse.ArgumentParser(description="Inspeciona a recuperação de uma pergunta.")
    analisador.add_argument("pergunta")
    analisador.add_argument("--modo", default="hybrid")
    analisador.add_argument("--max-sources", type=int, default=20)
    argumentos = analisador.parse_args()
    inspecionar(argumentos.pergunta, argumentos.modo, argumentos.max_sources)
