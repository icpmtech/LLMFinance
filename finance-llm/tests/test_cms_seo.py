"""SEO do `<head>` do site do CMS — o `<title>` não pode passar do limite.

O título do artigo é do editor: pode ser tão longo quanto quiser, e o `<h1>` da
página mostra-o todo. O que vai para o `<title>` leva o sufixo da marca
(`· Sabemos Studio`), e um artigo de 79 caracteres compunha um título de 96 — os
motores de busca cortam-no a meio da frase (era o que o teste de browser
`chat-ui/e2e/test_seo_blog_publico.py` apanhava, já no site publicado).

O que se testa aqui:

* o corte é feito **em palavras** e o sufixo da marca nunca é cortado;
* os títulos que já cabiam não mudam uma letra;
* o `og:title` e o `twitter:title` dizem o mesmo que o `<title>`;
* o `<h1>` do artigo mantém o título completo.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from api import cms_render  # noqa: E402
from api import cms_store  # noqa: E402

MARCA = "Sabemos Studio"
#: O título do artigo real que motivou o corte (79 caracteres).
TITULO_LONGO = "Trump se protege sobre pagar governo de volta por anúncios que já foram ao ar"


@pytest.fixture()
def instalacao_limpa(tmp_path, monkeypatch):
    """Site isolado em `tmp_path` (sem ler nem escrever em `data/`)."""
    cms = tmp_path / "cms"
    monkeypatch.setattr(cms_store, "CMS_DIR", cms)
    monkeypatch.setattr(cms_store, "CMS_PATH", cms / "cms.json")
    monkeypatch.setattr(cms_store, "MEDIA_DIR", cms / "media")
    monkeypatch.setattr(cms_store, "_cache", None)
    monkeypatch.setattr(cms_store, "_cache_mtime", None)
    yield


@pytest.fixture()
def definicoes() -> dict:
    return {"site_name": MARCA, "base_url": "https://sabemos.studio"}


def _tag(html: str, padrao: str) -> str:
    encontro = re.search(padrao, html)
    return encontro.group(1) if encontro else ""


def _conteudo(html: str, seletor: str) -> str:
    return _tag(html, re.escape(seletor) + r' content="([^"]*)"')


# ------------------------------------------------------------- título do head
def test_titulo_curto_leva_o_sufixo_da_marca() -> None:
    titulo = cms_render._titulo_do_head("Contratos públicos em 2026", MARCA)
    assert titulo == f"Contratos públicos em 2026 · {MARCA}"


def test_titulo_longo_e_cortado_em_palavras() -> None:
    titulo = cms_render._titulo_do_head(TITULO_LONGO, MARCA)
    assert len(titulo) <= cms_render.LIMITE_TITULO_HEAD, f"{len(titulo)} caracteres: {titulo}"
    assert titulo.endswith(f" · {MARCA}"), "o sufixo da marca foi cortado"
    # Corta em palavras: o que fica antes da marca não acaba a meio de uma palavra.
    assert TITULO_LONGO.startswith(titulo[: -len(f" · {MARCA}")])


def test_titulo_sem_espaco_para_a_marca_fica_so_o_titulo() -> None:
    marca = "Observatório Português de Compras Públicas e Contratação"
    titulo = cms_render._titulo_do_head("Contratos públicos em Portugal", marca)
    assert marca not in titulo
    assert titulo == "Contratos públicos em Portugal"


def test_titulo_sem_marca_nao_leva_sufixo() -> None:
    assert cms_render._titulo_do_head("Contratos públicos", "") == "Contratos públicos"


def test_titulo_vazio_usa_o_nome_do_site() -> None:
    assert cms_render._titulo_do_head("", MARCA) == MARCA


def test_titulo_que_ja_tem_a_marca_nao_a_repete() -> None:
    titulo = cms_render._titulo_do_head(f"Notícias do {MARCA}", MARCA)
    assert titulo == f"Notícias do {MARCA}"


def test_titulo_com_espacos_a_mais_e_normalizado() -> None:
    assert cms_render._titulo_do_head("  Contratos \n  públicos  ", MARCA) == f"Contratos públicos · {MARCA}"


# --------------------------------------------------------- página renderizada
def test_artigo_com_titulo_longo_sai_com_titulo_do_head_curto(instalacao_limpa, definicoes) -> None:
    post = cms_store.save_item(
        "posts",
        {"title": TITULO_LONGO, "markdown": "Corpo do artigo.", "status": "rascunho"},
    )
    cms_store.publish_item("posts", post["id"])
    html = cms_render.render_post(cms_store.get_item("posts", post["id"]), settings=definicoes)

    titulo = _tag(html, r"<title>([^<]*)</title>")
    assert len(titulo) <= cms_render.LIMITE_TITULO_HEAD, f"{len(titulo)} caracteres: {titulo}"
    assert titulo.endswith(f" · {MARCA}")
    assert _conteudo(html, 'meta property="og:title"') == titulo
    assert _conteudo(html, 'meta name="twitter:title"') == titulo
    # O cabeçalho da página mostra o título todo: só o `<head>` é encurtado.
    assert _tag(html, r"<h1>([^<]*)</h1>") == TITULO_LONGO


def test_artigo_com_titulo_curto_mantem_o_titulo_do_head(instalacao_limpa, definicoes) -> None:
    post = cms_store.save_item(
        "posts",
        {"title": "Contratos públicos em 2026", "markdown": "Corpo do artigo.", "status": "rascunho"},
    )
    cms_store.publish_item("posts", post["id"])
    html = cms_render.render_post(cms_store.get_item("posts", post["id"]), settings=definicoes)
    assert _tag(html, r"<title>([^<]*)</title>") == f"Contratos públicos em 2026 · {MARCA}"


def test_titulo_de_seo_escrito_a_mao_respeita_o_limite(instalacao_limpa, definicoes) -> None:
    """Um `seo.title` longo também é cortado (é o que o editor escreveu para o head)."""
    post = cms_store.save_item(
        "posts",
        {
            "title": "Título do documento",
            "seo": {"title": TITULO_LONGO},
            "markdown": "Corpo do artigo.",
            "status": "rascunho",
        },
    )
    cms_store.publish_item("posts", post["id"])
    html = cms_render.render_post(cms_store.get_item("posts", post["id"]), settings=definicoes)
    titulo = _tag(html, r"<title>([^<]*)</title>")
    assert len(titulo) <= cms_render.LIMITE_TITULO_HEAD
    assert titulo.endswith(f" · {MARCA}")
