"""Agente de investigação **sobre a rede neuronal** — a camada que decide.

Este módulo é a peça que o desenho põe acima da Dynamic Neural Network: a rede
*aprende* a dinâmica do mundo (crescimento, poda, memória, previsão, anomalias e
transição latente); o **agente** decide o que investigar, com que evidência e em
que ordem. O LLM não é o modelo do mundo — é usado (quando existe) só para
linguagem; o planeamento e a escolha de alvos são dados.

Roster de agentes (cada um é um passo com entradas e saídas declaradas):

===========================  =============================================
Agente                        O que faz
===========================  =============================================
`observer`                   Lê o estado do mundo do sujeito
`network`                    Lê previsão, memória e **anomalias** da rede
`historian`                  Reconstrói a série temporal (estado por período)
`scout`                      Vai buscar evidência às fontes (contratos, CIRE…)
`simulator`                  Corre os cenários t0→t3 do sujeito
`verifier`                   Verifica contas e corroboração (código, não LLM)
`narrator`                   Escreve o relatório e os diagramas
===========================  =============================================

O plano **não é fixo**: o `planner` escolhe os passos a partir do que a rede
sinalizou (ex.: anomalia de `drop` obriga a olhar para a série; sinal de
`insolvency` obriga a ir ao CIRE). Cada execução produz três grafos:

- **grafo de execução** — o DAG de decisões (quem chamou quem, com que dados);
- **grafo de evidências** — cada afirmação ligada aos factos e às fontes;
- **grafo de relações** — a ego-rede do sujeito.

Os três têm representação em **Mermaid** (para relatórios) e em nós/arestas
(para serem desenhados na página).
"""
from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk

from api import world_graph as graph
from api import world_investigation as investigation
from api import world_model as model
from api import world_neural as neural
from api import world_simulator as simulator
from api.elasticsearch_client import (
    INVESTIGATIONS_INDEX,
    WORLD_HISTORY_INDEX,
    WORLD_RELATIONS_INDEX,
    WORLD_STATE_INDEX,
    ensure_indices,
    get_es_client,
)

logger = logging.getLogger(__name__)

# A higiene de Mermaid (identificadores e rótulos) vive em `world_model`
# (`mermaid_id`, `mermaid_label`, `mermaid_edge_label`, `MermaidIds`) e é usada
# por **todos** os geradores — pipeline, catálogo, execução, evidências e
# relações. Não se duplica aqui: duas implementações de sanitização divergem.

MAX_EVIDENCE = 40


def _client(es: Optional[Elasticsearch] = None) -> Optional[Elasticsearch]:
    return es or get_es_client(request_timeout=90)


# ---------------------------------------------------------------------------
# Catálogo de agentes
# ---------------------------------------------------------------------------
AGENTS: List[Dict[str, Any]] = [
    {
        "id": "planner",
        "label": "Agente planeador",
        "role": "Decide o que investigar a partir dos sinais da rede",
        "consumes": ["finance_network_state"],
        "produces": ["plano", "alvo"],
    },
    {
        "id": "observer",
        "label": "Agente de observação",
        "role": "Observa o estado do mundo",
        "consumes": [WORLD_STATE_INDEX],
        "produces": ["observação", "métricas", "risco"],
    },
    {
        "id": "network",
        "label": "Agente da rede",
        "role": "Lê previsão, memória, anomalias e transição latente",
        "consumes": ["finance_network_state", WORLD_HISTORY_INDEX],
        "produces": ["previsão", "padrões recordados", "anomalias", "trajetória"],
    },
    {
        "id": "historian",
        "label": "Agente de história",
        "role": "Reconstrói a evolução por períodos",
        "consumes": [WORLD_HISTORY_INDEX],
        "produces": ["série temporal", "quebras", "picos"],
    },
    {
        "id": "scout",
        "label": "Agente de recolha",
        "role": "Vai buscar evidência às fontes públicas",
        "consumes": ["contratos", "contratos_es", "finance_cire"],
        "produces": ["evidência com fonte"],
    },
    {
        "id": "simulator",
        "label": "Agente de simulação",
        "role": "Corre cenários t0→t3 informados pela transição",
        "consumes": ["finance_world_simulations"],
        "produces": ["cenários", "distribuições"],
    },
    {
        "id": "verifier",
        "label": "Agente de verificação",
        "role": "Confere contas e corroboração (código, não LLM)",
        "consumes": ["evidência", "estado"],
        "produces": ["verificações", "afirmações classificadas"],
    },
    {
        "id": "narrator",
        "label": "Agente de narrativa",
        "role": "Escreve o relatório e os diagramas Mermaid",
        "consumes": ["tudo"],
        "produces": ["relatório", "grafo de execução", "grafo de evidências"],
    },
]

#: Fluxo de dados entre agentes (usado no grafo de execução quando tudo corre).
_AGENT_FLOW: List[Tuple[str, str, str]] = [
    ("planner", "observer", "plano"),
    ("planner", "historian", "plano"),
    ("observer", "network", "estado do sujeito"),
    ("historian", "network", "série por período"),
    ("network", "scout", "alvos e hipóteses"),
    ("scout", "verifier", "evidência"),
    ("network", "simulator", "previsão e anomalias"),
    ("simulator", "verifier", "cenários"),
    ("verifier", "narrator", "afirmações verificadas"),
]


