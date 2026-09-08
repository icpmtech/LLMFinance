"""BloombergGPT-style model wrapper."""
import math
import re
from pathlib import Path
from typing import List, Optional

import torch
from transformers import (
    AutoConfig,
    AutoModelForCausalLM,
    AutoTokenizer,
    PreTrainedModel,
    PreTrainedTokenizer,
    TextIteratorStreamer,
)


class BloombergGPTModel:
    """Wrapper para um modelo CausalLM usado no domínio financeiro.

    Pode ser inicializado a partir de:
      - um checkpoint HuggingFace (ex: mistralai/Mistral-7B-v0.1)
      - do `model/mistral-finance/final` já treinado no projeto
      - de um caminho local vazio, criando um GPT-2 from-scratch inspirado no paper BloombergGPT.
    """

    def __init__(
        self,
        model_path: str,
        device: Optional[str] = None,
        max_length: int = 512,
        load_in_8bit: bool = False,
        trust_remote_code: bool = False,
    ):
        self.model_path = model_path
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.max_length = max_length
        self.load_in_8bit = load_in_8bit

        self.tokenizer: PreTrainedTokenizer = self._load_tokenizer(trust_remote_code)
        self.model: PreTrainedModel = self._load_model(trust_remote_code)
        self.model.eval()

    def _load_tokenizer(self, trust_remote_code: bool) -> PreTrainedTokenizer:
        try:
            return AutoTokenizer.from_pretrained(
                self.model_path,
                trust_remote_code=trust_remote_code,
            )
        except Exception:
            # Fallback para tokenizer base se o específico falhar.
            return AutoTokenizer.from_pretrained("gpt2")

    def _load_model(self, trust_remote_code: bool) -> PreTrainedModel:
        config = AutoConfig.from_pretrained(
            self.model_path,
            trust_remote_code=trust_remote_code,
        )
        # Garante pad_token se for necessário.
        if self.tokenizer.pad_token is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token
        if getattr(config, "pad_token_id", None) is None:
            config.pad_token_id = self.tokenizer.pad_token_id

        kwargs = {
            "config": config,
            "trust_remote_code": trust_remote_code,
        }
        if self.load_in_8bit:
            kwargs["load_in_8bit"] = True
            kwargs["device_map"] = "auto"
        try:
            model = AutoModelForCausalLM.from_pretrained(self.model_path, **kwargs)
        except Exception:
            model = AutoModelForCausalLM.from_config(config, trust_remote_code=trust_remote_code)

        if not self.load_in_8bit:
            model = model.to(self.device)
        return model

    def encode_context(self, text: str) -> List[int]:
        return self.tokenizer.encode(text, add_special_tokens=False)

    def predict(
        self,
        prompt: str,
        max_new_tokens: int = 64,
        temperature: float = 0.1,
        top_p: float = 0.85,
        top_k: int = 30,
        repetition_penalty: float = 1.15,
        do_sample: bool = True,
        return_raw: bool = False,
    ) -> str:
        import time

        t0 = time.time()
        inputs = self.tokenizer(
            prompt,
            return_tensors="pt",
            truncation=True,
            max_length=self.max_length,
        ).to(self.device)

        with torch.no_grad():
            outputs = self.model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                temperature=temperature,
                top_p=top_p,
                top_k=top_k,
                repetition_penalty=repetition_penalty,
                do_sample=do_sample,
                pad_token_id=self.tokenizer.pad_token_id,
                eos_token_id=self.tokenizer.eos_token_id,
            )

        generated = outputs[0][inputs["input_ids"].shape[-1]:]
        raw_text = self.tokenizer.decode(generated, skip_special_tokens=True)
        print(f"[BloombergGPTModel.predict] generated {len(generated)} tokens in {time.time() - t0:.2f}s")
        if return_raw:
            return raw_text
        return self._extract_answer(raw_text)

    def predict_streaming(
        self,
        prompt: str,
        max_new_tokens: int = 128,
        temperature: float = 0.7,
        top_p: float = 0.9,
        top_k: int = 50,
    ):
        """Gera tokens via streaming (útil para UI)."""
        streamer = TextIteratorStreamer(
            self.tokenizer,
            skip_prompt=True,
            skip_special_tokens=True,
        )
        inputs = self.tokenizer(
            prompt,
            return_tensors="pt",
            truncation=True,
            max_length=self.max_length,
        ).to(self.device)

        kwargs = {
            "input_ids": inputs["input_ids"],
            "max_new_tokens": max_new_tokens,
            "temperature": temperature,
            "top_p": top_p,
            "top_k": top_k,
            "do_sample": True,
            "pad_token_id": self.tokenizer.pad_token_id,
            "eos_token_id": self.tokenizer.eos_token_id,
            "streamer": streamer,
        }

        import threading

        thread = threading.Thread(target=self.model.generate, kwargs=kwargs)
        thread.start()
        for text in streamer:
            yield text
        thread.join()

    def _extract_answer(self, text: str) -> str:
        """Remove bloat e extrai a parte útil da resposta."""
        # Corta se voltar a repetir o prompt ou instruções de formatação.
        for marker in ["Pergunta:", "Contexto:", "Resposta:", "Instrução:", "###"]:
            idx = text.find(marker)
            if idx > 10:
                text = text[:idx]
        text = re.split(r"\n\n(?=# |## )", text)[0]
        return text.strip()

    def financial_sentiment_score(self, text: str) -> dict:
        """Exemplo de análise de sentimento numérico via perplexidade."""
        prompts = [
            f"Texto: {text}\nSentimento financeiro: positivo",
            f"Texto: {text}\nSentimento financeiro: negativo",
            f"Texto: {text}\nSentimento financeiro: neutro",
        ]
        scores: List[float] = []
        for prompt in prompts:
            enc = self.tokenizer(prompt, return_tensors="pt").to(self.device)
            with torch.no_grad():
                loss = self.model(**enc, labels=enc["input_ids"]).loss
            scores.append(math.exp(loss.item()))

        labels = ["positivo", "negativo", "neutro"]
        best = labels[scores.index(min(scores))]
        total = sum(scores)
        return {
            "label": best,
            "perplexities": dict(zip(labels, scores)),
            "probabilities": {label: s / total for label, s in zip(labels, scores)},
        }
