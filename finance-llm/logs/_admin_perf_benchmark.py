"""Benchmark dos endpoints usados pelas tabs da área de administração."""
from __future__ import annotations

import json
import statistics
import time
import urllib.request
from typing import Any

BASE = "http://127.0.0.1:4180"
EMAIL = "e2e-empresas-iq@example.com"
PASSWORD = "E2eEmpresasIQ123"

def post(path: str, payload: dict) -> tuple[int, dict]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8") or "{}")

def get(token: str, path: str) -> tuple[int, dict, float]:
    req = urllib.request.Request(
        f"{BASE}{path}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        method="GET",
    )
    start = time.perf_counter()
    with urllib.request.urlopen(req, timeout=120) as resp:
        body = resp.read().decode("utf-8")
    elapsed = time.perf_counter() - start
    return resp.status, json.loads(body or "{}"), elapsed

def login() -> str:
    status, body = post("/api/auth/login", {"email": EMAIL, "password": PASSWORD, "remember": True})
    if status != 200 or not body.get("token"):
        raise RuntimeError(f"Login falhou: {status} {body}")
    return body["token"]

def main() -> None:
    token = login()
    print(f"Sessão obtida para {EMAIL}")

    endpoints = [
        ("overview", "/api/admin/overview"),
        ("users", "/api/admin/users?limit=200"),
        ("events", "/api/admin/events?size=200&backend=memory"),
        ("events_stats", "/api/admin/events/stats?hours=24"),
        ("payments", "/api/admin/payments"),
        ("logs", "/api/admin/logs"),
        ("sidebar_access", "/api/admin/sidebar-access"),
        ("service_keys", "/api/admin/service-keys"),
        ("mfa_policy", "/api/admin/auth/mfa"),
        ("reports_inbox", "/api/reports/backoffice/inbox"),
        ("reports_backoffice_me", "/api/reports/backoffice/me"),
        ("reports_admin", "/api/reports/admin"),
        ("base_impic_recursos", "/api/base-impic/recursos"),
        ("base_impic_estado", "/api/base-impic/estado"),
        ("app_shell", "/api/admin/app-shell"),
    ]

    results: dict[str, list[float]] = {name: [] for name, _ in endpoints}

    # 3 corridas para ver variância / cache
    for run in range(1, 4):
        print(f"\n--- Corrida {run} ---")
        for name, path in endpoints:
            try:
                status, body, elapsed = get(token, path)
                results[name].append(elapsed)
                print(f"{name:25} {elapsed*1000:8.1f} ms  HTTP {status}  ({_summary(name, body)})")
            except Exception as exc:
                results[name].append(float("nan"))
                print(f"{name:25} ERRO: {exc}")

    print("\n=== Resumo (ms) ===")
    print(f"{'endpoint':25} {'min':>8} {'max':>8} {'mean':>8} {'median':>8}")
    for name, times in results.items():
        clean = [t * 1000 for t in times if not isinstance(t, float) or t == t]
        if clean:
            print(
                f"{name:25} {min(clean):8.1f} {max(clean):8.1f} "
                f"{statistics.mean(clean):8.1f} {statistics.median(clean):8.1f}"
            )
        else:
            print(f"{name:25} ERRO")

def _summary(name: str, body: dict) -> str:
    if name == "overview":
        return f"users={body.get('accounts', {}).get('users')}, es={body.get('elasticsearch', {}).get('available')}"
    if name == "users":
        return f"total={body.get('total')}, items={len(body.get('items', []))}"
    if name == "events":
        return f"total={body.get('total')}, backend={body.get('backend')}"
    if name == "events_stats":
        return f"total={body.get('total')}"
    if name == "payments":
        return f"items={len(body.get('items', []))}"
    if name == "logs":
        return f"files={len(body.get('files', []))}"
    if name == "sidebar_access":
        return f"profiles={len(body.get('profiles', []))}"
    if name == "service_keys":
        return f"chaves={len(body.get('chaves', []))}"
    if name == "mfa_policy":
        return f"policy={body.get('policy')}"
    if name in ("reports_inbox", "reports_admin"):
        return f"items={len(body.get('items', []))}"
    if name == "reports_backoffice_me":
        return f"backoffice={body.get('backoffice')}"
    if name == "base_impic_recursos":
        return f"recursos={len(body.get('recursos', []))}"
    if name == "base_impic_estado":
        return f"ano_atual={body.get('ano_atual')}"
    return "ok"

if __name__ == "__main__":
    main()
