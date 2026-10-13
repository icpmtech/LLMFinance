"""Validacao da API de despesas municipais."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from api import municipios_service as m  # noqa: E402

r = m.listar(size=6, ordenar="despesas")
print("total:", r["total"], "| origem:", r.get("origem"))
for i in r["items"]:
    desp = (i.get("despesas_total") or 0) / 1e6
    con = (i.get("contratos_valor") or 0) / 1e6
    print(f"   {i['nome']:<24} {(i.get('distrito') or '-'):<16} desp={desp:>8.1f} M  contr={con:>8.1f} M")
print("soma despesas (M EUR):", round((r.get("despesas_somadas") or 0) / 1e6, 1))
print("soma contratos (M EUR):", round((r.get("contratos_somados") or 0) / 1e6, 1))
print("distritos:", len(r.get("distritos") or []))

print("\n-- ficha Abrantes --")
f = m.ficha("abrantes")
for k in ("nome", "geocod", "distrito", "nuts_nome", "ano_despesas", "despesas_total",
          "despesas_pessoal", "despesas_bens_servicos", "despesas_capital",
          "contratos_total", "contratos_valor", "contratos_primeiro_ano", "contratos_ultimo_ano"):
    print(f"   {k}: {f.get(k)}")
print("   adjudicantes:", f.get("adjudicantes"))
print("   contratos por ano:", json.dumps(f.get("contratos_por_ano"), ensure_ascii=False)[:220])

print("\n-- ficha por codigo INE --")
g = m.ficha("1D21401")
print("   nome:", g.get("nome"), "| total:", g.get("despesas_total"))

print("\n-- filtros --")
print("   distrito Lisboa:", m.listar(distrito="Lisboa", size=1)["total"])
print("   q=Aveiro:", m.listar(q="Aveiro", size=3)["total"])
print("   ordenar=contratos:", [i["nome"] for i in m.listar(ordenar="contratos", size=3)["items"]])

print("\n-- meta --")
meta = m.meta()
print("   anos:", meta["anos"], "| indicador:", meta["indicador"], "| unidade:", meta["indice"].get("documents"), "docs")
print("   total despesas (MM EUR):", round((meta["indice"].get("total_despesas") or 0) / 1e9, 2))
print("   total contratos (MM EUR):", round((meta["indice"].get("total_contratos") or 0) / 1e9, 2))

print("\n-- mapa --")
mm = m.mapa()
print("   total:", mm["total"], "| primeiro:", mm["items"][0]["nome"])
