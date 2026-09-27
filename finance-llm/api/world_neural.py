"""Dynamic Neural Network — crescimento, poda, memória e previsão.

A rede é a camada adaptativa do IQ OS sobre o estado do mundo. É uma rede
**dinâmica** no sentido literal: a topologia muda a cada ciclo (cresce com
entidades e relações novas, poda arestas fracas e padrões esquecidos) e mantém
uma **memória** de padrões de atividade que são reutilizados na previsão.

O que é (e o que não é)
----------------------
- **Growth** — cada ciclo lê o estado do mundo (`finance_world_state`) e as suas
  relações (`finance_world_relations`): os nós são as entidades (com um vetor de
  `features`), as arestas são as relações com peso.
- **Pruning** — as arestas decaem (`decay` por ciclo); abaixo de
  `prune_threshold` são removidas. Nós sem atividade nem eventos recentes são
  desativados; os padrões de memória não usados durante `memory_max_age`
  ciclos são esquecidos.
- **Memory** — aprendizagem competitiva (estilo *online k-means*): cada padrão
  de atividade recente aproxima o padrão de memória mais parecido (cosseno) ou
  cria um novo, até `memory_size`.
- **Prediction** — um *readout* linear (regressão *ridge* em forma fechada,
  `numpy`) prevê a **atividade do próximo período** por entidade a partir das
  features e da vizinhança. O erro reportado (RMSE/R²) é **in-sample** e serve
  para comparar ciclos — não é validação fora da amostra.

Limitação assumida: a previsão é **transversal** (o estado atual das entidades
explica a atividade recente); não há histórico de snapshots do mundo para fazer
previsão verdadeiramente sequencial. O `world_simulator` usa estas previsões
apenas como *priors* das taxas de transição, sempre com distribuições e
intervalos, nunca como valores garantidos.
"""
from __future__ import annotations

import logging
import math
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk

from api import world_model as model
from api.elasticsearch_client import (
    NETWORK_STATE_INDEX,
    WORLD_EVENTS_INDEX,
    WORLD_HISTORY_INDEX,
    WORLD_RELATIONS_INDEX,
    WORLD_STATE_INDEX,
    ensure_indices,
    get_es_client,
)

logger = logging.getLogger(__name__)

DEFAULT_PARAMS: Dict[str, Any] = {
    "max_nodes": 1500,
    "node_limit": 4000,
    "edge_limit": 12000,
    "decay": 0.92,
    "prune_threshold": 0.15,
    "memory_size": 48,
    "memory_match": 0.82,
    "memory_learning_rate": 0.25,
    "memory_max_age": 6,
    "ridge_lambda": 1.0,
    "seed": 42,
    # Anomalias e transição latente (usam o estado temporal).
    "period_limit": 20000,
    "periods_min": 4,
    "anomaly_limit": 60,
    "anomaly_attention": 0.35,
    "anomaly_alert": 0.6,
    "transition_min_pairs": 200,
    #: O histórico lido para ajustar a transição é mais largo do que os nós
    #: modelados: a dinâmica aprende-se com todas as entidades com série.
    "transition_docs": 60000,
}

FEATURE_NAMES = [
    "contracts",
    "value",
    "degree",
    "events_recent",
    "insolvent",
    "concentration",
    "risk",
    "recency",
    "is_public_entity",
    "is_person",
]

#: Features do **período** usadas pelo modelo de transição `z_t → z_{t+1}`.
PERIOD_FEATURES = [
    "cum_contracts",
    "cum_value",
    "cum_counterparties",
    "cum_directors",
    "contracts",
    "value",
    "events",
    "new_counterparties",
    "risk",
]

#: Sinais de anomalia e o peso de cada um na pontuação final.
ANOMALY_WEIGHTS: Dict[str, float] = {
    "insolvency": 0.45,
    "spike": 0.20,
    "drop": 0.20,
    "stall": 0.15,
    "novelty": 0.15,
    "residual": 0.20,
    "directors": 0.15,
}


# ---------------------------------------------------------------------------
# Leitura do mundo
# ---------------------------------------------------------------------------
def _client(es: Optional[Elasticsearch] = None) -> Optional[Elasticsearch]:
    return es or get_es_client(request_timeout=90)


def _load_state(limit: int, es: Elasticsearch) -> List[Dict[str, Any]]:
    """Nós candidatos: entidades com contratos, relações ou eventos.

    O filtro não pode ser só `contracts_count >= 1`: as entidades que aparecem
    **na amostra de contratos** (e que por isso têm relações e eventos) são
    muitas vezes pequenas e não entram nas agregações de topo. Sem elas, a rede
    teria nós mas nenhuma aresta.
    """
    body = {
        "size": max(50, min(5000, int(limit))),
        "track_total_hits": False,
        "query": {
            "bool": {
                "should": [
                    {"range": {"contracts_count": {"gte": 1}}},
                    {"range": {"relations_count": {"gte": 1}}},
                    {"range": {"events_count": {"gte": 1}}},
                ],
                "minimum_should_match": 1,
            }
        },
        "sort": [{"activity": "desc"}, {"contracts_value": "desc"}],
        "_source": [
            "entity_ref",
            "entity_id",
            "entity_type",
            "name",
            "country",
            "roles",
            "contracts_count",
            "contracts_value",
            "relations_count",
            "events_count",
            "counterparties_count",
            "risk",
            "risk_label",
            "activity",
            "activity_trend",
            "insolvent",
            "first_seen",
            "last_event_at",
            "state",
            "metrics",
        ],
    }
    try:
        resp = es.search(index=WORLD_STATE_INDEX, body=body)
    except Exception as exc:
        logger.warning("Leitura do estado do mundo falhou: %s", exc)
        return []
    return [hit.get("_source") or {} for hit in (resp.get("hits") or {}).get("hits") or []]


def _load_state_by_refs(refs: List[str], es: Elasticsearch) -> List[Dict[str, Any]]:
    """Estado de um conjunto explícito de entidades (usado para os nós do grafo).

    Permite que a rede inclua as entidades que **participam nas relações** (as
    que dão as arestas), independentemente de estarem ou não no topo por
    atividade — a ordenação por atividade deixá-las-ia de fora e a rede ficaria
    sem ligações.
    """
    if not refs:
        return []
    out: List[Dict[str, Any]] = []
    for start in range(0, len(refs), 500):
        chunk = refs[start : start + 500]
        try:
            resp = es.mget(index=WORLD_STATE_INDEX, body={"ids": chunk})
        except Exception as exc:
            logger.warning("mget do estado do mundo falhou: %s", exc)
            continue
        for doc in resp.get("docs") or []:
            if doc.get("found"):
                out.append(doc.get("_source") or {})
    return out


def _load_edges(limit: int, es: Elasticsearch) -> List[Dict[str, Any]]:
    body = {
        "size": max(10, min(10000, int(limit))),
        "track_total_hits": False,
        "sort": [{"weight": "desc"}, {"value_sum": "desc"}],
        "_source": ["relation_id", "kind", "source_ref", "target_ref", "weight", "contracts_count", "value_sum", "last_ts"],
    }
    try:
        resp = es.search(index=WORLD_RELATIONS_INDEX, body=body)
    except Exception as exc:
        logger.warning("Leitura das relações falhou: %s", exc)
        return []
    return [hit.get("_source") or {} for hit in (resp.get("hits") or {}).get("hits") or []]


