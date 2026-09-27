"""Sonda: tipos de cargo (role) e origem (role_org) no índice de pessoas."""
from __future__ import annotations

import sys

sys.path.insert(0, r"c:\LLMFinance\finance-llm")

from api.elasticsearch_client import PEOPLE_INDEX, get_es_client  # noqa: E402

es = get_es_client()
body = {
    "size": 0,
    "aggs": {
        "r": {
            "nested": {"path": "roles"},
            "aggs": {
                "roles": {
                    "terms": {"field": "roles.role", "size": 40},
                    "aggs": {"org": {"terms": {"field": "roles.role_org", "size": 5}}},
                }
            },
        }
    },
}
resp = es.search(index=PEOPLE_INDEX, body=body)
for bucket in resp["aggregations"]["r"]["roles"]["buckets"]:
    orgs = ", ".join(f"{o['key']}:{o['doc_count']}" for o in bucket["org"]["buckets"])
    print(f"{str(bucket['key'])[:44]:46s} {bucket['doc_count']:>9,}  [{orgs}]")
