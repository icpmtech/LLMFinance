"""Confirmar a unidade do indicador e municipios sem valores."""
import json
from pathlib import Path

import httpx

base = Path(__file__).resolve().parent
d = json.loads((base / "despesas_ine.json").read_text(encoding="utf-8"))
linhas = d[0]["Dados"]["2023"]

sem_valor = {}
for x in linhas:
    if len(str(x["geocod"])) != 7:
        continue
    if "valor" not in x:
        sem_valor[x["geodsg"]] = sem_valor.get(x["geodsg"], 0) + 1
print("linhas sem chave 'valor' por municipio:", sem_valor)

presentes = {x["geodsg"] for x in linhas if len(str(x["geocod"])) == 7}
utilizaveis = set()
for x in linhas:
    if len(str(x["geocod"])) != 7:
        continue
    try:
        float(x["valor"])
        utilizaveis.add(x["geodsg"])
    except (KeyError, TypeError, ValueError):
        pass
print("municipios presentes:", len(presentes), "| com pelo menos um valor:", len(utilizaveis))
print("em falta (nenhum valor numerico):", sorted(presentes - utilizaveis))

# unidade: pagina de metainformacao do INE
url = d[0].get("MetaInfUrl")
print("\nmeta:", url)
try:
    r = httpx.get(url, timeout=40, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})
    texto = r.text
    for chave in ("Unidade", "unidade", "Escala", "10^", "Milhares", "milhares"):
        i = texto.find(chave)
        if i >= 0:
            print(f"  '{chave}' -> {texto[max(0, i-120):i+160]!r}")
            break
except Exception as exc:
    print("  erro:", exc)
