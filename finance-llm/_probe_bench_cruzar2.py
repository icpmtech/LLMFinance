"""Sonda: cruzamento com empresas do mesmo setor em países diferentes."""
from __future__ import annotations

import os

os.environ.setdefault("ELASTICSEARCH_URL", "http://127.0.0.1:9200")

from api import benchmark_service as bench  # noqa: E402

EMPRESAS = [
    {"country": "pt", "nif": "500189412", "name": "JANSSEN CILAG FARMACEUTICA"},
    {"country": "pt", "nif": "504293753", "name": "B. Braun Medical"},
    {"country": "es", "nif": "A08023145", "name": "ROCHE FARMA S.A."},
]

resultado = bench.benchmark_cross(entities=EMPRESAS, role="adjudicatario", cpv_code="33600000", top=20)
if resultado.get("error"):
    print("ERRO:", resultado["error"])
    raise SystemExit(1)
for empresa in resultado["companies"]:
    print(
        f"[{empresa['short']}] {empresa['name'][:32]!r} contr={empresa['contracts']} valor={empresa['total_value']:.0f} "
        f"med={empresa['median']} idx={empresa['price_index']} pos={empresa['rank']} quota={empresa['share_pct']}"
    )
print("CPV em comum:", len(resultado["shared_cpvs"]))
for item in resultado["shared_cpvs"][:5]:
    print(
        f"  {item['code']} ({item['companies_count']}) {str(item.get('description'))[:34]!r} "
        + " | ".join(f"{c['short']}:{c['count']}" for c in item["companies"])
    )
print("Contrapartes em comum:", len(resultado["shared_counterparties"]))
for item in resultado["shared_counterparties"][:8]:
    print(f"  {item.get('nif')} {str(item.get('name'))[:44]!r} ({item['companies_count']})")
