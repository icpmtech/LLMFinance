"""Verifica que as rotas do Email ficam bem montadas na aplicação FastAPI."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.email_routes import router as email_router

app = FastAPI()
app.include_router(email_router)
client = TestClient(app)

routes = sorted(
    (sorted(route.methods)[0], route.path)
    for route in app.routes
    if getattr(route, "methods", None) and route.path.startswith("/email")
)
for method, path in routes:
    print(f"{method:7} {path}")

print("total:", len(routes))

# Sem sessão, tudo o que é pessoal responde 401 (as contas são por utilizador).
response = client.get("/email/accounts")
print("GET /email/accounts ->", response.status_code, response.json())

# O catálogo de fornecedores não expõe segredos e traz os presets esperados.
response = client.get("/email/meta")
payload = response.json()
print("GET /email/meta ->", response.status_code, [item["id"] for item in payload["items"]])
