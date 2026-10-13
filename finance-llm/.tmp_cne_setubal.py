"""Corrige a deteção de blocos (CÓD numérico) e inspeciona Setúbal (temporário)."""
from collections import Counter

import openpyxl

CAMINHO = ".tmp_cne/2025al-mapa-oficial_retificado/mapa_3_eleitos_retificado.xlsx"
folha = openpyxl.load_workbook(CAMINHO, read_only=True, data_only=True)["Folha1"]
linhas = [list(linha) for linha in folha.iter_rows(values_only=True)]

larguras = Counter(len(linha) for linha in linhas)
print("larguras de linha:", larguras.most_common(8))


def vazio(valor):
    return valor is None or str(valor).strip() == ""


blocos = []
atual = None
for linha in linhas:
    primeira = "" if vazio(linha[0]) else str(linha[0]).strip()
    if primeira.isdigit():
        if atual:
            blocos.append(atual)
        atual = {
            "cod": primeira,
            "concelho": str(linha[1]).strip() if not vazio(linha[1]) else "",
            "freguesia": str(linha[2]).strip() if not vazio(linha[2]) else None,
            "org": str(linha[3]).strip() if not vazio(linha[3]) else "",
            "linhas": [],
        }
    elif atual is not None:
        atual["linhas"].append([None if vazio(c) else str(c).strip() for c in linha])
if atual:
    blocos.append(atual)

print("blocos:", len(blocos))
print("por órgão:", Counter(b["org"] for b in blocos).most_common(6))

cm = [b for b in blocos if b["org"] == "CM"]
print("blocos CM:", len(cm))

for bloco in cm:
    if bloco["concelho"].lower().startswith("setúbal") or bloco["concelho"].lower().startswith("setubal"):
        print()
        print("=== SETÚBAL", bloco["cod"], "===")
        for numero, linha in enumerate(bloco["linhas"]):
            preenchidas = [(i, v) for i, v in enumerate(linha) if v]
            print(f"  {numero}: {preenchidas}")
        break
