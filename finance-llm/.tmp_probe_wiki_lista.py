import re

import httpx

r = httpx.get(
    "https://pt.wikipedia.org/w/api.php",
    params={
        "action": "parse",
        "page": "Lista de municípios de Portugal",
        "prop": "wikitext",
        "format": "json",
        "formatversion": "2",
    },
    headers={"User-Agent": "IQOS/1.0 (analise de financas publicas; contacto@icpm.tech)"},
    timeout=120.0,
)
texto = r.json()["parse"]["wikitext"]
print("bytes:", len(texto))

# Cabeçalhos de tabela e primeiras linhas.
linhas = texto.split("\n")
cabecalhos = [(i, l) for i, l in enumerate(linhas) if l.lstrip().startswith("!")]
print("linhas de cabeçalho:", len(cabecalhos))
for i, l in cabecalhos[:20]:
    print(i, l[:200])

exemplo = [l for l in linhas if l.lstrip().startswith("|")][:12]
print("--- primeiras linhas de dados ---")
for l in exemplo:
    print(l[:220])
