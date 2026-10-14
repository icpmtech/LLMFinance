"""Verificacao: quais sao os caminhos de escrita realmente registados na app."""
from api.main import app

escritas = []
for rota in app.routes:
    caminho = getattr(rota, "path", None)
    metodos = getattr(rota, "methods", None) or set()
    if not caminho:
        continue
    for m in metodos:
        if m in {"POST", "PUT", "PATCH", "DELETE"}:
            escritas.append((m, caminho))

print(f"total de rotas na app: {len(app.routes)}")
print(f"total de (metodo, caminho) de escrita: {len(escritas)}")
print("\nprimeiras 40:")
for m, c in sorted(escritas, key=lambda x: x[1])[:40]:
    print(f"  {m:<7} {c}")
print("\nas que contem 'crm':")
for m, c in sorted(escritas, key=lambda x: x[1]):
    if "/crm" in c:
        print(f"  {m:<7} {c}")
