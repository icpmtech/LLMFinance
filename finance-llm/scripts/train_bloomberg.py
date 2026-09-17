"""Script de treino para criar o modelo BloombergGPT-style a partir do corpus do IQ OS.

Uso:
    .venv\Scripts\python.exe scripts/train_bloomberg.py

O treino usa continual pre-training sobre o checkpoint `model/mistral-finance/final`
com os dados de `data/final/*.jsonl` e eventuais markdowns ingeridos.
O modelo final é guardado em `model/bloomberg-finance/final`.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag.models.train_bloomberg import train_bloomberg_model

TRAIN_FILES = sorted((ROOT / "data" / "final").glob("*.jsonl"))
MD_FILES = sorted((ROOT / "data" / "documents" / "markdown").glob("*.md"))


def main():
    train_files = [p for p in TRAIN_FILES if p.stat().st_size > 0]
    train_files += [p for p in MD_FILES if p.stat().st_size > 0]

    if not train_files:
        raise SystemExit("Nenhum ficheiro de treino encontrado.")

    print("Ficheiros de treino:")
    for f in train_files:
        print(f"  - {f.relative_to(ROOT)} ({f.stat().st_size:,} bytes)")

    # Modo demo por defeito para CPU: treina sobre um subconjunto pequeno
    # e limita o número de steps. Defina FULL_TRAIN=1 para correr o treino
    # completo (muito mais lento em CPU).
    import os
    demo_mode = not os.environ.get("FULL_TRAIN", "").strip()
    if demo_mode:
        print("\nModo demo: treino limitado a 500 exemplos / 50 max_steps.")
        print("Defina FULL_TRAIN=1 para treino completo.\n")
        output = train_bloomberg_model(
            base_model_path=str(ROOT / "model" / "mistral-finance" / "final"),
            output_dir=ROOT / "model" / "bloomberg-finance",
            train_files=train_files,
            validation_files=[ROOT / "data" / "final" / "validation.jsonl"],
            epochs=1,
            max_steps=50,
            max_examples=500,
            batch_size=1,
            gradient_accumulation_steps=1,
            learning_rate=5e-5,
            max_length=256,
            save_steps=25,
            eval_steps=25,
            logging_steps=5,
            fp16=False,
            bf16=False,
        )
    else:
        output = train_bloomberg_model(
            base_model_path=str(ROOT / "model" / "mistral-finance" / "final"),
            output_dir=ROOT / "model" / "bloomberg-finance",
            train_files=train_files,
            validation_files=[ROOT / "data" / "final" / "validation.jsonl"],
            epochs=2,
            batch_size=1,
            gradient_accumulation_steps=8,
            learning_rate=5e-5,
            max_length=512,
            save_steps=2000,
            eval_steps=500,
            logging_steps=50,
            fp16=False,
            bf16=False,
        )
    print(f"\nModelo guardado em: {output}")


if __name__ == "__main__":
    main()
