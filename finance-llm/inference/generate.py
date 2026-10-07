"""Geração de texto com o modelo treinado."""
from pathlib import Path
from transformers import GPT2LMHeadModel, GPT2TokenizerFast
import torch

ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "model" / "gpt2-finance" / "final"


class InferenceModel:
    """Envolve tokenizer e modelo para inferência."""

    def __init__(self, device: str | None = None):
        self.tokenizer = GPT2TokenizerFast.from_pretrained(MODEL_DIR)
        self.model = GPT2LMHeadModel.from_pretrained(MODEL_DIR)
        if self.tokenizer.pad_token is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token
        self.model.config.pad_token_id = self.tokenizer.pad_token_id
        self.device = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
        self.model.to(self.device)
        self.model.eval()

    def generate(self, prompt: str, max_new_tokens: int = 40, temperature: float = 1.0) -> str:
        # O prompt pode ser maior do que a janela do modelo (a Pesquisa profunda
        # chega a mandar 60 fontes). Sem cortar, os `position_ids` passam do
        # limite e o PyTorch rebenta com «index out of range in self».
        contexto = int(getattr(self.model.config, "max_position_embeddings", 1024))
        max_new_tokens = max(1, min(max_new_tokens, contexto - 64))
        limite = max(1, contexto - max_new_tokens)
        # Corta pelo início: no prompt da Pesquisa profunda a pergunta e as
        # regras estão no fim, e são a parte que não pode faltar.
        self.tokenizer.truncation_side = "left"
        inputs = self.tokenizer(
            prompt, return_tensors="pt", truncation=True, max_length=limite
        ).to(self.device)
        with torch.no_grad():
            outputs = self.model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                do_sample=temperature > 0,
                temperature=temperature if temperature > 0 else 1.0,
                pad_token_id=self.tokenizer.pad_token_id,
                eos_token_id=self.tokenizer.eos_token_id,
                use_cache=True,
            )
        return self.tokenizer.decode(outputs[0], skip_special_tokens=True)


_generate = None


def generate(prompt: str, max_new_tokens: int = 60, temperature: float = 1.0) -> str:
    """Gera continuação a partir de um prompt (singleton lazy)."""
    global _generate
    if _generate is None:
        _generate = InferenceModel()
    return _generate.generate(prompt, max_new_tokens=max_new_tokens, temperature=temperature)


if __name__ == "__main__":
    print(generate("What is the closing price of AAPL?"))
