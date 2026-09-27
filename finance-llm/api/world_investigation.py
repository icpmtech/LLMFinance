"""Investigation Agent — Observe → Hypothesize → Search → Validate → Simulate → Report.

O agente não inventa: cada afirmação do relatório tem de estar ancorada numa
fonte do IQ OS, e as contas são feitas em **Python** (nunca pelo LLM). O ciclo é
o do diagrama:

1. **Observe** — resolve o sujeito da pergunta (NIF/NIPC ou designação) no World
   Model e recolhe estado, linha temporal, relações e a previsão da rede.
2. **Hypothesize** — gera hipóteses a partir de regras explícitas sobre o
   estado observado (insolvência, concentração de clientes, queda de atividade,
   exposição a entidades em risco). Cada hipótese diz como pode ser testada.
3. **Search** — recolhe evidência das fontes (contratos PT/ES, CIRE, eventos,
   relações) com `source_index`/`source_id`, para o relatório citar a origem.
4. **Validate** — verifica programaticamente as hipóteses: recalcula contagens e
   somas a partir da evidência e compara com o estado do mundo; classifica cada
   afirmação em FACT, CALCULATION, INFERENCE ou HYPOTHESIS.
5. **Simulate** — corre o simulador de futuro para o sujeito (t0→t3) e anexa as
   distribuições ao relatório.
6. **Evidence Report** — relatório em Markdown com objetivo, observação,
   hipóteses, evidência, validação, simulação e limitações.

Guardado em `finance_world_investigations` (auditoria completa: passos,
argumentos, resultados, validações e tempos).
"""
from __future__ import annotations

import json
import logging
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk

from api import world_graph as graph
from api import world_model as model
from api import world_neural as neural
from api import world_simulator as simulator
from api import world_sources as sources
from api.elasticsearch_client import INVESTIGATIONS_INDEX, ensure_indices, get_es_client

logger = logging.getLogger(__name__)

MAX_EVIDENCE = 40
_NIF_RE = re.compile(r"\b(\d{9})\b")


def _client(es: Optional[Elasticsearch] = None) -> Optional[Elasticsearch]:
    return es or get_es_client(request_timeout=90)


# ---------------------------------------------------------------------------
# 1. Observe
# ---------------------------------------------------------------------------
def resolve_subject(question: str, subject: Optional[str] = None, es: Optional[Elasticsearch] = None) -> Optional[Dict[str, Any]]:
    """Descobre de quem fala a pergunta (NIF explícito, nome ou sujeito indicado)."""
    client = _client(es)
    if client is None:
        return None
    explicit = (subject or "").strip()
    if explicit:
        entity = model.get_entity(explicit, es=client)
        if entity:
            return {"entity": entity, "how": "sujeito indicado"}
    match = _NIF_RE.search(question or "")
    if match:
        entity = model.get_entity(match.group(1), es=client)
        if entity:
            return {"entity": entity, "how": f"NIF {match.group(1)} na pergunta"}
    # Sem NIF: procura no mundo pelo texto da pergunta (2 melhores candidatos).
    words = re.findall(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ0-9&.,-]{2,}", question or "")
    candidates = [word for word in words if word.lower() not in {"qual", "quais", "quem", "sobre", "para", "risco", "contrato", "contratos", "empresa", "empresas", "esta", "está", "estao", "estão", "posicao", "posição", "analise", "análise", "situacao", "situação", "evolucao", "evolução"}]
    best: Optional[Dict[str, Any]] = None
    best_score = 0.0
    for phrase in sorted(candidates, key=len, reverse=True)[:4]:
        result = model.search_entities(q=phrase, size=3, es=client)
        for hit in result.get("results") or []:
            score = float(hit.get("_score") or 0.0)
            if score > best_score:
                best_score = score
                best = {"entity": hit, "how": f"designação «{phrase}»"}
    return best


