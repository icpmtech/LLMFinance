"""Valida o filtro ecológico: pesquisa, análise e regional."""
import time

import httpx

BASE = "http://127.0.0.1:8002"
client = httpx.Client(trust_env=False, timeout=300)


def get(path, **params):
    r = client.get(BASE + path, params=params)
    r.raise_for_status()
    return r.json()


total_geral = get("/contracts/analytics", top_entities=1, top_cpv=1)
eco = get("/contracts/analytics", ecological=True, top_entities=5, top_cpv=5, value_buckets=7)

tg, te = total_geral["total_contracts"], eco["total_contracts"]
print(f"universo: {tg} contratos · {total_geral['total_value']:,.0f} €")
print(f"ecológico: {te} contratos ({te / tg * 100:.2f}%) · {eco['total_value']:,.0f} € "
      f"({eco['total_value'] / total_geral['total_value'] * 100:.2f}% do valor)")
print("  valor médio:", f"{eco['avg_value']:,.0f} €", "| adjudicantes:", eco["distinct_adjudicantes"],
      "| adjudicatários:", eco["distinct_adjudicatarios"], "| CPV:", eco["distinct_cpv"])
print("  por ano:", [(b["key"], b["count"]) for b in eco["by_year"][:5]])
print("  top CPV:", [(b["key"], b["count"]) for b in eco["top_cpv"][:3]])
print("  top entidades:", [(b["key"], b["description"], round(b["total_value"] or 0)) for b in eco["top_entities"][:3]])
print("  procedimentos:", [(b["key"], b["count"]) for b in eco["procedure_types"][:3]])

reg = get("/contracts/analytics/regional", ecological=True, size=5)
print("regional eco: region_count=", reg.get("region_count"), "top:", [(b["key"], b["count"]) for b in reg["regions"][:3]])

t0 = time.perf_counter()
page = client.post(BASE + "/contracts/search", json={
    "ecological": True, "size": 3, "sort_by": "precoContratual", "sort_order": "desc",
}).json()
print(f"\npágina de resultados em {time.perf_counter() - t0:.2f}s :: total={page['total']}")
for item in page["items"]:
    print(f"   {item.get('idcontrato')} | {item.get('Ano')} | {item.get('precoContratual')} € | "
          f"eco={item.get('ContratEcologico')} | peças={'sim' if item.get('linkPecasProc') else 'não'}")
    print(f"      {str(item.get('objectoContrato'))[:100]}")
    print(f"      adjudicante: {str(item.get('adjudicantes'))[:80]}")
