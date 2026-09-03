"""Modelo GPT-2 adaptado para domínio financeiro."""
from pathlib import Path
from transformers import GPT2Config, GPT2LMHeadModel, GPT2TokenizerFast

MODEL_DIR = Path(__file__).resolve().parent
ROOT = MODEL_DIR.parent


def create_model(vocab_size: int = 50000, max_length: int = 1024) -> GPT2LMHeadModel:
    """Cria um modelo GPT-2 pequeno."""
    config = GPT2Config(
        vocab_size=vocab_size,
        n_positions=max_length,
        n_embd=512,
        n_layer=8,
        n_head=8,
    )
    return GPT2LMHeadModel(config)


def create_tokenizer_from_corpus(
    corpus_path: Path, vocab_size: int = 50000
) -> GPT2TokenizerFast:
    """Treina um tokenizer BPE a partir do corpus financeiro."""
    from tokenizers import Tokenizer, models, pre_tokenizers, trainers, decoders

    tokenizer = Tokenizer(models.BPE())
    tokenizer.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False)
    tokenizer.decoder = decoders.ByteLevel()
    trainer = trainers.BpeTrainer(
        vocab_size=vocab_size,
        special_tokens=["<|endoftext|>", "<pad>"],
        initial_alphabet=list(pre_tokenizers.ByteLevel.alphabet()),
    )

    def iterator():
        with corpus_path.open("r", encoding="utf-8") as f:
            for line in f:
                import json

                yield json.loads(line)["text"]

    tokenizer.train_from_iterator(iterator(), trainer=trainer)
    wrapped = GPT2TokenizerFast(tokenizer_object=tokenizer)
    wrapped.pad_token = "<pad>"
    wrapped.eos_token = "<|endoftext|>"
    wrapped.bos_token = "<|endoftext|>"
    # Garante IDs válidos para o novo vocabulário.
    wrapped.pad_token_id = wrapped.convert_tokens_to_ids("<pad>")
    wrapped.eos_token_id = wrapped.convert_tokens_to_ids("<|endoftext|>")
    wrapped.bos_token_id = wrapped.convert_tokens_to_ids("<|endoftext|>")
    return wrapped


def initialize(
    vocab_size: int = 50000,
    max_length: int = 1024,
    name: str = "gpt2-finance",
) -> Path:
    """Cria tokenizer e modelo base no disco."""
    out = MODEL_DIR / name
    out.mkdir(parents=True, exist_ok=True)

    corpus_path = ROOT / "data" / "final" / "train.jsonl"
    tokenizer = create_tokenizer_from_corpus(corpus_path, vocab_size=vocab_size)
    tokenizer.save_pretrained(out)

    model = create_model(vocab_size=len(tokenizer), max_length=max_length)
    model.resize_token_embeddings(len(tokenizer))
    model.config.pad_token_id = tokenizer.pad_token_id
    model.config.eos_token_id = tokenizer.eos_token_id
    model.config.bos_token_id = tokenizer.bos_token_id
    # Força os IDs especiais no tokenizer salvo para evitar fallback para 50256.
    tokenizer.bos_token_id = tokenizer.eos_token_id
    tokenizer.save_pretrained(out)
    model.save_pretrained(out)
    return out


if __name__ == "__main__":
    print(initialize())
