"""Lança a sincronização do índice de contribuintes pela API e acompanha o progresso.

Usa a sessão de uma conta (por omissão, a conta de QA local) para chamar
`POST /contribuintes/sync` em segundo plano e vai lendo `GET /contribuintes/jobs/{id}`
até terminar, imprimindo o progresso.

Uso:
    c:\\LLMFinance\\.venv\\Scripts\\python.exe _contribuintes_api_sync.py [fonte ...]
    (credenciais: variáveis IQOS_EMAIL / IQOS_PASSWORD; por omissão a conta de QA)
"""
import json
import os
import sys
import time

import httpx

BASE = os.getenv("IQOS_BASE", "http://127.0.0.1:8002")
EMAIL = os.getenv("IQOS_EMAIL", "qa.contribuintes@iqos.dev")
PASSWORD = os.getenv("IQOS_PASSWORD", "qa.contribuintes.2026")


def main(sources):
    with httpx.Client(base_url=BASE, timeout=120.0) as client:
        login = client.post("/auth/login", json={"email": EMAIL, "password": PASSWORD})
        login.raise_for_status()
        token = login.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        payload = {"sources": sources} if sources else {}
        started = client.post("/contribuintes/sync", headers=headers, json=payload)
        if started.status_code != 200:
            print("erro ao lançar:", started.status_code, started.text[:300], flush=True)
            return 1
        job_id = started.json().get("job_id")
        print(f"job {job_id} lançado para {sources or 'todas as fontes'}", flush=True)

        last = ""
        while True:
            time.sleep(10)
            job = client.get(f"/contribuintes/jobs/{job_id}", timeout=60).json()
            line = json.dumps(job.get("progress") or {}, ensure_ascii=False)
            if line != last:
                print(f"  [{job.get('status')}] {line}", flush=True)
                last = line
            if job.get("status") != "running":
                summary = job.get("summary") or {}
                print("estado:", job.get("status"), "| erro:", job.get("error"), flush=True)
                print(
                    "resumo: {unique} únicos, {written} escritos, {deleted} removidos em {duration}s".format(
                        unique=summary.get("unique"),
                        written=summary.get("written"),
                        deleted=summary.get("deleted"),
                        duration=summary.get("duration_s"),
                    ),
                    flush=True,
                )
                for source_id, stats in (summary.get("sources") or {}).items():
                    print(f"  · {source_id}: {stats.get('nifs')} registos, {stats.get('pages')} páginas, {stats.get('seconds')} s", flush=True)
                for error in summary.get("errors") or []:
                    print(f"  ! {error.get('source')}.{error.get('spec')}: {error.get('error')} (parcial: {error.get('partial_nifs')})", flush=True)
                return 0 if job.get("status") == "ok" else 1


if __name__ == "__main__":
    sys.exit(main([arg for arg in sys.argv[1:] if not arg.startswith("-")]))
