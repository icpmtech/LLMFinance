"""Porque é que o preço não sai, se ele está lá? Mede o que cada seletor devolve.

Dado um URL de listagem, mostra para os primeiros itens: o que devolve
`::text` vs `get_all_text()`, se `_parece_preco` aceita cada valor, e se a busca
de elementos lança exceção. É o teste que separa «o preço não está na página» de
«o seletor não o vê».

Uso (no contentor)::

    python -u /app/logs/_diagnosticar_preco_sonda.py "https://www.worten.pt/..." --fetcher dynamic
"""
from __future__ import annotations

import argparse
import sys
from typing import Any, List

sys.stdout.reconfigure(encoding="utf-8")

from api import scraper_ai  # noqa: E402
from api import scraper_service  # noqa: E402

SELETORES = (
    "[class*='price__numbers']::text",
    "[class*='price__numbers']",
    "[class*='price']::text",
    "[class*='price']",
    "[itemprop='price']::attr(content)",
)


def mostrar_no(no: Any, indice: int) -> None:
    print(f"\n--- item #{indice}")
    for seletor in SELETORES:
        try:
            valores = [str(v) for v in no.css(seletor).getall()][:3]
        except Exception as exc:  # noqa: BLE001
            print(f"  {seletor:42} EXCEÇÃO {type(exc).__name__}: {str(exc)[:80]}")
            continue
        aceites = [scraper_ai._parece_preco(v) for v in valores]
        resumo = " | ".join(f"{v[:34]!r}={ok}" for v, ok in zip(valores, aceites))
        print(f"  {seletor:42} {resumo}")
    try:
        elementos = no.css(scraper_ai._ELEMENTOS_BUSCA)[:400]
        print(f"  _ELEMENTOS_BUSCA: {len(elementos)} elementos")
    except Exception as exc:  # noqa: BLE001
        print(f"  _ELEMENTOS_BUSCA: EXCEÇÃO {type(exc).__name__}: {str(exc)[:120]}")
        return
    marcados = 0
    for elemento in elementos:
        try:
            texto = (elemento.get_all_text() or "").strip()
        except Exception:  # noqa: BLE001
            continue
        if scraper_ai._parece_preco(texto):
            marcados += 1
            if marcados <= 4:
                print(f"    aceite por get_all_text: {scraper_ai._selector_do_no(elemento)!r} → {texto[:40]!r}")
    print(f"  elementos com preço (get_all_text): {marcados}")


def principal() -> int:
    parser = argparse.ArgumentParser(description="Diagnóstico do preço num item.")
    parser.add_argument("url")
    parser.add_argument("--fetcher", default="dynamic")
    parser.add_argument("--itens", type=int, default=2)
    args = parser.parse_args()

    with scraper_service._open_session(args.fetcher, {}) as session:
        page = scraper_service._session_fetch(session, args.fetcher, args.url, {})
    if page is None:
        print("sem página")
        return 1

    analise = scraper_ai.analyze_products(page, limit=4)
    print("candidatos (produtos):", [(c["selector"], c["count"], c.get("price_ratio")) for c in analise])
    if not analise:
        return 1
    seletor = analise[0]["selector"]
    nos: List[Any] = list(page.css(seletor))
    print(f"lista: {seletor} · {len(nos)} itens")

    for indice in range(min(args.itens, len(nos))):
        mostrar_no(nos[indice], indice)

    print("\n--- resultado do extrator")
    heuristica = scraper_ai.product_heuristic_definition(args.url, page, analise)
    for chave, valor in (heuristica.get("campos") or {}).items():
        print(f"  {chave:15} {valor.get('selector') if isinstance(valor, dict) else valor}")
    print("  atributo:", scraper_ai._preco_por_atributo(nos))
    return 0


if __name__ == "__main__":
    sys.exit(principal())
