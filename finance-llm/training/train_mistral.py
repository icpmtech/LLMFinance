"""Treina o modelo Mistral com dados processados usando loop PyTorch manual.

Suporta pausa/continuação via sinal SIGUSR1/SIGUSR2 (Linux) ou ficheiro de
controlo ``training/pause.flag`` em todos os sistemas.

Otimizações para treino em CPU:
- ``torch.set_num_threads(8)`` equilibra throughput e latência em CPUs Intel
  de consumo.
- Acumulação de gradientes permite aumentar o batch virtual sem estourar
  memória nem tempo por passo.
- Estado guardado periodicamente permite continuar treino interrompido.
"""
from pathlib import Path
from transformers import MistralForCausalLM, PreTrainedTokenizerFast
import json
import os
import signal
import sys
import time
import torch
from torch.utils.data import DataLoader, TensorDataset

ROOT = Path(__file__).resolve().parents[1]
FINAL_DIR = ROOT / "data" / "final"
MODEL_DIR = ROOT / "model" / "mistral-finance"
PAUSE_FLAG = ROOT / "training" / "pause.flag"
STATE_FILE = ROOT / "training" / "mistral_state.pt"

# Otimização de CPU: benchmark interno mostrou melhor throughput com 8 threads
# no Intel Core Ultra 7 255U (14 lógicos / 12 físicos). Ajustar conforme CPU.
CPU_THREADS = int(os.environ.get("LLMFINANCE_CPU_THREADS", "8"))
torch.set_num_threads(CPU_THREADS)
torch.set_num_interop_threads(min(2, CPU_THREADS // 2))
torch.backends.mkldnn.enabled = True

_pause_requested = False
_resume_requested = False


def load_jsonl(path: Path) -> list[str]:
    """Carrega linhas de um ficheiro JSONL."""
    with path.open("r", encoding="utf-8") as f:
        return [json.loads(line)["text"] for line in f]


def _on_pause(signum=None, frame=None):
    global _pause_requested
    _pause_requested = True
    print("[PAUSE] sinal recebido. Pausa será efetuada no próximo batch.")


def _on_resume(signum=None, frame=None):
    global _resume_requested
    _resume_requested = True
    if PAUSE_FLAG.exists():
        PAUSE_FLAG.unlink()
    print("[RESUME] sinal recebido. Treino continua.")


def _check_flag_and_signal() -> tuple[bool, bool]:
    """Devolve (pause_requested, resume_requested) com base na flag e variáveis globais."""
    global _pause_requested, _resume_requested
    pause_requested = _pause_requested
    resume_requested = _resume_requested
    _pause_requested = False
    _resume_requested = False
    if PAUSE_FLAG.exists() and not pause_requested:
        pause_requested = True
    return pause_requested, resume_requested


def _register_signals():
    if sys.platform != "win32":
        signal.signal(signal.SIGUSR1, _on_pause)
        signal.signal(signal.SIGUSR2, _on_resume)
    else:
        # Windows não tem SIGUSR; usamos o ficheiro de flag.
        pass


def _save_state(step: int, epoch: int, model, optimizer, loss: float, rng_state):
    state = {
        "step": step,
        "epoch": epoch,
        "model_state_dict": model.state_dict(),
        "optimizer_state_dict": optimizer.state_dict(),
        "last_loss": loss,
        "rng_state": rng_state,
    }
    torch.save(state, STATE_FILE)
    print(f"[SAVE] estado guardado em {STATE_FILE} (step {step})")


def _load_state(model, optimizer):
    if not STATE_FILE.exists():
        return None
    state = torch.load(STATE_FILE, map_location="cpu")
    model.load_state_dict(state["model_state_dict"])
    optimizer.load_state_dict(state["optimizer_state_dict"])
    print(f"[LOAD] estado retomado de {STATE_FILE} (step {state['step']}, epoch {state['epoch']})")
    return state


def run_training(
    texts: list[str],
    epochs: int = 1,
    batch_size: int = 4,
    max_length: int = 128,
    learning_rate: float = 5e-5,
    save_checkpoints: bool = True,
    resume: bool = False,
    gradient_accumulation_steps: int = 1,
    output_dir: Path | None = None,
):
    """Executa o loop de treino Mistral a partir de uma lista de textos já prontos."""
    _register_signals()
    tokenizer = PreTrainedTokenizerFast.from_pretrained(MODEL_DIR)
    model = MistralForCausalLM.from_pretrained(MODEL_DIR)

    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    model.config.pad_token_id = tokenizer.pad_token_id
    model.config.loss_type = "ForCausalLMLoss"

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model.to(device)

    # Pré-truncar a nível de caracteres para acelerar a tokenização (o tokenizer
    # iria truncar a max_length tokens de qualquer forma).
    char_limit = max_length * 8
    print(f"[TOKENIZE] tokenizando {len(texts)} exemplos com max_length={max_length}...")
    all_input_ids = []
    all_attention_mask = []
    for i, txt in enumerate(texts):
        if len(txt) > char_limit:
            txt = txt[:char_limit]
        enc = tokenizer(
            txt,
            truncation=True,
            padding="max_length",
            max_length=max_length,
            return_tensors="pt",
        )
        all_input_ids.append(enc["input_ids"].squeeze(0))
        all_attention_mask.append(enc["attention_mask"].squeeze(0))
        if (i + 1) % 10000 == 0:
            print(f"  tokenizado {i+1}/{len(texts)}")

    input_ids = torch.stack(all_input_ids)
    attention_mask = torch.stack(all_attention_mask)
    labels = input_ids.clone()
    labels[attention_mask == 0] = -100

    dataset = TensorDataset(input_ids, attention_mask, labels)
    loader = DataLoader(dataset, batch_size=batch_size, shuffle=True)
    print(f"[DATASET] {len(dataset)} exemplos, {len(loader)} batches por época")

    optimizer = torch.optim.AdamW(model.parameters(), lr=learning_rate)
    model.train()

    start_step = 0
    start_epoch = 0
    if resume:
        state = _load_state(model, optimizer)
        if state:
            start_step = state["step"]
            start_epoch = state["epoch"]
            rng_state = state.get("rng_state")
            if rng_state is not None:
                torch.set_rng_state(rng_state)

    steps_per_epoch = len(loader)
    # Contabilizamos "step" como cada passo de gradiente efetivo (depois de accum).
    effective_steps_per_epoch = (steps_per_epoch + gradient_accumulation_steps - 1) // gradient_accumulation_steps
    total_steps = effective_steps_per_epoch * epochs
    step = start_epoch * effective_steps_per_epoch + start_step // max(1, gradient_accumulation_steps)
    epoch = start_epoch
    paused = False
    accum_counter = 0

    while epoch < epochs:
        for batch_idx, batch in enumerate(loader):
            pause_requested, resume_requested = _check_flag_and_signal()

            if pause_requested and not paused:
                _save_state(step, epoch, model, optimizer, loss.item() if 'loss' in locals() else 0.0, torch.get_rng_state())
                paused = True
                print("[PAUSED] treino em pausa. Apague training/pause.flag ou envie SIGUSR2 para continuar.")

            if paused:
                while paused:
                    _, resume_requested = _check_flag_and_signal()
                    if resume_requested or not PAUSE_FLAG.exists():
                        paused = False
                        print("[RESUMED] treino continua.")
                        break
                    time.sleep(1)
                continue

            # Continuação de treino: saltar batches já processados na época atual.
            if resume and epoch == start_epoch and batch_idx < start_step:
                continue

            b_input, b_mask, b_labels = (x.to(device) for x in batch)
            outputs = model(input_ids=b_input, attention_mask=b_mask, labels=b_labels)
            loss = outputs.loss / gradient_accumulation_steps
            loss.backward()
            accum_counter += 1

            if accum_counter % gradient_accumulation_steps == 0:
                optimizer.step()
                optimizer.zero_grad()
                step += 1

            if step % 20 == 0 and accum_counter % gradient_accumulation_steps == 0:
                print(f"step {step}/{total_steps} | epoch {epoch+1}/{epochs} | loss {loss.item() * gradient_accumulation_steps:.4f}")

            if save_checkpoints and step % 200 == 0 and accum_counter % gradient_accumulation_steps == 0:
                _save_state(step, epoch, model, optimizer, loss.item() * gradient_accumulation_steps, torch.get_rng_state())
                ckpt_dir = MODEL_DIR / "checkpoints" / f"step-{step}"
                ckpt_dir.mkdir(parents=True, exist_ok=True)
                model.save_pretrained(ckpt_dir)

        epoch += 1
        start_step = 0  # Nova época: ignora o offset de step.
        accum_counter = 0

    final_dir = output_dir or (MODEL_DIR / "final")
    final_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(final_dir)
    tokenizer.save_pretrained(final_dir)
    print("Modelo Mistral guardado em", final_dir)


def train_model(
    epochs: int = 1,
    batch_size: int = 4,
    max_length: int = 128,
    learning_rate: float = 5e-5,
    max_samples: int | None = None,
    save_checkpoints: bool = True,
    resume: bool = False,
    gradient_accumulation_steps: int = 1,
):
    """Treina com o dataset financeiro padrão (data/final/train.jsonl)."""
    texts = load_jsonl(FINAL_DIR / "train.jsonl")
    if max_samples:
        texts = texts[:max_samples]
    run_training(
        texts=texts,
        epochs=epochs,
        batch_size=batch_size,
        max_length=max_length,
        learning_rate=learning_rate,
        save_checkpoints=save_checkpoints,
        resume=resume,
        gradient_accumulation_steps=gradient_accumulation_steps,
        output_dir=MODEL_DIR / "final",
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Treina o modelo Mistral Finance-LLM")
    parser.add_argument("--epochs", type=int, default=1)
    parser.add_argument("--batch_size", type=int, default=4)
    parser.add_argument("--max_length", type=int, default=128)
    parser.add_argument("--learning_rate", type=float, default=5e-5)
    parser.add_argument("--max_samples", type=int, default=None)
    parser.add_argument("--gradient_accumulation_steps", type=int, default=1,
                        help="Número de mini-batches a acumular antes de efetuar optimizer.step().")
    parser.add_argument("--save_checkpoints", action="store_true", default=True)
    parser.add_argument("--resume", action="store_true", default=False,
                        help="Retoma treino a partir do ficheiro training/mistral_state.pt")
    parser.add_argument("--pause", action="store_true", default=False,
                        help="Cria training/pause.flag para pausar um treino em execução")
    parser.add_argument("--continue", dest="continue_", action="store_true", default=False,
                        help="Remove training/pause.flag para continuar um treino pausado")
    args = parser.parse_args()

    if args.pause:
        PAUSE_FLAG.touch(exist_ok=True)
        print("[PAUSE] flag criada. O treino em execução irá pausar no próximo batch.")
        sys.exit(0)
    if args.continue_:
        if PAUSE_FLAG.exists():
            PAUSE_FLAG.unlink()
            print("[CONTINUE] flag removida. Treino continua.")
        else:
            print("[CONTINUE] não há flag de pausa ativa.")
        sys.exit(0)

    train_model(
        epochs=args.epochs,
        batch_size=args.batch_size,
        max_length=args.max_length,
        learning_rate=args.learning_rate,
        max_samples=args.max_samples,
        save_checkpoints=args.save_checkpoints,
        resume=args.resume,
        gradient_accumulation_steps=args.gradient_accumulation_steps,
    )
