"""Conta as rotas de escrita a partir do OpenAPI do servidor a correr."""
import json
import urllib.request

with urllib.request.urlopen("http://127.0.0.1:4180/api/openapi.json", timeout=60) as resp:
    spec = json.loads(resp.read().decode())

caminhos = spec.get("paths") or {}
escritas = []
for caminho, metodos in caminhos.items():
    for metodo in metodos:
        if metodo.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
            escritas.append((metodo.upper(), caminho))

print(f"total de caminhos no OpenAPI: {len(caminhos)}")
print(f"total de operacoes de escrita: {len(escritas)}")

prefixos = {}
for m, c in escritas:
    partes = [p for p in c.split("/") if p and not p.startswith("{")]
    prefixos.setdefault("/" + (partes[0] if partes else ""), []).append(c)

print(f"\nprefixos de topo com escrita: {len(prefixos)}\n")
for prefixo, lista in sorted(prefixos.items(), key=lambda x: -len(x[1])):
    print(f"  {prefixo:<28} {len(lista):>4}")
