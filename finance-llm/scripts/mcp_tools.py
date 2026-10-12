"""Orçamento de ferramentas do servidor MCP do IQ OS.

Os clientes de IA limitam o número de **funções por pedido** (o DeepSeek recusa
acima de 128) e a conta inclui as ferramentas internas do próprio cliente
(ficheiro, terminal, browser, …). O catálogo do IQ OS tem 224 operações curadas:
expô-las todas faz o agente falhar antes de responder.

Este utilitário ajuda a escolher os grupos certos e a confirmar que a seleção
cabe no orçamento.

Uso::

    # tabela de grupos e quantas ferramentas cada um traz
    python scripts/mcp_tools.py

    # simular uma seleção (não altera nada)
    python scripts/mcp_tools.py --tags contratos,empresas,deep-search,hermes --max 40

    # falha (código 1) se a seleção passar o orçamento — útil em CI
    python scripts/mcp_tools.py --tags contratos,empresas --budget 60

As variáveis de ambiente do servidor (`IQOS_MCP_TAGS`, `IQOS_MCP_EXCLUDE_TAGS`,
`IQOS_MCP_MAX_TOOLS`) são respeitadas quando as opções não são indicadas.
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mcp_server.catalog import OPERATIONS  # noqa: E402
from mcp_server.server import CLIENT_TOOL_LIMIT, GENERIC_TOOLS  # noqa: E402

#: Orçamento sugerido para as ferramentas do IQ OS quando o cliente limita a 128
#: funções por pedido e traz as suas próprias (VS Code/Copilot ronda as 80).
DEFAULT_BUDGET = 40


def _table(per_tag: Counter) -> None:
    print(f"{'grupo':<22}{'ferramentas':>12}")
    for tag, count in sorted(per_tag.items(), key=lambda item: (-item[1], item[0])):
        print(f"{tag:<22}{count:>12}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mcp_tools", description="Orçamento de ferramentas do MCP do IQ OS")
    parser.add_argument("--tags", default=os.environ.get("IQOS_MCP_TAGS", ""), help="grupos a expor (vírgulas)")
    parser.add_argument("--exclude", default=os.environ.get("IQOS_MCP_EXCLUDE_TAGS", ""), help="grupos a excluir")
    parser.add_argument("--max", type=int, default=int(os.environ.get("IQOS_MCP_MAX_TOOLS", "0") or 0), help="teto de ferramentas curadas")
    parser.add_argument("--budget", type=int, default=DEFAULT_BUDGET, help=f"orçamento total a respeitar (por omissão {DEFAULT_BUDGET})")
    args = parser.parse_args(argv)

    per_tag = Counter(op.tag for op in OPERATIONS)
    print(f"catálogo: {len(OPERATIONS)} ferramentas em {len(per_tag)} grupos (+{GENERIC_TOOLS} genéricas)\n")
    _table(per_tag)

    wanted = {tag.strip() for tag in args.tags.split(",") if tag.strip()}
    excluded = {tag.strip() for tag in args.exclude.split(",") if tag.strip()}
    selected = [
        op
        for op in OPERATIONS
        if (not wanted or op.tag in wanted) and op.tag not in excluded
    ]
    if args.max:
        selected = selected[: args.max]

    print("\nseleção:")
    if wanted:
        for tag in sorted(wanted):
            print(f"  {tag:<20}{per_tag.get(tag, 0):>5}")
        unknown = sorted(wanted - set(per_tag))
        if unknown:
            print("  grupos desconhecidos:", ", ".join(unknown))
    if excluded:
        print("  excluídos:", ", ".join(sorted(excluded)))
    total = len(selected) + GENERIC_TOOLS
    print(f"  curadas: {len(selected)} + genéricas: {GENERIC_TOOLS} = {total}")

    if total > args.budget:
        print(
            f"\nACIMA DO ORÇAMENTO: {total} > {args.budget}. "
            "Retire grupos (ver a tabela) ou baixe IQOS_MCP_MAX_TOOLS."
        )
        return 1
    if total > CLIENT_TOOL_LIMIT:
        print(f"\nAVISO: {total} excede o limite de {CLIENT_TOOL_LIMIT} funções por pedido do DeepSeek.")
        return 1
    print(f"\ndentro do orçamento ({total} ≤ {args.budget}); limite do cliente: {CLIENT_TOOL_LIMIT}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
