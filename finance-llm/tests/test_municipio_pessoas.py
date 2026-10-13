"""Executivos municipais: os 308 concelhos, a partir do Mapa Oficial da CNE.

Testa-se o que não depende da rede nem do Elasticsearch:

* a construção das fichas a partir do Mapa Oficial — o presidente e os vereadores
  de cada concelho, com o cargo e a sigla por que foram eleitos;
* o identificador, que tem de levar o distrito: «Lagoa» é concelho no Algarve e
  nos Açores, e sem o distrito as duas fichas confundiam-se;
* o casamento dos nomes do site com os do mapa (os municípios abreviam os nomes)
  e o que entra quando o site tem no executivo quem o mapa não tem;
* os dados reais em disco — os 308 concelhos e as 2045 pessoas do Mapa Oficial;
* a substituição do índice, que é o que impede as duas fichas da mesma pessoa.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

import elasticsearch.helpers
import pytest

from api import municipio_pessoas_service as municipios
from api import remuneracoes_service as remuneracoes


# ---------------------------------------------------------------------------
# Dados sintéticos
# ---------------------------------------------------------------------------

def _registo(
    concelho_id: int,
    concelho: str,
    distrito: str,
    presidente: str,
    vereadores: List[str],
) -> Dict[str, Any]:
    return {
        "concelho_id": concelho_id,
        "concelho": concelho,
        "distrito": distrito,
        "codigo_ine": f"{concelho_id:06d}",
        "presidente": {
            "nome": presidente,
            "sigla": "PS",
            "votos": 1000,
            "cargo": "Presidente da Câmara Municipal",
        },
        "vereadores": [
            {"nome": nome, "sigla": "PPD/PSD", "cargo": "Vereador"} for nome in vereadores
        ],
    }


def _mapa() -> Dict[str, Any]:
    """Três concelhos, com os dois «Lagoa» que obrigam o id a levar o distrito."""
    return {
        "fonte_url": "https://www.cne.pt/exemplo.zip",
        "fonte_pagina": "https://www.cne.pt/content/eleicoes-autarquicas-2025",
        "nota": "Mapa de teste",
        "cached_at": "2026-10-13T00:00:00Z",
        "concelhos": {
            "1": _registo(1, "Águeda", "Aveiro", "Jorge Henrique de Almeida", ["Edson Viegas"]),
            "2": _registo(2, "Lagoa", "Faro", "Luís Encarnação", []),
            "3": _registo(3, "Lagoa", "Região Autónoma dos Açores", "Luís Encarnação", []),
        },
    }


def _itens() -> List[Dict[str, Any]]:
    itens: List[Dict[str, Any]] = []
    for registo in _mapa()["concelhos"].values():
        itens.extend(municipios._pessoas_do_mapa(registo))
    return itens


def _registos() -> Dict[Any, Dict[str, Any]]:
    return {
        registo["concelho_id"]: registo for registo in _mapa()["concelhos"].values()
    }


# ---------------------------------------------------------------------------
# Fichas do Mapa Oficial
# ---------------------------------------------------------------------------

def test_cada_concelho_da_um_presidente_e_os_seus_vereadores() -> None:
    itens = _itens()

    assert len(itens) == 4
    agueda = [i for i in itens if i["concelho"] == "Águeda"]
    assert [i["name"] for i in agueda] == ["Jorge Henrique de Almeida", "Edson Viegas"]
    assert [i["role"] for i in agueda] == [municipios.CARGO_PRESIDENTE, municipios.CARGO_VEREADOR]
    assert agueda[0]["party"] == "PS"
    assert agueda[1]["party"] == "PPD/PSD"
    assert agueda[0]["district"] == "Aveiro"
    assert agueda[0]["codigo_ine"] == "000001"
    assert agueda[0]["raw_role"] == "Presidente da Câmara Municipal"
    assert agueda[0]["election"] == municipios.ELEICAO
    assert agueda[0]["mandato"] == municipios.MANDATO
    assert agueda[0]["source"] == municipios.FONTE_CNE
    assert agueda[0]["pelouros"] == []
    assert agueda[0]["photo_url"] is None


def test_o_id_leva_o_distrito_porque_ha_dois_concelhos_com_o_mesmo_nome() -> None:
    itens = [i for i in _itens() if i["concelho"] == "Lagoa"]

    assert len(itens) == 2
    # A mesma pessoa, o mesmo concelho escrito da mesma maneira: só o distrito as
    # distingue — sem ele, uma ficha substituía a outra no índice.
    assert itens[0]["name"] == itens[1]["name"]
    assert len({i["doc_id"] for i in itens}) == 2
    assert itens[0]["doc_id"] == "municipio-faro-lagoa-luis-encarnacao"
    assert itens[1]["doc_id"] == "municipio-regiao-autonoma-dos-acores-lagoa-luis-encarnacao"


def test_registo_sem_presidente_nao_gera_ficha_vazia() -> None:
    registo = _registo(9, "Sem Ninguém", "Aveiro", "", ["Ana Silva"])

    itens = municipios._pessoas_do_mapa(registo)

    assert [i["name"] for i in itens] == ["Ana Silva"]
    assert itens[0]["role"] == municipios.CARGO_VEREADOR


@pytest.mark.parametrize(
    "cargo,esperado",
    [
        ("Presidente", municipios.CARGO_PRESIDENTE),
        ("Presidente da Câmara Municipal", municipios.CARGO_PRESIDENTE),
        ("Vice-Presidente da Câmara Municipal", municipios.CARGO_VICE_PRESIDENTE),
        ("Vereadora", municipios.CARGO_VEREADOR),
        ("Vereador", municipios.CARGO_VEREADOR),
        ("Pelouro da Educação", municipios.CARGO_VEREADOR),
    ],
)
def test_cargos_do_site_reduzem_se_ao_vocabulario_do_modulo(cargo: str, esperado: str) -> None:
    assert municipios._cargo_canonico(cargo) == esperado


def test_cargo_sem_reconhecimento_fica_com_o_do_mapa() -> None:
    assert municipios._cargo_canonico("", municipios.CARGO_PRESIDENTE) == municipios.CARGO_PRESIDENTE


def test_slug_nao_perde_os_acentos() -> None:
    assert municipios._slug("Águeda") == "agueda"
    assert municipios._slug("Região Autónoma dos Açores") == "regiao-autonoma-dos-acores"
    assert municipios._slug("Corte-Real") == "corte-real"


def test_pelouros_vem_em_lista_ou_em_frase() -> None:
    assert municipios._pelouros_de(["Pelouro da Educação"]) == ["Pelouro da Educação"]
    assert municipios._pelouros_de("Pelouro da Segurança e Pelouro das Finanças") == [
        "Pelouro da Segurança",
        "Pelouro das Finanças",
    ]
    assert municipios._pelouros_de(None) == []
    # O que o município escreveu fora dessa forma guarda-se como está: mais vale
    # o texto do site do que perder o pelouro.
    assert municipios._pelouros_de("Educação e Cultura") == ["Educação e Cultura"]


def test_indice_de_concelhos_marca_os_nomes_ambiguos() -> None:
    indice = municipios._indice_concelhos(_mapa()["concelhos"])

    assert indice["agueda"] == 1
    assert indice["lagoa"] is None


# ---------------------------------------------------------------------------
# Detalhes dos sites das câmaras
# ---------------------------------------------------------------------------

def _entrada(
    concelho_id: int,
    membros: List[Dict[str, Any]],
    site: str | None = None,
    site_url: str | None = None,
) -> Dict[str, Any]:
    """Entrada de detalhes, tal como o serviço a constrói a partir de um site."""
    return {
        "concelho_id": concelho_id,
        "concelho": None,
        "membros": [municipios._membro_do_site(m, site, site_url) for m in membros],
    }


def test_detalhes_do_site_casam_com_o_nome_abreviado_do_municipio() -> None:
    itens = _itens()
    entradas = [
        _entrada(
            1,
            [
                {
                    "nome": "Jorge de Almeida",
                    "cargo": "Presidente",
                    "partido": "PS",
                    "atribuicoes": "Pelouro da Segurança e Pelouro das Finanças",
                    "url": "https://www.cm-agueda.pt/executivo/jorge-de-almeida",
                    "photo_url": "https://www.cm-agueda.pt/foto.jpg",
                },
            ],
            site="cm-agueda",
            site_url="https://www.cm-agueda.pt/executivo",
        ),
    ]

    resultado = municipios._aplicar_detalhes(itens, entradas, _registos())

    assert len(resultado) == len(itens)
    alvo = next(i for i in resultado if i["name"] == "Jorge Henrique de Almeida")
    assert alvo["role"] == municipios.CARGO_PRESIDENTE
    assert alvo["pelouros"] == ["Pelouro da Segurança", "Pelouro das Finanças"]
    assert alvo["profile_url"] == "https://www.cm-agueda.pt/executivo/jorge-de-almeida"
    assert alvo["photo_url"] == "https://www.cm-agueda.pt/foto.jpg"
    assert alvo["source"] == "cm-agueda"
    assert alvo["source_url"] == "https://www.cm-agueda.pt/executivo"


def test_detalhes_do_site_nao_cruzam_concelhos_com_o_mesmo_nome() -> None:
    itens = _itens()
    entradas = [
        _entrada(2, [{"nome": "Luís Encarnação", "cargo": "Presidente"}], site="cm-lagoa-faro"),
    ]

    resultado = municipios._aplicar_detalhes(itens, entradas, _registos())

    faro = next(i for i in resultado if i["doc_id"].startswith("municipio-faro-lagoa"))
    acores = next(i for i in resultado if i["doc_id"].startswith("municipio-regiao-autonoma"))

    assert faro["source"] == "cm-lagoa-faro"
    assert acores["source"] == municipios.FONTE_CNE


def test_quem_o_site_tem_e_o_mapa_nao_entra_como_substituto() -> None:
    itens = _itens()
    entradas = [
        _entrada(
            1,
            [{"nome": "Helena Maia", "cargo": "Vereadora", "partido": "PS"}],
            site="cm-agueda",
        ),
    ]

    resultado = municipios._aplicar_detalhes(itens, entradas, _registos())

    assert len(resultado) == len(itens) + 1
    extra = next(i for i in resultado if i["name"] == "Helena Maia")
    assert extra["role"] == municipios.CARGO_VEREADOR
    assert extra["party"] == "PS"
    assert extra["concelho"] == "Águeda"
    assert extra["district"] == "Aveiro"
    assert extra["source"] == "cm-agueda"
    # O id é o mesmo género dos outros: é uma pessoa do executivo daquele concelho.
    assert extra["doc_id"] == "municipio-aveiro-agueda-helena-maia"


def test_site_com_o_nome_de_uma_camara_fica_so_com_o_primeiro_rotulo() -> None:
    assert municipios._site_do_url("https://www.cm-porto.pt/executivo") == "cm-porto"
    assert municipios._site_do_url("https://cm-porto.pt/executivo") == "cm-porto"
    assert municipios._site_do_url(None) is None


# ---------------------------------------------------------------------------
# Recolha completa
# ---------------------------------------------------------------------------

def test_recolha_junta_o_mapa_e_os_sites(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(municipios, "_mapa_oficial", _mapa)
    monkeypatch.setattr(
        remuneracoes,
        "executivos",
        lambda: {
            "fonte": {"documento": "sites dos municípios"},
            "concelhos": {
                "Águeda": {
                    "concelho_id": 1,
                    "nome": "Águeda",
                    "fonte_url": "https://www.cm-agueda.pt/executivo",
                    "membros": [
                        {"nome": "Jorge de Almeida", "cargo": "Presidente", "partido": "PS"},
                        {"nome": "Helena Maia", "cargo": "Vereadora", "partido": "PS"},
                    ],
                },
            },
        },
    )
    monkeypatch.setattr(
        municipios,
        "scrape_cm_porto",
        lambda refresh=False: {"error": "sem rede"},
    )

    resultado = municipios.collect_executivos()

    assert resultado["concelhos"] == 3
    assert resultado["total"] == 5
    assert [fonte["documento"] for fonte in resultado["fontes"]] == [
        municipios.FONTE_CNE_DOCUMENTO,
        "sites dos municípios",
    ]
    nomes = {i["name"] for i in resultado["items"]}
    assert nomes == {"Jorge Henrique de Almeida", "Edson Viegas", "Luís Encarnação", "Helena Maia"}
    jorge = next(i for i in resultado["items"] if i["name"] == "Jorge Henrique de Almeida")
    assert jorge["source"] == "cm-agueda"
    assert jorge["source_url"] == "https://www.cm-agueda.pt/executivo"


def test_recolha_sem_mapa_avisa_em_vez_de_indexar_vazio(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(municipios, "_mapa_oficial", dict)

    resultado = municipios.collect_executivos()

    assert resultado["error"]
    assert resultado["items"] == []


def test_mapa_oficial_real_tem_os_308_concelhos(monkeypatch: pytest.MonkeyPatch) -> None:
    """O ficheiro em disco é a base da recolha: se vier truncado, o módulo mente."""
    monkeypatch.setattr(municipios, "scrape_cm_porto", lambda refresh=False: {"error": "sem rede"})

    resultado = municipios.collect_executivos()
    itens = resultado["items"]

    assert resultado["concelhos"] == 308
    assert resultado["total"] >= 2045
    assert len({i["doc_id"] for i in itens}) == len(itens)
    assert all(i["name"].strip() and i["concelho"].strip() and i["district"].strip() for i in itens)
    assert {i["role"] for i in itens} <= {
        municipios.CARGO_PRESIDENTE,
        municipios.CARGO_VICE_PRESIDENTE,
        municipios.CARGO_VEREADOR,
    }
    assert sum(1 for i in itens if i["role"] == municipios.CARGO_PRESIDENTE) == 308
    assert len([i for i in itens if i["concelho"] == "Porto"]) >= 13


# ---------------------------------------------------------------------------
# Consulta
# ---------------------------------------------------------------------------

class _BuscaFalsa:
    """Um cliente que só guarda o corpo das consultas que lhe chegam."""

    def __init__(self, resposta: Dict[str, Any] | None = None) -> None:
        self.corpos: List[Dict[str, Any]] = []
        self.resposta = resposta or {"hits": {"total": {"value": 0}, "hits": []}}

    def search(self, index: str, body: Dict[str, Any]) -> Dict[str, Any]:
        self.corpos.append(body)
        return self.resposta

    def count(self, index: str) -> Dict[str, Any]:
        # Um índice com documentos: `stats` só agrega quando há o que agregar.
        return {"count": 1}


@pytest.fixture()
def sem_indices(monkeypatch: pytest.MonkeyPatch) -> None:
    """As consultas testam-se sem passar pela criação dos índices."""
    monkeypatch.setattr(municipios, "ensure_indices", lambda client: True)


def test_filtros_procuram_em_campos_que_existem(sem_indices: None) -> None:
    """`role` e `pelouros` são `keyword`: procurar em `role.keyword` não acha nada."""
    cliente = _BuscaFalsa()

    municipios.search_municipio_pessoas(
        q="Presidente",
        role="Presidente",
        concelho="Porto",
        district="Porto",
        party="PS",
        es=cliente,
    )

    texto = json.dumps(cliente.corpos[0], ensure_ascii=False)
    for frase in ('role.keyword', 'pelouros.keyword'):
        assert frase not in texto
    for campo in ('"role"', '"pelouros"', '"concelho.keyword"', '"district.keyword"'):
        assert campo in texto


def test_agregacoes_agrupam_pelos_campos_indexados(sem_indices: None) -> None:
    cliente = _BuscaFalsa({"aggregations": {}})

    municipios.stats(es=cliente)

    aggs = cliente.corpos[0]["aggs"]
    assert aggs["by_role"]["terms"]["field"] == "role"
    assert aggs["by_concelho"]["terms"]["size"] >= 308
    assert aggs["by_district"]["aggs"]["concelhos"]["terms"]["field"] == "concelho.keyword"


# ---------------------------------------------------------------------------
# Indexação
# ---------------------------------------------------------------------------

class _IndicesFalsos:
    """O pouco do `client.indices` de que a indexação precisa."""

    def __init__(self) -> None:
        self.eventos: List[str] = []

    def delete(self, index: str, **kwargs: Any) -> None:
        self.eventos.append(f"delete:{index}")

    def exists(self, index: str) -> bool:
        return False

    def create(self, index: str, body: Dict[str, Any]) -> None:
        self.eventos.append(f"create:{index}")

    def get_mapping(self, index: str) -> Dict[str, Any]:
        return {index: {"mappings": {"properties": {}}}}

    def put_mapping(self, index: str, body: Dict[str, Any]) -> None:
        self.eventos.append(f"put_mapping:{index}")

    def refresh(self, index: str) -> None:
        self.eventos.append(f"refresh:{index}")


class _ESFalso:
    def __init__(self) -> None:
        self.indices = _IndicesFalsos()
        self.acoes: List[Dict[str, Any]] = []


@pytest.fixture()
def es_falso(monkeypatch: pytest.MonkeyPatch) -> _ESFalso:
    cliente = _ESFalso()

    def _bulk(client: _ESFalso, actions: List[Dict[str, Any]], **kwargs: Any) -> Any:
        client.acoes.extend(actions)
        return len(actions), []

    monkeypatch.setattr(elasticsearch.helpers, "bulk", _bulk)
    return cliente


def test_indexar_substitui_o_indice_antes_de_escrever(es_falso: _ESFalso) -> None:
    itens = _itens()

    resultado = municipios.index_municipio_pessoas(itens, es=es_falso, substituir=True)

    assert resultado["indexed"] == len(itens)
    assert es_falso.indices.eventos[0] == f"delete:{municipios.MUNICIPIO_PESSOAS_INDEX}"
    assert f"refresh:{municipios.MUNICIPIO_PESSOAS_INDEX}" in es_falso.indices.eventos
    assert [acao["_id"] for acao in es_falso.acoes] == [i["doc_id"] for i in itens]


def test_indexar_sem_substituir_nao_apaga_o_indice(es_falso: _ESFalso) -> None:
    municipios.index_municipio_pessoas(_itens(), es=es_falso)

    assert not [e for e in es_falso.indices.eventos if e.startswith("delete:")]


def test_reindexar_o_mesmo_mapa_mantem_os_identificadores(es_falso: _ESFalso) -> None:
    municipios.index_municipio_pessoas(_itens(), es=es_falso, substituir=True)
    primeiros = [acao["_id"] for acao in es_falso.acoes]
    es_falso.acoes.clear()

    municipios.index_municipio_pessoas(_itens(), es=es_falso, substituir=True)

    assert [acao["_id"] for acao in es_falso.acoes] == primeiros


def test_actualizacao_completa_devolve_o_resumo_da_recolha(
    es_falso: _ESFalso,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(municipios, "_mapa_oficial", _mapa)
    monkeypatch.setattr(
        remuneracoes,
        "executivos",
        lambda: {"fonte": {"documento": "sites dos municípios"}, "concelhos": {}},
    )
    monkeypatch.setattr(municipios, "scrape_cm_porto", lambda refresh=False: {"error": "sem rede"})
    monkeypatch.setattr(municipios, "get_es_client", lambda: es_falso)

    resultado = municipios.refresh_executivos()

    assert resultado["concelhos"] == 3
    assert resultado["total"] == 4
    assert resultado["indexed"] == 4
    assert resultado["errors"] == 0
    assert resultado["fontes"] == [municipios.FONTE_CNE_DOCUMENTO]
    assert resultado["refreshed_at"]