def _observe(entity: Optional[Dict[str, Any]], es: Elasticsearch) -> Dict[str, Any]:
    """Recolhe o estado observado (entidade ou mundo, se não houver sujeito)."""
    if not entity:
        status = model.index_status(es=es)
        return {
            "kind": "mundo",
            "indexes": status.get("indexes"),
            "distributions": status.get("distributions"),
        }
    ref = entity.get("entity_ref")
    timeline = model.timeline(entity_ref=ref, size=60, es=es)
    relations = model.relations(entity_ref=ref, size=60, es=es)
    prediction = neural.node_prediction(ref, es=es)
    profile = graph.temporal_profile(entity_ref=ref, years=6, es=es)
    metrics = entity.get("metrics") or {}
    value_stats = {
        "total": round(float(entity.get("contracts_value") or 0.0), 2),
        "count": int(entity.get("contracts_count") or 0),
        "avg_ticket": round(
            float(entity.get("contracts_value") or 0.0) / max(1, int(entity.get("contracts_count") or 1)), 2
        ),
    }
    return {
        "kind": "entidade",
        "entity": entity,
        "metrics": metrics,
        "value_stats": value_stats,
        "timeline": timeline.get("events") or [],
        "timeline_total": timeline.get("total"),
        "relations": relations.get("relations") or [],
        "relations_total": relations.get("total"),
        "prediction": prediction,
        "series": profile.get("series") or [],
    }


# ---------------------------------------------------------------------------
# 2. Hypothesize
# ---------------------------------------------------------------------------
def _hypotheses(observation: Dict[str, Any]) -> List[Dict[str, Any]]:
    if observation.get("kind") != "entidade":
        distributions = observation.get("distributions") or {}
        top_risk = distributions.get("top_risk") or []
        hypotheses = [
            {
                "id": "H0",
                "kind": "HYPOTHESIS",
                "statement": "Existem entidades no mundo com risco elevado que merecem investigação individual.",
                "test": "Ordenar as entidades por risco e investigar as primeiras.",
                "basis": [item.get("key") for item in top_risk[:5]],
            }
        ]
        risk_labels = {item.get("key"): item.get("count") for item in distributions.get("risk_labels") or []}
        if risk_labels.get("elevado"):
            hypotheses.append(
                {
                    "id": "H1",
                    "kind": "HYPOTHESIS",
                    "statement": f"{risk_labels['elevado']} entidades estão classificadas com risco elevado.",
                    "test": "Cruzamento com insolvências (CIRE) e concentração de clientes.",
                    "basis": ["distributions.risk_labels"],
                }
            )
        return hypotheses

    entity = observation.get("entity") or {}
    metrics = observation.get("metrics") or {}
    state = entity.get("state") or {}
    relations = observation.get("relations") or []
    hypotheses: List[Dict[str, Any]] = []
    counter = 1

    def add(statement: str, test: str, basis: List[str]) -> None:
        nonlocal counter
        hypotheses.append({"id": f"H{counter}", "kind": "HYPOTHESIS", "statement": statement, "test": test, "basis": basis})
        counter += 1

    concentration = float(state.get("concentration") or 0.0)
    concentration_reliable = bool(state.get("concentration_reliable"))
    insolvency_roles = state.get("insolvency_roles") or []
    if entity.get("insolvent"):
        add(
            "A entidade tem um processo de insolvência declarado, o que agrava o risco de incumprimento.",
            "Confirmar o processo no CIRE (tribunal, data e papel do interveniente).",
            ["state.insolvent", "cire"],
        )
    elif insolvency_roles:
        add(
            f"A entidade aparece em processos CIRE com o papel «{', '.join(insolvency_roles[:2])}», sinal indireto de stress.",
            "Confirmar em que processos e em que papel aparece.",
            ["state.insolvency_roles", "cire"],
        )
    if concentration_reliable and concentration >= 0.4:
        add(
            f"Mais de {round(concentration * 100)}% do valor contratual concentra-se num só cliente — dependência elevada.",
            "Identificar o cliente dominante e o peso relativo das restantes relações.",
            ["state.concentration", "relations"],
        )
    if (entity.get("activity_trend") or "") == "em queda":
        add(
            "A atividade contratual está em queda face ao período anterior, o que pode indicar perda de mercado.",
            "Comparar a série de eventos e valores dos últimos 24 meses.",
            ["state.activity_trend", "events"],
        )
    risky_neighbours = [rel for rel in relations if (rel.get("risk_label") == "elevado")]
    if risky_neighbours:
        add(
            f"Existem {len(risky_neighbours)} relações diretas com entidades em risco elevado (risco de contágio).",
            "Verificar as contrapartes e o valor exposto em cada relação.",
            ["relations", "risk"],
        )
    if float(entity.get("contracts_value") or 0) > 0 and metrics.get("counterparties", 0) <= 2:
        add(
            "A carteira tem poucos clientes face ao valor movimentado — exposição assimétrica.",
            "Verificar a distribuição de valor por contraparte.",
            ["metrics.counterparties", "value"],
        )
    if not hypotheses:
        add(
            "A entidade mantém atividade estável e sem sinais de risco material no estado atual.",
            "Monitorizar a atividade e o aparecimento de eventos de risco.",
            ["state", "metrics"],
        )
    return hypotheses


