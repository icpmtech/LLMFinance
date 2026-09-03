"""Treina o modelo Mistral com dados processados usando loop PyTorch manual.

Suporta pausa/continuação via sinal SIGUSR1/SIGUSR2 (Linux) ou ficheiro de
controlo ``training/pause.flag`` em todos os sistemas.
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


def train_model(
    epochs: int = 1,
    batch_size: int = 4,
    max_length: int = 128,
    learning_rate: float = 5e-5,
    max_samples: int | None = None,
    save_checkpoints: bool = True,
    resume: bool = False,
):
    _register_signals()
    tokenizer = PreTrainedTokenizerFast.from_pretrained(MODEL_DIR)
    model = MistralForCausalLM.from_pretrained(MODEL_DIR)

    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    model.config.pad_token_id = tokenizer.pad_token_id
    model.config.loss_type = "ForCausalLMLoss"

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model.to(device)

    texts = load_jsonl(FINAL_DIR / "train.jsonl")
    if max_samples:
        texts = texts[:max_samples]

    print(f"[TOKENIZE] tokenizando {len(texts)} exemplos com max_length={max_length}...")
    encodings = tokenizer(
        texts,
        truncation=True,
        padding="max_length",
        max_length=max_length,
        return_tensors="pt",
    )
    input_ids = encodings["input_ids"]
    attention_mask = encodings["attention_mask"]
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

    total_steps = len(loader) * epochs
    step = start_step
    epoch = start_epoch
    paused = False

    while epoch < epochs:
        for batch_idx, batch in enumerate(loader):
            pause_requested, resume_requested = _check_flag_and_signal()

            if pause_requested and not paused:
                _save_state(step, epoch, model, optimizer, loss.item() if 'loss' in locals() else 0.0, torch.get_rng_state())
                paused = True
                print("[PAUSED] treino em pausa. Apague training/pause.flag ou envie SIGUSR2 para continuar.")

            if paused:
                step += 1
                while paused:
                    _, resume_requested = _check_flag_and_signal()
                    if resume_requested or not PAUSE_FLAG.exists():
                        paused = False
                        print("[RESUMED] treino continua.")
                        break
                    time.sleep(1)
                continue

            step += 1
            if step <= start_step and resume:
                continue

            b_input, b_mask, b_labels = (x.to(device) for x in batch)
            optimizer.zero_grad()
            outputs = model(input_ids=b_input, attention_mask=b_mask, labels=b_labels)
            loss = outputs.loss
            loss.backward()
            optimizer.step()

            if step % 20 == 0:
                print(f"step {step}/{total_steps} | epoch {epoch+1}/{epochs} | loss {loss.item():.4f}")

            if save_checkpoints and step % 200 == 0:
                ckpt_dir = MODEL_DIR / "checkpoints" / f"step-{step}"
                ckpt_dir.mkdir(parents=True, exist_ok=True)
                model.save_pretrained(ckpt_dir)

        epoch += 1
        start_step = 0  # Nova época: ignora o offset de step.

    final_dir = MODEL_DIR / "final"
    final_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(final_dir)
    tokenizer.save_pretrained(final_dir)
    print("Modelo Mistral guardado em", final_dir)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Treina o modelo Mistral Finance-LLM")
    parser.add_argument("--epochs", type=int, default=1)
    parser.add_argument("--batch_size", type=int, default=4)
    parser.add_argument("--max_length", type=int, default=128)
    parser.add_argument("--learning_rate", type=float, default=5e-5)
    parser.add_argument("--max_samples", type=int, default=None)
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
    )
