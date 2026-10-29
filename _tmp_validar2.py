import csv, io, json, statistics, urllib.request
from collections import defaultdict

def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "validador/1.0"})
    with urllib.request.urlopen(req, timeout=90) as resp:
        return resp.read().decode("utf-8", "replace")

precos = defaultdict(list)
for pagina in range(1, 6):
    payload = json.loads(get(f"https://precoscombustiveis.dgeg.gov.pt/api/PrecoComb/PesquisarPostos?idsTiposComb=2101&qtdPorPagina=5000&pagina={pagina}"))
    postos = payload.get("resultado") or []
    if not postos:
        break
    for p in postos:
        precos[p["Municipio"]].append(float(str(p["Preco"]).replace("€", "").replace(".", "").replace(",", ".").strip()))
    if len(postos) < 5000:
        break

print("postos lidos:", sum(len(v) for v in precos.values()), "concelhos:", len(precos))
for nome in ["Mêda", "Porto Santo", "Calheta (R.A.A.)", "Funchal"]:
    print(" ", nome, "->", round(statistics.median(precos[nome]), 4) if precos.get(nome) else None)

imi = {r["municipality"].strip(): r["urban_percent"].strip()
       for r in csv.DictReader(io.StringIO(get("https://flatin.pt/api/v1/imi/rates.csv?year=2025").lstrip("\ufeff")))}
for nome in ["Lagoa (Algarve)", "Lagoa (Açores)", "Porto Santo", "Sesimbra"]:
    print(" IMI", nome, "->", imi.get(nome) or "(vazio)")
