"""Teste das rotas /ontology/* com o cliente de testes do FastAPI."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi.testclient import TestClient  # noqa: E402

from api.main import app  # noqa: E402

client = TestClient(app)


def show(label: str, response) -> None:
    body = response.json() if response.headers.get("content-type", "").startswith("application/json") else response.text
    text = json.dumps(body, ensure_ascii=False, default=str) if not isinstance(body, str) else body
    print(f"  {response.status_code} {label}: {text[:260]}")


def main() -> int:
    print("== leitura ==")
    show("GET /ontology/summary", client.get("/ontology/summary"))
    show("GET /ontology/object-types", client.get("/ontology/object-types"))
    show("GET /ontology/object-types/empresa", client.get("/ontology/object-types/empresa"))
    show("GET /ontology/object-types/inexistente", client.get("/ontology/object-types/inexistente"))
    show("GET /ontology/link-types", client.get("/ontology/link-types"))
    show("GET /ontology/actions", client.get("/ontology/actions"))
    show("GET /ontology/graph", client.get("/ontology/graph"))
    show("GET /ontology/status", client.get("/ontology/status"))
    show("GET /ontology/ai/tools", client.get("/ontology/ai/tools"))
    show("GET /ontology", client.get("/ontology"))

    print("== consultas ==")
    show("POST empresa query", client.post("/ontology/objects/empresa/query", json={"search": "EDP", "size": 2}))
    show("POST contrato query", client.post("/ontology/objects/contrato/query", json={"filters": {"ano": 2025}, "size": 1}))
    show("POST cpv query", client.post("/ontology/objects/cpv/query", json={"search": "medicamentos", "size": 2}))
    show("POST conta query (sem sessão)", client.post("/ontology/objects/conta/query", json={"size": 1}))
    show("POST resolve", client.post("/ontology/resolve", json={"text": "contratos da EDP e GALP em 2025", "limit": 4}))
    show("GET objeto", client.get("/ontology/objects/empresa/500233810?with_links=true"))
    show("GET objeto inexistente", client.get("/ontology/objects/empresa/000000000"))
    show("POST links", client.post("/ontology/objects/empresa/500233810/links?size=2"))
    show("POST links (ligação específica)", client.post("/ontology/objects/empresa/500233810/links?link=empresa_marcas"))

    print("== IA ==")
    show("POST ai/context", client.post("/ontology/ai/context", json={"question": "Quais os contratos da EDP?"}))
    show("POST ai/answer", client.post("/ontology/ai/answer", json={"question": "Quais os contratos da EDP?"}))
    show(
        "POST ai/validate",
        client.post("/ontology/ai/validate", json={"answer": "A EDP tem contratos. A Inventada Lda (NIF 999999999) ganhou 1 M€."}),
    )

    print("== ações ==")
    show("POST action resolve", client.post("/ontology/actions/empresa.contratos/resolve", json={"type": "empresa", "id": "500233810"}))
    show("POST action resolve (sessão)", client.post("/ontology/actions/empresa.enriquecer/resolve", json={"type": "empresa", "id": "500233810"}))

    print("== escrita (sem sessão, deve dar 401) ==")
    show("POST object-types", client.post("/ontology/object-types", json={"id": "teste", "label": "Teste"}))
    show("DELETE object-types/empresa", client.delete("/ontology/object-types/empresa"))
    show("POST reset", client.post("/ontology/reset", json={"confirm": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
