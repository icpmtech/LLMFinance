"""Sonda: /companies/role-summary (dashboard de adjudicantes)."""
import time

import httpx

BASE = "http://127.0.0.1:8002"
client = httpx.Client(trust_env=False, timeout=300)

for role in ("adjudicante", "adjudicatario", "all"):
    payload = {"role": role, "top_n": 25, "min_contracts": 1}
    t0 = time.perf_counter()
    try:
        r = client.post(f"{BASE}/companies/role-summary", json=payload)
        dt = time.perf_counter() - t0
        body = r.text
        print(f"role={role:14s} HTTP {r.status_code} em {dt:6.1f}s :: {body[:220]}")
        if r.status_code == 200:
            d = r.json()
            print("   chaves:", sorted(d.keys())[:14])
            print("   total:", d.get("total_entities"), "| contratos:", d.get("total_contracts"),
                  "| valor:", d.get("total_value"), "| concentração:", str(d.get("concentration"))[:80])
    except Exception as exc:  # noqa: BLE001
        print(f"role={role:14s} EXCECAO em {time.perf_counter() - t0:6.1f}s :: {type(exc).__name__}: {exc}")
