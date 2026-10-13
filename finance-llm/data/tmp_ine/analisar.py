import collections
import json
from pathlib import Path

base = Path(__file__).resolve().parent
d = json.loads((base / "despesas_ine.json").read_text(encoding="utf-8"))
r = d[0]
print("chaves topo:", list(r.keys()))
print("dsg:", r.get("IndicadorDsg"))
print("atualizado:", r.get("DataUltimoAtualizacao"), "| ultimoPref:", r.get("UltimoPref"))
dados = r["Dados"]
anos = sorted(dados.keys())
print("anos:", anos)
linhas = dados[anos[-1]]
print(f"--- ano {anos[-1]}: {len(linhas)} linhas")
print("chaves linha:", list(linhas[0].keys()))
for k in sorted(linhas[0].keys()):
    if k.startswith("dim_"):
        vals = collections.Counter(str(x.get(k)) for x in linhas)
        print(f"   {k}: {len(vals)} valores")
        for item in list(vals.items())[:14]:
            print("      ", item)
geo = {(x.get("geocod"), x.get("geodsg")) for x in linhas}
print("municipios distintos:", len(geo))
print("exemplos geo:", list(geo)[:5])
# classificadores com etiqueta
cl = {}
for x in linhas:
    cl[x.get("dim_3")] = x.get("dim_3_t")
print("classificadores:", len(cl))
for k in sorted(cl):
    print("   ", k, "->", cl[k])
