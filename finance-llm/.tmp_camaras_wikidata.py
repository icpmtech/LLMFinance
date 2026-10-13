"""Protótipo: câmaras municipais (edifícios) do Wikidata + atribuição das fotos (temporário)."""
import httpx

CABECALHOS = {"User-Agent": "IQOS/1.0 (analise de financas publicas; contacto@icpm.tech)"}
SPARQL = """
SELECT DISTINCT ?item ?itemLabel ?imagem ?localizacaoLabel ?coord ?patrimonioLabel ?sipa ?artigo WHERE {
  ?item wdt:P31 wd:Q25550691 ; wdt:P17 wd:Q45 .
  OPTIONAL { ?item wdt:P18 ?imagem . }
  OPTIONAL { ?item wdt:P131 ?localizacao . }
  OPTIONAL { ?item wdt:P625 ?coord . }
  OPTIONAL { ?item wdt:P1435 ?patrimonio . }
  OPTIONAL { ?item wdt:P1700 ?sipa . }
  OPTIONAL { ?artigo schema:about ?item ; schema:isPartOf <https://pt.wikipedia.org/> . }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "pt,en". }
}
"""

resposta = httpx.get(
    "https://query.wikidata.org/sparql",
    params={"query": SPARQL, "format": "json"},
    headers={**CABECALHOS, "Accept": "application/sparql-results+json"},
    timeout=180.0,
)
print("estado:", resposta.status_code)
linhas = resposta.json()["results"]["bindings"]
print("linhas:", len(linhas))

itens = {}
for linha in linhas:
    qid = linha["item"]["value"].rsplit("/", 1)[-1]
    registo = itens.setdefault(qid, {
        "wikidata": qid,
        "designacao": linha.get("itemLabel", {}).get("value"),
        "imagem": None,
        "localizacao": None,
        "lat": None,
        "lon": None,
        "patrimonio": None,
        "sipa": None,
        "artigo": None,
    })
    if linha.get("imagem"):
        registo["imagem"] = linha["imagem"]["value"].rsplit("/", 1)[-1].replace("_", " ")
    if linha.get("localizacaoLabel"):
        registo["localizacao"] = linha["localizacaoLabel"]["value"]
    if linha.get("coord"):
        valor = linha["coord"]["value"]
        dentro = valor[valor.find("(") + 1 : valor.find(")")].split()
        registo["lat"], registo["lon"] = float(dentro[1]), float(dentro[0])
    if linha.get("patrimonioLabel"):
        registo["patrimonio"] = linha["patrimonioLabel"]["value"]
    if linha.get("sipa"):
        registo["sipa"] = linha["sipa"]["value"]
    if linha.get("artigo"):
        registo["artigo"] = linha["artigo"]["value"]

print("itens únicos:", len(itens))
com_foto = [r for r in itens.values() if r["imagem"]]
com_coord = [r for r in itens.values() if r["lat"]]
print("com foto:", len(com_foto), "| com coordenadas:", len(com_coord))
print()
print("exemplos:")
for registo in list(itens.values())[:5]:
    print(" ", registo["designacao"], "|", registo["localizacao"], "|", registo["lat"], registo["lon"], "|", registo["imagem"])

# Atribuição das imagens, em lotes de 50
ficheiros = sorted({r["imagem"] for r in com_foto})
print()
print("ficheiros a consultar no Commons:", len(ficheiros))
creditos = {}
for inicio in range(0, len(ficheiros), 50):
    lote = ficheiros[inicio : inicio + 50]
    dados = httpx.get(
        "https://commons.wikimedia.org/w/api.php",
        params={
            "action": "query",
            "format": "json",
            "formatversion": "2",
            "prop": "imageinfo",
            "iiprop": "url|extmetadata",
            "iiurlwidth": "320",
            "titles": "|".join(f"File:{nome}" for nome in lote),
        },
        headers=CABECALHOS,
        timeout=120.0,
    ).json()
    for pagina in dados.get("query", {}).get("pages", []):
        if "imageinfo" not in pagina:
            continue
        info = pagina["imageinfo"][0]
        meta = info.get("extmetadata", {})
        creditos[pagina["title"][5:]] = {
            "url": info.get("thumburl") or info.get("url"),
            "autor": (meta.get("Artist", {}) or {}).get("value", "")[:200],
            "licenca": (meta.get("LicenseShortName", {}) or {}).get("value"),
            "licenca_url": (meta.get("LicenseUrl", {}) or {}).get("value"),
            "pagina": info.get("descriptionurl"),
        }
print("créditos obtidos:", len(creditos))
print("exemplo:", list(creditos.items())[0])
