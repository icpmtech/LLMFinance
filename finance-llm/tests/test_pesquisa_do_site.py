"""Pesquisa do site (`/site/pesquisa?q=`): páginas, artigos, estudos e relatórios.

O que se prova aqui:

* o **agrupamento** dos resultados — estudos de benchmark, páginas, artigos e
  relatórios — e a ordem dentro de cada grupo (o que casa no título vem primeiro);
* a comparação **sem acentos nem maiúsculas**: quem escreve «precos» encontra
  «Preços»;
* a **fronteira do que é público**: rascunhos e relatórios não publicados não
  aparecem nos resultados;
* a página em si — cabeçalho próprio, o mesmo formulário do menu com o termo já
  escrito e `noindex` (resultados de pesquisa não se indexam).

Nada aqui toca em `data/`: o CMS e a loja de relatórios vivem em `tmp_path`.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from api import cms_render  # noqa: E402
from api import cms_store  # noqa: E402
from api import reports_store as store  # noqa: E402
from api import reports_studio as studio  # noqa: E402


@pytest.fixture()
def instalacao(tmp_path, monkeypatch):
    """CMS e relatórios isolados em `tmp_path` (sem ler nem escrever em `data/`)."""
    monkeypatch.setattr(store, "REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr(store, "REPORTS_PATH", tmp_path / "reports" / "reports.json")
    monkeypatch.setattr(store, "FILES_DIR", tmp_path / "reports" / "files")
    monkeypatch.setattr(studio, "STUDIO_DIR", tmp_path / "reports" / "studio")

    cms = tmp_path / "cms"
    monkeypatch.setattr(cms_store, "CMS_DIR", cms)
    monkeypatch.setattr(cms_store, "CMS_PATH", cms / "cms.json")
    monkeypatch.setattr(cms_store, "MEDIA_DIR", cms / "media")
    monkeypatch.setattr(cms_store, "_cache", None)
    monkeypatch.setattr(cms_store, "_cache_mtime", None)

    store.reset_for_tests()
    studio.reset_for_tests()
    yield
    store.reset_for_tests()
    studio.reset_for_tests()


def _pagina(
    titulo: str, slug: str, *, mae: str = "", resumo: str = "", estado: str = "publicado"
) -> Dict[str, Any]:
    """Página do CMS (o caminho público é montado pelo CMS a partir do ascendente)."""
    return cms_store.save_item(
        "pages",
        {
            "title": titulo,
            "slug": slug,
            "parent_id": mae or None,
            "status": estado,
            "excerpt": resumo,
            "blocks": [],
        },
        "sistema",
    )


def _artigo(titulo: str, slug: str, *, corpo: str = "", estado: str = "publicado") -> Dict[str, Any]:
    return cms_store.save_item(
        "posts",
        {"title": titulo, "slug": slug, "markdown": corpo, "status": estado},
        "sistema",
    )


def _relatorio(titulo: str, *, tags: List[str], publicar: bool = True) -> Dict[str, Any]:
    """Relatório do Estúdio com PDF: é o que a biblioteca mostra e a pesquisa lê."""
    criado = studio.save_report(
        {
            "title": titulo,
            "subtitle": f"Leitura de {titulo}",
            "template": "personalizado",
            "tags": tags,
            "blocks": [{"type": "heading", "title": "Enquadramento", "text": "Objeto e período."}],
        },
        actor="autor@exemplo.pt",
    )["report"]
    studio.attach_pdf(criado["id"], "autor@exemplo.pt")
    if publicar:
        studio.publish_site(criado["id"], {"price": 0.0}, actor="autor@exemplo.pt")
    return criado


def _titulos(grupos: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    return {grupo["label"]: [item["title"] for item in grupo["items"]] for grupo in grupos}


def _itens(grupos: List[Dict[str, Any]], rotulo: str) -> Dict[str, str]:
    """Título → destino dos resultados de um grupo (vazio se o grupo não existir)."""
    return {
        item["title"]: item["href"]
        for grupo in grupos
        if grupo["label"] == rotulo
        for item in grupo["items"]
    }


# ------------------------------------------------------------------ agrupar
def test_agrupa_estudos_paginas_artigos_e_relatorios(instalacao):
    """Um termo encontra o que lhe pertence, já agrupado por tipo."""
    secao = _pagina("Benchmarks", "benchmarks")
    _pagina(
        "Telemóveis — comparação entre lojas",
        "lojas",
        mae=secao["id"],
        resumo="Os preços publicados por várias lojas.",
    )
    _pagina("Fontes dos dados", "fontes", resumo="De onde vêm os preços que publicamos.")
    _artigo("Como comparamos preços", "como-comparamos-precos", corpo="Normalizamos o mesmo produto.")
    _relatorio("Relatório de preços de mercado", tags=["mercados"])

    grupos = cms_render._resultados_da_pesquisa("preços")
    # A instalação vem semeada com o editorial e o catálogo por omissão (o CMS
    # semeia-se na primeira escrita): procura-se o que é nosso **dentro** de cada
    # grupo, e os grupos saem sempre por esta ordem.
    assert list(_titulos(grupos)) == [
        "Estudos de benchmark",
        "Páginas",
        "Artigos do blog",
        "Relatórios e documentos",
    ]
    assert "Telemóveis — comparação entre lojas" in _itens(grupos, "Estudos de benchmark")
    assert _itens(grupos, "Estudos de benchmark")["Telemóveis — comparação entre lojas"] == "/site/benchmarks/lojas"
    assert "Fontes dos dados" in _itens(grupos, "Páginas")
    assert "Como comparamos preços" in _itens(grupos, "Artigos do blog")
    assert "Relatório de preços de mercado" in _itens(grupos, "Relatórios e documentos")


def test_comparacao_ignora_acentos_e_maiusculas(instalacao):
    _pagina("Preços e dispersão", "precos")
    _artigo("Precos na loja", "precos-na-loja", corpo="Sem acento no título.")
    for termo in ("PRECOS", "preços", "Preços"):
        grupos = cms_render._resultados_da_pesquisa(termo)
        assert "Preços e dispersão" in _itens(grupos, "Páginas"), termo
        assert "Precos na loja" in _itens(grupos, "Artigos do blog"), termo


def test_o_que_casa_no_titulo_vem_primeiro(instalacao):
    _pagina("Preços por loja", "precos-por-loja")
    _pagina("Método", "metodo", resumo="Falamos de preços aqui dentro.")
    titulos = _titulos(cms_render._resultados_da_pesquisa("precos"))["Páginas"]
    assert titulos.index("Preços por loja") < titulos.index("Método")
    assert _itens(cms_render._resultados_da_pesquisa("precos"), "Páginas")["Preços por loja"] == "/site/precos-por-loja"


def test_rascunhos_e_relatorios_por_publicar_ficam_fora(instalacao):
    """O que não está publicado não é resultado: é a fronteira do site público."""
    _pagina("Preços por loja", "precos-por-loja")
    _pagina("Preços (rascunho)", "precos-rascunho", estado="rascunho")
    _artigo("Artigo sobre preços", "artigo-precos", corpo="Preços.", estado="rascunho")
    _relatorio("Relatório de preços por publicar", tags=["mercados"], publicar=False)

    grupos = cms_render._resultados_da_pesquisa("precos")
    assert "Preços por loja" in _itens(grupos, "Páginas")
    achados = {item["title"] for grupo in grupos for item in grupo["items"]}
    assert "Preços (rascunho)" not in achados
    assert "Artigo sobre preços" not in achados
    assert "Relatório de preços por publicar" not in achados


# -------------------------------------------------------------------- página
def test_pagina_de_resultados(instalacao):
    _pagina("Preços por loja", "precos-por-loja", resumo="O que custa onde.")
    html = cms_render.render_search("preços")

    assert "<h1>Pesquisar no site</h1>" in html
    assert 'action="/site/pesquisa"' in html and 'value="preços"' in html
    assert "Preços por loja" in html
    assert re.search(r"\d+ resultado\(s\) para «preços»", html)
    assert 'content="noindex, nofollow"' in html

    # Sem termo explica-se; sem resultados diz que não há e sugere por onde ir.
    vazio = cms_render.render_search("")
    assert "Escreva o que procura" in vazio and "<h2>" not in vazio
    nada = cms_render.render_search("xyznada")
    assert "Não encontrámos nada" in nada and 'href="/site/blog"' in nada


def test_rota_publica_de_pesquisa(instalacao):
    from fastapi.testclient import TestClient

    from api import main as api_main

    _pagina("Preços por loja", "precos-por-loja")
    cliente = TestClient(api_main.app, base_url="http://prova")

    resposta = cliente.get("/site/pesquisa", params={"q": "precos"})
    assert resposta.status_code == 200, resposta.text
    assert "Pesquisar no site" in resposta.text and "Preços por loja" in resposta.text
    # Sem termo responde na mesma (é o estado inicial do formulário).
    assert cliente.get("/site/pesquisa").status_code == 200