def activity_targets(size: int = 2000, es: Optional[Elasticsearch] = None) -> Dict[str, Dict[str, float]]:
    """Atividade por entidade nos últimos 12 meses e nos 12 anteriores.

    Devolve `{entity_ref: {"recent": n, "previous": n, "value": €}}`.
    """
    client = _client(es)
    if client is None:
        return {}
    body = {
        "size": 0,
        "track_total_hits": False,
        "aggs": {
            "recent": {
                "filter": {"range": {"ts": {"gte": "now-12M"}}},
                "aggs": {"by_ref": {"terms": {"field": "entity_ref", "size": max(10, int(size))}}},
            },
            "previous": {
                "filter": {"range": {"ts": {"gte": "now-24M", "lt": "now-12M"}}},
                "aggs": {"by_ref": {"terms": {"field": "entity_ref", "size": max(10, int(size))}}},
            },
            "recent_value": {
                "filter": {"range": {"ts": {"gte": "now-12M"}}},
                "aggs": {
                    "by_ref": {
                        "terms": {"field": "entity_ref", "size": max(10, int(size))},
                        "aggs": {"v": {"sum": {"field": "value"}}},
                    }
                },
            },
        },
    }
    try:
        resp = client.search(index=WORLD_EVENTS_INDEX, body=body)
    except Exception as exc:
        logger.warning("Agregação de atividade falhou: %s", exc)
        return {}
    aggs = resp.get("aggregations") or {}
    out: Dict[str, Dict[str, float]] = {}
    for bucket in ((aggs.get("recent") or {}).get("by_ref") or {}).get("buckets", []):
        out.setdefault(bucket["key"], {})["recent"] = int(bucket["doc_count"])
    for bucket in ((aggs.get("previous") or {}).get("by_ref") or {}).get("buckets", []):
        out.setdefault(bucket["key"], {})["previous"] = int(bucket["doc_count"])
    for bucket in ((aggs.get("recent_value") or {}).get("by_ref") or {}).get("buckets", []):
        out.setdefault(bucket["key"], {})["value"] = float((bucket.get("v") or {}).get("value") or 0.0)
    return out


# ---------------------------------------------------------------------------
# Features
# ---------------------------------------------------------------------------
def build_features(
    entities: List[Dict[str, Any]],
    edges: List[Dict[str, Any]],
    targets: Dict[str, Dict[str, float]],
) -> Tuple[np.ndarray, List[Dict[str, Any]]]:
    """Constrói a matriz de features (nós × FEATURE_NAMES) e a lista de nós."""
    degree: Dict[str, float] = {}
    for edge in edges:
        for end in (edge.get("source_ref"), edge.get("target_ref")):
            if end:
                degree[end] = degree.get(end, 0.0) + float(edge.get("weight") or 1.0)
    max_degree = max(degree.values(), default=1.0) or 1.0

    rows: List[List[float]] = []
    nodes: List[Dict[str, Any]] = []
    max_recent = max((t.get("recent", 0.0) for t in targets.values()), default=1.0) or 1.0
    current_year = datetime.now(timezone.utc).year

    for entity in entities:
        ref = entity.get("entity_ref")
        if not ref:
            continue
        target = targets.get(ref) or {}
        last_seen = entity.get("last_event_at") or entity.get("first_seen")
        try:
            years_since = max(0.0, current_year - int(str(last_seen)[:4])) if last_seen else 5.0
        except Exception:
            years_since = 5.0
        state = entity.get("state") or {}
        row = [
            math.log1p(float(entity.get("contracts_count") or 0)) / math.log1p(50.0),
            model._log_scale(entity.get("contracts_value"), 8.5),
            float(degree.get(ref, 0.0)) / max_degree,
            float(target.get("recent", 0.0)) / max_recent,
            1.0 if entity.get("insolvent") else 0.0,
            float(state.get("concentration") or 0.0),
            float(entity.get("risk") or 0.0),
            1.0 - min(1.0, years_since / 5.0),
            1.0 if entity.get("entity_type") == "entidade_publica" else 0.0,
            1.0 if entity.get("entity_type") == "pessoa" else 0.0,
        ]
        rows.append(row)
        nodes.append(
            {
                "id": ref,
                "name": entity.get("name") or ref,
                "entity_type": entity.get("entity_type"),
                "risk": entity.get("risk"),
                "risk_label": entity.get("risk_label"),
                "activity_trend": entity.get("activity_trend"),
                "insolvent": bool(entity.get("insolvent")),
                "recent_events": int(target.get("recent", 0) or 0),
                "previous_events": int(target.get("previous", 0) or 0),
                "degree": round(float(degree.get(ref, 0.0)), 3),
                "features": [round(value, 6) for value in row],
            }
        )
    matrix = np.asarray(rows, dtype=float) if rows else np.zeros((0, len(FEATURE_NAMES)))
    return matrix, nodes


