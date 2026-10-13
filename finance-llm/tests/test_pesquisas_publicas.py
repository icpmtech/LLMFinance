"""Páginas de pesquisa do CMS: filtros congelados, fotografia dos números e SEO.

Testa-se o que não depende da rede nem do Elasticsearch:

* a normalização dos filtros (tipos, limites e campos desconhecidos);
* a frase legível dos filtros, que serve de resumo e de `meta description`;
* a fotografia da pesquisa montada a partir da lista de municípios;
* a página no CMS: criar, endereço público, publicação, sitemap e SEO, com a
  marca própria (capa, logótipo e cor de destaque).
"""
from __future__ import annotations

from typing import Any, Dict

import pytest

from api import cms_render
from api import cms_store as store
from api import pesquisas_publicas as pesquisas


# ---------------------------------------------------------------------------
# Filtros
# ---------------------------------------------------------------------------

def test_normalizar_filtros_tipa_e_limita() -> None:
    limpos = store.normalizar_filtros(
        {
            "q": "  porto ",
            "distrito": "Porto",
            "ano_contratos": "2024",
            "ordenar": "contratos",
            "ordem": "ASC",
            "min_despesas": "1000",
            "limite": "500",
            "campo_desconhecido": "ignorado",
        }
    )

    assert limpos == {
        "q": "porto",
        "distrito": "Porto",
        "nuts": "",
        "ano_contratos": 2024,
        "ordenar": "contratos",
        "ordem": "asc",
        "min_despesas": 1000,
        "limite": 200,  # o máximo aceite
    }


def test_normalizar_filtros_com_lixo_nao_rebenta() -> None:
    limpos = store.normalizar_filtros({"ano_contratos": "abc", "limite": None, "ordem": "qualquer"})

    assert limpos["ano_contratos"] is None
    assert limpos["limite"] == 25
    assert limpos["ordem"] == "desc"


def test_descricao_dos_filtros_em_portugues() -> None:
    texto = pesquisas.descricao_dos_filtros(
        {"distrito": "Porto", "ano_contratos": 2024, "ordenar": "contratos"}
    )

    assert texto == "distrito de Porto, contratação de 2024, ordenado por valor contratado (decrescente)"


def test_descricao_dos_filtros_sem_filtros_diz_a_ordenacao() -> None:
    assert pesquisas.descricao_dos_filtros({}) == "ordenado por despesa total (decrescente)"


# ---------------------------------------------------------------------------
# Fotografia dos números
# ---------------------------------------------------------------------------

def _resposta(monkeypatch: pytest.MonkeyPatch) -> None:
    def falso_listar(**_kwargs: Any) -> Dict[str, Any]:
        return {
            "total": 18,
            "origem": "json-local",
            "ano_contratos": 2024,
            "items": [
                {
                    "nome": "Porto",
                    "geocod": "131202",
                    "distrito": "Porto",
                    "ano_despesas": 2023,
                    "despesas_total": 317_577_000.0,
                    "contratos_total": 5375,
                    "contratos_valor": 429_200_000.0,
                    "contratos_ano_total": 1468,
                    "contratos_ano_valor": 140_360_316.0,
                    "contratos_recentes": [
                        {"ano": "2026", "contratos": 425, "valor": 105_197_241.0},
                        {"ano": "2025", "contratos": 556, "valor": 113_903_101.0},
                    ],
                }
            ],
            "despesas_somadas": 1_590_878_000.0,
            "contratos_somados": 6_256_580_851.0,
            "contratos_ano_somados": 868_817_792.0,
            "contratos_ano_total_somados": 7200,
            "distritos": [{"key": "Porto", "count": 18}],
        }

    monkeypatch.setattr(pesquisas.municipios, "listar", falso_listar)


def test_dados_da_pesquisa_monta_a_fotografia(monkeypatch: pytest.MonkeyPatch) -> None:
    _resposta(monkeypatch)

    dados = pesquisas.dados_da_pesquisa(
        {"distrito": "Porto", "ano_contratos": 2024, "ordenar": "contratos", "limite": 5}
    )

    assert dados["total"] == 18
    assert dados["linhas"] == 1
    assert dados["ano_contratos"] == 2024
    assert dados["ano_despesas"] == 2023
    assert dados["contratos_ano_total_somados"] == 7200
    assert dados["itens"][0]["nome"] == "Porto"
    assert dados["itens"][0]["anos_recentes"][0]["ano"] == "2026"
    assert dados["descricao"].startswith("distrito de Porto")
    assert [fonte["documento"] for fonte in dados["fontes"]]


def test_resumo_dos_dados_fala_do_filtro_e_do_ano(monkeypatch: pytest.MonkeyPatch) -> None:
    _resposta(monkeypatch)

    resumo = pesquisas.resumo_dos_dados(pesquisas.dados_da_pesquisa({"ano_contratos": 2024}))

    assert "18 municípios" in resumo
    assert "em 2024" in resumo
    assert "7 200 contratos" in resumo


