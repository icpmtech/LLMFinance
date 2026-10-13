"""Sonda 5: wildcard por adjudicante-municipio e agregacao por nome do adjudicante."""
import json

from api.elasticsearch_client import CONTRACTS_INDEX, get_es_client

client = get_es_client()


def contar(rotulo, query):
    try:
        r = client.count(index=CONTRACTS_INDEX, body={"query": query})
        print(f"{r['count']:>10}  {rotulo}")
    except Exception as exc:
        print(f"{'ERRO':>10}  {rotulo} -> {str(exc)[:140]}")


def wc(padrao):
    return {
        "nested": {
            "path": "adjudicantes.parsed",
            "query": {"wildcard": {"adjudicantes.parsed.nome": {"value": padrao, "case_insensitive": True}}},
        }
    }


for padrao in ("*Município de*", "*Câmara Municipal*", "*Camara Municipal*", "*Município*", "*municipio*"):
    contar(f"adjudicantes.parsed.nome wildcard '{padrao}'", wc(padrao))

# agregacao: top adjudicantes por nome (keyword)
r = client.search(
    index=CONTRACTS_INDEX,
    body={
        "size": 0,
        "aggs": {
            "adj": {
                "nested": {"path": "adjudicantes.parsed"},
                "aggs": {
                    "nomes": {"terms": {"field": "adjudicantes.parsed.nome", "size": 12}},
                },
            }
        },
    },
)
print("\ntop 12 adjudicantes por nome:")
for b in r["aggregations"]["adj"]["nomes"]["buckets"]:
    print("   ", b["doc_count"], b["key"])
