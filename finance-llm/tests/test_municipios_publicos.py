"""Fichas públicas de município: os dados, o texto com IA e a publicação.

Testa-se o que não depende da rede nem do Elasticsearch:

* a montagem da fotografia dos dados a partir de uma ficha (classificadores na
  ordem oficial, série anual, fornecedores) e a recusa de um município que não
  existe;
* o resumo factual que a IA e a página recebem — incluindo a contratação por
  ano do Portal BASE, que é a única série anual que existe;
* a leitura do JSON que o modelo devolve (com cercas ``` à volta e prosa em vez
  de JSON) sem perder o texto;
* a ficha do CMS: criar, publicar, endereço público, sitemap e SEO;
* a lista por ano de contratos, calculada sobre as fichas locais.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

import pytest

from api import cms_render
from api import cms_store as store
from api import municipios_publicos as publicos
from api import municipios_service as municipios


# ---------------------------------------------------------------------------
# Dados sintéticos
# ---------------------------------------------------------------------------

def _ficha(nome: str = "Águeda", ano: int = 2023) -> Dict[str, Any]:
    return {
        "doc_id": "010100",
        "nome": nome,
        "geocod": "010100",
        "geocod_curto": "100",
        "distrito": "Aveiro",
        "nuts": "1C",
        "nuts_nome": "Região de Aveiro",
        "ano_despesas": ano,
        "anos": [str(ano)],
        "despesas_total": 22_268_000.0,
        "despesas_correntes": 17_844_000.0,
        "despesas_capital": 4_423_000.0,
        "despesas_pessoal": 7_253_000.0,
        "despesas_bens_servicos": 8_714_000.0,
        "despesas_por_ano": {
            str(ano): {"D": 22_268_000.0, "D1": 17_844_000.0, "D11": 7_253_000.0, "D2": 4_423_000.0}
        },
        "contratos_total": 1663,
        "contratos_valor": 70_699_262.95,
        "contratos_por_ano": {
            "2015": {"contratos": 69, "valor": 7_763_749.59},
            "2024": {"contratos": 120, "valor": 6_500_000.0},
        },
        "contratos_primeiro_ano": 2012,
        "contratos_ultimo_ano": 2026,
        "contratos_detalhe": {
            "total": 1663,
            "valor": 70_699_262.95,
            "fornecedores": [
                {"nome": "Obras do Vouga", "contratos": 12, "valor": 3_000_000.0},
                {"nome": "Papelaria Central", "contratos": 40, "valor": 90_000.0},
            ],
        },
        "recolhido_em": "2026-10-13T15:37:14Z",
        "fonte_despesas": "INE · indicador 0013909",
        "fonte_contratos": "Portal BASE · contratos",
    }


@pytest.fixture()
def ficha_sintetica(monkeypatch: pytest.MonkeyPatch) -> Dict[str, Any]:
    ficha = _ficha()
    monkeypatch.setattr(municipios, "ficha", lambda *_args, **_kwargs: ficha)
    return ficha


# ---------------------------------------------------------------------------
# Fotografia dos dados
# ---------------------------------------------------------------------------

def test_dados_do_municipio_levam_os_classificadores_na_ordem_oficial(ficha_sintetica: Dict[str, Any]) -> None:
    dados = publicos.dados_do_municipio("Águeda")

    assert dados["municipio"] == "Águeda"
    assert dados["ano_despesas"] == 2023
    assert dados["despesas_total"] == 22_268_000.0
    # A ordem é a do classificador oficial (D antes de D1 antes de D11).
    assert [item["codigo"] for item in dados["por_classificador"]] == ["D", "D1", "D11", "D2"]
    assert dados["serie_despesas"] == [{"ano": "2023", "total": 22_268_000.0}]
    assert dados["contratos"]["total"] == 1663
    assert [f["nome"] for f in dados["contratos"]["fornecedores"]] == ["Obras do Vouga", "Papelaria Central"]
    assert dados["contratos"]["por_ano"]["2024"] == {"contratos": 120, "valor": 6_500_000.0}


def test_municipio_inexistente_devolve_erro(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(municipios, "ficha", lambda *_args, **_kwargs: {"error": "Município não encontrado: X"})

    dados = publicos.dados_do_municipio("X")

    assert "não encontrado" in dados["error"]


def test_resumo_usa_a_serie_anual_do_portal_base(ficha_sintetica: Dict[str, Any]) -> None:
    resumo = publicos.resumo_dos_dados(publicos.dados_do_municipio("Águeda"))

    assert "Despesa total: 22,3 milhões de euros" in resumo
    assert "Contratação por ano (Portal BASE): 2015: 69 contratos" in resumo
    assert "2024: 120 contratos" in resumo
    assert "Obras do Vouga" in resumo
    assert "Portal BASE · contratos" in resumo


@pytest.mark.parametrize(
    "valor,esperado",
    [
        (0, "0 euros"),
        (40_000, "40 000 euros"),
        (1_000_000, "1 milhão de euros"),
        (22_268_000, "22,3 milhões de euros"),
    ],
)
def test_valores_escritos_como_se_le(valor: float, esperado: str) -> None:
    assert publicos._milhoes(valor) == esperado


# ---------------------------------------------------------------------------
# Texto com IA
# ---------------------------------------------------------------------------

def test_le_o_json_mesmo_com_cercas_de_codigo() -> None:
    resposta = '```json\n{"titulo": "T", "resumo": "R", "corpo": "C"}\n```'

    assert publicos._extrato_json(resposta) == {"titulo": "T", "resumo": "R", "corpo": "C"}
    assert publicos._extrato_json("sem json aqui") is None


def test_resposta_em_prosa_nao_se_perde() -> None:
    dados = {"municipio": "Águeda", "despesas_total": 22_268_000.0}

    texto = publicos._normalizar_texto({}, "## A despesa\n\nGastou 22,3 milhões de euros.", dados)

    assert texto["titulo"] == "Despesas da Câmara Municipal de Águeda"
    assert texto["corpo"].startswith("## A despesa")
    assert texto["resumo"].startswith("## A despesa") is False
    assert "22,3 milhões" in texto["resumo"]


def test_sem_fornecedor_de_ia_nao_inventa_texto(monkeypatch: pytest.MonkeyPatch, ficha_sintetica: Dict[str, Any]) -> None:
    from api import scraper_ai

    monkeypatch.setattr(scraper_ai, "pick_provider", lambda *_args, **_kwargs: (None, None, None, None))

    resultado = publicos.texto_com_ia("Águeda")

    assert resultado["ok"] is False
    assert "Nenhum fornecedor de IA" in resultado["error"]


def test_o_prompt_leva_os_numeros_e_as_instrucoes(ficha_sintetica: Dict[str, Any]) -> None:
    dados = publicos.dados_do_municipio("Águeda")

    prompt = publicos.PROMPT_TEXTO.format(
        municipio=dados["municipio"],
        resumo=publicos.resumo_dos_dados(dados),
        instrucoes="Foca a despesa com pessoal.",
    )

    assert "Águeda" in prompt
    assert "22,3 milhões de euros" in prompt
    assert "Foca a despesa com pessoal." in prompt
    assert '"titulo"' in prompt  # o formato pedido chega ao modelo com as chaves certas


# ---------------------------------------------------------------------------
# Ficha no CMS, publicação e SEO
# ---------------------------------------------------------------------------

@pytest.fixture()
def cms_limpo(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> Any:
    """Um CMS vazio em disco, para a ficha de teste não tocar no CMS real."""
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


def _criar_ficha(**extra: Any) -> Dict[str, Any]:
    dados = publicos.dados_do_municipio("Águeda")
    doc = store.save_item(
        "municipios",
        {
            "municipio": "Águeda",
            "title": extra.pop("title", "Despesas da Câmara Municipal de Águeda"),
            "slug": extra.pop("slug", "agueda"),
            "dados": dados,
            "excerpt": "A despesa da Câmara de Águeda em 2023.",
            "blocks": [{"type": "texto", "data": {"markdown": "## A despesa\n\n22,3 milhões de euros."}}],
            **extra,
        },
        "qa@iqos.dev",
    )
    return doc


def test_ficha_nasce_rascunho_com_endereco_publico(cms_limpo: Any, ficha_sintetica: Dict[str, Any]) -> None:
    doc = _criar_ficha()

    assert doc["id"].startswith("mun_")
    assert doc["slug"] == "agueda"
    assert doc["status"] == "rascunho"
    assert doc["municipio"] == "Águeda"
    assert store.municipio_path(doc) == "/municipio/agueda"
    assert store.municipio_by_slug("agueda", published_only=False)["id"] == doc["id"]
    assert store.municipio_by_slug("agueda") is None  # ainda não publicado
    assert store.municipio_by_name("agueda")["id"] == doc["id"]


def test_ficha_sem_municipio_nao_grava(cms_limpo: Any) -> None:
    with pytest.raises(ValueError):
        store.save_item("municipios", {"title": "Sem município"}, "qa@iqos.dev")


def test_publicar_torna_a_ficha_visivel_e_no_sitemap(cms_limpo: Any, ficha_sintetica: Dict[str, Any]) -> None:
    doc = _criar_ficha()
    publicado = store.publish_item("municipios", doc["id"], "qa@iqos.dev")

    assert publicado["status"] == "publicado"
    assert store.municipio_by_slug("agueda")["id"] == doc["id"]
    assert [item["id"] for item in store.published_municipios()] == [doc["id"]]

    sitemap = cms_render.render_sitemap({"base_url": "https://exemplo.pt"})
    assert "https://exemplo.pt/site/municipio/agueda" in sitemap


def test_ficha_publicada_tem_seo_e_os_numeros(cms_limpo: Any, ficha_sintetica: Dict[str, Any]) -> None:
    doc = _criar_ficha()
    doc = store.save_item(
        "municipios",
        {**doc, "seo": {"title": "Despesas de Águeda", "description": "Despesa e contratação em 2023."}},
        "qa@iqos.dev",
    )

    html = cms_render.render_municipio(doc)

    assert "<title>Despesas de Águeda" in html
    assert 'name="description" content="Despesa e contratação em 2023."' in html
    assert f'rel="canonical" href="{cms_render._absolute("/site/municipio/agueda", "")}"' in html
    assert "application/ld+json" in html
    assert "22,3 M€" in html  # destaque da despesa total
    assert "Despesa por classificador económico (2023)" in html
    assert "Contratação pública por ano (Portal BASE)" in html
    assert "Obras do Vouga" in html
    assert "INE · indicador 0013909" in html


def test_ficha_ainda_em_rascunho_nao_serve_no_site(cms_limpo: Any, ficha_sintetica: Dict[str, Any]) -> None:
    _criar_ficha()

    with pytest.raises(KeyError):
        store.get_item("municipios", "inexistente")
    assert store.municipio_by_slug("agueda") is None


def test_apagar_a_ficha_tira_a_do_site(cms_limpo: Any, ficha_sintetica: Dict[str, Any]) -> None:
    doc = _criar_ficha()
    store.publish_item("municipios", doc["id"], "qa@iqos.dev")

    store.delete_item("municipios", doc["id"], "qa@iqos.dev")

    assert store.municipio_by_slug("agueda") is None
    assert store.municipio_by_name("Águeda") is None


# ---------------------------------------------------------------------------
# Contratação por ano (Portal BASE)
# ---------------------------------------------------------------------------

def test_anos_de_contratos_do_mais_recente_para_o_mais_antigo() -> None:
    anos = municipios.anos_de_contratos([_ficha(), _ficha(nome="Outro")])

    assert anos == ["2024", "2015"]


def test_contratos_do_ano_devolve_zero_quando_nao_ha_contratos() -> None:
    assert municipios.contratos_do_ano(_ficha(), "2019") == {"contratos": 0, "valor": 0.0}
    assert municipios.contratos_do_ano(_ficha(), "2024") == {"contratos": 120, "valor": 6_500_000.0}


def test_lista_por_ano_de_contratos_ordena_pelo_ano_escolhido(monkeypatch: pytest.MonkeyPatch) -> None:
    fichas = [
        {**_ficha("Alfa"), "contratos_por_ano": {"2024": {"contratos": 2, "valor": 200.0}}},
        {**_ficha("Beta"), "contratos_por_ano": {"2024": {"contratos": 9, "valor": 900.0}}},
    ]
    monkeypatch.setattr(municipios, "fichas_locais", lambda: fichas)

    resposta = municipios.listar_por_ano_contratos(ano_contratos=2024, ordenar="contratos", size=10)

    assert [item["nome"] for item in resposta["items"]] == ["Beta", "Alfa"]
    assert resposta["contratos_ano_somados"] == 1100.0
    assert resposta["contratos_ano_total_somados"] == 11
    assert resposta["ano_contratos"] == 2024
    assert resposta["origem"] == "json-local"
    assert resposta["distritos"] == [{"key": "Aveiro", "count": 2}]


def test_lista_por_ano_de_contratos_filtra_por_distrito(monkeypatch: pytest.MonkeyPatch) -> None:
    fichas = [
        {**_ficha("Alfa"), "distrito": "Aveiro", "contratos_por_ano": {"2024": {"contratos": 1, "valor": 1.0}}},
        {**_ficha("Beta"), "distrito": "Porto", "contratos_por_ano": {"2024": {"contratos": 1, "valor": 1.0}}},
    ]
    monkeypatch.setattr(municipios, "fichas_locais", lambda: fichas)

    resposta = municipios.listar_por_ano_contratos(ano_contratos=2024, distrito="Porto")

    assert resposta["total"] == 1
    assert resposta["items"][0]["nome"] == "Beta"


def test_contratos_dos_anos_recentes_usa_os_anos_do_municipio() -> None:
    """O município mostra os anos dele (desc), não zeros dos anos em que não contratou."""
    pontos = municipios.contratos_dos_anos_recentes(_ficha())

    assert [(ponto["ano"], ponto["contratos"]) for ponto in pontos] == [
        ("2024", 120),
        ("2015", 69),
    ]
    assert pontos[0]["valor"] == 6_500_000.0


def test_contratos_dos_anos_recentes_limita_a_serie() -> None:
    ficha = {
        **_ficha(),
        "contratos_por_ano": {
            str(ano): {"contratos": ano, "valor": float(ano)} for ano in range(2015, 2026)
        },
    }

    pontos = municipios.contratos_dos_anos_recentes(ficha)

    assert [ponto["ano"] for ponto in pontos] == ["2025", "2024", "2023", "2022", "2021"]
    assert len(pontos) == municipios.ANOS_RECENTES


def test_totais_dos_anos_recentes_somam_os_municipios() -> None:
    fichas = [
        {**_ficha("Alfa"), "contratos_por_ano": {"2024": {"contratos": 2, "valor": 200.0}}},
        {
            **_ficha("Beta"),
            "contratos_por_ano": {
                "2024": {"contratos": 9, "valor": 900.0},
                "2023": {"contratos": 4, "valor": 400.0},
            },
        },
    ]

    totais = municipios.totais_dos_anos_recentes(fichas)

    assert totais == [
        {"ano": "2024", "contratos": 11, "valor": 1100.0},
        {"ano": "2023", "contratos": 4, "valor": 400.0},
    ]


def test_anos_recentes_sao_o_arranque_da_serie_completa() -> None:
    anos = municipios.anos_de_contratos(municipios.fichas_locais())

    assert municipios.anos_recentes(municipios.fichas_locais()) == anos[: municipios.ANOS_RECENTES]


def test_lista_por_ano_de_contratos_traz_os_anos_recentes(monkeypatch: pytest.MonkeyPatch) -> None:
    fichas = [{**_ficha("Alfa"), "contratos_por_ano": {"2024": {"contratos": 2, "valor": 200.0}}}]
    monkeypatch.setattr(municipios, "fichas_locais", lambda: fichas)

    resposta = municipios.listar_por_ano_contratos(ano_contratos=2024)

    assert resposta["items"][0]["contratos_recentes"] == [
        {"ano": "2024", "contratos": 2, "valor": 200.0}
    ]


def test_listar_traz_os_anos_recentes_vindos_do_indice(monkeypatch: pytest.MonkeyPatch) -> None:
    """A lista do Elasticsearch também sai com os anos recentes de cada município."""
    from api import elasticsearch_client

    ficha = {
        **_ficha("Alfa"),
        "contratos_por_ano": {
            "2024": {"contratos": 2, "valor": 200.0},
            "2019": {"contratos": 1, "valor": 10.0},
        },
    }
    monkeypatch.setattr(
        elasticsearch_client,
        "search_municipios_despesas",
        lambda **_kwargs: {"total": 1, "items": [ficha]},
    )

    resposta = municipios.listar()

    assert resposta["origem"] == "elasticsearch"
    assert [ponto["ano"] for ponto in resposta["items"][0]["contratos_recentes"]] == ["2024", "2019"]


def test_tipo_de_despesa_usa_a_divisao_de_cpv() -> None:
    assert municipios.tipo_de_despesa("45") == "Obras de construção"
    assert municipios.tipo_de_despesa("55", "Serviços de mesa") == "Hotelaria, restauração e catering"


def test_tipo_de_despesa_cai_na_descricao_do_base() -> None:
    """Divisão desconhecida não fica sem nome: usa a descrição do contrato."""
    assert municipios.tipo_de_despesa("99", "Serviços diversos") == "Serviços diversos"
    assert municipios.tipo_de_despesa("", None) == "CPV —"


def test_nomear_tipos_de_despesa_completa_a_ficha() -> None:
    detalhe: Dict[str, Any] = {
        "cpv": [{"divisao": "45", "descricao": "Obras", "contratos": 3, "valor": 30.0}],
        "ano_cpv": [{"divisao": "79", "descricao": "Consultoria", "contratos": 1, "valor": 10.0}],
    }

    municipios._nomear_tipos_de_despesa(detalhe)

    assert detalhe["cpv"][0]["tipo"] == "Obras de construção"
    assert detalhe["ano_cpv"][0]["tipo"] == "Serviços profissionais, de gestão e consultoria"


def test_ficha_real_do_municipio_traz_a_serie_de_contratos() -> None:
    """A fonte real em disco tem de ter a série anual — é o que a página mostra."""
    fichas = municipios.fichas_locais()
    if not fichas:
        pytest.skip("Sem fichas locais neste ambiente.")

    amostra = next((ficha for ficha in fichas if ficha.get("contratos_por_ano")), None)
    assert amostra is not None
    anos = list(amostra["contratos_por_ano"])
    assert anos and all(ano.isdigit() for ano in anos)
    for valores in amostra["contratos_por_ano"].values():
        assert set(valores) == {"contratos", "valor"}
    assert set(municipios.anos_de_contratos(fichas)) >= set(anos)
