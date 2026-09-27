"""Sonda de validação do World Model (execução manual, sem servidor).

    c:\\LLMFinance\\.venv\\Scripts\\python.exe _probe_world.py [--full]

Sem `--full` só valida as leituras (fontes, agregações e amostras). Com `--full`
reconstrói o mundo, treina a rede (em memória) e corre uma simulação — o que
apaga o estado das versões anteriores.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api import world_graph, world_investigation, world_model, world_neural, world_simulator, world_sources  # noqa: E402


def _show(title: str, payload) -> None:
    text = json.dumps(payload, ensure_ascii=False, default=str)
    print(f"\n=== {title} ===")
    print(text[:1400] + ("…" if len(text) > 1400 else ""))


def main() -> int:
    full = "--full" in sys.argv
    agent_only = "--agent" in sys.argv

    if agent_only:
        top = world_model.search_entities(size=3, sort="risk")
        ref = (top.get("results") or [{}])[0].get("entity_ref")
        _show("entidades com mais risco", top)
        simulation = world_simulator.run(subject=ref, params={"horizon": 3, "samples": 100}, persist=False)
        _show("simulação", {"summary": simulation.get("summary"), "steps": simulation.get("steps")})
        investigation = world_investigation.investigate(
            f"Qual é o risco de {ref} e o que pode acontecer até 2027?",
            subject=ref,
            params={"horizon": 3, "samples": 100},
            simulate=True,
            persist=True,
        )
        _show("investigação (resumo)", {k: v for k, v in investigation.items() if k not in {"report", "steps", "evidence", "hypotheses"}})
        print("\n--- relatório ---\n")
        print(investigation["report"][:4000])
        return 0

    start = time.time()
    _show("fontes", world_sources.availability())
    print(f"({time.time() - start:.1f} s)")

    for role in ("adjudicante", "adjudicatario"):
        start = time.time()
        rows = world_sources.pt_party_metrics(role, limit=5)
        _show(f"PT {role}", rows[:3])
        print(f"({time.time() - start:.1f} s, {len(rows)} linhas)")

    for role in ("adjudicante", "adjudicatario"):
        rows = world_sources.es_party_metrics(role, limit=5)
        _show(f"ES {role}", rows[:3])

    sample = world_sources.contract_sample(size=3)
    _show("amostra de contratos", [{k: v for k, v in item.items() if k != "cpv"} for item in sample[:2]])

    nif = (sample[0]["adjudicatarios"][0]["nif"] if sample and sample[0].get("adjudicatarios") else "501234567")
    _show(f"contratos de {nif}", world_sources.entity_contracts(nif, size=2)[:1])
    _show(f"insolvências de {nif}", world_sources.entity_insolvencies(nif, size=2)[:1])
    _show("insolvências (CIRE)", world_sources.insolvency_records(size=2)[:2])
    _show("cargos (pessoas)", world_sources.people_relations(size=2)[:2])

    if not full:
        print("\n(leitura validada; usar --full para reconstruir o mundo)")
        return 0

    start = time.time()
    summary = world_model.rebuild(
        params={"entity_limit": 300, "contract_sample": 400, "insolvency_sample": 200, "people_sample": 300}
    )
    _show("reconstrução", summary)
    print(f"({time.time() - start:.1f} s)")

    _show("status", {k: v for k, v in world_model.status().items() if k != "available_sources"})
    top = world_model.search_entities(size=3, sort="risk")
    _show("entidades com mais risco", top)
    ref = (top.get("results") or [{}])[0].get("entity_ref")
    if ref:
        _show(f"ficha {ref}", world_model.get_entity(ref))
        _show("timeline", world_model.timeline(entity_ref=ref, size=5))
        _show("relações", world_model.relations(entity_ref=ref, size=5))
        _show("grafo", world_graph.build_graph(entity_ref=ref, depth=1, node_limit=30, edge_limit=60))
    _show("centralidade", world_graph.centrality(top=5))
    _show("série temporal", world_graph.temporal_profile(years=3))
    _show("causalidade", world_graph.causality(window_days=45, limit=5))

    network = world_neural.train(params={"node_limit": 300, "max_nodes": 200, "edge_limit": 800}, persist=True)
    _show("rede (métricas)", {"version": network.get("version"), "metrics": network.get("metrics"), "pruned": network.get("pruned"), "growth": network.get("growth")})
    _show("rede como grafo", {k: v for k, v in world_neural.network_graph(limit=30).items() if k not in {"nodes", "edges"}})

    simulation = world_simulator.run(params={"horizon": 3, "samples": 100}, persist=False)
    _show("simulação (mundo)", {"summary": simulation.get("summary"), "steps": simulation.get("steps")})
    if ref:
        entity_sim = world_simulator.run(subject=ref, params={"horizon": 3, "samples": 100}, persist=False)
        _show(f"simulação {ref}", entity_sim.get("summary"))

    investigation = world_investigation.investigate(
        f"Qual é o risco de {ref or 'contratação pública'} e o que pode acontecer até 2027?",
        subject=ref,
        params={"horizon": 3, "samples": 100},
        simulate=True,
        persist=True,
    )
    _show("investigação (resumo)", {k: v for k, v in investigation.items() if k not in {"report", "steps", "evidence", "hypotheses"}})
    print("\n--- relatório ---\n")
    print(investigation["report"][:3000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
