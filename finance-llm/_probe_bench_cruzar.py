"""Sonda: cruzamento de empresas de países diferentes (`benchmark_cross`)."""
from __future__ import annotations

import json
import os

os.environ.setdefault("ELASTICSEARCH_URL", "http://127.0.0.1:9200")

from api import benchmark_service as bench  # noqa: E402

EMPRESAS = [
    {"country": "pt", "nif": "500189412", "name": "JANSSEN CILAG FARMACEUTICA"},
    {"country": "es", "nif": "A28599033", "name": "INDRA SISTEMAS SA"},
    {"country": "fr", "nif": "54210765114459"},
]

resultado = bench.benchmark_cross(entities=EMPRESAS, role="adjudicatario", cpv_code=None, top=20)
if resultado.get("error"):
    print("ERRO:", resultado["error"])
    raise SystemExit(1)

for empresa in resultado["companies"]:
    print(
        f"[{empresa['short']}] {empresa['name'][:36]!r} contr={empresa['contracts']} "
        f"valor={empresa['total_value']:.0f} mediana={empresa['median']} indice={empresa['price_index']} "
        f"pos={empresa['rank']} quota={empresa['share_pct']} cpvs={len(empresa['cpvs'])} "
        f"contrapartes={len(empresa['counterparties'])} {empresa.get('error', '')}"
    )
print("--- CPV em comum:", len(resultado["shared_cpvs"]))
for item in resultado["shared_cpvs"][:6]:
    empr = " | ".join(f"{c['short']}:{c['count']}" for c in item["companies"])
    print(f"  {item.get('code')} ({item['companies_count']}) {str(item.get('description'))[:38]!r} -> {empr}")
print("--- contrapartes em comum:", len(resultado["shared_counterparties"]))
for item in resultado["shared_counterparties"][:6]:
    empr = " | ".join(f"{c['short']}:{c['count']}" for c in item["companies"])
    print(f"  {item.get('nif')} {str(item.get('name'))[:40]!r} ({item['companies_count']}) -> {empr}")
print("--- notas")
for nota in resultado["notes"]:
    print("  *", nota)
print(json.dumps(resultado, ensure_ascii=False)[:160])
