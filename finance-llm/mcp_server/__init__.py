"""Servidor MCP (Model Context Protocol) do IQ OS.

Expõe o backend `api.main` (porta 8002 por omissão) como ferramentas para
agentes de IA: ferramentas curadas por módulo, acesso genérico a qualquer
endpoint e a especificação OpenAPI como recurso.

Ver ``mcp_server/README.md`` e ``docs/API_SWAGGER_MCP.md``.
"""
from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
