"""Sonda: ficha de região com pesquisa (PT por distrito, ES por NUTS)."""
import time

from api.elasticsearch_client import get_contract_region_detail

casos = [
    ("PT", "Bragança", None, None, None),
    ("PT", "Bragança", None, "escola", None),
    ("PT", "Bragança", None, None, "336"),
    ("ES", "ES300", 2023, "lanzacohetes", None),
    ("ES", "ES300", 2023, None, "45"),
]

for pais, code, ano, q, cpv in casos:
    t = time.time()
    res = get_contract_region_detail(pais=pais, code=code, ano=ano, q=q, cpv=cpv)
    totals = res.get("totals") or {}
    print("=" * 72)
    print(
        "%s %s ano=%s q=%r cpv=%r -> %.1fs erro=%s"
        % (pais, code.encode("ascii", "replace").decode(), ano, q, cpv, time.time() - t, res.get("error"))
    )
    print("  filtros:", res.get("filters"))
    print("  totais:", totals)
    print("  awarders:", [(r["name"][:30].encode("ascii", "replace").decode(), r["count"]) for r in (res.get("awarders") or [])][:3])
    print("  suppliers:", [(r["name"][:30].encode("ascii", "replace").decode(), r["count"]) for r in (res.get("suppliers") or [])][:3])
    print("  contratos:", len(res.get("contracts") or []), (res.get("contracts") or [{}])[0].get("title", "")[:60].encode("ascii", "replace").decode())
    print("  por ano:", [(r["key"], r["count"]) for r in (res.get("by_year") or [])][:4])
