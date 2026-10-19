"""Recolhe as declarações da **Entidade para a Transparência** (scraper).

Percorre a cascata da plataforma — **entidade → cargo → titular** — e, por cada
titular, lê as declarações únicas (facto determinante, dados pessoais,
rendimentos, ativo, passivo e registo de interesses). Grava JSONL em
`data/entidade-transparencia` e, com `--indexar`, alimenta os índices
`finance_ept_*` do Elasticsearch.

É o mesmo trabalho que `POST /entidade-transparencia/recolher` faz a pedido da
interface; este script permite corrê-lo fora da API (por exemplo, numa tarefa
agendada) e ver o relatório final.

Uso::

    python scripts/recolher_entidade_transparencia.py --entidade 2 --limite 50
    python scripts/recolher_entidade_transparencia.py --titular 4952
    python scripts/recolher_entidade_transparencia.py --tudo --indexar
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api import entidade_transparencia_service as ept  # noqa: E402
from collectors.entidade_transparencia import PAUSA  # noqa: E402


def _progresso(progresso: dict) -> None:
    fase = progresso.get("phase") or ""
    titulares = f"{progresso.get('titulares_done', 0)}/{progresso.get('titulares_total', 0)}"
    print(
        f"\r{fase:24} titulares {titulares:>12} · declarações novas {progresso.get('declaracoes', 0):>6}"
        f" · {progresso.get('current') or ''}",
        end="",
        flush=True,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Recolha das declarações da Entidade para a Transparência.")
    parser.add_argument("--entidade", help="Id da entidade (passo 1 da cascata)")
    parser.add_argument("--cargo", help="Id do cargo (passo 2 da cascata)")
    parser.add_argument("--titular", help="Id do titular (recolhe só este)")
    parser.add_argument("--limite", type=int, default=None, help="Máximo de titulares a percorrer")
    parser.add_argument("--declaracoes", type=int, default=None, help="Máximo de declarações por titular")
    parser.add_argument("--pausa", type=float, default=PAUSA, help="Pausa entre pedidos, em segundos")
    parser.add_argument("--forcar", action="store_true", help="Reler o que já está em disco")
    parser.add_argument("--indexar", action="store_true", help="Indexar em finance_ept_* no fim")
    parser.add_argument("--tudo", action="store_true", help="Percorrer o catálogo completo (sem filtros)")
    args = parser.parse_args(argv)

    if not args.tudo and not any((args.entidade, args.cargo, args.titular)):
        parser.error("Indique --entidade/--cargo/--titular, ou --tudo para o catálogo completo.")

    progresso: dict = {}
    resultado = ept.recolher(
        entidade_id=args.entidade,
        cargo_id=args.cargo,
        titular_id=args.titular,
        limite_titulares=args.limite,
        limite_declaracoes=args.declaracoes,
        pausa=args.pausa,
        forcar=args.forcar,
        indexar_no_fim=args.indexar,
        progresso=progresso,
    )
    _progresso(progresso)
    print("\n")
    print(json.dumps({chave: valor for chave, valor in resultado.items() if chave != "errors"}, ensure_ascii=False, indent=2))

    erros = resultado.get("errors") or []
    if erros:
        print(f"\n{len(erros)} erro(s):")
        for erro in erros[:20]:
            print(f"  {erro}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
