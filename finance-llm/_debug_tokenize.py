import json
from pathlib import Path
from inference.generate_mistral import InferenceModel

m = InferenceModel()
path = Path("data/final/contratos_train.jsonl")
with path.open("r", encoding="utf-8") as fh:
    doc = json.loads(fh.readline())

text = (
    f"### Instrução:\n{doc['instruction']}\n\n"
    f"### Entrada:\n{doc['input']}\n\n"
    f"### Resposta:\n{doc['output']}"
)
print(text[:500])
ids = m.tokenizer.encode(text, add_special_tokens=False)
print("len ids", len(ids))
ids_bos = m.tokenizer.encode(text, add_special_tokens=True)
print("len ids with special", len(ids_bos))
print("first 10 ids with special:", ids_bos[:10])
print("decoded first 30:", m.tokenizer.decode(ids_bos[:30]))
print("decoded last 30:", m.tokenizer.decode(ids_bos[-30:]))
