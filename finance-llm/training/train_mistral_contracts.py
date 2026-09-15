"""Fine-tuning do Mistral com o corpus de contratos públicos portugueses.

Converte o ficheiro data/final/contratos_train.jsonl (formato instruction/
input/output) para texto contínuo e reutiliza o loop de treino do
``training/train_mistral.py``.

Exemplo:
    python training/train_mistral_contracts.py --max_samples 50000 --epochs 1
"""
from pathlib import Path
import argparse
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from training.train_mistral import run_training  # noqa: E402
from transformers import PreTrainedTokenizerFast

CONTRACTS_TRAIN_FILE = ROOT / "data" / "final" / "contratos_train.jsonl"
DEFAULT_MODEL_DIR = ROOT / "model" / "mistral-finance"


def load_contracts_texts(path: Path | str, max_samples: int | None = None) -> list[str]:
    """Carrega contratos do JSONL e converte cada registo num texto de treino."""
    path = Path(path)
    texts: list[str] = []
    with path.open("r", encoding="utf-8") as fh:
        for i, line in enumerate(fh):
            if not line.strip():
                continue
            if max_samples is not None and i >= max_samples:
                break
            doc = json.loads(line)
            instruction = doc.get("instruction", "")
            inp = doc.get("input", "")
            out = doc.get("output", "")
            # Formato de texto contínuo para Causal LM
            text = (
                f"### Instrução:\n{instruction}\n\n"
                f"### Entrada:\n{inp}\n\n"
                f"### Resposta:\n{out}"
            )
            texts.append(text)
    return texts


def pack_texts_to_length(
    texts: list[str],
    tokenizer,
    max_length: int = 1024,
    separator: str = "\n\n",
) -> list[str]:
    """Agrupa exemplos curtos em blocos de até max_length tokens para reduzir padding.

    Apenas concatena exemplos quando a soma de tokens (mais separador) cabe no
    limite. Exemplos isolados que já excedem o limite são truncados pelo tokenizer
    durante o treino.
    """
    packed: list[str] = []
    current_texts: list[str] = []
    current_len = 0
    sep_len = len(tokenizer.encode(separator, add_special_tokens=False))

    def flush():
        nonlocal current_texts, current_len
        if current_texts:
            packed.append(separator.join(current_texts))
            current_texts = []
            current_len = 0

    for txt in texts:
        txt_len = len(tokenizer.encode(txt, add_special_tokens=False))
        if txt_len >= max_length:
            flush()
            packed.append(txt[: int(max_length * 6)])  # corte grosseiro de caracteres
            continue
        if current_len + (sep_len if current_texts else 0) + txt_len > max_length:
            flush()
        current_texts.append(txt)
        current_len += (sep_len if len(current_texts) > 1 else 0) + txt_len
    flush()
    return packed


def main():
    parser = argparse.ArgumentParser(description="Fine-tuning Mistral com contratos públicos")
    parser.add_argument("--epochs", type=int, default=1)
    parser.add_argument("--batch_size", type=int, default=4)
    parser.add_argument("--max_length", type=int, default=1024,
                        help="Número máximo de tokens por exemplo (1024 é o limite do modelo atual)")
    parser.add_argument("--learning_rate", type=float, default=2e-5)
    parser.add_argument("--max_samples", type=int, default=None,
                        help="Número máximo de contratos a usar (padrão: todos)")
    parser.add_argument("--pack", action="store_true", default=True,
                        help="Agrupar exemplos curtos para reduzir padding")
    parser.add_argument("--gradient_accumulation_steps", type=int, default=4,
                        help="Acumulação de gradientes para batch virtual maior")
    parser.add_argument("--save_checkpoints", action="store_true", default=True)
    parser.add_argument("--resume", action="store_true", default=False,
                        help="Retoma a partir de training/mistral_state.pt")
    parser.add_argument("--model_dir", type=str, default=None,
                        help="Diretório base do modelo a treinar (padrão: model/mistral-finance)")
    parser.add_argument("--output_dir", type=str, default=None,
                        help="Diretório onde guardar o modelo final (padrão: <model_dir>/final)")
    args = parser.parse_args()

    model_dir = Path(args.model_dir) if args.model_dir else DEFAULT_MODEL_DIR

    if not CONTRACTS_TRAIN_FILE.exists():
        raise FileNotFoundError(
            f"Corpus de contratos não encontrado: {CONTRACTS_TRAIN_FILE}. "
            "Gere primeiro com: python collectors/contratos.py --train-corpus"
        )

    print(f"[LOAD] a carregar corpus de contratos de {CONTRACTS_TRAIN_FILE}...")
    texts = load_contracts_texts(CONTRACTS_TRAIN_FILE, max_samples=args.max_samples)
    print(f"[LOAD] {len(texts)} exemplos de contratos carregados.")

    if args.pack:
        print("[PACK] a carregar tokenizer para agrupar exemplos...")
        tokenizer = PreTrainedTokenizerFast.from_pretrained(str(model_dir), local_files_only=True)
        texts = pack_texts_to_length(texts, tokenizer, max_length=args.max_length)
        print(f"[PACK] {len(texts)} blocos de treino após agrupamento.")

    output_dir = Path(args.output_dir) if args.output_dir else model_dir / "final"
    run_training(
        texts=texts,
        epochs=args.epochs,
        batch_size=args.batch_size,
        max_length=args.max_length,
        learning_rate=args.learning_rate,
        save_checkpoints=args.save_checkpoints,
        resume=args.resume,
        gradient_accumulation_steps=args.gradient_accumulation_steps,
        output_dir=output_dir,
        checkpoint_dir=output_dir,
        model_dir=model_dir,
    )


if __name__ == "__main__":
    main()
