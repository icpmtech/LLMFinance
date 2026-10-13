import httpx

CABECALHOS = {"User-Agent": "IQOS/1.0 (analise de financas publicas; contacto@icpm.tech)"}

texto = httpx.get(
    "https://pt.wikipedia.org/w/api.php",
    params={
        "action": "parse",
        "page": "Lista de municípios de Portugal",
        "prop": "wikitext",
        "format": "json",
        "formatversion": "2",
    },
    headers=CABECALHOS,
    timeout=120.0,
).json()["parse"]["wikitext"]

inicio = texto.index("{|")
profundidade = 0
tabela = []
for linha in texto[inicio:].split("\n"):
    if linha.lstrip().startswith("{|"):
        profundidade += 1
    if linha.lstrip().startswith("|}"):
        profundidade -= 1
        tabela.append(linha)
        if profundidade == 0:
            break
        continue
    tabela.append(linha)

for linha in tabela:
    if "Almada" in linha or "Vila Real" in linha or "Lisboa" in linha:
        print(repr(linha[:260]))
