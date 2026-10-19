import json
from elasticsearch import Elasticsearch
es = Elasticsearch(["http://127.0.0.1:9200"], request_timeout=30)
r = es.search(index="finance_racius", size=3, query={"term": {"concelho": "Só"}})
r = es.search(index="finance_racius", size=3, query={"match": {"nome": "Clivita"}})
for h in r["hits"]["hits"]:
    print(json.dumps(h["_source"], ensure_ascii=False, indent=2))
