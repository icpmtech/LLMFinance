#!/usr/bin/env python3
"""Recolha de **todas as empresas de um distrito** (todos os concelhos, todas as páginas).

Cada concelho fica em `data/scraper/exports/empresas/<distrito>/<concelho>/pagina_1_a_N.json`
e o estado de cada um em `<distrito>/_manifest.json`, o que permite retomar
(`--skip-done`, ligado por omissão).

Exemplos:
    python _run_empresas_recolha_distrito.py "Évora"
    python _run_empresas_recolha_distrito.py "Évora" --delay 0.5 --concelho alandroal
    python _run_empresas_recolha_distrito.py "Évora" --listar      # só mostra os concelhos
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[0] / "finance-llm"))

from api import empresas_recolha_service as service

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _para_ficheiro(caminho: str) -> None:
    """Acrescenta um destino de log em ficheiro (UTF-8, sem depender do terminal).

    Útil quando a recolha é arrancada sem consola (ex.: pelo serviço WMI) e o
    progresso de várias horas tem de ficar registado em disco.
    """
    path = Path(caminho).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.INFO)


def _progresso(evento: dict) -> None:
    tipo = evento.get("tipo")
    if tipo == "inicio":
        logger.info("Distrito %s: %d concelhos a recolher", evento["distrito"], len(evento["concelhos"]))
    elif tipo == "concelho_inicio":
        logger.info("[%d/%d] %s — a começar", evento["indice"] + 1, evento["total"], evento["concelho"])
    elif tipo == "concelho_fim":
        res = evento.get("resultado") or {}
        if evento.get("saltado"):
            logger.info("[%d/%d] %s — já feito (%d itens), saltado", evento["indice"] + 1, evento["total"], evento["concelho"], res.get("items_count", 0))
        else:
            logger.info(
                "[%d/%d] %s — %s itens, %s páginas → %s",
                evento["indice"] + 1,
                evento["total"],
                evento["concelho"],
                res.get("items_count"),
                res.get("pages"),
                res.get("file"),
            )


def main() -> int:
    parser = argparse.ArgumentParser(description="Recolha de todas as empresas de um distrito")
    parser.add_argument("distrito", help="Distrito (ex.: Évora)")
    parser.add_argument("--concelho", action="append", help="Limita a este concelho (pode repetir-se)")
    parser.add_argument("--start-page", type=int, default=1, help="Página inicial de cada concelho (padrão: 1)")
    parser.add_argument("--max-pages", type=int, default=service.DISTRICT_MAX_PAGES, help="Teto de páginas por concelho")
    parser.add_argument("--delay", type=float, default=0.5, help="Segundos entre pedidos de detalhe (padrão: 0.5)")
    parser.add_argument("--paralelo", type=int, default=1, help="Concelhos recolhidos ao mesmo tempo (1-6)")
    parser.add_argument("--no-detail", action="store_false", dest="detail", help="Não recolher o detalhe das fichas")
    parser.add_argument("--ingest", action="store_true", help="Indexar automaticamente (reservado)")
    parser.add_argument("--skip-done", action="store_true", default=True, help="Saltar concelhos já concluídos (padrão: sim)")
    parser.add_argument("--force", action="store_false", dest="skip_done", help="Refazer também os concelhos já concluídos")
    parser.add_argument("--listar", action="store_true", help="Só listar os concelhos e sair")
    parser.add_argument("--log", help="Ficheiro de log (UTF-8); útil sem consola")
    args = parser.parse_args()

    if args.log:
        _para_ficheiro(args.log)

    if args.listar:
        nomes = service.concelhos_do_site(args.distrito)
        print(f"{args.distrito}: {len(nomes)} concelhos")
        for nome in nomes:
            print(" ", nome)
        return 0

    resultado = service.run_district_sync(
        distrito=args.distrito,
        start_page=args.start_page,
        max_pages=args.max_pages,
        detail=args.detail,
        delay=args.delay,
        ingest=args.ingest,
        skip_done=args.skip_done,
        concelhos=args.concelho,
        paralelo=args.paralelo,
        on_progress=_progresso,
    )
    logger.info(
        "Concluído: %d/%d concelhos, %d empresas, manifesto %s",
        resultado["concelhos_ok"],
        resultado["total_concelhos"],
        resultado["total_items"],
        resultado["manifest"],
    )
    if resultado["falhados"]:
        logger.error("Concelhos com falha: %s", ", ".join(resultado["falhados"]))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
