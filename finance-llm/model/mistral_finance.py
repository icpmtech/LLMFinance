"""Modelo Mistral mini adaptado para domínio financeiro."""
from pathlib import Path
from transformers import MistralConfig, MistralForCausalLM, PreTrainedTokenizerFast

MODEL_DIR = Path(__file__).resolve().parent
ROOT = MODEL_DIR.parent


def create_model(vocab_size: int = 50000, max_length: int = 1024) -> MistralForCausalLM:
    """Cria um modelo Mistral pequeno para CPU/demo."""
    config = MistralConfig(
        vocab_size=vocab_size,
        hidden_size=512,
        intermediate_size=1024,
        num_hidden_layers=8,
        num_attention_heads=8,
        num_key_value_heads=4,
        max_position_embeddings=max_length,
        sliding_window=512,
        tie_word_embeddings=False,
    )
    return MistralForCausalLM(config)


def create_tokenizer_from_corpus(
    corpus_path: Path, vocab_size: int = 50000
) -> PreTrainedTokenizerFast:
    """Treina um tokenizer BPE a partir do corpus financeiro."""
    from tokenizers import Tokenizer, models, pre_tokenizers, trainers, decoders

    tokenizer = Tokenizer(models.BPE())
    tokenizer.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False)
    tokenizer.decoder = decoders.ByteLevel()
    trainer = trainers.BpeTrainer(
        vocab_size=vocab_size,
        special_tokens=["<s>", "</s>", "<pad>", "<unk>"],
        initial_alphabet=list(pre_tokenizers.ByteLevel.alphabet()),
    )

    def iterator():
        with corpus_path.open("r", encoding="utf-8") as f:
            for line in f:
                import json

                yield json.loads(line)["text"]

    tokenizer.train_from_iterator(iterator(), trainer=trainer)
    wrapped = PreTrainedTokenizerFast(
        tokenizer_object=tokenizer,
        bos_token="<s>",
        eos_token="</s>",
        pad_token="<pad>",
        unk_token="<unk>",
    )
    # Garante IDs válidos para o novo vocabulário.
    wrapped.pad_token_id = wrapped.convert_tokens_to_ids("<pad>")
    wrapped.eos_token_id = wrapped.convert_tokens_to_ids("</s>")
    wrapped.bos_token_id = wrapped.convert_tokens_to_ids("<s>")
    wrapped.unk_token_id = wrapped.convert_tokens_to_ids("<unk>")
    return wrapped


def initialize(
    vocab_size: int = 50000,
    max_length: int = 1024,
    name: str = "mistral-finance",
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
    # Previne avisos de loss_type.
    model.config.loss_type = "ForCausalLMLoss"
    tokenizer.bos_token_id = tokenizer.bos_token_id
    tokenizer.save_pretrained(out)
    model.save_pretrained(out)
    return out


if __name__ == "__main__":
    print(initialize())
