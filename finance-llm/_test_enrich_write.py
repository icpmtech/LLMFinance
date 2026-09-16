"""Testar os endpoints de ingestão (escrita) via API."""
import sys

sys.path.insert(0, ".")

from fastapi.testclient import TestClient  # noqa: E402

from api.main import app  # noqa: E402

client = TestClient(app)

print("=== POST /firmas/ingest (PRIMAVERA) ===")
r = client.post("/firmas/ingest", json={
    "name": "PRIMAVERA",
    "nif": "503140600",
    "max_results": 3,
    "include_detail": True,
})
print(r.status_code, r.json())

print("\n=== GET /firmas/search?q=PRIMAVERA ===")
r = client.get("/firmas/search?q=PRIMAVERA&size=5")
print(r.status_code, "total:", r.json().get("total"))
for it in r.json().get("items", [])[:5]:
    print("  *", it.get("nome"), "|", it.get("nipc"), "|", it.get("cae_principal"), "|", it.get("concelho_sede"))

print("\n=== GET /companies/503140600/firmas ===")
r = client.get("/companies/503140600/firmas?size=5")
print(r.status_code, "total:", r.json().get("total"))

print("\n=== POST /trademarks/ingest ===")
r = client.post("/trademarks/ingest", json={
    "name": "PRIMAVERA",
    "nif": "503140600",
    "max_results": 2,
    "include_detail": True,
})
print(r.status_code, r.json())

print("\n=== GET /companies/503140600/trademarks ===")
r = client.get("/companies/503140600/trademarks?size=5")
print(r.status_code, "total:", r.json().get("total"))
for it in r.json().get("items", [])[:5]:
    print("  *", it.get("mark_name"), "|", it.get("holder_name"), "|", it.get("application_date"))
