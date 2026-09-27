"""Testes do World Model — puros, sem Elasticsearch nem rede.

Cobrem a lógica que não depende de infraestrutura:

- normalização das fontes públicas (listas, datas absurdas, valores impossíveis);
- construçao do estado, eventos e relações a partir de contratos normalizados
  (`world_model._collect_from_contracts` + `_finalize`);
- risco, concentração e atividade (incluindo a recusa de concluir concentração
  com poucas relações);
- leitura do grafo (BFS de caminhos) e da causalidade (proximidade temporal);
- features, memória e pré-visualização da rede dinâmica (aqui simula-se o estado
  que viria do Elasticsearch);
- taxas e cenários do simulador de futuro (sem ES);
- relatório e validação do agente de investigação.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api import world_agent, world_graph, world_investigation, world_model, world_neural, world_simulator, world_sources  # noqa: E402


# ---------------------------------------------------------------------------
# Fontes públicas
# ---------------------------------------------------------------------------
def test_clean_name_aceita_listas_e_descarta_vazios() -> None:
    assert world_sources._clean_name(["  Aquisição de bens  "]) == "Aquisição de bens"
    assert world_sources._clean_name(None) is None
    assert world_sources._clean_name("  ") is None
    assert world_sources._clean_name("n/a") is None
    assert world_sources._clean_name("Sociedade   X") == "Sociedade X"


def test_iso_day_descarta_anos_absurdos_e_formatos_estranhos() -> None:
    assert world_sources._iso_day("2024-03-04T00:00:00Z") == "2024-03-04"
    assert world_sources._iso_day("0018-03-02") is None
    assert world_sources._iso_day("2501-01-01") is None
    assert world_sources._iso_day("04/03/2024") is None
    assert world_sources._iso_day(None) is None


def test_as_float_descarta_valores_absurdos() -> None:
    assert world_sources._as_float("1234.5") == 1234.5
    assert world_sources._as_float(None) is None
    assert world_sources._as_float("abc") is None
    assert world_sources._as_float("1e20") is None


# ---------------------------------------------------------------------------
# World Model: estado, eventos e relações
# ---------------------------------------------------------------------------
def _contract(uid: str, buyer: tuple[str, str], winner: tuple[str, str], value: float, date: str, **extra) -> dict:
    return {
        "uid": uid,
        "source": "contratos",
        "index": "contratos",
        "country": "Portugal",
        "id": uid,
        "date": date,
        "end_date": extra.get("end_date"),
        "end_type": extra.get("end_type"),
        "value": value,
        "cpv": extra.get("cpv") or [{"code": "33600000-6", "label": "Produtos farmacêuticos"}],
        "adjudicantes": [{"nif": buyer[0], "name": buyer[1]}],
        "adjudicatarios": [{"nif": winner[0], "name": winner[1]}],
        "contract_type": "Aquisição de bens",
        "object": extra.get("object"),
    }


def _days_ago(days: int) -> str:
    """Data ISO relativa a hoje (os testes não podem depender do calendário)."""
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")


def _build_mundo() -> dict:
    store = world_model._EntityStore()
    contracts = [
        _contract("c1", ("500000001", "Hospital A"), ("600000001", "Empresa X"), 1000.0, _days_ago(300)),
        _contract("c2", ("500000001", "Hospital A"), ("600000001", "Empresa X"), 3000.0, _days_ago(200)),
        _contract("c3", ("500000002", "Município B"), ("600000001", "Empresa X"), 500.0, _days_ago(120)),
        _contract(
            "c4",
            ("500000002", "Município B"),
            ("600000002", "Empresa Y"),
            900.0,
            _days_ago(100),
            end_date=_days_ago(30),
            end_type="Cumprimento",
        ),
        _contract("c5", ("500000003", "Hospital C"), ("600000002", "Empresa Y"), 700.0, _days_ago(60)),
    ]
    world_model._collect_from_contracts(store, contracts, version=1)
    world_model._collect_insolvencies(
        store,
        [
            {"nif": "600000002", "name": "Empresa Y", "role": "insolvente", "ts": _days_ago(45), "process": "1/25", "court": "Porto"},
            {"nif": "500000001", "name": "Hospital A", "role": "credor", "ts": _days_ago(45), "process": "1/25", "court": "Porto"},
        ],
    )
    world_model._collect_people(
        store,
        [
            {
                "person_id": "999999999",
                "person_name": "Ana Silva",
                "company_nif": "600000001",
                "company_name": "Empresa X",
                "role": "Gerente",
                "ts": _days_ago(1000),
            }
        ],
    )
    config = dict(world_model.DEFAULT_CONFIG)
    documents = world_model._finalize(store, config, version=1, now="2026-01-01T00:00:00+00:00")
    return {"store": store, "documents": documents, "state": {doc["entity_ref"]: doc for doc in documents["state"]}}


def test_world_model_gera_estado_eventos_e_relacoes() -> None:
    mundo = _build_mundo()
    documentos = mundo["documents"]
    assert documentos["state"], "o mundo tem de ter entidades"
    assert documentos["events"], "o mundo tem de ter eventos"
    assert documentos["relations"], "o mundo tem de ter relações"

    empresa_x = mundo["state"]["entidade:600000001"]
    assert empresa_x["roles"] == ["adjudicatario"]
    assert empresa_x["contracts_value"] == 4500.0
    # Contrapartes do grafo: as duas entidades públicas + a pessoa com cargo.
    assert empresa_x["counterparties_count"] == 3
    # Clientes comerciais (só relações `adjudicou`): as duas entidades públicas.
    assert empresa_x["metrics"]["clients"] == 2
    assert empresa_x["metrics"]["value_source"] == "amostra"
    assert empresa_x["state"]["status"] == "ativo"

    # Eventos: adjudicação do lado da empresa e contratação do lado de quem contrata.
    kinds = {event["kind"] for event in documentos["events"]}
    assert {"adjudicacao", "contratacao", "insolvencia"} <= kinds
    assert any(event["kind"] == "cessacao" for event in documentos["events"])

    # Relações: adjudicações + cargos.
    relation_kinds = {relation["kind"] for relation in documentos["relations"]}
    assert relation_kinds == {"adjudicou", "cargo_em"}
    cargo = next(relation for relation in documentos["relations"] if relation["kind"] == "cargo_em")
    assert cargo["source_ref"] == "pessoa:999999999"
    assert cargo["target_ref"] == "entidade:600000001"


def test_risco_sobe_com_insolvencia_e_concentracao_so_com_amostra_suficiente() -> None:
    mundo = _build_mundo()
    empresa_y = mundo["state"]["entidade:600000002"]
    empresa_x = mundo["state"]["entidade:600000001"]

    assert empresa_y["insolvent"] is True
    assert empresa_y["state"]["status"] == "insolvente"
    assert empresa_y["risk"] > empresa_x["risk"], "a insolvência tem de pesar no risco"

    # Empresa X tem 2 contrapartes → concentração não é fiável (não se conclui).
    assert empresa_x["state"]["concentration_reliable"] is False
    assert empresa_x["state"]["concentration"] == 0.0


def test_eventos_do_mesmo_dia_sao_deduplicados() -> None:
    store = world_model._EntityStore()
    contract = _contract("c9", ("500000009", "Entidade"), ("600000009", "Empresa"), 100.0, "2025-01-01")
    world_model._collect_from_contracts(store, [contract, dict(contract)], version=1)
    adjudicacoes = [event for event in store.events if event["kind"] == "adjudicacao"]
    assert len(adjudicacoes) == 1


# ---------------------------------------------------------------------------
# Grafo / tempo
# ---------------------------------------------------------------------------
def test_bfs_encontra_caminho_mais_curto() -> None:
    adjacency = {"a": {"b"}, "b": {"a", "c"}, "c": {"b", "d"}, "d": {"c"}}
    caminhos = world_graph._bfs_paths(adjacency, "a", "d", max_depth=5)
    assert caminhos and caminhos[0] == ["a", "b", "c", "d"]


def test_bfs_respeita_profundidade_maxima() -> None:
    adjacency = {"a": {"b"}, "b": {"a", "c"}, "c": {"b"}}
    assert world_graph._bfs_paths(adjacency, "a", "c", max_depth=1) == []
    assert world_graph._bfs_paths(adjacency, "a", "c", max_depth=2)


def test_interpretacao_da_causalidade_e_explicita() -> None:
    assert "contratação" in world_graph._interpret("contratacao", "adjudicacao")
    assert "insolvência" in world_graph._interpret("insolvencia", "adjudicacao")
    assert world_graph._interpret("outro", "outro")


def test_parse_ts_ignora_lixo() -> None:
    assert world_graph._parse_ts("2025-01-02") is not None
    assert world_graph._parse_ts("") is None
    assert world_graph._parse_ts("não é data") is None


# ---------------------------------------------------------------------------
# Rede dinâmica
# ---------------------------------------------------------------------------
def _network_inputs():
    entities = [
        {
            "entity_ref": f"entidade:{600000000 + index}",
            "name": f"Empresa {index}",
            "entity_type": "empresa",
            "contracts_count": index + 1,
            "contracts_value": (index + 1) * 1000.0,
            "risk": 0.1 * index,
            "risk_label": "baixo",
            "insolvent": index == 7,
            "last_event_at": "2025-06-01",
            "state": {"concentration": 0.2},
        }
        for index in range(10)
    ]
    edges = [
        {
            "relation_id": f"e{index}",
            "source_ref": f"entidade:{600000000 + index}",
            "target_ref": f"entidade:{600000001 + index}",
            "kind": "adjudicou",
            "weight": index + 1,
            "contracts_count": index + 1,
            "value_sum": (index + 1) * 500.0,
        }
        for index in range(9)
    ]
    targets = {f"entidade:{600000000 + index}": {"recent": index, "previous": max(0, index - 1)} for index in range(10)}
    return entities, edges, targets


def test_features_e_nos_da_rede() -> None:
    entities, edges, targets = _network_inputs()
    matrix, nodes = world_neural.build_features(entities, edges, targets)
    assert matrix.shape == (len(nodes), len(world_neural.FEATURE_NAMES))
    assert nodes[0]["id"] == "entidade:600000000"
    assert nodes[0]["degree"] > 0
    # Todas as features normalizadas em [0, 1].
    assert float(matrix.min()) >= 0.0 and float(matrix.max()) <= 1.0


def test_standardize_devolve_media_zero() -> None:
    import numpy as np

    matrix = np.asarray([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]])
    scaled, mean, std = world_neural._standardize(matrix)
    assert abs(float(scaled.mean())) < 1e-9
    assert list(mean) == [3.0, 4.0]
    assert all(value > 0 for value in std)


def test_memoria_da_rede_aproxima_padroes_parecidos() -> None:
    import numpy as np

    vector = np.asarray([0.5, 0.5, 0.0])
    candidate = np.asarray([0.5, 0.49, 0.0])
    similarity = float(np.dot(vector, candidate) / (np.linalg.norm(vector) * np.linalg.norm(candidate)))
    assert similarity > 0.99  # acima do limiar de reutilização (0.82)


def test_percentis_do_simulador() -> None:
    import numpy as np

    values = np.asarray([0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0])
    stats = world_simulator._percentiles(values)
    assert stats["mean"] == 4.5
    assert stats["p10"] < stats["p50"] < stats["p90"]


def test_trend_ratio_do_simulador() -> None:
    import numpy as np

    assert world_simulator._trend_ratio(np.asarray([1.0, 1.0, 1.0, 1.0])) == 1.0
    assert world_simulator._trend_ratio(np.asarray([1.0, 1.0, 3.0, 3.0])) > 1.0
    assert world_simulator._trend_ratio(np.asarray([3.0, 3.0, 1.0, 1.0])) < 1.0
    assert world_simulator._trend_ratio(np.asarray([1.0, 2.0])) == 1.0  # amostra curta


def test_cenarios_do_simulador_tem_pesos_e_fatores() -> None:
    assert set(world_simulator.SCENARIOS) == {"otimista", "base", "pessimista"}
    assert abs(sum(scenario["weight"] for scenario in world_simulator.SCENARIOS.values()) - 1.0) < 1e-9
    assert world_simulator.SCENARIOS["pessimista"]["cancels"] > world_simulator.SCENARIOS["otimista"]["cancels"]


# ---------------------------------------------------------------------------
# Agente de investigação
# ---------------------------------------------------------------------------
def test_hipoteses_reagem_ao_estado() -> None:
    mundo = _build_mundo()
    empresa_y = mundo["state"]["entidade:600000002"]
    observation = {
        "kind": "entidade",
        "entity": empresa_y,
        "metrics": empresa_y["metrics"],
        "relations": [],
    }
    hypotheses = world_investigation._hypotheses(observation)
    assert hypotheses and all(item["kind"] == "HYPOTHESIS" for item in hypotheses)
    assert any("insolvência" in item["statement"].lower() for item in hypotheses)
    assert all(item["test"] for item in hypotheses)


def test_validacao_classifica_afirmacoes_e_verifica_contas() -> None:
    mundo = _build_mundo()
    empresa_x = mundo["state"]["entidade:600000001"]
    evidence = [
        {"id": "contract:c1", "type": "contrato", "source_index": "contratos", "source_id": "c1", "value": 1000.0},
        {"id": "contract:c2", "type": "contrato", "source_index": "contratos", "source_id": "c2", "value": 3000.0},
        {"id": "event:e1", "type": "adjudicacao", "source_index": "finance_world_events", "source_id": "e1", "ts": "2024-01-10"},
    ]
    validation = world_investigation._validate(empresa_x, {"kind": "entidade", "entity": empresa_x}, evidence)
    kinds = {claim["kind"] for claim in validation["claims"]}
    assert "CALCULATION" in kinds and "FACT" in kinds
    calculo = next(claim for claim in validation["claims"] if claim["kind"] == "CALCULATION")
    assert "4 000" in calculo["claim"] or "4000" in calculo["claim"].replace(" ", "")
    assert all(check["ok"] for check in validation["checks"])


def test_relatorio_tem_todas_as_seccoes() -> None:
    mundo = _build_mundo()
    empresa_x = mundo["state"]["entidade:600000001"]
    observation = {"kind": "entidade", "entity": empresa_x, "metrics": empresa_x["metrics"], "timeline": [], "relations": []}
    hypotheses = world_investigation._hypotheses(observation)
    validation = world_investigation._validate(empresa_x, observation, [])
    report = world_investigation._report("O que se passa?", "teste", observation, hypotheses, [], validation, None)
    for section in ("## 1. Observação", "## 2. Hipóteses", "## 3. Evidência", "## 4. Validação", "## 5. Simulação", "## 6. Limitações"):
        assert section in report


# ---------------------------------------------------------------------------
# Configuração e metadados
# ---------------------------------------------------------------------------
def test_arquitetura_descreve_o_pipeline_completo() -> None:
    ids = [layer["id"] for layer in world_model.ARCHITECTURE]
    assert ids == ["public-data", "world-model", "dynamic-network", "graph-temporal", "future-simulator", "investigation-agent"]
    assert all(layer["backend"].endswith(".py") for layer in world_model.ARCHITECTURE)


def test_config_por_omissao_tem_amostras_e_agenda() -> None:
    config = world_model.DEFAULT_CONFIG
    assert config["contract_sample"] > 0
    assert 0 < config["risk_medium"] < config["risk_high"] <= 1
    assert config["schedule_cron"]
    assert config["schedule_train_network"] is True


def test_rotulos_de_eventos_e_relacoes_estao_definidos() -> None:
    store = world_model._EntityStore()
    store.add_event({"kind": "adjudicacao", "entity_ref": "entidade:1", "ts": "2025-01-01"})
    store.add_relation("adjudicou", "entidade:1", "A", "entidade_publica", "entidade:2", "B", "empresa", "2025-01-01", 10.0)
    documents = world_model._finalize(store, dict(world_model.DEFAULT_CONFIG), version=1, now="2026-01-01T00:00:00+00:00")
    assert documents["events"][0]["kind_label"] == world_model.EVENT_LABELS["adjudicacao"]
    assert documents["relations"][0]["kind_label"] == world_model.RELATION_LABELS["adjudicou"]


def test_meses_entre_datas() -> None:
    assert world_model.months_between("2024-01-01", "2025-01-01") == 12
    assert world_model.months_between(None, "2025-01-01") is None
    assert world_model.months_between("2025-01-01", "2024-01-01") == 0


# ---------------------------------------------------------------------------
# Estado temporal (períodos e histórico)
# ---------------------------------------------------------------------------
def test_periodo_por_granularidade() -> None:
    assert world_model._period_of("2026-08-14", "quarter") == ("2026-Q3", "2026-07-01", "2026-09-30")
    assert world_model._period_of("2026-01-05", "quarter") == ("2026-Q1", "2026-01-01", "2026-03-31")
    assert world_model._period_of("2026-12-31", "quarter") == ("2026-Q4", "2026-10-01", "2026-12-31")
    assert world_model._period_of("2026-02-10", "month")[0] == "2026-02"
    assert world_model._period_of("2026-02-10", "year") == ("2026", "2026-01-01", "2026-12-31")
    assert world_model._period_of("", "quarter") is None
    assert world_model._period_of("não é data", "quarter") is None


def test_risco_pesa_insolvencia_e_concentracao() -> None:
    base = world_model.risk_score(
        insolvent=False, insolvency_roles=[], contracts=5, value=100_000.0, concentration=0.1, inactive_years=0.0
    )
    insolvent = world_model.risk_score(
        insolvent=True, insolvency_roles=["insolvente"], contracts=5, value=100_000.0, concentration=0.1, inactive_years=0.0
    )
    concentrated = world_model.risk_score(
        insolvent=False, insolvency_roles=[], contracts=5, value=100_000.0, concentration=0.9, inactive_years=0.0
    )
    inactive = world_model.risk_score(
        insolvent=False, insolvency_roles=[], contracts=5, value=100_000.0, concentration=0.1, inactive_years=4.0
    )
    assert 0.0 <= base < concentrated < 1.0
    assert insolvent > base
    assert inactive > base


def test_historico_gera_um_documento_por_periodo() -> None:
    store = world_model._EntityStore()
    contracts = [
        _contract("h1", ("500000001", "Hospital A"), ("600000001", "Empresa X"), 1000.0, "2025-02-10"),
        _contract("h2", ("500000001", "Hospital A"), ("600000001", "Empresa X"), 2000.0, "2025-05-10"),
        _contract("h3", ("500000002", "Município B"), ("600000001", "Empresa X"), 500.0, "2025-08-10"),
    ]
    world_model._collect_from_contracts(store, contracts, version=1)
    documents = world_model._history_documents(store, dict(world_model.DEFAULT_CONFIG), version=1, now="2026-01-01T00:00:00+00:00")
    empresa = [doc for doc in documents if doc["entity_ref"] == "entidade:600000001"]
    periods = sorted(doc["period"] for doc in empresa)
    assert periods == ["2025-Q1", "2025-Q2", "2025-Q3"]

    primeiro = next(doc for doc in empresa if doc["period"] == "2025-Q1")
    terceiro = next(doc for doc in empresa if doc["period"] == "2025-Q3")
    assert primeiro["contracts"] == 1 and primeiro["cum_contracts"] == 1
    assert primeiro["new_counterparties"] == 1
    assert terceiro["cum_contracts"] == 3
    assert terceiro["cum_value"] == 3500.0
    assert terceiro["cum_counterparties"] == 2
    assert terceiro["risk"] >= primeiro["risk"], "o risco acumulado não deve descer com mais atividade e valor"
    assert primeiro["delta_contracts"] == 1 and terceiro["delta_contracts"] == 0
    assert all("_history_id" in doc for doc in documents)


def test_historico_marca_atraso_como_evento() -> None:
    store = world_model._EntityStore()
    contract = _contract("d1", ("500000001", "Hospital A"), ("600000001", "Empresa X"), 1000.0, "2025-01-10")
    contract["end_date"] = "2026-03-01"
    contract["expected_end"] = "2025-06-01"  # 273 dias depois do previsto
    contract["end_type"] = "Cumprimento"
    world_model._collect_from_contracts(store, [contract], version=1)
    kinds = {event["kind"] for event in store.events}
    assert "atraso" in kinds
    atraso = next(event for event in store.events if event["kind"] == "atraso")
    assert atraso["delay_days"] == 273
    assert atraso["severity"] > 0.25


def test_cargos_geram_eventos_de_cargo() -> None:
    store = world_model._EntityStore()
    world_model._collect_people(
        store,
        [
            {
                "person_id": "999999999",
                "person_name": "Ana Silva",
                "company_nif": "600000001",
                "company_name": "Empresa X",
                "role": "Gerente",
                "ts": "2024-04-01",
            }
        ],
    )
    cargos = [event for event in store.events if event["kind"] == "cargo_iniciado"]
    assert len(cargos) == 1
    assert cargos[0]["counterparty_ref"] == "pessoa:999999999"
    assert cargos[0]["role"] == "Gerente"


def test_pipeline_tem_todas_as_camadas_ligadas() -> None:
    layers = {layer["id"] for layer in world_model.ARCHITECTURE}
    assert layers == {
        "public-data",
        "world-model",
        "dynamic-network",
        "graph-temporal",
        "future-simulator",
        "investigation-agent",
    }
    stages = {stage["id"] for stage in world_model.PIPELINE_STAGES}
    assert stages - layers == {"evidence-graph"}
    edges = world_model._PIPELINE_EDGES
    assert all(source in stages and target in stages for source, target, _ in edges)
    # Todas as camadas participam no fluxo (nenhuma isolada).
    touched = {node for source, target, _ in edges for node in (source, target)}
    assert layers <= touched


# ---------------------------------------------------------------------------
# Rede: transição latente e anomalias
# ---------------------------------------------------------------------------
def _synthetic_series(entity_ref: str = "entidade:600000001", periods: int = 10, spike_at: int | None = None):
    """Série sintética com crescimento suave (e, opcionalmente, um pico)."""
    rows = []
    for index in range(periods):
        value = 1000.0 * (index + 1)
        if spike_at is not None and index == spike_at:
            value *= 12
        rows.append(
            {
                "entity_ref": entity_ref,
                "entity_type": "empresa",
                "name": f"Empresa {entity_ref[-3:]}",
                "period": f"2024-Q{index % 4 + 1}",
                "period_start": f"2024-{index % 12 + 1:02d}-01",
                "cum_contracts": index + 1,
                "cum_value": sum(1000.0 * (i + 1) for i in range(index + 1)),
                "cum_counterparties": min(5, index + 1),
                "cum_directors": 2,
                "contracts": 1,
                "value": value,
                "events": 1,
                "new_counterparties": 1 if index % 2 == 0 else 0,
                "risk": 0.2 + 0.02 * index,
            }
        )
    return rows


def test_vetor_de_periodo_aplica_logaritmos() -> None:
    vector = world_neural._period_vector(_synthetic_series(periods=3)[2])
    assert len(vector) == len(world_neural.PERIOD_FEATURES)
    import math as _math

    assert abs(vector[0] - _math.log1p(3)) < 1e-9


def test_transicao_ajusta_dinamica_linear() -> None:
    import numpy as np

    series = {f"entidade:{600000000 + index}": _synthetic_series(f"entidade:{600000000 + index}") for index in range(20)}
    model = world_neural.fit_transition(series, {"transition_min_pairs": 50, "ridge_lambda": 1.0}, np.random.default_rng(0))
    assert model["available"] is True
    assert model["pairs"] >= 50
    assert -1.0 <= model["r2"] <= 1.0
    assert len(model["features"]) == len(world_neural.PERIOD_FEATURES)
    assert model["holdout"] == 0.3


def test_transicao_sem_pares_suficientes() -> None:
    import numpy as np

    model = world_neural.fit_transition({"entidade:1": _synthetic_series(periods=2)}, {"transition_min_pairs": 500}, np.random.default_rng(0))
    assert model["available"] is False
    assert "pares insuficientes" in model["reason"]


def test_anomalias_detetam_pico_e_quebra() -> None:
    normal = _synthetic_series("entidade:600000001")
    spike = _synthetic_series("entidade:600000002", spike_at=9)
    stalled = _synthetic_series("entidade:600000003", periods=8)
    for row in stalled[-3:]:
        row["contracts"] = 0
        row["value"] = 0.0
    series = {row[0]["entity_ref"]: row for row in (normal, spike, stalled)}

    results = world_neural.detect_anomalies(series, nodes=[], params={"periods_min": 4, "anomaly_attention": 0.15, "anomaly_limit": 10})
    by_ref = {item["entity_ref"]: item for item in results}
    assert "entidade:600000002" in by_ref and "spike" in by_ref["entidade:600000002"]["signal_ids"]
    assert "entidade:600000003" in by_ref and "stall" in by_ref["entidade:600000003"]["signal_ids"]
    assert all(item["score"] >= 0.15 for item in results)
    assert all("Não implica" in item["interpretation"] for item in results)


def test_anomalias_ignoram_series_curtas() -> None:
    series = {"entidade:600000001": _synthetic_series(periods=3)}
    assert world_neural.detect_anomalies(series, params={"periods_min": 4}) == []


def test_anomalia_por_insolvencia() -> None:
    rows = _synthetic_series("entidade:600000009")
    rows[-1]["insolvent"] = True
    results = world_neural.detect_anomalies({"entidade:600000009": rows}, params={"periods_min": 4, "anomaly_attention": 0.15})
    assert results and "insolvency" in results[0]["signal_ids"]
    assert results[0]["score"] >= 0.45


# ---------------------------------------------------------------------------
# Fontes do sistema associáveis ao Public Data
# ---------------------------------------------------------------------------
def test_catalogo_de_fontes_e_coerente() -> None:
    ids = [source["id"] for source in world_sources.SOURCES]
    assert len(ids) == len(set(ids)), "ids de fontes duplicados"
    for source in world_sources.SOURCES:
        for field in ("label", "index", "adapter", "join", "contributes", "description"):
            assert source.get(field), f"fonte {source['id']} sem {field}"
        assert source["contributes"], f"fonte {source['id']} sem contributos declarados"
    assert set(world_sources.DEFAULT_SOURCE_IDS) <= set(ids)
    assert set(world_sources.REQUIRED_SOURCE_IDS) <= set(ids)
    # Qualquer fonte do catálogo é associável ou obrigatória (não há fontes órfãs).
    for source in world_sources.SOURCES:
        assert source.get("associable") or source["id"] in world_sources.REQUIRED_SOURCE_IDS


def test_normalize_source_ids_ignora_desconhecidas_e_garante_obrigatorias() -> None:
    assert world_sources.normalize_source_ids(["cire"])[:1] == ["contratos"]
    assert world_sources.normalize_source_ids([]) == ["contratos"]
    chosen = world_sources.normalize_source_ids(["gleif", "inexistente", "marcas"])
    assert "inexistente" not in chosen
    assert {"contratos", "gleif", "marcas"} <= set(chosen)
    # A ordem é a do catálogo (estável para a UI).
    assert chosen == [item for item in [source["id"] for source in world_sources.SOURCES] if item in chosen]


def test_fold_name_normaliza_designacoes() -> None:
    assert world_sources.fold_name("Sonae, SGPS, S.A.") == "SONAE SGPS S A"
    assert world_sources.fold_name("Câmara Municipal de Lisboa") == "CAMARA MUNICIPAL DE LISBOA"
    assert world_sources.fold_name(None) == ""
    assert world_sources.fold_name("  EDP   —  Energias  ") == "EDP ENERGIAS"


def test_registo_enriquece_sem_criar_entidades() -> None:
    store = world_model._EntityStore()
    world_model._collect_from_contracts(store, [_contract("r1", ("500000001", None), ("600000001", None), 900.0, "2025-03-01")], version=1)
    records = [
        {
            "source": "contribuintes",
            "index": "finance_contribuintes",
            "nif": "600000001",
            "name": "Empresa X, S.A.",
            "name_folded": "EMPRESA X S A",
            "country": "Portugal",
            "entity_type": "empresa",
            "identifiers": {},
            "extra": {"contracts_count": 42, "total_value": 12345.0},
        },
        {
            "source": "contribuintes",
            "index": "finance_contribuintes",
            "nif": "999999999",
            "name": "Desconhecida",
            "entity_type": "empresa",
            "identifiers": {},
            "extra": {},
        },
    ]
    stats = world_model._collect_from_registry(store, records, {}, "contribuintes")
    entity = store.entities["entidade:600000001"]
    assert entity["name"] == "Empresa X, S.A."
    assert entity["contracts_count"] == 42 and entity["contracts_value"] == 12345.0
    assert "contribuintes" in entity["sources"]
    assert stats["enriched"] == 1 and stats["ignored"] == 1
    assert "entidade:999999999" not in store.entities, "os registos não podem criar entidades em massa"


def test_registo_liga_gleif_por_designacao_legal() -> None:
    store = world_model._EntityStore()
    world_model._collect_from_contracts(store, [_contract("g1", ("500000001", "Município A"), ("600000002", "Empresa LeI, S.A."), 500.0, "2025-01-01")], version=1)
    folded = world_model._folded_name_index(store)
    records = [
        {
            "source": "gleif",
            "index": "finance_gleif_lei",
            "nif": None,
            "name": "EMPRESA LEI, S.A.",
            "name_folded": world_sources.fold_name("Empresa LeI, S.A."),
            "country": "PT",
            "entity_type": "empresa",
            "identifiers": {"lei": "529900T8BM49AURSDO55"},
            "extra": {},
        }
    ]
    stats = world_model._collect_from_registry(store, records, folded, "gleif")
    assert stats["by_name"] == 1
    assert store.entities["entidade:600000002"]["identifiers"]["lei"] == "529900T8BM49AURSDO55"


def test_publicacoes_criam_eventos() -> None:
    store = world_model._EntityStore()
    stats = world_model._collect_publications(
        store,
        [
            {
                "nif": "600000003",
                "name": "Nova Sociedade, Lda.",
                "ts": "2025-06-12",
                "act": "constituicao",
                "act_label": "Constituição",
                "nature": "Sociedade por quotas",
                "place": "Lisboa",
                "url": "https://publicacoes.mj.pt/x",
                "id": "pub-1",
                "index": "finance_publicacoes_mj",
            }
        ],
    )
    assert stats["events"] == 1
    assert "entidade:600000003" in store.entities
    events = [event for event in store.events if event["kind"] == "publicacao_societaria"]
    assert events and events[0]["ts"] == "2025-06-12" and events[0]["act"] == "constituicao"
    kinds = {kind: label for kind, label in world_model.EVENT_LABELS.items()}
    assert "publicacao_societaria" in kinds and "marca_registada" in kinds and "mencao" in kinds


def test_propriedades_dao_eventos_e_atributos() -> None:
    store = world_model._EntityStore()
    stats = world_model._collect_properties(
        store,
        [
            {
                "kind": "marca",
                "nif": "600000004",
                "entity_name": "Empresa Marca, Lda.",
                "name": "MARCA X",
                "detail": "nacional",
                "ts": "2024-02-02",
                "phase": "concedida",
                "classes": [9, 42],
                "id": "marca-1",
                "index": "finance_trademarks",
            },
            {
                "kind": "firma",
                "nif": "600000004",
                "entity_name": "Empresa Marca, Lda.",
                "detail": "62010",
                "extra": {"situacao": "Ativa", "concelho": "Porto"},
                "id": "firma-1",
                "index": "finance_firmas",
            },
        ],
    )
    assert stats["events"] == 1 and stats["attributes"] == 1
    entity = store.entities["entidade:600000004"]
    assert entity["attributes"]["cae"] == "62010" and entity["attributes"]["situacao"] == "Ativa"
    event = next(event for event in store.events if event["kind"] == "marca_registada")
    assert event["mark"] == "MARCA X" and event["source_id"] == "marca-1"


def test_mencoes_ligam_por_nif_e_por_nome() -> None:
    store = world_model._EntityStore()
    world_model._collect_from_contracts(
        store,
        [
            _contract("m1", ("500000001", "Município A"), ("600000005", "Empresa Mencionada, Lda."), 700.0, "2025-01-05"),
        ],
        version=1,
    )
    folded = world_model._folded_name_index(store)
    stats = world_model._collect_mentions(
        store,
        [
            {
                "kind": "mencao",
                "nif": "600000005",
                "text": "Falência da empresa no próximo ano",
                "ts": "2026-01-10",
                "channel": "social",
                "sentiment": "negativo",
                "sentiment_score": -0.8,
                "url": "https://exemplo.pt/1",
                "id": "men-1",
                "index": "finance_social",
            },
            {
                "kind": "mencao",
                "nif": None,
                "text": "A Empresa Mencionada, Lda. ganhou um contrato",
                "ts": "2026-02-01",
                "channel": "imprensa",
                "sentiment": "positivo",
                "sentiment_score": 0.6,
                "url": "https://exemplo.pt/2",
                "id": "men-2",
                "index": "finance_scraped",
            },
            {
                "kind": "mencao",
                "nif": None,
                "text": "Assunto sem qualquer entidade conhecida",
                "ts": "2026-02-02",
                "channel": "imprensa",
                "id": "men-3",
                "index": "finance_scraped",
            },
        ],
        folded,
    )
    assert stats["events"] == 2 and stats["unmatched"] == 1
    events = [event for event in store.events if event["kind"] == "mencao"]
    assert len(events) == 2
    assert all(event["entity_ref"] == "entidade:600000005" for event in events)
    severities = sorted(event["severity"] for event in events)
    assert severities[0] == 0.25 and severities[1] == 0.55, "negativo pesa mais do que positivo"


def test_nomes_ambiguos_saem_do_indice_de_juncao() -> None:
    store = world_model._EntityStore()
    store.touch("600000001", "Nome Duplicado, Lda.", "adjudicatario", "Portugal", "contratos", "empresa")
    store.touch("600000002", "Nome Duplicado, Lda.", "adjudicatario", "Portugal", "contratos", "empresa")
    store.touch("600000003", "Nome Único, Lda.", "adjudicatario", "Portugal", "contratos", "empresa")
    folded = world_model._folded_name_index(store)
    assert world_sources.fold_name("Nome Duplicado, Lda.") not in folded
    assert world_sources.fold_name("Nome Único, Lda.") in folded


def test_config_traz_as_fontes_associadas() -> None:
    config = world_model.DEFAULT_CONFIG
    assert config["sources"] == world_sources.DEFAULT_SOURCE_IDS
    assert config["source_sample"] >= 1000
    schema = world_model._config_schema() if hasattr(world_model, "_config_schema") else config
    assert "sources" in schema


def test_text_name_matches_ignora_palavras_comuns() -> None:
    folded = {"EMPRESA MENCIONADA LDA": "entidade:1"}
    assert world_model._text_name_matches("a EMPRESA MENCIONADA, LDA. ganhou", folded) == ["entidade:1"]
    assert world_model._text_name_matches("nada a ver", folded) == []


# ---------------------------------------------------------------------------
# Agente sobre a rede: plano, grafo de execução e grafo de evidências
# ---------------------------------------------------------------------------
def test_plano_do_agente_reage_aos_sinais() -> None:
    entity = {"entity_ref": "entidade:1", "name": "Empresa", "metrics": {}}
    without = world_agent.plan({"kind": "entidade", "entity": entity}, {}, None)
    agents = [step["agent"] for step in without]
    assert agents[0] == "observer" and "network" in agents and "verifier" in agents and "narrator" in agents
    assert "simulator" in agents

    anomaly = {"label": "anómalo", "score": 0.7, "signal_ids": ["insolvency", "drop"]}
    with_anomaly = world_agent.plan({"kind": "entidade", "entity": entity}, {}, anomaly)
    scout = next(step for step in with_anomaly if step["agent"] == "scout")
    assert "insolvency" in scout["why"]


def test_grafo_de_execucao_regista_passos_e_fluxos() -> None:
    trace = world_agent._ExecutionTrace()
    planner = trace.add("planner", "planear", outputs={"passos": 3})
    observer = trace.add("observer", "ler estado", parent=planner, flow_label="plano", elapsed_s=0.2)
    trace.add("network", "prever", parent=observer, flow_label="estado")
    assert len(trace.nodes) == 3
    assert len(trace.edges) == 2
    mermaid = trace.mermaid()
    assert mermaid.startswith("flowchart TD")
    assert "planner_1" in mermaid and "observer_2" in mermaid
    assert "classDef passo" in mermaid


def test_grafo_de_evidencias_liga_afirmacoes_a_fontes() -> None:
    claims = [
        {
            "kind": "FACT",
            "claim": "A empresa tem 3 contratos.",
            "confidence": 1.0,
            "sources": ["contratos#c1"],
        }
    ]
    evidence = [
        {"id": "c1", "type": "contrato", "source_index": "contratos", "source_id": "c1", "description": "Contrato A", "value": 100.0}
    ]
    graph_payload = world_agent.build_evidence_graph(claims, evidence, {"entity_id": "600000001", "name": "Empresa X"})
    kinds = {node["type"] for node in graph_payload["nodes"]}
    assert {"sujeito", "afirmacao", "evidencia", "fonte"} <= kinds
    labels = {edge["label"] for edge in graph_payload["edges"]}
    assert "vem de" in labels and "sustenta" in labels
    assert graph_payload["mermaid"].startswith("flowchart LR")
    assert graph_payload["counts"]["fonte"] == 1


def test_mermaid_das_relacoes_e_do_catalogo() -> None:
    ego = {
        "nodes": [{"id": "entidade:1", "name": "Empresa A"}, {"id": "entidade:2", "name": "Município B"}],
        "edges": [{"source": "entidade:1", "target": "entidade:2", "contracts_count": 3, "value_sum": 1500.0}],
    }
    mermaid = world_agent.relations_mermaid(ego, limit=5)
    assert mermaid.startswith("graph LR")
    assert "Empresa A" in mermaid and "Município B" in mermaid

    catalog = world_agent.catalog()
    ids = {item["id"] for item in catalog["agents"]}
    assert {"planner", "observer", "network", "historian", "scout", "simulator", "verifier", "narrator"} <= ids
    assert catalog["mermaid"].startswith("flowchart LR")
    assert all(step["source"] in ids and step["target"] in ids for step in catalog["flow"])
