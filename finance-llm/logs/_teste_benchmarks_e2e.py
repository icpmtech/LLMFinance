"""Teste ponta-a-ponta do módulo de benchmarks (corre **dentro** do container).

Cria um benchmark de demonstração contra `books.toscrape.com` (sandbox pública
feita para treinar scraping, sem implicações de uso), recolhe os preços, confere
o índice próprio do benchmark, publica no site e verifica a página pública com
pesquisa.

Uso::

    docker exec finance-llm-backend python /app/logs/_teste_benchmarks_e2e.py
"""
from __future__ import annotations

import json
import sys

import httpx

BASE = "http://127.0.0.1:8000"
SLUG = "livros-demo"

LOJA = {
    "id": "books-toscrape",
    "name": "Books to Scrape",
    "url": "https://books.toscrape.com/",
    "enabled": True,
    "scraper": {
        "fetcher": "http",
        "list": {"selector": "article.product_pod", "type": "css"},
        "fields": [
            {"name": "titulo", "label": "Título", "selector": "h3 a::attr(title)", "type": "css"},
            {"name": "preco", "label": "Preço", "selector": "p.price_color::text", "type": "css"},
            {"name": "disponibilidade", "label": "Disponibilidade", "selector": "p.instock.availability::text", "type": "css"},
            {"name": "url", "label": "Endereço", "selector": "h3 a::attr(href)", "type": "css"},
            {"name": "imagem", "label": "Imagem", "selector": "img::attr(src)", "type": "css"},
        ],
        "pagination": {"selector": "li.next a", "type": "css", "attr": "href", "max_pages": 3},
        "options": {"impersonate": "chrome", "timeout": 30},
        "respect_robots": True,
        "id_fields": ["url"],
    },
}

# Segundo ponto de recolha **igual ao primeiro**, de propósito: é o único
# catálogo de demonstração que tem os mesmos produtos em duas lojas, e é isso que
# exercita a comparação entre lojas (mínimo/máximo/dispersão e ranking).
LOJA_ESPELHO = {
    **LOJA,
    "id": "books-toscrape-espelho",
    "name": "Books to Scrape (espelho)",
}

