import json, statistics, urllib.request
from collections import defaultdict

API = "https://sabemos.studio/api/custo-vida/concelhos?size=400"

def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "validador/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8", "replace")

items = json.loads(get(API))["items"]
por_nome = {i["nome"]: i for i in items}
amostra = ["Lisboa", "Caminha", "Mêda", "Faro", "Braga", "Calheta (R.A.A.)", "Lagoa", "Porto Santo"]

# --- IMI: ficheiro oficial (AT via flatin) ---
import csv, io
imi = {}
for row in csv.DictReader(io.StringIO(get("https://flatin.pt/api/v1/imi/rates.csv?year=2025").lstrip("\ufeff"))):
    imi[row["municipality"].strip()] = row["urban_percent"].strip()

print("== IMI ==")
for nome in amostra:
    fonte = imi.get(nome) or imi.get(nome.replace(" (R.A.A.)", " (Açores)")) or ""
    api = por_nome[nome]["imi_pct"]
    print(f"  {nome:24} fonte={fonte or '(vazio)':10} api={api}")

# --- Gasóleo: mediana recalculada dos postos da DGEG ---
postos = json.loads(get("https://precoscombustiveis.dgeg.gov.pt/api/PrecoComb/PesquisarPostos?idsTiposComb=2101&qtdPorPagina=5000&pagina=1"))["resultado"]
precos = defaultdict(list)
for p in postos:
    preco = float(str(p["Preco"]).replace("€", "").replace(".", "").replace(",", ".").strip())
    precos[p["Municipio"]].append(preco)

print("== Gasóleo ==")
for nome in amostra:
    valores = precos.get(nome)
    esperado = round(statistics.median(valores), 4) if valores else None
    print(f"  {nome:24} dgeg={esperado} api={por_nome[nome]['gasoleo_l']}")

# --- Índice: recalcular a partir do custo e da mediana ---
print("== Índice ==")
custos = sorted(i["custo_t2"] for i in items if i["custo_t2"] is not None)
mediana = custos[len(custos) // 2]
for nome in amostra:
    d = por_nome[nome]
    if d["custo_t2"] is None:
        print(f"  {nome:24} sem renda -> indice {d['indice']}")
        continue
    esperado = round(100 * d["custo_t2"] / mediana, 1)
    print(f"  {nome:24} custo={d['custo_t2']:8.2f} indice={d['indice']:6.1f} esperado={esperado:6.1f} ok={abs(esperado-d['indice'])<0.2}")

# --- Componentes fixos ---
d = items[0]
print("== Fixos ==", "eletricidade", d["eletricidade_mensal"], "gas", d["gas_mensal"])

# --- Decomposição de um concelho ---
d = por_nome["Caminha"]
calc = d["renda_m2"] * 70 + d["gasoleo_l"] * 50 + d["eletricidade_mensal"] + d["gas_mensal"] + d["imi_anual"] / 12
print("Caminha T2:", d["custo_t2"], "recalc:", round(calc, 2))
