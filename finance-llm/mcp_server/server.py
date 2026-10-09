"""Servidor MCP do IQ OS.

Liga o catálogo (`mcp_server.catalog`) às ferramentas do protocolo MCP,
usando o cliente HTTP (`mcp_server.client`).

Ferramentas disponíveis:

* uma por operação curada do catálogo (``rag_chat``, ``contratos_search``,
  ``empresa_detail``, …), com assinatura tipada e descrição em português;
* ``iqos_api_call`` — chamada genérica a qualquer endpoint da API;
* ``iqos_search_endpoints`` — pesquisa na especificação OpenAPI;
* ``iqos_describe_endpoint`` — esquema completo de um endpoint;
* ``iqos_modules`` — módulos da plataforma e respetivas descrições.

Recursos: ``iqos://openapi``, ``iqos://modules``, ``iqos://health``.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from mcp_server.catalog import BY_NAME, OPERATIONS, TAGS, Operation, Param
from mcp_server.client import IQOSClient, IQOSError

LOGGER = logging.getLogger("iqos.mcp")

SERVER_NAME = "iqos"
SERVER_TITLE = "IQ OS"
SERVER_INSTRUCTIONS = """
Ferramentas do IQ OS (inteligência financeira, contratos públicos, empresas,
ontologia, recolha de dados e agentes).

Como usar:
1. `iqos_modules` dá a lista de módulos e o que fazem.
2. Cada módulo tem ferramentas próprias com nomes descritivos
   (`contratos_search`, `empresas_global_search`, `ontologia_ai_answer`, …).
3. Para algo que não esteja nas ferramentas curadas, use
   `iqos_search_endpoints` para encontrar o endpoint e depois `iqos_api_call`.
4. `iqos_describe_endpoint` devolve o esquema de parâmetros e corpo de um
   endpoint concreto.

Os valores monetários dos contratos estão em euros; as datas em ISO 8601.
""".strip()

_client: Optional[IQOSClient] = None


def get_client() -> IQOSClient:
    """Cliente HTTP partilhado (single-flight, configurado por variáveis de ambiente)."""
    global _client
    if _client is None:
        _client = IQOSClient()
        LOGGER.info("IQ OS API: %s (token=%s)", _client.base_url, "sim" if _client.token else "não")
    return _client


server = MCPServer(
    name=SERVER_NAME,
    title=SERVER_TITLE,
    version="0.1.0",
    instructions=SERVER_INSTRUCTIONS,
)


# ---------------------------------------------------------------------------
# Geração das ferramentas curadas
# ---------------------------------------------------------------------------

_TYPE_ANNOTATION = {
    "str": "str | None",
    "int": "int | None",
    "float": "float | None",
    "bool": "bool | None",
    "list[str]": "list[str] | None",
    "dict": "dict[str, Any] | None",
}


def _annotation(param: Param) -> str:
    if param.required:
        return param.type if param.type in _TYPE_ANNOTATION else "str"
    return _TYPE_ANNOTATION.get(param.type, "str | None")


def _signature(op: Operation) -> tuple[str, str]:
    """Devolve (parâmetros, argumentos) da assinatura gerada."""
    # Obrigatórios primeiro (regra do Python para argumentos com valor por omissão).
    ordered = [p for p in op.params if p.required] + [p for p in op.params if not p.required]
    parts: List[str] = []
    args: List[str] = []
    for param in ordered:
        name = param.python_name
        args.append(f"{name}={name}")
        if param.required:
            parts.append(f"{name}: {_annotation(param)}")
        else:
            default = repr(param.default)
            parts.append(f"{name}: {_annotation(param)} = {default}")
    return ", ".join(parts), ", ".join(args)


def _docstring(op: Operation) -> str:
    lines = [op.summary, "", f"Endpoint: `{op.method} {op.path}`"]
    described = [p for p in op.params if p.description and p.location != "body"]
    if described:
        lines.append("")
        lines.append("Parâmetros:")
        for param in described:
            marker = "obrigatório" if param.required else f"por omissão {param.default!r}"
            lines.append(f"    {param.name}: {param.description} ({marker})")
    body = op.body_param
    if body is not None:
        lines.append("")
        lines.append(f"Corpo JSON: {body.description}")
    lines.append("")
    lines.append("Devolve o JSON do endpoint; em caso de falha, um objeto com 'error'.")
    text = "\n".join(lines)
    # A docstring é injetada no módulo gerado: não pode quebrar o literal.
    return text.replace("\\", "\\\\").replace('"""', '\\"\\"\\"').replace('\\"', '"')