BENCHMARK = {
    "name": "Livros (demonstração)",
    "slug": SLUG,
    "description": "Comparação de preços de livros recolhidos de uma loja de demonstração.",
    "category": "Livros",
    "currency": "GBP",
    "match_on": "nome",
    "field_map": {"price": "preco", "product_name": "titulo", "url": "url", "image": "imagem", "availability": "disponibilidade"},
    "tags": ["demonstracao", "livros"],
    "stores": [LOJA, LOJA_ESPELHO],
}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    from api import auth_service

    utilizadores = auth_service.list_users(1) or [{}]
    token = auth_service.create_session(utilizadores[0]).get("token", "")
    cabecalhos = {"Authorization": f"Bearer {token}"}
    cliente = httpx.Client(base_url=BASE, timeout=300, headers=cabecalhos)

    def passo(titulo: str, resposta: httpx.Response, chaves: tuple[str, ...] = ()) -> dict:
        try:
            corpo = resposta.json()
        except Exception:  # noqa: BLE001
            corpo = {"_texto": resposta.text[:200]}
        resumo = {k: corpo.get(k) for k in chaves} if chaves else {}
        print(f"{titulo:28} HTTP {resposta.status_code} {resumo if resumo else ''}")
        return corpo

    # 1. criar (ou substituir) o benchmark
    existente = cliente.get(f"/benchmarks/{SLUG}")
    if existente.status_code == 200:
        passo("editar benchmark", cliente.put(f"/benchmarks/{SLUG}", json=BENCHMARK), ("slug",))
    else:
        passo("criar benchmark", cliente.post("/benchmarks", json=BENCHMARK), ("slug", "name"))

    definicao = cliente.get(f"/benchmarks/{SLUG}").json()
    print(f"{'índice do benchmark':28} {definicao.get('slug')} → ", end="")
    from api import elasticsearch_client as esc

    print(esc.benchmark_items_index(SLUG))
    print(f"{'field_map':28} {definicao.get('field_map')}")

    # 2. recolher
    recolha = passo("recolher", cliente.post(f"/benchmarks/{SLUG}/recolher", json={"limite_por_loja": 60}), ("offers", "indexed"))
    for loja in recolha.get("stores") or []:
        print(f"   loja {loja.get('store_id'):20} estado={loja.get('status')} itens={loja.get('items')} "
              f"ofertas={loja.get('ofertas')} indexadas={loja.get('indexadas')} erro={loja.get('error')}")

    # 3. análise
    estudo = passo("analise", cliente.get(f"/benchmarks/{SLUG}/analise"), ("kpis",))
    kpis = estudo.get("kpis") or {}
    print(f"   KPIs: {json.dumps(kpis, ensure_ascii=False)}")
    for loja_stats in estudo.get("stores") or []:
        print(f"   loja: {loja_stats.get('store_name')} · ofertas={loja_stats.get('ofertas')} · "
              f"média={loja_stats.get('preco_medio')} · índice={loja_stats.get('indice_preco')}")
    comparaveis = int(kpis.get("comparable_products") or 0)
    print(f"   produtos em 2+ lojas: {comparaveis}")
    assert comparaveis > 0, "a comparação entre lojas não encontrou produtos comuns"

    # 4. comparação e pesquisa
    comparacao = passo("comparacao", cliente.get(f"/benchmarks/{SLUG}/comparacao", params={"min_lojas": 2, "size": 5}), ("total",))
    for produto in (comparacao.get("items") or [])[:5]:
        melhor = produto.get("best") or {}
        print(f"   {str(produto.get('product_name'))[:46]:46} min={produto.get('price_min')} max={produto.get('price_max')} "
              f"loja={melhor.get('store_name')}")
    ofertas = passo("ofertas (pesquisa)", cliente.get(f"/benchmarks/{SLUG}/ofertas", params={"q": "light", "size": 3}), ("total",))
    for oferta in (ofertas.get("items") or [])[:3]:
        print(f"   oferta: {str(oferta.get('product_name'))[:50]:50} {oferta.get('price')} {oferta.get('currency')}")

    # 5. publicar e verificar o site
    publicacao = passo("publicar", cliente.post(f"/benchmarks/{SLUG}/publicar"), ("url", "search_url", "page_id"))
    pagina_cms = cliente.get(f"/site/{publicacao.get('path')}")
    print(f"{'página do CMS':28} HTTP {pagina_cms.status_code} · {len(pagina_cms.text)} bytes · "
          f"contém tabela={'<table' in pagina_cms.text}")
    publica = cliente.get(f"/site/benchmarks/{SLUG}/pesquisa", follow_redirects=True)
    tem_formulario = 'class="pesquisa"' in publica.text
    print(f"{'pesquisa pública':28} HTTP {publica.status_code} · {len(publica.text)} bytes · "
          f"tem formulário={tem_formulario} · tem linhas={'<tr>' in publica.text}")
    filtrada = cliente.get(f"/site/benchmarks/{SLUG}/pesquisa", params={"q": "light", "ordem": "preco"})
    print(f"{'pesquisa pública (q)':28} HTTP {filtrada.status_code} · {len(filtrada.text)} bytes")
    json_publico = passo("json público", cliente.get(f"/benchmarks/publico/{SLUG}"), ("kpis",))

    assert kpis.get("offers"), "sem ofertas recolhidas"
    assert publica.status_code == 200, "página pública não respondeu 200"
    assert "<table" in publica.text, "página pública sem tabela"
    assert json_publico.get("kpis"), "json público sem KPIs"
    print("\nTUDO OK: recolha, índice próprio, análise, publicação e pesquisa pública.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
