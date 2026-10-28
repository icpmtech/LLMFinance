"""Modelo de contratos+empresas: prompt partilhado e inferência com adaptador LoRA.

Este módulo é a **única** definição do molde de prompt do modelo afinado com os
dados do Elasticsearch (contratos, entidades e subvenções). Treino
(`training/train_lora_contratos.py`), avaliação
(`training/eval_lora_contratos.py`) e API (`api/llm_contratos_service.py`)
importam daqui, para que um prompt diferente não transforme um modelo bom em
respostas más.

Vive em `inference/` (e não em `training/`) porque `training/` fica fora do
contexto das imagens Docker (`ver .dockerignore`): o backend tem de conseguir
carregar o modelo, mas não precisa dos scripts de treino.
"""
from __future__ import annotations

import json
import os
import random
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]

# Modelo de partida escolhido para o fine-tune em CPU: já fala português,
# cabe na memória (0,5 B parâmetros) e é o mesmo que
# `training/soup/soup-qwen05-empresas-contratos.yaml` já previa.
DEFAULT_BASE_MODEL = os.environ.get("LLMFINANCE_BASE_MODEL", "Qwen/Qwen2.5-0.5B-Instruct")
DEFAULT_ADAPTER_DIR = ROOT / "model" / "qwen05-contratos"

SYSTEM_PROMPT = (
    "Assistente do IQ OS: descreves contratos públicos, empresas e subsídios "
    "portugueses em 2-3 frases, só com os dados recebidos. Se um campo faltar, "
    "dizes «não especificado»."
)

# Molde em texto simples (sem `chat_template`): o mesmo que
# `training/soup/eval_holdout.py` usa para medir o par instruction/input/output.
PROMPT_TEMPLATE = "### Instrução:\n{instruction}\n\n{input}\n\n### Resposta:\n"


def user_content(instruction: str, data: str) -> str:
    """Junta a instrução e os dados do documento no bloco do utilizador."""
    return f"### Instrução:\n{instruction.strip()}\n\n{data.strip()}"


def render_prompt(instruction: str, data: str, eos_token: str = "") -> str:
    """Prompt de texto simples — usado na avaliação e como rede de segurança."""
    del eos_token
    return PROMPT_TEMPLATE.format(instruction=instruction.strip(), input=data.strip())


def build_messages(instruction: str, data: str, *, sistema: Optional[str] = None, contexto: Optional[str] = None) -> List[Dict[str, str]]:
    """Mensagens no formato do `apply_chat_template` (Qwen2.5 traz o dele).

    `contexto` (memória + evidências do RAG + resultados de skills) entra **antes**
    dos dados do pedido: o modelo lê primeiro o que a plataforma sabe e só depois
    o documento, que é o que tem de descrever.
    """
    partes: List[str] = []
    if contexto and contexto.strip():
        partes.append(contexto.strip())
    partes.append(user_content(instruction, data))
    return [
        {"role": "system", "content": (sistema or SYSTEM_PROMPT).strip() or SYSTEM_PROMPT},
        {"role": "user", "content": "\n\n".join(partes)},
    ]


def render_chat_prompt(
    tokenizer,
    instruction: str,
    data: str,
    *,
    sistema: Optional[str] = None,
    contexto: Optional[str] = None,
) -> str:
    """Prompt com o `chat_template` do modelo e o turno do assistente aberto."""
    messages = build_messages(instruction, data, sistema=sistema, contexto=contexto)
    template = getattr(tokenizer, "chat_template", None)
    if not template:
        return render_prompt(instruction, data)
    return tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)


# ---------------------------------------------------------------------------
# Adaptadores no disco
# ---------------------------------------------------------------------------


def adapter_available(adapter_dir: Path | str = DEFAULT_ADAPTER_DIR) -> bool:
    """True quando há um adaptador LoRA treinado no diretório indicado."""
    path = Path(adapter_dir)
    return (path / "adapter_config.json").exists() and any(
        (path / name).exists() for name in ("adapter_model.safetensors", "adapter_model.bin")
    )


def read_run_metadata(adapter_dir: Path | str = DEFAULT_ADAPTER_DIR) -> Dict[str, Any]:
    """Metadados do treino guardados ao lado do adaptador (`run_metadata.json`).

    Devolve `{}` quando o ficheiro não existe — é o caso de um adaptador feito
    por outra ferramenta (a pasta `model/soup-*`), e a API mostra só o que sabe.
    """
    path = Path(adapter_dir) / "run_metadata.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def split_indices(total: int, holdout: int, seed: int = 42) -> tuple[list[int], list[int]]:
    """Divide `total` linhas em treino e held-out de forma **estável**.

    Baralha com a semente antes de cortar: o exporter grava as linhas agrupadas
    por fonte (primeiro todos os contratos, depois as entidades, depois as
    subvenções), por isso cortar as últimas N linhas daria um held-out só de
    subvenções — e um `--max-pairs` pequeno treinaria só contratos. Com a
    baralha determinística, qualquer prefixo já é uma amostra das três fontes e
    a divisão é a mesma em todas as corridas.
    """
    indices = list(range(max(0, int(total))))
    random.Random(seed).shuffle(indices)
    holdout = max(0, min(int(holdout), len(indices)))
    return indices[holdout:], indices[:holdout]


