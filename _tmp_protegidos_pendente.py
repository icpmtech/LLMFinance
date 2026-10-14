"""Endpoints realmente protegidos com a conta em `pending` (restaura no fim)."""
import json
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:4180/api"
EMAIL = "teste.pendente.1791981548751@example.com"
PASSWORD = "Teste1234!"
PROTEGIDOS = ["/auth/me", "/auth/sidebar-access", "/billing/subscription", "/scraper/meta"]


def call(method, path, body=None, token=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code


admin = call("POST", "/auth/login", {"email": "teste@teste.com", "password": "teste123"}) and None
req = urllib.request.Request(
    BASE + "/auth/login",
    data=json.dumps({"email": "teste@teste.com", "password": "teste123"}).encode(),
    method="POST",
)
req.add_header("Content-Type", "application/json")
with urllib.request.urlopen(req, timeout=60) as resp:
    admin = json.loads(resp.read().decode())["token"]

req = urllib.request.Request(
    BASE + "/auth/login",
    data=json.dumps({"email": EMAIL, "password": PASSWORD}).encode(),
    method="POST",
)
req.add_header("Content-Type", "application/json")
with urllib.request.urlopen(req, timeout=60) as resp:
    dados = json.loads(resp.read().decode())
token, uid = dados["token"], dados["user"]["id"]

print("primeiro, sem sessao (baseline dos endpoints):")
for caminho in PROTEGIDOS:
    print(f"  {caminho:<24} sem token -> {call('GET', caminho)}")

print("\ncom a conta ATIVA:")
for caminho in PROTEGIDOS:
    print(f"  {caminho:<24} -> {call('GET', caminho, token=token)}")

try:
    call("PATCH", f"/admin/users/{uid}", {"status": "pending"}, token=admin)
    print("\ncom a conta em PENDING (mesmo token):")
    for caminho in PROTEGIDOS:
        print(f"  {caminho:<24} -> {call('GET', caminho, token=token)}")
finally:
    call("PATCH", f"/admin/users/{uid}", {"status": "active"}, token=admin)
    print("\ndepois de restaurar:")
    for caminho in PROTEGIDOS:
        print(f"  {caminho:<24} -> {call('GET', caminho, token=token)}")
