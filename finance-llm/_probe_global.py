"""Sonda: validar sincronizar / dashboard / pesquisa do universo."""
from __future__ import annotations

import sys

sys.path.insert(0, r"c:\LLMFinance\finance-llm")

from api import padroes_global as g  # noqa: E402

print("sincronizar PT 2023-2025:", g.sincronizar("PT", anos=[2023, 2024, 2025]))
dash = g.dashboard("PT", granularidade="mes")
tot = dash.get("totais") or {}
print("dashboard PT vazio:", dash.get("vazio"))
print("  anos:", tot.get("anos"), "| contratos:", tot.get("contratos"), "| valor:", round((tot.get("valor") or 0) / 1e9, 2), "mM EUR")
print("  ajuste direto:", tot.get("ajuste_direto"))
print("  aditivos:", tot.get("aditivos"), "| valor_aditivos:", tot.get("valor_aditivos"), "| taxa:", tot.get("taxa_aditivo"))
print("  sem concorrentes:", tot.get("sem_concorrentes"), "| taxa:", tot.get("taxa_sem_concorrentes"))
print("  serie:", len(dash.get("serie") or []), "| top_cpv:", len(dash.get("top_cpv") or []), "| top_adj:", len(dash.get("top_adjudicatarias") or []))

r = g.pesquisa("PT", q="obras de reabilitacao", ano_from=2024, ano_to=2025, size=3)
k = r.get("kpis") or {}
print("pesquisa:", r.get("total"), "| kpis:", k.get("valor"), k.get("valor_mediano"), k.get("aditivos"), k.get("sem_concorrentes"))
print("  serie:", len(r.get("serie") or []), "| facetas cpv:", len((r.get("facetas") or {}).get("cpvs") or []))
for item in (r.get("items") or [])[:2]:
    print("   -", item.get("ano"), (item.get("objeto") or "")[:60], item.get("valor"), item.get("adjudicataria"))

r2 = g.pesquisa("PT", granularidade="dia", data_from="2025-06-01", data_to="2025-06-30", size=1)
print("pesquisa por dia:", r2.get("total"), "| pontos serie:", len(r2.get("serie") or []))

print("sincronizar ES:", g.sincronizar("ES", anos=[2024, 2025]))
des = g.dashboard("ES")
print("dashboard ES:", (des.get("totais") or {}).get("contratos"), (des.get("totais") or {}).get("valor"))
