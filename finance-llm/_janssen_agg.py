import json
from pathlib import Path
from api.elasticsearch_client import get_es_client

client = get_es_client()

q = json.loads(Path(__file__).with_name("_janssen_agg_query.json").read_text(encoding="utf-8"))

resp = client.search(index="finance_contracts", body=q)
print("total contratos PT:", resp["hits"]["total"]["value"])
print("por ano:")
for b in resp["aggregations"]["anos"]["buckets"]:
    print(" ", b["key_as_string"], b["doc_count"], "€", round(b.get("valor", {}).get("value", 0), 2))
print("top CPV:")
for b in resp["aggregations"]["cpv"]["buckets"]:
    nome = b["nome"]["buckets"][0]["key"] if b["nome"]["buckets"] else ""
    print(" ", b["key"], nome[:60], b["doc_count"], "€", round(b["total"]["value"], 2))
print("top adjudicantes (clientes públicos):")
for b in resp["aggregations"]["clientes"]["adjudicantes"]["nifs"]["buckets"]:
    nome = b["nomes"]["buckets"][0]["key"] if b["nomes"]["buckets"] else ""
    print(" ", b["key"], nome[:60], b["doc_count"], "€", round(b["total"]["value"], 2))
print("top lotes/descrições:")
for b in resp["aggregations"]["top_lotes"]["desc"]["buckets"]:
    print(" ", b["key"][:80], "€", round(b["_sum"]["value"], 2), "x", b["doc_count"])

with open(Path(__file__).with_name("_janssen_agg_result.json"), "w", encoding="utf-8") as f:
    json.dump(resp["aggregations"], f, ensure_ascii=False, indent=2)