# ---------------------------------------------------------------------------
# Inferência
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_cache: Dict[str, Any] = {}


def _load(base_model: str, adapter_dir: Path | str, adapter: bool):
    """Carrega base + adaptador LoRA (uma vez por processo)."""
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    threads = int(os.environ.get("LLMFINANCE_CPU_THREADS", "8"))
    torch.set_num_threads(threads)

    tokenizer = AutoTokenizer.from_pretrained(base_model)
    model = AutoModelForCausalLM.from_pretrained(base_model, dtype=torch.float32)
    if adapter and adapter_available(adapter_dir):
        from peft import PeftModel

        model = PeftModel.from_pretrained(model, str(adapter_dir))
        model = model.merge_and_unload()
    model.eval()
    return tokenizer, model


def get_model(base_model: str = DEFAULT_BASE_MODEL, adapter_dir: Path | str = DEFAULT_ADAPTER_DIR, adapter: bool = True):
    """Devolve `(tokenizer, model)` do cache do processo (carregamento pesado)."""
    key = f"{base_model}|{adapter_dir}|{int(adapter)}"
    with _lock:
        if key not in _cache:
            _cache[key] = _load(base_model, adapter_dir, adapter)
        return _cache[key]


def limpar_cache() -> None:
    """Esquece o modelo carregado (o adaptador foi reescrito por uma adaptação)."""
    with _lock:
        _cache.clear()


def answer(
    instruction: str,
    data: str,
    *,
    base_model: str = DEFAULT_BASE_MODEL,
    adapter_dir: Path | str = DEFAULT_ADAPTER_DIR,
    adapter: bool = True,
    max_new_tokens: int = 160,
    temperature: float = 0.2,
    sistema: Optional[str] = None,
    contexto: Optional[str] = None,
    devolver_tokens: bool = False,
) -> Dict[str, Any]:
    """Gera a resposta do modelo afinado para um documento do Elasticsearch.

    Com `devolver_tokens`, devolve também a probabilidade que o modelo deu a cada
    token gerado — é a matéria-prima do diagrama «como é que ele chegou aqui»
    (uma resposta com tokens de 0,2 de probabilidade é um palpite).
    """
    import torch

    tokenizer, model = get_model(base_model, adapter_dir, adapter)
    prompt = render_chat_prompt(tokenizer, instruction, data, sistema=sistema, contexto=contexto)
    inputs = tokenizer(prompt, return_tensors="pt", truncation=True, max_length=1536)
    prompt_len = inputs["input_ids"].shape[-1]
    with torch.no_grad():
        saida = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=temperature > 0,
            temperature=temperature if temperature > 0 else 1.0,
            top_p=0.9,
            # 1,05 não travava a degeneração de um 0,5 B: a resposta repetia
            # «o CPV principal principal é» e emendava um segundo CPV inventado.
            # 1,15 é o valor habitual neste tamanho; e o corte de 3-gramas impede
            # a repetição literal sem tocar em frases legítimas como
            # «Código dos Contratos Públicos (DL 18/2008)».
            repetition_penalty=1.15,
            no_repeat_ngram_size=3,
            pad_token_id=tokenizer.pad_token_id or tokenizer.eos_token_id,
            eos_token_id=tokenizer.eos_token_id,
            output_scores=devolver_tokens,
            return_dict_in_generate=devolver_tokens,
        )
    sequencia = saida.sequences if devolver_tokens else saida
    gerados = sequencia[0][prompt_len:]
    text = tokenizer.decode(gerados, skip_special_tokens=True).strip()
    resultado: Dict[str, Any] = {
        "resposta": text,
        "modelo": base_model,
        "adaptador": str(adapter_dir) if adapter and adapter_available(adapter_dir) else None,
        "prompt_tokens": int(prompt_len),
        "tokens_gerados": int(sequencia.shape[-1] - prompt_len),
    }
    if devolver_tokens:
        tokens: List[Dict[str, Any]] = []
        for i, token_id in enumerate(gerados.tolist()):
            entrada: Dict[str, Any] = {"token": tokenizer.decode([token_id]), "id": token_id}
            if i < len(saida.scores):
                distribuicao = torch.softmax(saida.scores[i][0], dim=-1)
                probabilidade = float(distribuicao[token_id])
                entrada["probabilidade"] = round(probabilidade, 4)
                # Entropia normalizada: 0 = certeza absoluta, 1 = indecisão total.
                entrada["entropia"] = round(float(-(distribuicao * torch.log(distribuicao + 1e-12)).sum()) / 12.0, 3)
            tokens.append(entrada)
        resultado["tokens"] = tokens
        if tokens:
            probs = [t.get("probabilidade", 0.0) for t in tokens if "probabilidade" in t]
            resultado["confianca_media"] = round(sum(probs) / len(probs), 4) if probs else None
    return resultado
