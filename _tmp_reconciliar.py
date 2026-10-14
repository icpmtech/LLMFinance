"""Compara os prefixos com escrita (OpenAPI) com os modulos do catalogo."""
import json
import urllib.request

with urllib.request.urlopen("http://127.0.0.1:4180/api/openapi.json", timeout=60) as resp:
    spec = json.loads(resp.read().decode())

prefixos = set()
for caminho, metodos in (spec.get("paths") or {}).items():
    for metodo in metodos:
        if metodo.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
            partes = [p for p in caminho.split("/") if p and not p.startswith("{")]
            if partes:
                prefixos.add(partes[0].lower())

import sys

sys.path.insert(0, r"c:\LLMFinance\finance-llm")
from api import permissions_service as perms  # noqa: E402

catalogo = set(perms.MODULE_BY_ID)

print(f"prefixos com escrita no OpenAPI: {len(prefixos)}")
print(f"modulos no catalogo:            {len(catalogo)}")

fora = sorted(prefixos - catalogo)
print(f"\n=== prefixos com escrita FORA do catalogo ({len(fora)}) ===")
for p in fora:
    print(f"  {p}")

sobrando = sorted(catalogo - prefixos)
print(f"\n=== modulos do catalogo sem escrita propria ({len(sobrando)}) ===")
for p in sobrando:
    print(f"  {p}")