def _standardize(matrix: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    if matrix.size == 0:
        return matrix, np.zeros(matrix.shape[1]), np.ones(matrix.shape[1])
    mean = matrix.mean(axis=0)
    std = matrix.std(axis=0)
    std[std < 1e-9] = 1.0
    return (matrix - mean) / std, mean, std


# ---------------------------------------------------------------------------
# Ciclo: crescimento → poda → memória → previsão
# ---------------------------------------------------------------------------
def train(
    params: Optional[Dict[str, Any]] = None,
    es: Optional[Elasticsearch] = None,
    persist: bool = True,
) -> Dict[str, Any]:
    """Corre um ciclo completo da rede dinâmica e devolve (e grava) o estado."""
    started = time.time()
    config = dict(DEFAULT_PARAMS)
    config.update({k: v for k, v in (params or {}).items() if v is not None})
    rng = np.random.default_rng(int(config["seed"]))
    client = _client(es)
    if client is None:
        raise RuntimeError("Elasticsearch indisponível — não é possível treinar a rede.")
    ensure_indices(client)

    previous = latest_state(es=client)
    previous_edges: Dict[str, float] = {}
    previous_patterns: List[Dict[str, Any]] = []
    previous_version = 0
    if previous:
        previous_version = int(previous.get("version") or 0)
        for edge in previous.get("edges") or []:
            key = edge.get("id") or f"{edge.get('source')}>{edge.get('target')}"
            previous_edges[key] = float(edge.get("weight") or 1.0)
        previous_patterns = previous.get("memory") or []

    entities = _load_state(int(config["node_limit"]), client)
    raw_edges = _load_edges(int(config["edge_limit"]), client)
    # Os nós que participam em relações entram **por direito próprio**: são eles
    # que dão as arestas. Metade do orçamento de nós vai para os mais ligados.
    degree_seed: Dict[str, int] = {}
    for edge in raw_edges:
        for end in (edge.get("source_ref"), edge.get("target_ref")):
            if end:
                degree_seed[end] = degree_seed.get(end, 0) + 1
    seeded_refs = [
        ref for ref, _ in sorted(degree_seed.items(), key=lambda item: item[1], reverse=True)[: max(20, int(config["max_nodes"]) // 2)]
    ]
    known = {entity.get("entity_ref") for entity in entities}
    seeded = [entity for entity in _load_state_by_refs(seeded_refs, client) if entity.get("entity_ref") not in known]
    entities = entities + seeded
    targets = activity_targets(size=int(config["node_limit"]), es=client)

    # -- crescimento: nós e arestas que entram neste ciclo ----------------
    matrix, nodes = build_features(entities, raw_edges, targets)
    node_ids = {node["id"] for node in nodes}
    if len(nodes) > int(config["max_nodes"]):
        # Mantém os nós mais relevantes. O critério combina o **grau** (participar
        # no grafo) com a **atividade** — só pela atividade, os maiores
        # adjudicantes públicos (milhares de contratos, mas fora da amostra de
        # relações) enchiam o ciclo e a rede ficava sem uma única aresta.
        ranked = sorted(
            range(len(nodes)),
            key=lambda index: (
                float(nodes[index]["degree"]) + math.log1p(max(0.0, nodes[index]["recent_events"])),
                float(nodes[index]["degree"]),
                nodes[index]["recent_events"],
            ),
            reverse=True,
        )[: int(config["max_nodes"])]
        matrix = matrix[ranked]
        nodes = [nodes[index] for index in ranked]
        node_ids = {node["id"] for node in nodes}

    scaled, mean, std = _standardize(matrix)

    edges: List[Dict[str, Any]] = []
    edges_added = 0
    candidates = 0
    for edge in raw_edges:
        source, target_ref = edge.get("source_ref"), edge.get("target_ref")
        if source not in node_ids or target_ref not in node_ids:
            continue
        candidates += 1
        key = edge.get("relation_id") or f"{source}>{target_ref}"
        # Peso sináptico: a força observada (nº de contratos, saturada em 5 — uma
        # única adjudicação já é um sinal) entra na primeira observação e depois é
        # mantida com decaimento: as arestas que persistem consolidam-se e as que
        # desaparecem decaem até serem podadas.
        strength = min(1.0, float(edge.get("weight") or 1.0) / 5.0)
        decay = float(config["decay"])
        previous_weight = previous_edges.get(key)
        weight = strength if previous_weight is None else decay * previous_weight + (1.0 - decay) * strength
        if previous_weight is None:
            edges_added += 1
        if weight < float(config["prune_threshold"]):
            continue
        edges.append(
            {
                "id": key,
                "source": source,
                "target": target_ref,
                "kind": edge.get("kind"),
                "weight": round(weight, 4),
                "strength": round(strength, 4),
                "value_sum": round(float(edge.get("value_sum") or 0.0), 2),
                "contracts_count": int(edge.get("contracts_count") or 0),
                "last_ts": edge.get("last_ts"),
            }
        )
    pruned_edges = max(0, len(previous_edges) - len(edges))

    # -- memória: padrões de atividade (aprendizagem competitiva) ---------
    memory = [dict(pattern) for pattern in previous_patterns]
    index_of = {node["id"]: index for index, node in enumerate(nodes)}
    memory_hits = 0
    memory_created = 0
    for node in nodes:
        if node["recent_events"] <= 0:
            continue
        index = index_of.get(node["id"])
        if index is None:
            continue
        vector = scaled[index]
        norm = float(np.linalg.norm(vector))
        if norm < 1e-9:
            continue
        best_index = -1
        best_similarity = -1.0
        for position, pattern in enumerate(memory):
            candidate = np.asarray(pattern.get("features") or [], dtype=float)
            if candidate.shape != vector.shape:
                continue
            candidate_norm = float(np.linalg.norm(candidate))
            if candidate_norm < 1e-9:
                continue
            similarity = float(np.dot(vector, candidate) / (norm * candidate_norm))
            if similarity > best_similarity:
                best_similarity = similarity
                best_index = position
        if best_index >= 0 and best_similarity >= float(config["memory_match"]):
            pattern = memory[best_index]
            old = np.asarray(pattern.get("features") or [], dtype=float)
            rate = float(config["memory_learning_rate"])
            updated = old + rate * (vector - old)
            pattern["features"] = [round(value, 6) for value in updated]
            pattern["hits"] = int(pattern.get("hits") or 0) + 1
            pattern["last_used"] = node["id"]
            pattern["age"] = 0
            pattern["label"] = node["name"]
            memory_hits += 1
        elif len(memory) < int(config["memory_size"]):
            memory.append(
                {
                    "id": f"pattern-{len(memory) + 1}",
                    "label": node["name"],
                    "entity_ref": node["id"],
                    "features": [round(value, 6) for value in vector],
                    "hits": 1,
                    "age": 0,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            memory_created += 1
    for pattern in memory:
        if pattern.get("last_used") not in node_ids:
            pattern["age"] = int(pattern.get("age") or 0) + 1
    memory = [pattern for pattern in memory if int(pattern.get("age") or 0) <= int(config["memory_max_age"])]

    # -- previsão: readout ridge (forma fechada) --------------------------
    prediction: Dict[str, Any] = {"rmse": None, "r2": None, "weights": [], "method": "ridge (forma fechada)"}
    scores: Dict[str, float] = {}
    if len(nodes) >= 8:
        target = np.asarray([node["recent_events"] for node in nodes], dtype=float)
        target_scaled = target / (target.max() or 1.0)
        # O alvo (atividade recente) **é** uma das features: mantê-la no readout
        # daria R² = 1 sempre. Exclui-se essa coluna e mede-se a qualidade numa
        # amostra de validação (não vista no treino).
        readout_indices = [index for index, name in enumerate(FEATURE_NAMES) if name != "events_recent"]
        design_all = np.hstack([scaled[:, readout_indices], np.ones((scaled.shape[0], 1))])
        lam = float(config["ridge_lambda"])
        order = rng.permutation(len(nodes))
        holdout = max(2, int(round(0.3 * len(nodes))))
        test_idx, train_idx = order[:holdout], order[holdout:]

        def _fit(rows: np.ndarray, targets: np.ndarray) -> np.ndarray:
            gram = rows.T @ rows + lam * np.eye(rows.shape[1])
            try:
                return np.linalg.solve(gram, rows.T @ targets)
            except np.linalg.LinAlgError:
                return np.linalg.pinv(gram) @ (rows.T @ targets)

        weights = _fit(design_all[train_idx], target_scaled[train_idx])
        predicted = design_all[test_idx] @ weights
        actual = target_scaled[test_idx]
        rmse = float(np.sqrt(np.mean((actual - predicted) ** 2)))
        total = float(np.sum((actual - actual.mean()) ** 2)) or 1.0
        r2 = float(1.0 - np.sum((actual - predicted) ** 2) / total)
        prediction = {
            "rmse": round(rmse, 4),
            "r2": round(r2, 4),
            "weights": [round(float(value), 6) for value in weights[:-1]],
            "bias": round(float(weights[-1]), 6),
            "method": "ridge (forma fechada)",
            "in_sample": False,
            "holdout": 0.3,
            "features_used": [FEATURE_NAMES[i] for i in readout_indices],
        }
        # Previsões (para os nós) com o modelo reajustado a toda a amostra.
        full_weights = _fit(design_all, target_scaled)
        fitted = design_all @ full_weights
        for index, node in enumerate(nodes):
            scores[node["id"]] = float(fitted[index])

    # Crescimento esperado no próximo período: razão entre a atividade recente e a
    # anterior. Sem período anterior não há tendência medida — assume-se 1.0 em
    # vez de saturar no máximo.
    recent_total = sum(int(node["recent_events"]) for node in nodes)
    previous_total = sum(int(node["previous_events"]) for node in nodes)
    if previous_total > 0:
        growth_factor = _clipf((recent_total + 1.0) / (previous_total + 1.0), 0.5, 2.0)
        growth_basis = "atividade recente vs. período anterior"
    else:
        growth_factor = 1.0
        growth_basis = "sem período anterior na amostra de eventos"

    top_predictions = []
    for node in nodes:
        score = scores.get(node["id"])
        if score is None:
            continue
        expected_contracts = round(max(0.0, score) * (node["recent_events"] or 1.0) * growth_factor, 2)
        expected_value = round(expected_contracts * float(node.get("degree") or 0.0) * 1000.0, 2)
        risk_after = model._clip(
            float(node.get("risk") or 0.0) * 0.6 + min(1.0, expected_contracts / 6.0) * 0.25 + (0.3 if node.get("insolvent") else 0.0)
        )
        node["prediction"] = {
            "score": round(score, 4),
            "expected_contracts": expected_contracts,
            "expected_value": expected_value,
            "risk_after": round(risk_after, 4),
        }
        top_predictions.append(
            {
                "entity_ref": node["id"],
                "entity_name": node["name"],
                "entity_type": node.get("entity_type"),
                "score": round(score, 4),
                "expected_contracts": expected_contracts,
                "expected_value": expected_value,
                "risk_after": round(risk_after, 4),
            }
        )
    top_predictions.sort(key=lambda item: item["score"], reverse=True)

    version = int(time.time())
    created_at = datetime.now(timezone.utc).isoformat()

    # -- estado temporal: transição latente + anomalias --------------------
    # A transição `z_{t+1} ≈ A·z_t + b` não se aprende só com os nós escolhidos
    # para a rede: é uma regressão sobre pares de períodos, e com poucos nós
    # (ex.: `max_nodes: 200`) não há pares suficientes. Lê-se por isso um histórico
    # mais largo — só para a transição e as anomalias, não para os nós.
    period_series = load_period_series(refs=sorted(node_ids), limit=int(config["period_limit"]), es=client)
    transition_series = load_period_series(limit=int(config.get("transition_docs") or 60000), es=client)
    if len(transition_series) < len(period_series):
        # Falhou a leitura global (ou o histórico é menor do que o esperado):
        # fica-se com o que existe, em vez de não se ajustar nada.
        transition_series = period_series
    transition_model = fit_transition(transition_series, config, rng)
    detected = detect_anomalies(transition_series, nodes, config, scores)
    anomaly_counts: Dict[str, int] = {}
    for item in detected:
        anomaly_counts[item["label"]] = anomaly_counts.get(item["label"], 0) + 1
    anomaly_counts["total"] = len(detected)
    signal_counts: Dict[str, int] = {}
    for item in detected:
        for signal_id in item["signal_ids"]:
            signal_counts[signal_id] = signal_counts.get(signal_id, 0) + 1

    weights = [float(edge["weight"]) for edge in edges] or [0.0]
    metrics = {
        "nodes": len(nodes),
        "edges": len(edges),
        "edges_added": edges_added,
        "edges_pruned": pruned_edges,
        "edges_below_threshold": max(0, candidates - len(edges)),
        "avg_weight": round(sum(weights) / len(weights), 4),
        "max_weight": round(max(weights), 4),
        "avg_degree": round((2.0 * len(edges)) / max(1, len(nodes)), 4),
        "sparsity": round(1.0 - (2.0 * len(edges)) / max(1.0, len(nodes) * (len(nodes) - 1)), 6),
        "memory_patterns": len(memory),
        "memory_hits": memory_hits,
        "memory_created": memory_created,
        "growth_factor": round(growth_factor, 4),
        "growth_basis": growth_basis,
        "recent_events": recent_total,
        "previous_events": previous_total,
        "rmse": prediction.get("rmse"),
        "r2": prediction.get("r2"),
        "periods": sum(len(periods) for periods in period_series.values()),
        "series": len(period_series),
        "transition_series": len(transition_series),
        "transition_periods": sum(len(periods) for periods in transition_series.values()),
        "transition_pairs": transition_model.get("pairs"),
        "transition_r2": transition_model.get("r2"),
        "anomalies": anomaly_counts,
        "anomaly_signals": signal_counts,
    }
    document = {
        "version": version,
        "created_at": created_at,
        "input_version": (model._load_meta() or {}).get("version"),
        "previous_version": previous_version or None,
        "seed": int(config["seed"]),
        "nodes": nodes,
        "edges": edges,
        "memory": memory,
        "growth": {
            "nodes_added": len(nodes) - len(previous.get("nodes") or []) if previous else len(nodes),
            "edges_added": edges_added,
            "factor": round(growth_factor, 4),
        },
        "pruned": {
            "edges": pruned_edges,
            "nodes": max(0, len(previous.get("nodes") or []) - len(nodes)) if previous else 0,
            "patterns": max(0, len(previous_patterns) - len(memory)),
        },
        "predictions": {
            "readout": prediction,
            "scaler": {"mean": [round(float(v), 6) for v in mean], "std": [round(float(v), 6) for v in std]},
            "features": FEATURE_NAMES,
            "growth_factor": round(growth_factor, 4),
        },
        "transition": transition_model,
        "anomalies": detected,
        "top_anomalies": [
            {
                "entity_ref": item["entity_ref"],
                "entity_name": item["entity_name"],
                "entity_type": item["entity_type"],
                "score": item["score"],
                "label": item["label"],
                "signals": item["signal_ids"],
            }
            for item in detected[:50]
        ],
        "top_predictions": top_predictions[:50],
        "metrics": metrics,
        "params": config,
    }

    written = 0
    errors = 0
    if persist:
        actions = [{"_index": NETWORK_STATE_INDEX, "_id": f"version:{version}", "_source": document}]
        try:
            success, errs = bulk(client, actions, raise_on_error=False, stats_only=False)
            written = int(success)
            errors = len(errs) if isinstance(errs, list) else 0
            client.indices.refresh(index=NETWORK_STATE_INDEX)
        except Exception as exc:
            logger.warning("Gravação do estado da rede falhou: %s", exc)
            errors = 1

    document["duration_s"] = round(time.time() - started, 2)
    document["persisted"] = {"written": written, "errors": errors}
    document["top_predictions"] = top_predictions[:50]
    logger.info(
        "Rede dinâmica treinada (v%s): %s nós, %s arestas (+%s/-%s), %s padrões, R²=%s, %s anomalias%s",
        version,
        metrics["nodes"],
        metrics["edges"],
        edges_added,
        pruned_edges,
        len(memory),
        metrics["r2"],
        len(detected),
        f", transição R²={transition_model.get('r2')}" if transition_model.get("available") else "",
    )
    return document


def _clipf(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def latest_state(es: Optional[Elasticsearch] = None) -> Optional[Dict[str, Any]]:
    """Estado da rede da última versão (mais recente primeiro)."""
    client = _client(es)
    if client is None:
        return None
    body = {
        "size": 1,
        "track_total_hits": False,
        "sort": [{"version": {"order": "desc"}}],
        "query": {"match_all": {}},
    }
    try:
        resp = client.search(index=NETWORK_STATE_INDEX, body=body)
    except Exception:
        return None
    hits = (resp.get("hits") or {}).get("hits") or []
    return hits[0].get("_source") if hits else None


def history(limit: int = 20, es: Optional[Elasticsearch] = None) -> List[Dict[str, Any]]:
    """Histórico de ciclos da rede (métricas por versão), sem o grafo."""
    client = _client(es)
    if client is None:
        return []
    body = {
        "size": max(1, min(100, int(limit))),
        "track_total_hits": False,
        "sort": [{"version": {"order": "desc"}}],
        "_source": ["version", "created_at", "metrics", "pruned", "growth"],
    }
    try:
        resp = client.search(index=NETWORK_STATE_INDEX, body=body)
    except Exception:
        return []
    return [hit.get("_source") or {} for hit in (resp.get("hits") or {}).get("hits") or []]


def recall(entity_ref: str, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Padrões de memória mais próximos das features de uma entidade.

    Mostra como a memória é reutilizada: a entidade é comparada com cada padrão
    guardado (semelhança de cosseno) e são devolvidos os mais próximos.
    """
    state = latest_state(es=es)
    if not state:
        return {"error": "Rede ainda não treinada", "patterns": []}
    nodes = {node["id"]: node for node in state.get("nodes") or []}
    node = nodes.get(entity_ref)
    if not node:
        return {"error": f"Entidade {entity_ref} não existe na rede atual", "patterns": []}
    vector = np.asarray(node.get("features") or [], dtype=float)
    norm = float(np.linalg.norm(vector)) or 1.0
    matches = []
    for pattern in state.get("memory") or []:
        candidate = np.asarray(pattern.get("features") or [], dtype=float)
        if candidate.shape != vector.shape:
            continue
        candidate_norm = float(np.linalg.norm(candidate)) or 1.0
        similarity = float(np.dot(vector, candidate) / (norm * candidate_norm))
        matches.append(
            {
                "pattern_id": pattern.get("id"),
                "label": pattern.get("label"),
                "similarity": round(similarity, 4),
                "hits": pattern.get("hits"),
                "age": pattern.get("age"),
            }
        )
    matches.sort(key=lambda item: item["similarity"], reverse=True)
    return {"entity_ref": entity_ref, "patterns": matches[:5], "memory_size": len(state.get("memory") or [])}


def network_graph(
    limit: int = 90,
    include_memory: bool = True,
    version: Optional[int] = None,
    entity_ref: Optional[str] = None,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """A rede dinâmica **como grafo** (nós = neurónios/entidades, arestas = sinapses).

    É a projeção usada pelo painel: cada nó é uma entidade (com a ativação — os
    eventos recentes —, o risco e a previsão) e cada aresta é uma relação com o
    peso que a rede lhe dá neste ciclo. Com `include_memory`, os **padrões de
    memória** entram como nós próprios, ligados à entidade que os recordou, para
    se ver o que a rede lembra e reutiliza.

    `entity_ref` limita o grafo à vizinhança de uma entidade (ego-rede).
    """
    client = _client(es)
    if client is None:
        return {"error": "Elasticsearch indisponível", "nodes": [], "edges": []}
    state = _state_by_version(client, version)
    if not state:
        return {"error": "A rede ainda não foi treinada.", "nodes": [], "edges": [], "trained": False}

    limit = max(10, min(200, int(limit)))
    all_nodes = state.get("nodes") or []
    all_edges = state.get("edges") or []
    metrics = state.get("metrics") or {}

    def rank(node: Dict[str, Any]) -> Tuple[float, float, float, float]:
        prediction = node.get("prediction") or {}
        # Primeiro os nós **ligados** (senão o grafo desenhado sai sem arestas),
        # depois pela previsão, pelo grau e pela atividade.
        connected = 1.0 if float(node.get("degree") or 0.0) > 0 else 0.0
        return (
            connected,
            float(prediction.get("score") or 0.0),
            float(node.get("degree") or 0.0),
            float(node.get("recent_events") or 0.0),
        )

    if entity_ref:
        origin = entity_ref if entity_ref.startswith(("entidade:", "pessoa:")) else model._ref_for(entity_ref)
        keep = {origin}
        for edge in all_edges:
            if edge.get("source") == origin:
                keep.add(edge.get("target"))
            elif edge.get("target") == origin:
                keep.add(edge.get("source"))
        selected = [node for node in all_nodes if node.get("id") in keep]
    else:
        # Privilegiar nós **ligados**: um grafo de neurónios sem sinapses não
        # mostra a rede. Só se houver poucos ligados é que se completa com o
        # resto (por previsão e atividade).
        connected = [node for node in all_nodes if float(node.get("degree") or 0.0) > 0]
        pool = connected if len(connected) >= max(10, limit // 2) else all_nodes
        selected = sorted(pool, key=rank, reverse=True)[:limit]

    keep_ids = {node.get("id") for node in selected}
    edges = [
        {
            "source": edge.get("source"),
            "target": edge.get("target"),
            "count": int(edge.get("contracts_count") or 0),
            "value": float(edge.get("value_sum") or 0.0),
            "weight": round(float(edge.get("weight") or 0.0), 4),
            "kind": edge.get("kind"),
        }
        for edge in all_edges
        if edge.get("source") in keep_ids and edge.get("target") in keep_ids
    ]

    nodes: List[Dict[str, Any]] = []
    for node in selected:
        prediction = node.get("prediction") or {}
        nodes.append(
            {
                "id": node.get("id"),
                "key": node.get("id"),
                "label": node.get("name") or node.get("id"),
                "type": node.get("entity_type") or "empresa",
                "dimension": "entidade",
                "count": int(node.get("recent_events") or 0),
                "total_value": float(prediction.get("expected_value") or 0.0),
                "activation": int(node.get("recent_events") or 0),
                "degree": float(node.get("degree") or 0.0),
                "risk": node.get("risk"),
                "risk_label": node.get("risk_label"),
                "score": prediction.get("score"),
                "expected_contracts": prediction.get("expected_contracts"),
                "risk_after": prediction.get("risk_after"),
                "insolvent": bool(node.get("insolvent")),
                "trend": node.get("activity_trend"),
                "features": node.get("features"),
                "memory_hits": 0,
            }
        )

    memory_nodes: List[Dict[str, Any]] = []
    memory_edges: List[Dict[str, Any]] = []
    if include_memory:
        node_by_id = {node["id"]: node for node in nodes}
        for pattern in (state.get("memory") or [])[:24]:
            pattern_id = f"memoria:{pattern.get('id')}"
            owner = pattern.get("last_used")
            hits = int(pattern.get("hits") or 0)
            memory_nodes.append(
                {
                    "id": pattern_id,
                    "key": pattern_id,
                    "label": f"Padrão · {pattern.get('label') or pattern.get('id')}",
                    "type": "memoria",
                    "dimension": "memoria",
                    "count": hits,
                    "total_value": 0.0,
                    "activation": hits,
                    "degree": 1.0 if owner else 0.0,
                    "risk": None,
                    "risk_label": None,
                    "score": None,
                    "expected_contracts": None,
                    "risk_after": None,
                    "insolvent": False,
                    "trend": None,
                    "age": pattern.get("age"),
                    "features": None,
                    "memory_hits": hits,
                }
            )
            if owner in node_by_id:
                node_by_id[owner]["memory_hits"] = hits
                memory_edges.append(
                    {
                        "source": owner,
                        "target": pattern_id,
                        "count": hits,
                        "value": 0.0,
                        "weight": round(min(1.0, 0.3 + hits / 10.0), 4),
                        "kind": "memoria",
                    }
                )

    return {
        "trained": True,
        "version": state.get("version"),
        "created_at": state.get("created_at"),
        "nodes": nodes + memory_nodes,
        "edges": edges + memory_edges,
        "memory": [
            {
                "id": pattern.get("id"),
                "label": pattern.get("label"),
                "hits": pattern.get("hits"),
                "age": pattern.get("age"),
                "entity_ref": pattern.get("entity_ref"),
            }
            for pattern in (state.get("memory") or [])[:24]
        ],
        "metrics": metrics,
        "pruned": state.get("pruned"),
        "growth": state.get("growth"),
        "readout": (state.get("predictions") or {}).get("readout"),
        "params": state.get("params"),
        "meta": {
            "dimension_a": "entidade",
            "dimension_b": "memoria" if include_memory and memory_nodes else None,
            "metric": "ativacao",
            "mode": "rede",
            "complete": True,
            "sample_order": "previsão > atividade recente > grau",
            "sample_limit": limit,
            "documents_scanned": len(all_nodes),
            "documents_matching": len(all_nodes),
            "scanned_value": 0.0,
            "nodes_total": len(all_nodes),
            "edges_total": len(all_edges),
            "kept_nodes": len(nodes) + len(memory_nodes),
            "kept_edges": len(edges) + len(memory_edges),
            "omitted_edges": max(0, len(all_edges) - len(edges)),
            "directed": True,
            "notes": [
                f"Ciclo da rede v{state.get('version')} (seed {state.get('seed')}).",
                f"Poda neste ciclo: {(state.get('pruned') or {}).get('edges')} aresta(s), "
                f"{(state.get('pruned') or {}).get('patterns')} padrão(ões).",
                f"Crescimento: {(state.get('growth') or {}).get('factor')}× face ao período anterior.",
                "Nós = entidades (neurónios); arestas = relações (sinapses) com o peso do ciclo atual.",
                "Nós «Padrão · …» são a memória da rede, ligada à entidade que a recordou.",
            ],
            "filters": {},
            "limits": {"nodes": limit, "memory": 24},
        },
    }


# ---------------------------------------------------------------------------
# Estado temporal: sequências, transição latente e anomalias
# ---------------------------------------------------------------------------
def load_period_series(
    refs: Optional[List[str]] = None,
    limit: int = 20000,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """Lê o estado temporal (`finance_world_history`) e agrupa por entidade.

    Devolve `{entity_ref: [período, ...]}` ordenado cronologicamente — a matéria
    -prima do modelo de transição e da deteção de anomalias. `refs` limita às
    entidades modeladas (evita ler 40 mil séries quando só interessam as que
    estão na rede).
    """
    client = _client(es)
    if client is None:
        return {}
    filters: List[Dict[str, Any]] = []
    if refs:
        filters.append({"terms": {"entity_ref": refs[:2000]}})
    body: Dict[str, Any] = {
        "size": min(5000, max(1, int(limit))),
        "track_total_hits": False,
        "query": {"bool": {"filter": filters}} if filters else {"match_all": {}},
        "sort": [{"entity_ref": {"order": "asc"}}, {"period_start": {"order": "asc"}}],
        "_source": [
            "entity_ref",
            "entity_type",
            "name",
            "period",
            "period_start",
            "period_end",
            *PERIOD_FEATURES,
        ],
    }
    out: Dict[str, List[Dict[str, Any]]] = {}
    collected = 0
    # `search_after` em vez de `from/size`: o histórico tem dezenas de milhares de
    # documentos e o Elasticsearch recusa janelas acima de 10 000.
    while collected < int(limit):
        try:
            resp = client.search(index=WORLD_HISTORY_INDEX, body=body)
        except Exception as exc:
            logger.warning("Leitura do estado temporal falhou: %s", exc)
            break
        hits = (resp.get("hits") or {}).get("hits") or []
        if not hits:
            break
        for hit in hits:
            source = hit.get("_source") or {}
            ref = source.get("entity_ref")
            if ref:
                out.setdefault(ref, []).append(source)
        collected += len(hits)
        body["search_after"] = hits[-1].get("sort")
        if len(hits) < body["size"] or not body["search_after"]:
            break
    return out


def _period_vector(period: Dict[str, Any]) -> List[float]:
    """Vetor latente de um período (mesmas features para transição e anomalias)."""
    row: List[float] = []
    for name in PERIOD_FEATURES:
        value = float(period.get(name) or 0.0)
        if name in {"cum_contracts", "cum_value", "cum_counterparties", "cum_directors"}:
            row.append(math.log1p(max(0.0, value)))
        else:
            row.append(value)
    return row


def fit_transition(
    series: Dict[str, List[Dict[str, Any]]],
    params: Dict[str, Any],
    rng: "np.random.Generator",
) -> Dict[str, Any]:
    """Ajusta a transição linear `z_{t+1} ≈ A·z_t + b` (mínimos quadrados).

    É a versão **honesta e verificável** de `f_θ(z_t, a_t, e_t)`: com poucos
    períodos por entidade não há dados para uma rede profunda, mas há para uma
    transição linear — e o erro é medido numa amostra de validação, o que diz se
    o modelo aprendeu alguma coisa ou se só reproduz a média.
    """
    import numpy as np

    pairs_x: List[List[float]] = []
    pairs_y: List[List[float]] = []
    for ref, periods in series.items():
        if len(periods) < 2:
            continue
        vectors = [_period_vector(period) for period in periods]
        for index in range(len(vectors) - 1):
            pairs_x.append(vectors[index])
            pairs_y.append(vectors[index + 1])
    minimum = int(params.get("transition_min_pairs") or 200)
    if len(pairs_x) < minimum:
        return {
            "available": False,
            "reason": f"pares insuficientes ({len(pairs_x)} < {minimum}) — é preciso mais histórico",
            "pairs": len(pairs_x),
            "features": PERIOD_FEATURES,
        }

    x = np.asarray(pairs_x, dtype=float)
    y = np.asarray(pairs_y, dtype=float)
    mean = x.mean(axis=0)
    std = x.std(axis=0)
    std[std < 1e-9] = 1.0
    # Winsorização: sem isto, uma entidade que salta de 0 para milhões num único
    # período produz desvios normalizados enormes que destroem o ajuste (o RMSE
    # passa a medir outliers, não a dinâmica).
    xs = np.clip((x - mean) / std, -8.0, 8.0)
    ys = np.clip((y - mean) / std, -8.0, 8.0)

    order = rng.permutation(len(xs))
    holdout = max(5, int(round(0.3 * len(xs))))
    test_idx, train_idx = order[:holdout], order[holdout:]
    design = np.hstack([xs[train_idx], np.ones((len(train_idx), 1))])
    lam = float(params.get("ridge_lambda") or 1.0)
    gram = design.T @ design + lam * np.eye(design.shape[1])
    try:
        coefficients = np.linalg.solve(gram, design.T @ ys[train_idx])
    except np.linalg.LinAlgError:
        coefficients = np.linalg.pinv(gram) @ (design.T @ ys[train_idx])
    matrix, bias = coefficients[:-1], coefficients[-1]

    predicted = xs[test_idx] @ matrix + bias
    actual = ys[test_idx]
    rmse = float(np.sqrt(np.mean((actual - predicted) ** 2)))
    total = float(np.sum((actual - actual.mean(axis=0)) ** 2)) or 1.0
    r2 = float(1.0 - np.sum((actual - predicted) ** 2) / total)
    per_feature = {
        name: round(float(np.sqrt(np.mean((actual[:, index] - predicted[:, index]) ** 2))), 4)
        for index, name in enumerate(PERIOD_FEATURES)
    }
    return {
        "available": True,
        "pairs": len(pairs_x),
        "entities": sum(1 for periods in series.values() if len(periods) >= 2),
        "holdout": 0.3,
        "rmse": round(rmse, 4),
        "r2": round(r2, 4),
        "rmse_by_feature": per_feature,
        "features": PERIOD_FEATURES,
        "matrix": [[round(float(value), 5) for value in row] for row in matrix.tolist()],
        "bias": [round(float(value), 5) for value in bias.tolist()],
        "scaler": {"mean": [round(float(v), 6) for v in mean], "std": [round(float(v), 6) for v in std]},
        "note": "Transição linear ajustada por mínimos quadrados com validação de 30 %.",
    }


def transition_forecast(
    entity_ref: str,
    steps: int = 4,
    state: Optional[Dict[str, Any]] = None,
    es: Optional[Elasticsearch] = None,
) -> Optional[Dict[str, Any]]:
    """Projeta o estado latente de uma entidade com a transição ajustada.

    Devolve, por passo, os valores esperados de contratos acumulados, valor,
    contrapartes e risco — é isto que o simulador usa para as taxas **variarem no
    tempo** em vez de ficarem constantes.
    """
    import numpy as np

    current = state or latest_state(es=es)
    if not current:
        return None
    transition = current.get("transition") or {}
    if not transition.get("available"):
        return None
    ref = entity_ref if entity_ref.startswith(("entidade:", "pessoa:")) else model._ref_for(entity_ref)
    series = load_period_series(refs=[ref], limit=200, es=es).get(ref) or []
    if not series:
        return None
    vector = np.asarray(_period_vector(series[-1]), dtype=float)
    scaler = transition.get("scaler") or {}
    mean = np.asarray(scaler.get("mean") or [0.0] * len(PERIOD_FEATURES), dtype=float)
    std = np.asarray(scaler.get("std") or [1.0] * len(PERIOD_FEATURES), dtype=float)
    matrix = np.asarray(transition.get("matrix") or [], dtype=float)
    bias = np.asarray(transition.get("bias") or [], dtype=float)
    if matrix.shape != (len(PERIOD_FEATURES), len(PERIOD_FEATURES)):
        return None

    latent = (vector - mean) / np.where(std == 0, 1.0, std)
    forecasts: List[Dict[str, Any]] = []
    last_period = series[-1]
    base = {
        "cum_contracts": float(last_period.get("cum_contracts") or 0.0),
        "cum_value": float(last_period.get("cum_value") or 0.0),
        "cum_counterparties": float(last_period.get("cum_counterparties") or 0.0),
        "risk": float(last_period.get("risk") or 0.0),
    }
    for step in range(1, max(1, min(24, int(steps))) + 1):
        latent = matrix @ latent + bias
        raw = latent * np.where(std == 0, 1.0, std) + mean
        values = {name: float(raw[index]) for index, name in enumerate(PERIOD_FEATURES)}
        forecasts.append(
            {
                "step": step,
                "cum_contracts": round(max(base["cum_contracts"], math.expm1(max(0.0, values["cum_contracts"]))), 2),
                "cum_value": round(max(base["cum_value"], math.expm1(max(0.0, values["cum_value"]))), 2),
                "cum_counterparties": round(
                    max(base["cum_counterparties"], math.expm1(max(0.0, values["cum_counterparties"]))), 2
                ),
                "risk": round(model._clip(max(base["risk"] * 0.5, values["risk"])) if values["risk"] >= 0 else base["risk"], 4),
                "contracts": round(max(0.0, values["contracts"]), 2),
                "value": round(max(0.0, values["value"]), 2),
            }
        )
    return {
        "entity_ref": ref,
        "base_period": last_period.get("period"),
        "steps": forecasts,
        "transition_r2": transition.get("r2"),
    }


def _zscore(value: float, history: List[float]) -> float:
    """Desvio normalizado de um valor face à sua própria história (0 se não houver)."""
    if len(history) < 3:
        return 0.0
    mean = sum(history) / len(history)
    variance = sum((item - mean) ** 2 for item in history) / len(history)
    std = math.sqrt(variance)
    if std < 1e-9:
        return 0.0
    return (value - mean) / std


def detect_anomalies(
    series: Dict[str, List[Dict[str, Any]]],
    nodes: Optional[List[Dict[str, Any]]] = None,
    params: Optional[Dict[str, Any]] = None,
    scores: Optional[Dict[str, float]] = None,
) -> List[Dict[str, Any]]:
    """Deteta anomalias por entidade, comparando cada uma **consigo própria**.

    Sinais (todos normalizados em [0,1] e combinados com pesos explícitos):

    - `insolvency` — insolvência declarada no último período;
    - `spike` — valor do último período muito acima da sua média (z ≥ 2);
    - `drop` — contratos do último período muito abaixo do hábito (z ≤ −1,5);
    - `stall` — sem contratos novos nos últimos períodos apesar de histórico;
    - `novelty` — maioria das contrapartes é nova nos últimos 2 períodos;
    - `residual` — a previsão da rede errou muito nesta entidade;
    - `directors` — alteração de administradores no último período.

    O resultado são **padrões a investigar**, nunca acusações: o relatório do
    agente trata-os como hipóteses.
    """
    import numpy as np

    params = params or DEFAULT_PARAMS
    minimum = int(params.get("periods_min") or 4)
    attention = float(params.get("anomaly_attention") or 0.35)
    alert = float(params.get("anomaly_alert") or 0.6)
    node_by_ref = {node["id"]: node for node in (nodes or [])}

    results: List[Dict[str, Any]] = []
    for ref, periods in series.items():
        if len(periods) < minimum:
            continue
        window = periods[:-1]
        last = periods[-1]
        signals: List[Dict[str, Any]] = []

        events_history = [float(period.get("events") or 0.0) for period in window]
        value_history = [float(period.get("value") or 0.0) for period in window]
        contracts_history = [float(period.get("contracts") or 0.0) for period in window]

        if last.get("insolvent"):
            signals.append({"id": "insolvency", "label": "Insolvência declarada", "detail": f"período {last.get('period')}"})

        value_z = _zscore(float(last.get("value") or 0.0), value_history)
        if value_z >= 2.0 and float(last.get("value") or 0.0) > 0:
            signals.append(
                {
                    "id": "spike",
                    "label": "Pico de valor",
                    "detail": f"{model._fmt_money(last.get('value'))} (z={round(value_z, 2)})",
                }
            )
        contracts_z = _zscore(float(last.get("contracts") or 0.0), contracts_history)
        if contracts_z <= -1.5 and sum(contracts_history) > 0:
            signals.append(
                {
                    "id": "drop",
                    "label": "Quebra de atividade",
                    "detail": f"{int(last.get('contracts') or 0)} contratos (z={round(contracts_z, 2)})",
                }
            )
        recent = periods[-3:]
        if sum(int(period.get("contracts") or 0) for period in recent) == 0 and sum(contracts_history) > 3:
            signals.append({"id": "stall", "label": "Sem contratos novos", "detail": "3 períodos sem adjudicações"})

        counterparties_now = float(last.get("cum_counterparties") or 0.0)
        novelties = sum(int(period.get("new_counterparties") or 0) for period in periods[-2:])
        if novelties >= 2 and (counterparties_now <= 0 or novelties >= 0.5 * counterparties_now):
            signals.append(
                {"id": "novelty", "label": "Contrapartes novas", "detail": f"{novelties} novas nos últimos 2 períodos"}
            )
        if int(last.get("cum_directors") or 0) > int(window[-1].get("cum_directors") or 0):
            signals.append({"id": "directors", "label": "Alteração de administradores", "detail": f"período {last.get('period')}"})

        node = node_by_ref.get(ref) or {}
        prediction = node.get("prediction") or {}
        if scores and ref in scores and float(node.get("recent_events") or 0) > 0:
            observed = min(1.0, float(node.get("recent_events") or 0) / 5.0)
            residual = abs(observed - float(scores[ref]))
            if residual >= 0.5:
                signals.append(
                    {"id": "residual", "label": "Previsão desviada", "detail": f"desvio {round(residual, 3)}"}
                )

        if not signals:
            continue
        score = sum(ANOMALY_WEIGHTS.get(signal["id"], 0.1) for signal in signals)
        score = round(model._clip(score), 4)
        if score < attention:
            continue
        results.append(
            {
                "entity_ref": ref,
                "entity_name": periods[-1].get("name") or node.get("name") or ref,
                "entity_type": periods[-1].get("entity_type") or node.get("entity_type"),
                "period": last.get("period"),
                "score": score,
                "label": "anómalo" if score >= alert else "atenção",
                "signals": signals,
                "signal_ids": [signal["id"] for signal in signals],
                "risk": last.get("risk"),
                "cum_contracts": last.get("cum_contracts"),
                "cum_value": last.get("cum_value"),
                "periods": len(periods),
                "evidence": [
                    {"source_index": WORLD_HISTORY_INDEX, "source_id": f"{ref}@{last.get('period')}"},
                ],
                "interpretation": _anomaly_interpretation([signal["id"] for signal in signals]),
            }
        )

    results.sort(key=lambda item: item["score"], reverse=True)
    limit = int(params.get("anomaly_limit") or 60)
    return results[: max(1, limit)]


def _anomaly_interpretation(signal_ids: List[str]) -> str:
    """Frase neutra que descreve o padrão (sem sugerir irregularidade)."""
    parts: List[str] = []
    if "insolvency" in signal_ids:
        parts.append("existe um processo de insolvência declarado")
    if "spike" in signal_ids:
        parts.append("houve um pico de valor face ao histórico próprio")
    if "drop" in signal_ids:
        parts.append("a atividade caiu face ao histórico próprio")
    if "stall" in signal_ids:
        parts.append("não há adjudicações novas há três períodos")
    if "novelty" in signal_ids:
        parts.append("apareceram várias contrapartes novas")
    if "directors" in signal_ids:
        parts.append("a composição de administradores mudou")
    if "residual" in signal_ids:
        parts.append("a atividade observada desviou-se da previsão da rede")
    if not parts:
        return "Padrão a acompanhar."
    return "Padrão detetado: " + "; ".join(parts) + ". Não implica, por si, irregularidade."


def anomalies(
    limit: int = 60,
    entity_ref: Optional[str] = None,
    version: Optional[int] = None,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Anomalias da última versão da rede (ou recalculadas se ainda não existirem)."""
    client = _client(es)
    state = _state_by_version(client, version) if client is not None else None
    if state is None:
        return {"available": False, "reason": "A rede ainda não foi treinada.", "anomalies": []}
    items = state.get("anomalies") or []
    if entity_ref:
        ref = entity_ref if entity_ref.startswith(("entidade:", "pessoa:")) else model._ref_for(entity_ref)
        items = [item for item in items if item.get("entity_ref") == ref]
    return {
        "available": True,
        "version": state.get("version"),
        "created_at": state.get("created_at"),
        "counts": (state.get("metrics") or {}).get("anomalies") or {},
        "anomalies": items[: max(1, int(limit))],
        "note": "Padrões a investigar (heurísticos), não acusações.",
    }


def transition(state: Optional[Dict[str, Any]] = None, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Modelo de transição latente da última versão da rede."""
    current = state or latest_state(es=es)
    if not current:
        return {"available": False, "reason": "A rede ainda não foi treinada."}
    return current.get("transition") or {"available": False, "reason": "Ciclo antigo, sem transição ajustada."}


def _state_by_version(client: Elasticsearch, version: Optional[int]) -> Optional[Dict[str, Any]]:
    """Estado da rede de uma versão (ou o mais recente)."""
    if not version:
        return latest_state(es=client)
    try:
        resp = client.get(index=NETWORK_STATE_INDEX, id=f"version:{int(version)}", ignore=[404])
    except Exception:
        return None
    return resp.get("_source") if resp.get("found") else None


def state(version: Optional[int] = None, es: Optional[Elasticsearch] = None) -> Optional[Dict[str, Any]]:
    """Estado da rede (versão indicada ou o mais recente)."""
    client = _client(es)
    if client is None:
        return None
    return _state_by_version(client, version)


def node_prediction(entity_ref: str, es: Optional[Elasticsearch] = None) -> Optional[Dict[str, Any]]:
    """Previsão da rede para uma entidade (score, contratos e risco esperados)."""
    state = latest_state(es=es)
    if not state:
        return None
    for node in state.get("nodes") or []:
        if node.get("id") == entity_ref or node.get("id") == model._ref_for(entity_ref):
            return {
                "entity_ref": node.get("id"),
                "name": node.get("name"),
                "prediction": node.get("prediction"),
                "features": dict(zip(FEATURE_NAMES, node.get("features") or [])),
                "readout": (state.get("predictions") or {}).get("readout"),
            }
    return None
