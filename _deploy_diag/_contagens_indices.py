"""Contagens dos indices relevantes e do estado do modulo de vereadores."""

import json
import os
import urllib.request

INDICES = [
    "finance_vereadores",
    "finance_vortal",
    "finance_contribuintes",
    "finance_racius",
    "finance_gleif_lei",
    "finance_municipio_pessoas",
    "finance_municipios_despesas",
    "finance_remuneracoes",
    "finance_entities",
]

BASE_ES = os.environ.get("ELASTICSEARCH_URL", "http://elasticsearch:9200")

print("=== contagens ES ===")
for indice in INDICES:
    url = f"{BASE_ES}/{indice}/_count"
    try:
        with urllib.request.urlopen(url, timeout=10) as resposta:
            dados = json.load(resposta)
        print(f"  {indice:<32} {dados.get('count', 0):>9} docs")
    except Exception as exc:  # noqa: BLE001
        print(f"  {indice:<32} erro: {exc}")

print()
print("=== pastas de dados no backend ===")

for pasta in ("vereadores", "deputados", "politicos_portugal"):
    caminho = f"/opt/iqos/servicos/backend/data/{pasta}"
    existe = os.path.isdir(caminho)
    n = len(os.listdir(caminho)) if existe else 0
    print(f"  data/{pasta:<22} {'existe' if existe else 'AUSENTE'}  {n} ficheiros")
