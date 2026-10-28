"""Adaptação incremental do adaptador LoRA com o que o utilizador ensinou.

O treino grande corre à mão (`training/train_lora_contratos.py`, com pausa e
retoma). Este módulo é a versão **curta e automática**: pega nas correções
humanas (`finance_llm_feedback`) e nas skills com exemplo
(`finance_llm_memoria`), escreve-as como pares Alpaca, dá alguns passos de
treino sobre o adaptador que já existe e guarda-o em sítio.

Regras que o tornam seguro:

- **Uma adaptação de cada vez** (`_lock` + estado), porque carrega outro modelo
  de 0,5 B para a memória;
- **Backup antes de escrever** (`adapter_model.safetensors.bak-<ts>`), para que
  uma adaptação má seja reversível;
- **Mínimo de pares** (`MIN_PARES`) — treinar com um exemplo só move o modelo na
  direção de uma frase e estraga o formato aprendido;
- **Avaliação antes/depois**: mede a perda nos próprios pares e guarda o número
  em `metricas_adaptacao.jsonl`, para a interface mostrar se melhorou.
"""
from __future__ import annotations

import json
import logging
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
DATA_FICHEIRO = ROOT / "data" / "final" / "iqos_adaptacao.jsonl"

MIN_PARES = 3
MAX_PASSOS = 40

_estado: Dict[str, Any] = {
    "a_correr": False,
    "passo": 0,
    "passos": 0,
    "perda": None,
    "iniciado": None,
    "concluido": None,
    "pares": 0,
    "erro": None,
    "ultimo_resultado": None,
}
_estado_lock = threading.Lock()
_treino_lock = threading.Lock()


def estado_adaptacao() -> Dict[str, Any]:
    """Estado da adaptação: o que está a correr **e** o que ficou da última.

    O estado em memória perde-se quando o contentor reinicia; o histórico está
    em `metricas_adaptacao.jsonl`, ao lado do adaptador, e é de lá que se lê o
    último resultado depois de um restart.
    """
    with _estado_lock:
        estado = dict(_estado)
    if not estado.get("ultimo_resultado"):
        historico = _ler_historico()
        if historico:
            estado["ultimo_resultado"] = historico[-1]
    estado["versoes"] = _versoes_guardadas()
    return estado


def _ler_historico() -> List[Dict[str, Any]]:
    from inference.contratos_lora import DEFAULT_ADAPTER_DIR

    ficheiro = DEFAULT_ADAPTER_DIR / "metricas_adaptacao.jsonl"
    if not ficheiro.exists():
        return []
    linhas: List[Dict[str, Any]] = []
    try:
        with ficheiro.open("r", encoding="utf-8") as fh:
            for linha in fh:
                linha = linha.strip()
                if linha:
                    try:
                        linhas.append(json.loads(linha))
                    except ValueError:
                        continue
    except OSError:
        return []
    return linhas


def _versoes_guardadas() -> int:
    """Quantos backups do adaptador existem (cada adaptação cria um)."""
    from inference.contratos_lora import DEFAULT_ADAPTER_DIR

    try:
        return len(list(DEFAULT_ADAPTER_DIR.glob("adapter_model.safetensors.bak-*")))
    except OSError:
        return 0


def _escrever_pares(pares: List[Dict[str, Any]]) -> Path:
    """Grava os pares de adaptação (um ficheiro só, reescrito de cada vez)."""
    DATA_FICHEIRO.parent.mkdir(parents=True, exist_ok=True)
    with DATA_FICHEIRO.open("w", encoding="utf-8") as fh:
        for par in pares:
            fh.write(json.dumps(par, ensure_ascii=False) + "\n")
    return DATA_FICHEIRO


def _encode(tokenizer, par: Dict[str, Any], max_length: int = 512):
    """Mesmo molde do treino grande: perda só nos tokens da resposta."""
    import torch
    from inference.contratos_lora import render_chat_prompt

    prompt_ids = tokenizer(
        render_chat_prompt(tokenizer, par.get("instruction", ""), par.get("input", "")),
        add_special_tokens=False,
    )["input_ids"]
    resposta = str(par.get("output", "")).strip()
    alvo = tokenizer(resposta, add_special_tokens=False)["input_ids"]
    if tokenizer.eos_token_id is not None:
        alvo = alvo + [tokenizer.eos_token_id]
    if not alvo or len(prompt_ids) + len(alvo) >= max_length:
        return None
    ids = torch.tensor([prompt_ids + alvo])
    labels = torch.tensor([[-100] * len(prompt_ids) + alvo])
    return ids, labels


