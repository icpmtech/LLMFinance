"""Ponto de entrada do servidor MCP do IQ OS.

Uso::

    # stdio (padrão, é assim que o VS Code e outros clientes o arrancam)
    python -m mcp_server

    # HTTP (streamable) para testar com o Inspector ou a partir da rede
    python -m mcp_server --transport streamable-http --port 8765

Variáveis de ambiente: ver `mcp_server/client.py`.
"""
from __future__ import annotations

import argparse
import os
import sys

from mcp_server.server import build_server, get_client, tool_report


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="mcp_server", description="Servidor MCP do IQ OS")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http", "sse"],
        default=os.getenv("IQOS_MCP_TRANSPORT", "stdio"),
        help="Transporte MCP (por omissão stdio).",
    )
    parser.add_argument("--host", default=os.getenv("IQOS_MCP_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("IQOS_MCP_PORT", "8765")))
    parser.add_argument("--path", default=os.getenv("IQOS_MCP_PATH", "/mcp"))
    parser.add_argument(
        "--list-tools",
        action="store_true",
        help="Imprime as ferramentas registadas e sai (verificação rápida).",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="Só o resumo do orçamento de ferramentas (quantas expõe e porquê) e sai.",
    )
    return parser.parse_args(argv)


def _print_report() -> None:
    """Resumo do orçamento de ferramentas: quantas são expostas e com que grupos."""
    report = tool_report()
    print(f"catálogo: {report['catalog']} operações")
    print(f"expostas: {report['selected']} curadas + {report['generic']} genéricas = {report['total']}")
    print("grupos: " + (", ".join(report["tags"]) or "(nenhum)"))
    print(f"teto IQOS_MCP_MAX_TOOLS: {report['limit'] or 'sem teto'}")
    for name, value in report["env"].items():
        print(f"{name}={value or '(vazio)'}")
    if report["over_client_limit"]:
        print(
            f"AVISO: {report['total']} ferramentas excedem o limite de {report['client_limit']} "
            "funções por pedido de alguns clientes (DeepSeek). Use IQOS_MCP_TAGS para expor menos grupos."
        )


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    if args.report:
        _print_report()
        return 0

    server = build_server()

    if args.list_tools:
        import asyncio

        _print_report()
        for tool in asyncio.run(server.list_tools()):
            print(f"{tool.name}\t{tool.description or ''}")
        return 0

    client = get_client()
    print(
        f"Servidor MCP do IQ OS ({args.transport}) → API {client.base_url}"
        f"{' autenticada' if client.token else ' sem token'}",
        file=sys.stderr,
    )

    if args.transport == "stdio":
        server.run(transport="stdio")
    elif args.transport == "sse":
        server.run(transport="sse", host=args.host, port=args.port)
    else:
        server.run(transport="streamable-http", host=args.host, port=args.port, streamable_http_path=args.path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
