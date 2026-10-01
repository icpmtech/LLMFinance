import sys, json
sys.path.insert(0, r'C:\LLMFinance\finance-llm')
from api.elasticsearch_client import get_es_client, PEOPLE_INDEX
es = get_es_client()
r = es.search(
    index=PEOPLE_INDEX,
    body={
        'query': {'bool': {'should': [{'prefix': {'nif': 'PT-AR-BID'}}, {'prefix': {'nif': 'PT-WIKI-PT'}}]}},
        'size': 3,
        '_source': ['nif','name','source','sources','roles','photo_url','photo_path','summary','party','metadata']
    }
)
for h in r['hits']['hits']:
    print(json.dumps(h['_source'], ensure_ascii=False, indent=2))
