import json
from pathlib import Path

base = Path(__file__).resolve().parent
d = json.loads((base / "despesas_ine.json").read_text(encoding="utf-8"))
linhas = d[0]["Dados"]["2023"]
geo = sorted({(x["geocod"], x["geodsg"]) for x in linhas})
print("total geografias:", len(geo))
curtos = [g for g in geo if len(g[0]) <= 3]
longos = [g for g in geo if len(g[0]) > 3]
print("codigos curtos (NUTS/agregados):", len(curtos))
for g in curtos:
    print("   ", g)
print("codigos de municipio:", len(longos))
print("exemplos:", longos[:8])
comprimentos = {}
for g in longos:
    comprimentos[len(g[0])] = comprimentos.get(len(g[0]), 0) + 1
print("comprimentos de codigo:", comprimentos)
