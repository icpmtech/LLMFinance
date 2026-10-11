"""Sondagem de lojas para benchmarks de produtos (corre **dentro** do container).

Para cada loja candidata:

1. lê o `robots.txt` e diz se o caminho está **permitido** a um agente genérico
   (não vale a pena desenhar uma recolha para um caminho proibido);
2. pede a página de listagem e mede o que volta (estado, tamanho, nº de
   seletores candidatos que casam);
3. corre o motor de recolha a sério (`scraper_service.preview_source`) com a
   definição proposta e mostra os primeiros itens extraídos.

Uso::

    docker exec finance-llm-backend python /app/logs/_sondar_lojas_benchmarks.py
    docker exec finance-llm-backend python /app/logs/_sondar_lojas_benchmarks.py --loja worten
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.robotparser
from typing import Any, Dict, List
from urllib.parse import urlparse

import httpx
from lxml import html as lxml_html

sys.stdout.reconfigure(encoding="utf-8")

from api import scraper_service  # noqa: E402

AGENTE = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"

#: Lojas candidatas: nome, listagem, e os seletores a testar (do mais provável ao
#: mais genérico). Os `fields` são a proposta inicial; a sondagem confirma-os.
CANDIDATAS: List[Dict[str, Any]] = [
    {
        "id": "worten",
        "nome": "Worten",
        "url": "https://www.worten.pt/informatica-e-acessorios/computadores/portateis",
        "cartao": ["article.product-grid-item", "[data-testid='product-card']", "div.product-card", "li.product-grid-item"],
        "campos": {
            "titulo": ["h3", "[data-testid='product-name']", "a[title]"],
            "preco": [".w-product__price__current", "[data-testid='price']", ".price"],
            "url": ["a[href]"],
            "imagem": ["img[src]", "img[data-src]"],
        },
    },
    {
        "id": "fnac",
        "nome": "Fnac",
        "url": "https://www.fnac.pt/Computadores-Portateis/Computadores-Portateis/cN32208",
        "cartao": [".Article-item", "article.Article", "li.Article-item", "[data-testid='product-card']"],
        "campos": {
            "titulo": [".Article-title", "a[title]", "h3"],
            "preco": [".userPrice", ".Article-price", "[data-testid='price']"],
            "url": ["a[href]"],
            "imagem": ["img[src]", "img[data-src]"],
        },
    },
    {
        "id": "fnac-es",
        "nome": "Fnac Espanha",
        "url": "https://www.fnac.es/Ordenadores-portatiles/Ordenadores-portatiles/na48",
        "cartao": [".Article-item", "article.Article", "li.Article-item"],
        "campos": {
            "titulo": [".Article-title", "a[title]"],
            "preco": [".userPrice", ".Article-price"],
            "url": ["a[href]"],
            "imagem": ["img[src]"],
        },
    },
    {
        "id": "darty",
        "nome": "Darty (França)",
        "url": "https://www.darty.com/nav/achat/informatique/ordinateur_portable-portable/index.html",
        "cartao": ["div.product-list__product", "article.product", "div.pdp-card", "li.product-list__item"],
        "campos": {
            "titulo": [".product-list__product-name", "h2", "a[title]"],
            "preco": [".product-list__price", ".price", "[data-testid='price']"],
            "url": ["a[href]"],
            "imagem": ["img[src]", "img[data-src]"],
        },
    },
    {
        "id": "pcdiga",
        "nome": "PCDiga",
        "url": "https://www.pcdiga.com/portateis",
        "cartao": ["li.item.product.product-item", "div.product-item", "article.product"],
        "campos": {
            "titulo": [".product-item-link", "a.product-item-link", "h3"],
            "preco": [".price", "[data-price-type='finalPrice'] .price"],
            "url": ["a.product-item-link"],
            "imagem": ["img.product-image-photo"],
        },
    },
    {
        "id": "radiopopular",
        "nome": "Radio Popular",
        "url": "https://www.radiopopular.pt/categoria/produtos/informatica/portateis/",
        "cartao": [".product-item", "li.product", "article.product-card"],
        "campos": {
            "titulo": [".product-item__title", "h2", "h3"],
            "preco": [".product-item__price", ".price"],
            "url": ["a[href]"],
            "imagem": ["img[src]"],
        },
    },
    {
        "id": "mediamarkt-pt",
        "nome": "MediaMarkt Portugal",
        "url": "https://www.mediamarkt.pt/pt/cat/portateis-1736",
        "cartao": ["div.product-wrapper", "[data-test='mms-product-card']", "article"],
        "campos": {
            "titulo": ["[data-test='mms-product-title']", "h3", "a[title]"],
            "preco": ["[data-test='mms-price']", ".price"],
            "url": ["a[href]"],
            "imagem": ["img[src]"],
        },
    },
]


def permitido(url: str, agente: str = "*") -> str:
    """`robots.txt` do site: «permitido», «proibido» ou «desconhecido»."""
    partes = urlparse(url)
    robots = f"{partes.scheme}://{partes.netloc}/robots.txt"
    try:
        resposta = httpx.get(robots, timeout=20, headers={"User-Agent": AGENTE}, follow_redirects=True)
    except Exception as exc:  # noqa: BLE001
        return f"desconhecido ({type(exc).__name__})"
    if resposta.status_code >= 400:
        return f"sem robots.txt (HTTP {resposta.status_code})"
    rp = urllib.robotparser.RobotFileParser()
    rp.parse(resposta.text.splitlines())
    return "permitido" if rp.can_fetch(agente, url) else "PROIBIDO"


def inspecionar(loja: Dict[str, Any]) -> None:
    print(f"\n=== {loja['nome']} ({loja['id']})")
    print(f"    url: {loja['url']}")
    print(f"    robots: {permitido(loja['url'], 'IQOSBenchmarkBot/1.0')} (agente próprio) · "
          f"{permitido(loja['url'], '*')} (genérico)")

    try:
        resposta = httpx.get(loja["url"], timeout=45, headers={"User-Agent": AGENTE}, follow_redirects=True)
    except Exception as exc:  # noqa: BLE001
        print(f"    pedido falhou: {type(exc).__name__}: {exc}")
        return
    print(f"    HTTP {resposta.status_code} · {len(resposta.text)} bytes · {resposta.headers.get('content-type', '')[:40]}")
    if resposta.status_code != 200:
        return

    documento = lxml_html.fromstring(resposta.text)
    for seletor in loja["cartao"]:
        try:
            nos = documento.cssselect(seletor)
        except Exception:  # noqa: BLE001
            continue
        if nos:
            print(f"    cartões «{seletor}»: {len(nos)}")
            exemplo = nos[0]
            for campo, candidatos in loja["campos"].items():
                for candidato in candidatos:
                    alvo = exemplo.cssselect(candidato)
                    if alvo:
                        elemento = alvo[0]
                        valor = (elemento.text_content() or "").strip()[:70]
                        if campo == "url" or campo == "imagem":
                            valor = elemento.get("href") or elemento.get("src") or elemento.get("data-src") or ""
                        print(f"        {campo:9} «{candidato}» → {valor[:80]}")
                        break
            break
    else:
        print("    nenhum seletor de cartão casou (página provavelmente protegida ou markup diferente)")

    # Recolha a sério, pelo motor do módulo (dry-run, nada é guardado).
    payload = {
        "name": f"Sonda {loja['nome']}",
        "url": loja["url"],
        "fetcher": "http",
        "list": {"selector": loja["cartao"][0], "type": "css"},
        "fields": [
            {"name": "titulo", "selector": f"{loja['cartao'][0]} {loja['campos']['titulo'][0]}::text"},
            {"name": "preco", "selector": f"{loja['cartao'][0]} {loja['campos']['preco'][0]}::text"},
        ],
        "pagination": {"max_pages": 1},
        "respect_robots": True,
        "id_fields": [],
    }
    try:
        resultado = scraper_service.preview_source(payload, limit=3, max_pages=1)
        itens = resultado.get("items") or []
        print(f"    pré-visualização: {len(itens)} item(ns) · erros: {resultado.get('errors')}")
        for item in itens[:3]:
            print(f"      · {str(item.get('title'))[:60]} | {str((item.get('data') or {}).get('preco'))[:20]}")
    except Exception as exc:  # noqa: BLE001
        print(f"    pré-visualização falhou: {type(exc).__name__}: {exc}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Sonda lojas para os benchmarks de produtos.")
    parser.add_argument("--loja", default="", help="Só esta loja (id)")
    args = parser.parse_args()

    alvo = [c for c in CANDIDATAS if not args.loja or c["id"] == args.loja]
    print(f"a sondar {len(alvo)} loja(s)")
    for loja in alvo:
        inspecionar(loja)
    print("\nresumo:", json.dumps([c["id"] for c in alvo], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
