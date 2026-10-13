"""Teste decisivo da unidade: soma nacional e escala na metainformacao."""
import json
import re
from pathlib import Path

import httpx

base = Path(__file__).resolve().parent
d = json.loads((base / "despesas_ine.json").read_text(encoding="utf-8"))
linhas = d[0]["Dados"]["2023"]

soma_D = 0.0
soma_PT = None
for x in linhas:
    if x["dim_3"] != "D":
        continue
    codigo = str(x["geocod"])
    if len(codigo) == 7:
        try:
            soma_D += float(x["valor"])
        except (KeyError, TypeError, ValueError):
            pass
    if codigo == "PT":
        soma_PT = x.get("valor")

print(f"soma dos 308 municipios (classificador D): {soma_D:,.0f}")
print(f"valor publicado para Portugal (PT):        {soma_PT}")
print("se a unidade for Euro:  soma =", f"{soma_D/1e9:.3f} mil M EUR")
print("se for milhares (10^3): soma =", f"{soma_D/1e6:.3f} mil M EUR")

r = httpx.get(d[0]["MetaInfUrl"], timeout=40, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})
texto = re.sub(r"<[^>]+>", " ", r.text)
texto = re.sub(r"\s+", " ", texto)
for chave in ("Escala", "escala", "10^", "Milhares", "milhares de", "Unidade de Medida"):
    for m in re.finditer(chave, texto):
        i = m.start()
        print(f"\n[{chave}] ...{texto[max(0, i-90):i+140]}...")
        break
