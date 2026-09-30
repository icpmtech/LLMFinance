#!/usr/bin/env python3
"""Script de raiz para recolha massiva de empresas por distrito/concelho.

Exemplo:
    python _run_empresas_recolha.py "Évora" "Alandroal" --start-page 6 --max-pages 1 --detail

O resultado fica em `data/scraper/exports/empresas/<distrito>/<concelho>/pagina_X_a_Y.json`.
"""
from __future__ import annotations

import argparse
import logging
import sys

# Garantir que a raiz do projecto está no path.
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[0] / "finance-llm"))

from api import empresas_recolha_service as service

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description="Recolha massiva de empresas por distrito/concelho")
    parser.add_argument("distrito", help="Distrito (ex.: Évora)")
    parser.add_argument("concelho", help="Concelho (ex.: Alandroal)")
    parser.add_argument("--start-page", type=int, default=1, help="Página inicial (padrão: 1)")
    parser.add_argument("--max-pages", type=int, default=1, help="Número de páginas a recolher (padrão: 1)")
    parser.add_argument("--detail", action="store_true", default=True, help="Recolher detalhe (padrão: sim)")
    parser.add_argument("--no-detail", action="store_false", dest="detail", help="Não recolher detalhe")
    parser.add_argument("--delay", type=float, default=1.0, help="Segundos entre pedidos de detalhe (padrão: 1.0)")
    parser.add_argument("--job", action="store_true", help="Correr em segundo plano e devolver job_id")
    parser.add_argument("--ingest", action="store_true", help="Indexar automaticamente (reservado)")
    args = parser.parse_args()

    if args.job:
        res = service.start_job(
            distrito=args.distrito,
            concelho=args.concelho,
            start_page=args.start_page,
            max_pages=args.max_pages,
            detail=args.detail,
            delay=args.delay,
            ingest=args.ingest,
        )
        logger.info("Job arrancado: %s (%s)", res.get("job_id"), res.get("status"))
        print(res.get("job_id"))
        return 0

    res = service.run_sync(
        distrito=args.distrito,
        concelho=args.concelho,
        start_page=args.start_page,
        max_pages=args.max_pages,
        detail=args.detail,
        delay=args.delay,
        ingest=args.ingest,
    )
    if not res.get("ok"):
        logger.error("Recolha falhou: %s", res.get("error"))
        return 1

    logger.info("Recolha concluída: %s itens → %s", res.get("items_count"), res.get("file"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
