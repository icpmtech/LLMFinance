import json, statistics, sys
from transformers import AutoTokenizer
tok = AutoTokenizer.from_pretrained("Qwen/Qwen2.5-0.5B-Instruct")
rows = [json.loads(l) for l in open("/app/data/final/iqos_contratos_v2.jsonl", encoding="utf-8") if l.strip()]
def n(r): return len(tok(r["input"], add_special_tokens=False)["input_ids"]) + len(tok(r["output"], add_special_tokens=False)["input_ids"])
lens = [n(r) for r in rows]
print("pares", len(rows))
print("tokens/par: min", min(lens), "mediana", int(statistics.median(lens)), "media", int(statistics.mean(lens)), "max", max(lens))
for p in (50, 75, 90, 95):
    print(f"  p{p}", int(sorted(lens)[int(len(lens)*p/100)-1]))
from collections import Counter
por = Counter(r["instruction"][:20] for r in rows)
print(por.most_common())
