"""Cria os benchmarks reais das lojas (sonda → estudo → recolha → site).

Para cada loja: sonda a página (com a IA a propor os seletores), guarda os
seletores que a sonda validou, junta as lojas que responderam no estudo, recolhe
os preços e — se houver produtos em duas ou mais lojas — publica a página pública.

Uso (dentro do container)::

    docker exec finance-llm-backend python /app/logs/_criar_recolhas_lojas.py
    docker exec finance-llm-backend python /app/logs/_criar_recolhas_lojas.py --estudo portateis --sem-ia
    docker exec finance-llm-backend python /app/logs/_criar_recolhas_lojas.py --so-sondar
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List

import httpx

BASE = "http://127.0.0.1:8000"

#: Lojas a sondar: endereço da **categoria** e fetcher necessário. O `http` chega
#: para catálogos simples; os sites de retalho exigem browser (`dynamic`) ou
#: browser furtivo (`stealth`) porque respondem 403 a um pedido simples.
LOJAS: Dict[str, List[Dict[str, str]]] = {
    "portateis": [
        {
            "id": "worten",
            "name": "Worten",
            "url": "https://www.worten.pt/informatica-e-acessorios/computadores",
            "fetcher": "dynamic",
        },
        {
            "id": "fnac",
            "name": "Fnac",
            "url": "https://www.fnac.pt/Computadores-Portateis/Computadores-Portateis/cN32208",
            "fetcher": "stealth",
        },
        {
            "id": "darty",
            "name": "Darty",
            "url": "https://www.darty.com/nav/achat/informatique/ordinateur_portable-portable/index.html",
            "fetcher": "stealth",
        },
        {
            "id": "pcdiga",
            "name": "PCDiga",
            "url": "https://www.pcdiga.com/portateis",
            "fetcher": "dynamic",
        },
        {
            "id": "radiopopular",
            "name": "Radio Popular",
            "url": "https://www.radiopopular.pt/produtos/informatica/portateis/",
            "fetcher": "dynamic",
        },
    ]
}


def _cliente() -> httpx.Client:
    from api import auth_service

    utilizadores = auth_service.list_users(1) or [{}]
    token = auth_service.create_session(utilizadores[0]).get("token", "")
    return httpx.Client(base_url=BASE, timeout=900, headers={"Authorization": f"Bearer {token}"})


def sondar(cliente: httpx.Client, loja: Dict[str, str], *, use_ai: bool, hint: str) -> Dict[str, Any]:
    print(f"\n--- sonda: {loja['name']} ({loja['fetcher']}) · {loja['url']}")
    resposta = cliente.post(
        "/benchmarks/sonda",
        json={
            "url": loja["url"],
            "fetcher": loja["fetcher"],
            "use_ai": use_ai,
            "hint": hint,
            "nome_loja": loja["name"],
        },
    )
    if resposta.status_code >= 400:
        detalhe = ""
        try:
            detalhe = str(resposta.json().get("detail"))
        except Exception:  # noqa: BLE001
            detalhe = resposta.text[:200]
        print(f"    falhou (HTTP {resposta.status_code}): {detalhe[:200]}")
        return {"ok": False, "erro": detalhe}
    dados = resposta.json()
    print(
        f"    ok={dados.get('ok')} · origem={dados.get('origem')} · lista="
        f"{((dados.get('loja_sugerida') or {}).get('scraper') or {}).get('list', {}).get('selector')}"
    )
    print(f"    campos: {', '.join(dados.get('campos') or []) or '—'}")
    print(f"    mapa: {json.dumps(dados.get('field_map') or {}, ensure_ascii=False)}")
    for aviso in dados.get("avisos") or []:
        print(f"    aviso: {str(aviso)[:180]}")
    completos = 0
    for oferta in (dados.get("amostra") or [])[:4]:
        if oferta.get("price") and oferta.get("image"):
            completos += 1
        print(
            f"      · {str(oferta.get('product_name'))[:46]:46} {oferta.get('price')} {oferta.get('currency')} "
            f"| imagem={'sim' if oferta.get('image') else 'não'} | descrição={'sim' if oferta.get('description') else 'não'}"
        )
    print(f"    → {completos} de {len(dados.get('amostra') or [])} ofertas completas")
    return dados


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Recolhas reais das lojas a partir da sonda.")
    parser.add_argument("--estudo", default="portateis", help="Conjunto de lojas (portateis)")
    parser.add_argument("--slug", default="", help="Slug do benchmark (por omissão: <estudo>-lojas)")
    parser.add_argument("--sem-ia", action="store_true", help="Sondar só com a análise determinística")
    parser.add_argument("--so-sondar", action="store_true", help="Sondar e parar (não cria nem recolhe)")
    parser.add_argument("--limite", type=int, default=120, help="Máximo de ofertas por loja")
    args = parser.parse_args()

    lojas = LOJAS.get(args.estudo)
    if not lojas:
        print(f"estudo desconhecido: {args.estudo} (disponíveis: {', '.join(LOJAS)})")
        return 2

    slug = args.slug or f"{args.estudo}-lojas"
    cliente = _cliente()
    hint = f"{args.estudo} — produtos com preço, imagem e descrição"

    sondagens: Dict[str, Dict[str, Any]] = {}
    for loja in lojas:
        sondagens[loja["id"]] = sondar(cliente, loja, use_ai=not args.sem_ia, hint=hint)

    prontas = [
        loja
        for loja in lojas
        if (sondagens[loja["id"]].get("loja_sugerida") or {}).get("scraper")
        and sondagens[loja["id"]].get("amostra")
    ]
    print(f"\nlojas com seletores validados: {len(prontas)}/{len(lojas)} → {[l['name'] for l in prontas]}")
    if args.so_sondar or not prontas:
        return 0 if prontas else 1

    mapa: Dict[str, str] = {}
    for loja in prontas:
        for chave, campo in (sondagens[loja["id"]].get("field_map") or {}).items():
            mapa.setdefault(chave, str(campo))

    definicao = {
        "name": f"{args.estudo.capitalize()} — comparação entre lojas".replace("Portateis", "Portáteis"),
        "slug": slug,
        "description": "O mesmo produto comparado entre lojas, com preço, imagem e descrição recolhidos de cada site.",
        "category": args.estudo.capitalize(),
        "currency": "EUR",
        "match_on": "nome",
        "field_map": mapa,
        "stores": [
            {
                "id": loja["id"],
                "name": loja["name"],
                "url": loja["url"],
                "enabled": True,
                "scraper": (sondagens[loja["id"]].get("loja_sugerida") or {}).get("scraper"),
            }
            for loja in prontas
        ],
    }
    print(f"\nfield_map do estudo: {json.dumps(mapa, ensure_ascii=False)}")

    existente = cliente.get(f"/benchmarks/{slug}")
    if existente.status_code == 200:
        resposta = cliente.put(f"/benchmarks/{slug}", json=definicao)
        print(f"estudo atualizado: HTTP {resposta.status_code}")
    else:
        resposta = cliente.post("/benchmarks", json=definicao)
        print(f"estudo criado: HTTP {resposta.status_code}")
    if resposta.status_code >= 400:
        print(f"  erro: {resposta.text[:300]}")
        return 1

    recolha = cliente.post(f"/benchmarks/{slug}/recolher", json={"limite_por_loja": args.limite})
    corpo = recolha.json() if recolha.status_code < 400 else {"error": recolha.text[:200]}
    print(f"recolha: HTTP {recolha.status_code} · ofertas={corpo.get('offers')} · indexadas={corpo.get('indexed')}")
    for loja in corpo.get("stores") or []:
        print(
            f"  {str(loja.get('store_name'))[:18]:18} estado={loja.get('status')} itens={loja.get('items')} "
            f"ofertas={loja.get('ofertas')} indexadas={loja.get('indexadas')} erro={str(loja.get('error'))[:90]}"
        )

    estudo = cliente.get(f"/benchmarks/{slug}/analise").json()
    kpis = estudo.get("kpis") or {}
    print(f"KPIs: {json.dumps(kpis, ensure_ascii=False)}")
    for linha in estudo.get("stores") or []:
        print(
            f"  {str(linha.get('store_name'))[:18]:18} ofertas={linha.get('ofertas')} produtos={linha.get('produtos')} "
            f"média={linha.get('preco_medio')} índice={linha.get('indice_preco')}"
        )

    if int(kpis.get("offers") or 0) == 0:
        print("sem ofertas: não há nada para publicar.")
        return 1

    publicacao = cliente.post(f"/benchmarks/{slug}/publicar")
    if publicacao.status_code < 400:
        dados = publicacao.json()
        print(f"publicado em {dados.get('url')} (pesquisa: {dados.get('search_url')})")
        alvo = f"/site/benchmarks/{slug}/pesquisa"
        pagina = cliente.get(alvo, follow_redirects=True)
        print(f"página de pesquisa: HTTP {pagina.status_code} · {len(pagina.text)} bytes · miniaturas={'class=\"thumb\"' in pagina.text}")
    else:
        print(f"publicação falhou: HTTP {publicacao.status_code} · {publicacao.text[:200]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
