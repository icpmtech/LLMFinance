"""Testes da pesquisa de **entidades** nos éditos (citações) — puros, sem Elasticsearch.

Cobrem o que não depende do cluster:

- a normalização que agrupa grafias da mesma designação (`_entidade_key`) — só
  caixa, acentos e pontuação, nunca aproximações de nomes diferentes;
- as cláusulas de pesquisa partilhadas (`_citacoes_query`), sobretudo o filtro por
  **várias grafias** (`nomes`), que é o que faz a lista de éditos explicar a
  contagem da entidade.

A agregação em si (nested + `reverse_nested`) é validada contra o índice em
`_probe_citacoes_entidades.py`, que confirma a coerência entre o grupo e a lista.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.elasticsearch_client import _citacoes_query, _entidade_key  # noqa: E402


# ---------------------------------------------------------------------------
# Agrupamento de grafias
# ---------------------------------------------------------------------------
def test_chave_de_entidade_junta_caixa_acentos_e_pontuacao() -> None:
    chave = _entidade_key("CAIXA ECONÓMICA MONTEPIO GERAL")
    assert chave == _entidade_key("Caixa Económica Montepio Geral")
    assert chave == _entidade_key("caixa  economica, montepio geral.")
    assert chave == "CAIXA ECONOMICA MONTEPIO GERAL"


def test_chave_de_entidade_nao_aproxima_nomes_diferentes() -> None:
    assert _entidade_key("Banco A") != _entidade_key("Banco ABC")
    assert _entidade_key("Montepio Crédito, S.A.") != _entidade_key("Caixa Económica Montepio Geral")
    assert _entidade_key("Instituto da Segurança Social - I P") == _entidade_key("INSTITUTO DA SEGURANCA SOCIAL IP")


def test_chave_de_entidade_ignora_vazios() -> None:
    assert _entidade_key(None) == ""
    assert _entidade_key("   ") == ""
    assert _entidade_key("...") == ""


# ---------------------------------------------------------------------------
# Cláusulas de pesquisa
# ---------------------------------------------------------------------------
def _nested_clauses(query: dict) -> list[dict]:
    return (query.get("bool") or {}).get("filter") or []


def test_pesquisa_sem_filtros_e_match_all() -> None:
    assert _citacoes_query() == {"match_all": {}}


def test_filtro_por_varias_grafias_e_terms_nested() -> None:
    query = _citacoes_query(nomes=["Caixa Económica Montepio Geral", "CAIXA ECONÓMICA MONTEPIO GERAL"])
    clausulas = _nested_clauses(query)
    nested = [item for item in clausulas if "nested" in item]
    assert nested, clausulas
    clausula = nested[0]["nested"]
    assert clausula["path"] == "intervenientes"
    assert clausula["query"]["terms"]["intervenientes.nome.keyword"] == [
        "Caixa Económica Montepio Geral",
        "CAIXA ECONÓMICA MONTEPIO GERAL",
    ]


def test_filtro_por_nome_unico_usa_match_nested() -> None:
    query = _citacoes_query(nome="Montepio")
    clausulas = _nested_clauses(query)
    clausula = [item for item in clausulas if "nested" in item][0]["nested"]
    assert clausula["query"]["match"]["intervenientes.nome"] == "Montepio"


def test_nomes_vazios_nao_acrescentam_clausulas() -> None:
    assert _citacoes_query(nomes=["", "   "]) == {"match_all": {}}


def test_filtros_combinam_em_filter_e_a_texto_livre_em_must() -> None:
    query = _citacoes_query(q="citacao", tipo="Citação", papel="Exequente", data_from="2026-01-01")
    assert "must" in query["bool"] and query["bool"]["must"]
    filtros = query["bool"]["filter"]
    assert {"term": {"tipo": "Citação"}} in filtros
    assert {"term": {"papeis": "Exequente"}} in filtros
    assert {"range": {"data_publicacao": {"gte": "2026-01-01"}}} in filtros


def test_nif_procura_no_documento_e_nos_intervenientes() -> None:
    query = _citacoes_query(nif="223886025")
    filtros = query["bool"]["filter"]
    nif_clause = [item for item in filtros if "bool" in item][0]["bool"]
    assert {"term": {"documento_nifs": "223886025"}} in nif_clause["should"]
    assert nif_clause["should"][1]["nested"]["query"]["term"]["intervenientes.nif"] == "223886025"
