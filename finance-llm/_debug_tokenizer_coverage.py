import json
from pathlib import Path
from transformers import PreTrainedTokenizerFast
from collections import Counter

tok = PreTrainedTokenizerFast.from_pretrained("model/mistral-finance/final")
print("vocab", len(tok))

path = Path("data/final/contratos_train.jsonl")
c = Counter()
total = 0
with path.open("r", encoding="utf-8") as fh:
    for i, line in enumerate(fh):
        if i >= 100000:
            break
        doc = json.loads(line)
        text = (
            f"### Instrução:\n{doc['instruction']}\n\n"
            f"### Entrada:\n{doc['input']}\n\n"
            f"### Resposta:\n{doc['output']}"
        )
        for t in tok.tokenize(text):
            c[t] += 1
            total += 1

print("total tokens", total)
print("unique tokens in sample", len(c))
unk = c.get(tok.unk_token, 0)
print("unk count", unk, "ratio", unk / total)
print("top 20 contract tokens", c.most_common(20))
print("sample tokenization:", tok.tokenize("aquisição de serviços de consultoria para Basevo"))
