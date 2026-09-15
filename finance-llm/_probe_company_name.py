import json, sys
sys.path.insert(0, 'c:\\LLMFinance\\finance-llm')
from api.elasticsearch_client import get_es_client, CONTRACTS_INDEX

es = get_es_client()
body = {
    "size": 0,
    "query": {"bool": {"should": [
        {"nested": {"path": "adjudicantes.parsed", "query": {"term": {"adjudicantes.parsed.nif": "519242335"}}}},
        {"nested": {"path": "adjudicatarios.parsed", "query": {"term": {"adjudicatarios.parsed.nif": "519242335"}}}}
    ], "minimum_should_match": 1}},
    "aggs": {
        "adjudicantes": {"nested": {"path": "adjudicantes.parsed"}, "aggs": {"filtered": {"filter": {"term": {"adjudicantes.parsed.nif": "519242335"}}, "aggs": {"name": {"top_hits": {"size": 1, "_source": ["adjudicantes.parsed.nome"]}}}}}}},
        "adjudicatarios": {"nested": {"path": "adjudicatarios.parsed"}, "aggs": {"filtered": {"filter": {"term": {"adjudicatarios.parsed.nif": "519242335"}}, "aggs": {"name": {"top_hits": {"size": 1, "_source": ["adjudicatarios.parsed.nome"]}}}}}}},
    }
}
resp = es.search(index=CONTRACTS_INDEX, body=body)
for key in ['adjudicantes', 'adjudicatarios']:
    hit = resp['aggregations'][key]['filtered'].get('name', {}).get('hits', {}).get('hits', [None])[0]
    print(key, hit.get('_source') if hit else None)
