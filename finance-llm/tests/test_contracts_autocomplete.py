"""Autocomplete de contratos (`/contracts/autocomplete`) — consulta e sugestões.

Regressão do 502 que o endpoint devolvia a **qualquer** pesquisa: as partes do
contrato (`adjudicantes.parsed.nome`) são `keyword` no índice real, e o código
usava `match_phrase_prefix` (só existe para `text`) na consulta e um campo
`.keyword` inexistente na agregação — o Elasticsearch respondia 400 e o endpoint
traduzia isso num 502.

Estes testes fixam o contrato: (a) a consulta enviada não usa
`match_phrase_prefix` sobre as partes, usa `prefix` com `case_insensitive`;
(b) o texto do utilizador nunca entra em `include` de agregação (este cluster
recusa a forma com objeto e devolve zero baldes com a forma de string);
(c) a filtragem do texto é feita em Python, sem distinguir maiúsculas.
"""
from __future__ import annotations

from typing import Any, Dict, List

import pytest

from api import elasticsearch_client as esc


@pytest.fixture(autouse=True)
def _limpar_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """A resolução do campo do nome é memorizada no módulo (uma vez por índice)."""
    monkeypatch.setattr(esc, "_PARTE_NOME_CACHE", {})


class _FakeES:
    """Cliente mínimo: guarda o corpo do pedido e devolve a resposta preparada."""

    def __init__(self, resposta: Dict[str, Any], mapping: Dict[str, Any] | None = None) -> None:
        self.resposta = resposta
        self.mapping = mapping
        self.pedidos: List[Dict[str, Any]] = []

    def search(self, **kwargs: Any) -> Dict[str, Any]:
        self.pedidos.append(kwargs)
        return self.resposta

    class _Indices:
        def __init__(self, outer: "_FakeES") -> None:
            self.outer = outer

        def get_mapping(self, index: str | None = None) -> Dict[str, Any]:
            if self.outer.mapping is None:
                raise RuntimeError("sem mapping no cliente falso")
            return self.outer.mapping

    @property
    def indices(self) -> "_FakeES._Indices":
        return _FakeES._Indices(self)


def _balde(nome: str, doc_count: int) -> Dict[str, Any]:
    return {"key": nome, "doc_count": doc_count}


def _resposta(
    adjudicantes: List[Dict[str, Any]],
    adjudicatarios: List[Dict[str, Any]],
    cpvs: List[Dict[str, Any]],
) -> Dict[str, Any]:
    return {
        "aggregations": {
            "adjudicantes": {"names": {"buckets": adjudicantes}},
            "adjudicatarios": {"names": {"buckets": adjudicatarios}},
            "cpv_codes": {"codes": {"buckets": cpvs}},
        }
    }


def _corpo(cliente: _FakeES) -> Dict[str, Any]:
    assert cliente.pedidos, "não foi feito nenhum pedido ao Elasticsearch"
    return cliente.pedidos[-1]["body"]


def _textos(consulta: Dict[str, Any]) -> str:
    return str(consulta)


def test_consulta_usa_prefix_keyword_e_nao_phrase_prefix():
    cliente = _FakeES(_resposta([], [], []))
    esc.contracts_autocomplete(q="janssen", size=6, es=cliente)
    corpo = _corpo(cliente)
    consulta = corpo["query"]

    # `match_phrase_prefix` continua válido para os campos de texto do contrato…
    assert "match_phrase_prefix" in _textos(consulta["bool"]["should"][0])
    # …mas não pode aparecer nas partes (são keyword: davam 400 → 502).
    ramo_partes = consulta["bool"]["should"][2]
    assert "match_phrase_prefix" not in _textos(ramo_partes)
    assert ramo_partes["bool"]["should"][0]["nested"]["query"]["prefix"]["adjudicantes.parsed.nome"] == {
        "value": "janssen",
        "case_insensitive": True,
    }
    assert ramo_partes["bool"]["should"][1]["nested"]["query"]["prefix"]["adjudicatarios.parsed.nome"] == {
        "value": "janssen",
        "case_insensitive": True,
    }


def test_agregacoes_nao_levam_include_e_apanham_o_campo_real():
    cliente = _FakeES(_resposta([], [], []))
    esc.contracts_autocomplete(q="janssen", size=6, es=cliente)
    corpo = _corpo(cliente)

    nomes = corpo["aggs"]["adjudicantes"]["aggs"]["names"]["terms"]
    assert nomes["field"] == "adjudicantes.parsed.nome"
    assert "include" not in nomes
    assert corpo["aggs"]["adjudicatarios"]["aggs"]["names"]["terms"]["field"] == "adjudicatarios.parsed.nome"
    assert "include" not in corpo["aggs"]["cpv_codes"]["aggs"]["codes"]["terms"]
    # O topo por contagem tem de ser maior do que o pedido: o filtro é em Python.
    assert nomes["size"] >= 6 * 8


