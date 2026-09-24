"""Lista as regiões presentes no índice GLEIF sem centroide conhecido no frontend."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from elasticsearch import Elasticsearch  # noqa: E402

WORLD_TS = Path(__file__).resolve().parent / "chat-ui" / "src" / "components" / "geo" / "world.ts"

client = Elasticsearch(["http://127.0.0.1:9200"], request_timeout=60)
response = client.search(
    index="finance_gleif_lei",
    size=0,
    body={"aggs": {"regions": {"terms": {"field": "region", "size": 500}}}},
)
buckets = response["aggregations"]["regions"]["buckets"]
codes = [b["key"] for b in buckets if b["key"]]
print(f"{len(codes)} regiões distintas")

source = WORLD_TS.read_text(encoding="utf-8")
known = set(re.findall(r'"([A-Z]{1,2}-[A-Z0-9]{1,3})":\s*\[', source))

missing = [(b["key"], b["doc_count"]) for b in buckets if b["key"] and b["key"] not in known]
missing.sort(key=lambda item: -item[1])
print(f"\n{len(missing)} regiões sem centroide (as restantes caem no centroide do país):")
for code, count in missing:
    print(f'  "{code}": [{count:,}]'.replace(",", ""))
print("\nJSON:", json.dumps({code: count for code, count in missing}, ensure_ascii=False))
