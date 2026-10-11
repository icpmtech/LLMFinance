"""O que devolve cada campo, no item, campo a campo? (isolado)

Chama `scraper_service._value_from` para cada campo da definição proposta pela
heurística, com o **primeiro item** da lista. É o teste que separa «o seletor
está errado» de «a extração devolve vazio».

Uso::

    python -u /app/logs/_diagnosticar_campo_a_campo.py "https://www.worten.pt/..." --fetcher dynamic
"""
from __future__ import annotations

import argparse
import sys

sys.stdout.reconfigure(encoding="utf-8")

from api import scraper_ai  # noqa: E402
from api import scraper_service as scraper  # noqa: E402


def principal() -> int:
    parser = argparse.ArgumentParser(description="Extrair campo a campo de um item.")
    parser.add_argument("url")
    parser.add_argument("--fetcher", default="dynamic")
    args = parser.parse_args()

    with scraper._open_session(args.fetcher, {}) as session:
        page = scraper._session_fetch(session, args.fetcher, args.url, {})

    heuristica = scraper_ai.product_heuristic_definition(args.url, page, scraper_ai.analyze_products(page, limit=4))
    seletor_lista = (heuristica.get("list") or {}).get("selector") or ""
    itens = list(page.css(seletor_lista))
    print(f"lista {seletor_lista!r}: {len(itens)} itens")
    if not itens:
        return 1
    item = itens[0]

    for campo in heuristica.get("fields") or []:
        try:
            valor = scraper._value_from(item, campo)
        except Exception as exc:  # noqa: BLE001
            valor = f"EXCEÇÃO {type(exc).__name__}: {exc}"
        print(f"  {campo['name']:14} {campo['selector']:46} → {str(valor)[:90]!r}")

    print("\ncaminho completo (como na pré-visualização):")
    base = {
        "url": args.url,
        "name": "sonda",
        "fetcher": args.fetcher,
        "enabled": False,
        "options": {},
        "respect_robots": True,
        "schedule": {"cron": "", "timezone": "Europe/Lisbon"},
        "tags": [],
    }
    definicao = {**base, **heuristica}
    definicao.pop("campos", None)
    source = scraper.normalize_source(definicao, None)
    print("  fonte normalizada: list=", (source.get("list") or {}).get("selector"), "campos=", [f["name"] for f in source.get("fields") or []])
    for campo in source.get("fields") or []:
        print(
            f"    {campo['name']:14} {str(campo.get('selector'))[:44]:44} "
            f"text_only={campo.get('text_only')} max_length={campo.get('max_length')}"
        )
    extraidos = scraper._extract_items(page, source)
    print(f"  _extract_items → {len(extraidos)} itens")
    if extraidos:
        print("    data[0]:", str(extraidos[0].get("data"))[:220])
    else:
        item_teste = itens[0]
        raw = {f["name"]: scraper._value_from(item_teste, f) for f in source.get("fields") or []}
        print("    raw do item #0:", str(raw)[:300])

    print("\ncaminho elementar:")
    for seletor in ("div.product-card__details", "[class*=name]:text", "img::attr(src)"):
        try:
            nativo = list(item.css(seletor))
            via_as_list = scraper._as_list(item.css(seletor))
            print(f"  {seletor:32} css()={len(nativo)} as_list={len(via_as_list)} tipo0={type(via_as_list[0]).__name__ if via_as_list else '-'}")
            if via_as_list:
                print(f"      valor0={str(via_as_list[0])[:70]!r}")
        except Exception as exc:  # noqa: BLE001
            print(f"  {seletor:32} EXCEÇÃO {type(exc).__name__}: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(principal())
