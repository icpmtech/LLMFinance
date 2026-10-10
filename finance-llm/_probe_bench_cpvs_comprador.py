"""Sonda: porque é que `cpvs_here` sai 0 (cardinalidade dentro do ramo do comprador)."""
from __future__ import annotations

import json
import os

os.environ.setdefault("ELASTICSEARCH_URL", "http://127.0.0.1:9200")

from api import benchmark_countries as bc  # noqa: E402
from api.elasticsearch_client import get_es_client  # noqa: E402

es = get_es_client(request_timeout=60)
NIF_COMPRADOR = "508142156"
NIF_FORNECEDOR = "500697370"

entidade = bc.entity_filter("pt", bc.BUYER, nif=NIF_COMPRADOR)
fornecedor = bc.party_in_filter("pt", bc.SUPPLIER, [NIF_FORNECEDOR])
spec_cpv = bc.dialect("pt")["cpv"]

corpo = {
    "size": 0,
    "query": {"bool": {"filter": [entidade, fornecedor]}},
    "aggs": {
        "fornecedores": {
            "nested": {"path": "adjudicatarios.parsed"},
            "aggs": {
                "top": {
                    "terms": {"field": "adjudicatarios.parsed.nif", "size": 2},
                    "aggs": {
                        "documento": {
                            "reverse_nested": {},
                            "aggs": {
                                "limpos": {
                                    "filter": {"bool": {"filter": bc.value_filters("pt")}},
                                    "aggs": {
                                        "pc": {"percentiles": {"field": "precoContratual", "percents": [50]}},
                                    },
                                }
                            },
                        },
                        "cpvs": {
                            "nested": {"path": spec_cpv["nested"]},
                            "aggs": {"distintos": {"cardinality": {"field": spec_cpv["code"]}}},
                        },
                    },
                }
            },
        }
    },
}

resposta = es.search(index="contratos", body=corpo)
for bucket in resposta["aggregations"]["fornecedores"]["top"]["buckets"]:
    print(
        bucket["key"],
        "doc_count(nested)=", bucket["doc_count"],
        "| pc=", bucket["documento"]["limpos"]["pc"]["values"].get("50.0"),
        "| cpvs=", bucket["cpvs"]["distintos"]["value"],
    )

# Segunda variante: sem o ramo `documento`, para ver se interfere.
corpo["aggs"]["fornecedores"]["aggs"]["top"]["aggs"] = {
    "cpvs": {"nested": {"path": spec_cpv["nested"]}, "aggs": {"distintos": {"cardinality": {"field": spec_cpv["code"]}}}}
}
resposta2 = es.search(index="contratos", body=corpo)
for bucket in resposta2["aggregations"]["fornecedores"]["top"]["buckets"]:
    print("sem documento ->", bucket["key"], "cpvs=", bucket["cpvs"]["distintos"]["value"])
