"""Mede quanto tempo o agregado do dashboard de entidades leva no ES."""
import sys
import time

sys.path.insert(0, "c:/LLMFinance/finance-llm")

from api.elasticsearch_client import get_es_client, get_entity_role_summary  # noqa: E402

es = get_es_client(request_timeout=600)
print("ES:", es.info()["version"]["number"] if es else None)

for role in ("adjudicante", "all"):
    t0 = time.perf_counter()
    res = get_entity_role_summary(role=role, top_n=25, min_contracts=1, es=es)
    dt = time.perf_counter() - t0
    err = res.get("error")
    print(f"role={role:12s} {dt:6.1f}s  erro={err}  entidades={res.get('total_entities')} valor={res.get('total_value')}")

stats = es.nodes.stats(metric="thread_pool")
for node_id, node in stats.get("nodes", {}).items():
    pool = node.get("thread_pool", {}).get("search", {})
    print(f"no {node.get('name')}: search queue={pool.get('queue')} rejected={pool.get('rejected')} completed={pool.get('completed')}")

tasks = es.tasks.list(actions="*search", detailed=False)
running = (tasks.get("nodes") or {})
n = sum(len(v.get("tasks", {})) for v in running.values())
print("pesquisas em curso:", n)
for node in running.values():
    for tid, task in list(node.get("tasks", {}).items())[:4]:
        print("  ", task.get("running_time_in_nanos", 0) // 1_000_000, "ms ::", str(task.get("description"))[:150])
