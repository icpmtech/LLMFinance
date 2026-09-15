import json
from pathlib import Path
from transformers import PreTrainedTokenizerFast

tok = PreTrainedTokenizerFast.from_pretrained(Path("model/mistral-finance/final"))
path = Path("data/final/contratos_train.jsonl")
lengths = []
with path.open("r", encoding="utf-8") as fh:
    for i, line in enumerate(fh):
        if i >= 10000:
            break
        doc = json.loads(line)
        text = (
            f"### Instrução:\n{doc['instruction']}\n\n"
            f"### Entrada:\n{doc['input']}\n\n"
            f"### Resposta:\n{doc['output']}"
        )
        lengths.append(len(tok.encode(text, add_special_tokens=False)))
print("samples", len(lengths))
print("min", min(lengths), "max", max(lengths), "mean", sum(lengths)/len(lengths), "median", sorted(lengths)[len(lengths)//2])
print("p95", sorted(lengths)[int(len(lengths)*0.95)])
print("p99", sorted(lengths)[int(len(lengths)*0.99)])
print("p99.9", sorted(lengths)[int(len(lengths)*0.999)])
print(">1024", sum(1 for x in lengths if x > 1024))
print(">2048", sum(1 for x in lengths if x > 2048))
