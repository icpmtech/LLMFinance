"""Inventario dos routers da app: prefixo, metodos de escrita e dependencias ja aplicadas."""
from api.main import app

MODULOS = {}
for rota in app.routes:
    caminho = getattr(rota, "path", None)
    metodos = getattr(rota, "methods", None) or set()
    if not caminho:
        continue
    partes = [p for p in caminho.split("/") if p]
    prefixo = "/" + (partes[0] if partes else "")
    entrada = MODULOS.setdefault(prefixo, {"rotas": 0, "escritas": set()})
    entrada["rotas"] += 1
    for m in metodos:
        if m in {"POST", "PUT", "PATCH", "DELETE"}:
            entrada["escritas"].add(m)

print(f"{'prefixo':<34}{'rotas':>6}{'escritas':>9}  metodos")
for prefixo, dados in sorted(MODULOS.items(), key=lambda x: -len(x[1]["escritas"])):
    print(f"{prefixo:<34}{dados['rotas']:>6}{len(dados['escritas']):>9}  {'/'.join(sorted(dados['escritas']))}")

print(f"\ntotal de prefixos de topo: {len(MODULOS)}")
com_escrita = [p for p, d in MODULOS.items() if d["escritas"]]
print(f"prefixos com escrita: {len(com_escrita)}")
