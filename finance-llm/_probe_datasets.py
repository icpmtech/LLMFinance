import json, urllib.request
BASE = "http://127.0.0.1:8002"

def call(path, method="GET", body=None, token=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())

login = call("/auth/login", "POST", {"email": "teste@teste.com", "password": "teste"})
token = login.get("token") or login.get("access_token")
print("login:", bool(token))
cat = call("/crm/analytics/datasets", token=token)
print("datasets:", cat["total"], "| grupos:", cat["groups"])
print("ignorados:", cat["ignorados"])
for ds in cat["datasets"][:4]:
    print("  -", ds["id"], "|", ds["dimension"]["label"], "|", [m["key"] for m in ds["metrics"]])
rows = call("/crm/analytics/datasets/vendas-utilizador?months=12", token=token)
print("vendas-utilizador:", rows.get("error") or (rows["linhas_totais"], "linhas;", "totais:", rows["totals"]))
rows2 = call("/crm/analytics/datasets/encomendas-estado", token=token)
print("encomendas-estado:", rows2.get("error") or rows2["rows"][:3])
suite = call("/crm/suite", token=token)
dash = [m for m in suite["modules"] if m["slug"] == "dashboards"]
print("módulo dashboards:", dash[0]["label"] if dash else "EM FALTA", "| grupo:", dash[0]["group"] if dash else "-", "| criar:", dash[0]["permissions"]["create"] if dash else "-")
print("grupos do registo:", [g["id"] for g in suite["groups"]])
