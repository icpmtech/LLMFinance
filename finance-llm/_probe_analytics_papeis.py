"""Sonda: papel (adjudicante/adjudicatário), rankings separados e indicadores distintos."""
import httpx

BASE = "http://127.0.0.1:8002"
client = httpx.Client(trust_env=False, timeout=180)


def get(path, **params):
    response = client.get(BASE + path, params=params)
    response.raise_for_status()
    return response.json()


base = get("/contracts/analytics", top_entities=10, top_cpv=10)
print("contratos:", base["total_contracts"])
print("distintos -> adjudicantes:", base["distinct_adjudicantes"],
      "| adjudicatarios:", base["distinct_adjudicatarios"],
      "| cpv:", base["distinct_cpv"])
print("top_entities:", len(base["top_entities"]),
      "| top_adjudicantes:", len(base["top_adjudicantes"]),
      "| top_adjudicatarios:", len(base["top_adjudicatarios"]))
print("top_adjudicantes[0]:", base["top_adjudicantes"][0])
print("top_adjudicatarios[0]:", base["top_adjudicatarios"][0])
print("by_year[0]:", base["by_year"][0])

top_n = get("/contracts/analytics", top_entities=100, top_cpv=100)
print("top N=100 ->", len(top_n["top_adjudicantes"]), len(top_n["top_adjudicatarios"]), len(top_n["top_cpv"]))

for role in ("adjudicante", "adjudicatario"):
    r = get("/contracts/analytics", role=role, top_entities=5, top_cpv=5)
    print(f"role={role}: contratos={r['total_contracts']} distintos(adj/atario)="
          f"{r['distinct_adjudicantes']}/{r['distinct_adjudicatarios']} "
          f"top_cpv[0]={r['top_cpv'][0]['key'] if r['top_cpv'] else None}")

reg = get("/contracts/analytics/regional", role="adjudicatario", size=5)
print("regional role=adjudicatario -> region_count:", reg.get("region_count"),
      "| top:", [(x["key"], x["count"]) for x in reg["regions"][:2]])

# Top entidades POR CPV (o filtro de CPV reescreve o ranking de entidades).
cpv = base["top_cpv"][0]["key"]
por_cpv = get("/contracts/analytics", cpv_code=cpv, top_entities=5, top_cpv=5)
print(f"top entidades no CPV {cpv}:")
for row in por_cpv["top_entities"][:5]:
    print("   ", row["key"], row["description"], row["count"], row["total_value"])

# Top CPVs de uma entidade (filtro por NIF reescreve o ranking de CPV).
nif = por_cpv["top_entities"][0]["key"]
por_nif = get("/contracts/analytics", nif=nif, top_entities=5, top_cpv=10)
print(f"top CPVs da entidade {nif} ({por_nif['total_contracts']} contratos):")
for row in por_nif["top_cpv"][:5]:
    print("   ", row["key"], row["count"], row["description"])
