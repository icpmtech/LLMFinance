"""Sonda 8: por que faltam municipios no emparelhamento."""
import json
import re
import unicodedata
from pathlib import Path

base = Path(__file__).resolve().parent
contratos = json.loads((base / "contratos_municipios.json").read_text(encoding="utf-8"))

for alvo in ("Guarda", "Maia", "Covilh", "Cartaxo", "Nazar", "Entroncamento", "Marinha", "Murtosa", "Bombarral", "Cadaval"):
    achados = [n for n in contratos if alvo.lower() in unicodedata.normalize("NFKD", n).encode("ascii", "ignore").decode().lower()]
    print(f"{alvo}: {len(achados)} -> {achados[:4]}")

print()
padrao = re.compile(r"(?:c[âa]mara\s+municipal|munic[íi]pio)\s+d(?:e|o|a)\s+(?P<nome>.+?)\s*$", re.IGNORECASE)
for nome in list(contratos)[:0]:
    pass
# quantos nomes terminam em formas que o padrao nao apanha
sem_connector = [n for n in contratos if not padrao.search(n.strip())]
print("nomes que o padrao NAO apanha:", len(sem_connector))
for n in sem_connector[:25]:
    print("   ", n)
