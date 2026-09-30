"""Inspeciona os itens do Iberinform no índice da recolha (`finance_scraped`).

Uso:
    python _probe_iberinform_index.py [termo]
"""
from __future__ import annotations

import json
import sys

from api.elasticsearch_client import get_es_client, SCRAPED_INDEX


def main() -> int:
    cliente = get_es_client()
    if not cliente:
        print("Elasticsearch indisponível")
        return 1

    res = cliente.search(
        index=SCRAPED_INDEX,
        body={
            "size": 0,
            "query": {"prefix": {"source_id": "empresas-"}},
            "aggs": {"fontes": {"terms": {"field": "source_id", "size": 30}}},
        },
    )
    fontes = res["aggregations"]["fontes"]["buckets"]
    print("fontes iberinform:", [(b["key"], b["doc_count"]) for b in fontes])

    res2 = cliente.search(
        index=SCRAPED_INDEX,
        body={"size": 2, "query": {"prefix": {"source_id": "empresas-"}}},
    )
    for hit in res2["hits"]["hits"]:
        doc = hit["_source"]
        print("\n--- doc ---")
        print(json.dumps({k: (v[:120] + "…" if isinstance(v, str) and len(v) > 120 else v) for k, v in doc.items()}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
