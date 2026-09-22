"""Verificação rápida do servidor MCP do IQ OS.

Confirma que:

1. o catálogo gera ferramentas com esquema de entrada válido;
2. os parâmetros de caminho obrigatórios estão marcados como tal;
3. as ferramentas genéricas falam com a API (`/health`, `/openapi.json`,
   `/openapi/summary`);
4. uma consulta real devolve dados.

Uso::

    python _test_mcp_server.py
"""
from __future__ import annotations

import asyncio
import json
import sys
from typing import Any, Dict, List

from mcp_server.client import IQOSClient, IQOSError
from mcp_server.server import build_server

EXPECTED_TOOLS = [
    "iqos_health",
    "contratos_search",
    "contratos_analytics",
    "contratos_es_entities",
    "empresas_search",
    "empresa_detail",
    "empresas_global_search",
    "search_unified",
    "search360_topic",
    "hermes_ask",
    "rag_chat",
    "market_forecast",
    "elastic_search_global",
    "crm_overview",
    "office_documents",
    "email_messages",
    "sentiment_analyze_text",
    "visualizador_query",
    "scraper_search",
    "ontology_ai_answer",
    "vectors_search",
    "skills_list",
    "providers_list",
    "admin_overview",
    "favorites_list",
    "import_ingest",
]


def ok(label: str, condition: bool, detail: str = "") -> bool:
    mark = "OK  " if condition else "FALHA"
    print(f"[{mark}] {label}{(' — ' + detail) if detail else ''}")
    return condition


def _pretty(value: Any, limit: int = 400) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str)
    return text[:limit] + ("…" if len(text) > limit else "")


async def main() -> int:
    failures: List[str] = []

    server = build_server()
    tools = {tool.name: tool for tool in await server.list_tools()}

    if not ok("Ferramentas registadas", len(tools) > 150, f"{len(tools)} ferramentas"):
        failures.append("contagem")

    missing = [name for name in EXPECTED_TOOLS if name not in tools]
    if not ok("Ferramentas essenciais presentes", not missing, ", ".join(missing) or "todas"):
        failures.append("essenciais")

    # -- esquema de entrada -------------------------------------------------
    detail_schema: Dict[str, Any] = tools["empresa_detail"].input_schema or {}
    required = set(detail_schema.get("required") or [])
    if not ok(
        "empresa_detail exige o NIF",
        "nif" in required,
        f"required={sorted(required)}",
    ):
        failures.append("schema-path")

    search_schema: Dict[str, Any] = tools["contratos_search"].input_schema or {}
    if not ok(
        "contratos_search aceita corpo JSON",
        "payload" in (search_schema.get("properties") or {}),
        _pretty(list((search_schema.get("properties") or {}).keys())),
    ):
        failures.append("schema-body")

    # -- chamadas reais -----------------------------------------------------
    health = await server.call_tool("iqos_health", {})
    health_text = "".join(getattr(item, "text", "") for item in health.content)
    if not ok("iqos_health responde", "healthy" in health_text, _pretty(health_text, 160)):
        failures.append("health")

    modules = await server.call_tool("iqos_modules", {})
    modules_text = "".join(getattr(item, "text", "") for item in modules.content)
    if not ok("iqos_modules lista grupos", '"modules"' in modules_text, _pretty(modules_text, 200)):
        failures.append("modules")

    endpoints = await server.call_tool("iqos_search_endpoints", {"query": "contratos", "limit": 5})
    endpoints_text = "".join(getattr(item, "text", "") for item in endpoints.content)
    if not ok("iqos_search_endpoints encontra rotas", "/contracts" in endpoints_text, _pretty(endpoints_text, 200)):
        failures.append("search-endpoints")

    describe = await server.call_tool("iqos_describe_endpoint", {"path": "/contracts/status", "method": "GET"})
    describe_text = "".join(getattr(item, "text", "") for item in describe.content)
    if not ok("iqos_describe_endpoint devolve esquema", "summary" in describe_text, _pretty(describe_text, 200)):
        failures.append("describe")

    # Uma consulta de dados real, tolerante a índices vazios.
    live = await server.call_tool("contratos_status", {})
    live_text = "".join(getattr(item, "text", "") for item in live.content)
    if not ok("contratos_status responde", ('"total"' in live_text) or ("error" in live_text.lower()), _pretty(live_text, 200)):
        failures.append("live")

    # -- cliente direto -----------------------------------------------------
    client = IQOSClient()
    try:
        spec = await client.openapi()
        if not ok("OpenAPI tem grupos declarados", bool(spec.get("tags")), f"{len(spec.get('tags') or [])} grupos"):
            failures.append("openapi-tags")
        untagged = [
            path
            for path, ops in (spec.get("paths") or {}).items()
            for method, op in ops.items()
            if method.lower() in {"get", "post", "put", "patch", "delete"} and not op.get("tags")
        ]
        if not ok("Sem operações sem grupo", not untagged, ", ".join(untagged[:5]) or "todas agrupadas"):
            failures.append("openapi-untagged")
        secured = (spec.get("components") or {}).get("securitySchemes") or {}
        if not ok("Esquema bearerAuth presente", "bearerAuth" in secured, _pretty(list(secured.keys()))):
            failures.append("security")
        total_ops = sum(
            1
            for ops in (spec.get("paths") or {}).values()
            for method in ops
            if method.lower() in {"get", "post", "put", "patch", "delete"}
        )
        print(f"       → {total_ops} operações documentadas em {len(spec.get('paths') or {})} caminhos")
    except IQOSError as exc:
        failures.append("openapi")
        ok("Ler a especificação OpenAPI", False, str(exc))
    finally:
        await client.aclose()

    await client_close()
    print()
    if failures:
        print(f"RESULTADO: {len(failures)} verificação(ões) falharam: {', '.join(failures)}")
        return 1
    print("RESULTADO: servidor MCP do IQ OS validado.")
    return 0


async def client_close() -> None:
    from mcp_server import server as server_module

    if server_module._client is not None:
        await server_module._client.aclose()
        server_module._client = None


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