def test_opcoes_tem_distritos_e_anos() -> None:
    escolhas = pesquisas.opcoes()

    assert escolhas["limite_maximo"] == pesquisas.LIMITE_MAXIMO
    assert any(item["id"] == "contratos" for item in escolhas["ordenacoes"])
    assert all(distrito and distrito != "—" for distrito in escolhas["distritos"])


# ---------------------------------------------------------------------------
# Página no CMS: publicação, endereço, SEO e marca
# ---------------------------------------------------------------------------

@pytest.fixture()
def cms_limpo(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> Any:
    """Um CMS vazio em disco, para as páginas de teste não tocarem no real."""
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


def _pagina(**extra: Any) -> Dict[str, Any]:
    pagina: Dict[str, Any] = {
        "title": "Maiores contratações do distrito do Porto em 2024",
        "slug": "porto-2024",
        "status": "rascunho",
        "filtros": {"distrito": "Porto", "ano_contratos": 2024, "ordenar": "contratos", "limite": 10},
        "descricao_filtros": "distrito de Porto, contratação de 2024, ordenado por valor contratado (decrescente)",
        "intro": "## Onde se contrata mais\n\nRanking do distrito.",
        "cor": "#1d4ed8",
        "capa_id": "med_capa",
        "logo_id": "med_logo",
        "seo": {
            "title": "Contratos do Porto em 2024",
            "description": "Ranking dos municípios do distrito do Porto pela contratação de 2024.",
            "keywords": ["contratação", "porto", "2024"],
        },
        "dados": {
            "total": 18,
            "linhas": 1,
            "ano_contratos": 2024,
            "ano_despesas": 2023,
            "descricao": "distrito de Porto, contratação de 2024",
            "despesas_somadas": 1_590_878_000.0,
            "contratos_somados": 6_256_580_851.0,
            "contratos_ano_somados": 868_817_792.0,
            "contratos_ano_total_somados": 7200,
            "itens": [
                {
                    "nome": "Porto",
                    "distrito": "Porto",
                    "despesas_total": 317_577_000.0,
                    "contratos_ano_total": 1468,
                    "contratos_ano_valor": 140_360_316.0,
                    "anos_recentes": [{"ano": "2026", "contratos": 425, "valor": 1.0}],
                }
            ],
            "fontes": [{"documento": "INE · indicador 0013909", "url": "https://www.ine.pt"}],
            "gerado_em": "2026-10-13T21:30:00Z",
        },
    }
    pagina.update(extra)
    return pagina


def test_pagina_de_pesquisa_publica_e_tem_endereco(cms_limpo: Any) -> None:
    item = store.save_item("pesquisas", _pagina(), "qa@teste.pt")

    assert store.pesquisa_by_slug("porto-2024", published_only=True) is None  # ainda é rascunho
    assert store.pesquisa_by_slug("porto-2024", published_only=False) is not None

    store.publish_item("pesquisas", item["id"], "qa@teste.pt")

    publicada = store.pesquisa_by_slug("porto-2024")
    assert publicada is not None
    assert publicada["status"] == "publicado"
    assert store.pesquisa_path(publicada) == "/pesquisa/porto-2024"
    assert [entrada["slug"] for entrada in store.published_pesquisas()] == ["porto-2024"]
    assert "/site/pesquisa/porto-2024" in cms_render.render_sitemap()


def test_pagina_de_pesquisa_normaliza_filtros_ao_guardar(cms_limpo: Any) -> None:
    item = store.save_item("pesquisas", _pagina(filtros={"distrito": "Porto", "limite": "999"}), "qa@teste.pt")

    assert item["filtros"]["limite"] == 200
    assert item["id"].startswith("pes_")
    assert item["excerpt"]  # resumo gerado a partir do texto de entrada


def test_pagina_de_pesquisa_sem_titulo_falha(cms_limpo: Any) -> None:
    with pytest.raises(ValueError):
        store.save_item("pesquisas", {"title": "", "slug": "sem-titulo"}, "qa@teste.pt")


def test_render_da_pagina_tem_seo_marca_e_tabela(cms_limpo: Any) -> None:
    capa = store.save_media({"title": "Capa", "url": "https://exemplo.test/capa.jpg"}, "qa@teste.pt")
    logo = store.save_media({"title": "Logótipo", "url": "https://exemplo.test/logo.png"}, "qa@teste.pt")
    item = store.save_item(
        "pesquisas",
        _pagina(capa_id=capa["id"], logo_id=logo["id"]),
        "qa@teste.pt",
    )

    html = cms_render.render_pesquisa(item)

    assert "<title>Contratos do Porto em 2024" in html
    assert 'name="description" content="Ranking dos municípios' in html
    assert 'rel="canonical" href="' in html and "/site/pesquisa/porto-2024" in html
    assert '"@type": "Dataset"' in html
    assert "--accent: #1d4ed8" in html  # cor própria da página
    assert "https://exemplo.test/capa.jpg" in html  # imagem de capa
    assert "https://exemplo.test/logo.png" in html  # logótipo
    assert "Municípios do filtro" in html
    assert "Contratado em 2024" in html and "868,8 M€" in html
    assert "1 468" in html  # linha do Porto (contratos de 2024)
    assert "INE · indicador 0013909" in html  # proveniência
