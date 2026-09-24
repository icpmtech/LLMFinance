"""Recolha histórica do CIRE (insolvências) — 2020→hoje, em segundo plano.

Percorre o intervalo de datas em **janelas** (uma recolha/ficheiro JSON por
janela) e importa cada janela para o Elasticsearch logo a seguir. Como o
progresso fica registado em `data/cire/runs/*.meta.json`, o processo é
**retomável**: voltar a arrancá-lo (sem `--force`) salta as janelas já
processadas e avisa no log.

Uso::

    python _recolha_cire_historico.py --desde 2020-01-01 --ate 2026-09-23 \
        --window-days 31 --max-pages 3000 --min-interval 1.0

O estado corrente fica em `data/cire/historico_status.json` e o log em
`logs/cire_historico.out`.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from api import cire_service  # noqa: E402

STATUS_PATH = ROOT / "data" / "cire" / "historico_status.json"
LOG_PATH = ROOT / "logs" / "cire_historico.out"
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)


def _escrever_status(dados: dict) -> None:
    """Grava o estado da recolha (consultável enquanto o processo corre)."""
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATUS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATUS_PATH)


def main() -> int:
    parser = argparse.ArgumentParser(description="Recolha histórica do CIRE (janelas de datas).")
    parser.add_argument("--desde", default="2020-01-01", help="Data inicial (AAAA-MM-DD)")
    parser.add_argument("--ate", default=datetime.now().date().isoformat(), help="Data final (AAAA-MM-DD)")
    parser.add_argument("--window-days", type=int, default=31, help="Tamanho de cada janela (dias)")
    parser.add_argument("--max-pages", type=int, default=3000, help="Máximo de páginas por janela (10 docs/página)")
    parser.add_argument("--min-interval", type=float, default=1.0, help="Pausa entre pedidos (segundos)")
    parser.add_argument("--force", action="store_true", help="Reprocessar janelas já recolhidas")
    parser.add_argument("--no-index", action="store_true", help="Só gravar JSON (não importar)")
    args = parser.parse_args()

    janelas = cire_service._windows(  # noqa: SLF001
        cire_service.normalize_date(args.desde), cire_service.normalize_date(args.ate), args.window_days
    )
    total_previstas = len(janelas)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"), logging.StreamHandler(sys.stdout)],
    )
    log = logging.getLogger("cire-historico")

    def on_progress(info: dict) -> None:
        etapa = info.get("stage")
        if etapa == "window":
            janela = info.get("window") or {}
            log.info(
                "janela %s/%s %s → %s | docs %s | páginas %s | recolhas %s | indexados %s",
                info.get("window_index"),
                info.get("window_total"),
                janela.get("desde"),
                janela.get("ate"),
                info.get("total_collected"),
                info.get("pages"),
                info.get("runs"),
                info.get("indexed"),
            )
            _escrever_status(
                {
                    "estado": "a correr",
                    "iniciado_em": iniciado,
                    "atualizado_em": datetime.now(timezone.utc).isoformat(),
                    "intervalo": {"desde": args.desde, "ate": args.ate},
                    "janelas_previstas": total_previstas,
                    "janela_atual": janela,
                    "janela_numero": info.get("window_index"),
                    "documentos": info.get("total_collected"),
                    "paginas": info.get("pages"),
                    "recolhas": info.get("runs"),
                    "indexados": info.get("indexed"),
                }
            )
        elif etapa == "collecting":
            janela = info.get("window") or {}
            log.info(
                "  página %s de %s → %s (declarado %s) | recolhidos %s",
                info.get("page"),
                janela.get("ate"),
                janela.get("desde"),
                info.get("declared_total"),
                info.get("collected"),
            )
            # Estado em direto: escreve a cada 20 páginas (e não a cada página).
            pagina = int(info.get("page") or 0)
            if pagina % 20 == 0:
                _escrever_status(
                    {
                        "estado": "a correr",
                        "iniciado_em": iniciado,
                        "atualizado_em": datetime.now(timezone.utc).isoformat(),
                        "intervalo": {"desde": args.desde, "ate": args.ate},
                        "janelas_previstas": total_previstas,
                        "janela_atual": janela,
                        "pagina_atual": pagina,
                        "recolhidos_janela": info.get("collected"),
                        "declarado_janela": info.get("declared_total"),
                        "paginas_totais": info.get("pages"),
                        "recolhas": info.get("runs"),
                        "indexados": info.get("indexed"),
                    }
                )

    iniciado = datetime.now(timezone.utc).isoformat()
    inicio = time.monotonic()
    log.info(
        "início da recolha histórica: %s → %s | janelas: %s × %s dias | max_pages %s | indexar: %s | force: %s",
        args.desde, args.ate, total_previstas, args.window_days, args.max_pages, not args.no_index, args.force,
    )
    _escrever_status(
        {
            "estado": "a iniciar",
            "iniciado_em": iniciado,
            "intervalo": {"desde": args.desde, "ate": args.ate},
            "janelas_previstas": total_previstas,
        }
    )

    try:
        resultado = cire_service.collect(
            desde=args.desde,
            ate=args.ate,
            window_days=args.window_days,
            max_pages=args.max_pages,
            min_interval=args.min_interval,
            force=args.force,
            split_runs=True,
            ingest_each=not args.no_index,
            on_progress=on_progress,
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("recolha falhou")
        _escrever_status(
            {
                "estado": "erro",
                "iniciado_em": iniciado,
                "atualizado_em": datetime.now(timezone.utc).isoformat(),
                "erro": str(exc),
            }
        )
        return 1

    meta = resultado["meta"]
    duracao = time.monotonic() - inicio
    janelas_com_dados = [w for w in meta.get("windows") or [] if (w.get("collected") or 0) > 0]
    truncadas = [
        w for w in meta.get("windows") or []
        if (w.get("pages") or 0) >= args.max_pages and (w.get("total") or 0) > args.max_pages * 10
    ]
    log.info("=" * 80)
    log.info(
        "fim: %s documentos em %s janelas (%s recolhas) | páginas %s | indexados %s | ignorados (já no índice) %s",
        meta["collected"], len(janelas_com_dados), len(meta.get("runs") or []), meta["pages"],
        meta.get("indexed"), meta.get("skipped_existing"),
    )
    log.info("duração: %.1f min | janelas ignoradas (já processadas): %s", duracao / 60, len(meta.get("skipped_windows") or []))
    for aviso in meta.get("warnings") or []:
        log.warning("AVISO: %s", aviso)
    for erro in meta.get("errors") or []:
        log.error("ERRO: %s", erro)
    if truncadas:
        log.warning("janelas possivelmente truncadas (max_pages=%s): %s", args.max_pages, len(truncadas))

    _escrever_status(
        {
            "estado": "concluído",
            "iniciado_em": iniciado,
            "atualizado_em": datetime.now(timezone.utc).isoformat(),
            "intervalo": {"desde": args.desde, "ate": args.ate},
            "janelas_previstas": total_previstas,
            "janelas_com_dados": len(janelas_com_dados),
            "janelas_ignoradas": len(meta.get("skipped_windows") or []),
            "documentos": meta["collected"],
            "paginas": meta["pages"],
            "recolhas": meta.get("runs") or [],
            "indexados": meta.get("indexed"),
            "ignorados_ja_no_indice": meta.get("skipped_existing"),
            "erros": meta.get("errors") or [],
            "avisos": meta.get("warnings") or [],
            "duracao_min": round(duracao / 60, 1),
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
