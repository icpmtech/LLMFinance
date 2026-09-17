"""Sonda: etiqueta dos buckets CPV e tempos das consultas derivadas."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api.elasticsearch_client import get_es_client, search_companies  # noqa: E402


def main() -> int:
    es = get_es_client()
    if not es:
        print("ES indisponível")
        return 1

    print("--- variante A: _source cpv.description ---")
    body = {
        "size": 0,
        "aggs": {
            "nested_agg": {
                "nested": {"path": "cpv"},
                "aggs": {
                    "values": {
                        "terms": {"field": "cpv.code", "size": 3},
                        "aggs": {
                            "a": {"top_hits": {"size": 1, "_source": ["cpv.description"]}},
                            "b": {"top_hits": {"size": 1, "_source": ["cpv"]}},
                            "c": {"top_hits": {"size": 1, "_source": False, "docvalue_fields": ["cpv.code"]}},
                        },
                    }
                },
            }
        },
    }
    resp = es.search(index="contratos", body=body)
    for bucket in resp["aggregations"]["nested_agg"]["values"]["buckets"]:
        key = bucket["key"]
        a = bucket["a"]["hits"]["hits"][0]
        b = bucket["b"]["hits"]["hits"][0]
        print(f"  cpv={key} doc_count={bucket['doc_count']}")
        print("    a _source:", json.dumps(a.get("_source"), ensure_ascii=False)[:300])
        print("    a _nested:", json.dumps(a.get("_nested"), ensure_ascii=False)[:200])
        print("    b _source:", json.dumps(b.get("_source"), ensure_ascii=False)[:300])

    print("\n--- tempos search_companies ---")
    for role in ("all", "adjudicante"):
        started = time.time()
        res = search_companies(role=role, size=3, es=es)
        print(f"  role={role:12s} {(time.time() - started) * 1000:7.0f}ms total={res.get('total')} erro={res.get('error')}")
    started = time.time()
    res = search_companies(q="EDP", role="all", size=3, es=es)
    print(f"  q=EDP        {(time.time() - started) * 1000:7.0f}ms total={res.get('total')}")

    print("\n--- agregados ---")
    for index, field in (("contratos", "NUTs"), ("finance_news", "topics"), ("finance_prices", "ticker")):
        started = time.time()
        resp = es.search(index=index, body={"size": 0, "aggs": {"values": {"terms": {"field": field, "size": 500}}}})
        buckets = resp["aggregations"]["values"]["buckets"]
        print(f"  {index}.{field:10s} {(time.time() - started) * 1000:7.0f}ms buckets={len(buckets)}")

    started = time.time()
    resp = es.search(index="contratos", body={"size": 0, "aggs": {"values": {"terms": {"field": "cpv.code", "size": 2000}, "aggs": {"soma": {"sum": {"field": "precoContratual"}}}}}})
    print(f"  aggs cpv.code (sem nested) {(time.time() - started) * 1000:7.0f}ms buckets={len(resp['aggregations']['values']['buckets'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
