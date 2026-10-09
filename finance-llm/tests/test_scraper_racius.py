"""Testes do template do Racius e das extensões do motor de recolha.

Cobre as duas peças novas de que a recolha do diretório do Racius depende:

* `pagination.mode="query"` — a página é um parâmetro do URL (`?page=2`), e não
  uma ligação «seguinte»;
* `detail.pairs` — a ficha da empresa como dicionário `{rótulo: valor}` no item
  (é o que dá «dados diferentes» por empresa sem um campo por cada linha).

Junta-se a validação do template `racius-diretorio`: seletores da lista, campos
e identidade do item.
"""
from __future__ import annotations

from api import scraper_service as scraper
from api import scraper_templates as templates

LIST_HTML = """
<a class="results__col-link" href="/empresa-exemplo-lda/">
  <article class="results__entry">
    <p class="results__name"> Empresa Exemplo, Lda</p>
    <p class="results__activity"> NIF: 500083002</p>
    <div class="results__col-location"> <span class="ico">ico-gps</span> Santarem, Santarem</div>
  </article>
</a>
"""

DETAIL_HTML = """
<ul>
  <li class="detail__detail">
    <p class="detail__key-info"> Morada</p><p class="t--d-blue"> Rua A 1</p>
    <p class="detail__key-info"> Santarem</p><p class="t--d-blue"> Santarem</p>
  </li>
  <li class="detail__detail">
    <p class="detail__key-info"> Forma Juridica</p><p class="t--d-blue"> Sociedade por Quotas</p>
    <p class="detail__key-info"> Capital Social</p><p class="t--d-blue"> 1000</p>
  </li>
</ul>
"""


def _page(html: str):
    from scrapling.parser import Adaptor

    return Adaptor(html, url="https://www.racius.com/")


# --------------------------------------------------------------- paginação
def test_paginacao_query_normaliza_parametro_e_inicio():
    pagination = scraper._normalize_pagination({"mode": "query", "param": "page", "start": 1, "max_pages": 5})
    assert pagination["mode"] == "query"
    assert pagination["param"] == "page"
    assert pagination["start"] == 1
    assert pagination["max_pages"] == 5


def test_paginacao_sem_modo_mantem_ligacao():
    pagination = scraper._normalize_pagination({"selector": "a.next", "max_pages": 3})
    assert pagination["mode"] == "link"
    assert pagination["selector"] == "a.next"


def test_paginacao_postback_tem_prioridade_sobre_o_modo():
    pagination = scraper._normalize_pagination({"type": "postback", "mode": "query"})
    assert pagination["mode"] == "postback"


def test_url_da_pagina_incrementa_o_parametro():
    base = "https://www.racius.com/pesquisa/empresas/?q=galp"
    pagination = {"param": "page", "start": 1}
    first = scraper._page_query_url(base, pagination, 2)
    second = scraper._page_query_url(base, pagination, 3)
    assert first == "https://www.racius.com/pesquisa/empresas/?q=galp&page=2"
    assert second == "https://www.racius.com/pesquisa/empresas/?q=galp&page=3"


def test_url_da_pagina_substitui_parametro_existente():
    base = "https://www.racius.com/pesquisa/empresas/?q=galp&page=1"
    url = scraper._page_query_url(base, {"param": "page", "start": 1}, 4)
    assert url.count("page=") == 1
    assert url.endswith("page=4")


# ---------------------------------------------------------------- detalhe
def test_detalhe_com_pares_fica_ligado_sem_seletor_de_texto():
    detail = scraper._normalize_detail(
        {
            "enabled": True,
            "selector": "",
            "pairs": {
                "enabled": True,
                "container": "li.detail__detail",
                "key_selector": "p.detail__key-info",
                "value_selector": "p.t--d-blue",
            },
        }
    )
    assert detail["enabled"] is True
    assert detail["pairs"]["enabled"] is True
    assert detail["pairs"]["field"] == "ficha"


def test_detalhe_sem_seletor_nem_pares_fica_desligado():
    detail = scraper._normalize_detail({"enabled": True, "selector": ""})
    assert detail["enabled"] is False
    assert detail["pairs"]["enabled"] is False


