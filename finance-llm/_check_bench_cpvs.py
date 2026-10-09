"""Verifica o perfil de CPV das entidades na comparação (fora do filtro de CPV)."""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api import benchmark_service as bench
from api.elasticsearch_client import get_es_client

client = get_es_client(request_timeout=300)
EMP = [
    {"nif": "501506543", "name": "B. BRAUN MEDICAL"},
    {"nif": "500189412", "name": "JANSSEN CILAG"},
    {"nif": "500063524", "name": "NOVARTIS"},
]

for rotulo, kwargs in (("com CPV 33000000", {"cpv_code": "33000000"}), ("sem CPV", {})):
    inicio = time.perf_counter()
    res = bench.benchmark_compare(entities=EMP, role="adjudicatario", top=10, es=client, **kwargs)
    print(f"===== {rotulo} ({time.perf_counter() - inicio:.1f}s) erro={res.get('error')} =====")
    if res.get("error"):
        continue
    for linha in res["entities"]:
        print(f"  {linha['name'][:26]:26} cpv={[(c['code'], c['count']) for c in linha['top_cpv'][:4]]}")
    print("  cpv em comum:")
    for item in res["shared_cpvs"][:5]:
        print(f"   - {item['code']:12} {item['description'][:40]:40} em {item['companies_total']} empresas")
    print("  notas:", res["notes"][-1][:120])
print("OK")
