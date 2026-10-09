"""Pesquisa de entidades (`/companies/search`) — contrato e filtros.

Cobre o que não depende do Elasticsearch: o modelo de resposta (o offset pedido
tem de voltar no campo `from`) e a seleção das entidades em `search_companies`
(papel pedido, paginação e aviso de lista limitada), com um cliente falso.
"""
from __future__ import annotations

from typing import Any, Dict, List

import pytest

from api import elasticsearch_client as esc
from api.models import CompanySearchResponse


# ------------------------------------------------------------------- fábricas
def _bucket(nif: str, nome: str, doc_count: int, valor: float) -> Dict[str, Any]:
    return {
        "key": nif,
        "doc_count": doc_count,
        "name": {"hits": {"hits": [{"_source": {"nome": nome}}]}},
        "total_value": {"value": {"value": valor}},
        "years": {"stats": {"min": 2015, "max": 2025}},
    }


def _resposta(
    adjudicantes: List[Dict[str, Any]],
    adjudicatarios: List[Dict[str, Any]],
    *,
    distintos_adjudicantes: int = 0,
    distintos_adjudicatarios: int = 0,
    truncado_adjudicantes: int = 0,
    truncado_adjudicatarios: int = 0,
) -> Dict[str, Any]:
    return {
        "aggregations": {
            "adjudicantes": {
                "by_nif": {"buckets": adjudicantes, "sum_other_doc_count": truncado_adjudicantes}
            },
            "adjudicatarios": {
                "by_nif": {"buckets": adjudicatarios, "sum_other_doc_count": truncado_adjudicatarios}
            },
            "unique_adjudicantes": {"nifs": {"value": distintos_adjudicantes or len(adjudicantes)}},
            "unique_adjudicatarios": {"nifs": {"value": distintos_adjudicatarios or len(adjudicatarios)}},
        }
    }


class _FakeES:
    """Cliente mínimo: devolve sempre a mesma resposta de agregações."""

    def __init__(self, resposta: Dict[str, Any]) -> None:
        self.resposta = resposta

    def search(self, **_kwargs: Any) -> Dict[str, Any]:
        return self.resposta


@pytest.fixture
def sem_indices(monkeypatch: pytest.MonkeyPatch) -> None:
    """`search_companies` garante os índices antes de pesquisar; aqui não é preciso."""
    monkeypatch.setattr(esc, "ensure_indices", lambda *_args, **_kwargs: True)


# ---------------------------------------------------------------------- dados
# `B` é adjudicante e adjudicatário; `A` só adjudicante; `C` só adjudicatário.
BUCKETS_ADJUDICANTES = [
    _bucket("100000001", "Empresa A", 5, 1000.0),
    _bucket("100000002", "Empresa B", 3, 800.0),
]
BUCKETS_ADJUDICATARIOS = [
    _bucket("100000002", "Empresa B", 7, 700.0),
    _bucket("100000003", "Empresa C", 2, 500.0),
]


def _search(monkeypatch, resposta, **kwargs) -> Dict[str, Any]:
    monkeypatch.setattr(esc, "get_es_client", lambda: _FakeES(resposta))
    return esc.search_companies(es=_FakeES(resposta), include_cae=False, **kwargs)


# ------------------------------------------------------- offset na resposta
def test_resposta_devolve_o_offset_pedido():
    """O campo `from` da resposta tem de refletir o offset, não o valor por omissão."""
    resposta = CompanySearchResponse(query="mota", total=968, items=[], from_=15, size=15)

    assert resposta.from_ == 15
    assert resposta.model_dump(by_alias=True)["from"] == 15
    # O JSON público mantém a chave `from` (o tipo do frontend não muda).
    assert "from_" not in resposta.model_dump(by_alias=True)


def test_resposta_sem_offset_pedido_mantem_zero():
    """Sem offset explícito, o valor por omissão continua a ser 0."""
    assert CompanySearchResponse().model_dump(by_alias=True)["from"] == 0


