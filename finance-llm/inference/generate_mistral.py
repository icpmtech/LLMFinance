"""Geração de texto com o modelo Mistral treinado."""
from pathlib import Path
from transformers import MistralForCausalLM, PreTrainedTokenizerFast
import torch

ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "model" / "mistral-finance" / "final"


class InferenceModel:
    """Envolve tokenizer e modelo Mistral para inferência."""

    def __init__(self, device: str | None = None):
        self.tokenizer = PreTrainedTokenizerFast.from_pretrained(MODEL_DIR)
        self.model = MistralForCausalLM.from_pretrained(MODEL_DIR)
        if self.tokenizer.pad_token is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token
        self.model.config.pad_token_id = self.tokenizer.pad_token_id
        self.device = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
        self.model.to(self.device)
        self.model.eval()

    def generate(self, prompt: str, max_new_tokens: int = 50, temperature: float = 0.8) -> str:
        prompt_with_bos = f"{self.tokenizer.bos_token}{prompt}"
        encoded = self.tokenizer(prompt_with_bos, return_tensors="pt")
        input_len = encoded["input_ids"].shape[-1]
        encoded = encoded.to(self.device)
        with torch.no_grad():
            outputs = self.model.generate(
                **encoded,
                max_new_tokens=max_new_tokens,
                do_sample=temperature > 0,
                temperature=temperature if temperature > 0 else 1.0,
                pad_token_id=self.tokenizer.pad_token_id,
                eos_token_id=self.tokenizer.eos_token_id,
                bos_token_id=self.tokenizer.bos_token_id,
                top_k=50,
                top_p=0.95,
                use_cache=True,
                early_stopping=True,
                num_beams=1,
            )
        new_ids = outputs[0][input_len:]
        decoded = self.tokenizer.decode(new_ids, skip_special_tokens=True)
        return decoded.strip()


_generate = None


def generate(prompt: str, max_new_tokens: int = 80, temperature: float = 0.8) -> str:
    """Gera continuação a partir de um prompt (singleton lazy)."""
    global _generate
    if _generate is None:
        _generate = InferenceModel()
    return _generate.generate(prompt, max_new_tokens=max_new_tokens, temperature=temperature)


if __name__ == "__main__":
    print(generate("What is the closing price of AAPL?"))
