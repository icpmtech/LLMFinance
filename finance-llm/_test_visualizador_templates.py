"""Valida os templates de dashboards contra o catálogo e corre as consultas de cada visual."""
from __future__ import annotations

import sys
import time

sys.path.insert(0, ".")

from api import visualizador_service as service  # noqa: E402
from api import visualizador_templates as templates  # noqa: E402

listing = templates.resolve_templates(scope=None)
print(f"templates: {listing['total']}\n")

problems = 0
for item in listing["items"]:
    state = "OK " if item["available"] and not item["warnings"] else "AVISO"
    volume = "?" if item["records"] is None else f"{item['records']:,}".replace(",", " ")
    print(f"{state} {item['id']:<24} dataset={item['dataset']:<18} visuais={len(item['visuals']):>2} registos={volume:>12}"
          + ("  [escasso]" if item.get("sparse") else ""))
    if item.get("data_note"):
        print(f"      · {item['data_note']}")
    for warning in item["warnings"]:
        problems += 1
        print(f"      ! {warning}")
    if item["requires_session"]:
        print("      · privado: consultas não testadas sem sessão")
        continue
    for visual in item["visuals"]:
        payload = {
            "dataset": item["dataset"],
            "dimensions": visual["dimensions"],
            "measures": visual["measures"],
            "formulas": visual["formulas"],
            "filters": item["filters"],
            "sort": visual["sort"] if visual["sort"].get("by") else None,
            "top_n": visual["top_n"] or None,
            "others": visual["others"],
            "limit": visual["limit"],
        }
        started = time.time()
        result = service.run_query(payload)
        rows = len(result.get("rows") or [])
        elapsed = round((time.time() - started) * 1000)
        bad = bool(result.get("error")) or rows == 0
        if bad:
            problems += 1
        flag = "  !" if bad else "   "
        extra = ""
        if result.get("error"):
            extra = f"  erro={result['error']}"
        elif bad:
            extra = f"  notas={result.get('meta', {}).get('notes')}"
        print(f"{flag} {visual['title'][:36]:<36} {visual['chart']:<9} linhas={rows:<4} {elapsed:>5} ms{extra}")

print(f"\nproblemas: {problems}")