# ---------------------------------------------------------------------------
# Grafo de execução
# ---------------------------------------------------------------------------
class _ExecutionTrace:
    """Registo do DAG de execução (nós = passos, arestas = dados que passam)."""

    def __init__(self) -> None:
        self.nodes: List[Dict[str, Any]] = []
        self.edges: List[Dict[str, Any]] = []
        self._by_id: Dict[str, Dict[str, Any]] = {}

    def add(
        self,
        agent: str,
        action: str,
        status: str = "concluído",
        elapsed_s: float = 0.0,
        outputs: Optional[Dict[str, Any]] = None,
        evidence: Optional[List[str]] = None,
        note: Optional[str] = None,
        parent: Optional[str] = None,
        flow_label: Optional[str] = None,
    ) -> str:
        node_id = f"{agent}-{len(self.nodes) + 1}"
        node = {
            "id": node_id,
            "agent": agent,
            "label": next((item["label"] for item in AGENTS if item["id"] == agent), agent),
            "action": action,
            "status": status,
            "elapsed_s": round(float(elapsed_s), 3),
            "outputs": outputs or {},
            "evidence": evidence or [],
            "note": note,
            "dimension": "passo",
            "type": "step",
        }
        self.nodes.append(node)
        self._by_id[node_id] = node
        if parent:
            self.edges.append(
                {
                    "id": f"{parent}->{node_id}",
                    "source": parent,
                    "target": node_id,
                    "label": flow_label or "dados",
                    "kind": "fluxo",
                }
            )
        return node_id

    def mermaid(self) -> str:
        """Diagrama Mermaid do DAG de execução (estados coloridos por classe)."""
        lines = ["flowchart TD"]
        ids = model.MermaidIds()
        for node in self.nodes:
            detail = ", ".join(f"{key}={value}" for key, value in list(node["outputs"].items())[:3])
            text = f"{node['label']}<br/>{node['action']}"
            if detail:
                text += f"<br/><small>{detail}</small>"
            lines.append(f'    {ids(node["id"])}["{model.mermaid_label(text)}"]:::passo')
        for edge in self.edges:
            lines.append(
                f"    {ids(edge['source'])} -->|{model.mermaid_edge_label(edge['label'], limit=40)}| {ids(edge['target'])}"
            )
        lines.append("    classDef passo fill:#0b1a21,stroke:#38bdf8,color:#e6f6fb")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Grafo de evidências
