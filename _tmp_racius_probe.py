import json
from collections import Counter
from elasticsearch import Elasticsearch

es = Elasticsearch(["http://127.0.0.1:9200"], request_timeout=30)

r = es.search(index="finance_racius", size=200, query={"match_all": {}})
docs = [h["_source"] for h in r["hits"]["hits"]]
print("total", len(docs))

# exemplos de concelhos suspeitos
for name in ["Sé", "Oeiras", "Alcobaça", "Santa Cruz", "Vizela", "Oliveira de Azeméis", "Porto", "Oeiras e São Julião Barra"]:
    ex = [d for d in docs if d.get("concelho") == name]
    print(f"\n== {name}: {len(ex)}")
    for d in ex[:2]:
        print(json.dumps({k: d.get(k) for k in ("nome", "url", "morada", "concelho", "distrito")}, ensure_ascii=False))

print("\n== distritos ==")
for k, v in Counter(d.get("distrito") for d in docs).most_common():
    print(f"{k}: {v}")
