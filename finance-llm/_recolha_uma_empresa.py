"""Lança a recolha societária de uma entidade e acompanha o progresso."""
from __future__ import annotations

import json
import sys
import time

import httpx

sys.path.insert(0, r"c:/LLMFinance/finance-llm")

from api import auth_service  # noqa: E402

BASE = "http://127.0.0.1:8002"
NIF = sys.argv[1] if len(sys.argv) > 1 else "500697370"

utilizador = auth_service.get_user_by_email("mourao.martins@gmail.com")
sessao = auth_service.create_session(utilizador)
cabecalhos = {"Authorization": f"Bearer {sessao.get('token') or ''}"}

with httpx.Client(timeout=120, headers=cabecalhos) as cliente:
    inicio = cliente.post(
        f"{BASE}/societario/recolha/jobs",
        json={
            "nifs": [NIF],
            "max_entities": 1,
            "exclude_collected": False,
            "with_details": True,
            "max_pages": 50,
            "min_interval": 4.0,
            "ingest": True,
            "tipo": "0",
        },
    )
    if inicio.status_code != 200:
        print("falhou a lançar:", inicio.status_code, inicio.text[:300])
        raise SystemExit(1)
    job = inicio.json()
    print("job:", job["job_id"], "| status:", job["status"])
    job_id = job["job_id"]

    for volta in range(12):
        time.sleep(20)
        estado = cliente.get(f"{BASE}/societario/recolha/jobs/{job_id}").json()
        progresso = estado.get("progress") or {}
        atual = progresso.get("current") or {}
        print(
            f"[{(volta + 1) * 20:>4}s] status={estado['status']} | {progresso.get('phase')} | "
            f"pubs_gravadas={progresso.get('publications')} | encontradas={progresso.get('publications_live')} | "
            f"paginas={progresso.get('pages_read')} | ja_no_json={progresso.get('saved_total')} | atual={atual.get('name')}"
        )
        if estado["status"] != "running":
            print("resultado:", json.dumps(estado.get("result"), ensure_ascii=False)[:500])
            print("erro:", estado.get("error"))
            break
    cliente.post(f"{BASE}/auth/logout")
