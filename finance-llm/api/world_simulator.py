"""Future Simulator — t0 → t1 → t2 → t3 sobre o estado do mundo.

O simulador pega no estado (World Model) e nas previsões da rede dinâmica e
projeta o que pode acontecer nos próximos passos, sempre com **distribuições**
(e nunca um número único):

- **novos contratos** — processo de Poisson com taxa estimada da atividade
  recente (eventos/trimestre), corrigida pelo fator de crescimento da rede;
- **atrasos** — probabilidade binomial por contrato, agravada pelo risco e pela
  concentração de clientes (é um *proxy*, não um prazo real);
- **cancelamentos** — probabilidade binomial, muito agravada por insolvência;
- **novas relações** — Poisson sobre o grau da entidade × fator de crescimento;
- **alterações financeiras** — valor dos novos contratos menos o valor
  cancelado e a penalização dos atrasos;
- **mudança de risco** — o risco de saída combina o risco atual, a atividade
  esperada e o stress simulado.

Estima-se 3 cenários (**otimista**, **base**, **pessimista**) com fatores
multiplicativos sobre taxas e probabilidades, cada um com um peso (probabilidade
subjetiva). O resultado final é a agregação de Monte Carlo dos três cenários,
com média e percentis (p10/p50/p90) por passo.

Limitações assumidas: as taxas vêm de uma janela curta de eventos e de uma
amostra de contratos; o objetivo é comparar cenários e ordenar riscos, não
prever valores exatos.
"""
from __future__ import annotations

import logging
import math
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import numpy as np
from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk

from api import world_model as model
from api import world_neural as neural
from api.elasticsearch_client import (
    SIMULATIONS_INDEX,
    WORLD_EVENTS_INDEX,
    WORLD_STATE_INDEX,
    ensure_indices,
    get_es_client,
)

logger = logging.getLogger(__name__)

DEFAULT_PARAMS: Dict[str, Any] = {
    "horizon": 4,
    "step_months": 3,
    "samples": 300,
    "seed": 42,
    # Probabilidades base por contrato (proxy a partir da amostra de eventos).
    "delay_base": 0.16,
    "cancel_base": 0.05,
    # Penalização de valor por atraso (desloca e encarece o contrato).
    "delay_penalty": 0.08,
}

#: Cenários: multiplicadores sobre as taxas e probabilidades base.
SCENARIOS: Dict[str, Dict[str, Any]] = {
    "otimista": {
        "label": "Otimista",
        "contracts": 1.25,
        "delays": 0.70,
        "cancels": 0.55,
        "relations": 1.30,
        "weight": 0.25,
        "note": "Contratação acelera, menos atrasos e cancelamentos.",
    },
    "base": {
        "label": "Base",
        "contracts": 1.00,
        "delays": 1.00,
        "cancels": 1.00,
        "relations": 1.00,
        "weight": 0.50,
        "note": "Continuação das taxas observadas.",
    },
    "pessimista": {
        "label": "Pessimista",
        "contracts": 0.70,
        "delays": 1.60,
        "cancels": 2.10,
        "relations": 0.65,
        "weight": 0.25,
        "note": "Abrandamento, mais atrasos e cancelamentos.",
    },
}


def _client(es: Optional[Elasticsearch] = None) -> Optional[Elasticsearch]:
    return es or get_es_client(request_timeout=90)


def _percentiles(values: np.ndarray) -> Dict[str, float]:
    if values.size == 0:
        return {"mean": 0.0, "p10": 0.0, "p50": 0.0, "p90": 0.0}
    return {
        "mean": round(float(values.mean()), 3),
        "p10": round(float(np.percentile(values, 10)), 3),
        "p50": round(float(np.percentile(values, 50)), 3),
        "p90": round(float(np.percentile(values, 90)), 3),
    }


