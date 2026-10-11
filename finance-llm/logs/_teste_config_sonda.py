"""Testa a configuração do módulo e a sonda **dentro de um estudo** (API).

Confirma o que a UI passou a usar:

1. `GET/PUT /benchmarks/configuracao` — opções guardadas (fetcher, IA, limites);
2. `GET /benchmarks/lojas` — catálogo de lojas conhecidas;
3. `POST /benchmarks/{slug}/sonda` — sonda que **guarda** os seletores na loja do
   estudo (é o que permite corrigir uma loja a partir do painel).

Uso::

    docker exec finance-llm-backend python -u /app/logs/_teste_config_sonda.py
    docker exec finance-llm-backend python -u /app/logs/_teste_config_sonda.py --slug portateis-lojas --url "https://books.toscrape.com/catalogue/page-1.html" --fetcher http
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict

import httpx

BASE = "http://127.0.0.1:8000"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Configuração + sonda dentro de um estudo.")
    parser.add_argument("--slug", default="", help="Estudo de destino (vazio: só testa a configuração)")
    parser.add_argument("--url", default="https://books.toscrape.com/catalogue/page-1.html")
    parser.add_argument("--fetcher", default="http")
    parser.add_argument("--sem-ia", action="store_true")
    args = parser.parse_args()

    from api import auth_service

    utilizadores = auth_service.list_users(1) or [{}]
    token = auth_service.create_session(utilizadores[0]).get("token", "")
    cliente = httpx.Client(base_url=BASE, timeout=600, headers={"Authorization": f"Bearer {token}"})

    config = cliente.get("/benchmarks/configuracao")
    print(f"GET  /benchmarks/configuracao  HTTP {config.status_code}")
    if config.status_code == 200:
        corpo = config.json()
        print("   config:", json.dumps(corpo.get("configuracao"), ensure_ascii=False))
        print("   lojas:", len(corpo.get("lojas") or []), "| fetchers:", [f["id"] for f in corpo.get("fetchers") or []])
        print("   fornecedores com chave:", [f["id"] for f in corpo.get("fornecedores") or [] if f.get("tem_chave")])

    # Guardar (e reler) uma alteração pequena: prova que a persistência funciona.
    guardar = cliente.put("/benchmarks/configuracao", json={"pausa_segundos": 2.5, "hint": "produtos com preço, imagem e descrição"})
    print(f"PUT  /benchmarks/configuracao  HTTP {guardar.status_code} · pausa={guardar.json().get('configuracao', {}).get('pausa_segundos') if guardar.status_code < 400 else guardar.text[:120]}")
    relido = cliente.get("/benchmarks/configuracao").json().get("configuracao") or {}
    print(f"   relido: pausa={relido.get('pausa_segundos')} · fetcher={relido.get('fetcher')} · use_ai={relido.get('use_ai')}")

    lojas = cliente.get("/benchmarks/lojas")
    print(f"GET  /benchmarks/lojas  HTTP {lojas.status_code} · {len(lojas.json().get('items') or [])} loja(s)")

    if not args.slug:
        return 0

    antes = cliente.get(f"/benchmarks/{args.slug}").json()
    lojas_antes = len(antes.get("stores") or [])
    resposta = cliente.post(
        f"/benchmarks/{args.slug}/sonda",
        json={
            "url": args.url,
            "fetcher": args.fetcher,
            "use_ai": not args.sem_ia,
            "loja_nome": "Sonda de teste",
            "guardar": True,
        },
    )
    print(f"\nPOST /benchmarks/{args.slug}/sonda  HTTP {resposta.status_code}")
    if resposta.status_code >= 400:
        print("   erro:", str(resposta.json().get("detail"))[:220])
        return 1
    dados: Dict[str, Any] = resposta.json()
    print(f"   ok={dados.get('ok')} · origem={dados.get('origem')} · amostra={len(dados.get('amostra') or [])}")
    print(f"   loja guardada: {json.dumps(dados.get('loja_guardada'), ensure_ascii=False)}")
    depois = cliente.get(f"/benchmarks/{args.slug}").json()
    lojas_depois = len(depois.get("stores") or [])
    print(f"   lojas no estudo: {lojas_antes} → {lojas_depois}")
    nomes = [loja.get("name") for loja in depois.get("stores") or []]
    print(f"   lojas: {nomes}")
    for loja in depois.get("stores") or []:
        if loja.get("id") == (dados.get("loja_guardada") or {}).get("id"):
            scraper = loja.get("scraper") or {}
            print(f"   seletores guardados: lista={((scraper.get('list') or {}).get('selector'))} · campos={len(scraper.get('fields') or [])}")

    # Limpeza: a loja de teste não deve ficar no estudo.
    if dados.get("loja_guardada"):
        limpo = [l for l in depois.get("stores") or [] if l.get("id") != dados["loja_guardada"]["id"]]
        if limpo:
            cliente.put(f"/benchmarks/{args.slug}", json={**depois, "stores": limpo})
            print(f"   loja de teste removida (ficam {len(limpo)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