# ---------------------------------------------------------------------------
# 3. Search
# ---------------------------------------------------------------------------
def _search_evidence(entity: Optional[Dict[str, Any]], observation: Dict[str, Any], es: Elasticsearch) -> List[Dict[str, Any]]:
    """Evidência das fontes, com um teto por tipo.

    Um só tipo de evento pode dominar a linha temporal (ex.: uma entidade
    pública que é **credora** em centenas de insolvências). O teto por tipo
    (`PER_KIND`) mantém a evidência diversificada e legível.
    """
    PER_KIND = 6
    evidence: List[Dict[str, Any]] = []
    seen: set = set()
    per_kind: Dict[str, int] = {}

    def add(item: Dict[str, Any]) -> None:
        kind = str(item.get("type") or "?")
        key = f"{item.get('source_index')}#{item.get('source_id')}"
        if key in seen:
            return
        if per_kind.get(kind, 0) >= PER_KIND:
            return
        seen.add(key)
        per_kind[kind] = per_kind.get(kind, 0) + 1
        evidence.append(item)

    for event in (observation.get("timeline") or [])[:20]:
        add(
            {
                "id": f"event:{event.get('event_id')}",
                "type": event.get("kind"),
                "source_index": event.get("source_index") or "finance_world_events",
                "source_id": event.get("source_id"),
                "description": f"{event.get('kind_label') or event.get('kind')} em {event.get('ts')}"
                + (f" ({event.get('counterparty_name')})" if event.get("counterparty_name") else ""),
                "ts": event.get("ts"),
                "value": event.get("value"),
                "severity": event.get("severity"),
            }
        )
    for relation in (observation.get("relations") or [])[:15]:
        add(
            {
                "id": f"relation:{relation.get('relation_id')}",
                "type": f"relacao_{relation.get('kind')}",
                "source_index": "finance_world_relations",
                "source_id": relation.get("relation_id"),
                "description": f"{relation.get('source_name') or relation.get('source_ref')} → "
                f"{relation.get('target_name') or relation.get('target_ref')} ({relation.get('contracts_count')} contratos)",
                "ts": relation.get("last_ts"),
                "value": relation.get("value_sum"),
            }
        )
    if entity:
        nif = entity.get("entity_id")
        for contract in sources.entity_contracts(str(nif), size=20, es=es):
            add(
                {
                    "id": f"contract:{contract.get('uid')}",
                    "type": "contrato",
                    "source_index": contract.get("index"),
                    "source_id": contract.get("id"),
                    "description": f"{contract.get('date') or 'sem data'} — {contract.get('object') or contract.get('contract_type') or 'contrato'}"
                    + f" ({contract.get('role')})",
                    "ts": contract.get("date"),
                    "value": contract.get("value"),
                    "cpv": [item.get("code") for item in (contract.get("cpv") or [])],
                }
            )
        for process in sources.entity_insolvencies(str(nif), size=10, es=es):
            add(
                {
                    "id": f"cire:{process.get('id')}",
                    "type": "insolvencia",
                    "source_index": process.get("index"),
                    "source_id": process.get("id"),
                    "description": f"Processo {process.get('process') or process.get('id')} ({process.get('type') or 'CIRE'})"
                    + (f" — {process.get('court')}" if process.get("court") else ""),
                    "ts": process.get("ts"),
                    "roles": process.get("roles"),
                }
            )
    return evidence[:MAX_EVIDENCE]


