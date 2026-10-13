"""Inspecciona a lista do Wikidata incluída na página (temporário)."""
import json
import re

import httpx

TITULO = "Lista_das_câmaras_municipais_em_Portugal"
API = "https://pt.wikipedia.org/w/api.php"
cliente = httpx.Client(
    timeout=60.0,
    headers={"User-Agent": "IQOS/1.0 (analise de financas publicas; contacto@icpm.tech)"},
)
texto = cliente.get(
    API,
    params={"action": "parse", "page": TITULO, "prop": "wikitext", "format": "json", "formatversion": "2"},
).json()["parse"]["wikitext"]

i = texto.find("{{Lista do Wikidata")
print("---- Lista do Wikidata ----")
print(texto[i : i + 1200])

print()
print("---- HTML renderizado: que tabelas tem? ----")
html = cliente.get(
    API,
    params={"action": "parse", "page": TITULO, "prop": "text", "format": "json", "formatversion": "2"},
).json()["parse"]["text"]
tabelas = re.findall(r"<table.*?</table>", html, re.S)
print("tabelas no HTML:", len(tabelas))
for n, tabela in enumerate(tabelas):
    cabecalhos = re.findall(r"<th[^>]*>(.*?)</th>", tabela, re.S)
    limpos = [re.sub(r"<[^>]+>", "", c).strip() for c in cabecalhos][:8]
    print(f"  tabela {n}: {len(tabela)} chars | colunas: {limpos}")
    if n == 0:
        linhas = re.findall(r"<tr.*?</tr>", tabela, re.S)
        print("    linhas:", len(linhas))
        if len(linhas) > 1:
            print("    exemplo:", re.sub(r"<[^>]+>", " | ", linhas[1])[:300])

with open(".tmp_wiki_html.json", "w", encoding="utf-8") as ficheiro:
    json.dump({"html_len": len(html)}, ficheiro)
print()
print("comprimento do HTML:", len(html))
