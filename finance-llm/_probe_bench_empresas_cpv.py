"""Sonda: empresas por CPV nos três países (`top_entities`)."""
from __future__ import annotations

import json
import os
import sys

os.environ.setdefault("ELASTICSEARCH_URL", "http://127.0.0.1:9200")

from api import benchmark_service as bench  # noqa: E402

role = sys.argv[1] if len(sys.argv) > 1 else "adjudicatario"
cpv = sys.argv[2] if len(sys.argv) > 2 else None

resultado = bench.top_entities(role=role, cpv_code=cpv, size=4, cpv_size=3)
print("notas:", resultado.get("notes"))
for pais in resultado.get("countries", []):
    print(
        "==",
        pais.get("country"),
        pais.get("label"),
        "contratos=",
        pais.get("contracts"),
        "valor=",
        pais.get("total_value"),
        pais.get("error", ""),
    )
for item in resultado.get("items", []):
    cpvs = " / ".join(f"{c['code']}({c['count']})" for c in item.get("cpvs", []))
    print(
        f"  [{item['short']}] #{item['rank']} {item['name'][:38]!r} nif={item['nif']} "
        f"contr={item['contracts']} valor={item['value']} quota={item.get('share_pct')} cpv={cpvs}"
    )
print(json.dumps(resultado, ensure_ascii=False)[:200])
