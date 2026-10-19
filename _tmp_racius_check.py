import io, json
rows = [json.loads(line) for line in io.open(r'C:\LLMFinance\_tmp_racius_porto_test.jsonl', encoding='utf-8')]
for r in rows:
    print(f"{r.get('nif',''):>10} | {r.get('nome','')[:42]:42} | {r.get('concelho')} / {r.get('distrito')} | loc={r.get('localizacao')}")
from collections import Counter
print(Counter(r.get('distrito') for r in rows))
print('sem distrito:', sum(1 for r in rows if not r.get('distrito')))