# ------------------------------------------------------------- filtro de papel
def test_sem_filtro_de_papel_junta_os_dois_papeis(monkeypatch, sem_indices):
    """Sem papel pedido, a lista continua a juntar adjudicantes e adjudicatários."""
    res = _search(monkeypatch, _resposta(BUCKETS_ADJUDICANTES, BUCKETS_ADJUDICATARIOS), role="all")

    assert [item["nif"] for item in res["items"]] == ["100000002", "100000001", "100000003"]
    assert res["total"] == 3
    # `B` aparece nos dois papéis: os totais somam os dois contratos agregados.
    b = next(item for item in res["items"] if item["nif"] == "100000002")
    assert b["contracts_total"] == 10
    assert b["total_value"] == pytest.approx(1500.0)


def test_filtro_adjudicante_devolve_so_quem_adjudica(monkeypatch, sem_indices):
    """Pedir adjudicantes não pode devolver os adjudicatários desses contratos."""
    res = _search(monkeypatch, _resposta(BUCKETS_ADJUDICANTES, BUCKETS_ADJUDICATARIOS), role="adjudicante")

    assert [item["nif"] for item in res["items"]] == ["100000002", "100000001"]
    assert res["total"] == 2
    assert all(item["adjudicante"] for item in res["items"])
    assert "100000003" not in {item["nif"] for item in res["items"]}


def test_filtro_adjudicatario_devolve_so_quem_e_adjudicatario(monkeypatch, sem_indices):
    res = _search(monkeypatch, _resposta(BUCKETS_ADJUDICANTES, BUCKETS_ADJUDICATARIOS), role="adjudicatario")

    assert [item["nif"] for item in res["items"]] == ["100000002", "100000003"]
    assert res["total"] == 2
    assert all(item["adjudicatario"] for item in res["items"])
    assert "100000001" not in {item["nif"] for item in res["items"]}


def test_paginacao_desloca_sem_mudar_o_total(monkeypatch, sem_indices):
    """O offset move a página, mas o total mantém-se o da lista filtrada."""
    resposta = _resposta(BUCKETS_ADJUDICANTES, BUCKETS_ADJUDICATARIOS)
    primeira = _search(monkeypatch, resposta, role="adjudicante", size=1)
    segunda = _search(monkeypatch, resposta, role="adjudicante", size=1, from_=1)

    assert [item["nif"] for item in primeira["items"]] == ["100000002"]
    assert [item["nif"] for item in segunda["items"]] == ["100000001"]
    assert primeira["total"] == segunda["total"] == 2
    assert segunda["from"] == 1


def test_avisa_quando_a_lista_fica_abaixo_do_universo(monkeypatch, sem_indices):
    """Universo maior que a lista agregada: fica um aviso em vez de total enganador."""
    resposta = _resposta(
        BUCKETS_ADJUDICANTES,
        BUCKETS_ADJUDICATARIOS,
        distintos_adjudicantes=11127,
    )
    res = _search(monkeypatch, resposta, role="adjudicante")

    assert res["total"] == 2
    assert "11127" in " ".join(res["notes"])


def test_sem_aviso_quando_a_lista_cobre_o_universo(monkeypatch, sem_indices):
    """Com a lista completa, não há aviso a mostrar."""
    res = _search(monkeypatch, _resposta(BUCKETS_ADJUDICANTES, BUCKETS_ADJUDICATARIOS), role="adjudicante")

    assert res["notes"] == []


def test_min_value_filtra_antes_do_papel(monkeypatch, sem_indices):
    """Os filtros de valor continuam a aplicar-se por entidade, em cada papel."""
    res = _search(monkeypatch, _resposta(BUCKETS_ADJUDICANTES, BUCKETS_ADJUDICATARIOS), role="all", min_value=600)

    assert [item["nif"] for item in res["items"]] == ["100000002", "100000001"]
    assert res["total"] == 2


