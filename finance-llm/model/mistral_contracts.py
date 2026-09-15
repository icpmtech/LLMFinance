"""Cria tokenizer e modelo Mistral from-scratch para contratos públicos portugueses.

O modelo atual ``model/mistral-finance/final`` foi treinado sobre dados financeiros
em inglês (tendências de preços de ações), pelo que gera lixo quando se lhe pedem
respostas sobre contratos em português. Este script treina um novo tokenizer BPE
sobre o corpus de contratos e inicializa um modelo Mistral com configuração
adaptada a português (vocab_size maior, max_position_embeddings maior).

Uso:
    python model/mistral_contracts.py --vocab_size 32768 --max_length 2048 --name mistral-contracts
    python training/train_mistral_contracts.py --output_dir model/mistral-contracts/final ...
"""
from pathlib import Path
from transformers import MistralConfig, MistralForCausalLM, PreTrainedTokenizerFast
import argparse

MODEL_DIR = Path(__file__).resolve().parent
ROOT = MODEL_DIR.parent


def create_model(vocab_size: int, max_length: int) -> MistralForCausalLM:
    """Cria um modelo Mistral pequeno para CPU/demo."""
    config = MistralConfig(
        vocab_size=vocab_size,
        hidden_size=512,
        intermediate_size=1024,
        num_hidden_layers=8,
        num_attention_heads=8,
        num_key_value_heads=4,
        max_position_embeddings=max_length,
        sliding_window=min(512, max_length),
        tie_word_embeddings=False,
    )
    return MistralForCausalLM(config)


def create_tokenizer_from_contracts_corpus(
    corpus_path: Path, vocab_size: int
) -> PreTrainedTokenizerFast:
    """Treina um tokenizer BPE a partir do corpus de contratos."""
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

                doc = json.loads(line)
                # Concatena instruction+input+output para capturar todo o vocabulário.
                yield (
                    f"### Instrução:\n{doc.get('instruction', '')}\n\n"
                    f"### Entrada:\n{doc.get('input', '')}\n\n"
                    f"### Resposta:\n{doc.get('output', '')}"
                )

    tokenizer.train_from_iterator(iterator(), trainer=trainer)
    wrapped = PreTrainedTokenizerFast(
        tokenizer_object=tokenizer,
        bos_token="<s>",
        eos_token="</s>",
        pad_token="<pad>",
        unk_token="<unk>",
    )
    wrapped.pad_token_id = wrapped.convert_tokens_to_ids("<pad>")
    wrapped.eos_token_id = wrapped.convert_tokens_to_ids("</s>")
    wrapped.bos_token_id = wrapped.convert_tokens_to_ids("<s>")
    wrapped.unk_token_id = wrapped.convert_tokens_to_ids("<unk>")
    return wrapped


def initialize(
    vocab_size: int = 32768,
    max_length: int = 2048,
    name: str = "mistral-contracts",
) -> Path:
    """Cria tokenizer e modelo base no disco."""
    out = MODEL_DIR / name
    out.mkdir(parents=True, exist_ok=True)

    corpus_path = ROOT / "data" / "final" / "contratos_train.jsonl"
    if not corpus_path.exists():
        raise FileNotFoundError(
            f"Corpus de contratos não encontrado: {corpus_path}. "
            "Gere primeiro com: python collectors/contratos.py --train-corpus"
        )

    print(f"[TOKENIZER] a treinar BPE com vocab_size={vocab_size} sobre {corpus_path}...")
    tokenizer = create_tokenizer_from_contracts_corpus(corpus_path, vocab_size=vocab_size)
    tokenizer.save_pretrained(out)
    print(f"[TOKENIZER] vocab efetivo: {len(tokenizer)}")

    print(f"[MODEL] a criar Mistral com max_length={max_length} e vocab={len(tokenizer)}...")
    model = create_model(vocab_size=len(tokenizer), max_length=max_length)
    model.resize_token_embeddings(len(tokenizer))
    model.config.pad_token_id = tokenizer.pad_token_id
    model.config.eos_token_id = tokenizer.eos_token_id
    model.config.bos_token_id = tokenizer.bos_token_id
    model.config.loss_type = "ForCausalLMLoss"
    tokenizer.bos_token_id = tokenizer.bos_token_id
    tokenizer.save_pretrained(out)
    model.save_pretrained(out)
    print(f"[MODEL] modelo base guardado em {out}")
    return out


def main():
    parser = argparse.ArgumentParser(description="Cria tokenizer+modelo Mistral from-scratch para contratos")
    parser.add_argument("--vocab_size", type=int, default=32768)
    parser.add_argument("--max_length", type=int, default=2048)
    parser.add_argument("--name", type=str, default="mistral-contracts")
    args = parser.parse_args()
    initialize(args.vocab_size, args.max_length, args.name)


if __name__ == "__main__":
    main()
