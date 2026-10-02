"""Debug CAE lookup inside search_companies."""
import json
from api.elasticsearch_client import get_es_client, ENTITIES_INDEX, search_companies

es = get_es_client()
nif = "500189412"

# 1) direct term query on nif
r = es.search(
    index=ENTITIES_INDEX,
    body={
        "size": 1,
        "query": {"term": {"nif": nif}},
        "_source": ["nif", "cae_principal", "caes_secundarios"],
    },
)
print("direct term nif:", json.dumps(r["hits"]["hits"], ensure_ascii=False, indent=2))

# 2) terms query
r2 = es.search(
    index=ENTITIES_INDEX,
    body={
        "size": 1,
        "query": {"terms": {"nif.keyword": [nif]}},
        "_source": ["nif", "cae_principal", "caes_secundarios"],
    },
)
print("terms nif.keyword:", json.dumps(r2["hits"]["hits"], ensure_ascii=False, indent=2))

# 3) full search_companies for Janssen
res = search_companies(q="janssen", size=3, include_cae=True)
for it in res.get("items", []):
    print("item", it.get("nif"), "cae", it.get("cae_principal"))
