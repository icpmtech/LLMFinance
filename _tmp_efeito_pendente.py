"""O que acontece exatamente ao tentar entrar com uma conta pendente."""
import json
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:4180/api"
EMAIL = "teste.pendente.1791981500975@example.com"  # ainda pendente
PASSWORD = "Teste1234!"


def call(method, path, body=None, token=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        corpo = exc.read().decode()
        try:
            return exc.code, json.loads(corpo)
        except Exception:
            return exc.code, corpo


admin = call("POST", "/auth/login", {"email": "teste@teste.com", "password": "teste123"})[1]["token"]


def ficha():
    dados = call("GET", f"/admin/users?q={EMAIL}&limit=5", token=admin)[1]
    item = next(u for u in dados["items"] if u["email"] == EMAIL)
    return {
        "estado": item["status"],
        "sessoes_ativas": item.get("active_sessions"),
        "logins": item.get("login_count"),
        "ultimo_login": item.get("last_login_at"),
        "trial": item.get("trial_expires_at"),
    }


print("ANTES da tentativa de login:")
antes = ficha()
for k, v in antes.items():
    print(f"  {k:<16} {v}")

print("\nTentar entrar com a conta pendente:")
codigo, corpo = call("POST", "/auth/login", {"email": EMAIL, "password": PASSWORD})
print(f"  HTTP {codigo} -> {corpo}")

print("\nDEPOIS da tentativa:")
depois = ficha()
for k, v in depois.items():
    print(f"  {k:<16} {v}")

print("\nDiferencas:")
for k in antes:
    marca = "IGUAL" if antes[k] == depois[k] else f"MUDOU ({antes[k]} -> {depois[k]})"
    print(f"  {k:<16} {marca}")

print("\nUltimos eventos de autenticacao para este email:")
eventos = call("GET", f"/admin/events?source=auth&limit=200", token=admin)
lista = eventos[1].get("items") or eventos[1].get("events") or []
achados = [e for e in lista if EMAIL in json.dumps(e, ensure_ascii=False)][:4]
for e in achados:
    print(f"  [{e.get('level')}] {e.get('message')}  data={e.get('data')}")
if not achados:
    print(f"  (nenhum; chaves disponiveis: {list(eventos[1].keys())})")
