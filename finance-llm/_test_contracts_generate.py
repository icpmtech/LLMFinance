"""Teste rápido de inferência do modelo fine-tuned nos contratos."""
from pathlib import Path
import argparse
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))



def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model_dir", type=str, default="model/mistral-finance/final")
    parser.add_argument("--prompt", type=str, default="Descreve o contrato cujo objeto inclui 'aquisição de serviços de consultoria'.")
    parser.add_argument("--max_new_tokens", type=int, default=80)
    parser.add_argument("--temperature", type=float, default=0.8)
    args = parser.parse_args()

    model_dir = ROOT / args.model_dir
    print(f"[LOAD] {model_dir}")
    from transformers import PreTrainedTokenizerFast, MistralForCausalLM
    import torch

    tokenizer = PreTrainedTokenizerFast.from_pretrained(model_dir)
    model = MistralForCausalLM.from_pretrained(model_dir)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    model.config.pad_token_id = tokenizer.pad_token_id
    device = torch.device("cpu")
    model.to(device)
    model.eval()

    print(f"[PROMPT] {args.prompt}")
    encoded = tokenizer(f"{tokenizer.bos_token}{args.prompt}", return_tensors="pt")
    input_len = encoded["input_ids"].shape[-1]
    with torch.no_grad():
        out = model.generate(
            **encoded.to(device),
            max_new_tokens=args.max_new_tokens,
            do_sample=args.temperature > 0,
            temperature=args.temperature if args.temperature > 0 else 1.0,
            top_k=50,
            top_p=0.95,
            pad_token_id=tokenizer.pad_token_id,
            eos_token_id=tokenizer.eos_token_id,
            bos_token_id=tokenizer.bos_token_id,
        )
    decoded = tokenizer.decode(out[0][input_len:], skip_special_tokens=True)
    print(f"[OUTPUT] {decoded.strip()}")


if __name__ == "__main__":
    main()
