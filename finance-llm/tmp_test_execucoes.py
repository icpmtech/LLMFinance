import requests, json, time, sys

BASE = "https://sabemos.studio"
EMAIL = "e2e-empresas-iq@example.com"
PASSW = "E2eEmpresasIQ123"

s = requests.Session()
r = s.post(f"{BASE}/api/auth/login", json={"email": EMAIL, "password": PASSW}, timeout=30)
print("login", r.status_code, r.text[:200])
if r.status_code != 200:
    sys.exit(1)
token = r.json().get("token", "")
s.headers["Authorization"] = f"Bearer {token}"

payload = {
    "nome": "",
    "documento": "",
    "tipo": "todos",
    "processo": "",
    "letras": ["A"],
    "max_paginas_por_letra": 2,
    "max_registos": 20,
    "intervalo": 1.5,
    "proxy": "",
    "importar": False,
    "atalho_datas": "todos"
}
r = s.post(f"{BASE}/api/execucoes/collect", json=payload, timeout=30)
print("collect", r.status_code, r.text[:500])
if r.status_code == 202:
    data = r.json()
    run_id = data.get("run_id") or data.get("id")
    print("run_id", run_id)
    time.sleep(10)
    r2 = s.get(f"{BASE}/api/execucoes/runs/{run_id}/status", timeout=30)
    print("status", r2.status_code, r2.text[:500])
