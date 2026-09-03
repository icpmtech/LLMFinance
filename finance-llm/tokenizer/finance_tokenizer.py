"""Tokenizer simples baseado em subword BPE para texto financeiro."""
from pathlib import Path
from collections import defaultdict

VOCAB_FILE = Path(__file__).resolve().parent / "vocab.txt"


def build_bpe_vocab(texts: list[str], num_merges: int = 100) -> dict:
    """Constrói vocabulário BPE minimal a partir de textos."""
    vocab = defaultdict(int)
    for text in texts:
        for token in text.split():
            vocab[tuple(token) + ("</w>",)] += 1

    for _ in range(num_merges):
        pairs = defaultdict(int)
        for word, freq in vocab.items():
            for i in range(len(word) - 1):
                pairs[(word[i], word[i + 1])] += freq
        if not pairs:
            break
        best = max(pairs, key=pairs.get)
        new_vocab = {}
        for word, freq in vocab.items():
            new_word = []
            i = 0
            while i < len(word):
                if i < len(word) - 1 and (word[i], word[i + 1]) == best:
                    new_word.append(word[i] + word[i + 1])
                    i += 2
                else:
                    new_word.append(word[i])
                    i += 1
            new_vocab[tuple(new_word)] = freq
        vocab = new_vocab
    return vocab


def save_vocab(vocab: dict) -> None:
    """Guarda vocabulário em ficheiro."""
    with VOCAB_FILE.open("w", encoding="utf-8") as f:
        for token in sorted({t for word in vocab for t in word}):
            f.write(token + "\n")


if __name__ == "__main__":
    sample = ["Earnings per share increased by 5%", "The ECB raised interest rates"]
    vocab = build_bpe_vocab(sample, num_merges=10)
    save_vocab(vocab)
    print(VOCAB_FILE)
