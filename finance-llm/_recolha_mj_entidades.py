"""Recolha automática de publicações do MJ por entidades indexadas (2captcha).

Usa o módulo societário do IQ OS para iterar pelas entidades do índice
``finance_entities`` e recolher as publicações de atos societários em
https://publicacoes.mj.pt. A resolução do reCAPTCHA é feita via 2captcha.

Exemplos
--------
    # Recolher as 10 entidades com mais contratos (todo o histórico)
    python _recolha_mj_entidades.py --limite 10

    # Recolher publicações dos últimos 90 dias para entidades específicas
    python _recolha_mj_entidades.py --nifs 500273170 501413197 --dias 90

    # Continuar de onde parou (ignorar entidades já recolhidas)
    python _recolha_mj_entidades.py --limite 50 --detalhe

    # Sem indexar, só guardar em JSON
    python _recolha_mj_entidades.py --nifs 500273170 --sem-indexar --output sonae.json
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("ELASTICSEARCH_URL", "http://127.0.0.1:9200")

from api import societario_service  # noqa: E402

logger = logging.getLogger("recolha_mj_entidades")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Recolha automática de publicações MJ por entidades indexadas (2captcha).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--nifs", nargs="+", help="NIFs/NIPC específicos a pesquisar")
    parser.add_argument("--limite", type=int, help="Máximo de entidades a recolher do índice")
    parser.add_argument("--min-contratos", type=int, default=1, help="Mínimo de contratos para uma entidade ser elegível")
    parser.add_argument("--incluir-recolhidas", action="store_true", help="Não excluir entidades já recolhidas")
    parser.add_argument("--dias", type=int, help="Limitar a publicações dos últimos N dias")
    parser.add_argument("--data-ini", help="Data inicial (AAAA-MM-DD)")
    parser.add_argument("--data-fim", help="Data final (AAAA-MM-DD)")
    parser.add_argument("--tipo", default="0", choices=sorted(societario_service.TIPOS_PUBLICACAO), help="Tipo de publicação")
    parser.add_argument("--max-paginas", type=int, default=50, help="Máximo de páginas da grelha por pesquisa")
    parser.add_argument("--intervalo", type=float, default=1.0, help="Intervalo mínimo entre pedidos ao portal (segundos)")
    parser.add_argument("--timeout-captcha", type=int, default=180, help="Timeout para resolução do reCAPTCHA")
    parser.add_argument("--sem-detalhe", action="store_true", help="Não abrir o detalhe de cada publicação")
    parser.add_argument("--sem-indexar", action="store_true", help="Não indexar no Elasticsearch")
    parser.add_argument("--parar-no-captcha", action="store_true", help="Parar se o captcha for rejeitado")
    parser.add_argument("--api-key", help="API key da 2captcha (ou env TWOCAPTCHA_API_KEY)")
    parser.add_argument("--output", help="Guardar itens num ficheiro JSON (além de indexar)")
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def resolve_dates(args: argparse.Namespace) -> tuple[Optional[str], Optional[str]]:
    """Determina o intervalo de datas a partir de --dias ou --data-ini/--data-fim."""
    if args.dias:
        fim = date.today()
        ini = fim - timedelta(days=args.dias - 1)
        return ini.isoformat(), fim.isoformat()
    return args.data_ini, args.data_fim


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    data_ini, data_fim = resolve_dates(args)

    print(
        f"Recolha automática MJ por entidades | "
        f"nifs={len(args.nifs) if args.nifs else 'do índice'} | "
        f"datas={data_ini or 'todas'}..{data_fim or 'todas'} | "
        f"detalhe={'não' if args.sem_detalhe else 'sim'} | "
        f"indexar={'não' if args.sem_indexar else 'sim'}",
        flush=True,
    )

    try:
        result = societario_service.collect_entities(
            api_key=args.api_key,
            nifs=args.nifs,
            limit=args.limite,
            min_contracts=args.min_contratos,
            exclude_collected=not args.incluir_recolhidas,
            data_ini=data_ini,
            data_fim=data_fim,
            tipo=args.tipo,
            with_details=not args.sem_detalhe,
            max_pages=args.max_paginas,
            min_interval=args.intervalo,
            recaptcha_timeout=args.timeout_captcha,
            ingest_result=not args.sem_indexar,
            stop_on_captcha=args.parar_no_captcha,
        )
    except Exception as exc:
        logger.exception("Falha na recolha automática")
        print(f"ERRO: {exc}", file=sys.stderr)
        return 1

    print(
        f"\nConcluído: {result['entities']} entidades | "
        f"{result['collected']} publicações recolhidas | "
        f"{result.get('ingested', result.get('total_ingested', 0))} indexadas | "
        f"{len(result['errors'])} erros",
        flush=True,
    )
    for err in result["errors"]:
        print(f"  ERRO {err['nif']}: {err['error']}", flush=True)

    if args.output:
        path = Path(args.output)
        path.write_text(json.dumps(result["items"], ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Itens guardados em {path}", flush=True)

    return 0 if not result["errors"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
