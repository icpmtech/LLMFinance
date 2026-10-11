"""O que ficou mesmo guardado nas ofertas? (preço, imagem, descrição)

Lê o índice do benchmark pela API e mostra, oferta a oferta, se cada campo ficou
preenchido — é a verificação de que a recolha real guardou o que a sonda prometeu
(a amostra da sonda não é prova: o que conta é o que está no índice).

Uso::

    python -u /app/logs/_verificar_ofertas_lojas.py portateis-lojas
"""
from __future__ import annotations

import argparse
import sys

import httpx

BASE = "http://127.0.0.1:8000"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Verificar as ofertas guardadas.")
    parser.add_argument("slug", nargs="?", default="portateis-lojas")
    parser.add_argument("--size", type=int, default=200)
    args = parser.parse_args()

    from api import auth_service

    utilizadores = auth_service.list_users(1) or [{}]
    token = auth_service.create_session(utilizadores[0]).get("token", "")
    cliente = httpx.Client(base_url=BASE, timeout=120, headers={"Authorization": f"Bearer {token}"})

    resposta = cliente.get(f"/benchmarks/{args.slug}/ofertas", params={"size": args.size})
    if resposta.status_code >= 400:
        print("falhou:", resposta.status_code, resposta.text[:200])
        return 1
    corpo = resposta.json()
    itens = corpo.get("items") or []
    print(f"índice: {corpo.get('index')} · total={corpo.get('total')} · mostrados={len(itens)}")
    if not itens:
        return 1

    com_preco = sum(1 for i in itens if i.get("price"))
    com_imagem = sum(1 for i in itens if i.get("image"))
    com_descricao = sum(1 for i in itens if i.get("description"))
    com_url = sum(1 for i in itens if i.get("url"))
    print(
        f"preço={com_preco}/{len(itens)} · imagem={com_imagem} · descrição={com_descricao} · ligação={com_url}"
    )
    print(f"preços: mínimo={corpo.get('stats', {}).get('preco_min')} máximo={corpo.get('stats', {}).get('preco_max')}")
    for item in itens[:4]:
        print(f"\n  {str(item.get('product_name'))[:64]}")
        print(f"    preço={item.get('price')} {item.get('currency')} · antes={item.get('price_original')} · loja={item.get('store_name')}")
        print(f"    imagem={str(item.get('image'))[:78]}")
        print(f"    descrição={str(item.get('description'))[:90]}")
        print(f"    ligação={str(item.get('url'))[:78]}")

    html = cliente.get(f"/site/benchmarks/{args.slug}/pesquisa", follow_redirects=True)
    print(f"\npágina pública: HTTP {html.status_code} · {len(html.text)} bytes")
    print("  miniaturas:", html.text.count('class="thumb"'), "· descrições:", html.text.count('class="descricao"'))
    return 0


if __name__ == "__main__":
    sys.exit(main())