def test_detalhe_so_com_selector_mantem_comportamento_antigo():
    detail = scraper._normalize_detail({"enabled": True, "selector": "div.body"})
    assert detail["enabled"] is True
    assert detail["selector"] == "div.body"
    assert detail["pairs"]["enabled"] is False


def test_extracao_de_pares_da_ficha():
    pairs = {
        "enabled": True,
        "container": "li.detail__detail",
        "key_selector": "p.detail__key-info",
        "value_selector": "p.t--d-blue",
        "field": "ficha",
        "max_pairs": 60,
    }
    ficha = scraper._extract_pairs(_page(DETAIL_HTML), pairs)
    assert ficha == {
        "Morada": "Rua A 1",
        "Santarem": "Santarem",
        "Forma Juridica": "Sociedade por Quotas",
        "Capital Social": "1000",
    }


def test_pares_desligados_devolvem_vazio():
    assert scraper._extract_pairs(_page(DETAIL_HTML), {"enabled": False}) == {}


# --------------------------------------------------------------- template
def test_template_racius_define_lista_campos_e_ficha():
    source = templates.build_source("racius-diretorio")
    assert source["url"].startswith("https://www.racius.com/pesquisa/empresas/")
    assert source["list"]["selector"] == "a.results__col-link"
    assert [f["name"] for f in source["fields"]] == [
        "nome",
        "nif",
        "localizacao",
        "concelho",
        "distrito",
        "url",
    ]
    assert source["pagination"]["mode"] == "query"
    assert source["pagination"]["param"] == "page"
    assert source["id_fields"] == ["nif", "url"]
    assert source["detail"]["enabled"] is True
    pairs = source["detail"]["pairs"]
    assert pairs["field"] == "ficha"
    # A ficha alimenta o índice de diretório (facetas e filtros).
    assert source["sink_index"] == "finance_racius"
    assert pairs["fields"]["Forma Jurídica"] == {"field": "forma_juridica", "cast": "text"}
    assert pairs["fields"]["Capital Social"] == {"field": "capital_social_eur", "cast": "float"}


def test_normalizacao_dos_rotulos_da_ficha():
    pairs = scraper._normalize_detail_pairs(
        {
            "enabled": True,
            "key_selector": "p.k",
            "value_selector": "p.v",
            "fields": {"Morada": "morada", "Capital Social": {"field": "capital_social_eur", "cast": "float"}, "": "ignorar"},
        }
    )
    assert pairs["fields"] == {
        "Morada": {"field": "morada", "cast": "text"},
        "Capital Social": {"field": "capital_social_eur", "cast": "float"},
    }


def test_extracao_da_lista_com_os_campos_do_template():
    source = templates.build_source("racius-diretorio")
    items = scraper._extract_items(_page(LIST_HTML), source)
    assert len(items) == 1
    data = items[0]["data"]
    assert data["nome"] == "Empresa Exemplo, Lda"
    assert data["nif"] == "500083002"
    assert data["url"] == "https://www.racius.com/empresa-exemplo-lda/"
    assert "ico-gps" not in data["localizacao"]
    assert data["localizacao"] == "Santarem, Santarem"
    # O distrito/concelho alimentam as facetas da página do diretório.
    assert data["concelho"] == "Santarem"
    assert data["distrito"] == "Santarem"


def test_pares_normalizados_entram_no_item_como_campos_proprios():
    detail = scraper._normalize_detail(
        {
            "enabled": True,
            "selector": "",
            "pairs": {
                "enabled": True,
                "container": "li.detail__detail",
                "key_selector": "p.detail__key-info",
                "value_selector": "p.t--d-blue",
                "fields": {"Capital Social": {"field": "capital_social_eur", "cast": "float"}},
            },
        }
    )
    pairs = scraper._extract_pairs(_page(DETAIL_HTML), detail["pairs"])
    assert pairs["Capital Social"] == "1000"
    # `cast: float` converte para número (é o que se filtra/ordena no índice).
    assert scraper._cast(pairs["Capital Social"], {"cast": "float"}) == 1000.0