def test_filtra_nomes_em_python_sem_distinguir_maiusculas():
    cliente = _FakeES(
        _resposta(
            [
                _balde("Unidade Local de Saúde do Norte Alentejano", 577),
                _balde("Instituto Português de Oncologia do Porto", 664),
            ],
            [
                _balde("JANSSEN CILAG FARMACEUTICA", 3082),
                _balde("Janssen Cilag Farmacêutica", 723),
            ],
            [_balde("33600000-6", 475), _balde("45200000-9", 10)],
        )
    )
    resultado = esc.contracts_autocomplete(q="jan", size=10, es=cliente)
    assert "error" not in resultado
    textos = [item["text"] for item in resultado["suggestions"]]
    # «alentejano» contém «jan» (filtro é «contém», não «começa por»)…
    assert "Unidade Local de Saúde do Norte Alentejano" in textos
    assert "JANSSEN CILAG FARMACEUTICA" in textos
    assert "Janssen Cilag Farmacêutica" in textos
    # …e o que não contém o texto (e o CPV que não começa por ele) fica de fora.
    assert "Instituto Português de Oncologia do Porto" not in textos
    assert "45200000-9" not in textos


def test_cpv_entra_por_prefixo():
    cliente = _FakeES(_resposta([], [], [_balde("33600000-6", 475), _balde("45200000-9", 10)]))
    resultado = esc.contracts_autocomplete(q="3360", size=6, es=cliente)
    tipos = {item["text"]: item["type"] for item in resultado["suggestions"]}
    assert tipos == {"33600000-6": "cpv"}


def test_texto_livre_perigoso_nao_vai_para_o_elasticsearch():
    """`(((`, `.*` ou `a|b` não entram na consulta: só o `prefix` (valor literal)."""
    for consulta in ("(((", ".*", "a|b", '"aspas"', "AND OR NOT"):
        cliente = _FakeES(_resposta([], [], []))
        resultado = esc.contracts_autocomplete(q=consulta, size=5, es=cliente)
        assert "error" not in resultado
        corpo = _corpo(cliente)
        assert consulta not in str(corpo.get("aggs")), "o texto não pode ir para `include`"


def test_sem_cliente_devolve_erro_e_sem_texto_nao_pesquisa(monkeypatch):
    monkeypatch.setattr(esc, "get_es_client", lambda *a, **k: None)
    assert esc.contracts_autocomplete(q="janssen")["error"]

    cliente = _FakeES(_resposta([], [], []))
    assert esc.contracts_autocomplete(q="   ", es=cliente) == {"suggestions": []}
    assert cliente.pedidos == []


def test_erro_do_elasticsearch_volta_como_erro(monkeypatch):
    class _Explode:
        def search(self, **_kwargs: Any) -> Dict[str, Any]:
            raise RuntimeError("search_phase_execution_exception")

    resultado = esc.contracts_autocomplete(q="janssen", es=_Explode())
    assert "search_phase_execution_exception" in resultado["error"]
    assert resultado["suggestions"] == []


def _mapping(nome: str) -> Dict[str, Any]:
    """Mapping mínimo do índice de contratos com o campo do nome das partes."""
    return {
        "contratos": {
            "mappings": {
                "properties": {
                    "adjudicantes": {"properties": {"parsed": {"type": "nested", "properties": {"nome": nome}}}},
                    "adjudicatarios": {"properties": {"parsed": {"type": "nested", "properties": {"nome": nome}}}},
                }
            }
        }
    }


def test_campo_do_nome_segue_o_mapping_texto_com_keyword():
    cliente = _FakeES(_resposta([], [], []), _mapping({"type": "text", "fields": {"keyword": {"type": "keyword"}}}))
    esc.contracts_autocomplete(q="janssen", size=4, es=cliente)
    corpo = _corpo(cliente)
    assert corpo["aggs"]["adjudicantes"]["aggs"]["names"]["terms"]["field"] == "adjudicantes.parsed.nome.keyword"
    ramo_partes = corpo["query"]["bool"]["should"][2]
    assert "adjudicantes.parsed.nome.keyword" in str(ramo_partes)


def test_campo_do_nome_segue_o_mapping_keyword_direto():
    cliente = _FakeES(_resposta([], [], []), _mapping({"type": "keyword"}))
    esc.contracts_autocomplete(q="janssen", size=4, es=cliente)
    corpo = _corpo(cliente)
    assert corpo["aggs"]["adjudicatarios"]["aggs"]["names"]["terms"]["field"] == "adjudicatarios.parsed.nome"
    assert ".keyword" not in str(corpo)


def test_ordenacao_pelas_partes_usa_o_campo_resolvido():
    """Ordenar por parte usava `.keyword` fixo: com o mapping novo a pesquisa falhava."""
    cliente = _FakeES(_resposta([], [], []), _mapping({"type": "keyword"}))
    ordenacao = esc._build_contract_sort("adjudicatarios", "asc", cliente)
    assert ordenacao[0]["adjudicatarios.parsed.nome"] == {
        "order": "asc",
        "nested": {"path": "adjudicatarios.parsed"},
        "unmapped_type": "keyword",
    }

    cliente_texto = _FakeES(_resposta([], [], []), _mapping({"type": "text", "fields": {"keyword": {"type": "keyword"}}}))
    ordenacao_texto = esc._build_contract_sort("adjudicantes", "desc", cliente_texto)
    assert "adjudicantes.parsed.nome.keyword" in ordenacao_texto[0]

    # Sem cliente (função pura) nunca se aponta para um campo inexistente sem rede de segurança.
    sem_cliente = esc._build_contract_sort("adjudicantes")
    assert sem_cliente[0]["adjudicantes.parsed.nome"]["unmapped_type"] == "keyword"