# ---------------------------------------------------------------------------
# Perfis (sujeito ou mundo inteiro)
# ---------------------------------------------------------------------------
def _quarterly_series(entity_ref: Optional[str], years: int = 4, es: Optional[Elasticsearch] = None) -> List[Dict[str, Any]]:
    """Série por trimestre (nº de eventos e valor), para estimar as taxas."""
    client = _client(es)
    if client is None:
        return []
    filters: List[Dict[str, Any]] = [{"range": {"ts": {"gte": f"now-{max(1, years)}y"}}}]
    if entity_ref:
        filters.append({"term": {"entity_ref": entity_ref}})
    body = {
        "size": 0,
        "track_total_hits": False,
        "query": {"bool": {"filter": filters}},
        "aggs": {
            "series": {
                "date_histogram": {"field": "ts", "calendar_interval": "quarter", "min_doc_count": 0},
                "aggs": {"value": {"sum": {"field": "value"}}},
            }
        },
    }
    try:
        resp = client.search(index=WORLD_EVENTS_INDEX, body=body)
    except Exception as exc:
        logger.warning("Série trimestral falhou: %s", exc)
        return []
    buckets = ((resp.get("aggregations") or {}).get("series") or {}).get("buckets") or []
    return [
        {
            "period": bucket.get("key_as_string"),
            "events": int(bucket.get("doc_count") or 0),
            "value": float((bucket.get("value") or {}).get("value") or 0.0),
        }
        for bucket in buckets
    ]


