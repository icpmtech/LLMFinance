"""Treina o modelo com dados processados usando um loop PyTorch manual."""
from pathlib import Path
from transformers import GPT2LMHeadModel, GPT2TokenizerFast
import json
import torch
import torch.nn.functional as F
from torch.utils.data import DataLoader, TensorDataset

ROOT = Path(__file__).resolve().parents[1]
FINAL_DIR = ROOT / "data" / "final"
MODEL_DIR = ROOT / "model" / "gpt2-finance"


def load_jsonl(path: Path) -> list[str]:
    """Carrega linhas de um ficheiro JSONL."""
    with path.open("r", encoding="utf-8") as f:
        return [json.loads(line)["text"] for line in f]


def train_model(
    epochs: int = 1,
    batch_size: int = 8,
    max_length: int = 128,
    learning_rate: float = 5e-5,
    max_samples: int | None = None,
    save_checkpoints: bool = True,
):
    tokenizer = GPT2TokenizerFast.from_pretrained(MODEL_DIR)
    model = GPT2LMHeadModel.from_pretrained(MODEL_DIR)

    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    model.config.pad_token_id = tokenizer.pad_token_id
    # Evita aviso `loss_type=None` nas versões recentes do transformers.
    model.config.loss_type = "ForCausalLMLoss"

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model.to(device)

    texts = load_jsonl(FINAL_DIR / "train.jsonl")
    if max_samples:
        texts = texts[:max_samples]

    encodings = tokenizer(
        texts,
        truncation=True,
        padding="max_length",
        max_length=max_length,
        return_tensors="pt",
    )
    input_ids = encodings["input_ids"]
    attention_mask = encodings["attention_mask"]
    labels = input_ids.clone()
    labels[attention_mask == 0] = -100

    dataset = TensorDataset(input_ids, attention_mask, labels)
    loader = DataLoader(dataset, batch_size=batch_size, shuffle=True)

    optimizer = torch.optim.AdamW(model.parameters(), lr=learning_rate)
    model.train()

    total_steps = len(loader) * epochs
    step = 0
    for epoch in range(epochs):
        for batch in loader:
            step += 1
            b_input, b_mask, b_labels = (x.to(device) for x in batch)
            optimizer.zero_grad()
            outputs = model(input_ids=b_input, attention_mask=b_mask, labels=b_labels)
            loss = outputs.loss
            loss.backward()
            optimizer.step()

            if step % 20 == 0:
                print(f"step {step}/{total_steps} | epoch {epoch+1}/{epochs} | loss {loss.item():.4f}")

            if save_checkpoints and step % 200 == 0:
                ckpt_dir = MODEL_DIR / "checkpoints" / f"step-{step}"
                ckpt_dir.mkdir(parents=True, exist_ok=True)
                model.save_pretrained(ckpt_dir)

    final_dir = MODEL_DIR / "final"
    final_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(final_dir)
    tokenizer.save_pretrained(final_dir)
    print("Modelo guardado em", final_dir)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Treina o modelo GPT-2 Finance-LLM")
    parser.add_argument("--epochs", type=int, default=1)
    parser.add_argument("--batch_size", type=int, default=8)
    parser.add_argument("--max_length", type=int, default=128)
    parser.add_argument("--learning_rate", type=float, default=5e-5)
    parser.add_argument("--max_samples", type=int, default=None)
    parser.add_argument("--save_checkpoints", action="store_true", default=True)
    args = parser.parse_args()

    train_model(
        epochs=args.epochs,
        batch_size=args.batch_size,
        max_length=args.max_length,
        learning_rate=args.learning_rate,
        max_samples=args.max_samples,
        save_checkpoints=args.save_checkpoints,
    )