# ------------------------------------------------------- pesquisa por nome/NIF
class _ESComBaldes:
    """Cliente falso que devolve os baldes indicados e regista a query enviada."""

    def __init__(self, resposta: Dict[str, Any]) -> None:
        self.resposta = resposta
        self.pedidos: List[Dict[str, Any]] = []

    def search(self, **kwargs: Any) -> Dict[str, Any]:
        self.pedidos.append(kwargs)
        return self.resposta


def test_pesquisa_por_nome_so_devolve_entidades_com_esse_nome(monkeypatch, sem_indices):
    """A pesquisa por nome não pode devolver as contrapartes dos contratos."""
    resposta = _resposta(BUCKETS_ADJUDICANTES, BUCKETS_ADJUDICATARIOS)
    cliente = _ESComBaldes(resposta)
    res = esc.search_companies(es=cliente, include_cae=False, q="empresa a")

    assert [item["name"] for item in res["items"]] == ["Empresa A"]
    assert res["total"] == 1
    assert res["unique_adjudicantes"] == 1
    assert res["unique_adjudicatarios"] == 0


def test_pesquisa_por_nome_ignora_acentos_e_ordem(monkeypatch, sem_indices):
    """A comparação é sem acentos e cada termo casa o início de uma palavra."""
    bucket = _bucket("100000009", "CONSTRUÇÕES SÃO JOÃO, LDA", 4, 900.0)
    resposta = _resposta([bucket], [])
    cliente = _ESComBaldes(resposta)

    assert esc.search_companies(es=cliente, include_cae=False, q="construcoes sao")["total"] == 1
    assert esc.search_companies(es=cliente, include_cae=False, q="joao construcoes")["total"] == 1
    assert esc.search_companies(es=cliente, include_cae=False, q="construcoes lisboa")["total"] == 0


def test_pesquisa_por_nif_devolve_so_a_entidade(monkeypatch, sem_indices):
    """Um NIF identifica uma entidade, não os contratos em que aparece."""
    resposta = _resposta(BUCKETS_ADJUDICANTES, BUCKETS_ADJUDICATARIOS)
    cliente = _ESComBaldes(resposta)
    res = esc.search_companies(es=cliente, include_cae=False, q="100000003")

    assert [item["name"] for item in res["items"]] == ["Empresa C"]
    assert res["total"] == 1


def test_pesquisa_por_nome_alarga_a_janela_dos_papeis(monkeypatch, sem_indices):
    """Com pesquisa textual a janela por papel cresce (caberem as correspondências)."""
    resposta = _resposta(BUCKETS_ADJUDICANTES, BUCKETS_ADJUDICATARIOS)
    cliente = _ESComBaldes(resposta)

    def janela(**kwargs: Any) -> int:
        esc.search_companies(es=cliente, include_cae=False, **kwargs)
        corpo = cliente.pedidos[-1]["body"]
        return corpo["aggs"]["adjudicantes"]["aggs"]["by_nif"]["terms"]["size"]

    assert janela(q="empresa") > janela()


def test_pesquisa_por_nome_avisa_quando_a_janela_foi_cortada(monkeypatch, sem_indices):
    """Nome comum: avisa que pode haver mais correspondências do que as listadas."""
    resposta = _resposta(BUCKETS_ADJUDICANTES, BUCKETS_ADJUDICATARIOS, truncado_adjudicatarios=3000)
    cliente = _ESComBaldes(resposta)

    res = esc.search_companies(es=cliente, include_cae=False, q="empresa")

    assert any("pode haver mais resultados" in nota for nota in res["notes"])


def test_pesquisa_por_nome_sem_aviso_quando_a_janela_esta_completa(monkeypatch, sem_indices):
    """Janela completa: nada a avisar."""
    resposta = _resposta(BUCKETS_ADJUDICANTES, BUCKETS_ADJUDICATARIOS)
    cliente = _ESComBaldes(resposta)

    res = esc.search_companies(es=cliente, include_cae=False, q="empresa")

    assert res["notes"] == []
