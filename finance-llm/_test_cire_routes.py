"""Teste HTTP das rotas POST do CIRE (com a dependência de sessão substituída por um stub)."""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi.testclient import TestClient  # noqa: E402

import api.main as m  # noqa: E402
from api.auth_routes import require_session  # noqa: E402


class _User:
    id = "test-user"
    email = "teste@teste.com"
    role = "admin"


class _Session:
    user = _User()
    email = "teste@teste.com"
    user_id = "test-user"


m.app.dependency_overrides[require_session] = lambda: _Session()
client = TestClient(m.app)

print("=== POST /cire/collect (1 dia, 2 páginas, index=true) ===")
resp = client.post(
    "/cire/collect",
    json={"desde": "2026-09-22", "ate": "2026-09-22", "max_pages": 2, "min_interval": 1.0, "index": True},
)
print(resp.status_code, resp.json().get("id"), resp.json().get("state"))
job_id = resp.json()["id"]

for _ in range(90):
    job = client.get(f"/cire/jobs/{job_id}").json()
    if job.get("finished"):
        break
    time.sleep(2)
print("job final:", {k: job.get(k) for k in ("state", "stage", "collected", "pages", "indexed", "run_id", "file")})
print("erros:", job.get("errors"))

print("\n=== GET /cire/jobs ===")
jobs = client.get("/cire/jobs").json()["jobs"]
print("jobs:", [(j["id"], j["state"], j.get("collected")) for j in jobs[:3]])

print("\n=== GET /cire/runs ===")
runs = client.get("/cire/runs").json()
for r in runs["items"][:3]:
    print(f"  {r['run_id']}: {r.get('collected')} recolhidos | {r.get('index_count')} no índice | indexed_at={r.get('indexed_at')}")

print("\n=== POST /cire/ingest (reimportar a mais recente) ===")
ing = client.post("/cire/ingest", json={}).json()
print({k: ing.get(k) for k in ("run_id", "indexed_count", "index_total")})

print("\n=== GET /cire/runs/{id} ===")
detail = client.get(f"/cire/runs/{runs['items'][0]['run_id']}").json()
print({k: detail.get(k) for k in ("run_id", "collected", "declared_total", "pages", "declared_total", "duration_s")})

print("\n=== GET /cire/search (com filtros) ===")
s = client.get("/cire/search", params={"tipo": "Insolvência", "size": 3}).json()
print("total:", s["total"], "| facetas:", list((s.get("facets") or {}).keys()))

print("\n=== POST /cire/collect inválido (só uma data) ===")
bad = client.post("/cire/collect", json={"desde": "2026-09-22", "max_pages": 1})
print(bad.status_code, bad.json().get("detail"))
