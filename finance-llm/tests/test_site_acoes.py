"""Partilhar e favoritos no site, e a lista de estudos em `/site/benchmarks`.

O que se prova aqui:

* a barra de ações (blog e estudo) traz o menu de partilha, o botão de guardar
  e a ligação para a lista — e o script uma só vez por página;
* a estrela dos cartões guarda o produto com o preço e a loja (é o que a lista
  de favoritos mostra);
* `/site/favoritos` existe, é `noindex` e desenha a moldura que o script usa;
* a página-mãe dos estudos ganha os cartões dos benchmarks publicados, com
  imagem, «desde» e ligação — sem ninguém editar a página do CMS.
"""
from __future__ import annotations

from typing import Any, Dict, List

import pytest
from fastapi.testclient import TestClient

from api import benchmarks_store
from api import cms_render as render
from api import cms_store as cms_store
from api import elasticsearch_client as esc
from api import site_acoes


def _app() -> Any:
    from api import main as api_main

    return api_main.app


@pytest.fixture()
def instalacao(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    """CMS isolado em `tmp_path` (sem ler nem escrever em `data/`)."""
    cms = tmp_path / "cms"
    monkeypatch.setattr(cms_store, "CMS_DIR", cms)
    monkeypatch.setattr(cms_store, "CMS_PATH", cms / "cms.json")
    monkeypatch.setattr(cms_store, "MEDIA_DIR", cms / "media")
    monkeypatch.setattr(cms_store, "_cache", None)
    monkeypatch.setattr(cms_store, "_cache_mtime", None)
    yield


# ------------------------------------------------------------------- ações
def test_barra_de_acoes_tem_partilha_guardar_e_lista() -> None:
    html = site_acoes.barra_acoes(
        url="https://sabemos.studio/site/blog/exemplo",
        titulo='Um artigo com "aspas"',
        tipo="artigo",
        chave="/site/blog/exemplo",
    )
    assert 'class="site-acoes"' in html
    # As redes levam o endereço e o título codificados (e o `&` escapado uma vez).
    assert "https://wa.me/?text=Um+artigo" in html
    assert "linkedin.com/sharing/share-offsite/?url=https%3A%2F%2Fsabemos.studio" in html
    assert "&amp;url=" in html and "&amp;amp;" not in html
    # A partilha do sistema nasce escondida; a cópia está sempre disponível.
    assert "data-partilhar hidden" in html
    assert 'data-copiar="https://sabemos.studio/site/blog/exemplo"' in html
    assert 'data-favoritar' in html and 'data-chave="/site/blog/exemplo"' in html
    assert 'href="/site/favoritos"' in html and "data-favoritos-ligacao hidden" in html
    # O script entra uma vez e sabe partilhar e copiar.
    assert html.count("<script>") == 1 and html.count("</script>") == 1
    assert "navigator.share" in html and "navigator.clipboard.writeText" in html


def test_estrela_do_cartao_leva_o_produto_para_os_favoritos() -> None:
    html = site_acoes.botao_favorito(
        chave="/site/benchmarks/x/pesquisa#abc",
        url="/site/benchmarks/x/pesquisa#p-abc",
        titulo="Sapatilhas Run",
        preco="36,33 €",
        nota="Amazon Espanha",
        imagem="https://loja.pt/foto.png",
    )
    assert "data-favoritar" in html
    assert 'data-tipo="produto"' in html
    assert 'data-preco="36,33 €"' in html and 'data-nota="Amazon Espanha"' in html
    assert 'data-imagem="https://loja.pt/foto.png"' in html
    assert 'aria-pressed="false"' in html
    # O script não se repete em cada cartão.
    assert "<script" not in html


def test_a_pagina_de_favoritos_desenha_a_moldura_da_lista(instalacao: Any) -> None:
    html = render.render_favoritos(settings=cms_store.get_settings())
    assert "<h1>Favoritos</h1>" in html
    assert 'data-favoritos-itens' in html
    assert 'data-favoritos-vazio' in html and 'data-favoritos-limpar' in html
    assert "window.SabemosFavoritos" in html
    assert 'content="noindex, nofollow"' in html
    assert 'href="/site/favoritos"' in html  # canónica

    resposta = TestClient(_app(), base_url="http://prova").get("/site/favoritos")
    assert resposta.status_code == 200
    assert "Ainda não guardou nada" in resposta.text


# ------------------------------------------------------- estudos na página-mãe
def _benchmark_publico() -> Dict[str, Any]:
    return {
        "slug": "sapatilhas-lojas",
        "name": "Sapatilhas — comparação entre lojas",
        "description": "O mesmo modelo comparado entre lojas.",
        "category": "Calçado",
        "currency": "EUR",
        "public": True,
        "stores": [{"id": "nike"}, {"id": "decathlon"}],
    }


def test_cartao_do_estudo_mostra_imagem_e_preco(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        esc,
        "benchmark_product_comparison",
        lambda *a, **k: {
            "items": [
                {
                    "product_name": "Sapatilhas Run",
                    "price_min": 36.33,
                    "stores": 2,
                    "best": {"image": "https://loja.pt/foto.png", "store_name": "Amazon"},
                }
            ],
            "total": 110,
        },
    )
    html = render._cartao_estudo(_benchmark_publico())  # noqa: SLF001 - o cartão é o objeto do teste
    assert "estudo-card" in html
    assert "https://loja.pt/foto.png" in html
    assert "desde 36,33 €" in html
    assert "2 lojas" in html and "110 produtos" in html
    assert 'href="/site/benchmarks/sapatilhas-lojas/pesquisa"' in html


def test_pagina_dos_benchmarks_ganha_a_lista_dos_estudos(
    instalacao: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(benchmarks_store, "publicos", lambda: [_benchmark_publico()])
    monkeypatch.setattr(
        esc,
        "benchmark_product_comparison",
        lambda *a, **k: {
            "items": [
                {
                    "product_name": "Sapatilhas Run",
                    "price_min": 36.33,
                    "stores": 2,
                    "best": {"image": "https://loja.pt/foto.png"},
                }
            ],
            "total": 20,
        },
    )
    pagina = {
        "id": "pagina-benchmarks",
        "slug": "benchmarks",
        "title": "Benchmarks de produtos",
        "path": "benchmarks",
        "status": "publicado",
        "blocks": [
            {"type": "hero", "data": {"title": "Benchmarks de produtos", "subtitle": "Comparações"}},
            {"type": "texto", "data": {"title": "Como ler", "markdown": "Texto de apoio."}},
        ],
    }
    html = render.render_page(pagina, settings=cms_store.get_settings())
    assert "Estudos publicados" in html
    assert 'href="/site/benchmarks/sapatilhas-lojas/pesquisa"' in html
    # A lista entra logo a seguir à abertura, antes do texto de apoio.
    assert html.index('data-bloco="hero"') < html.index("Estudos publicados") < html.index("Como ler")


def test_sem_estudos_publicados_a_seccao_nao_aparece(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(benchmarks_store, "publicos", lambda: [])
    assert render._seccao_estudos() == ""  # noqa: SLF001


def test_bloco_de_estudos_configura_desenho_e_colunas(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(benchmarks_store, "publicos", lambda: [_benchmark_publico()])
    monkeypatch.setattr(
        esc,
        "benchmark_product_comparison",
        lambda *a, **k: {
            "items": [
                {
                    "product_name": "Sapatilhas Run",
                    "price_min": 36.33,
                    "best": {"image": "https://loja.pt/foto.png"},
                }
            ],
            "total": 3,
        },
    )
    html = render._render_block(  # noqa: SLF001 - o bloco é o objeto do teste
        {
            "type": "estudos",
            "data": {
                "title": "Os nossos estudos",
                "intro": "Escolha um para comparar.",
                "layout": "lista",
                "columns": 2,
                "limit": 1,
                "show_image": False,
                "show_price": False,
            },
        }
    )
    assert "estudos--lista" in html and "estudos--cols-1" in html
    assert "Os nossos estudos" in html and "Escolha um para comparar." in html
    assert "estudo-figura--vazia" in html and "<img" not in html
    assert "desde " not in html
    assert "1 estudo" in html


def test_a_pagina_nao_duplica_a_lista_quando_o_bloco_esta_na_pagina(
    instalacao: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(benchmarks_store, "publicos", lambda: [_benchmark_publico()])
    monkeypatch.setattr(
        esc,
        "benchmark_product_comparison",
        lambda *a, **k: {"items": [{"product_name": "X", "price_min": 1.0, "best": {}}], "total": 1},
    )
    pagina = {
        "id": "pagina-benchmarks",
        "slug": "benchmarks",
        "title": "Benchmarks de produtos",
        "path": "benchmarks",
        "status": "publicado",
        "blocks": [
            {"type": "hero", "data": {"title": "Benchmarks de produtos"}},
            {"type": "estudos", "data": {"title": "Escolha um estudo"}},
        ],
    }
    html = render.render_page(pagina, settings=cms_store.get_settings())
    assert html.count("estudos-grid") == 1
    assert "Escolha um estudo" in html
