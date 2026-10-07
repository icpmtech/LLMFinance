"""Backfill dos embeddings do índice `contratos` — correr em segundo plano.

O índice tem ~2,25 M de contratos e só ~510 com `embedding`, o que faz a
«Pesquisa profunda» **saltar** o âmbito dos contratos na parte semântica
(`MIN_VECTOR_PERCENT`). Este script preenche o campo em blocos, retomando
sempre de onde ficou (só pede documentos sem `embedding`), por isso pode ser
interrompido e voltar a arrancar sem repetir trabalho.

Uso:
    python logs/_backfill_contratos.py                 # até ao fim
    python logs/_backfill_contratos.py --max-docs 5000 # piloto (mede ritmo)
    python logs/_backfill_contratos.py --index finance_entities
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

LOG = RAIZ / "logs" / "_backfill_contratos.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG, encoding="utf-8"), logging.StreamHandler(sys.stdout)],
)
# O cliente do Elasticsearch é ruidoso (um aviso por pedido); só queremos o essencial.
logging.getLogger("elastic_transport").setLevel(logging.ERROR)
logging.getLogger("elasticsearch").setLevel(logging.ERROR)
logging.getLogger("urllib3").setLevel(logging.ERROR)

from api import vector_service as vs  # noqa: E402


def _status(index: str) -> dict:
    """Cobertura atual do índice (com e sem `embedding`)."""
    es = vs.get_es_client()
    total = es.count(index=index).get("count", 0)
    com = es.count(index=index, body={"query": {"exists": {"field": "embedding"}}}).get("count", 0)
    return {"total": total, "com": com, "sem": total - com}


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill de embeddings (retomável).")
    parser.add_argument("--index", default=vs.CONTRACTS_INDEX, help="Índice a preencher.")
    parser.add_argument("--batch-size", type=int, default=256, help="Documentos por lote de codificação.")
    parser.add_argument("--chunk", type=int, default=20000, help="Documentos por chamada (para reportar progresso).")
    parser.add_argument("--max-docs", type=int, default=0, help="Limite total de documentos (0 = sem limite).")
    parser.add_argument("--model", default=vs.DEFAULT_MODEL_NAME, help="Modelo sentence-transformers.")
    args = parser.parse_args()

    inicio = time.time()
    estado = _status(args.index)
    logging.info(
        "%s: %s documentos, %s com embedding, %s em falta (%.2f%% coberto)",
        args.index,
        f"{estado['total']:,}",
        f"{estado['com']:,}",
        f"{estado['sem']:,}",
        100.0 * estado["com"] / estado["total"] if estado["total"] else 0.0,
    )
    if estado["sem"] == 0:
        logging.info("nada a fazer")
        return 0

    # Carrega o modelo antes de contar o ritmo (a primeira codificação é a mais lenta).
    vs._get_embedding_model(args.model)
    logging.info("modelo %s carregado", args.model)

    feitos = 0
    falhas = 0
    ciclos = 0
    while True:
        if args.max_docs and feitos >= args.max_docs:
            logging.info("limite de %s documentos atingido", f"{args.max_docs:,}")
            break

        restante = (args.max_docs - feitos) if args.max_docs else args.chunk
        t0 = time.time()
        try:
            resultado = vs.index_missing_embeddings(
                args.index,
                batch_size=args.batch_size,
                max_docs=min(args.chunk, restante),
                model_name=args.model,
            )
        except Exception as erro:  # noqa: BLE001
            falhas += 1
            logging.error("ciclo %d falhou (%s: %s); nova tentativa em 15 s", ciclos + 1, type(erro).__name__, erro)
            if falhas >= 20:
                logging.error("demasiadas falhas seguidas; a parar")
                break
            time.sleep(15)
            continue

        if resultado.get("error"):
            logging.error("ciclo %d: %s", ciclos + 1, resultado["error"])
            time.sleep(30)
            falhas += 1
            if falhas >= 5:
                break
            continue

        feitos += int(resultado.get("indexed") or 0)
        gasto = max(time.time() - t0, 0.001)
        ciclos += 1
        ritmo = feitos / (time.time() - inicio)
        if ritmo > 0:
            eta = (estado["sem"] - feitos) / ritmo
            eta_txt = f"{eta / 3600:.1f} h" if eta > 3600 else f"{eta / 60:.0f} min"
        else:
            eta_txt = "?"
        logging.info(
            "ciclo %d: +%s (erros %s) | %s feitos em %.1f min | %.0f docs/s | restam ~%s",
            ciclos,
            f"{resultado.get('indexed') or 0:,}",
            f"{resultado.get('errors') or 0:,}",
            f"{feitos:,}",
            gasto / 60 if ciclos == 1 else (time.time() - inicio) / 60,
            ritmo,
            eta_txt,
        )

        if not resultado.get("indexed"):
            logging.info("o Elasticsearch não devolveu mais documentos sem embedding")
            break

    estado = _status(args.index)
    logging.info(
        "FIM: %s com embedding de %s (%.2f%%), %s em falta, %s falhas, %.1f min",
        f"{estado['com']:,}",
        f"{estado['total']:,}",
        100.0 * estado["com"] / estado["total"] if estado["total"] else 0.0,
        f"{estado['sem']:,}",
        falhas,
        (time.time() - inicio) / 60,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