# ---------------------------------------------------------------------------
# 4. Validate
# ---------------------------------------------------------------------------
def _validate(entity: Optional[Dict[str, Any]], observation: Dict[str, Any], evidence: List[Dict[str, Any]]) -> Dict[str, Any]:
    checks: List[Dict[str, Any]] = []
    claims: List[Dict[str, Any]] = []

    contract_evidence = [item for item in evidence if item.get("type") == "contrato"]
    event_evidence = [item for item in evidence if item.get("type") not in {"contrato", "insolvencia"}]
    cire_evidence = [item for item in evidence if item.get("type") == "insolvencia"]

    total_value = sum(float(item.get("value") or 0.0) for item in contract_evidence)
    claims.append(
        {
            "kind": "CALCULATION",
            "claim": f"Valor somado dos {len(contract_evidence)} contratos recolhidos como evidência: {round(total_value, 2)} €.",
            "computed_by": "python",
            "sources": [item["id"] for item in contract_evidence[:10]],
            "confidence": 1.0 if contract_evidence else 0.0,
        }
    )

    if entity:
        state_value = float(entity.get("contracts_value") or 0.0)
        observed_ok = total_value <= state_value * 1.35 + 1.0
        checks.append(
            {
                "check": "Soma da evidência não excede o valor total do estado do mundo",
                "expected": f"<= {round(state_value * 1.35, 2)} €",
                "observed": f"{round(total_value, 2)} €",
                "ok": bool(observed_ok),
            }
        )
        claims.append(
            {
                "kind": "FACT",
                "claim": f"O World Model atribui {int(entity.get('contracts_count') or 0)} contratos e "
                f"{round(state_value, 2)} € a «{entity.get('name')}» (versão {entity.get('world_version')}).",
                "sources": ["finance_world_state"],
                "confidence": 1.0,
            }
        )
        insolvent_state = bool(entity.get("insolvent"))
        insolvent_evidence = bool(cire_evidence)
        checks.append(
            {
                "check": "Insolvência no estado do mundo corroborada por processo CIRE",
                "expected": "true" if insolvent_state else "não aplicável",
                "observed": f"{len(cire_evidence)} processo(s) CIRE",
                "ok": (not insolvent_state) or insolvent_evidence,
            }
        )
        if insolvent_state and insolvent_evidence:
            claims.append(
                {
                    "kind": "FACT",
                    "claim": f"A entidade tem insolvência declarada, corroborada por {len(cire_evidence)} processo(s) do CIRE.",
                    "sources": [item["id"] for item in cire_evidence[:5]],
                    "confidence": 0.95,
                }
            )
        elif insolvent_state:
            claims.append(
                {
                    "kind": "INFERENCE",
                    "claim": "O estado do mundo marca insolvência, mas neste momento não há processo CIRE na evidência recolhida.",
                    "sources": ["finance_world_state"],
                    "confidence": 0.5,
                }
            )
        claims.append(
            {
                "kind": "INFERENCE",
                "claim": f"Concentração de valor no maior cliente: {round(float((entity.get('state') or {}).get('concentration') or 0.0) * 100)}%.",
                "computed_by": "python",
                "sources": ["finance_world_relations"],
                "confidence": 0.8,
            }
        )

    checks.append(
        {
            "check": "Evidência temporal (eventos) disponível",
            "expected": ">= 1 evento",
            "observed": f"{len(event_evidence)} evento(s)",
            "ok": bool(event_evidence),
        }
    )
    corroborated = sum(1 for check in checks if check["ok"])
    return {
        "checks": checks,
        "claims": claims,
        "summary": {
            "checks_total": len(checks),
            "checks_ok": corroborated,
            "evidence_total": len(evidence),
            "contracts": len(contract_evidence),
            "insolvencies": len(cire_evidence),
            "events": len(event_evidence),
        },
    }


# ---------------------------------------------------------------------------
# 6. Report
# ---------------------------------------------------------------------------
def _fmt_money(value: Any) -> str:
    try:
        return f"{float(value):,.2f} €".replace(",", " ")
    except Exception:
        return "—"


