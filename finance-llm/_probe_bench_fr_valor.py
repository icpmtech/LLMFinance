"""Probe 4: distribuição dos valores franceses (há outliers absurdos?)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api.elasticsearch_client import get_es_client

client = get_es_client(request_timeout=180)

resp = client.search(
    index="contratos_fr",
    body={
        "size": 0,
        "aggs": {
            "s": {"stats": {"field": "valor"}},
            "faixas": {
                "filters": {
                    "filters": {
                        "zero": {"range": {"valor": {"lte": 0}}},
                        "ate_1M": {"range": {"valor": {"gt": 0, "lte": 1_000_000}}},
                        "1M_100M": {"range": {"valor": {"gt": 1_000_000, "lte": 100_000_000}}},
                        "100M_1G": {"range": {"valor": {"gt": 100_000_000, "lte": 1_000_000_000}}},
                        "1G_100G": {"range": {"valor": {"gt": 1_000_000_000, "lte": 100_000_000_000}}},
                        "acima_100G": {"range": {"valor": {"gt": 100_000_000_000}}},
                    }
                }
            },
            "maiores": {"terms": {"field": "doc_id", "size": 3, "order": {"v": "desc"}}, "aggs": {"v": {"max": {"field": "valor"}}}},
        },
    },
)
aggs = resp["aggregations"]
print("stats:", {k: aggs["s"].get(k) for k in ("count", "sum", "avg", "min", "max")})
for nome, bucket in aggs["faixas"]["buckets"].items():
    print(f"  {nome:12} {bucket['doc_count']}")
resp2 = client.search(
    index="contratos_fr",
    body={"size": 3, "query": {"range": {"valor": {"gt": 1_000_000_000}}}, "_source": ["doc_id", "ano", "valor", "montant", "code_cpv", "adjudicatario_id"], "sort": [{"valor": {"order": "desc"}}]},
)
print("maiores contratos:")
for hit in resp2["hits"]["hits"]:
    print("  ", hit["_source"])
