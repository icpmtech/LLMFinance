"""Sonda: ficha de região (PT por distrito, ES por NUTS)."""
import time

from api.elasticsearch_client import get_contract_region_detail

for pais, code, ano in (("PT", "Bragança", None), ("PT", "Bragança", 2023), ("ES", "ES300", 2023)):
    t = time.time()
    res = get_contract_region_detail(pais=pais, code=code, ano=ano)
    print("=" * 70)
    print(pais, code, ano, "->", round(time.time() - t, 1), "s | erro:", res.get("error"))
    totals = res.get("totals") or {}
    print("  totais:", totals)
    print("  by_year:", [(r["key"], r["count"]) for r in (res.get("by_year") or [])][:4])
    print("  awarders:", [(r["name"][:34].encode("ascii", "replace").decode(), r["count"]) for r in (res.get("awarders") or [])][:3])
    print("  suppliers:", [(r["name"][:34].encode("ascii", "replace").decode(), r["count"]) for r in (res.get("suppliers") or [])][:3])
    print("  cpv:", [(r["key"], (r.get("description") or "")[:28].encode("ascii", "replace").decode()) for r in (res.get("by_cpv") or [])][:3])
    print("  proc:", [(r["key"][:28].encode("ascii", "replace").decode(), r["count"]) for r in (res.get("by_procedure") or [])][:3])
    print("  escaloes:", [(r.get("description"), r["count"]) for r in (res.get("by_value_range") or [])][:3])
    print("  contratos:", len(res.get("contracts") or []), (res.get("contracts") or [{}])[0].get("title", "")[:50].encode("ascii", "replace").decode())
