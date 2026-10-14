"""Uma sessao ja aberta e cortada quando o admin poe a conta em `pending`?

Restaura o estado no fim. Confirma tambem que /auth/me devolve 403 (e nao um
perfil com status=pending), o que torna o ramo `pending_approval` do frontend
inalcancavel.
"""
import json
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:4180/api"
EMAIL = "teste.pendente.1791981548751@example.com"
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
_, utilizador = call("POST", "/auth/login", {"email": EMAIL, "password": PASSWORD})
token = utilizador["token"]
uid = utilizador["user"]["id"]
print(f"sessao aberta para {EMAIL} (id {uid}), estado={utilizador['user']['status']}")

codigo, corpo = call("GET", "/auth/me", token=token)
print(f"/auth/me com a conta ativa      -> {codigo} status={corpo.get('status') if isinstance(corpo, dict) else corpo}")

try:
    print("\nA administracao poe a conta em 'pending' (pelo seletor de Estado):")
    codigo_patch, corpo_patch = call("PATCH", f"/admin/users/{uid}", {"status": "pending"}, token=admin)
    print(f"  PATCH -> {codigo_patch} estado={corpo_patch.get('status') if isinstance(corpo_patch, dict) else corpo_patch}")

    codigo, corpo = call("GET", "/auth/me", token=token)
    print(f"\n/auth/me com o MESMO token      -> {codigo} {corpo}")
    print("  -> o frontend v\u00ea 403 e descarta o token (volta ao formul\u00e1rio),")
    print("     logo o ramo `status === 'pending'` em auth.tsx nunca corre.")

    codigo, corpo = call("GET", "/contracts/status", token=token)
    print(f"\n/contracts/status (endpoint protegido) -> {codigo}")
finally:
    codigo_patch, corpo_patch = call("PATCH", f"/admin/users/{uid}", {"status": "active"}, token=admin)
    print(f"\nrestaurado -> {codigo_patch} estado={corpo_patch.get('status') if isinstance(corpo_patch, dict) else corpo_patch}")
    codigo, corpo = call("GET", "/auth/me", token=token)
    print(f"/auth/me depois de restaurar    -> {codigo} status={corpo.get('status') if isinstance(corpo, dict) else corpo}")