def _make_tool(op: Operation) -> Any:
    """Gera a função da ferramenta com assinatura tipada (para o esquema MCP)."""
    params, args = _signature(op)
    source = (
        "from __future__ import annotations\n"
        "from typing import Any\n"
        f"async def {op.name}({params}) -> dict:\n"
        f'    """{_docstring(op)}"""\n'
        f'    return await _dispatch("{op.name}"{", " + args if args else ""})\n'
    )
    namespace: Dict[str, Any] = {"_dispatch": _dispatch}
    exec(compile(source, f"<mcp:{op.name}>", "exec"), namespace)  # noqa: S102 - código gerado a partir do catálogo
    return namespace[op.name]


async def _dispatch(name: str, **kwargs: Any) -> Dict[str, Any]:
    """Executa a operação do catálogo contra a API do IQ OS."""
    op = BY_NAME.get(name)
    if op is None:  # pragma: no cover - defensivo
        return {"error": f"Operação desconhecida: {name}"}

    path = op.path
    for param in op.path_params:
        value = kwargs.pop(param.python_name, None)
        if value is None:
            return {"error": f"Falta o parâmetro obrigatório '{param.name}' para {op.method} {op.path}"}
        path = path.replace("{" + param.name + "}", str(value))

    query: Dict[str, Any] = {}
    for param in op.query_params:
        value = kwargs.pop(param.python_name, None)
        if value is not None:
            query[param.name] = value

    body = kwargs.pop("payload", None)

    try:
        result = await get_client().request(op.method, path, query=query, body=body)
    except IQOSError as exc:
        LOGGER.warning("%s falhou: %s", name, exc)
        return {"error": str(exc), "status_code": exc.status_code, "endpoint": f"{op.method} {op.path}"}
    return result if isinstance(result, dict) else {"result": result}


def _annotations(op: Operation) -> ToolAnnotations:
    return ToolAnnotations(
        title=op.summary,
        read_only_hint=op.read_only,
        destructive_hint=op.destructive,
        idempotent_hint=op.method in {"GET", "PUT", "DELETE"},
        open_world_hint=op.tag in {"scraper", "proxy", "search360", "hermes", "researcher", "elastic"},
    )


def _selected_operations() -> List[Operation]:
    """Operações do catálogo a expor, filtradas por ``IQOS_MCP_TAGS``.

    Sem a variável (ou com ``*``) expõe o catálogo completo. Com uma lista de
    grupos separados por vírgula (ex.: ``contratos,contratos-fr,empresas``)
    expõe apenas essas operações.

    O filtro existe porque os clientes (Copilot/DeepSeek) limitam o número de
    funções por pedido (128 no DeepSeek) e o catálogo completo tem 219 — a
    lista inteira provoca o erro «supports at most 128 functions».
    """
    raw = os.environ.get("IQOS_MCP_TAGS", "").strip()
    if not raw or raw == "*":
        return list(OPERATIONS)
    wanted = {tag.strip().lower() for tag in raw.split(",") if tag.strip()}
    unknown = wanted - {tag.lower() for tag in TAGS}
    if unknown:
        LOGGER.warning(
            "IQOS_MCP_TAGS: grupos desconhecidos %s (válidos: %s)",
            sorted(unknown),
            sorted(TAGS),
        )
    return [op for op in OPERATIONS if op.tag.lower() in wanted]


def register_catalog_tools() -> int:
    """Regista uma ferramenta MCP por cada operação selecionada do catálogo."""
    registered = 0
    for op in _selected_operations():
        server.add_tool(
            _make_tool(op),
            name=op.name,
            title=op.summary,
            description=f"[{op.tag}] {op.summary}",
            annotations=_annotations(op),
        )
        registered += 1
    return registered


# ---------------------------------------------------------------------------
# Ferramentas genéricas
# ---------------------------------------------------------------------------


