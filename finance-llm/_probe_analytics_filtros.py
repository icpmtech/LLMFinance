"""Sonda temporária: filtros por tipo e regional com filtros completos."""
import httpx

BASE = "http://127.0.0.1:8002"
TIMEOUT = 180

# `trust_env=False`: sem proxies do ambiente (um proxy do sistema devolvia uma
# resposta de erro em vez dos agregados).
client = httpx.Client(trust_env=False, timeout=TIMEOUT)


def get(path, **params):
    response = client.get(BASE + path, params=params)
    response.raise_for_status()
    return response.json()


base = get("/contracts/analytics", top_entities=1, top_cpv=1)
print("total base:", base["total_contracts"])

procedures = [r for r in base["procedure_types"] if r["key"] != "N/A"]
contracts = [r for r in base["contract_types"] if r["key"] != "N/A"]
print("procedure_types:", [(r["key"], r["count"]) for r in procedures[:3]])
print("contract_types:", [(r["key"], r["count"]) for r in contracts[:3]])

if procedures:
    value = procedures[0]["key"]
    filtered = get("/contracts/analytics", procedure_type=value, top_entities=1, top_cpv=1)
    print(f"analytics procedure_type={value!r} ->", filtered["total_contracts"])
    regional = get("/contracts/analytics/regional", procedure_type=value, size=5)
    print("  regional region_count:", regional.get("region_count"),
          "| top:", [(r["key"], r["count"]) for r in regional["regions"][:2]])

if contracts:
    value = contracts[0]["key"]
    filtered = get("/contracts/analytics", contract_type=value, top_entities=1, top_cpv=1)
    print(f"analytics contract_type={value!r} ->", filtered["total_contracts"])

regional_base = get("/contracts/analytics/regional", size=5)
print("regional base region_count:", regional_base.get("region_count"),
      "| top:", [(r["key"], r["count"]) for r in regional_base["regions"][:3]])

regional_cpv = get("/contracts/analytics/regional", cpv_code="33600000-6", size=5)
print("regional cpv_code region_count:", regional_cpv.get("region_count"),
      "| top:", [(r["key"], r["count"]) for r in regional_cpv["regions"][:3]])

regional_year = get("/contracts/analytics/regional", year=2026, size=5)
print("regional year=2026 region_count:", regional_year.get("region_count"),
      "| top:", [(r["key"], r["count"]) for r in regional_year["regions"][:2]])