def _report(
    question: str,
    subject_how: Optional[str],
    observation: Dict[str, Any],
    hypotheses: List[Dict[str, Any]],
    evidence: List[Dict[str, Any]],
    validation: Dict[str, Any],
    simulation: Optional[Dict[str, Any]],
) -> str:
    entity = observation.get("entity") or {}
    lines: List[str] = []
    lines.append("# Relatório de investigação")
    lines.append("")
    lines.append(f"**Pergunta:** {question}")
    lines.append(f"**Sujeito:** {entity.get('name') or 'mundo (todas as entidades)'}"
                 + (f" — `{entity.get('entity_ref')}`" if entity.get("entity_ref") else "")
                 + (f" *({subject_how})*" if subject_how else ""))
    lines.append(f"**Gerado:** {datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    lines.append("")

    lines.append("## 1. Observação")
    if entity:
        metrics = observation.get("metrics") or {}
        value_stats = observation.get("value_stats") or {}
        lines.append(
            f"- Tipo: **{entity.get('entity_type')}** · país: {entity.get('country')} · estado: **{(entity.get('state') or {}).get('status')}**"
        )
        lines.append(f"- Contratos: **{value_stats.get('count')}** · valor: **{_fmt_money(value_stats.get('total'))}** · ticket médio: {_fmt_money(value_stats.get('avg_ticket'))}")
        lines.append(f"- Relações: {metrics.get('relations')} · contrapartes: {metrics.get('counterparties')} · eventos: {metrics.get('events')}")
        lines.append(f"- Risco: **{entity.get('risk')}** ({entity.get('risk_label')}) · atividade: {entity.get('activity')} ({entity.get('activity_trend')})")
        prediction = (observation.get("prediction") or {}).get("prediction") or {}
        if prediction:
            lines.append(
                f"- Rede dinâmica: score {prediction.get('score')} · contratos esperados {prediction.get('expected_contracts')} · risco projetado {prediction.get('risk_after')}"
            )
    else:
        lines.append(f"- Índices do mundo: {json.dumps(observation.get('indexes') or {}, ensure_ascii=False)}")
    lines.append("")

    lines.append("## 2. Hipóteses")
    for hypothesis in hypotheses:
        lines.append(f"- **{hypothesis['id']}** ({hypothesis['kind']}) — {hypothesis['statement']}  ")
        lines.append(f"  *Como testar:* {hypothesis['test']}")
    lines.append("")

    lines.append("## 3. Evidência")
    if evidence:
        lines.append("| # | Tipo | Data | Valor | Descrição | Origem |")
        lines.append("|---|------|------|-------|-----------|--------|")
        for index, item in enumerate(evidence[:25], start=1):
            lines.append(
                f"| {index} | {item.get('type')} | {item.get('ts') or '—'} | {_fmt_money(item.get('value')) if item.get('value') is not None else '—'} | "
                f"{str(item.get('description') or '')[:110]} | `{item.get('source_index')}#{item.get('source_id')}` |"
            )
    else:
        lines.append("Não foi recolhida evidência adicional.")
    lines.append("")

    lines.append("## 4. Validação")
    for check in validation["checks"]:
        mark = "OK" if check["ok"] else "ATENÇÃO"
        lines.append(f"- [{mark}] {check['check']} — esperado {check['expected']}, observado {check['observed']}")
    lines.append("")
    lines.append("### Afirmações")
    for claim in validation["claims"]:
        lines.append(f"- **{claim['kind']}** — {claim['claim']} _(confiança {claim['confidence']})_")
    lines.append("")

    lines.append("## 5. Simulação de futuro (t0 → t3)")
    if simulation:
        summary = simulation.get("summary") or {}
        totals = summary.get("totals") or {}
        lines.append(
            f"- Passos: {simulation.get('horizon')} × {simulation.get('step_months')} meses · {simulation.get('samples')} amostras · cenários {', '.join(summary.get('scenario_labels') or [])}"
        )
        lines.append(
            f"- Total esperado: **{totals.get('new_contracts')}** contratos novos · {totals.get('delays')} atrasos · {totals.get('cancellations')} cancelamentos · {totals.get('new_relations')} relações novas"
        )
        lines.append(f"- Alteração financeira líquida esperada: **{_fmt_money(totals.get('financial_change'))}** · risco final: {totals.get('risk_final')}")
        lines.append("")
        lines.append("| Passo | Contratos | Atrasos | Cancelamentos | Relações | Δ Financeiro | Risco |")
        lines.append("|-------|-----------|---------|---------------|----------|--------------|-------|")
        for step in simulation.get("steps") or []:
            lines.append(
                f"| {step.get('label')} | {step['new_contracts']['mean']} (p10 {step['new_contracts']['p10']} – p90 {step['new_contracts']['p90']}) | "
                f"{step['delays']['mean']} | {step['cancellations']['mean']} | {step['new_relations']['mean']} | "
                f"{_fmt_money(step['financial_change']['mean'])} | {step['risk']['mean']} |"
            )
    else:
        lines.append("Simulação não executada.")
    lines.append("")

    lines.append("## 6. Limitações")
    lines.append("- O World Model assenta em **amostras** de contratos para eventos e relações (contagens por entidade vêm de agregações).")
    lines.append("- A causalidade é **influência temporal candidata**, não causalidade provada.")
    lines.append("- As previsões da rede dinâmica são estimativas transversais (in-sample) e a simulação usa cenários com pesos subjetivos.")
    lines.append("- A documentação original de cada contrato não foi lida; a evidência são metadados indexados.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Ciclo completo
# ---------------------------------------------------------------------------
def investigate(
    question: str,
    subject: Optional[str] = None,
    params: Optional[Dict[str, Any]] = None,
    simulate: bool = True,
    persist: bool = True,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Corre o ciclo completo de investigação e devolve o relatório com auditoria."""
    started = time.time()
    client = _client(es)
    if client is None:
        raise RuntimeError("Elasticsearch indisponível — não é possível investigar.")
    ensure_indices(client)
    config = {"horizon": 4, "samples": 200, "step_months": 3, "seed": 42}
    config.update({k: v for k, v in (params or {}).items() if v is not None})

    steps: List[Dict[str, Any]] = []

    def _step(name: str, started_at: float, **details: Any) -> None:
        steps.append({"step": name, "elapsed_s": round(time.time() - started_at, 3), **details})

    # 1. Observe
    mark = time.time()
    resolved = resolve_subject(question, subject=subject, es=client)
    entity = (resolved or {}).get("entity")
    observation = _observe(entity, client)
    _step("observe", mark, subject=(entity or {}).get("entity_ref") or "mundo", how=(resolved or {}).get("how"), events=len(observation.get("timeline") or []))

    # 2. Hypothesize
    mark = time.time()
    hypotheses = _hypotheses(observation)
    _step("hypothesize", mark, count=len(hypotheses), ids=[item["id"] for item in hypotheses])

    # 3. Search
    mark = time.time()
    evidence = _search_evidence(entity, observation, client)
    _step("search", mark, evidence=len(evidence))

    # 4. Validate
    mark = time.time()
    validation = _validate(entity, observation, evidence)
    _step("validate", mark, **validation["summary"])

    # 5. Simulate
    simulation: Optional[Dict[str, Any]] = None
    if simulate:
        mark = time.time()
        try:
            simulation = simulator.run(
                subject=(entity or {}).get("entity_ref"),
                params={"horizon": config["horizon"], "samples": config["samples"], "step_months": config["step_months"], "seed": config["seed"]},
                persist=False,
                es=client,
            )
            _step("simulate", mark, totals=(simulation.get("summary") or {}).get("totals"))
        except Exception as exc:
            logger.warning("Simulação na investigação falhou: %s", exc)
            _step("simulate", mark, error=str(exc)[:200])

    # 6. Report
    mark = time.time()
    report = _report(question, (resolved or {}).get("how"), observation, hypotheses, evidence, validation, simulation)
    _step("report", mark, chars=len(report))

    run_id = f"inv-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"
    document = {
        "run_id": run_id,
        "question": question,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "concluída",
        "elapsed_s": round(time.time() - started, 2),
        "subject_ref": (entity or {}).get("entity_ref"),
        "subject_name": (entity or {}).get("name"),
        "subject_type": (entity or {}).get("entity_type"),
        "steps": steps,
        "hypotheses": hypotheses,
        "evidence": evidence,
        "claims": validation["claims"],
        "validation": validation,
        "simulation": simulation,
        "counters": validation["summary"],
        "sources": sorted({str(item.get("source_index")) for item in evidence if item.get("source_index")}),
        "world_version": (entity or {}).get("world_version"),
        "report": report,
        "engine": "world_investigation",
    }

    if persist:
        try:
            bulk(client, [{"_index": INVESTIGATIONS_INDEX, "_id": run_id, "_source": document}], raise_on_error=False)
            client.indices.refresh(index=INVESTIGATIONS_INDEX)
        except Exception as exc:
            logger.warning("Gravação da investigação falhou: %s", exc)

    logger.info("Investigação %s concluída em %s s (%s passos)", run_id, document["elapsed_s"], len(steps))
    return document


def list_runs(limit: int = 20, es: Optional[Elasticsearch] = None) -> List[Dict[str, Any]]:
    """Últimas investigações (resumo, sem o relatório completo)."""
    client = _client(es)
    if client is None:
        return []
    body = {
        "size": max(1, min(100, int(limit))),
        "track_total_hits": False,
        "sort": [{"created_at": {"order": "desc"}}],
        "_source": ["run_id", "question", "created_at", "status", "subject_ref", "subject_name", "elapsed_s", "counters"],
    }
    try:
        resp = client.search(index=INVESTIGATIONS_INDEX, body=body)
    except Exception:
        return []
    return [hit.get("_source") or {} for hit in (resp.get("hits") or {}).get("hits") or []]


def get_run(run_id: str, es: Optional[Elasticsearch] = None) -> Optional[Dict[str, Any]]:
    """Uma investigação completa pelo identificador."""
    client = _client(es)
    if client is None:
        return None
    try:
        resp = client.get(index=INVESTIGATIONS_INDEX, id=run_id, ignore=[404])
    except Exception:
        return None
    return resp.get("_source") if resp.get("found") else None
