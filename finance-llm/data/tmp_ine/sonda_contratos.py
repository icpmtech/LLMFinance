"""Sonda: como atribuir contratos a municípios."""
import json
from collections import Counter

from api.elasticsearch_client import CONTRACTS_INDEX, get_es_client

client = get_es_client()
print("total contratos:", client.count(index=CONTRACTS_INDEX).get("count"))

# 1) localExecucao: que valores tem?
r = client.search(
    index=CONTRACTS_INDEX,
    body={"size": 0, "aggs": {"loc": {"terms": {"field": "localExecucao", "size": 25}}}},
)
print("\nlocalExecucao (top 25):")
for b in r["aggregations"]["loc"]["buckets"]:
    print("   ", b["key"], b["doc_count"])

# 2) adjudicantes com "Camara"/"Câmara" no nome
for termo in ("Câmara Municipal", "Camara Municipal", "Município de", "Municipio de"):
    q = {
        "size": 0,
        "query": {
            "nested": {
                "path": "adjudicantes.parsed",
                "query": {"match_phrase": {"adjudicantes.parsed.nome": termo}},
            }
        },
    }
    try:
        print(f"\nadjudicantes com '{termo}':", client.count(index=CONTRACTS_INDEX, body={"query": q["query"]})["count"])
    except Exception as exc:
        print(f"\nadjudicantes com '{termo}': erro {exc}")

# 3) exemplo de contrato com câmara
ex = client.search(
    index=CONTRACTS_INDEX,
    body={
        "size": 2,
        "query": {
            "nested": {
                "path": "adjudicantes.parsed",
                "query": {"match_phrase": {"adjudicantes.parsed.nome": "Câmara Municipal"}},
            }
        },
        "_source": ["idcontrato", "objectoContrato", "precoContratual", "localExecucao", "adjudicantes"],
    },
)
for h in ex["hits"]["hits"]:
    print("\n--- exemplo", h["_id"])
    print(json.dumps(h["_source"], ensure_ascii=False, indent=1)[:1200])
