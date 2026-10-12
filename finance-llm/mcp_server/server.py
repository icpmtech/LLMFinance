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


def _env_tags(name: str) -> List[str]:
    """Lê uma lista de grupos separada por vírgulas (``*`` ou vazio = todos)."""
    raw = os.environ.get(name, "").strip()
    if not raw or raw == "*":
        return []
    return [tag.strip().lower() for tag in raw.split(",") if tag.strip()]


def _max_tools() -> int:
    """Teto de ferramentas curadas a expor (``0`` = sem teto)."""
    raw = os.environ.get("IQOS_MCP_MAX_TOOLS", "").strip()
    if not raw:
        return 0
    try:
        return max(0, int(raw))
    except ValueError:
        LOGGER.warning("IQOS_MCP_MAX_TOOLS inválido (%r): ignorado (sem teto)", raw)
        return 0


def _selected_operations() -> List[Operation]:
    """Operações do catálogo a expor.

    Filtros, por ordem:

    1. ``IQOS_MCP_TAGS`` — grupos a expor (lista separada por vírgulas; vazio ou
       ``*`` expõe o catálogo completo).
    2. ``IQOS_MCP_EXCLUDE_TAGS`` — grupos a retirar da seleção anterior.
    3. ``IQOS_MCP_MAX_TOOLS`` — teto de ferramentas curadas (``0``/vazio = sem
       teto), aplicado na ordem do catálogo.

    Os dois primeiros existem porque os clientes limitam o número de **funções
    por pedido** — o DeepSeek recusa acima de 128 e a conta inclui as
    ferramentas internas do cliente (ficheiro, terminal, browser, …), não só as
    do MCP. O catálogo completo tem 224: expô-lo inteiro faz o cliente falhar
    com «supports at most 128 functions». O teto é a rede de segurança para uma
    seleção de grupos demasiado generosa (ou para quando o catálogo cresce).
    """
    wanted = set(_env_tags("IQOS_MCP_TAGS"))
    excluded = set(_env_tags("IQOS_MCP_EXCLUDE_TAGS"))
    known = {tag.lower() for tag in TAGS}
    for env_name, tags in (("IQOS_MCP_TAGS", wanted), ("IQOS_MCP_EXCLUDE_TAGS", excluded)):
        unknown = tags - known
        if unknown:
            LOGGER.warning(
                "%s: grupos desconhecidos %s (válidos: %s)",
                env_name,
                sorted(unknown),
                sorted(TAGS),
            )

    selected = [
        op
        for op in OPERATIONS
        if (not wanted or op.tag.lower() in wanted) and op.tag.lower() not in excluded
    ]

    limit = _max_tools()
    if limit and len(selected) > limit:
        dropped = selected[limit:]
        LOGGER.warning(
            "IQOS_MCP_MAX_TOOLS=%d: %d de %d ferramentas curadas ficaram de fora (grupos afetados: %s). "
            "Reduza IQOS_MCP_TAGS ou aumente o teto.",
            limit,
            len(dropped),
            len(selected),
            sorted({op.tag for op in dropped}),
        )
        selected = selected[:limit]
    return selected



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

1. `descoberta_resolver` com "{empresa}": obtém o NIF (e candidatos, se houver dúvida).
2. `descoberta_empresa` com o NIF: recolhe **tudo** numa só chamada — cadastro,
   contratos, rede de relações, pessoas e cargos, atos societários, insolvências
   (CIRE), risco, marcas (INPI), firmas (RNPC), subvenções, devedores,
   contribuintes, mercado, registos LEI e notícias — e devolve o **grafo de
   informação** (camadas: adjudicantes, CPV, pessoas, processos, marcas, firmas)
   e a projeção na **ontologia** (tipos instanciados, ligações materializadas e
   lacunas).
3. `empresa_contratos` e `empresa_analytics` para o detalhe contrato a contrato
   e a evolução anual por CPV e contraparte.
4. `hermes_ask` para uma leitura citada, com as fontes da plataforma.
5. `empresas_global_search` para confirmar presença noutras fontes (Espanha, CRM).

Apresenta: identificação, dimensão (nº de contratos e valor), papéis
(adjudicante/adjudicatário), principais contrapartes, evolução anual,
insolvências e sinais de risco, e o que a ontologia ainda não cobre.
Cita sempre o número de contratos e o valor total.
"""


#: Ferramentas genéricas (não vêm do catálogo).
GENERIC_TOOLS = 4
#: Limite de **funções por pedido** de alguns clientes (DeepSeek, por exemplo).
#: A conta inclui as ferramentas internas do cliente, por isso o orçamento do
#: servidor MCP tem de ser bem menor do que isto.
CLIENT_TOOL_LIMIT = 128


def tool_report() -> Dict[str, Any]:
    """Resumo do que este servidor vai expor (usado pelo CLI e pelos testes)."""
    selected = _selected_operations()
    tags = sorted({op.tag for op in selected})
    total = len(selected) + GENERIC_TOOLS
    return {
        "catalog": len(OPERATIONS),
        "selected": len(selected),
        "generic": GENERIC_TOOLS,
        "total": total,
        "tags": tags,
        "limit": _max_tools(),
        "client_limit": CLIENT_TOOL_LIMIT,
        "over_client_limit": total > CLIENT_TOOL_LIMIT,
        "env": {
            "IQOS_MCP_TAGS": os.environ.get("IQOS_MCP_TAGS", ""),
            "IQOS_MCP_EXCLUDE_TAGS": os.environ.get("IQOS_MCP_EXCLUDE_TAGS", ""),
            "IQOS_MCP_MAX_TOOLS": os.environ.get("IQOS_MCP_MAX_TOOLS", ""),
        },
    }


def build_server() -> MCPServer:
    """Regista as ferramentas do catálogo e devolve o servidor pronto."""
    count = register_catalog_tools()
    tags = os.environ.get("IQOS_MCP_TAGS", "").strip() or "*"
    total = count + GENERIC_TOOLS
    LOGGER.info(
        "Servidor MCP do IQ OS: %d ferramentas curadas + %d genéricas = %d (grupos: %s).",
        count,
        GENERIC_TOOLS,
        total,
        tags,
    )
    if total > CLIENT_TOOL_LIMIT:
        LOGGER.warning(
            "O servidor expõe %d ferramentas: alguns clientes recusam pedidos com mais de %d funções "
            "(a conta inclui as ferramentas internas do cliente). Defina IQOS_MCP_TAGS "
            "(ex.: contratos,empresas,deep-search,hermes) e/ou IQOS_MCP_MAX_TOOLS.",
            total,
            CLIENT_TOOL_LIMIT,
        )
    return server


__all__ = [
    "server",
    "build_server",
    "get_client",
    "register_catalog_tools",
    "tool_report",
    "_selected_operations",
]
