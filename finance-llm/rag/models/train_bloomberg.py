"""Pipeline de treino/continual pre-training para o BloombergGPT-style model."""
import json
import shutil
from pathlib import Path
from typing import Optional

import torch
from torch.utils.data import Dataset
from transformers import (
    AutoConfig,
    AutoModelForCausalLM,
    AutoTokenizer,
    DataCollatorForLanguageModeling,
    Trainer,
    TrainingArguments,
)


def load_text_dataset(
    input_paths: list[Path],
    tokenizer,
    max_length: int = 512,
    overlap: int = 128,
) -> Dataset:
    """Cria um dataset de linguagem lazy a partir de ficheiros jsonl/texto.

    Evita carregar todo o texto em memória de uma só vez: lê cada ficheiro
    em pequenos blocos, tokeniza e gera chunks de tamanho fixo com overlap.
    """
    pad_id = tokenizer.pad_token_id or tokenizer.eos_token_id
    stride = max_length - overlap

    examples = []
    for path in input_paths:
        path = Path(path)
        if not path.exists():
            continue
        if path.suffix == ".jsonl":
            with path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                        text = obj.get("text", obj.get("content", ""))
                    except Exception:
                        text = line
                    if not text or len(text.strip()) < 8:
                        continue
                    tokens = tokenizer.encode(text, add_special_tokens=False, truncation=False)
                    for i in range(0, len(tokens), stride):
                        chunk = tokens[i : i + max_length]
                        if len(chunk) < 16:
                            continue
                        examples.append({"input_ids": chunk + [pad_id] * (max_length - len(chunk))})
        else:
            text = path.read_text(encoding="utf-8")
            if not text.strip():
                continue
            tokens = tokenizer.encode(text, add_special_tokens=False, truncation=False)
            for i in range(0, len(tokens), stride):
                chunk = tokens[i : i + max_length]
                if len(chunk) < 16:
                    continue
                examples.append({"input_ids": chunk + [pad_id] * (max_length - len(chunk))})

    class _TextDataset(Dataset):
        def __init__(self, data):
            self.data = data

        def __len__(self):
            return len(self.data)

        def __getitem__(self, idx):
            item = self.data[idx]
            return {k: torch.tensor(v, dtype=torch.long) for k, v in item.items()}

    return _TextDataset(examples)


def train_bloomberg_model(
    base_model_path: str,
    output_dir: Path,
    train_files: list[Path],
    validation_files: Optional[list[Path]] = None,
    epochs: int = 3,
    max_steps: int = -1,
    max_examples: Optional[int] = None,
    batch_size: int = 2,
    gradient_accumulation_steps: int = 4,
    learning_rate: float = 5e-5,
    max_length: int = 512,
    fp16: bool = False,
    bf16: bool = False,
    save_steps: int = 500,
    eval_steps: int = 500,
    logging_steps: int = 50,
    warmup_ratio: float = 0.05,
    trust_remote_code: bool = False,
):
    """Treina um modelo causal do zero ou faz continual pre-training.

    Args:
        base_model_path: checkpoint base (ex: mistral-finance/final ou gpt2).
        output_dir: pasta de saída para o modelo final e checkpoints.
        train_files: lista de ficheiros markdown/jsonl para treino.
        validation_files: lista opcional para validação.
        epochs: número de épocas.
        batch_size: batch size por device.
        gradient_accumulation_steps: acumulação de gradientes.
        learning_rate: learning rate máximo.
        max_length: tamanho máximo das sequências.
        fp16/bf16: precisão mista.
        save_steps/eval_steps/logging_steps: frequência das callbacks.
        warmup_ratio: percentagem do total de steps para warmup.
        trust_remote_code: ativar se o modelo custom precisar.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    checkpoints_dir = output_dir / "checkpoints"
    final_dir = output_dir / "final"
    if checkpoints_dir.exists():
        shutil.rmtree(checkpoints_dir, ignore_errors=True)

    tokenizer = AutoTokenizer.from_pretrained(
        base_model_path,
        trust_remote_code=trust_remote_code,
    )
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    config = AutoConfig.from_pretrained(
        base_model_path,
        trust_remote_code=trust_remote_code,
    )
    if getattr(config, "pad_token_id", None) is None:
        config.pad_token_id = tokenizer.pad_token_id

    try:
        model = AutoModelForCausalLM.from_pretrained(
            base_model_path,
            config=config,
            trust_remote_code=trust_remote_code,
            torch_dtype=torch.bfloat16 if bf16 else (torch.float16 if fp16 else torch.float32),
        )
    except Exception:
        model = AutoModelForCausalLM.from_config(config, trust_remote_code=trust_remote_code)

    train_dataset = load_text_dataset(train_files, tokenizer, max_length=max_length)
    if max_examples and len(train_dataset) > max_examples:
        train_dataset = torch.utils.data.Subset(train_dataset, range(max_examples))
    eval_dataset = None
    if validation_files:
        eval_dataset = load_text_dataset(validation_files, tokenizer, max_length=max_length)
        if max_examples and eval_dataset and len(eval_dataset) > max(100, max_examples // 10):
            eval_dataset = torch.utils.data.Subset(eval_dataset, range(max(100, max_examples // 10)))

    training_args = TrainingArguments(
        output_dir=str(checkpoints_dir),
        num_train_epochs=epochs,
        max_steps=max_steps,
        per_device_train_batch_size=batch_size,
        per_device_eval_batch_size=batch_size,
        gradient_accumulation_steps=gradient_accumulation_steps,
        learning_rate=learning_rate,
        warmup_steps=int(warmup_ratio * max_steps) if max_steps > 0 else int(warmup_ratio * 1000),
        fp16=fp16,
        bf16=bf16,
        logging_steps=logging_steps,
        save_steps=save_steps,
        eval_steps=eval_steps,
        eval_strategy="steps" if eval_dataset else "no",
        save_total_limit=3,
        load_best_model_at_end=bool(eval_dataset),
        report_to="none",
        remove_unused_columns=False,
    )

    data_collator = DataCollatorForLanguageModeling(
        tokenizer=tokenizer,
        mlm=False,
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=eval_dataset,
        data_collator=data_collator,
        processing_class=tokenizer,
    )

    trainer.train()
    trainer.save_model(str(final_dir))
    tokenizer.save_pretrained(str(final_dir))
    if checkpoints_dir.exists():
        # Remove checkpoints intermédios; mantém o final.
        shutil.rmtree(checkpoints_dir, ignore_errors=True)
    return str(final_dir)


if __name__ == "__main__":
    from rag.paths import MARKDOWN_DIR

    md_files = list(MARKDOWN_DIR.glob("*.md"))
    if not md_files:
        raise SystemExit("Nenhum ficheiro Markdown encontrado em data/documents/markdown")

    result = train_bloomberg_model(
        base_model_path="model/mistral-finance/final",
        output_dir=Path("model/bloomberg-finance"),
        train_files=md_files,
        epochs=2,
        batch_size=1,
        gradient_accumulation_steps=8,
        max_length=512,
        fp16=False,
        bf16=False,
    )
    print(f"Modelo guardado em: {result}")
