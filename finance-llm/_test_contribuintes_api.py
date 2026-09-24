"""Verificação do módulo Contribuintes na API (leitura + escrita).

Uso:
    set IQOS_TOKEN=<token de sessão>
    c:\\LLMFinance\\.venv\\Scripts\\python.exe _test_contribuintes_api.py

Sem `IQOS_TOKEN`, são testados apenas os endpoints públicos.
"""
import json
import os
import sys
import time

import httpx

BASE = os.getenv("IQOS_BASE", "http://127.0.0.1:8002")
TOKEN = os.getenv("IQOS_TOKEN", "").strip()

ok = 0
fail = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global ok, fail
    if condition:
        ok += 1
        print(f"[OK]   {label} {detail}")
    else:
        fail += 1
        print(f"[FALHA] {label} {detail}")


def main() -> int:
    headers = {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}
    with httpx.Client(base_url=BASE, timeout=900.0) as client:
        response = client.get("/contribuintes/meta")
        check("GET /contribuintes/meta", response.status_code == 200, f"-> {response.status_code}")
        meta = response.json() if response.status_code == 200 else {}
        if meta:
            check("catálogo de fontes", len(meta.get("sources", [])) == 9, f"-> {len(meta.get('sources', []))} fontes")

        response = client.get("/contribuintes/status")
        check("GET /contribuintes/status", response.status_code == 200, f"-> {response.status_code}")
        status = response.json() if response.status_code == 200 else {}
        print("       documentos:", status.get("documents"), "| tipos:", [t["key"] for t in status.get("types", [])])

        response = client.get("/contribuintes/search", params={"size": 3, "sort": "activity"})
        check("GET /contribuintes/search", response.status_code == 200, f"-> {response.status_code}")
        result = response.json() if response.status_code == 200 else {}
        print("       total:", result.get("total"))
        for item in result.get("items", [])[:3]:
            print(f"       - {item['nif']} {item.get('name')} ({item.get('type')}) fontes={item.get('sources')}")

        response = client.get("/contribuintes/schedule")
        check("GET /contribuintes/schedule", response.status_code == 200, f"-> {response.status_code}")
        if response.status_code == 200:
            schedule = response.json()
            print("       enabled:", schedule.get("enabled"), "| cron:", schedule.get("cron"), "| scheduler:", schedule.get("scheduler", {}).get("active"))

        nif = (result.get("items") or [{}])[0].get("nif")
        if nif:
            response = client.get(f"/contribuintes/{nif}")
            check("GET /contribuintes/{nif}", response.status_code == 200, f"-> {response.status_code}")
            if response.status_code == 200:
                doc = response.json()
                blocks = sorted(key for key in doc if key.startswith("src_"))
                print(f"       ficha {nif}: {doc.get('name')} | {doc.get('type')} | papéis={doc.get('roles')} | blocos={blocks}")

        response = client.get("/contribuintes/naoexiste")
        check("GET /contribuintes/{nif} inexistente -> 400/404/503", response.status_code in (400, 404, 503), f"-> {response.status_code}")

        response = client.post("/contribuintes/sync", json={"sources": ["firmas"]})
        check("POST /contribuintes/sync sem sessão -> 401/403", response.status_code in (401, 403), f"-> {response.status_code}")

        authorized = False
        if TOKEN:
            response = client.get("/auth/me", headers=headers)
            authorized = response.status_code == 200
            check("sessão válida (GET /auth/me)", authorized, f"-> {response.status_code}")
        if not authorized:
            print("\n(sem sessão válida: operações de escrita não testadas)")
            print(f"\n{ok} verificações OK, {fail} falhas")
            return 1 if fail else 0

        response = client.post("/contribuintes/sync", headers=headers, json={"sources": ["firmas"], "wait": True})
        check("POST /contribuintes/sync (parcial, à espera)", response.status_code == 200, f"-> {response.status_code} {response.text[:200]}")
        if response.status_code == 200:
            summary = response.json().get("summary") or response.json()
            print("       resumo:", {key: summary.get(key) for key in ("run_id", "status", "unique", "written", "duration_s")})

        response = client.get("/contribuintes/jobs")
        check("GET /contribuintes/jobs", response.status_code == 200, f"-> {response.status_code}")

        response = client.put("/contribuintes/schedule", headers=headers, json={"enabled": False, "cron": "0 3 * * *", "timezone": "Europe/Lisbon"})
        check("PUT /contribuintes/schedule", response.status_code == 200, f"-> {response.status_code}")
        if response.status_code == 200:
            print("       agenda:", response.json().get("enabled"), response.json().get("cron"))

        response = client.put("/contribuintes/schedule", headers=headers, json={"enabled": True, "cron": "0 3 *"})
        check("PUT /contribuintes/schedule com cron inválido -> 400", response.status_code == 400, f"-> {response.status_code}")

    print(f"\n{ok} verificações OK, {fail} falhas")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
