import json
from elasticsearch import Elasticsearch
es = Elasticsearch(["http://127.0.0.1:9200"], request_timeout=30)
r = es.search(index="finance_racius", size=200, query={"match_all": {}}, _source=True)
docs = [h["_source"] for h in r["hits"]["hits"]]
match_ficha = match_loc = other = 0
examples = []
for d in docs:
    ficha = d.get("ficha") or {}
    items = list(ficha.items())
    pair = None
    for i, (k, v) in enumerate(items):
        if k.strip().lower() == "morada" and i + 1 < len(items):
            pair = items[i + 1]
            break
    loc = (d.get("localizacao") or "").split(",")
    loc_pair = (loc[0].strip(), loc[-1].strip()) if len(loc) > 1 else None
    stored = (d.get("concelho"), d.get("distrito"))
    if pair and (pair[0], pair[1]) == stored:
        match_ficha += 1
    elif loc_pair and loc_pair == stored:
        match_loc += 1
    else:
        other += 1
        if len(examples) < 12:
            examples.append((d.get("nome"), stored, pair, loc_pair, d.get("localizacao")))
print("total", len(docs), "ficha", match_ficha, "localizacao", match_loc, "outros", other)
for e in examples:
    print(e)
