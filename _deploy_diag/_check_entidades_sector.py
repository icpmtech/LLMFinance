import json
import os

PASTA = "/opt/iqos/servicos/backend/data/entidades-sector"

print("=== conteudo da pasta ===")
for nome in sorted(os.listdir(PASTA)):
    caminho = os.path.join(PASTA, nome)
    print(f"  {os.path.getsize(caminho):>10}  {nome!r}")

indice = os.path.join(PASTA, "administracao-central.json")
print()
print("=== administracao-central.json ===")
with open(indice, encoding="utf-8") as fh:
    dados = json.load(fh)

entidades = dados.get("entidades") or []
ligadas = [e for e in entidades if e.get("nif")]
print(f"  entidades : {len(entidades)}")
print(f"  ligadas   : {len(ligadas)}")
print(f"  total     : {dados.get('total')}")
print(f"  subsetores: {len(dados.get('subsetores') or [])}")

print()
print("=== top 8 por valor ===")
por_valor = sorted(entidades, key=lambda e: e.get("valor") or 0, reverse=True)
for e in por_valor[:8]:
    print(
        f"  {(e.get('valor') or 0):>15,.0f} €  "
        f"{e.get('contratos') or 0:>5} contratos  "
        f"{e.get('nif') or '(sem NIF)':>10}  {e.get('nome')}"
    )

print()
print("=== ficheiros auxiliares ===")
for extra in ("ligacoes-manuais.json",):
    caminho = os.path.join(PASTA, extra)
    print(f"  {extra}: {'existe' if os.path.exists(caminho) else 'nao existe'}")
