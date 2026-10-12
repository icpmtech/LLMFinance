"""Sonda: contratos com peças do procedimento publicadas (e quantos são Vortal)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api.elasticsearch_client import CONTRACTS_INDEX, get_es_client  # noqa: E402

cliente = get_es_client()

total = cliente.count(index=CONTRACTS_INDEX, body={"query": {"bool": {"filter": [{"exists": {"field": "linkPecasProc"}}]}}})
print("contratos com linkPecasProc:", total.get("count"))

# Sem agregação por script (o campo é `text` sem fielddata: script dá «runtime error»):
# conta-se por anfitrião conhecido com `wildcard`.
for anfitriao in ("vortal.biz", "acingov.pt", "anogov.com", "base.gov.pt", "gov.pt", "compras", "municode", "saphety"):
    contagem = cliente.count(index=CONTRACTS_INDEX, body={"query": {"wildcard": {"linkPecasProc": f"*{anfitriao}*"}}})
    print(f"  {int(contagem.get('count') or 0):>8}  {anfitriao}")

exemplos = cliente.search(
    index=CONTRACTS_INDEX,
    body={
        "size": 6,
        "_source": ["idcontrato", "objectoContrato", "linkPecasProc", "Ano", "precoContratual"],
        "query": {"wildcard": {"linkPecasProc": "*vortal.biz*"}},
    },
)
print("\nexemplos com link Vortal:")
for hit in exemplos["hits"]["hits"]:
    fonte = hit["_source"]
    print(f"  {fonte.get('idcontrato')} | {fonte.get('Ano')} | {str(fonte.get('objectoContrato'))[:60]}")
    print(f"     {fonte.get('linkPecasProc')}")

outros = cliente.search(
    index=CONTRACTS_INDEX,
    body={
        "size": 4,
        "_source": ["idcontrato", "objectoContrato", "linkPecasProc", "Ano"],
        "query": {"bool": {"filter": [{"exists": {"field": "linkPecasProc"}}]}},
    },
)
print("\nexemplos (quaisquer peças publicadas):")
for hit in outros["hits"]["hits"]:
    fonte = hit["_source"]
    print(f"  {fonte.get('idcontrato')} | {fonte.get('Ano')} | {str(fonte.get('linkPecasProc'))[:110]}")
