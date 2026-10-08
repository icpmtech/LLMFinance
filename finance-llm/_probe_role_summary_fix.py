"""Verifica o fix: custo real por papel + cache a servir instantaneamente."""
import sys
import time

sys.path.insert(0, "c:/LLMFinance/finance-llm")

from api.elasticsearch_client import (  # noqa: E402
    _compute_entity_role_summary,
    get_entity_role_summary,
)

for role in ("adjudicante", "adjudicatario"):
    t0 = time.perf_counter()
    res = _compute_entity_role_summary(role=role, top_n=25, min_contracts=1)
    dt = time.perf_counter() - t0
    print(f"cálculo {role:14s} {dt:7.1f}s erro={res.get('error')} "
          f"entidades={len(res.get('top_entities') or [])} contratos={res.get('total_contracts')}")

print()
for role in ("adjudicante", "adjudicatario", "all"):
    t0 = time.perf_counter()
    res = get_entity_role_summary(role=role, top_n=25, min_contracts=1)
    dt = time.perf_counter() - t0
    print(f"com cache {role:14s} {dt:7.3f}s erro={res.get('error')} entidades={len(res.get('top_entities') or [])}")

t0 = time.perf_counter()
res = get_entity_role_summary(role="adjudicante", top_n=25, min_contracts=1)
print(f"\nsegunda chamada (cache quente): {time.perf_counter() - t0:.3f}s  "
      f"top1={(res.get('top_entities') or [{}])[0].get('name')}")
