"""Mede o que um fine-tune do Soup mudou, num conjunto held-out.

O `soup train` diz a perda do treino, e isso não responde à pergunta que
interessa: o modelo aprendeu, ou decorou? Este script compara o modelo de partida
com o adaptador treinado nos pares que **nunca** entraram no treino.

    docker run --rm -v <repo>:/workspace -w /workspace --entrypoint python \
        iq-os-soup:latest training/soup/eval_holdout.py \
        --pairs ./data/final/subvencoes_holdout.jsonl \
        --base ./model/mistral-finance/final \
        --adapter ./model/soup-subvencoes

Para gerar os pares held-out: exporte com um `--max-records` maior do que o que
usou no treino e fique com as linhas que sobraram (com `--seed`, a semente dá a
mesma ordem, por isso as linhas a mais são estáveis entre corridas).

O texto de cada par é montado com o mesmo molde do treino; a perda e a exactidão
são medidas **só nos tokens da resposta** (o prompt fica mascarado, como no
`train_on_responses_only`).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

PROMPT_TEMPLATE = "### Instrução:\n{instruction}\n\n{input}\n\n### Resposta:\n"


def render(row: dict) -> str:
    return PROMPT_TEMPLATE.format(instruction=row.get("instruction", ""), input=row.get("input", ""))


def score(model, tokenizer, pairs) -> dict:
    total_loss, total_tokens, hits = 0.0, 0, 0
    model.eval()
    with torch.no_grad():
        for row in pairs:
            prompt_ids = tokenizer(render(row), add_special_tokens=False)["input_ids"]
            target_ids = tokenizer(row["output"], add_special_tokens=False)["input_ids"]
            if not target_ids:
                continue
            ids = torch.tensor([prompt_ids + target_ids])
            labels = torch.tensor([[-100] * len(prompt_ids) + target_ids])
            total_loss += model(input_ids=ids, labels=labels).loss.item() * len(target_ids)
            total_tokens += len(target_ids)
            logits = model(input_ids=ids).logits[0, len(prompt_ids) - 1 : -1]
            hits += int((logits.argmax(-1) == torch.tensor(target_ids)).sum())
    mean_loss = total_loss / total_tokens
    return {
        "perda_por_token": round(mean_loss, 4),
        "perplexidade": round(float(torch.exp(torch.tensor(mean_loss))), 1),
        "exactidao_token": round(hits / total_tokens, 4),
        "tokens": total_tokens,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Compara base e adaptador num conjunto held-out.")
    parser.add_argument("--pairs", type=Path, required=True, help="JSONL held-out (formato Alpaca)")
    parser.add_argument("--base", default="./model/mistral-finance/final", help="Modelo de partida")
    parser.add_argument("--adapter", help="Adaptador LoRA treinado (sem ele, mede só o base)")
    args = parser.parse_args()

    pairs = [json.loads(line) for line in args.pairs.open(encoding="utf-8") if line.strip()]
    print(f"held-out: {len(pairs)} pares de {args.pairs}")

    tokenizer = AutoTokenizer.from_pretrained(args.base)
    model = AutoModelForCausalLM.from_pretrained(args.base, dtype=torch.float32)
    print("BASE     ", score(model, tokenizer, pairs))

    if args.adapter:
        from peft import PeftModel

        treinado = PeftModel.from_pretrained(model, args.adapter)
        print("TREINADO ", score(treinado, tokenizer, pairs))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
