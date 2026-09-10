import sys, json
sys.path.insert(0, r'c:\LLMFinance\finance-llm')
from api.elasticsearch_client import get_es_client

c = get_es_client()
if not c:
    print('ES client not available')
    sys.exit(1)

r = c.search(index='finance_news', body={'query': {'term': {'ticker': 'AAPL'}}, 'size': 3})
for h in r['hits']['hits']:
    s = h['_source']
    print('sentiment:', s.get('sentiment'))
    print('language:', s.get('language'))
    print('topics:', s.get('topics'))
    print('entities:', s.get('entities'))
    print('translated_title:', s.get('translated_title'))
    print('summary_pt:', s.get('summary_pt'))
    print('---')
