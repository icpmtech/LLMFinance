"""Sonda rápida: percentis e top_hits dentro de nested."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api.elasticsearch_client import get_es_client  # noqa: E402

es = get_es_client(60)
escopo = {
    "bool": {
        "filter": [
            {"nested": {"path": "cpv", "query": {"wildcard": {"cpv.code": "336*"}}}},
            {"range": {"Ano": {"gte": 2025, "lte": 2025}}},
        ]
    }
}
r = es.search(
    index="contratos",
    body={"size": 0, "query": escopo, "aggs": {"p": {"percentiles": {"field": "precoContratual", "percents": [50, 95, 99], "keyed": True}}}},
)
print("percentis:", json.dumps(r["aggregations"]["p"])[:400])

r2 = es.search(
    index="contratos",
    body={
        "size": 0,
        "query": escopo,
        "aggs": {
            "f": {
                "nested": {"path": "adjudicatarios.parsed"},
                "aggs": {
                    "por": {
                        "terms": {"field": "adjudicatarios.parsed.nif", "size": 2},
                        "aggs": {
                            "documento": {"reverse_nested": {}, "aggs": {"valor": {"sum": {"field": "precoContratual"}}}},
                            "nome_a": {"top_hits": {"size": 1}},
                            "nome_b": {"top_hits": {"size": 1, "_source": ["nif", "nome"]}},
                            "nome_c": {"top_hits": {"size": 1, "_source": ["adjudicatarios"]}},
                        },
                    }
                },
            }
        },
    },
)
balde = r2["aggregations"]["f"]["por"]["buckets"][0]
for chave in ("nome_a", "nome_b", "nome_c"):
    fonte = balde[chave]["hits"]["hits"][0]["_source"]
    print(chave, "->", json.dumps(fonte)[:220])
print("valor do documento:", json.dumps(balde["documento"])[:160])
