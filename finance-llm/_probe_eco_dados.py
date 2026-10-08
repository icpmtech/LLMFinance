"""Reconhecimento dos dados de contratação pública ecológica no índice `contratos`."""
import json
import sys

sys.path.insert(0, "c:/LLMFinance/finance-llm")

from api.elasticsearch_client import get_es_client  # noqa: E402

es = get_es_client(request_timeout=180)

props = list(es.indices.get_mapping(index="contratos").values())[0]["mappings"]["properties"]
print("campos com 'col'/'crit'/'ambient' no nome:")
for name, spec in props.items():
    low = name.lower()
    if "col" in low or "crit" in low or "ambient" in low or "verde" in low:
        print("   ", name, "->", json.dumps(spec, ensure_ascii=False)[:200])

resp = es.search(
    index="contratos",
    body={
        "size": 0,
        "track_total_hits": True,
        "aggs": {
            "eco": {"terms": {"field": "ContratEcologico.keyword", "size": 15, "missing": "(vazio)"}},
            "crit": {"terms": {"field": "CritMateriais.keyword", "size": 20, "missing": "(vazio)"}},
            "eco_por_ano": {
                "terms": {"field": "Ano", "size": 20, "order": {"_key": "desc"}},
                "aggs": {"eco": {"terms": {"field": "ContratEcologico.keyword", "size": 5, "missing": "(vazio)"}}},
            },
        },
    },
)
agg = resp["aggregations"]
print("\nContratEcologico:", [(b["key"], b["doc_count"]) for b in agg["eco"]["buckets"]])
print("CritMateriais:", [(b["key"], b["doc_count"]) for b in agg["crit"]["buckets"]])
print("\npor ano (Sim):")
for b in agg["eco_por_ano"]["buckets"][:8]:
    sim = next((x["doc_count"] for x in b["eco"]["buckets"] if x["key"] == "Sim"), 0)
    nao = next((x["doc_count"] for x in b["eco"]["buckets"] if x["key"] == "Não"), 0)
    print(f"   {b['key']}: total={b['doc_count']} sim={sim} nao={nao}")

sample = es.search(
    index="contratos",
    body={
        "size": 2,
        "query": {"term": {"ContratEcologico.keyword": "Sim"}},
        "_source": ["idcontrato", "objectoContrato", "Ano", "precoContratual", "ContratEcologico", "CritMateriais", "NUTs", "tipoprocedimento", "tipoContrato"],
    },
)
print("\nexemplos com ContratEcologico=Sim:")
for hit in sample["hits"]["hits"]:
    src = hit["_source"]
    print("  ", src.get("idcontrato"), "|", src.get("Ano"), "|", str(src.get("precoContratual"))[:12],
          "| CritMateriais:", src.get("CritMateriais"), "|", str(src.get("objectoContrato"))[:90])
