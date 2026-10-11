"""O que é que a definição da sonda extrai, item a item? (o valor cru)

Mostra o `data` de cada item devolvido pela definição que a heurística propôs —
é aqui que se vê se o preço sai como número, HTML ou vazio, e se o título e a
imagem vêm preenchidos. Sem isto, só se sabe que «não houve ofertas».

Uso (no contentor)::

    python -u /app/logs/_diagnosticar_preview_sonda.py "https://www.worten.pt/..." --fetcher dynamic
"""
from __future__ import annotations

import argparse
import json
import sys

sys.stdout.reconfigure(encoding="utf-8")

from api import scraper_ai  # noqa: E402
from api import scraper_service as scraper  # noqa: E402

BASE = {
    "url": "",
    "name": "sonda",
    "fetcher": "http",
    "enabled": False,
    "options": {},
    "respect_robots": True,
    "schedule": {"cron": "", "timezone": "Europe/Lisbon"},
    "tags": [],
}


def principal() -> int:
    parser = argparse.ArgumentParser(description="Ver os valores extraídos pela definição.")
    parser.add_argument("url")
    parser.add_argument("--fetcher", default="dynamic")
    parser.add_argument("--itens", type=int, default=3)
    args = parser.parse_args()

    with scraper._open_session(args.fetcher, {}) as session:
        page = scraper._session_fetch(session, args.fetcher, args.url, {})
    if page is None:
        print("sem página")
        return 1

    analise = scraper_ai.analyze_products(page, limit=4)
    heuristica = scraper_ai.product_heuristic_definition(args.url, page, analise)
    definicao = {**BASE, **heuristica}
    definicao.pop("campos", None)

    print("lista:", (definicao.get("list") or {}).get("selector"))
    print("campos:")
    for campo in definicao.get("fields") or []:
        print(f"  {campo['name']:15} {campo['selector']:48} text_only={campo.get('text_only')}")

    previsao = scraper.preview_source(definicao, limit=args.itens, max_pages=1)
    print(f"\npreview: ok={previsao.get('ok')} total={previsao.get('total')} itens={len(previsao.get('items') or [])}")
    if previsao.get("error"):
        print("  erro:", str(previsao["error"])[:300])
    validado = scraper_ai._validate(definicao, max_pages=1)
    print(
        f"_validate: ok={validado.get('ok')} total={validado.get('total')} "
        f"itens={len(validado.get('items') or [])} erro={str(validado.get('error'))[:120]}"
    )
    if not (previsao.get("items") or validado.get("items")):
        print("  (nenhum item: a lista casa?)", len(page.css((definicao.get('list') or {}).get('selector') or "body")))
    itens_amostra = list(previsao.get("items") or []) + [i for i in (validado.get("items") or []) if i not in (previsao.get("items") or [])]
    for indice, item in enumerate(itens_amostra[: args.itens]):
        print(f"\n--- item #{indice}")
        print(f"  url: {item.get('url')}")
        for chave, valor in (item.get("data") or {}).items():
            texto = str(valor)
            print(f"  {chave:15} {texto[:120]!r}")
        oferta = None
        try:
            oferta = __import__("api.benchmarks_service", fromlist=["x"]).normalizar_oferta(
                item,
                loja={"id": "sonda", "name": "sonda", "url": args.url},
                benchmark={"slug": "sonda", "match_on": "nome", "currency": "EUR", "field_map": heuristica and {
                    "price": "preco", "price_original": "preco_antigo", "product_name": "titulo",
                    "description": "descricao", "url": "url", "image": "imagem",
                }},
            )
        except Exception as exc:  # noqa: BLE001
            print("  normalizar_oferta falhou:", type(exc).__name__, exc)
        print("  oferta normalizada:", json.dumps(oferta, ensure_ascii=False)[:300] if oferta else "None")
    return 0


if __name__ == "__main__":
    sys.exit(principal())
