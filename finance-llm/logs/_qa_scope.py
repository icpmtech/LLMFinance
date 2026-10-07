"""Diagnostico do ranking **por âmbito**, sem fusão RRF.

Responde a: «Solresor i Sverige AB» aparece em 1.º porque o Elasticsearch a
devolve em 1.º no âmbito das entidades, ou porque a fusão lhe dá peso a mais?

Uso:
    python logs/_qa_scope.py "Quantos contratos tem a CLARANET II SOLUTIONS?"
"""
from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from api import deep_search_service as deep  # noqa: E402
from api import search_service  # noqa: E402


def main() -> None:
    pergunta = sys.argv[1] if len(sys.argv) > 1 else "Quantos contratos tem a CLARANET II SOLUTIONS e qual o valor total adjudicado?"
    termos = deep.keywords(pergunta)
    print(f"pergunta      : {pergunta!r}")
    print(f"termos (BM25) : {termos!r}")
    print()

    print("pesos dos âmbitos:")
    for entrada in deep.SOURCES:
        if entrada.get("weight", 0) >= 0.8:
            print(f"  {entrada['id']:<12} peso={entrada.get('weight')}")
    print()

    for ambito in ("entities", "contracts"):
        print(f"== unified_search(scope={ambito!r}) ==")
        resultado = search_service.unified_search(termos, scope=ambito, size=8)
        if resultado.get("error"):
            print(f"  erro: {resultado['error']}")
            continue
        grupo = next((g for g in resultado.get("groups") or [] if g.get("scope") == ambito), None)
        if not grupo:
            print("  sem grupo")
            continue
        print(f"  total={grupo.get('total')}")
        for posicao, item in enumerate(grupo.get("items") or [], start=1):
            subtitulo = (item.get("subtitle") or "")[:44]
            pontuacao = item.get("score")
            pontuacao = f"{pontuacao:>8}" if isinstance(pontuacao, (int, float)) else "       ?"
            print(f"  {posicao:>2}. {pontuacao} {str(item.get('title'))[:52]}")
            if subtitulo:
                print(f"      {'':>8} {subtitulo}")
        print()

    # A busca vetorial é a outra metade do híbrido: se o resultado estranho vier
    # daqui, é aqui que se vê.
    print("== vector_search(finance_entities) ==")
    try:
        vizinhos = deep.vectors.vector_search(deep.VECTOR_INDEXES["entities"], termos, top_k=10)
    except Exception as erro:  # noqa: BLE001
        print(f"  falhou: {type(erro).__name__}: {erro}")
        return
    if vizinhos.get("error"):
        print(f"  erro: {vizinhos['error']}")
        return
    for posicao, linha in enumerate(vizinhos.get("items") or [], start=1):
        print(
            f"  {posicao:>2}. vec={linha.get('vector_score'):.4f} {str(linha.get('name'))[:48]}"
            f"  ({linha.get('country') or '?'} · {linha.get('contracts_count') or 0})"
        )


if __name__ == "__main__":
    main()
