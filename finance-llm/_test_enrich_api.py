"""Testar os endpoints HTTP de marcas/firmas com o TestClient do FastAPI."""
import sys

sys.path.insert(0, ".")

from fastapi.testclient import TestClient  # noqa: E402

from api.main import app  # noqa: E402

client = TestClient(app)
NIF = "503933813"

print("=== GET /enrichment/indices ===")
r = client.get("/enrichment/indices")
print(r.status_code, r.json())

print("\n=== GET /companies/{nif}/trademarks ===")
r = client.get(f"/companies/{NIF}/trademarks?size=3")
print(r.status_code)
data = r.json()
print("total:", data.get("total"), "| error:", data.get("error"))
for it in data.get("items", [])[:3]:
    print("  *", it.get("mark_name"), "|", it.get("current_phase"), "|", len(it.get("nice_classes") or []), "classes")

print("\n=== GET /companies/{nif}/firmas ===")
r = client.get(f"/companies/{NIF}/firmas?size=3")
print(r.status_code)
data = r.json()
print("total:", data.get("total"), "| error:", data.get("error"))
for it in data.get("items", [])[:3]:
    print("  *", it.get("nome"), "|", it.get("nipc"), "|", it.get("score"))

print("\n=== GET /trademarks/search?q=PORTUGAL ===")
r = client.get("/trademarks/search?q=PORTUGAL&size=3")
print(r.status_code, "total:", r.json().get("total"))

print("\n=== GET /firmas/search?q=PRIMAVERA ===")
r = client.get("/firmas/search?q=PRIMAVERA&size=3")
print(r.status_code, "total:", r.json().get("total"))

print("\n=== GET /companies/{nif} (ficha completa) ===")
r = client.get(f"/companies/{NIF}", headers={"Accept": "application/json"})
print(r.status_code)
d = r.json()
print("name:", d.get("name"))
print("trademarks_total:", d.get("trademarks_total"), "| firmas_total:", d.get("firmas_total"))
print("trademarks:", len(d.get("trademarks") or []), "| firmas:", len(d.get("firmas") or []))
