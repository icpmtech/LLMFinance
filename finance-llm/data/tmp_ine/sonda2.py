"""Sonda 2: municípios em localExecucao e forma dos adjudicantes."""
import json
from collections import Counter

from api.elasticsearch_client import CONTRACTS_INDEX, get_es_client

client = get_es_client()

# 1) um contrato completo, para ver a forma dos adjudicantes
h = client.search(
    index=CONTRACTS_INDEX,
    body={"size": 1, "_source": ["idcontrato", "objectoContrato", "precoContratual", "localExecucao", "adjudicantes", "dataCelebracaoContrato"]},
)
print("exemplo de contrato:")
print(json.dumps(h["hits"]["hits"][0]["_source"], ensure_ascii=False, indent=1)[:1800])

# 2) municipios distintos no 3.o componente de localExecucao (amostra grande)
r = client.search(
    index=CONTRACTS_INDEX,
    body={"size": 0, "aggs": {"loc": {"terms": {"field": "localExecucao", "size": 3000}}}},
)
bucket = r["aggregations"]["loc"]["buckets"]
print("\ntotal de valores distintos de localExecucao:", len(bucket))
mun = set()
sem_mun = 0
for b in bucket:
    partes = [p.strip() for p in str(b["key"]).split(",")]
    if len(partes) >= 3:
        mun.add(partes[2])
    else:
        sem_mun += 1
print("municipios distintos extraidos:", len(mun))
print("valores sem 3.o componente (ex.: 'Portugal', 'Portugal, Portalegre'):", sem_mun)
print("exemplos:", sorted(mun)[:12])

# 3) contratos SEM municipio (so 'Portugal')
r2 = client.count(index=CONTRACTS_INDEX, body={"query": {"term": {"localExecucao": "Portugal"}}})
print("\ncontratos com localExecucao = 'Portugal':", r2["count"])
