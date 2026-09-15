from pathlib import Path
from transformers import PreTrainedTokenizerFast

path = Path("model/mistral-contracts")
tok = PreTrainedTokenizerFast.from_pretrained(path)
print("vocab", len(tok))
print("bos", tok.bos_token, tok.bos_token_id)
print("eos", tok.eos_token, tok.eos_token_id)
print("pad", tok.pad_token, tok.pad_token_id)
print("unk", tok.unk_token, tok.unk_token_id)

samples = [
    "aquisição de serviços de consultoria para Basevo",
    "adjudicante: Câmara Municipal de Lisboa",
    "preço contratual: 125000,00 EUR",
    "objeto do contrato: empreitada de construção de estrada",
]
for s in samples:
    toks = tok.tokenize(s)
    print(f"{s!r} -> {toks[:12]}... ({len(toks)} tokens)")