@server.tool(
    title="Chamar qualquer endpoint da API",
    annotations=ToolAnnotations(read_only_hint=False, open_world_hint=True),
)
async def iqos_api_call(
    method: str,
    path: str,
    query: Optional[Dict[str, Any]] = None,
    body: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Chama diretamente qualquer endpoint do IQ OS.

    Usar quando nenhuma ferramenta curada serve. Descubra o endpoint com
    `iqos_search_endpoints` e confirme os parâmetros com
    `iqos_describe_endpoint`.

    Parâmetros:
        method: GET | POST | PUT | PATCH | DELETE.
        path: caminho absoluto, começando por `/` (ex.: `/contracts/status`).
        query: parâmetros de query (opcional).
        body: corpo JSON (opcional).
    """
    try:
        result = await get_client().request(method, path, query=query, body=body)
    except IQOSError as exc:
        return {"error": str(exc), "status_code": exc.status_code, "endpoint": f"{method} {path}"}
    return result if isinstance(result, dict) else {"result": result}


@server.tool(
    title="Pesquisar endpoints na especificação OpenAPI",
    annotations=ToolAnnotations(read_only_hint=True),
)
async def iqos_search_endpoints(query: str, tag: Optional[str] = None, limit: int = 20) -> Dict[str, Any]:
    """Pesquisa endpoints do IQ OS por texto (caminho, resumo ou grupo).

    Parâmetros:
        query: texto a procurar (ex.: "notícias", "analytics", "contratos").
        tag: limitar a um grupo (ver `iqos_modules`).
        limit: número máximo de resultados (por omissão 20).
    """
    try:
        spec = await get_client().openapi()
    except IQOSError as exc:
        return {"error": str(exc)}

    needle = (query or "").strip().lower()
    found: List[Dict[str, Any]] = []
    for path, operations in (spec.get("paths") or {}).items():
        for method, op in operations.items():
            if method.lower() not in {"get", "post", "put", "patch", "delete"}:
                continue
            tags = op.get("tags") or []
            haystack = " ".join([path, op.get("summary") or "", op.get("description") or "", " ".join(tags)]).lower()
            if tag and tag not in tags:
                continue
            if needle and needle not in haystack:
                continue
            found.append(
                {
                    "method": method.upper(),
                    "path": path,
                    "summary": op.get("summary") or "",
                    "tags": tags,
                }
            )
            if len(found) >= max(1, min(limit, 200)):
                return {"total_found": len(found), "results": found, "truncated": True}
    return {"total_found": len(found), "results": found, "truncated": False}


@server.tool(
    title="Esquema de um endpoint",
    annotations=ToolAnnotations(read_only_hint=True),
)
async def iqos_describe_endpoint(path: str, method: str = "GET") -> Dict[str, Any]:
    """Devolve o esquema completo de um endpoint (parâmetros, corpo e respostas).

    Parâmetros:
        path: caminho do endpoint (ex.: `/contracts/analytics`).
        method: verbo HTTP (por omissão GET).
    """
    try:
        spec = await get_client().openapi()
    except IQOSError as exc:
        return {"error": str(exc)}

    operations = (spec.get("paths") or {}).get(path)
    if not operations:
        return {"error": f"Endpoint não encontrado: {path}", "hint": "Use iqos_search_endpoints."}
    operation = operations.get(method.lower())
    if not operation:
        return {
            "error": f"{method.upper()} não existe em {path}",
            "available_methods": sorted(k.upper() for k in operations if k.islower()),
        }

    schemas = ((spec.get("components") or {}).get("schemas")) or {}
    parameters = []
    for param in operation.get("parameters") or []:
        parameters.append(
            {
                "name": param.get("name"),
                "in": param.get("in"),
                "required": bool(param.get("required")),
                "schema": param.get("schema"),
                "description": param.get("description"),
            }
        )

    result: Dict[str, Any] = {
        "method": method.upper(),
        "path": path,
        "summary": operation.get("summary"),
        "description": operation.get("description"),
        "tags": operation.get("tags"),
        "parameters": parameters,
    }

    body_schema = (((operation.get("requestBody") or {}).get("content") or {}).get("application/json") or {}).get("schema")
    if body_schema:
        result["body_schema"] = body_schema
        ref = body_schema.get("$ref")
        if ref and ref.startswith("#/components/schemas/"):
            name = ref.rsplit("/", 1)[-1]
            result["body_schema_resolved"] = schemas.get(name)
    return result


@server.tool(
    title="Módulos e funcionalidades da plataforma",
    annotations=ToolAnnotations(read_only_hint=True),
)
async def iqos_modules() -> Dict[str, Any]:
    """Lista os módulos do IQ OS com descrição e estado do serviço.

    Útil como primeiro passo para saber onde procurar.
    """
    result: Dict[str, Any] = {"modules": []}
    client = get_client()
    try:
        summary = await client.request("GET", "/openapi/summary")
        result["modules"] = summary.get("tags", [])
        result["docs"] = summary.get("docs")
    except IQOSError as exc:
        result["error"] = str(exc)
        # Fallback local: grupos do catálogo, sem descrições.
        result["modules"] = [{"name": tag, "description": ""} for tag in TAGS]
    try:
        result["health"] = await client.request("GET", "/health")
    except IQOSError as exc:
        result["health"] = {"error": str(exc)}
    return result


# ---------------------------------------------------------------------------
# Recursos
# ---------------------------------------------------------------------------


@server.resource(
    "iqos://openapi",
    name="openapi",
    title="Especificação OpenAPI do IQ OS",
    description="Especificação OpenAPI 3.1 completa (JSON) usada pelo Swagger e por este servidor.",
    mime_type="application/json",
)
async def openapi_resource() -> str:
    """Especificação OpenAPI do backend."""
    try:
        spec = await get_client().openapi()
    except IQOSError as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
    return json.dumps(spec, ensure_ascii=False)


@server.resource(
    "iqos://modules",
    name="modules",
    title="Módulos do IQ OS",
    description="Catálogo de módulos e respetivas descrições.",
    mime_type="application/json",
)
async def modules_resource() -> str:
    """Catálogo de módulos da plataforma."""
    try:
        summary = await get_client().request("GET", "/openapi/summary")
    except IQOSError as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
    return json.dumps(summary, ensure_ascii=False)


@server.resource(
    "iqos://health",
    name="health",
    title="Estado do IQ OS",
    description="Modelos e features carregados no backend.",
    mime_type="application/json",
)
async def health_resource() -> str:
    """Estado do backend."""
    try:
        data = await get_client().request("GET", "/health")
    except IQOSError as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
    return json.dumps(data, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------


@server.prompt(
    name="investigar_empresa",
    title="Investigar uma empresa",
)
def investigar_empresa(empresa: str) -> str:
    """Roteiro para investigar uma empresa com os dados do IQ OS.

    Parâmetros:
        empresa: nome ou NIF da empresa a investigar.
    """
    return f"""Investiga a empresa "{empresa}" usando as ferramentas do IQ OS.

1. `empresas_autocomplete` ou `empresas_search` para obter o NIF e a ficha.
2. `empresa_detail` com o NIF: volume de contratos, valores e papéis.
3. `empresa_contratos` e `empresa_analytics`: contratos, evolução anual, CPV e contrapartes.
4. `empresa_marcas` e `empresa_firmas`: marcas (INPI) e firmas (RNPC), se existirem.
5. `empresas_global_search` para confirmar presença noutras fontes (Espanha, CRM).
6. Se for pedido sentimento, usar `sentiment_analyze_corpus` com origin=contracts ou news.

Apresenta: identificação, dimensão (nº de contratos e valor), papéis
(adjudicante/adjudicatário), principais contrapartes, evolução anual e
sinais de risco. Cita sempre o número de contratos e o valor total.
"""


def build_server() -> MCPServer:
    """Regista as ferramentas do catálogo e devolve o servidor pronto."""
    count = register_catalog_tools()
    tags = os.environ.get("IQOS_MCP_TAGS", "").strip() or "*"
    LOGGER.info(
        "Servidor MCP do IQ OS: %d ferramentas curadas + 4 genéricas (grupos: %s).",
        count,
        tags,
    )
    return server


__all__ = ["server", "build_server", "get_client", "register_catalog_tools", "_selected_operations"]
