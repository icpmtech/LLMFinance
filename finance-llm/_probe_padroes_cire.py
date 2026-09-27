"""Sonda: estrutura dos intervenientes de um processo do CIRE."""
from __future__ import annotations

import sys

sys.path.insert(0, r"c:\LLMFinance\finance-llm")

from api.elasticsearch_client import CIRE_INDEX, get_es_client  # noqa: E402

es = get_es_client()
resp = es.search(
    index=CIRE_INDEX,
    body={
        "size": 4,
        "query": {"bool": {"filter": [{"exists": {"field": "nifs"}}]}},
        "_source": ["nifs", "insolvente", "especie", "intervenientes", "processo_numero"],
    },
)
for hit in resp["hits"]["hits"]:
    src = hit["_source"]
    print("nifs:", src.get("nifs"), "| insolvente:", src.get("insolvente"), "| proc:", src.get("processo_numero"))
    for entry in (src.get("intervenientes") or [])[:8]:
        print("   ", entry.get("papel"), "|", entry.get("nif"), "|", str(entry.get("nome"))[:60])
    print("---")