# ---------------------------------------------------------------------------
def build_evidence_graph(
    claims: List[Dict[str, Any]],
    evidence: List[Dict[str, Any]],
    subject: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Liga cada conclusão aos factos e cada facto à sua fonte.

    Estrutura: `conclusão → evidência → origem`. É o que permite auditar o
    relatório: qualquer frase pode ser percorrida até ao documento de origem.
    """
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    seen: set = set()

    def add_node(node_id: str, label: str, kind: str, **extra: Any) -> None:
        if node_id in seen:
            return
        seen.add(node_id)
        nodes.append({"id": node_id, "label": label, "type": kind, "dimension": kind, **extra})

    if subject:
        add_node(
            f"subject:{subject.get('entity_id')}",
            subject.get("name") or subject.get("entity_id") or "sujeito",
            "sujeito",
            count=int(subject.get("contracts_count") or 0),
            total_value=float(subject.get("contracts_value") or 0.0),
        )

    for index, evidence_item in enumerate(evidence):
        evidence_id = evidence_item.get("id") or f"ev{index}"
        source_index = str(evidence_item.get("source_index") or "?")
        source_id = str(evidence_item.get("source_id") or "")
        add_node(
            f"ev:{evidence_id}",
            evidence_item.get("description") or evidence_item.get("type") or evidence_id,
            "evidencia",
            count=1,
            total_value=float(evidence_item.get("value") or 0.0),
            source_index=source_index,
            source_id=source_id,
        )
        add_node(
            f"src:{source_index}#{source_id}",
            f"{source_index}#{source_id}",
            "fonte",
            count=1,
            total_value=0.0,
        )
        edges.append({"id": f"ev:{evidence_id}->src", "source": f"ev:{evidence_id}", "target": f"src:{source_index}#{source_id}", "label": "vem de", "kind": "origem"})

    for index, claim in enumerate(claims):
        claim_id = f"claim:{index + 1}"
        add_node(
            claim_id,
            claim.get("claim", "")[:130],
            "afirmacao",
            count=1,
            total_value=0.0,
            claim_kind=claim.get("kind"),
            confidence=claim.get("confidence"),
        )
        if subject:
            edges.append(
                {"id": f"subject->{claim_id}", "source": f"subject:{subject.get('entity_id')}", "target": claim_id, "label": "sobre", "kind": "análise"}
            )
        for ref in claim.get("sources") or []:
            target = f"ev:{ref}" if f"ev:{ref}" in seen else None
            if target is None:
                # A fonte do claim pode vir como `source_index#source_id`.
                text = str(ref)
                for node in nodes:
                    if node["type"] == "evidencia" and text and text in f"{node.get('source_index')}#{node.get('source_id')}":
                        target = node["id"]
                        break
            if target:
                edges.append({"id": f"{target}->{claim_id}", "source": target, "target": claim_id, "label": "sustenta", "kind": "suporte"})

    mermaid = ["flowchart LR"]
    ids = model.MermaidIds()
    for node in nodes:
        mermaid.append(f'    {ids(node["id"])}["{model.mermaid_label(node["label"])}"]')
    for edge in edges:
        mermaid.append(
            f"    {ids(edge['source'])} -->|{model.mermaid_edge_label(edge['label'])}| {ids(edge['target'])}"
        )

    counts: Dict[str, int] = {}
    for node in nodes:
        counts[node["type"]] = counts.get(node["type"], 0) + 1
    return {
        "nodes": nodes,
        "edges": edges,
        "mermaid": "\n".join(mermaid),
        "counts": counts,
        "metrics": {"nodes": len(nodes), "edges": len(edges)},
    }


# ---------------------------------------------------------------------------
# Grafo de relações (ego-rede do sujeito)
# ---------------------------------------------------------------------------
def relations_mermaid(ego: Dict[str, Any], limit: int = 14) -> str:
    """Mermaid da ego-rede: entidade → vizinhos (arestas rotuladas com o valor).

    Os nomes vêm com espaços e acentos («Administrador da insolvência»), pelo que
    passam por `model.mermaid_id`/`mermaid_label` — sem isso o diagrama é inválido.
    """
    lines = ["graph LR"]
    nodes = {node["id"]: node for node in ego.get("nodes") or []}
    name = lambda node_id: (nodes.get(node_id) or {}).get("name") or node_id  # noqa: E731
    ids = model.MermaidIds()
    for edge in (ego.get("edges") or [])[:limit]:
        source = ids(edge["source"])
        target = ids(edge["target"])
        label = model.mermaid_edge_label(f"{edge.get('contracts_count') or 0} ctr · {model._fmt_money(edge.get('value_sum'))}")
        lines.append(
            f'    {source}["{model.mermaid_label(name(edge["source"]))}"] -->|{label}| '
            f'{target}["{model.mermaid_label(name(edge["target"]))}"]'
        )
    if len(lines) == 1:
        lines.append('    vazio["Sem relações na amostra atual"]')
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Plano
# ---------------------------------------------------------------------------
def plan(
    observation: Dict[str, Any],
    network: Dict[str, Any],
    anomaly: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Decide os passos a executar a partir dos sinais da rede (plano dinâmico).

    O plano é o que distingue este agente de um *pipeline* fixo: cada sinal da
    rede (anomalia, insolvência, previsão desviada, ausência de histórico)
    acrescenta ou remove passos.
    """
    steps: List[Dict[str, Any]] = [
        {"agent": "observer", "action": "ler estado do mundo", "why": "ponto de partida"},
        {"agent": "historian", "action": "reconstruir série por período", "why": "a rede precisa de tempo, não só do retrato"},
        {"agent": "network", "action": "previsão, memória e anomalias", "why": "é a camada que sinaliza o que é surpreendente"},
    ]
    signal_ids = set((anomaly or {}).get("signal_ids") or [])
    if anomaly:
        steps.append(
            {
                "agent": "scout",
                "action": "recolher evidência dos sinais detetados",
                "why": f"anomalia «{anomaly.get('label')}» ({', '.join(sorted(signal_ids)) or 'sem sinais'})",
            }
        )
    else:
        steps.append(
            {
                "agent": "scout",
                "action": "recolher evidência geral",
                "why": "sem anomalia na rede: consolidar evidência básica",
            }
        )
    if observation.get("entity"):
        steps.append({"agent": "simulator", "action": "correr cenários t0→t3", "why": "quantificar o que pode acontecer"})
    steps.append({"agent": "verifier", "action": "verificar contas e corroboração", "why": "nenhuma conclusão sem verificação"})
    steps.append({"agent": "narrator", "action": "relatório + diagramas", "why": "explicar com fonte"})
    prediction = (network.get("prediction") or {}).get("prediction") or {}
    if prediction.get("score") is not None and not anomaly:
        steps.append({"agent": "network", "action": "recalibrar leitura", "why": "previsão sem anomalia associada"})
    return steps


# ---------------------------------------------------------------------------
# Ciclo completo
# ---------------------------------------------------------------------------
def run(
    question: str,
    subject: Optional[str] = None,
    params: Optional[Dict[str, Any]] = None,
    simulate: bool = True,
    persist: bool = True,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Corre o agente sobre a rede e devolve relatório + três grafos.

    O sujeito pode ser indicado explicitamente (`entidade:<nif>`) ou ser
    **escolhido pela rede**: se não houver sujeito, usa-se a entidade com
    anomalia mais alta (é a rede que decide onde vale a pena olhar).
    """
    started = time.time()
    client = _client(es)
    if client is None:
        raise RuntimeError("Elasticsearch indisponível — não é possível correr o agente.")
    ensure_indices(client)
    config = {"horizon": 4, "samples": 300, "step_months": 3, "seed": 42}
    config.update({k: v for k, v in (params or {}).items() if v is not None})

    trace = _ExecutionTrace()
    state = neural.latest_state(es=client) or {}
    anomalies = (state.get("anomalies") or []) if state else []

    # ---- sujeito: indicado, ou o mais anómalo ----------------------------
    chosen_by_network = False
    resolved_how = "sujeito indicado"
    missing_history = False
    if subject:
        entity = model.get_entity(subject, es=client)
        if not entity:
            subject = None
    else:
        entity = None
    if not entity and anomalies:
        top = anomalies[0]
        entity = model.get_entity(top["entity_ref"], es=client)
        chosen_by_network = True
        resolved_how = f"escolhido pela rede (anomalia «{top.get('label')}», score {top.get('score')})"
    if not entity:
        found = investigation.resolve_subject(question, subject=subject, es=client)
        entity = (found or {}).get("entity")
        resolved_how = (found or {}).get("how") or "sem sujeito"

    subject_ref = (entity or {}).get("entity_ref")
    anomaly = next((item for item in anomalies if item.get("entity_ref") == subject_ref), None)
    if anomaly is None and anomalies and not subject_ref:
        anomaly = anomalies[0]

    observation: Dict[str, Any] = {"kind": "mundo" if not entity else "entidade", "entity": entity}

    # ---- plano -----------------------------------------------------------
    mark = time.time()
    network_view: Dict[str, Any] = {"prediction": neural.node_prediction(subject_ref, es=client) if subject_ref else None}
    planned = plan(observation, network_view, anomaly)
    plan_node = trace.add(
        "planner",
        "planear passos a partir dos sinais da rede",
        elapsed_s=time.time() - mark,
        outputs={"passos": len(planned), "anomalia": anomaly.get("label") if anomaly else "—"},
        note=resolved_how,
        evidence=["finance_network_state"],
    )

    # ---- observer --------------------------------------------------------
    mark = time.time()
    if entity:
        metrics = entity.get("metrics") or {}
        observation.update(
            {
                "metrics": metrics,
                "state": entity.get("state") or {},
                "value": float(entity.get("contracts_value") or 0.0),
                "contracts": int(entity.get("contracts_count") or 0),
                "risk": float(entity.get("risk") or 0.0),
                "risk_label": entity.get("risk_label"),
                "world_version": entity.get("world_version"),
            }
        )
    observation["kind"] = "entidade" if entity else "mundo"
    observer_node = trace.add(
        "observer",
        "ler estado do mundo",
        elapsed_s=time.time() - mark,
        outputs={
            "contratos": observation.get("contracts", 0),
            "risco": observation.get("risk", "—"),
            "estado": (observation.get("state") or {}).get("status", "—"),
        },
        evidence=[WORLD_STATE_INDEX],
        parent=plan_node,
        flow_label="plano",
    )

    # ---- historian -------------------------------------------------------
    mark = time.time()
    series = model.history(entity_ref=subject_ref, limit=60, es=client) if subject_ref else model.history_series("quarter", limit=24, es=client)
    history_rows = series.get("series") or []
    missing_history = len(history_rows) < 4
    periods = [row for row in history_rows if row.get("period")]
    historian_node = trace.add(
        "historian",
        "reconstruir série por período",
        elapsed_s=time.time() - mark,
        status="concluído" if periods else "sem histórico",
        outputs={"períodos": len(periods), "último": periods[-1].get("period") if periods else "—"},
        evidence=[f"{WORLD_HISTORY_INDEX}#{subject_ref}"] if subject_ref else [WORLD_HISTORY_INDEX],
        note="Amostra estratificada por ano alimenta o histórico." if periods else "Sem períodos suficientes.",
        parent=plan_node,
        flow_label="plano",
    )

    # ---- network ---------------------------------------------------------
    mark = time.time()
    prediction = network_view.get("prediction") or {}
    recall = neural.recall(subject_ref, es=client) if subject_ref else {"patterns": []}
    trajectory = neural.transition_forecast(subject_ref, steps=int(config["horizon"]), state=state, es=client) if subject_ref else None
    readout = ((state.get("predictions") or {}).get("readout") or {}) if state else {}
    transition_model = (state.get("transition") or {}) if state else {}
    network_node = trace.add(
        "network",
        "previsão, memória e anomalias",
        elapsed_s=time.time() - mark,
        outputs={
            "rede": state.get("version") or "—",
            "anomalia": f"{anomaly.get('label')} ({anomaly.get('score')})" if anomaly else "nenhuma",
            "padrões": len(recall.get("patterns") or []),
            "trajetória": "sim" if trajectory else "n/d",
        },
        evidence=["finance_network_state"],
        note=f"Readout R²={readout.get('r2')} (validação 30 %) · transição R²={transition_model.get('r2')}.",
        parent=observer_node,
        flow_label="estado",
    )
    trace.edges.append(
        {"id": f"{historian_node}->{network_node}", "source": historian_node, "target": network_node, "label": "série", "kind": "fluxo"}
    )

    # ---- scout -----------------------------------------------------------
    mark = time.time()
    evidence: List[Dict[str, Any]] = []
    if entity:
        evidence = investigation._search_evidence(entity, {"timeline": (model.timeline(entity_ref=subject_ref, size=20, es=client).get("events") or []), "relations": (model.relations(entity_ref=subject_ref, size=14, es=client).get("relations") or [])}, client)  # noqa: SLF001
    scout_node = trace.add(
        "scout",
        "recolher evidência às fontes",
        elapsed_s=time.time() - mark,
        outputs={"evidência": len(evidence)},
        evidence=[item.get("source_index") or "?" for item in evidence[:8]],
        parent=network_node,
        flow_label="alvos",
    )

    # ---- simulator -------------------------------------------------------
    simulation: Optional[Dict[str, Any]] = None
    simulator_node: Optional[str] = None
    if simulate:
        mark = time.time()
        try:
            simulation = simulator.run(
                subject=subject_ref,
                params={
                    "horizon": int(config["horizon"]),
                    "samples": int(config["samples"]),
                    "step_months": int(config["step_months"]),
                    "seed": int(config["seed"]),
                },
                persist=False,
                es=client,
            )
            totals = (simulation.get("summary") or {}).get("totals") or {}
            simulator_node = trace.add(
                "simulator",
                "correr cenários t0→t3",
                elapsed_s=time.time() - mark,
                outputs={
                    "contratos": totals.get("new_contracts", "—"),
                    "cancel.": totals.get("cancellations", "—"),
                    "Δ€": model._fmt_int(totals.get("financial_change")),
                },
                evidence=["finance_world_simulations"],
                note="Três cenários (otimista/base/pessimista) com pesos subjetivos.",
                parent=network_node,
                flow_label="previsão",
            )
        except Exception as exc:  # pragma: no cover - depende do ES
            logger.warning("Simulação no agente falhou: %s", exc)
            simulator_node = trace.add(
                "simulator",
                "correr cenários t0→t3",
                status="falhou",
                elapsed_s=time.time() - mark,
                outputs={},
                note=str(exc)[:200],
                parent=network_node,
                flow_label="previsão",
            )

    # ---- verifier --------------------------------------------------------
    mark = time.time()
    hypotheses = investigation._hypotheses(observation)  # noqa: SLF001
    if anomaly:
        hypotheses.append(
            {
                "id": f"H{len(hypotheses) + 1}",
                "kind": "HYPOTHESIS",
                "statement": f"A rede sinalizou o padrão «{anomaly.get('label')}»: {anomaly.get('interpretation')}",
                "test": "Confirmar na série por período e na evidência das fontes.",
                "basis": list(anomaly.get("signal_ids") or []),
            }
        )
    validation = investigation._validate(entity, observation, evidence)  # noqa: SLF001
    claims = list(validation.get("claims") or [])
    if anomaly:
        claims.append(
            {
                "kind": "CALCULATION",
                "claim": f"A rede classificou «{anomaly.get('entity_name')}» com score de anomalia {anomaly.get('score')} "
                f"({anomaly.get('label')}) no período {anomaly.get('period')}.",
                "computed_by": "python",
                "sources": [f"{WORLD_HISTORY_INDEX}#{anomaly.get('entity_ref')}@{anomaly.get('period')}"],
                "confidence": 0.9,
            }
        )
    if transition_model.get("available"):
        claims.append(
            {
                "kind": "CALCULATION",
                "claim": f"Modelo de transição latente ajustado com {transition_model.get('pairs')} pares "
                f"(R²={transition_model.get('r2')} numa amostra de 30 % não vista).",
                "computed_by": "python",
                "sources": ["finance_network_state"],
                "confidence": 0.85,
            }
        )
    extra_checks = list(validation.get("checks") or [])
    extra_checks.append(
        {
            "check": "Histórico temporal suficiente para analisar evolução",
            "expected": ">= 4 períodos",
            "observed": f"{len(periods)} períodos",
            "ok": len(periods) >= 4,
        }
    )
    if anomaly:
        extra_checks.append(
            {
                "check": "Anomalia da rede tem evidência correspondente nas fontes",
                "expected": ">= 1 item de evidência",
                "observed": f"{len(evidence)} itens",
                "ok": len(evidence) > 0,
            }
        )
    verifier_node = trace.add(
        "verifier",
        "verificar contas e corroboração",
        elapsed_s=time.time() - mark,
        outputs={
            "verificações": f"{sum(1 for c in extra_checks if c['ok'])}/{len(extra_checks)}",
            "afirmações": len(claims),
        },
        evidence=[item["id"] for item in evidence[:10]],
        note="Contas em Python; nenhuma conclusão sem fonte.",
        parent=scout_node,
        flow_label="evidência",
    )
    if simulator_node:
        trace.edges.append({"id": f"{simulator_node}->{verifier_node}", "source": simulator_node, "target": verifier_node, "label": "cenários", "kind": "fluxo"})

    # ---- grafos ----------------------------------------------------------
    ego = graph.build_graph(entity_ref=subject_ref, depth=1, node_limit=60, edge_limit=120, es=client) if subject_ref else {"nodes": [], "edges": [], "metrics": {"nodes": 0, "edges": 0}}
    evidence_graph = build_evidence_graph(claims, evidence, entity)
    relations_graph = {
        **ego,
        "mermaid": relations_mermaid(ego, limit=14),
    }

    # ---- narrator --------------------------------------------------------
    mark = time.time()
    report = _report(
        question=question,
        how=resolved_how,
        entity=entity,
        observation=observation,
        network={
            "prediction": prediction,
            "recall": recall,
            "readout": readout,
            "transition": transition_model,
            "trajectory": trajectory,
            "version": state.get("version"),
        },
        anomaly=anomaly,
        periods=periods,
        hypotheses=hypotheses,
        evidence=evidence,
        validation=validation,
        checks=extra_checks,
        simulation=simulation,
        trace=trace,
        evidence_graph=evidence_graph,
        relations_graph=relations_graph,
    )
    narrator_node = trace.add(
        "narrator",
        "relatório + diagramas",
        elapsed_s=time.time() - mark,
        outputs={"caracteres": len(report), "grafos": 3},
        evidence=[],
        note="Inclui Mermaid do grafo de execução, de evidências e de relações.",
        parent=verifier_node,
        flow_label="afirmações",
    )
    trace.edges.append(
        {
            "id": f"{network_node}->{narrator_node}",
            "source": network_node,
            "target": narrator_node,
            "label": "anomalia",
            "kind": "fluxo",
        }
    )

    run_id = f"agent-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"
    document = {
        "run_id": run_id,
        "question": question,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "concluída",
        "engine": "world_agent",
        "elapsed_s": round(time.time() - started, 2),
        "subject_ref": subject_ref,
        "subject_name": (entity or {}).get("name"),
        "subject_type": (entity or {}).get("entity_type"),
        "subject_resolution": resolved_how,
        "chosen_by_network": chosen_by_network,
        "network_version": state.get("version"),
        "anomaly": anomaly,
        "plan": planned,
        "execution_graph": {
            "nodes": trace.nodes,
            "edges": trace.edges,
            "mermaid": trace.mermaid(),
            "metrics": {"steps": len(trace.nodes), "flows": len(trace.edges)},
        },
        "evidence_graph": evidence_graph,
        "relations_graph": relations_graph,
        "hypotheses": hypotheses,
        "evidence": evidence,
        "claims": claims,
        "validation": {**validation, "checks": extra_checks},
        "simulation": simulation,
        "counters": {
            **validation.get("summary", {}),
            "periods": len(periods),
            "checks_total": len(extra_checks),
            "checks_ok": sum(1 for check in extra_checks if check["ok"]),
            "anomaly_score": (anomaly or {}).get("score"),
        },
        "sources": sorted({str(item.get("source_index")) for item in evidence if item.get("source_index")}),
        "world_version": (entity or {}).get("world_version"),
        "report": report,
    }

    if persist:
        try:
            # `refresh: wait_for` garante que a execução fica **imediatamente**
            # pesquisável: sem isto, a listagem logo a seguir ao POST vinha vazia
            # (o índice só se torna visível no refresh periódico do Elasticsearch).
            bulk(
                client,
                [{"_index": INVESTIGATIONS_INDEX, "_id": run_id, "_source": document, "refresh": "wait_for"}],
                raise_on_error=False,
            )
            client.indices.refresh(index=INVESTIGATIONS_INDEX, ignore_unavailable=True)
        except Exception as exc:
            logger.warning("Gravação da execução do agente falhou: %s", exc)

    logger.info(
        "Agente (%s) sobre %s: %s passos, %s evidências, anomalia=%s em %s s",
        run_id,
        subject_ref or "mundo",
        len(trace.nodes),
        len(evidence),
        (anomaly or {}).get("label", "—"),
        document["elapsed_s"],
    )
    return document


# ---------------------------------------------------------------------------
# Relatório
# ---------------------------------------------------------------------------
def _report(
    *,
    question: str,
    how: str,
    entity: Optional[Dict[str, Any]],
    observation: Dict[str, Any],
    network: Dict[str, Any],
    anomaly: Optional[Dict[str, Any]],
    periods: List[Dict[str, Any]],
    hypotheses: List[Dict[str, Any]],
    evidence: List[Dict[str, Any]],
    validation: Dict[str, Any],
    checks: List[Dict[str, Any]],
    simulation: Optional[Dict[str, Any]],
    trace: _ExecutionTrace,
    evidence_graph: Dict[str, Any],
    relations_graph: Dict[str, Any],
) -> str:
    """Relatório Markdown com os diagramas Mermaid incorporados."""
    lines: List[str] = []
    lines.append("# Relatório do agente (sobre a rede neuronal)")
    lines.append("")
    lines.append(f"**Pergunta:** {question}")
    lines.append(f"**Sujeito:** {observation['entity'].get('name') if observation.get('entity') else 'mundo (todas as entidades)'}")
    if observation.get("entity"):
        lines.append(f"**Referência:** `{observation['entity'].get('entity_ref')}` · *{how}*")
    else:
        lines.append(f"*{how}*")
    lines.append(f"**Gerado:** {datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    lines.append(f"**Rede:** versão {network.get('version') or '—'} · readout R²={network.get('readout', {}).get('r2')} · transição R²={(network.get('transition') or {}).get('r2')}")
    lines.append("")

    lines.append("## 1. Observação")
    if observation.get("entity"):
        state = observation.get("state") or {}
        lines.append(
            f"- Estado: **{state.get('status')}** · risco **{observation.get('risk')}** ({observation.get('risk_label')}) · "
            f"contratos {model._fmt_int(observation.get('contracts'))} · valor {model._fmt_money(observation.get('value'))}"
        )
        metrics = observation.get("metrics") or {}
        lines.append(
            f"- Relações {metrics.get('relations')} · contrapartes {metrics.get('counterparties')} · clientes {metrics.get('clients')} · "
            f"fonte dos totais: {metrics.get('value_source')}"
        )
    else:
        lines.append("- Sem sujeito: a rede não tinha anomalias e o texto da pergunta não identificou uma entidade.")
    lines.append("")

    lines.append("## 2. Sinais da rede neuronal")
    prediction = (network.get("prediction") or {}).get("prediction") or {}
    if prediction:
        lines.append(
            f"- Previsão: score {prediction.get('score')} · contratos esperados {prediction.get('expected_contracts')} · "
            f"risco projetado {prediction.get('risk_after')}"
        )
    patterns = network.get("recall", {}).get("patterns") or []
    if patterns:
        lines.append(
            "- Memória: padrões mais próximos — "
            + "; ".join(f"{item.get('label')} (sim. {item.get('similarity')})" for item in patterns[:3])
        )
    if anomaly:
        lines.append(f"- **Anomalia:** {anomaly.get('label')} (score {anomaly.get('score')}) no período {anomaly.get('period')}")
        lines.append(f"  - {anomaly.get('interpretation')}")
        for signal in anomaly.get("signals") or []:
            lines.append(f"  - `{signal['id']}` — {signal['label']}: {signal.get('detail')}")
    else:
        lines.append("- Sem anomalia detetada para o sujeito na versão atual da rede.")
    trajectory = network.get("trajectory")
    if trajectory:
        steps = trajectory.get("steps") or []
        lines.append(
            "- Trajetória latente (transição ajustada): "
            + " → ".join(f"t{item['step']}: {item['cum_contracts']} ctr / risco {item['risk']}" for item in steps[:4])
        )
    lines.append("")

    lines.append("## 3. Evolução por período (estado temporal)")
    if periods:
        lines.append("| Período | Contratos | Valor | Eventos | Contrapartes novas | Risco |")
        lines.append("|---------|-----------|-------|---------|--------------------|-------|")
        for row in periods[-8:]:
            lines.append(
                f"| {row.get('period')} | {row.get('contracts', 0)} | {model._fmt_money(row.get('value'))} | "
                f"{row.get('events', 0)} | {row.get('new_counterparties', 0)} | {row.get('risk')} |"
            )
    else:
        lines.append("Sem períodos suficientes (reconstruir o mundo com mais histórico).")
    lines.append("")

    lines.append("## 4. Hipóteses")
    for hypothesis in hypotheses:
        lines.append(f"- **{hypothesis['id']}** ({hypothesis['kind']}) — {hypothesis['statement']}")
        lines.append(f"  *Como testar:* {hypothesis['test']}")
    lines.append("")

    lines.append("## 5. Evidência")
    if evidence:
        lines.append("| # | Tipo | Data | Valor | Descrição | Origem |")
        lines.append("|---|------|------|-------|-----------|--------|")
        for index, item in enumerate(evidence[:20], start=1):
            lines.append(
                f"| {index} | {item.get('type')} | {item.get('ts') or '—'} | "
                f"{model._fmt_money(item.get('value')) if item.get('value') is not None else '—'} | "
                f"{str(item.get('description') or '')[:100]} | `{item.get('source_index')}#{item.get('source_id')}` |"
            )
    else:
        lines.append("Sem evidência adicional recolhida.")
    lines.append("")

    lines.append("## 6. Verificação")
    for check in checks:
        lines.append(f"- [{'OK' if check['ok'] else 'ATENÇÃO'}] {check['check']} — esperado {check['expected']}, observado {check['observed']}")
    lines.append("")
    lines.append("### Afirmações (com tipo e confiança)")
    for claim in validation.get("claims") or []:
        lines.append(f"- **{claim['kind']}** — {claim['claim']} _(confiança {claim['confidence']})_")
    lines.append("")

    if simulation:
        totals = (simulation.get("summary") or {}).get("totals") or {}
        lines.append("## 7. Simulação (t0 → t{})".format(simulation.get("horizon")))
        lines.append(
            f"- Total esperado: **{totals.get('new_contracts')}** contratos · {totals.get('delays')} atrasos · "
            f"{totals.get('cancellations')} cancelamentos · {totals.get('new_relations')} relações novas"
        )
        lines.append(f"- Alteração financeira líquida: **{model._fmt_money(totals.get('financial_change'))}** · risco final {totals.get('risk_final')}")
        lines.append("")
        lines.append("| Passo | Contratos (p10–p90) | Atrasos | Cancelamentos | Δ Financeiro | Risco |")
        lines.append("|-------|---------------------|---------|---------------|--------------|-------|")
        for step in simulation.get("steps") or []:
            lines.append(
                f"| {step.get('label')} | {step['new_contracts']['mean']} "
                f"({step['new_contracts']['p10']}–{step['new_contracts']['p90']}) | {step['delays']['mean']} | "
                f"{step['cancellations']['mean']} | {model._fmt_money(step['financial_change']['mean'])} | {step['risk']['mean']} |"
            )
        lines.append("")

    lines.append("## 8. Grafo de execução (Mermaid)")
    lines.append("```mermaid")
    lines.append(trace.mermaid())
    lines.append("```")
    lines.append("")
    lines.append("## 9. Grafo de evidências (Mermaid)")
    lines.append("```mermaid")
    lines.append(evidence_graph.get("mermaid") or "flowchart LR")
    lines.append("```")
    lines.append("")
    lines.append("## 10. Grafo de relações (Mermaid)")
    lines.append("```mermaid")
    lines.append(relations_graph.get("mermaid") or "graph LR")
    lines.append("```")
    lines.append("")
    lines.append("## 11. Limitações")
    lines.append("- A amostra de contratos é **estratificada por ano** (não é o universo); as contagens por entidade vêm de agregações.")
    lines.append("- As anomalias são **padrões estatísticos face ao histórico próprio** da entidade — não são irregularidades.")
    lines.append("- A causalidade é influência temporal candidata; a transição latente é linear e validada numa amostra de 30 %.")
    lines.append("- O LLM, quando existe, só escreve linguagem: os números e as decisões vêm do código.")
    return "\n".join(lines)


def catalog() -> Dict[str, Any]:
    """Catálogo de agentes e fluxo de dados entre eles (para a UI)."""
    return {
        "agents": AGENTS,
        "flow": [{"source": a, "target": b, "label": label} for a, b, label in _AGENT_FLOW],
        "mermaid": _catalog_mermaid(),
    }


def _catalog_mermaid() -> str:
    lines = ["flowchart LR"]
    ids = model.MermaidIds()
    for agent in AGENTS:
        lines.append(f'    {ids(agent["id"])}["{model.mermaid_label(agent["label"])}"]')
    for source, target, label in _AGENT_FLOW:
        lines.append(f"    {ids(source)} -->|{model.mermaid_edge_label(label)}| {ids(target)}")
    return "\n".join(lines)


def list_runs(limit: int = 20, es: Optional[Elasticsearch] = None) -> List[Dict[str, Any]]:
    """Últimas execuções do agente (resumo)."""
    client = _client(es)
    if client is None:
        return []
    body = {
        "size": max(1, min(100, int(limit))),
        "track_total_hits": False,
        "sort": [{"created_at": {"order": "desc"}}],
        "query": {"bool": {"filter": [{"term": {"engine": "world_agent"}}]}},
        "_source": [
            "run_id",
            "question",
            "created_at",
            "status",
            "subject_ref",
            "subject_name",
            "elapsed_s",
            "counters",
            "chosen_by_network",
            "anomaly",
        ],
    }
    try:
        resp = client.search(index=INVESTIGATIONS_INDEX, body=body)
    except Exception:
        return []
    return [hit.get("_source") or {} for hit in (resp.get("hits") or {}).get("hits") or []]


def get_run(run_id: str, es: Optional[Elasticsearch] = None) -> Optional[Dict[str, Any]]:
    """Execução completa do agente."""
    client = _client(es)
    if client is None:
        return None
    try:
        resp = client.get(index=INVESTIGATIONS_INDEX, id=run_id, ignore=[404])
    except Exception:
        return None
    return resp.get("_source") if resp.get("found") else None


def network_targets(limit: int = 10, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Entidades que a **rede** sugere investigar (anomalias, por ordem de score)."""
    state = neural.latest_state(es=es) or {}
    anomalies = (state.get("anomalies") or [])[: max(1, int(limit))]
    return {
        "version": state.get("version"),
        "targets": [
            {
                "entity_ref": item.get("entity_ref"),
                "entity_name": item.get("entity_name"),
                "entity_type": item.get("entity_type"),
                "score": item.get("score"),
                "label": item.get("label"),
                "signals": item.get("signal_ids"),
                "interpretation": item.get("interpretation"),
            }
            for item in anomalies
        ],
        "note": "Alvos escolhidos pela rede (anomalias face ao histórico próprio), não por regra fixa.",
    }
