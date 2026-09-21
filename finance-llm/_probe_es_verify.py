"""Sonda: verificação da importação de contratos de Espanha (contagens e facetas)."""
import json
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from api import elasticsearch_client as esc  # noqa: E402

print("status:", json.dumps(esc.contratos_es_status(), ensure_ascii=False))

for fonte in ("licitaciones", "menores"):
    r = esc.search_contratos_es(fonte=fonte, with_facets=False, size=0)
    print(f"  {fonte}: total={r.get('total')}")

r = esc.search_contratos_es(ano=2023, with_facets=True, size=0)
print("ano 2023:", r["total"])
facetas = r["facets"]
print("fonte:", facetas["fonte"])
print("tipo:", [(b["value"], b["count"]) for b in facetas["tipo"][:6]])
print("estado:", [(b["value"], b["count"]) for b in facetas["estado"][:8]])
print("procedimiento:", [(b["value"], b["count"]) for b in facetas["procedimiento"][:6]])
print("resultado:", [(b["value"], b["count"]) for b in facetas["resultado"][:6]])
print("cpv:", [(b["value"], b["count"], b.get("label", "")[:35]) for b in facetas["cpv"][:4]])
print("orgaos:", [(b["value"][:45], b["count"]) for b in facetas["organo"][:3]])
print("adjudicatarios:", [(b["value"][:35], b["count"]) for b in facetas["adjudicatario"][:3]])
stats = r.get("stats") or {}
print("stats:", {k: (round(v) if isinstance(v, float) else v) for k, v in stats.items()})

# consultas de controlo
print("texto 'limpieza':", esc.search_contratos_es(q="limpieza", with_facets=False, size=0).get("total"))
print("texto 'obras de rehabilitacion':", esc.search_contratos_es(q="rehabilitacion", with_facets=False, size=0).get("total"))
print("sem acento 'electricidad':", esc.search_contratos_es(q="electricidad", with_facets=False, size=0).get("total"))
print("valor > 5M:", esc.search_contratos_es(min_value=5_000_000, with_facets=False, size=0).get("total"))
r = esc.search_contratos_es(min_value=5_000_000, with_facets=False, size=3, sort_by="valor_adjudicado")
print("  exemplos:", [(i["id_expediente"], i.get("valor_adjudicado"), i["organo_nombre"][:35]) for i in r["items"]])
