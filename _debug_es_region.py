from elasticsearch import Elasticsearch
es = Elasticsearch(["http://127.0.0.1:9200"], request_timeout=30)
query = {
    "query": {"bool": {"filter": [{"term": {"NUTs": "PT11A - Área Metropolitana do Porto"}}]}},
    "size": 0,
    "aggs": {
        "rels": {
            "nested": {"path": "adjudicantes.parsed"},
            "aggs": {"nifs": {"terms": {"field": "adjudicantes.parsed.nif", "size": 5}}},
        }
    },
}
resp = es.search(index="finance_contracts", body=query)
print("hits:", resp["hits"]["total"])
print("buckets:", resp["aggregations"]["rels"]["nifs"]["buckets"][:5])
