"""Teste da **sonda de produtos** pela API (corre dentro do container).

Sonda páginas de loja pelo mesmo caminho que a interface usa
(`POST /benchmarks/sonda`): análise determinística + proposta da IA (opcional) e,
no fim, a amostra já normalizada — preço, imagem e descrição.

Uso::

    docker exec finance-llm-backend python /app/logs/_teste_sonda_produtos_e2e.py
    docker exec finance-llm-backend python /app/logs/_teste_sonda_produtos_e2e.py --lojas worten,fnac,darty --sem-ia
    docker exec finance-llm-backend python /app/logs/_teste_sonda_produtos_e2e.py --url https://... --fetcher stealth
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List

import httpx

BASE = "http://127.0.0.1:8000"

#: Alvos de ensaio: o catálogo público de treino (sem browser) e as lojas pedidas.
LOJAS: Dict[str, Dict[str, str]] = {
    "demo": {
        "url": "https://books.toscrape.com/catalogue/page-1.html",
        "fetcher": "http",
    },
    "worten": {
        "url": "https://www.worten.pt/informatica-e-acessorios/computadores",
        "fetcher": "dynamic",
    },
    "fnac": {
        "url": "https://www.fnac.pt/Computadores-Portateis/Computadores-Portateis/cN32208",
        "fetcher": "stealth",
    },
    "darty": {
        "url": "https://www.darty.com/nav/achat/informatique/ordinateur_portable-portable/index.html",
        "fetcher": "stealth",
    },
}


def mostrar(loja: str, resultado: Dict[str, Any], fetcher: str) -> bool:
    amostra = resultado.get("amostra") or []
    print(f"\n=== {loja} · fetcher={fetcher} · ok={resultado.get('ok')} · origem={resultado.get('origem')}")
    if resultado.get("erro"):
        print(f"  erro: {str(resultado['erro'])[:200]}")
    for aviso in resultado.get("avisos") or []:
        print(f"  aviso: {str(aviso)[:200]}")
    robots = resultado.get("robots") or {}
    print(f"  robots: {robots.get('detalhe')}")
    if resultado.get("ai"):
        print(f"  ia: {json.dumps(resultado['ai'], ensure_ascii=False)}")
    print(f"  campos: {', '.join(resultado.get('campos') or []) or '—'}")
    print(f"  mapa: {json.dumps(resultado.get('field_map') or {}, ensure_ascii=False)}")
    lista = ((resultado.get("loja_sugerida") or {}).get("scraper") or {}).get("list") or {}
    print(f"  lista: {lista.get('selector')}")

    completos = 0
    for oferta in amostra[:5]:
        preco = oferta.get("price")
        tem_imagem = bool(oferta.get("image"))
        tem_descricao = bool(oferta.get("description"))
        completos += 1 if (preco and tem_imagem) else 0
        print(
            f"    · {str(oferta.get('product_name'))[:52]:52} | {preco} {oferta.get('currency')} "
            f"| imagem={'sim' if tem_imagem else 'não'} | descrição={'sim' if tem_descricao else 'não'}"
        )
        if tem_descricao:
            print(f"      {str(oferta['description'])[:110]}")
    print(f"  → {completos}/{len(amostra)} ofertas com preço e imagem")
    return bool(resultado.get("ok")) and completos > 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Sonda de produtos (via API).")
    parser.add_argument("--lojas", default="demo", help="Ids separados por vírgula: demo,worten,fnac,darty")
    parser.add_argument("--url", default="", help="Endereço a sondar (em vez das lojas conhecidas)")
    parser.add_argument("--fetcher", default="", help="Força o fetcher (http|dynamic|stealth)")
    parser.add_argument("--sem-ia", action="store_true", help="Sem proposta da IA (só análise determinística)")
    args = parser.parse_args()

    from api import auth_service

    utilizadores = auth_service.list_users(1) or [{}]
    token = auth_service.create_session(utilizadores[0]).get("token", "")
    cliente = httpx.Client(base_url=BASE, timeout=600, headers={"Authorization": f"Bearer {token}"})

    alvos: List[Dict[str, str]] = []
    if args.url:
        alvos.append({"nome": args.url.split("/")[2], "url": args.url, "fetcher": args.fetcher or "http"})
    for chave in [c.strip() for c in args.lojas.split(",") if c.strip()]:
        alvo = LOJAS.get(chave)
        if not alvo:
            print(f"  (loja desconhecida: {chave})")
            continue
        alvos.append(
            {
                "nome": chave,
                "url": alvo["url"],
                "fetcher": args.fetcher or alvo["fetcher"],
            }
        )

    bons = 0
    for alvo in alvos:
        resposta = cliente.post(
            "/benchmarks/sonda",
            json={
                "url": alvo["url"],
                "fetcher": alvo["fetcher"],
                "use_ai": not args.sem_ia,
                "hint": "produtos com preço, imagem e descrição",
                "nome_loja": alvo["nome"],
            },
        )
        print(f"\nSonda HTTP {resposta.status_code} · {alvo['url']}")
        if resposta.status_code >= 400:
            detalhe = ""
            try:
                detalhe = str(resposta.json().get("detail"))
            except Exception:  # noqa: BLE001
                detalhe = resposta.text[:200]
            print(f"  falhou: {detalhe[:220]}")
            continue
        if mostrar(alvo["nome"], resposta.json(), alvo["fetcher"]):
            bons += 1

    print(f"\nresumo: {bons}/{len(alvos)} páginas com produtos extraídos (preço + imagem)")
    return 0 if bons else 1


if __name__ == "__main__":
    sys.exit(main())
