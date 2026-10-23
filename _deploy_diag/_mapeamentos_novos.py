import json
import os
import urllib.request

INDICES = ["finance_empresas_locais", "finance_freguesias_contactos"]
BASE = os.environ.get("ES_BASE") or os.environ.get("ELASTICSEARCH_URL") or "http://elasticsearch:9200"


def mapeamento(indice):
    url = f"{BASE}/{indice}/_mapping"
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            dados = json.load(r)
    except Exception as exc:  # noqa: BLE001
        return {"erro": str(exc)}
    for _, corpo in dados.items():
        return (corpo.get("mappings") or {}).get("properties") or {}
    return {}


for indice in INDICES:
    props = mapeamento(indice)
    print(f"=== {indice} ===")
    if "erro" in props:
        print(f"  erro: {props['erro']}")
        continue
    print(f"  campos: {len(props)}")
    for nome in sorted(props):
        tipos = props[nome]
        tipo = tipos.get("type") or ("object" if "properties" in tipos else "?")
        extra = ""
        if tipo == "text" and tipos.get("fields"):
            extra = " +" + ",".join(tipos["fields"].keys())
        if tipo == "keyword" and tipos.get("ignore_above"):
            extra = f" (ignore_above={tipos['ignore_above']})"
        print(f"    {nome:<34} {tipo}{extra}")
    print()