def _global_profile(es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Perfil agregado do mundo (usado quando não há sujeito)."""
    client = _client(es)
    if client is None:
        raise RuntimeError("Elasticsearch indisponível")
    series = _quarterly_series(None, years=4, es=client)
    counts = np.asarray([item["events"] for item in series], dtype=float)
    values = np.asarray([item["value"] for item in series], dtype=float)
    body = {
        "size": 0,
        "track_total_hits": False,
        "aggs": {
            "entities": {"value_count": {"field": "entity_ref"}},
            "value": {"sum": {"field": "contracts_value"}},
            "risk": {"avg": {"field": "risk"}},
            "insolvent": {"filter": {"term": {"insolvent": True}}},
            "risk_high": {"filter": {"term": {"risk_label": "elevado"}}},
            "by_country": {"terms": {"field": "country", "size": 6}},
        },
    }
    try:
        resp = client.search(index=WORLD_STATE_INDEX, body=body)
        aggs = resp.get("aggregations") or {}
    except Exception:
        aggs = {}
    return {
        "kind": "mundo",
        "subject_ref": None,
        "subject_name": "Mundo (todas as entidades)",
        "subject_type": "world",
        "entities": int((aggs.get("entities") or {}).get("value") or 0),
        "value": float((aggs.get("value") or {}).get("value") or 0.0),
        "risk": float((aggs.get("risk") or {}).get("value") or 0.25),
        "insolvent_count": int((aggs.get("insolvent") or {}).get("doc_count") or 0),
        "high_risk_count": int((aggs.get("risk_high") or {}).get("doc_count") or 0),
        "countries": [{"key": b["key"], "count": b["doc_count"]} for b in (aggs.get("by_country") or {}).get("buckets", [])],
        "rate_contracts": float(counts.mean()) if counts.size else 0.0,
        "rate_value": float(values.mean()) if values.size else 0.0,
        "trend": _trend_ratio(counts),
        "degree": None,
        "concentration": 0.0,
        "insolvent": False,
        "series": series,
    }


def _subject_profile(subject_ref: str, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Perfil de uma entidade: estado, atividade recente e previsão da rede."""
    client = _client(es)
    if client is None:
        raise RuntimeError("Elasticsearch indisponível")
    entity = model.get_entity(subject_ref, es=client)
    if not entity:
        raise ValueError(f"Entidade «{subject_ref}» não existe no World Model.")
    ref = entity.get("entity_ref")
    series = _quarterly_series(ref, years=4, es=client)
    counts = np.asarray([item["events"] for item in series], dtype=float)
    values = np.asarray([item["value"] for item in series], dtype=float)
    prediction = neural.node_prediction(ref, es=client) or {}
    metrics = entity.get("metrics") or {}
    state = entity.get("state") or {}
    return {
        "kind": "entidade",
        "subject_ref": ref,
        "subject_name": entity.get("name") or ref,
        "subject_type": entity.get("entity_type"),
        "value": float(entity.get("contracts_value") or 0.0),
        "contracts": int(entity.get("contracts_count") or 0),
        "risk": float(entity.get("risk") or 0.0),
        "risk_label": entity.get("risk_label"),
        "concentration": float(state.get("concentration") or 0.0),
        "insolvent": bool(entity.get("insolvent")),
        "degree": float(metrics.get("relations") or 0),
        "rate_contracts": float(counts.mean()) if counts.size else float(metrics.get("events_last_year") or 0) / 4.0,
        "rate_value": float(values.mean()) if values.size else float(entity.get("contracts_value") or 0.0) / 8.0,
        "trend": _trend_ratio(counts),
        "network": prediction.get("prediction"),
        "series": series,
    }


def _trend_ratio(counts: np.ndarray) -> float:
    """Razão entre a média recente e a anterior (>1 = a acelerar)."""
    if counts.size < 4:
        return 1.0
    half = counts.size // 2
    previous = float(counts[:half].mean()) or 0.0
    recent = float(counts[half:].mean()) or 0.0
    if previous <= 0:
        return 1.0 if recent <= 0 else 1.5
    return max(0.4, min(2.5, recent / previous))


# ---------------------------------------------------------------------------
# Simulação
# ---------------------------------------------------------------------------
def run(
    subject: Optional[str] = None,
    params: Optional[Dict[str, Any]] = None,
    persist: bool = True,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Corre o simulador de futuro e devolve (e grava) os cenários e as distribuições."""
    started = time.time()
    config = dict(DEFAULT_PARAMS)
    config.update({k: v for k, v in (params or {}).items() if v is not None})
    horizon = max(1, min(12, int(config["horizon"])))
    step_months = max(1, min(12, int(config["step_months"])))
    samples = max(20, min(2000, int(config["samples"])))
    rng = np.random.default_rng(int(config["seed"]))
    client = _client(es)
    if client is None:
        raise RuntimeError("Elasticsearch indisponível")
    ensure_indices(client)

    profile = _subject_profile(subject, es=client) if subject else _global_profile(es=client)

    # Taxas por passo (escala do passo escolhido) e valor médio por contrato.
    steps_per_year = 12.0 / step_months
    rate_contracts = max(0.0, profile["rate_contracts"]) * (step_months / 3.0)
    avg_value = max(0.0, profile["rate_value"]) / max(1.0, profile["rate_contracts"]) if profile["rate_contracts"] else 0.0
    trend = float(profile.get("trend") or 1.0)
    network = profile.get("network") or {}
    growth = float(network.get("expected_contracts") or 0.0)
    if growth > 0:
        # A rede dá um segundo sinal de atividade esperada; mistura-se com a
        # persistência (média 60/40 a favor da série observada).
        rate_contracts = 0.6 * rate_contracts + 0.4 * growth * (step_months / 12.0)
    rate_contracts *= 0.5 + 0.5 * trend

    delay_base = float(config["delay_base"]) * (1.0 + 1.6 * float(profile.get("risk") or 0.0)) * (1.0 + profile.get("concentration") or 0.0)
    cancel_base = float(config["cancel_base"]) * (1.0 + 2.5 * float(profile.get("risk") or 0.0))
    if profile.get("insolvent"):
        cancel_base = min(0.6, cancel_base * 4.0)
        delay_base = min(0.55, delay_base * 1.5)
    relation_rate = max(0.0, float(profile.get("degree") or 0.0)) * 0.08
    if not subject:
        # No mundo inteiro as "relações" são as novas arestas potenciais entre
        # as entidades que já têm atividade.
        relation_rate = max(1.0, math.sqrt(max(1.0, float(profile.get("entities") or 1.0))) * 0.6)

    per_step: List[Dict[str, Any]] = [
        {"step": index + 1, "label": f"t{index + 1}"} for index in range(horizon)
    ]
    scenario_results: Dict[str, Any] = {}

    for scenario_id, scenario in SCENARIOS.items():
        contracts_draws = np.zeros((samples, horizon))
        delays_draws = np.zeros((samples, horizon))
        cancels_draws = np.zeros((samples, horizon))
        relations_draws = np.zeros((samples, horizon))
        value_draws = np.zeros((samples, horizon))
        risk_draws = np.zeros((samples, horizon))

        lam = rate_contracts * float(scenario["contracts"])
        delay_p = min(0.95, delay_base * float(scenario["delays"]))
        cancel_p = min(0.95, cancel_base * float(scenario["cancels"]))
        rel_lam = relation_rate * float(scenario["relations"])
        # Contratos "em execução" herdados do período anterior: sem esta base, os
        # atrasos recairiam só sobre os contratos do próprio passo (subestimando)
        # e, se se usasse a carteira histórica completa, explodiriam. Usa-se a
        # taxa do passo como proxy da carteira ativa.
        carry_over = 0.25 * max(0.0, rate_contracts)

        for sample in range(samples):
            risk = float(profile.get("risk") or 0.0)
            for step in range(horizon):
                # Poisson: novos contratos no passo.
                new_contracts = float(rng.poisson(max(0.0, lam)))
                exposed = max(0.0, new_contracts + carry_over)
                delays = float(rng.binomial(max(1, int(round(exposed))), delay_p))
                cancels = float(rng.binomial(max(1, int(round(exposed))), cancel_p))
                new_relations = float(rng.poisson(max(0.0, rel_lam)))
                # Valor: new_contracts × valor médio (com ruído lognormal leve).
                if avg_value > 0:
                    noise = float(rng.lognormal(mean=0.0, sigma=0.25))
                    gross = new_contracts * avg_value * noise
                else:
                    gross = new_contracts * float(rng.lognormal(mean=8.0, sigma=1.0))
                cancelled_value = cancels * avg_value if avg_value > 0 else 0.0
                penalty = delays * avg_value * float(config["delay_penalty"]) if avg_value > 0 else 0.0
                net = gross - cancelled_value - penalty
                contracts_draws[sample, step] = new_contracts
                delays_draws[sample, step] = delays
                cancels_draws[sample, step] = cancels
                relations_draws[sample, step] = new_relations
                value_draws[sample, step] = net
                # Risco: sobe com a proporção de cancelamentos/atrasos e cai com
                # atividade acima da taxa esperada (tudo em rácios, para não
                # saturar quando a carteira é grande).
                cancel_ratio = cancels / max(1.0, exposed)
                delay_ratio = delays / max(1.0, exposed)
                activity_ratio = new_contracts / max(1.0, lam)
                risk = model._clip(
                    risk
                    + 0.20 * cancel_ratio
                    + 0.05 * delay_ratio
                    - 0.04 * min(2.0, activity_ratio)
                    + (0.03 if profile.get("insolvent") else 0.0)
                )
                risk_draws[sample, step] = risk

        steps = []
        for index in range(horizon):
            steps.append(
                {
                    **per_step[index],
                    "new_contracts": _percentiles(contracts_draws[:, index]),
                    "delays": _percentiles(delays_draws[:, index]),
                    "cancellations": _percentiles(cancels_draws[:, index]),
                    "new_relations": _percentiles(relations_draws[:, index]),
                    "financial_change": _percentiles(value_draws[:, index]),
                    "risk": _percentiles(risk_draws[:, index]),
                }
            )
        scenario_results[scenario_id] = {
            "id": scenario_id,
            "label": scenario["label"],
            "note": scenario["note"],
            "weight": scenario["weight"],
            "rates": {
                "contracts_per_step": round(lam, 4),
                "delay_probability": round(delay_p, 4),
                "cancel_probability": round(cancel_p, 4),
                "relations_per_step": round(rel_lam, 4),
            },
            "steps": steps,
            "totals": {
                "new_contracts": _percentiles(contracts_draws.sum(axis=1)),
                "delays": _percentiles(delays_draws.sum(axis=1)),
                "cancellations": _percentiles(cancels_draws.sum(axis=1)),
                "new_relations": _percentiles(relations_draws.sum(axis=1)),
                "financial_change": _percentiles(value_draws.sum(axis=1)),
                "risk_final": _percentiles(risk_draws[:, -1]),
            },
        }

    # Agregação ponderada pelos pesos dos cenários: mantém a **mesma forma** dos
    # passos por cenário (média e percentis), para a UI e o relatório lerem
    # sempre a mesma estrutura.
    combined_steps: List[Dict[str, Any]] = []
    for index in range(horizon):
        combined: Dict[str, Any] = {}
        for metric in ("new_contracts", "delays", "cancellations", "new_relations", "financial_change", "risk"):
            stats: Dict[str, float] = {}
            for stat in ("mean", "p10", "p50", "p90"):
                stats[stat] = round(
                    sum(
                        scenario_results[sid]["steps"][index][metric][stat] * SCENARIOS[sid]["weight"]
                        for sid in SCENARIOS
                    ),
                    3,
                )
            combined[metric] = stats
        combined_steps.append({**per_step[index], **combined})

    scenario_labels = [SCENARIOS[sid]["label"] for sid in SCENARIOS]
    # Cada linha é um cenário (não a mistura): é isso que mostra a divergência.
    scenario_matrix = [
        [scenario_results[sid]["steps"][index]["new_contracts"]["mean"] for index in range(horizon)]
        for sid in SCENARIOS
    ]

    run_id = f"sim-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"
    document = {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "kind": profile["kind"],
        "subject_ref": profile.get("subject_ref"),
        "subject_name": profile.get("subject_name"),
        "subject_type": profile.get("subject_type"),
        "horizon": horizon,
        "steps_per_year": round(steps_per_year, 2),
        "step_months": step_months,
        "samples": samples,
        "seed": int(config["seed"]),
        "input_version": (model._load_meta() or {}).get("version"),
        "network_version": (neural.latest_state(es=client) or {}).get("version"),
        "steps": combined_steps,
        "scenarios": list(scenario_results.values()),
        "parameters": {**config, "profile": {k: v for k, v in profile.items() if k != "series"}},
        "summary": {
            "subject": profile.get("subject_name"),
            "horizon": horizon,
            "step_months": step_months,
            "samples": samples,
            "scenario_labels": scenario_labels,
            "scenario_matrix": [[round(float(value), 3) for value in row] for row in scenario_matrix],
            "totals": {
                metric: round(
                    sum(scenario_results[sid]["totals"][metric]["mean"] * SCENARIOS[sid]["weight"] for sid in SCENARIOS), 3
                )
                for metric in ("new_contracts", "delays", "cancellations", "new_relations", "financial_change", "risk_final")
            },
            "rates": {
                "contracts_per_step": round(rate_contracts, 4),
                "delay_probability": round(delay_base, 4),
                "cancel_probability": round(cancel_base, 4),
                "carry_over_contacts": round(0.25 * max(0.0, rate_contracts), 3),
                "trend": round(trend, 3),
                "network_growth": round(growth, 3),
            },
            "assumptions": [
                "Novos contratos: Poisson com taxa da atividade recente (eventos/trimestre), corrigida pela tendência e pela rede dinâmica.",
                "Atrasos e cancelamentos: probabilidades binomiais com base empírica baixa e agravamento por risco, concentração e insolvência.",
                "Valor médio por contrato: derivado da série de valores observada; ruído lognormal por passo.",
                "Três cenários com pesos subjetivos (25/50/25).",
            ],
        },
        "status": "concluído",
        "elapsed_s": round(time.time() - started, 2),
    }

    if persist:
        try:
            bulk(client, [{"_index": SIMULATIONS_INDEX, "_id": run_id, "_source": document}], raise_on_error=False)
            client.indices.refresh(index=SIMULATIONS_INDEX)
        except Exception as exc:
            logger.warning("Gravação da simulação falhou: %s", exc)
            document["status"] = "concluído (não gravado)"

    logger.info(
        "Simulação %s (%s/%s passos): %s contratos esperados no total",
        run_id,
        profile.get("subject_name"),
        horizon,
        document["summary"]["totals"]["new_contracts"],
    )
    return document


def list_runs(limit: int = 20, es: Optional[Elasticsearch] = None) -> List[Dict[str, Any]]:
    """Últimas simulações (sem os passos nem os cenários completos)."""
    client = _client(es)
    if client is None:
        return []
    body = {
        "size": max(1, min(100, int(limit))),
        "track_total_hits": False,
        "sort": [{"created_at": {"order": "desc"}}],
        "_source": ["run_id", "created_at", "kind", "subject_ref", "subject_name", "horizon", "samples", "summary", "status"],
    }
    try:
        resp = client.search(index=SIMULATIONS_INDEX, body=body)
    except Exception:
        return []
    return [hit.get("_source") or {} for hit in (resp.get("hits") or {}).get("hits") or []]


def get_run(run_id: str, es: Optional[Elasticsearch] = None) -> Optional[Dict[str, Any]]:
    """Uma simulação pelo identificador."""
    client = _client(es)
    if client is None:
        return None
    try:
        resp = client.get(index=SIMULATIONS_INDEX, id=run_id, ignore=[404])
    except Exception:
        return None
    return resp.get("_source") if resp.get("found") else None
