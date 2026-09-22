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

from mcp_server.server import build_server, get_client


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
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    server = build_server()

    if args.list_tools:
        import asyncio

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
