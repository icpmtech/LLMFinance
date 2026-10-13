"""Inspecciona a lista da Wikipédia das câmaras municipais (temporário)."""
import re

import httpx

TITULO = "Lista_das_câmaras_municipais_em_Portugal"
API = "https://pt.wikipedia.org/w/api.php"

cliente = httpx.Client(
    timeout=60.0,
    headers={"User-Agent": "IQOS/1.0 (analise de financas publicas; contacto@icpm.tech)"},
)

# 1. Metadados e tamanho
info = cliente.get(
    API,
    params={"action": "query", "prop": "info", "titles": TITULO, "format": "json"},
).json()
pagina = list(info["query"]["pages"].values())[0]
print("pagina:", pagina.get("title"), "| bytes:", pagina.get("length"))

# 2. Wikitexto
texto = cliente.get(
    API,
    params={
        "action": "parse",
        "page": TITULO,
        "prop": "wikitext",
        "format": "json",
        "formatversion": "2",
    },
).json()["parse"]["wikitext"]
print("wikitext:", len(texto), "caracteres")

# 3. Que predefinições/tabelas usa?
predefinicoes = re.findall(r"\{\{([A-Za-zÀ-ÿ0-9 _\-]+)", texto)
from collections import Counter

print("predefinicoes mais usadas:", Counter(p.strip() for p in predefinicoes).most_common(12))
print("tabelas (wikitable):", texto.count("{|"))

# 4. Mostra um pedaço que pareça uma linha de município
indice = texto.find("{|")
print("---- excerto ----")
print(texto[indice : indice + 1500])
