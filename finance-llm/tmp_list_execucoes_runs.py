import requests, json, sys

BASE = "https://sabemos.studio"
EMAIL = "e2e-empresas-iq@example.com"
PASSW = "E2eEmpresasIQ123"

s = requests.Session()
r = s.post(f"{BASE}/api/auth/login", json={"email": EMAIL, "password": PASSW, "remember": True}, timeout=30)
print("login", r.status_code, r.text[:200])
if r.status_code != 200:
    sys.exit(1)

r2 = s.get(f"{BASE}/api/execucoes/runs", timeout=30)
print("runs", r2.status_code, r2.text)
