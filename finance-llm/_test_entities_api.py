"""Testar pesquisa e estatísticas do cadastro de entidades."""
import sys

sys.path.insert(0, ".")

from fastapi.testclient import TestClient  # noqa: E402

from api.main import app  # noqa: E402

client = TestClient(app)

print("=== GET /enrichment/indices ===")
print(client.get("/enrichment/indices").json())

print("\n=== GET /entities/stats ===")
s = client.get("/entities/stats").json()
print({k: v for k, v in s.items() if k != "countries"})
print("top países:", [(c["country"], c["count"]) for c in s.get("countries", [])[:5]])

print("\n=== GET /entities/search?q=PRIMAVERA ===")
r = client.get("/entities/search?q=PRIMAVERA&size=5").json()
print("total:", r.get("total"), "| error:", r.get("error"))
for it in r.get("items", [])[:5]:
    print(f"  {it.get('nif')} | {it.get('name')[:45]:45} | {it.get('country')[:12]:12} | {it.get('contracts_count'):>6} | {it.get('total_value'):>14,.2f}")

print("\n=== GET /entities/search?q=EDP&only_with_nif=true&sort_by=total_value ===")
r = client.get("/entities/search?q=EDP&only_with_nif=true&size=5").json()
print("total:", r.get("total"))
for it in r.get("items", [])[:5]:
    print(f"  {it.get('nif')} | {it.get('name')[:45]:45} | {it.get('total_value'):>16,.2f}")

print("\n=== GET /entities/search (sem filtros, top valor) ===")
r = client.get("/entities/search?size=5").json()
print("total:", r.get("total"))
for it in r.get("items", [])[:5]:
    print(f"  {it.get('name')[:50]:50} | {it.get('contracts_count'):>7} | {it.get('total_value'):>18,.2f}")

print("\n=== GET /entities/autocomplete?q=SONAE ===")
r = client.get("/entities/autocomplete?q=SONAE&size=5").json()
for s2 in r.get("suggestions", []):
    print("  ", s2)

print("\n=== GET /entities/{nif} (exemplo com NIF) ===")
nif = next((it.get("nif") for it in client.get("/entities/search?q=PRIMAVERA&only_with_nif=true&size=5").json().get("items", []) if it.get("nif")), None)
print("nif escolhido:", nif)
if nif:
    r = client.get(f"/entities/{nif}")
    print(r.status_code)
    d = r.json()
    print({k: v for k, v in d.items() if k not in ("trademarks", "firmas")})
