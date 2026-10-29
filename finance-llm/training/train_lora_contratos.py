"""Fine-tuning LoRA do modelo de contratos, empresas e subvenções (CPU).

Treina um adaptador LoRA sobre o `Qwen/Qwen2.5-0.5B-Instruct` com os pares
`instruction/input/output` que o `training/export_es_dataset.py` extrai dos
índices do Elasticsearch (`contratos`, `finance_entities`, `finance_subvencoes`).

Porque não o `soup` (ver `docs/soup.md`): o Soup é um `train` de uma só tacada.
Este treino corre em CPU e leva dezenas de minutos — precisa de **pausa**, de
**retoma** e de um progresso que se possa ler (`metrics.jsonl`) e mostrar na
interface. É a mesma ideia do `training/train_mistral.py` (ficheiro
`training/pause.flag`), agora com LoRA.

Exemplo curto (primeiro adaptador, ~30 min nesta CPU):

    python training/train_lora_contratos.py --max-pairs 150

Continuar de onde ficou (depois de uma pausa ou de um Ctrl+C):

    python training/train_lora_contratos.py --resume --max-pairs 400

Pausar a meio, sem matar o processo (o treino guarda e sai no passo seguinte):

    New-Item training/pause.flag      # PowerShell
    touch training/pause.flag         # bash

O adaptador fica em `model/qwen05-contratos/` (configurável com `--out`), ao
lado de `metrics.jsonl` (curva de perda) e `run_metadata.json` (o que a API e a
página do modelo mostram).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import shutil
import signal
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from inference.contratos_lora import (  # noqa: E402
    DEFAULT_ADAPTER_DIR,
    DEFAULT_BASE_MODEL,
    render_chat_prompt,
    split_indices,
)

DATA_FILE = ROOT / "data" / "final" / "iqos_contratos_empresas_qwen.jsonl"
PAUSE_FLAG = ROOT / "training" / "pause.flag"

# Alvos LoRA: todas as projecções lineares do bloco Qwen2. Cobrir só q/v (o que
# era hábito em 2023) deixa de fora as MLP, onde vive a maior parte do
# conhecimento factual — e é isso que este treino quer acrescentar.
LORA_TARGETS = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]

_stop_requested = False


def _handle_signal(signum, frame):  # noqa: ARG001
    """Ctrl+C não mata o treino a meio de um passo: guarda e sai no fim."""
    global _stop_requested
    _stop_requested = True
    print("\n[PAUSA] pedido de paragem recebido — a guardar no fim do passo atual...", flush=True)


def load_pairs(path: Path | str = DATA_FILE) -> List[Dict[str, Any]]:
    """Lê o JSONL Alpaca exportado do Elasticsearch."""
    rows: List[Dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def encode_example(tokenizer, row: Dict[str, Any], max_length: int) -> Optional[Dict[str, List[int]]]:
    """Codifica um par com a perda só na resposta (prompt mascarado com -100).

    Devolve `None` quando a resposta não cabe na janela — um exemplo sem nenhum
    token de resposta ensinaria o modelo a calar-se.
    """
    prompt_ids = tokenizer(
        render_chat_prompt(tokenizer, row.get("instruction", ""), row.get("input", "")),
        add_special_tokens=False,
    )["input_ids"]
    answer_ids = tokenizer(str(row.get("output", "")).strip(), add_special_tokens=False)["input_ids"]
    eos = tokenizer.eos_token_id
    if eos is not None:
        answer_ids = answer_ids + [eos]

    margem = len(prompt_ids)
    if margem + 8 >= max_length:
        # Sem espaço para a resposta: um par cortado ensinaria uma resposta a
        # meio. O exporter já mede os tokens do modelo, por isso isto é raro.
        return None
    answer_ids = answer_ids[: max_length - margem]
    if not answer_ids:
        return None
    input_ids = prompt_ids + answer_ids
    labels = [-100] * len(prompt_ids) + list(answer_ids)
    return {"input_ids": input_ids, "labels": labels}


def build_optimizer(model, lr: float):
    params = [p for p in model.parameters() if p.requires_grad]
    return __import__("torch").optim.AdamW(params, lr=lr, weight_decay=0.0)


def save_run_metadata(out_dir: Path, meta: Dict[str, Any]) -> None:
    (out_dir / "run_metadata.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Fine-tuning LoRA do modelo de contratos (CPU).")
    parser.add_argument("--data", type=Path, default=DATA_FILE, help="JSONL Alpaca exportado do Elasticsearch")
    parser.add_argument("--out", type=Path, default=DEFAULT_ADAPTER_DIR, help="Diretório do adaptador")
    parser.add_argument("--base-model", default=DEFAULT_BASE_MODEL, help="Modelo de partida")
    parser.add_argument("--max-pairs", type=int, default=150, help="Pares de treino a usar (após o held-out)")
    parser.add_argument("--holdout", type=int, default=60, help="Pares reservados para avaliação")
    parser.add_argument("--epochs", type=float, default=1.0)
    parser.add_argument("--max-length", type=int, default=512)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--grad-accum", type=int, default=8, help="Passos acumulados por actualização")
    parser.add_argument("--lr", type=float, default=1e-4)
    parser.add_argument("--lora-r", type=int, default=16)
    parser.add_argument("--lora-alpha", type=int, default=32)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--log-every", type=int, default=5, help="Passos entre linhas de métricas")
    parser.add_argument("--save-every", type=int, default=40, help="Passos entre checkpoints")
    parser.add_argument("--resume", action="store_true", help="Retoma de state.pt no diretório do adaptador")
    parser.add_argument("--pause-flag", type=Path, default=PAUSE_FLAG)
    parser.add_argument("--max-minutes", type=float, default=0.0, help="Tecto de tempo; 0 = sem tecto")
    parser.add_argument("--dry-run", action="store_true", help="Só prepara dados e mostra o plano")
    parser.add_argument("--no-index", action="store_true", help="Não guardar a ficha do treino no Elasticsearch")
    args = parser.parse_args()

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from peft import LoraConfig, PeftModel, get_peft_model

    torch.set_num_threads(int(os.environ.get("LLMFINANCE_CPU_THREADS", "8")))
    torch.manual_seed(args.seed)
    random.seed(args.seed)

    out_dir: Path = args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    state_path = out_dir / "state.pt"
    metrics_path = out_dir / "metrics.jsonl"

    rows = load_pairs(args.data)
    if not rows:
        print(f"[ERRO] dataset vazio: {args.data}", flush=True)
        return 2
    train_idx, holdout_idx = split_indices(len(rows), args.holdout, args.seed)
    train_idx = train_idx[: max(1, args.max_pairs)]

    tokenizer = AutoTokenizer.from_pretrained(args.base_model)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    exemplos = [encode_example(tokenizer, rows[i], args.max_length) for i in train_idx]
    exemplos = [e for e in exemplos if e]
    tokens_por_epoca = sum(len(e["input_ids"]) for e in exemplos)
    passos_por_epoca = math.ceil(len(exemplos) / args.batch_size)
    total_passos = math.ceil(passos_por_epoca / max(1, args.grad_accum) * max(1.0, args.epochs))
    print(
        f"[DADOS] {len(exemplos)} exemplos de treino ({tokens_por_epoca} tokens), "
        f"{len(holdout_idx)} held-out, {total_passos} actualizações planeadas "
        f"(batch {args.batch_size} × acumulação {args.grad_accum})",
        flush=True,
    )

    if args.dry_run:
        print("[DRY-RUN] nada foi treinado.", flush=True)
        return 0

    estado_anterior: Dict[str, Any] = {}
    if args.resume and state_path.exists():
        estado_anterior = torch.load(state_path, map_location="cpu", weights_only=False)

    # Um treino novo começa com um LoRA **de raiz** e substitui o adaptador que
    # lá está. Sem esta cópia, uma corrida pior apagava a anterior e não havia
    # como voltar atrás — a página oferecia «reverter» mas não havia versão para
    # onde reverter. Só na primeira gravação (não a cada checkpoint) e só quando
    # não é retoma: retomar continua o mesmo adaptador.
    if not estado_anterior:
        atual = out_dir / "adapter_model.safetensors"
        if atual.exists():
            carimbo = time.strftime("%Y%m%d-%H%M%S")
            anterior = Path(str(atual) + f".bak-{carimbo}")
            try:
                shutil.copy2(atual, anterior)
                print(f"[BACKUP] adaptador anterior em {anterior.name}", flush=True)
            except OSError as exc:  # pragma: no cover - depende do disco
                print(f"[AVISO] não consegui salvaguardar o adaptador anterior: {exc}", flush=True)

    model = AutoModelForCausalLM.from_pretrained(args.base_model, dtype=torch.float32)
    if estado_anterior:
        model = PeftModel.from_pretrained(model, str(out_dir), is_trainable=True)
        print(f"[RETOMA] a continuar do passo {estado_anterior.get('step', 0)}", flush=True)
    else:
        model = get_peft_model(
            model,
            LoraConfig(
                r=args.lora_r,
                lora_alpha=args.lora_alpha,
                lora_dropout=0.05,
                bias="none",
                task_type="CAUSAL_LM",
                target_modules=LORA_TARGETS,
            ),
        )
    model.train()
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print(f"[MODELO] {args.base_model} + LoRA r={args.lora_r} ({trainable / 1e6:.2f} M treináveis)", flush=True)

    optimizer = build_optimizer(model, args.lr)
    if estado_anterior.get("optimizer"):
        try:
            optimizer.load_state_dict(estado_anterior["optimizer"])
        except (ValueError, KeyError):
            print("[RETOMA] estado do optimizador incompatível — a reiniciar", flush=True)

    signal.signal(signal.SIGINT, _handle_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _handle_signal)

    step = int(estado_anterior.get("step", 0))
    inicio = time.time()
    perdas: List[float] = []
    perda_acumulada = 0.0
    tokens_vistos = 0
    status = "concluido"

    meta_final: Dict[str, Any] = {}

    def guardar(motivo: str) -> None:
        model.save_pretrained(str(out_dir))
        torch.save({"step": step, "optimizer": optimizer.state_dict(), "reason": motivo}, state_path)
        meta = {
            "estado": motivo,
            "modelo_base": args.base_model,
            "adaptador": out_dir.name,
            "lora": {"r": args.lora_r, "alpha": args.lora_alpha, "targets": LORA_TARGETS},
            "dados": {
                "ficheiro": str(args.data.relative_to(ROOT)) if args.data.is_relative_to(ROOT) else str(args.data),
                "pares_treino": len(exemplos),
                "pares_holdout": len(holdout_idx),
                "fontes": sorted({str(r.get("metadata", {}).get("fonte", "?")) for r in rows}),
            },
            "treino": {
                "passos": step,
                "passos_planeados": total_passos,
                "epocas": args.epochs,
                "lr": args.lr,
                "batch_size": args.batch_size,
                "grad_accum": args.grad_accum,
                "max_length": args.max_length,
                "tokens": tokens_vistos,
                "perda_final": round(sum(perdas[-20:]) / len(perdas[-20:]), 4) if perdas else None,
                "segundos": round(time.time() - inicio, 1),
                "concluido_em": time.strftime("%Y-%m-%dT%H:%M:%S"),
            },
        }
        save_run_metadata(out_dir, meta)
        meta_final.clear()
        meta_final.update(meta)
        print(f"[GUARDA] {motivo}: passo {step}, adaptador em {out_dir}", flush=True)

    def escrever_metrica(perda: float) -> None:
        with metrics_path.open("a", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {
                        "step": step,
                        "perda": round(perda, 4),
                        "perplexidade": round(math.exp(min(perda, 20)), 2),
                        "tokens": tokens_vistos,
                        "segundos": round(time.time() - inicio, 1),
                        # Instante absoluto: é o que permite à página distinguir
                        # «treino em curso» de «parou no passo 37» sem ter de
                        # perguntar ao processo (que pode nem estar a correr).
                        "ts": round(time.time(), 3),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

    try:
        for epoca in range(max(1, math.ceil(args.epochs))):
            for i in range(0, len(exemplos), args.batch_size):
                if step >= total_passos:
                    break
                if _stop_requested or args.pause_flag.exists():
                    status = "pausado"
                    break
                lote = exemplos[i : i + args.batch_size]
                maior = max(len(e["input_ids"]) for e in lote)
                input_ids = torch.full((len(lote), maior), tokenizer.pad_token_id, dtype=torch.long)
                labels = torch.full((len(lote), maior), -100, dtype=torch.long)
                attention = torch.zeros((len(lote), maior), dtype=torch.long)
                for j, e in enumerate(lote):
                    n = len(e["input_ids"])
                    input_ids[j, :n] = torch.tensor(e["input_ids"])
                    labels[j, :n] = torch.tensor(e["labels"])
                    attention[j, :n] = 1

                saida = model(input_ids=input_ids, attention_mask=attention, labels=labels)
                (saida.loss / max(1, args.grad_accum)).backward()
                perda_acumulada += float(saida.loss)
                tokens_vistos += int(attention.sum())

                if (i // args.batch_size + 1) % args.grad_accum == 0:
                    optimizer.step()
                    optimizer.zero_grad()
                    step += 1
                    perdas.append(perda_acumulada / args.grad_accum)
                    perda_acumulada = 0.0
                    if step % args.log_every == 0 or step == 1:
                        escrever_metrica(perdas[-1])
                        print(
                            f"passo {step}/{total_passos} | perda {perdas[-1]:.4f} | "
                            f"{tokens_vistos} tokens | {time.time() - inicio:.0f}s",
                            flush=True,
                        )
                    if step % args.save_every == 0:
                        guardar("checkpoint")
                if args.max_minutes and (time.time() - inicio) / 60 > args.max_minutes:
                    status = "limite_de_tempo"
                    break
            # Fecha o último grupo de acumulação: sem isto, o último lote de uma
            # época (quando não é múltiplo do `--grad-accum`) nunca era aplicado.
            if perda_acumulada:
                optimizer.step()
                optimizer.zero_grad()
                step += 1
                perdas.append(perda_acumulada / args.grad_accum)
                perda_acumulada = 0.0
                escrever_metrica(perdas[-1])
            if status != "concluido" or step >= total_passos:
                break
    finally:
        guardar(status)

    if not args.no_index and meta_final:
        try:
            from api import llm_contratos_service as service

            doc_id = service.index_run(meta_final)
            if doc_id:
                print(f"[INDICE] treino guardado em finance_llm_model_runs/{doc_id}", flush=True)
        except Exception as exc:  # o treino nao pode falhar por causa do Elasticsearch
            print(f"[INDICE] nao indexado: {exc}", flush=True)

    if status == "pausado" and args.pause_flag.exists():
        try:
            args.pause_flag.unlink()
        except OSError:
            pass
        print("[PAUSA] ficheiro training/pause.flag removido; retome com --resume", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
