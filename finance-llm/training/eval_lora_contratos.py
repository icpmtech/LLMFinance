"""CLI de avaliação do modelo de contratos (a lógica está em `inference/contratos_eval.py`).

Compara o modelo base com o adaptador LoRA no conjunto held-out e escreve o
resultado em `model/qwen05-contratos/eval.json`. Com `--indexar`, guarda também
o resumo no índice `finance_llm_model_evals` (é o que a página do modelo lê).

    python training/eval_lora_contratos.py --limite 12 --gerar 3
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from inference.contratos_eval import DATA_FILE, evaluate  # noqa: E402
from inference.contratos_lora import DEFAULT_ADAPTER_DIR, DEFAULT_BASE_MODEL  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Avalia o adaptador LoRA do modelo de contratos.")
    parser.add_argument("--pairs", type=Path, default=DATA_FILE)
    parser.add_argument("--base", default=DEFAULT_BASE_MODEL)
    parser.add_argument("--adapter", type=Path, default=DEFAULT_ADAPTER_DIR)
    parser.add_argument("--holdout", type=int, default=60, help="Pares reservados (igual ao treino)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--limite", type=int, default=12, help="Pares a medir (0 = todos)")
    parser.add_argument("--gerar", type=int, default=3, help="Respostas geradas para medir fidelidade")
    parser.add_argument("--out", type=Path, default=None, help="JSON de saída (padrão: <adapter>/eval.json)")
    parser.add_argument("--indexar", action="store_true", help="Guardar o resultado no Elasticsearch")
    args = parser.parse_args()

    resultado = evaluate(
        pairs_path=args.pairs,
        base_model=args.base,
        adapter_dir=args.adapter,
        holdout=args.holdout,
        seed=args.seed,
        limite=args.limite,
        gerar=args.gerar,
    )

    destino = args.out or (Path(args.adapter) / "eval.json")
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")
    resumo = {k: resultado[k] for k in ("base", "treinado", "delta") if k in resultado}
    print(json.dumps(resumo, ensure_ascii=False, indent=2))
    print(f"[AVALIAÇÃO] guardada em {destino}")

    if args.indexar:
        from api import llm_contratos_service as service

        doc_id = service.index_eval(resultado)
        print(f"[ÍNDICE] resultado guardado em finance_llm_model_evals/{doc_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
