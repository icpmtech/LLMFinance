"""Testes do **dashboard global** (o universo inteiro, por ano) — puros, sem Elasticsearch.

O que aqui se protege:

- a **classificação de ajuste direto** pelos prefixos do país (contratos, valor,
  taxas sobre contratos e sobre valor);
- a **linha de cada ano** a partir do balde de agregação (nested com `top_hits` e
  `reverse_nested`, `filter` aggs lidos por `doc_count`, mediana por percentis);
- os **documentos materializados**: um por ano + total + meta — a regressão que
  só gravava o último ano está aqui fixada;
- os **filtros** da pesquisa (período, parte, ajuste direto, campo calculado
  «aditivo»);
- o **dashboard** (estado vazio, recorte por ano, série por granularidade) e a
  **pesquisa** (KPIs, facetas, itens) com um cliente de Elasticsearch simulado;
- as degradações (sem ES, país desconhecido) e o registo das rotas.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api import padroes_global as universo  # noqa: E402
from api import padroes_service as padroes  # noqa: E402

PT = padroes.COUNTRIES["PT"]
ES = padroes.COUNTRIES["ES"]


# ---------------------------------------------------------------------------
# Cliente simulado (só o que o módulo usa)
# ---------------------------------------------------------------------------
class _ClienteFalso:
    """Cliente mínimo: `search`, `get`, `count` e `indices.refresh`."""

    def __init__(self, respostas: List[Dict[str, Any]] | None = None, documentos: Dict[str, Dict[str, Any]] | None = None):
        self.respostas = list(respostas or [])
        self.documentos = dict(documentos or {})
        self.pedidos: List[Dict[str, Any]] = []
        self.indices = self

    def search(self, *, index: str, body: Dict[str, Any], request_timeout: int = 0) -> Dict[str, Any]:
        self.pedidos.append({"index": index, "body": body})
        return self.respostas.pop(0) if self.respostas else {}

    def get(self, *, index: str, id: str) -> Dict[str, Any]:
        if id not in self.documentos:
            raise KeyError(id)
        return {"_source": self.documentos[id]}

    def count(self, *, index: str) -> Dict[str, Any]:
        return {"count": len(self.documentos)}

    def index(self, *, index: str, id: str, document: Dict[str, Any], refresh: bool = False) -> Dict[str, Any]:
        self.documentos[id] = document
        return {"result": "created"}

    def refresh(self, *, index: str) -> Dict[str, Any]:
        return {"_shards": {"total": 1, "successful": 1, "failed": 0}}


def _balde_ano(ano: int = 2025, *, contratos: int = 1000, valor: float = 1_000_000.0) -> Dict[str, Any]:
    """Balde de agregação de um ano, com a forma que o Elasticsearch devolve."""
    return {
        "key": ano,
        "doc_count": contratos,
        "valor": {"count": contratos, "sum": valor, "avg": valor / contratos, "max": valor / 10, "min": 100.0},
        "valor_base": {"count": contratos - 100, "sum": valor * 1.2, "avg": 1200.0},
        "mediana": {"values": {"50.0": 1200.5}},
        "procedimentos": {
            "buckets": [
                {"key": "Ajuste Direto Regime Geral", "doc_count": 400, "valor": {"value": 300_000.0}},
                {"key": "Consulta Prévia", "doc_count": 100, "valor": {"value": 150_000.0}},
                {"key": "Concurso Público", "doc_count": 500, "valor": {"value": 550_000.0}},
            ]
        },
        "meses": {"buckets": [{"key_as_string": "2025-01-01T00:00:00.000Z", "doc_count": 80, "valor": {"value": 90_000.0}}]},
        "cpvs": {
            "codigos": {
                "buckets": [
                    {"key": "45000000-7", "doc_count": 300, "valor": {"s": {"value": 400_000.0}}},
                    {"key": "33600000-6", "doc_count": 200, "valor": {"s": {"value": 250_000.0}}},
                ]
            }
        },
        "adjudicatarias": {
            "nifs": {
                "buckets": [
                    {
                        "key": "503439800",
                        "doc_count": 120,
                        "nome": {"hits": {"hits": [{"_source": {"adjudicatarios": {"parsed": {"nome": "ACME, Lda"}}}}]}},
                        "valor": {"s": {"value": 500_000.0}},
                    }
                ]
            }
        },
        "adjudicantes": {
            "nifs": {
                "buckets": [
                    {
                        "key": "500000001",
                        "doc_count": 200,
                        "nome": {"hits": {"hits": [{"_source": {"adjudicantes": {"parsed": {"nome": "Município A"}}}}]}},
                        "valor": {"s": {"value": 700_000.0}},
                    }
                ]
            }
        },
        "sem_concorrentes": {"doc_count": 520},
        "aditivos": {"doc_count": 37, "valor": {"value": 88_000.0}},
    }


def _resposta_universo(anos=(2024, 2025)) -> Dict[str, Any]:
    return {
        "hits": {"total": {"value": 473_044}},
        "aggregations": {
            "anos": {"buckets": [_balde_ano(ano) for ano in anos]},
            "meses": {"buckets": [{"key_as_string": "2025-01-01T00:00:00.000Z", "doc_count": 80, "valor": {"value": 90_000.0}}]},
            "procedimentos": {"buckets": [{"key": "Concurso Público", "doc_count": 900, "valor": {"value": 2_000_000.0}}]},
            "top_cpv": {"codigos": {"buckets": [{"key": "45000000-7", "doc_count": 300, "valor": {"s": {"value": 400_000.0}}}]}},
        },
    }


# ---------------------------------------------------------------------------
# Ajuste direto e campo calculado
# ---------------------------------------------------------------------------
def test_classificar_ajuste_direto_por_prefixos() -> None:
    baldes = [
        {"key": "Ajuste Direto Regime Geral", "doc_count": 400, "valor": {"value": 300_000.0}},
        {"key": "CONSULTA PRÉVIA", "doc_count": 100, "valor": {"value": 150_000.0}},
        {"key": "Concurso Público", "doc_count": 500, "valor": {"value": 550_000.0}},
    ]
    resultado = universo._classificar_ajuste_direto(PT, baldes)
    assert resultado["contratos"] == 500
    assert resultado["total"] == 1000
    assert resultado["taxa"] == 0.5
    assert resultado["valor"] == 450_000.0
    assert resultado["taxa_valor"] == 0.45


def test_classificar_ajuste_direto_exige_prefixo_no_inicio() -> None:
    """«(Ajuste direto)» no meio do texto não conta: o critério é o prefixo."""
    baldes = [{"key": "Concurso público — ajuste direto material", "doc_count": 10, "valor": {"value": 1.0}}]
    assert universo._classificar_ajuste_direto(PT, baldes)["contratos"] == 0


def test_classificar_ajuste_direto_sem_baldes() -> None:
    resultado = universo._classificar_ajuste_direto(PT, [])
    assert resultado == {"contratos": 0, "total": 0, "taxa": None, "valor": 0.0, "taxa_valor": None}


def test_classificar_ajuste_direto_espanha() -> None:
    baldes = [
        {"key": "Contrato menor", "doc_count": 30, "valor": {"value": 30_000.0}},
        {"key": "Abierto simplificado", "doc_count": 70, "valor": {"value": 70_000.0}},
    ]
    resultado = universo._classificar_ajuste_direto(ES, baldes)
    assert resultado["contratos"] == 30
    assert resultado["taxa"] == 0.3


def test_runtime_aditivo_so_em_portugal() -> None:
    campo = universo._runtime_aditivo(PT)
    assert "aditivo" in campo
    assert "PrecoTotalEfetivo" in campo["aditivo"]["script"]["source"]
    assert "1.15" in campo["aditivo"]["script"]["source"]
    # Espanha não tem valor efetivo: nada de campo calculado.
    assert universo._runtime_aditivo(ES) == {}


def test_filtro_direct_award_usa_prefixos_do_pais() -> None:
    filtro = universo._filtro_direct_award(PT)
    assert filtro is not None
    # `wildcard` com `case_insensitive`: o campo é `keyword` (sem analisador) e
    # um `prefix` sensível a maiúsculas nunca casaria «Ajuste Direto Regime Geral».
    padroes = [item["wildcard"]["tipoprocedimento"] for item in filtro["bool"]["should"]]
    assert "ajuste direto*" in [item["value"] for item in padroes]
    assert all(item["case_insensitive"] is True for item in padroes)
    assert filtro["bool"]["minimum_should_match"] == 1


# ---------------------------------------------------------------------------
# Linha de cada ano
# ---------------------------------------------------------------------------
def test_linha_ano_le_o_balde_de_agregacao() -> None:
    linha = universo._linha_ano("PT", 2025, _balde_ano())
    assert linha["ano"] == 2025
    assert linha["contratos"] == 1000
    assert linha["valor"] == 1_000_000.0
    assert linha["valor_medio"] == 1000.0
    assert linha["valor_mediano"] == 1200.5
    assert linha["valor_maximo"] == 100_000.0
    assert linha["contratos_com_base"] == 900
    assert linha["valor_base"] == 1_200_000.0
    assert linha["ajuste_direto"]["contratos"] == 500
    assert linha["ajuste_direto"]["taxa"] == 0.5
    assert linha["procedimentos"][0]["procedimento"] == "Ajuste Direto Regime Geral"
    assert linha["cpvs"][0] == {"cpv": "45000000-7", "contratos": 300, "valor": 400_000.0}
    assert linha["adjudicatarias"][0]["nome"] == "ACME, Lda"
    assert linha["adjudicatarias"][0]["valor"] == 500_000.0
    assert linha["adjudicantes"][0]["nome"] == "Município A"
    assert linha["meses"][0]["contratos"] == 80
    # `filter` aggs: a contagem vem em `doc_count` (era lida em `count` e dava 0).
    assert linha["aditivos"] == 37
    assert linha["valor_aditivos"] == 88_000.0
    assert linha["sem_concorrentes"] == 520
    assert linha["taxa_sem_concorrentes"] == 0.52
    assert linha["taxa_aditivo"] == 0.037


def test_linha_ano_do_adjudicatario_aceita_colchetes_vazios() -> None:
    balde = _balde_ano()
    balde["adjudicatarias"]["nifs"]["buckets"] = [
        {
            "key": "503439800",
            "doc_count": 5,
            "nome": {"hits": {"hits": []}},
            "valor": {"s": {"value": None}},
        }
    ]
    linha = universo._linha_ano("PT", 2025, balde)
    assert linha["adjudicatarias"][0]["nome"] == "503439800"
    assert linha["adjudicatarias"][0]["valor"] == 0.0


def test_linha_ano_espanha_usa_campos_planos() -> None:
    balde = {
        "key": 2025,
        "doc_count": 100,
        "valor": {"count": 100, "sum": 500_000.0, "avg": 5000.0, "max": 90_000.0},
        "valor_base": {"count": 100, "sum": 600_000.0, "avg": 6000.0},
        "mediana": {"values": {"50.0": 3000.0}},
        "procedimentos": {"buckets": [{"key": "Contrato menor", "doc_count": 60, "valor": {"value": 100_000.0}}]},
        "meses": {"buckets": []},
        "cpvs": {"codigos": {"buckets": []}},
        "adjudicatarias": {"buckets": [{"key": "B12345678", "doc_count": 10, "nome": {"hits": {"hits": [{"_source": {"adjudicatario_nombre": "Obra SA"}}]}}, "valor": {"value": 20_000.0}}]},
        "adjudicantes": {"buckets": [{"key": "L01234567", "doc_count": 40, "nome": {"hits": {"hits": []}}, "valor": {"value": 80_000.0}}]},
        "ofertas": {"count": 100, "avg": 3.2, "50.0": 3.0},
        "sem_concorrentes": {"doc_count": 7},
    }
    linha = universo._linha_ano("ES", 2025, balde)
    assert linha["ajuste_direto"]["contratos"] == 60
    assert linha["adjudicatarias"][0] == {"nif": "B12345678", "nome": "Obra SA", "contratos": 10, "valor": 20_000.0}
    assert linha["adjudicantes"][0]["nome"] == "L01234567"
    assert linha["ofertas_media"] == 3.2
    assert linha["ofertas_mediana"] == 3.0
    assert linha["sem_ofertas"] == 7
    assert "aditivos" not in linha


# ---------------------------------------------------------------------------
# Documentos materializados
# ---------------------------------------------------------------------------
def _metricas(anos=(2024, 2025)):
    return {
        "pais": "PT",
        "documentos": 473_044,
        "duracao_s": 12.0,
        "gerado_em": "2026-01-01T00:00:00+00:00",
        "meses": [{"data": "2025-01-01T00:00:00.000Z", "contratos": 80, "valor": 90_000.0}],
        "procedimentos": [{"procedimento": "Concurso Público", "contratos": 900, "valor": 2_000_000.0}],
        "top_cpv": [{"cpv": "45000000-7", "contratos": 300, "valor": 400_000.0}],
        "anos": [universo._linha_ano("PT", ano, _balde_ano(ano)) for ano in anos],
    }


def test_documentos_um_por_ano_total_e_meta() -> None:
    """Regressão: três anos têm de dar cinco documentos (e não só o último)."""
    documentos = universo._documentos("PT", _metricas(anos=(2023, 2024, 2025)))
    assert len(documentos) == 5
    assert [doc_id for doc_id, _ in documentos] == ["PT:2023", "PT:2024", "PT:2025", "PT:_total", "PT:_meta"]
    por_id = dict(documentos)
    assert por_id["PT:2024"]["kind"] == "ano"
    assert por_id["PT:2024"]["ano"] == 2024
    assert por_id["PT:_total"]["kind"] == "total"
    assert por_id["PT:_meta"]["kind"] == "meta"


def test_documento_total_soma_os_anos() -> None:
    total = dict(universo._documentos("PT", _metricas()))["PT:_total"]
    assert total["contratos"] == 2000
    assert total["valor"] == 2_000_000.0
    assert total["aditivos"] == 74
    assert total["valor_aditivos"] == 176_000.0
    assert total["taxa_aditivo"] == 0.037
    assert total["anos"] == [2024, 2025]
    assert total["valor_medio"] == 1000.0
    assert total["documentos"] == 473_044
    # Topos: somados por chave, com o valor agregado.
    assert total["cpvs_somados"][0]["cpv"] == "45000000-7"
    assert total["cpvs_somados"][0]["contratos"] == 600
    assert total["cpvs_somados"][0]["valor"] == 800_000.0
    assert total["adjudicatarias"][0]["nome"] == "ACME, Lda"
    assert total["adjudicatarias"][0]["contratos"] == 240
    assert total["adjudicatarias"][0]["valor"] == 1_000_000.0
    assert total["meses"] and total["procedimentos"]


def test_documento_meta_descreve_a_leitura() -> None:
    meta = dict(universo._documentos("PT", _metricas()))["PT:_meta"]
    assert meta["anos"] == [2024, 2025]
    assert meta["documentos"] == 473_044
    assert meta["duracao_s"] == 12.0
    assert meta["gerado_em"] == "2026-01-01T00:00:00+00:00"
    assert meta["versao"] == 1


def test_documentos_com_um_ano() -> None:
    documentos = universo._documentos("PT", _metricas(anos=(2025,)))
    assert [doc_id for doc_id, _ in documentos] == ["PT:2025", "PT:_total", "PT:_meta"]


def test_documentos_sem_anos() -> None:
    metricas = _metricas(anos=())
    documentos = universo._documentos("PT", metricas)
    assert [doc_id for doc_id, _ in documentos] == ["PT:_total", "PT:_meta"]
    assert dict(documentos)["PT:_total"]["anos"] == []


# ---------------------------------------------------------------------------
# Agregação do universo
# ---------------------------------------------------------------------------
def test_metricas_universo_agrega_por_ano(monkeypatch: pytest.MonkeyPatch) -> None:
    cliente = _ClienteFalso([_resposta_universo()])
    monkeypatch.setattr(universo, "get_es_client", lambda: cliente)
    monkeypatch.setattr(universo, "_anos", lambda pais, *, anos=None, es=None: [2024, 2025])

    metricas = universo.metricas_universo("PT", anos=[2024, 2025])
    assert metricas["pais"] == "PT"
    assert [linha["ano"] for linha in metricas["anos"]] == [2024, 2025]
    assert metricas["documentos"] == 473_044
    assert metricas["duracao_s"] is not None
    corpo = cliente.pedidos[0]["body"]
    assert corpo["size"] == 0
    assert corpo["query"]["bool"]["filter"][0]["range"]["Ano"] == {"gte": 2024, "lte": 2025}
    # O campo calculado «aditivo» vai no corpo do pedido (é o que faz os 751
    # aditivos de 2025 aparecerem em vez de zero).
    assert "aditivo" in corpo["runtime_mappings"]
    assert set(corpo["aggs"]) >= {"anos", "meses", "procedimentos", "top_cpv"}


def test_metricas_universo_espanha_so_um_ano(monkeypatch: pytest.MonkeyPatch) -> None:
    cliente = _ClienteFalso([_resposta_universo(anos=(2025,))])
    monkeypatch.setattr(universo, "get_es_client", lambda: cliente)
    monkeypatch.setattr(universo, "_anos", lambda pais, *, anos=None, es=None: [2025])
    metricas = universo.metricas_universo("ES", anos=[2025])
    assert [linha["ano"] for linha in metricas["anos"]] == [2025]
    assert "runtime_mappings" not in cliente.pedidos[0]["body"]


def test_metricas_universo_sem_es(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(universo, "get_es_client", lambda: None)
    assert "indisponível" in universo.metricas_universo("PT")["error"]


def test_metricas_universo_pais_desconhecido() -> None:
    resultado = universo.metricas_universo("FR")
    assert "país desconhecido" in resultado["error"]
    assert "PT" in resultado["paises"]


def test_metricas_universo_sem_anos(monkeypatch: pytest.MonkeyPatch) -> None:
    cliente = _ClienteFalso()
    monkeypatch.setattr(universo, "get_es_client", lambda: cliente)
    monkeypatch.setattr(universo, "_anos", lambda pais, *, anos=None, es=None: [])
    assert "sem anos" in universo.metricas_universo("PT")["error"]


def test_metricas_universo_falha_na_agregacao(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Rebenta(_ClienteFalso):
        def search(self, **kwargs: Any) -> Dict[str, Any]:
            raise RuntimeError("índice vermelho")

    monkeypatch.setattr(universo, "get_es_client", lambda: _Rebenta())
    monkeypatch.setattr(universo, "_anos", lambda pais, *, anos=None, es=None: [2025])
    assert "falha na agregação" in universo.metricas_universo("PT")["error"]


def test_anos_respeita_o_que_existe_no_indice(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(padroes, "_years_in_index", lambda client, spec: [2020, 2021, 2022])
    assert universo._anos("PT", anos=[2019, 2021], es=object()) == [2021]
    assert universo._anos("PT", es=object()) == [2020, 2021, 2022]


# ---------------------------------------------------------------------------
# Sincronização
# ---------------------------------------------------------------------------
def test_sincronizar_indexa_todos_os_anos(monkeypatch: pytest.MonkeyPatch) -> None:
    cliente = _ClienteFalso()
    monkeypatch.setattr(universo, "metricas_universo", lambda pais, *, anos=None, es=None: _metricas())
    resultado = universo.sincronizar("PT", anos=[2024, 2025], es=cliente)
    assert resultado["anos"] == [2024, 2025]
    assert resultado["documentos"] == 4
    assert resultado["indexados"] == 4
    assert set(cliente.documentos) == {"PT:2024", "PT:2025", "PT:_total", "PT:_meta"}
    assert cliente.documentos["PT:2025"]["kind"] == "ano"


def test_sincronizar_propaga_o_erro(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(universo, "metricas_universo", lambda pais, *, anos=None, es=None: {"error": "sem índice"})
    assert universo.sincronizar("PT", es=_ClienteFalso()) == {"error": "sem índice"}


def test_sincronizar_sem_es_nao_indexa(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(universo, "metricas_universo", lambda pais, *, anos=None, es=None: _metricas())
    monkeypatch.setattr(universo, "get_es_client", lambda: None)
    resultado = universo.sincronizar("PT", anos=[2024, 2025])
    assert resultado["indexados"] == 0
    assert resultado["documentos"] == 4


def test_iniciar_sincronizacao_e_single_flight(monkeypatch: pytest.MonkeyPatch) -> None:
    bloqueio = __import__("threading").Event()

    def _demora(pais: str, *, anos=None, es=None):
        bloqueio.wait(timeout=5)
        return {"pais": "PT", "anos": [2025], "documentos": 3, "indexados": 3}

    monkeypatch.setattr(universo, "sincronizar", _demora)
    universo._publicar(a_correr=False, erro=None, resultado=None, progresso=None)
    primeiro = universo.iniciar_sincronizacao("PT", anos=[2025])
    assert primeiro["a_correr"] is True
    segundo = universo.iniciar_sincronizacao("PT", anos=[2025])
    assert segundo["a_correr"] is True and "aviso" in segundo
    bloqueio.set()
    for _ in range(200):
        if not universo.estado()["a_correr"]:
            break
        __import__("time").sleep(0.02)
    assert universo.estado()["a_correr"] is False
    assert universo.estado()["resultado"]["indexados"] == 3


def test_iniciar_sincronizacao_regista_o_erro(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(universo, "sincronizar", lambda pais, *, anos=None, es=None: {"error": "índice em baixo"})
    universo._publicar(a_correr=False, erro=None, resultado=None)
    universo.iniciar_sincronizacao("PT")
    for _ in range(200):
        if not universo.estado()["a_correr"]:
            break
        __import__("time").sleep(0.02)
    assert universo.estado()["erro"] == "índice em baixo"


def test_estado_tem_campos_estaveis() -> None:
    estado = universo.estado()
    assert set(estado) >= {"a_correr", "pais", "progresso", "inicio", "fim", "resultado", "erro"}


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
def _documentos_materializados():
    return dict(universo._documentos("PT", _metricas()))


def test_dashboard_sem_materializacao(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(universo, "get_es_client", lambda: _ClienteFalso())
    painel = universo.dashboard("PT")
    assert painel["vazio"] is True
    assert "sincronização" in painel["aviso"]
    assert [item["id"] for item in painel["granularidades"]] == ["dia", "semana", "mes", "ano"]


def test_dashboard_le_os_documentos_materializados(monkeypatch: pytest.MonkeyPatch) -> None:
    cliente = _ClienteFalso(documentos=_documentos_materializados())
    monkeypatch.setattr(universo, "get_es_client", lambda: cliente)
    painel = universo.dashboard("PT", granularidade="mes")
    assert painel["vazio"] is False
    assert painel["totais"]["contratos"] == 2000
    assert painel["totais"]["anos"] == [2024, 2025]
    assert painel["totais"]["aditivos"] == 74
    assert painel["totais"]["ajuste_direto"]["taxa"] == 0.5
    assert painel["totais"]["valor_mediano"] == 1200.5
    assert painel["meta"]["anos"] == [2024, 2025]
    assert painel["top_cpv"][0]["cpv"] == "45000000-7"
    assert painel["top_adjudicatarias"][0]["nome"] == "ACME, Lda"
    assert len(painel["por_ano"]) == 2


def test_dashboard_recorta_pelos_anos_pedidos(monkeypatch: pytest.MonkeyPatch) -> None:
    cliente = _ClienteFalso(documentos=_documentos_materializados())
    monkeypatch.setattr(universo, "get_es_client", lambda: cliente)
    painel = universo.dashboard("PT", ano_from=2025, ano_to=2025)
    assert painel["totais"]["anos"] == [2025]
    assert painel["totais"]["contratos"] == 1000
    assert len(painel["por_ano"]) == 1


def test_dashboard_serie_por_ano_e_por_mes(monkeypatch: pytest.MonkeyPatch) -> None:
    cliente = _ClienteFalso(documentos=_documentos_materializados())
    monkeypatch.setattr(universo, "get_es_client", lambda: cliente)
    por_ano = universo.dashboard("PT", granularidade="ano")["serie"]
    assert [ponto["periodo"] for ponto in por_ano] == ["2024", "2025"]
    por_mes = universo.dashboard("PT", granularidade="mes")["serie"]
    assert por_mes[0]["periodo"] == "2025-01"
    # Dia e semana não têm leitura imediata: o dashboard mostra o mês.
    por_dia = universo.dashboard("PT", granularidade="dia")["serie"]
    assert por_dia[0]["periodo"] == "2025-01"


def test_dashboard_granularidade_invalida_cai_no_mes(monkeypatch: pytest.MonkeyPatch) -> None:
    cliente = _ClienteFalso(documentos=_documentos_materializados())
    monkeypatch.setattr(universo, "get_es_client", lambda: cliente)
    assert universo.dashboard("PT", granularidade="hora")["granularidade"] == "mes"


def test_dashboard_pais_desconhecido_e_sem_es(monkeypatch: pytest.MonkeyPatch) -> None:
    assert "país desconhecido" in universo.dashboard("XX")["error"]
    monkeypatch.setattr(universo, "get_es_client", lambda: None)
    assert "indisponível" in universo.dashboard("PT")["error"]


# ---------------------------------------------------------------------------
# Filtros da pesquisa
# ---------------------------------------------------------------------------
def test_filtro_periodo_escolhe_o_campo() -> None:
    assert universo._filtro_periodo(PT, data_from=None, data_to=None) is None
    publicacao = universo._filtro_periodo(PT, data_from="2025-01-01", data_to="2025-06-30")
    assert publicacao["range"]["dataPublicacao"] == {"gte": "2025-01-01", "lte": "2025-06-30", "format": "yyyy-MM-dd"}
    decisao = universo._filtro_periodo(PT, data_from="2025-01-01", data_to=None, campo="decisao")
    assert "dataDecisaoAdjudicacao" in decisao["range"]
    assinatura = universo._filtro_periodo(PT, data_from="2025-01-01", data_to=None, campo="assinatura")
    assert "dataCelebracaoContrato" in assinatura["range"]
    # Espanha não tem data de assinatura: cai na publicação.
    es = universo._filtro_periodo(ES, data_from="2025-01-01", data_to=None, campo="assinatura")
    assert "fecha_publicacion" in es["range"]


def test_filtro_parte_por_nif_e_por_nome() -> None:
    assert universo._filtro_parte(PT, "   ") is None
    por_nif = universo._filtro_parte(PT, "503439800")
    assert por_nif["nested"]["path"] == "adjudicatarios.parsed"
    assert por_nif["nested"]["query"] == {"term": {"adjudicatarios.parsed.nif": "503439800"}}
    por_nome = universo._filtro_parte(PT, "acme")
    assert por_nome["nested"]["query"]["wildcard"]["adjudicatarios.parsed.nome"]["case_insensitive"] is True
    assert por_nome["nested"]["query"]["wildcard"]["adjudicatarios.parsed.nome"]["value"] == "*ACME*"
    es_nif = universo._filtro_parte(ES, "B12345678")
    assert es_nif == {"wildcard": {"adjudicatario_nif": {"value": "B12345678", "case_insensitive": True}}}
    es_nome = universo._filtro_parte(ES, "Obra SA")
    assert es_nome["match"]["adjudicatario_nombre"]["operator"] == "and"


def test_pesquisa_compõe_os_filtros(monkeypatch: pytest.MonkeyPatch) -> None:
    cliente = _ClienteFalso([{"hits": {"total": {"value": 0}, "hits": []}, "aggregations": {}}])
    monkeypatch.setattr(universo, "get_es_client", lambda: cliente)
    universo.pesquisa(
        "PT",
        q="obras",
        data_from="2025-01-01",
        data_to="2025-12-31",
        ano_from=2024,
        ano_to=2025,
        empresa="503439800",
        adjudicante="Município A",
        cpv="45000000-7",
        procedimento="ajuste",
        valor_min=1000,
        valor_max=50_000,
        so_ajuste_direto=True,
        so_aditivo=True,
        granularidade="dia",
        size=10,
        from_=20,
    )
    corpo = cliente.pedidos[0]["body"]
    filtros = corpo["query"]["bool"]["must"][0]["bool"]["filter"]
    assert corpo["size"] == 10 and corpo["from"] == 20
    assert corpo["sort"][0]["dataPublicacao"]["order"] == "desc"
    assert corpo["aggs"]["serie"]["date_histogram"]["calendar_interval"] == "1d"
    assert corpo["runtime_mappings"]["aditivo"]["type"] == "boolean"
    assert corpo["query"]["bool"]["filter"] == [{"term": {"aditivo": True}}]
    assert any("simple_query_string" in filtro for filtro in filtros)
    assert any("range" in filtro and "dataPublicacao" in filtro["range"] for filtro in filtros)
    assert any("range" in filtro and "Ano" in filtro["range"] for filtro in filtros)
    assert any("nested" in filtro and filtro["nested"]["path"] == "adjudicatarios.parsed" for filtro in filtros)
    assert any("nested" in filtro and filtro["nested"]["path"] == "adjudicantes.parsed" for filtro in filtros)
    assert any("nested" in filtro and "prefix" in filtro["nested"]["query"] for filtro in filtros)
    assert any("wildcard" in filtro and "tipoprocedimento" in filtro["wildcard"] for filtro in filtros)
    assert any("range" in filtro and "precoContratual" in filtro["range"] for filtro in filtros)
    assert any("bool" in filtro and "should" in filtro["bool"] for filtro in filtros)


def test_pesquisa_sem_filtros_usa_match_all(monkeypatch: pytest.MonkeyPatch) -> None:
    cliente = _ClienteFalso([{"hits": {"total": {"value": 0}, "hits": []}, "aggregations": {}}])
    monkeypatch.setattr(universo, "get_es_client", lambda: cliente)
    universo.pesquisa("PT", size=5)
    assert cliente.pedidos[0]["body"]["query"] == {"match_all": {}}


def test_pesquisa_sem_facets_poupa_os_agregados_caros(monkeypatch: pytest.MonkeyPatch) -> None:
    """As páginas seguintes não pedem série nem topos (nested + top_hits)."""
    cliente = _ClienteFalso([{"hits": {"total": {"value": 0}, "hits": []}, "aggregations": {}}])
    monkeypatch.setattr(universo, "get_es_client", lambda: cliente)
    universo.pesquisa("PT", size=25, from_=50, facets=False)
    aggs = cliente.pedidos[0]["body"]["aggs"]
    assert set(aggs) == {"valor", "mediana", "aditivos", "sem_concorrentes"}
    assert cliente.pedidos[0]["body"]["from"] == 50


def test_pesquisa_serie_sem_baldes_vazios(monkeypatch: pytest.MonkeyPatch) -> None:
    """`min_doc_count: 1`: num intervalo de anos, um histograma diário com zero
    baldes vazios devolveria milhares de pontos sem contratos (e era lento)."""
    cliente = _ClienteFalso([{"hits": {"total": {"value": 0}, "hits": []}, "aggregations": {}}])
    monkeypatch.setattr(universo, "get_es_client", lambda: cliente)
    universo.pesquisa("PT", granularidade="dia")
    serie = cliente.pedidos[0]["body"]["aggs"]["serie"]["date_histogram"]
    assert serie["calendar_interval"] == "1d" and serie["min_doc_count"] == 1


def test_pesquisa_devolve_kpis_itens_e_facetas(monkeypatch: pytest.MonkeyPatch) -> None:
    resposta = {
        "hits": {
            "total": {"value": 12},
            "hits": [
                {
                    "_id": "abc",
                    "_source": {
                        "idcontrato": "abc",
                        "objectoContrato": "Reabilitação de edifício",
                        "tipoprocedimento": "Ajuste Direto Regime Geral",
                        "precoContratual": 25_000.0,
                        "PrecoTotalEfetivo": 40_000.0,
                        "dataPublicacao": "2025-03-05",
                        "Ano": 2025,
                        "cpv": [{"code": "45000000-7", "description": "Construção"}],
                        "adjudicantes": {"parsed": [{"nif": "500000001", "nome": "Município A"}]},
                        "adjudicatarios": {"parsed": [{"nif": "503439800", "nome": "ACME, Lda"}]},
                        "concorrentes": "",
                    },
                }
            ],
        },
        "aggregations": {
            "valor": {"count": 12, "sum": 1_200_000.0, "avg": 100_000.0, "max": 500_000.0},
            "mediana": {"values": {"50.0": 34_000.0}},
            "procedimentos": {
                "buckets": [
                    {"key": "Ajuste Direto Regime Geral", "doc_count": 8, "valor": {"value": 800_000.0}},
                    {"key": "Concurso Público", "doc_count": 4, "valor": {"value": 400_000.0}},
                ]
            },
            "serie": {"buckets": [{"key_as_string": "2025-03-01T00:00:00.000Z", "doc_count": 12, "valor": {"value": 1_200_000.0}}]},
            "cpvs": {"codigos": {"buckets": [{"key": "45000000-7", "doc_count": 12, "valor": {"s": {"value": 1_200_000.0}}}]}},
            "adjudicatarias": {"nifs": {"buckets": [{"key": "503439800", "doc_count": 12, "nome": {"hits": {"hits": []}}, "valor": {"s": {"value": 1_200_000.0}}}]}},
            "adjudicantes": {"nifs": {"buckets": []}},
            "aditivos": {"doc_count": 2, "valor": {"value": 90_000.0}},
            "sem_concorrentes": {"doc_count": 5},
        },
    }
    cliente = _ClienteFalso([resposta])
    monkeypatch.setattr(universo, "get_es_client", lambda: cliente)
    resultado = universo.pesquisa("PT", q="reabilitação", size=1)

    assert resultado["total"] == 12
    assert resultado["items"][0]["objeto"] == "Reabilitação de edifício"
    assert resultado["items"][0]["adjudicataria"] == "ACME, Lda"
    assert resultado["items"][0]["adjudicante"] == "Município A"
    assert resultado["items"][0]["ajuste_direto"] is True
    kpis = resultado["kpis"]
    assert kpis["contratos"] == 12
    assert kpis["valor"] == 1_200_000.0
    assert kpis["valor_mediano"] == 34_000.0
    assert kpis["ajuste_direto"]["contratos"] == 8
    assert kpis["aditivos"] == 2
    assert kpis["valor_aditivos"] == 90_000.0
    assert kpis["taxa_aditivo"] == 0.1667  # `service.num` arredonda a 4 casas
    assert kpis["sem_concorrentes"] == 5
    assert resultado["serie"][0]["contratos"] == 12
    assert resultado["facetas"]["cpvs"][0]["valor"] == 1_200_000.0
    assert resultado["facetas"]["adjudicatarias"][0]["nome"] == "503439800"
    assert resultado["pagina"] == {"size": 1, "from": 0}
    assert resultado["filtros"]["q"] == "reabilitação"


def test_pesquisa_guarda_os_filtros_pedidos(monkeypatch: pytest.MonkeyPatch) -> None:
    cliente = _ClienteFalso([{"hits": {"total": {"value": 0}, "hits": []}, "aggregations": {}}])
    monkeypatch.setattr(universo, "get_es_client", lambda: cliente)
    resultado = universo.pesquisa("PT", empresa="ACME", concorrentes_min=0, concorrentes_max=1, so_ajuste_direto=True)
    assert resultado["filtros"]["empresa"] == "ACME"
    assert resultado["filtros"]["concorrentes_max"] == 1
    assert resultado["filtros"]["so_ajuste_direto"] is True
    # Portugal tem `concorrentes` como texto: o intervalo de nº de concorrentes
    # só se aplica a países com contagem (`num_ofertas`, no PLACSP).
    filtros = cliente.pedidos[0]["body"]["query"]["bool"]["filter"]
    assert not any("range" in filtro and "concorrentes" in filtro["range"] for filtro in filtros)


def test_pesquisa_espanha_usa_contagem_de_ofertas(monkeypatch: pytest.MonkeyPatch) -> None:
    cliente = _ClienteFalso([{"hits": {"total": {"value": 0}, "hits": []}, "aggregations": {}}])
    monkeypatch.setattr(universo, "get_es_client", lambda: cliente)
    universo.pesquisa("ES", concorrentes_min=1, concorrentes_max=4, granularidade="semana")
    corpo = cliente.pedidos[0]["body"]
    assert corpo["aggs"]["serie"]["date_histogram"]["calendar_interval"] == "1w"
    assert corpo["aggs"]["ofertas"] == {"stats": {"field": "num_ofertas"}}
    assert {"range": {"num_ofertas": {"gte": 1, "lte": 4}}} in corpo["query"]["bool"]["filter"]


def test_pesquisa_sem_es_e_pais_desconhecido(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(universo, "get_es_client", lambda: None)
    assert "indisponível" in universo.pesquisa("PT")["error"]
    assert "país desconhecido" in universo.pesquisa("IT")["error"]


def test_pesquisa_falha_na_leitura(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Rebenta(_ClienteFalso):
        def search(self, **kwargs: Any) -> Dict[str, Any]:
            raise RuntimeError("timeout")

    monkeypatch.setattr(universo, "get_es_client", lambda: _Rebenta())
    assert "falha na pesquisa" in universo.pesquisa("PT")["error"]


# ---------------------------------------------------------------------------
# Meta e rotas
# ---------------------------------------------------------------------------
def test_meta_do_universo(monkeypatch: pytest.MonkeyPatch) -> None:
    cliente = _ClienteFalso(documentos=_documentos_materializados())
    monkeypatch.setattr(universo, "get_es_client", lambda: cliente)
    meta = universo.meta("PT")
    assert meta["pais"] == "PT"
    assert meta["indice"] == "contratos"
    assert meta["indice_materializado"] == "finance_padroes_global"
    assert meta["guardado"] is True
    assert meta["anos"] == [2024, 2025]
    assert meta["documentos"] == 4
    assert meta["documentos_universo"] == 473_044
    assert meta["anos_padrao"] == universo.ANOS_PADRAO
    assert "sincronização" in meta["aviso"]


def test_meta_sem_materializacao_e_pais_desconhecido(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(universo, "get_es_client", lambda: _ClienteFalso())
    meta = universo.meta("ES")
    assert meta["guardado"] is False
    assert meta["anos"] == []
    assert "país desconhecido" in universo.meta("JP")["error"]


def test_meta_sem_es(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(universo, "get_es_client", lambda: None)
    meta = universo.meta("PT")
    assert meta["documentos"] is None
    assert meta["guardado"] is False


def test_rotas_do_universo_registadas() -> None:
    from api import padroes_routes  # noqa: PLC0415

    caminhos = {route.path for route in padroes_routes.router.routes}
    assert {
        "/padroes/global",
        "/padroes/global/meta",
        "/padroes/global/estado",
        "/padroes/global/pesquisa",
        "/padroes/global/sincronizar",
        "/padroes/global/sincronizar/agora",
    } <= caminhos
