"""Runner de background para a recolha contínua da RigorBiz.

Usado pelo endpoint ``POST /rigorbiz/collect`` e executável standalone.
Enquanto recolhe, grava estado em tempo real em
``data/rigorbiz/rigorbiz_runner_state.json`` — é este ficheiro que alimenta a
página de monitorização ``/rigorbiz/collector``.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "data" / "rigorbiz" / "rigorbiz_runner_state.json"
LOG_PATH = ROOT / "data" / "rigorbiz" / "rigorbiz_collector.log"

logger = logging.getLogger(__name__)


def _setup_file_logging() -> None:
    """Garante que a recolha escreve num log consultável pela UI."""
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    target = str(LOG_PATH.resolve())
    for handler in logging.getLogger().handlers:
        if isinstance(handler, logging.FileHandler) and getattr(handler, "baseFilename", "") == target:
            return
    handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.INFO)



def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_state() -> Dict[str, Any]:
    if not STATE_PATH.exists():
        return {"running": False}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"running": False}


def _save_state(state: Dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {**state, "updated_at": _now()}
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, STATE_PATH)


def _on_progress(payload: Dict[str, Any]) -> None:
    state = _load_state()
    # O pedido de paragem vem de fora (`stop()`); nunca o apagamos aqui.
    stop_requested = bool(state.get("stop_requested"))
    state.update(payload)
    state["running"] = payload.get("kind") != "done"
    state["stop_requested"] = stop_requested
    _save_state(state)


def _should_stop() -> bool:
    return bool(_load_state().get("stop_requested"))


def run(
    mode: str = "all",
    pages: int = 1000,
    delay: float = 4.0,
    index_to_es: bool = True,
) -> Dict[str, Any]:
    """Executa a recolha e mantém o estado do runner atualizado."""
    from api.rigorbiz_collector import (
        DEFAULT_DELAY,
        _load_checkpoint,
        _read_jsonl,
        collect_all,
        collect_sample,
    )

    current = _load_state()
    if current.get("running"):
        logger.info("Já existe uma recolha em curso; não se arranca outra.")
        return {"ok": False, "already_running": True, "state": current}

    _setup_file_logging()

    checkpoint = _load_checkpoint()
    _save_state(
        {
            "running": True,
            "stop_requested": False,
            "mode": mode,
            "pages": pages,
            "delay": delay,
            "started_at": _now(),
            "start_page": int(checkpoint.get("last_page", 0)) + 1,
            "total_announced": checkpoint.get("total"),
            "collected": 0,
            "indexed": 0,
            "page": int(checkpoint.get("last_page", 0)),
            "unique_total": len(_read_jsonl()),
            "error": None,
        }
    )

    try:
        if mode != "all":
            result = collect_sample(max_pages=pages, delay=delay, index_to_es=index_to_es)
            _save_state(
                {
                    "running": False,
                    "mode": mode,
                    "ok": True,
                    "unique_total": result.get("unique_total"),
                    "indexed": result.get("indexed", 0),
                    "collected": result.get("collected", 0),
                    "completed": False,
                    "finished_at": _now(),
                }
            )
            return result

        result = collect_all(
            delay=delay,
            index_to_es=index_to_es,
            on_progress=_on_progress,
            should_stop=_should_stop,
        )

        state = _load_state()
        state.update(
            {
                "running": False,
                "ok": bool(result.get("ok")),
                "completed": bool(result.get("completed")),
                "stopped": bool(result.get("stopped")),
                "unique_total": result.get("unique_total"),
                "indexed": result.get("indexed", 0),
                "collected": result.get("collected", 0),
                "page": result.get("last_page"),
                "total_announced": result.get("total_announced"),
                "finished_at": _now(),
            }
        )
        _save_state(state)
        return result
    except Exception as exc:  # noqa: BLE001 — o estado tem de refletir a falha
        state = _load_state()
        state.update({"running": False, "error": str(exc), "finished_at": _now()})
        _save_state(state)
        logger.exception("RigorBiz runner falhou")
        raise


def get_state() -> Dict[str, Any]:
    """Estado atual do runner (lido pelo endpoint de monitorização)."""
    return _load_state() or {"running": False}


def stop() -> None:
    """Pede a paragem graciosamente (o coletor termina a página em curso)."""
    state = _load_state()
    state["stop_requested"] = True
    state["stop_requested_at"] = _now()
    _save_state(state)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    from api.rigorbiz_collector import DEFAULT_DELAY

    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    pages = int(sys.argv[2]) if len(sys.argv) > 2 else 1000
    delay = float(sys.argv[3]) if len(sys.argv) > 3 else DEFAULT_DELAY
    print(json.dumps(run(mode=mode, pages=pages, delay=delay), ensure_ascii=False, indent=2))
