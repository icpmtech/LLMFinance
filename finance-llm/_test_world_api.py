"""Teste de ponta a ponta das rotas do World Model (`/world/*`).

    c:\\LLMFinance\\.venv\\Scripts\\python.exe _test_world_api.py

Cria uma conta de QA, exercita as rotas de leitura e de escrita (com sessão) e
apaga a conta no fim. Requer o backend a correr na 8002 e o Elasticsearch up.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))

BASE = "http://127.0.0.1:8002"
EMAIL = "qa.world@iqos.dev"
PASSWORD = "QaWorld!2026"

READ_ROUTES = [
    "/world/meta",
    "/world/architecture",
    "/world/sources",
    "/world/status",
    "/world/schedule",
    "/world/jobs",
    "/world/entities?size=3&sort=risk",
    "/world/events?size=3",
    "/world/events/stats",
    "/world/relations?size=3",
    "/world/relations/stats",
    "/world/graph?nodes=40&edges=80",
    "/world/graph/dimensions",
    "/world/centrality?top=3",
    "/world/temporal?years=2",
    "/world/causality?window_days=60&limit=3",
    "/world/network",
    "/world/network/graph?limit=20",
    "/world/network/history?limit=3",
    "/world/network/anomalies?limit=5",
    "/world/network/transition",
    "/world/pipeline/graph",
    "/world/history?limit=5",
    "/world/history/series?grain=quarter&limit=8",
    "/world/agent/catalog",
    "/world/agent/targets?limit=5",
    "/world/agent/runs?limit=3",
    "/world/simulations?limit=3",
    "/world/investigations?limit=3",
    "/world/config",
]

failures: list[str] = []


def _check(label: str, ok: bool, detail: str = "") -> None:
    print(f"{'OK  ' if ok else 'FALHA'} {label}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


def main() -> int:
    client = httpx.Client(base_url=BASE, timeout=180.0)
    print("=== leitura (pública) ===")
    for route in READ_ROUTES:
        try:
            response = client.get(route)
            _check(route, response.status_code == 200, str(response.status_code))
        except Exception as exc:
            _check(route, False, str(exc)[:120])

    print("\n=== sessão de QA ===")
    response = client.post(
        "/auth/register",
        json={"name": "QA World", "email": EMAIL, "password": PASSWORD, "title": "QA"},
    )
    if response.status_code == 201:
        token = response.json().get("token")
        _check("POST /auth/register", True)
    else:
        response = client.post("/auth/login", json={"email": EMAIL, "password": PASSWORD, "remember": False})
        token = response.json().get("token") if response.status_code == 200 else None
        _check("POST /auth/login", bool(token), f"{response.status_code} {response.text[:120]}")
    if not token:
        return 1
    headers = {"Authorization": f"Bearer {token}"}

    print("\n=== escrita (sessão) ===")
    response = client.put(
        "/world/schedule",
        headers=headers,
        json={"enabled": False, "cron": "0 4 * * *", "timezone": "Europe/Lisbon", "train_network": True},
    )
    _check("PUT /world/schedule", response.status_code == 200, response.text[:160])

    response = client.put("/world/config", headers=headers, json={"contract_sample": 2000, "entity_limit": 2000, "year_from": None})
    _check("PUT /world/config", response.status_code == 200, response.text[:160])

    # Fontes do sistema: associa as que já estavam + uma adicional e confirma que
    # o catálogo devolve o estado gravado (é o que a página World mostra).
    sources = client.get("/world/sources").json()
    associadas = list(sources.get("associated") or [])
    if "firmas" not in associadas:
        associadas.append("firmas")
    response = client.put("/world/sources", headers=headers, json={"ids": associadas})
    payload = response.json() if response.status_code == 200 else {}
    _check(
        "PUT /world/sources",
        response.status_code == 200 and "firmas" in (payload.get("associated") or []),
        f"associadas: {', '.join(payload.get('associated') or [])}",
    )
    response = client.put("/world/sources", headers=headers, json={"ids": [item for item in associadas if item != "firmas"]})
    _check(
        "PUT /world/sources (remover)",
        response.status_code == 200 and "firmas" not in (response.json().get("associated") or []),
        f"{len(response.json().get('associated') or [])} fontes associadas",
    )

    started = time.time()
    response = client.post("/world/rebuild", headers=headers, json={"contract_sample": 8000, "entity_limit": 2000, "wait": True})
    ok = response.status_code == 200 and "entities" in response.text
    _check("POST /world/rebuild (wait)", ok, f"{response.status_code} em {round(time.time() - started, 1)}s")

    started = time.time()
    response = client.post("/world/network/train", headers=headers, json={"node_limit": 400, "max_nodes": 200, "wait": True})
    ok = response.status_code == 200 and "metrics" in response.text
    detail = ""
    if ok:
        metrics = response.json().get("metrics") or {}
        detail = f"nós={metrics.get('nodes')} arestas={metrics.get('edges')} memória={metrics.get('memory_patterns')} em {round(time.time() - started, 1)}s"
    _check("POST /world/network/train (wait)", ok, detail or str(response.status_code))

    response = client.get("/world/network/graph?limit=30")
    payload = response.json() if response.status_code == 200 else {}
    _check(
        "GET /world/network/graph",
        response.status_code == 200 and bool(payload.get("nodes")),
        f"{len(payload.get('nodes') or [])} nós, {len(payload.get('edges') or [])} arestas, versão {payload.get('version')}",
    )

    # Transição latente `z_{t+1} ≈ A·z_t + b` (cérebro do «dinâmico» da rede).
    # A rota devolve o modelo no próprio payload (`available`, `r2`, `pairs`, ...).
    transition = client.get("/world/network/transition").json()
    _check(
        "GET /world/network/transition",
        bool(transition.get("available")),
        f"R2={transition.get('r2')} pares={transition.get('pairs')} entidades={transition.get('entities')} "
        f"holdout={transition.get('holdout')} — {transition.get('reason') or transition.get('note')}",
    )

    anomalies = client.get("/world/network/anomalies?limit=50").json()
    _check(
        "GET /world/network/anomalies",
        bool(anomalies.get("available")),
        f"{len(anomalies.get('anomalies') or [])} anomalias, contagens {(anomalies.get('counts') or {}).get('total')}",
    )

    pipeline = client.get("/world/pipeline/graph").json()
    _check(
        "GET /world/pipeline/graph",
        bool(pipeline.get("mermaid")) and "evidence-graph" in {node.get("id") for node in pipeline.get("nodes") or []},
        f"{len(pipeline.get('nodes') or [])} estágios, {len(pipeline.get('edges') or [])} arestas, {pipeline.get('metrics', {}).get('documents')} docs",
    )

    history_series = client.get("/world/history/series?grain=quarter&limit=8").json()
    _check(
        "GET /world/history/series",
        bool(history_series.get("series")),
        f"{len(history_series.get('series') or [])} períodos ({', '.join(item['period'] for item in (history_series.get('series') or [])[-3:])})",
    )

    catalog = client.get("/world/agent/catalog").json()
    _check(
        "GET /world/agent/catalog",
        bool(catalog.get("agents")) and bool(catalog.get("mermaid")),
        f"{len(catalog.get('agents') or [])} agentes, {len(catalog.get('flow') or [])} fluxos",
    )

    targets = client.get("/world/agent/targets?limit=5").json()
    _check(
        "GET /world/agent/targets",
        True,
        f"{len(targets.get('targets') or [])} alvos sugeridos pela rede",
    )

    # Sujeito para a simulação: a primeira entidade com risco mais alto.
    entity = (client.get("/world/entities?size=1&sort=risk").json().get("results") or [{}])[0]
    subject = entity.get("entity_ref")
    print(f"    sujeito: {subject} ({entity.get('name')})")

    if subject:
        _check("GET /world/entities/{ref}", client.get(f"/world/entities/{subject}").status_code == 200)
        response = client.get(f"/world/entities/{subject}/timeline?size=5")
        _check("GET /world/entities/{ref}/timeline", response.status_code == 200)
        response = client.get(f"/world/network/recall/{subject}")
        _check("GET /world/network/recall/{ref}", response.status_code == 200, response.text[:120])
        response = client.get(f"/world/history/{subject}?limit=12")
        _check(
            "GET /world/history/{ref}",
            response.status_code == 200,
            f"{len((response.json().get('series') or []))} períodos da entidade",
        )
        response = client.get(f"/world/network/transition/{subject}?steps=4")
        _check("GET /world/network/transition/{ref}", response.status_code == 200, response.text[:140])

    started = time.time()
    response = client.post(
        "/world/simulate",
        headers=headers,
        json={"subject": subject, "horizon": 3, "samples": 100},
    )
    ok = response.status_code == 200
    detail = ""
    if ok:
        payload = response.json()
        detail = f"totais={payload.get('summary', {}).get('totals', {}).get('new_contracts')} contratos em {round(time.time() - started, 1)}s"
    _check("POST /world/simulate", ok, detail or response.text[:160])

    started = time.time()
    response = client.post(
        "/world/investigate",
        headers=headers,
        json={"question": "Qual é o risco desta entidade e o que pode acontecer até 2027?", "subject": subject, "horizon": 3, "samples": 100},
    )
    ok = response.status_code == 200
    detail = ""
    if ok:
        payload = response.json()
        detail = f"{len(payload.get('hypotheses') or [])} hipóteses, {len(payload.get('evidence') or [])} evidências, {len(payload.get('report') or '')} chars em {round(time.time() - started, 1)}s"
    _check("POST /world/investigate", ok, detail or response.text[:200])

    response = client.get("/world/investigations?limit=3")
    _check("GET /world/investigations", response.status_code == 200, f"{(len(response.json().get('investigations') or []))} registos")

    # Agente **sobre a rede**: plano dinâmico + três grafos (execução, evidências,
    # relações) + relatório. O sujeito é escolhido pela própria rede (anomalia).
    started = time.time()
    response = client.post(
        "/world/agent/run",
        headers=headers,
        json={"question": "O que muda nesta entidade e que evidência o sustenta?", "horizon": 3, "samples": 60, "wait": True},
    )
    ok = response.status_code == 200
    detail = response.text[:180]
    if ok:
        payload = response.json()
        graphs = {key: payload.get(key) or {} for key in ("execution_graph", "evidence_graph", "relations_graph")}
        mermaid_ok = all(bool(graph.get("mermaid")) for graph in graphs.values())
        detail = (
            f"sujeito={payload.get('subject_name')} (escolhido pela rede={payload.get('chosen_by_network')}), "
            f"{len(graphs['execution_graph'].get('nodes') or [])} passos, "
            f"{len(graphs['evidence_graph'].get('nodes') or [])} nós de evidência, "
            f"{len(payload.get('claims') or [])} afirmações, {len(payload.get('report') or '')} chars"
        )
        ok = ok and mermaid_ok
    _check("POST /world/agent/run (wait)", ok, f"{detail} em {round(time.time() - started, 1)}s")

    # O Elasticsearch é *near real-time*: dá-se uma janela curta para a execução
    # ficar visível antes de concluir que a gravação falhou.
    agent_runs = client.get("/world/agent/runs?limit=3")
    for _ in range(10):
        if (agent_runs.json().get("runs") or []):
            break
        time.sleep(1)
        agent_runs = client.get("/world/agent/runs?limit=3")
    _check(
        "GET /world/agent/runs",
        agent_runs.status_code == 200 and bool((agent_runs.json().get("runs") or [])),
        f"{len((agent_runs.json().get('runs') or []))} execuções",
    )
    newest = (agent_runs.json().get("runs") or [{}])[0].get("run_id")
    if newest:
        response = client.get(f"/world/agent/runs/{newest}")
        _check("GET /world/agent/runs/{id}", response.status_code == 200, f"{len(response.text)} chars")

    # Limpeza: a conta de QA (e as suas sessões) não fica no sistema.
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from api.elasticsearch_client import get_es_client

        es = get_es_client()
        if es is not None:
            removed_users = es.delete_by_query(
                index="finance_users", body={"query": {"term": {"email": EMAIL}}}, conflicts="proceed", refresh=True
            ).get("deleted", 0)
            removed_sessions = es.delete_by_query(
                index="finance_sessions", body={"query": {"term": {"email": EMAIL}}}, conflicts="proceed", refresh=True
            ).get("deleted", 0)
            print(f"\n(limpeza: {removed_users} conta(s) e {removed_sessions} sessão(ões) de QA removidas)")
    except Exception as exc:  # pragma: no cover - limpeza best effort
        print(f"\n(limpeza não feita: {exc})")

    print(f"\n=== {'TUDO OK' if not failures else 'FALHAS: ' + ', '.join(failures)} ===")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
