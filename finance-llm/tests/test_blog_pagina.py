"""A página do blog: hashtags nos cartões e blocos no índice.

O que se prova aqui:

* cada cartão da lista mostra as etiquetas do artigo como hashtags, a ligar à
  lista por etiqueta — e não estica quando o artigo tem muitas;
* a página escolhida em Aparência → Página do blog entra no índice com os seus
  blocos, e o bloco «Últimos artigos» marca o lugar da lista gerada;
* sem esse bloco a lista fica no fim, e um segundo bloco «Últimos artigos» não
  repete os cartões;
* sem página escolhida, o índice gerado (`blog-topo`) é o de sempre;
* a rota `/site/blog` serve a página montada (e volta ao gerado quando a
  página é desligada das definições).
"""
from __future__ import annotations

import pathlib
from typing import Any, Dict, List

import pytest

from api import cms_render as render
from api import cms_routes
from api import cms_store as store

CARTAO = 'class="card post-card"'


@pytest.fixture()
def cms(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    """CMS isolado em `tmp_path` (sem ler nem escrever em `data/`)."""
    monkeypatch.setattr(store, "CMS_DIR", tmp_path)
    monkeypatch.setattr(store, "CMS_PATH", tmp_path / "cms.json")
    monkeypatch.setattr(store, "MEDIA_DIR", tmp_path / "media")
    with store._lock:
        store._cache = None
        store._cache_mtime = None
    yield store
    with store._lock:
        store._cache = None
        store._cache_mtime = None


def _corpo(html: str) -> str:
    """O conteúdo depois do cabeçalho: a `<meta description>` também cita o
    texto dos blocos e não pode ser confundida com a ordem do corpo."""
    return html[html.index("<main") :] if "<main" in html else html[html.index("<body") :]


def _pagina(cms: Any, blocks: List[Dict[str, Any]], *, title: str = "Blog", excerpt: str = "") -> Dict[str, Any]:
    payload: Dict[str, Any] = {"title": title, "slug": "blog", "status": "publicado", "blocks": blocks}
    if excerpt:
        payload["excerpt"] = excerpt
    return cms.save_item("pages", payload, "prova")


# ------------------------------------------------------------------ cartões
def test_cartao_mostra_as_etiquetas_como_hashtags(cms: Any) -> None:
    html = _corpo(render.render_blog(settings=cms.get_settings()))
    assert "post-card-tags" in html
    assert 'class="post-tag" href="/site/etiqueta/' in html
    assert ">#" in html


def test_cartao_limita_as_hashtags_e_conta_as_restantes(cms: Any) -> None:
    post = cms.save_item(
        "posts",
        {
            "title": "Com muitas etiquetas",
            "slug": "muitas-etiquetas",
            "markdown": "Texto",
            "tags": ["um", "dois", "tres", "quatro", "cinco", "seis"],
            "status": "publicado",
        },
        "prova",
    )
    html = _corpo(render.render_blog(settings=cms.get_settings()))
    assert post["slug"] in html
    assert "+2" in html


# ------------------------------------------------------------ blocos no índice
def test_os_blocos_da_pagina_entram_na_ordem_do_editor(cms: Any) -> None:
    pagina = _pagina(
        cms,
        [
            {"id": "b1", "type": "hero", "data": {"title": "Abertura do blog"}},
            {"id": "b2", "type": "texto", "data": {"title": "Antes da lista", "markdown": "Ola"}},
            {"id": "b3", "type": "blog", "data": {"title": "Todos os artigos"}},
            {
                "id": "b4",
                "type": "cta",
                "data": {"title": "Subscreva a seguir", "cta_label": "Subscrever", "cta_href": "/site"},
            },
        ],
    )
    html = _corpo(render.render_blog(page=pagina, settings=cms.get_settings()))
    assert (
        html.index("Abertura do blog")
        < html.index("Antes da lista")
        < html.index("Todos os artigos")
        < html.index(CARTAO)
        < html.index("Subscreva a seguir")
    )
    assert html.count("<h1") == 1
    # A lista continua a ser a gerada: filtros e cartões.
    assert 'class="meta"' in html
    assert CARTAO in html


def test_sem_bloco_de_artigos_a_lista_fica_no_fim(cms: Any) -> None:
    pagina = _pagina(cms, [{"id": "b1", "type": "hero", "data": {"title": "Abertura do blog"}}])
    html = _corpo(render.render_blog(page=pagina, settings=cms.get_settings()))
    assert html.index("Abertura do blog") < html.index(CARTAO)


def test_um_segundo_bloco_de_artigos_nao_repete_a_lista(cms: Any) -> None:
    pagina = _pagina(
        cms,
        [
            {"id": "c1", "type": "blog", "data": {"title": "Primeira"}},
            {"id": "c2", "type": "blog", "data": {"title": "Segunda"}},
        ],
        excerpt="resumo",
    )
    html = _corpo(render.render_blog(page=pagina, settings=cms.get_settings()))
    assert "Primeira" in html
    assert "Segunda" not in html
    assert html.count('<div class="posts">') == 1


def test_sem_pagina_escolhida_o_indice_e_o_gerado(cms: Any) -> None:
    html = render.render_blog(settings=cms.get_settings())
    assert "blog-topo" in html
    assert CARTAO in html


# ------------------------------------------------------------------- rota
def test_a_rota_do_blog_serve_a_pagina_montada(cms: Any) -> None:
    pagina = _pagina(cms, [{"id": "b1", "type": "hero", "data": {"title": "Abertura do blog"}}])
    cms.save_settings({"blog_page_id": pagina["id"]}, "prova")
    texto = cms_routes.site_blog(1).body.decode("utf-8")
    assert "Abertura do blog" in texto and CARTAO in texto
    # A lista paginada (e não o bloco de 9 artigos da página) é a do índice.
    assert "blog-topo" not in texto

    cms.save_settings({"blog_page_id": ""}, "prova")
    gerado = cms_routes.site_blog(1).body.decode("utf-8")
    assert "blog-topo" in gerado and CARTAO in gerado
