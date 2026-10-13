"""Verificar unidades e municipios em falta no indicador do INE."""
import json
from pathlib import Path

base = Path(__file__).resolve().parent
d = json.loads((base / "despesas_ine.json").read_text(encoding="utf-8"))
bloco = d[0]
linhas = bloco["Dados"]["2023"]

geo7 = {x["geodsg"] for x in linhas if len(str(x["geocod"])) == 7}
print("municipios com geocod de 7:", len(geo7))

# valores de Lisboa no classificador Total
for alvo in ("Lisboa", "Abrantes"):
    for x in linhas:
        if x["geodsg"] == alvo and x["dim_3"] == "D":
            print(f"{alvo}: valor={x['valor']!r} ind_string={x['ind_string']!r} sinal={x['sinal_conv']!r} {x['sinal_conv_desc']!r}")

# municipios cujo `valor` nao e numerico
nao_numericos = {}
for x in linhas:
    if len(str(x["geocod"])) != 7:
        continue
    try:
        float(x["valor"])
    except (TypeError, ValueError):
        nao_numericos.setdefault(x["geodsg"], 0)
        nao_numericos[x["geodsg"]] += 1
print("\nmunicipios com valores nao numericos:", nao_numericos)

todos = sorted(geo7)
print("\ntotal nomes:", len(todos))
print("ultimos 6:", todos[-6:])

# procurar Penedono e outros
for alvo in ("Penedono", "Praia da Vitória", "Vila da Praia da Vitória", "Calheta"):
    achados = [n for n in todos if alvo.lower() in n.lower()]
    print(f"{alvo}: {achados}")
