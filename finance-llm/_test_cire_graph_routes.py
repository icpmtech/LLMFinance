"""Testa as rotas /cire/graph* através do TestClient (sem servidor a correr)."""
from __future__ import annotations

from api.main import app
from fastapi.testclient import TestClient

client = TestClient(app)

print("--- /cire/graph/dimensions ---")
r = client.get("/cire/graph/dimensions")
print(r.status_code, r.headers.get("content-type"))
data = r.json()
print("dimensões:", [d["key"] for d in data["dimensions"]])
print("receitas:", [x["id"] for x in data["recipes"]])

print("\n--- /cire/graph (exato, comarca) ---")
r = client.get("/cire/graph", params={"dimension_a": "comarca", "mode": "exato", "limit": 5})
print(r.status_code, r.headers.get("content-type"))
d = r.json()
print("modo:", d["meta"]["mode"], "| nós:", len(d["nodes"]), "| docs:", d["meta"]["documents_matching"])
print("topo:", [(n["label"], n["count"]) for n in d["nodes"][:3]])

print("\n--- /cire/graph (administrador × insolvente) ---")
r = client.get(
    "/cire/graph",
    params={
        "dimension_a": "administrador",
        "dimension_b": "insolvente",
        "sample": 3000,
        "limit": 20,
        "edge_limit": 15,
    },
)
print(r.status_code)
d = r.json()
print("nós:", len(d["nodes"]), "| arestas:", len(d["edges"]), "| notas:", len(d["meta"]["notes"]))
labels = {n["id"]: n["label"] for n in d["nodes"]}
for edge in d["edges"][:3]:
    print("  ", labels.get(edge["source"]), "→", labels.get(edge["target"]), edge["count"])

print("\n--- filtros (tipo=PER) ---")
r = client.get("/cire/graph", params={"dimension_a": "comarca", "tipo": "PER", "mode": "exato", "limit": 5})
print(r.status_code, [(n["label"], n["count"]) for n in r.json()["nodes"][:3]])

print("\n--- erro de dimensão ---")
r = client.get("/cire/graph", params={"dimension_a": "inexistente"})
print("status:", r.status_code, r.json().get("detail"))
