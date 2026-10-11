"""Testa as lojas protegidas com o fetcher *stealth* (browser real) do módulo.

O pedido HTTP simples devolve 403 em Worten, Fnac, Darty e PCDiga (proteção
anti-bot). Aqui repete-se a sondagem com os fetchers do módulo de recolha
(`dynamic` e `stealth`), que usam um browser a sério, e mostra o que sai.

Uso::

    docker exec finance-llm-backend python /app/logs/_sondar_lojas_stealth.py worten
"""
from __future__ import annotations

import argparse
import sys
from typing import Any, Dict, List

sys.stdout.reconfigure(encoding="utf-8")

from api import scraper_service  # noqa: E402

LOJAS: Dict[str, Dict[str, Any]] = {
    "worten": {
        "nome": "Worten",
        "url": "https://www.worten.pt/informatica-e-acessorios/computadores/portateis",
        "cartao": ["article.product-grid-item", "[data-testid='product-card']", "div.product-grid-item", "article"],
        "titulo": ["h3", "[data-testid='product-name']", "a[title]"],
        "preco": [".w-product__price__current", "[data-testid='price']", ".price", "[class*='price']"],
    },
    "fnac": {
        "nome": "Fnac",
        "url": "https://www.fnac.pt/Computadores-Portateis/Computadores-Portateis/cN32208",
        "cartao": [".Article-item", "article.Article", "li.Article-item", "article"],
        "titulo": [".Article-title", "a[title]", "h3"],
        "preco": [".userPrice", ".Article-price", "[class*='price']"],
    },
    "darty": {
        "nome": "Darty (França)",
        "url": "https://www.darty.com/nav/achat/informatique/ordinateur_portable-portable/index.html",
        "cartao": ["div.product-list__product", "article.product", "div.pdp-card", "article"],
        "titulo": [".product-list__product-name", "h2", "a[title]"],
        "preco": [".product-list__price", ".price", "[class*='price']"],
    },
    "pcdiga": {
        "nome": "PCDiga",
        "url": "https://www.pcdiga.com/portateis",
        "cartao": ["li.item.product.product-item", "div.product-item", "article.product", "article"],
        "titulo": [".product-item-link", "h3", "a[title]"],
        "preco": [".price", "[data-price-type='finalPrice'] .price", "[class*='price']"],
    },
}


def tentar(chave: str, fetcher: str, seletor_cartao: str, seletor_titulo: str, seletor_preco: str) -> int:
    loja = LOJAS[chave]
    payload = {
        "name": f"Sonda stealth {loja['nome']}",
        "url": loja["url"],
        "fetcher": fetcher,
        "list": {"selector": seletor_cartao, "type": "css"},
        "fields": [
            {"name": "titulo", "selector": f"{seletor_cartao} {seletor_titulo}::text", "max_length": 300},
            {"name": "preco", "selector": f"{seletor_cartao} {seletor_preco}::text", "max_length": 40},
        ],
        "options": {"timeout": 60, "headless": True},
        "pagination": {"max_pages": 1},
        "respect_robots": True,
        "id_fields": [],
    }
    try:
        resultado = scraper_service.preview_source(payload, limit=3, max_pages=1)
    except Exception as exc:  # noqa: BLE001
        print(f"    {fetcher:9} ERRO {type(exc).__name__}: {str(exc)[:120]}")
        return 0
    itens = resultado.get("items") or []
    erros = resultado.get("errors") or []
    print(f"    {fetcher:9} itens={len(itens)} páginas={resultado.get('pages')} erros={erros[:1]}")
    for item in itens[:3]:
        dados = item.get("data") or {}
        print(f"        · {str(item.get('title'))[:58]:58} | {str(dados.get('preco'))[:18]}")
    return len(itens)


def main() -> int:
    parser = argparse.ArgumentParser(description="Sonda lojas protegidas com browser real.")
    parser.add_argument("loja", nargs="?", default="", help="Id da loja (worten, fnac, darty, pcdiga)")
    parser.add_argument("--fetchers", default="dynamic,stealth", help="Fetchers a testar, por ordem")
    args = parser.parse_args()

    chaves = [args.loja] if args.loja else list(LOJAS)
    fetchers: List[str] = [f.strip() for f in args.fetchers.split(",") if f.strip()]
    for chave in chaves:
        loja = LOJAS[chave]
        print(f"\n=== {loja['nome']} · {loja['url']}")
        for fetcher in fetchers:
            encontrou = False
            # Testa combinações de seletores até uma delas devolver itens: cada
            # tentativa abre um browser, por isso não vale a pena varrer todas.
            for cartao in loja["cartao"][:2]:
                for titulo in loja["titulo"][:2]:
                    for preco in loja["preco"][:2]:
                        print(f"  {fetcher}: cartão «{cartao}» · título «{titulo}» · preço «{preco}»")
                        itens = tentar(chave, fetcher, cartao, titulo, preco)
                        if itens:
                            encontrou = True
                            break
                    if encontrou:
                        break
                if encontrou:
                    break
            if not encontrou:
                print(f"  {fetcher}: nenhuma combinação devolveu itens")
    return 0


if __name__ == "__main__":
    sys.exit(main())
