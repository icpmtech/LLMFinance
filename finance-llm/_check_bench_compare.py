"""Verificação da comparação com CPV e compradores por empresa."""
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
    {"nif": "501488421", "name": "B. Braun"},
]

for rotulo, kwargs in (("com CPV 33000000", {"cpv_code": "33000000"}), ("sem CPV", {})):
    inicio = time.perf_counter()
    res = bench.benchmark_compare(entities=EMP, role="adjudicatario", top=10, es=client, **kwargs)
    print(f"===== {rotulo} ({time.perf_counter() - inicio:.1f}s) erro={res.get('error')} counterpart={res.get('counterpart_role')} =====")
    if res.get("error"):
        continue
    for linha in res["entities"]:
        cpvs = ", ".join(f"{c['code']}({c['count']})" for c in linha["top_cpv"][:3])
        compradores = ", ".join(f"{b['name'][:22]}({b['count']})" for b in linha["buyers"][:3])
        print(f"  {linha['order']}. {linha['name'][:26]:26} cpv=[{cpvs}]")
        print(f"      compradores=[{compradores}] total={linha['buyers_total']}")
    print("  compradores em comum:")
    for item in res["shared_buyers"][:5]:
        print(f"   - {item['name'][:34]:34} em {item['companies_total']} empresas: {[c[:20] for c in item['companies']]} valor={item['value']:.0f}")
    print("  notas:", res["notes"][-1])
print("OK")