def adaptar(
    *,
    passos: int = 12,
    lr: float = 5e-5,
    max_length: int = 512,
    pares_minimos: int = MIN_PARES,
    marcar_utilizado: bool = True,
) -> Dict[str, Any]:
    """Dá `passos` actualizações sobre o adaptador, usando o feedback guardado."""
    from api import llm_contratos_agente as agente

    inicio = time.time()
    pares = agente.pares_de_feedback(limite=200, apenas_novos=True)
    if len(pares) < pares_minimos:
        return {
            "estado": "sem_dados",
            "mensagem": f"só há {len(pares)} pares com resposta corrigida (mínimo {pares_minimos})",
            "pares": len(pares),
        }

    ficheiro = _escrever_pares(pares)

    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    from inference.contratos_lora import DEFAULT_ADAPTER_DIR, DEFAULT_BASE_MODEL, adapter_available

    if not adapter_available(DEFAULT_ADAPTER_DIR):
        return {"estado": "sem_adaptador", "mensagem": "não há adaptador treinado para adaptar"}

    torch.set_num_threads(int(__import__("os").environ.get("LLMFINANCE_CPU_THREADS", "8")))
    tokenizer = AutoTokenizer.from_pretrained(DEFAULT_BASE_MODEL)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    exemplos = [e for e in (_encode(tokenizer, p, max_length) for p in pares) if e]
    if not exemplos:
        return {"estado": "sem_dados", "mensagem": "nenhum par cabe na janela do modelo", "pares": len(pares)}

    passos = max(1, min(int(passos), MAX_PASSOS))
    modelo_base = AutoModelForCausalLM.from_pretrained(DEFAULT_BASE_MODEL, dtype=torch.float32)
    modelo = PeftModel.from_pretrained(modelo_base, str(DEFAULT_ADAPTER_DIR), is_trainable=True)
    modelo.train()
    optimizer = torch.optim.AdamW([p for p in modelo.parameters() if p.requires_grad], lr=lr)

    def perda_media() -> float:
        modelo.eval()
        total, n = 0.0, 0
        with torch.no_grad():
            for ids, labels in exemplos:
                total += float(modelo(input_ids=ids, labels=labels).loss)
                n += 1
        modelo.train()
        return round(total / max(1, n), 4)

    perda_antes = perda_media()
    historico: List[Dict[str, Any]] = []
    for passo in range(1, passos + 1):
        ids, labels = exemplos[(passo - 1) % len(exemplos)]
        saida = modelo(input_ids=ids, labels=labels)
        saida.loss.backward()
        optimizer.step()
        optimizer.zero_grad()
        perda = round(float(saida.loss.detach()), 4)
        historico.append({"passo": passo, "perda": perda})
        with _estado_lock:
            _estado.update({"passo": passo, "perda": perda})

    perda_depois = perda_media()

    carimbo = time.strftime("%Y%m%d-%H%M%S")
    backup = Path(str(DEFAULT_ADAPTER_DIR / "adapter_model.safetensors") + f".bak-{carimbo}")
    try:
        atual = DEFAULT_ADAPTER_DIR / "adapter_model.safetensors"
        if atual.exists():
            shutil.copy2(atual, backup)
    except OSError as exc:  # pragma: no cover - depende do disco
        logger.warning("Backup do adaptador falhou: %s", exc)

    modelo.save_pretrained(str(DEFAULT_ADAPTER_DIR))

    resultado = {
        "estado": "concluido",
        "pares": len(exemplos),
        "passos": passos,
        "lr": lr,
        "perda_antes": perda_antes,
        "perda_depois": perda_depois,
        "delta": round(perda_depois - perda_antes, 4),
        "backup": backup.name,
        "ficheiro": str(DATA_FICHEIRO.relative_to(ROOT)) if DATA_FICHEIRO.is_relative_to(ROOT) else str(DATA_FICHEIRO),
        "segundos": round(time.time() - inicio, 1),
        "concluido_em": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "historico": historico,
    }

    try:
        with (DEFAULT_ADAPTER_DIR / "metricas_adaptacao.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({k: resultado[k] for k in ("concluido_em", "pares", "passos", "perda_antes", "perda_depois", "delta")}, ensure_ascii=False) + "\n")
    except OSError:
        pass

    if marcar_utilizado:
        agente.marcar_feedback_utilizado([p["metadata"]["feedback_id"] for p in pares if p.get("metadata", {}).get("feedback_id")])

    try:
        from api import llm_contratos_service as service

        service.index_run(
            {
                "estado": "adaptacao_incremental",
                "modelo_base": DEFAULT_BASE_MODEL,
                "adaptador": DEFAULT_ADAPTER_DIR.name,
                "dados": {"ficheiro": resultado["ficheiro"], "pares_treino": len(exemplos), "fontes": ["feedback"]},
                "treino": {
                    "passos": passos,
                    "perda_final": perda_depois,
                    "segundos": resultado["segundos"],
                    "concluido_em": resultado["concluido_em"],
                },
            }
        )
    except Exception as exc:  # pragma: no cover - depende do cluster
        logger.warning("Não indexou a adaptação: %s", exc)

    # O adaptador mudou: a próxima inferência tem de recarregar.
    from inference import contratos_lora

    contratos_lora.limpar_cache()
    return resultado


def adaptar_em_segundo_plano(passos: int = 12, lr: float = 5e-5) -> Dict[str, Any]:
    """Arranca a adaptação numa thread (a rota responde já, a página vai vendo)."""
    with _estado_lock:
        if _estado["a_correr"]:
            return {"estado": "a_correr", "ja_estava_a_correr": True, **_estado}
        _estado.update(
            {"a_correr": True, "passo": 0, "passos": passos, "perda": None, "erro": None, "iniciado": time.strftime("%Y-%m-%dT%H:%M:%S")}
        )

    def _correr() -> None:
        with _treino_lock:
            try:
                resultado = adaptar(passos=passos, lr=lr)
                with _estado_lock:
                    _estado.update({"ultimo_resultado": resultado, "concluido": time.strftime("%Y-%m-%dT%H:%M:%S")})
            except Exception as exc:  # pragma: no cover - protege a thread
                logger.exception("Adaptação incremental falhou")
                with _estado_lock:
                    _estado.update({"erro": str(exc)})
            finally:
                with _estado_lock:
                    _estado["a_correr"] = False

    threading.Thread(target=_correr, name="llm-adaptacao", daemon=True).start()
    return {"estado": "iniciado", "passos": passos}
