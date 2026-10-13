import json

import httpx

CONSULTA = """
SELECT ?municipio ?municipioLabel ?brasao ?inception ?inceptionPrec ?area ?populacao WHERE {
  ?municipio wdt:P31/wdt:P279* wd:Q13217644 .
  ?municipio wdt:P17 wd:Q45 .
  OPTIONAL { ?municipio wdt:P94 ?brasao . }
  OPTIONAL { ?municipio wdt:P571 ?inception . }
  OPTIONAL { ?municipio p:P571/psv:P571 [wikibase:timePrecision ?inceptionPrec] . }
  OPTIONAL { ?municipio wdt:P2046 ?area . }
  OPTIONAL { ?municipio wdt:P1082 ?populacao . }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "pt,en". }
}
"""

r = httpx.get(
    "https://query.wikidata.org/sparql",
    params={"query": CONSULTA, "format": "json"},
    headers={"User-Agent": "IQOS/1.0 (analise de financas publicas; contacto@icpm.tech)"},
    timeout=180.0,
)
print("status", r.status_code)
dados = r.json()["results"]["bindings"]
print("linhas:", len(dados))
municipios = {}
for linha in dados:
    qid = linha["municipio"]["value"].rsplit("/", 1)[-1]
    reg = municipios.setdefault(qid, {"nome": linha.get("municipioLabel", {}).get("value"), "brasao": None, "datas": []})
    if linha.get("brasao") and not reg["brasao"]:
        reg["brasao"] = linha["brasao"]["value"].rsplit("/", 1)[-1]
    if linha.get("inception"):
        reg["datas"].append((linha["inception"]["value"], linha.get("inceptionPrec", {}).get("value")))
print("municipios distintos:", len(municipios))
print("com brasao:", sum(1 for m in municipios.values() if m["brasao"]))
print("com data:", sum(1 for m in municipios.values() if m["datas"]))
print("exemplos:")
for qid, m in list(municipios.items())[:8]:
    print("  ", qid, m["nome"], "|", m["brasao"], "|", m["datas"][:2])
sem = [m["nome"] for m in municipios.values() if not m["brasao"]]
print("sem brasao:", len(sem), sem[:30])
semdata = [m["nome"] for m in municipios.values() if not m["datas"]]
print("sem data:", len(semdata), semdata[:30])
with open(".tmp_brasao.json", "w", encoding="utf-8") as fh:
    json.dump(municipios, fh, ensure_ascii=False, indent=1)
