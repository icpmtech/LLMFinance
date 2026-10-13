"""Sonda 3: contratos cujo adjudicante e o proprio municipio/camara."""
from collections import Counter

from api.elasticsearch_client import CONTRACTS_INDEX, get_es_client

client = get_es_client()


def contar(nome_query):
    try:
        r = client.count(index=CONTRACTS_INDEX, body={"query": nome_query})
        return r["count"]
    except Exception as exc:
        return f"erro: {exc}"


provas = {
    "nested adjudicantes + match_phrase parsed.nome 'Municipio de'": {
        "nested": {"path": "adjudicantes.parsed", "query": {"match_phrase": {"adjudicantes.parsed.nome": "Municipio de"}}}
    },
    "nested adjudicantes + match parsed.nome 'Município'": {
        "nested": {"path": "adjudicantes", "query": {"match": {"adjudicantes.parsed.nome": "Município"}}}
    },
    "nested adjudicantes + match raw 'Câmara Municipal'": {
        "nested": {"path": "adjudicantes", "query": {"match": {"adjudicantes.raw": "Câmara Municipal"}}}
    },
    "nested adjudicantes + match raw 'Município de'": {
        "nested": {"path": "adjudicantes", "query": {"match": {"adjudicantes.raw": "Município de"}}}
    },
    "nested adjudicantes + wildcard raw '*mara Municipal*'": {
        "nested": {"path": "adjudicantes", "query": {"wildcard": {"adjudicantes.raw": {"value": "*mara Municipal*", "case_insensitive": True}}}}
    },
    "nested adjudicantes + wildcard raw '*Municipio de*'": {
        "nested": {"path": "adjudicantes", "query": {"wildcard": {"adjudicantes.raw": {"value": "*Município de*", "case_insensitive": True}}}}
    },
}
for nome, q in provas.items():
    print(f"{contar(q):>12}  {nome}")

# top adjudicantes do genero, via agregacao nested
r = client.search(
    index=CONTRACTS_INDEX,
    body={
        "size": 0,
        "aggs": {
            "adj": {
                "nested": {"path": "adjudicantes"},
                "aggs": {"nomes": {"terms": {"field": "adjudicantes.raw", "size": 15}}},
            }
        },
    },
)
print("\ntop adjudicantes (raw) no indice:")
for b in r["aggregations"]["adj"]["nomes"]["buckets"]:
    print("   ", b["doc_count"], b["key"])
