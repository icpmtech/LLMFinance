"""Testes dos temas da plataforma nas notícias e da publicação no blog.

Cobre as três peças novas do módulo de notícias:

* `api/news_themes.py` — o catálogo curado (contratação pública, contratos,
  fundos europeus…) e as suas variantes sem acentos;
* a pesquisa por tema — o filtro que a aplica e a contagem por tema, que **não**
  pode ser feita dentro do tema ativo (senão os outros temas apareciam a zero);
* `POST /news/publish` — a notícia publicada como artigo rascunho no blog, com o
  crédito da fonte, a ligação para o original e sem duplicar o que já existe.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from api import cms_store  # noqa: E402
from api import elasticsearch_client as es_client  # noqa: E402
from api import news_routes  # noqa: E402
from api import news_themes  # noqa: E402

NOTICIA = {
    "id": "tema-obras-publicas-9f2c41d6a7b0e1c3",
    "title": "Lisbon council awards €4.2m road works contract",
    "translated_title": "Câmara de Lisboa adjudica obra de 4,2 M€",
    "summary": "The contract covers resurfacing on two main avenues.",
    "summary_pt": "O contrato cobre o reperfilamento de duas avenidas principais.",
    "publisher": "Construção Hoje",
    "published": "2026-10-14T09:30:00",
    "url": "https://exemplo.pt/noticia/obra",
    "topic": "contratação pública",
    "sentiment": "positivo",
    "topics": ["contratação pública", "obras"],
}


@pytest.fixture()
def cms_isolado(tmp_path, monkeypatch):
    """CMS isolado em `tmp_path` (não escreve em `data/`)."""
    cms = tmp_path / "cms"
    monkeypatch.setattr(cms_store, "CMS_DIR", cms)
    monkeypatch.setattr(cms_store, "CMS_PATH", cms / "cms.json")
    monkeypatch.setattr(cms_store, "MEDIA_DIR", cms / "media")
    monkeypatch.setattr(cms_store, "_cache", None)
    monkeypatch.setattr(cms_store, "_cache_mtime", None)
    yield


def _sessao(email: str = "editor@exemplo.pt") -> Any:
    return SimpleNamespace(user=SimpleNamespace(email=email))


class _ClienteESFalso:
    """Cliente Elasticsearch de prova: guarda o pedido e devolve o que se lhe der."""

    def __init__(self, resposta: Dict[str, Any] | None = None):
        self.resposta = resposta or {
            "hits": {
                "total": {"value": 1},
                "hits": [{"_id": NOTICIA["id"], "_score": 1.0, "_source": dict(NOTICIA)}],
            },
            "aggregations": {"themes": {"buckets": {"contratacao-publica": {"doc_count": 7}}}},
        }
        self.pedidos: List[Dict[str, Any]] = []

    def search(self, **kwargs: Any) -> Dict[str, Any]:
        self.pedidos.append(kwargs)
        return self.resposta


# ------------------------------------------------------------------ catálogo
def test_catalogo_tem_temas_com_vocabulario_e_sem_repetidos():
    ids = [theme["id"] for theme in news_themes.list_themes()]
    assert ids == news_themes.theme_ids()
    assert len(ids) == len(set(ids))
    for theme in news_themes.list_themes():
        assert theme["label"].strip()
        assert theme["description"].strip()
        assert theme["terms"], theme["id"]
        assert all(term == term.strip() and term for term in theme["terms"])
        assert all(tag == tag.strip() and tag for tag in theme["tags"])


def test_catalogo_cobre_contratacao_publica_e_contratos():
    ids = set(news_themes.theme_ids())
    assert {"contratacao-publica", "contratos"} <= ids


def test_tema_encontra_se_pelo_identificador_pelo_rotulo_e_sem_acentos():
    assert news_themes.get_theme("contratacao-publica")["label"] == "Contratação pública"
    assert news_themes.get_theme("Contratação pública")["id"] == "contratacao-publica"
    assert news_themes.get_theme("CONTRATACAO-PUBLICA")["id"] == "contratacao-publica"
    assert news_themes.get_theme("nao-existe") is None
    assert news_themes.get_theme(None) is None


def test_expressoes_incluem_a_forma_sem_acentos_e_nao_repetem():
    terms = news_themes.match_terms("contratacao-publica")
    assert "contratação pública" in terms
    assert "contratacao publica" in terms
    assert len(terms) == len(set(terms))
    # Termo sem acentos não gera variante nenhuma.
    assert news_themes.term_variants("contratos") == ["contratos"]


def test_baldes_levam_todos_os_temas_com_as_suas_expressoes():
    baldes = news_themes.theme_buckets()
    assert [balde["id"] for balde in baldes] == news_themes.theme_ids()
    assert all(balde["terms"] for balde in baldes)


def test_etiquetas_e_categoria_sugeridas_pelo_tema():
    assert "contratação pública" in news_themes.suggested_tags("contratacao-publica")
    assert news_themes.suggested_category("contratacao-publica") == "analises"
    assert news_themes.suggested_tags("nao-existe") == []
    assert news_themes.suggested_category("nao-existe") == ""


def test_endereco_do_artigo_sai_do_titulo_sem_acentos():
    assert news_themes.slugify("Contratação pública: 12 ajustes diretos!") == "contratacao-publica-12-ajustes-diretos"


# -------------------------------------------------------- pesquisa com tema
def test_pesquisa_com_tema_filtra_pelas_expressoes_e_pelo_tema_exato():
    cliente = _ClienteESFalso()
    es_client.search_all_news(
        theme_terms=news_themes.match_terms("contratacao-publica"),
        theme_buckets=news_themes.theme_buckets(),
        es=cliente,
    )
    filtros = cliente.pedidos[0]["body"]["query"]["bool"]["filter"]
    tema = filtros[-1]
    assert "bool" in tema and tema["bool"]["minimum_should_match"] == 1
    consultas = tema["bool"]["should"]
    assert {"multi_match": {"query": "contratação pública", "fields": es_client.NEWS_SEARCH_FIELDS,
                            "type": "best_fields", "operator": "and", "lenient": True}} in consultas
    assert {"term": {"topic": "contratacao publica"}} in consultas


def test_pesquisa_sem_tema_nao_leva_filtro_nem_agregacao_de_temas():
    cliente = _ClienteESFalso()
    es_client.search_all_news(es=cliente)
    corpo = cliente.pedidos[0]["body"]
    assert "themes" not in corpo.get("aggs", {})
    filtros = (corpo["query"].get("bool") or {}).get("filter") or []
    assert filtros == []


def test_contagem_por_tema_ignora_o_tema_ativo():
    """A contagem de cada tema não pode ser feita já dentro do tema escolhido."""
    cliente = _ClienteESFalso()
    es_client.search_all_news(
        tickers=["EDP.LS"],
        theme_terms=news_themes.match_terms("contratacao-publica"),
        theme_buckets=news_themes.theme_buckets(),
        es=cliente,
    )
    baldes = cliente.pedidos[0]["body"]["aggs"]["themes"]["filters"]["filters"]
    assert set(baldes) == set(news_themes.theme_ids())
    # Cada balde leva os filtros anteriores (o ticker, que o utilizador quer ver
    # respeitado na contagem) e a sua própria expressão de tema.
    for balde in baldes.values():
        filtros = balde["bool"]["filter"]
        assert {"terms": {"ticker": ["EDP.LS"]}} in filtros
        assert len(filtros) == 2
    ativo = es_client._news_theme_clause(news_themes.match_terms("contratacao-publica"))
    assert ativo in baldes["contratacao-publica"]["bool"]["filter"]
    # Nos outros temas não entra o filtro do tema ativo — senão apareciam a zero.
    assert ativo not in baldes["contratos"]["bool"]["filter"]
    assert ativo not in baldes["insolvencias"]["bool"]["filter"]


def test_facetas_de_temas_saem_pela_ordem_do_catalogo_com_o_que_o_servidor_contou():
    cliente = _ClienteESFalso()
    resultado = es_client.search_all_news(
        theme_buckets=news_themes.theme_buckets(),
        es=cliente,
    )
    temas = resultado["facets"]["themes"]
    assert [item["value"] for item in temas] == news_themes.theme_ids()
    contagens = {item["value"]: item["count"] for item in temas}
    assert contagens["contratacao-publica"] == 7
    assert contagens["contratos"] == 0


def test_rota_de_pesquisa_recusa_tema_desconhecido():
    from fastapi.testclient import TestClient

    from api import main as api_main

    cliente = TestClient(api_main.app, base_url="http://prova")
    resposta = cliente.get("/news/search", params={"theme": "tema-inventado"})
    assert resposta.status_code == 422
    assert "não existe" in resposta.json()["detail"]


def test_rota_de_temas_publica_o_catalogo():
    from fastapi.testclient import TestClient

    from api import main as api_main

    cliente = TestClient(api_main.app, base_url="http://prova")
    resposta = cliente.get("/news/themes")
    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["total"] == len(news_themes.theme_ids())
    ids = [item["id"] for item in corpo["items"]]
    assert ids == news_themes.theme_ids()


# ------------------------------------------------- publicação no blog
def test_publicacao_exige_sessao(cms_isolado, monkeypatch):
    from fastapi.testclient import TestClient

    from api import main as api_main

    monkeypatch.setattr(news_routes, "get_news_item", lambda news_id: dict(NOTICIA))
    cliente = TestClient(api_main.app, base_url="http://prova")
    resposta = cliente.post("/news/publish", json={"id": NOTICIA["id"]})
    assert resposta.status_code == 401


def test_publicacao_cria_artigo_rascunho_com_fonte_e_ligacao(cms_isolado, monkeypatch):
    monkeypatch.setattr(news_routes, "get_news_item", lambda news_id: dict(NOTICIA))
    resposta = news_routes.news_publish(
        {"id": NOTICIA["id"], "theme": "contratacao-publica"},
        session=_sessao(),
    )
    assert resposta["saved"] is True
    assert resposta["duplicado"] is False
    assert resposta["tema"] == "contratacao-publica"
    artigo = resposta["artigo"]
    # O título é o português (traduzido), não o original em inglês.
    assert artigo["title"] == "Câmara de Lisboa adjudica obra de 4,2 M€"
    assert artigo["status"] == "rascunho"
    assert artigo["excerpt"] == NOTICIA["summary_pt"]
    assert "[ler a notícia original](https://exemplo.pt/noticia/obra)" in artigo["markdown"]
    assert "**Fonte:** Construção Hoje · 2026-10-14" in artigo["markdown"]
    assert "tema «Contratação pública»" in artigo["markdown"]
    assert resposta["url"] == f"/cms/blog?id={artigo['id']}"
    # O artigo entra mesmo no CMS, como rascunho.
    listagem = cms_store.list_items("posts", status="rascunho")
    assert artigo["id"] in [item["id"] for item in listagem["items"]]


def test_publicacao_leva_etiquetas_do_tema_e_a_marca_da_noticia(cms_isolado, monkeypatch):
    monkeypatch.setattr(news_routes, "get_news_item", lambda news_id: dict(NOTICIA))
    artigo = news_routes.news_publish(
        {"id": NOTICIA["id"], "theme": "contratacao-publica"},
        session=_sessao(),
    )["artigo"]
    assert "contratação pública" in artigo["tags"]
    assert "Construção Hoje" in artigo["tags"]
    assert f"noticia-{NOTICIA['id']}" in artigo["tags"]


def test_publicacao_nao_duplica_a_mesma_noticia(cms_isolado, monkeypatch):
    monkeypatch.setattr(news_routes, "get_news_item", lambda news_id: dict(NOTICIA))
    primeiro = news_routes.news_publish({"id": NOTICIA["id"]}, session=_sessao())
    segundo = news_routes.news_publish({"id": NOTICIA["id"]}, session=_sessao())
    assert segundo["saved"] is False
    assert segundo["duplicado"] is True
    assert segundo["artigo"]["id"] == primeiro["artigo"]["id"]
    marca = f"noticia-{NOTICIA['id']}"
    assert cms_store.list_items("posts", tag=marca)["total"] == 1


def test_publicacao_respeita_o_texto_e_as_etiquetas_do_editor(cms_isolado, monkeypatch):
    monkeypatch.setattr(news_routes, "get_news_item", lambda news_id: dict(NOTICIA))
    artigo = news_routes.news_publish(
        {
            "id": NOTICIA["id"],
            "title": "Lisboa adjudica obra de 4,2 M€",
            "excerpt": "Resumo escrito à mão.",
            "markdown": "## Análise\n\nO contrato foi adjudicado por ajuste direto.",
            "tags": ["obras públicas", "Lisboa"],
        },
        session=_sessao(),
    )["artigo"]
    assert artigo["title"] == "Lisboa adjudica obra de 4,2 M€"
    assert artigo["excerpt"] == "Resumo escrito à mão."
    assert artigo["markdown"].startswith("## Análise")
    assert "obras públicas" in artigo["tags"] and "Lisboa" in artigo["tags"]
    assert artigo["author"] == "editor@exemplo.pt"


def test_publicacao_sem_noticia_nem_titulo_pede_os_dados(cms_isolado, monkeypatch):
    monkeypatch.setattr(news_routes, "get_news_item", lambda news_id: None)
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as erro:
        news_routes.news_publish({"id": "desaparecida"}, session=_sessao())
    assert erro.value.status_code == 422
    assert "título" in erro.value.detail


def test_publicacao_recusa_tema_desconhecido(cms_isolado, monkeypatch):
    monkeypatch.setattr(news_routes, "get_news_item", lambda news_id: dict(NOTICIA))
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as erro:
        news_routes.news_publish({"id": NOTICIA["id"], "theme": "inventado"}, session=_sessao())
    assert erro.value.status_code == 422


def test_publicacao_sem_elasticsearch_usa_o_que_o_pedido_traz(cms_isolado, monkeypatch):
    """Fora do índice (notícia apagada), o editor ainda pode escrever o artigo."""
    monkeypatch.setattr(news_routes, "get_news_item", lambda news_id: None)
    artigo = news_routes.news_publish(
        {"title": "Nota de mercado", "excerpt": "O que se passou.", "markdown": "Corpo escrito à mão."},
        session=_sessao(),
    )["artigo"]
    assert artigo["title"] == "Nota de mercado"
    assert artigo["markdown"] == "Corpo escrito à mão."
