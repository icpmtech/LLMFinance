"""Gateway do **Jarvis** — a única porta por onde o assistente toca o sistema.

O Jarvis não fala com os dados diretamente: fala com **gateways**, cada um com
um protocolo próprio. Assim, o que o assistente pode fazer é sempre a soma do
que os gateways expõem — e cada gateway pode ser testado à parte.

Três gateways:

- **`hermes`** — investigação citada do IQ OS. Delega em
  `api.hermes_service.ask()` (plano → recolha federada → resposta com `[n]`).
  É o gateway de *raciocínio sobre dados da plataforma*.
- **`agent`** — o **Hermes Agent** autónomo do IQ OS (`api/jarvis_agent.py`).
  Delega a tarefa no agente do container, que a executa com a **biblioteca de
  skills dele** (58 skills em 12 categorias) e os **29 toolsets** que tem
  (browser, terminal, ficheiros, execução de código, visão, imagem/vídeo,
  memória, cron, delegação, A2A, …). É o gateway de *trabalho autónomo*.
- **`mcp`** — o servidor MCP do sistema (`mcp_server.catalog`). Todas as
  operações curadas (`contratos_search`, `empresas_global_search`,
  `empresa_detail`, `search360_topic`, `ontology_ai_answer`, …) e o escape
  genérico (`iqos_api_call`) ficam disponíveis. As chamadas correm
  **dentro do processo** (ASGI em memória, com o token do utilizador
  reencaminhado) — sem rede nem login extra; se isso não for possível, cai
  para HTTP no backend configurado.
- **`web`** — o browser de fatos. Pesquisa na *web* e abre páginas,
  devolvendo texto limpo (sem navegador gráfico): `web.search`, `web.open` e
  `web.research`.

Cada ferramenta é descrita por `GatewayTool` (id, gateway, etiqueta, descrição,
parâmetros e palavras-chave para o planeador escolher sem modelo).

Uso::

    from api import jarvis_gateway as gateway

    gateway.catalog()                        # o que existe
    await gateway.invoke("hermes.ask", {"question": "..."}, ctx=ctx)

Rotas em `api/jarvis_routes.py`.
"""
from __future__ import annotations

import asyncio
import html
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import httpx

logger = logging.getLogger(__name__)

HERMES = "hermes"
AGENT = "agent"
MCP = "mcp"
WEB = "web"

GATEWAYS: List[Dict[str, str]] = [
    {
        "id": HERMES,
        "label": "Hermes",
        "description": "Investigação citada sobre os dados da plataforma (contratos, empresas, documentos, notícias).",
    },
    {
        "id": AGENT,
        "label": "Hermes Agent",
        "description": (
            "Agente autónomo do IQ OS: delega a tarefa e ele corre-a com as skills dele "
            "(investigação, web, devops, email, media, notas, desenvolvimento, …) e os 29 "
            "toolsets (browser, terminal, ficheiros, código, visão, cron, …)."
        ),
    },
    {
        "id": MCP,
        "label": "MCP do sistema",
        "description": "Catálogo curado de operações do IQ OS (o mesmo servidor MCP que os agentes usam).",
    },
    {
        "id": WEB,
        "label": "Browser",
        "description": "Pesquisa e leitura de páginas externas, com extração de texto.",
    },
]

WEB_TIMEOUT = 20.0
WEB_MAX_CHARS = 6000
WEB_MAX_RESULTS = 8
WEB_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


@dataclass(frozen=True)
class GatewayTool:
    """Uma capacidade do Jarvis, publicada por um gateway."""

    id: str
    gateway: str
    label: str
    description: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    keywords: Tuple[str, ...] = ()
    read_only: bool = True
    destructive: bool = False

    def public(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "gateway": self.gateway,
            "label": self.label,
            "description": self.description,
            "parameters": dict(self.parameters),
            "keywords": list(self.keywords),
            "read_only": self.read_only,
            "destructive": self.destructive,
        }


# ---------------------------------------------------------------------------
# Catálogo de ferramentas dos gateways nativos
# ---------------------------------------------------------------------------
_HERMES_TOOLS: List[GatewayTool] = [
    GatewayTool(
        id="hermes.ask",
        gateway=HERMES,
        label="Investigar (Hermes)",
        description=(
            "Investiga uma pergunta nas fontes da plataforma e da web aberta e devolve uma "
            "resposta citada com [n]. Argumentos: question (str), depth ('rapida'|'profunda')."
        ),
        parameters={
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "Pergunta a investigar."},
                "depth": {"type": "string", "enum": ["rapida", "profunda"], "default": "rapida"},
            },
            "required": ["question"],
        },
        keywords=("investigar", "investigacao", "hermes", "pesquisar", "evidencia", "citacoes"),
    ),
]

_AGENT_TOOLS: List[GatewayTool] = [
    GatewayTool(
        id="agent.ask",
        gateway=AGENT,
        label="Delegar no Hermes Agent",
        description=(
            "Entrega uma tarefa ao agente autónomo do IQ OS, que a executa com as **skills** "
            "dele e as ferramentas que tem (browser, terminal, ficheiros, execução de código, "
            "visão, cron, …) e devolve o resultado. Usar para trabalho autónomo ou multi-passo "
            "que as ferramentas da plataforma não cobrem. Argumento: task (str). É lento "
            "(pode levar minutos)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "Tarefa ou pergunta a entregar ao agente, com todo o contexto.",
                }
            },
            "required": ["task"],
        },
        keywords=(
            "agente",
            "hermes agent",
            "autónomo",
            "autonomo",
            "delegar",
            "delega",
            "tarefa complexa",
            "multi-passo",
            "automaticamente",
            "por ti",
        ),
    ),
    GatewayTool(
        id="agent.skills",
        gateway=AGENT,
        label="Skills do Hermes Agent",
        description=(
            "Lista as skills instaladas no agente autónomo (nome e categoria), opcionalmente "
            "filtradas. Serve para saber que métodos ele domina antes de lhe delegar algo. "
            "Argumento: query (str)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Filtro por nome ou categoria (opcional)."}
            },
            "required": ["query"],
        },
        keywords=("skills", "skill", "oque sabe", "métodos", "metodos", "biblioteca"),
    ),
    GatewayTool(
        id="agent.capabilities",
        gateway=AGENT,
        label="Capacidades do Hermes Agent",
        description=(
            "As capacidades declaradas do agente (toolsets: browser, terminal, ficheiros, "
            "código, visão, imagem, memória, cron, delegação, …), com destaque para as que "
            "interessam ao pedido. Argumento: focus (str)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "focus": {"type": "string", "description": "Área a destacar (ex.: browser, email)."}
            },
            "required": ["focus"],
        },
        keywords=("capacidades", "pode fazer", "toolsets", "ferramentas do agente"),
    ),
]

_WEB_TOOLS: List[GatewayTool] = [
    GatewayTool(
        id="web.search",
        gateway=WEB,
        label="Pesquisar na web",
        description="Pesquisa na web e devolve títulos, ligações e resumos. Argumento: query (str), max_results (int).",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_results": {"type": "integer", "default": 8},
            },
            "required": ["query"],
        },
        keywords=("web", "internet", "google", "pesquisar", "noticias", "site", "online"),
    ),
    GatewayTool(
        id="web.open",
        gateway=WEB,
        label="Abrir página",
        description="Abre uma página e devolve título, descrição e texto limpo. Argumento: url (str).",
        parameters={
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
        keywords=("abrir", "pagina", "url", "site", "ler", "ler pagina"),
    ),
    GatewayTool(
        id="web.research",
        gateway=WEB,
        label="Pesquisar e ler",
        description=(
            "Pesquisa na web, abre os melhores resultados e junta o texto de todos numa só evidência. "
            "Argumentos: query (str), max_pages (int, 1–5)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_pages": {"type": "integer", "default": 3},
            },
            "required": ["query"],
        },
        keywords=("pesquisar e ler", "investigar web", "comparar sites", "recolher web", "fontes externas"),
    ),
]

# Operações do MCP promovidas a ferramentas de primeira classe: são as que o
# assistente usa na maioria das perguntas sobre a plataforma. As restantes
# continuam acessíveis por `mcp.search` + `mcp.call`.
_MCP_PROMOTED: Tuple[Tuple[str, str, Tuple[str, ...]], ...] = (
    ("search_unified", "Pesquisar em todo o sistema", ("pesquisar", "procurar", "encontrar", "todo o sistema")),
    ("contratos_search", "Pesquisar contratos públicos", ("contrato", "contratos", "adjudicante", "adjudicatario")),
    ("contratos_analytics", "Agregados de contratos (por ano, região, tipo)", ("agregado", "estatistica", "por ano")),
    ("contratos_regional", "Contratos por região", ("regiao", "distrito", "concelho", "mapa")),
    ("contrato_detail", "Detalhe de um contrato", ("detalhe do contrato", "objeto do contrato")),
    ("contratos_chat", "Pergunta em linguagem natural sobre contratos", ("pergunta contratos",)),
    ("empresas_global_search", "Pesquisar entidades e empresas", ("empresa", "entidade", "nif", "companhia")),
    ("empresas_search", "Diretório de empresas (ranking)", ("ranking", "diretorio")),
    ("empresa_detail", "Ficha de uma empresa (por NIF)", ("ficha", "perfil", "cadastro", "empresa")),
    ("empresa_contratos", "Contratos de uma empresa", ("contratos da empresa", "adjudicatario")),
    ("empresa_analytics", "Indicadores de uma empresa", ("indicadores da empresa",)),
    ("empresas_role_summary", "Papéis da entidade (adjudicante/adjudicatário)", ("papeis", "adjudicante")),
    ("search360_topic", "Pesquisa 360 sobre um tema", ("tema", "panorama", "search360")),
    ("search360_search", "Pesquisa federada 360", ("federada", "fontes externas")),
    ("ontology_ai_answer", "Resposta da ontologia (camada semântica)", ("ontologia", "objeto", "semantica")),
    ("ontology_query_objects", "Consultar objetos da ontologia", ("objetos", "ontologia")),
    ("sentiment_analyze_text", "Analisar sentimento de um texto", ("sentimento", "opiniao", "tom")),
    ("market_info", "Informação fundamental de um ticker", ("fundamental", "setor", "capitalizacao")),
    ("market_history", "Histórico de cotações de um ticker", ("cotacao", "acao", "preco", "ticker", "bolsa")),
    ("market_news", "Notícias de mercado de um ticker", ("noticias do ticker", "noticias da acao", "ticker")),
    ("market_forecast", "Previsão de uma série de mercado", ("previsao", "forecast", "arima")),
    ("elastic_search_global", "Pesquisa global em notícias indexadas", ("google", "noticias indexadas")),
    ("rag_chat", "Pergunta sobre os documentos indexados (RAG)", ("documento", "rag", "pdf", "relatorio")),
    ("office_documents", "Documentos do Office", ("office", "documento guardado")),
    ("email_messages", "Mensagens de email", ("email", "correio", "mensagem")),
    ("crm_accounts", "Contas de CRM", ("crm", "conta", "cliente")),
    ("researcher_investigate", "Investigação autónoma do investigador", ("investigador", "investigar a fundo")),
    ("scraper_search", "Pesquisar nos dados recolhidos", ("recolha", "scraper", "recolhido")),
    ("visualizador_query", "Consultar o visualizador (BI)", ("bi", "dashboard", "metrica", "indicador")),
    ("proxy_get", "Abrir uma página externa através do proxy da plataforma", ("proxy", "incorporar pagina")),
)


def _mcp_tool(operation: Any, label: str = "", keywords: Tuple[str, ...] = ()) -> GatewayTool:
    """Converte uma `mcp_server.catalog.Operation` numa ferramenta do gateway."""
    properties: Dict[str, Any] = {}
    required: List[str] = []
    for param in operation.params:
        if param.location == "body":
            properties["payload"] = {
                "type": "object",
                "description": param.description or "Corpo JSON do pedido.",
            }
            continue
        properties[param.python_name] = {
            "type": "integer" if param.type == "int" else "boolean" if param.type == "bool" else "string",
            "description": param.description or f"Parâmetro `{param.name}`.",
        }
        if param.default is not None:
            properties[param.python_name]["default"] = param.default
        if param.required:
            required.append(param.python_name)
    return GatewayTool(
        id=operation.name,
        gateway=MCP,
        label=label or operation.name,
        description=operation.summary,
        parameters={"type": "object", "properties": properties, "required": required},
        keywords=keywords,
        read_only=operation.read_only,
        destructive=operation.destructive,
    )


def _build_catalog() -> Dict[str, GatewayTool]:
    tools: Dict[str, GatewayTool] = {
        tool.id: tool for tool in (*_HERMES_TOOLS, *_AGENT_TOOLS, *_WEB_TOOLS)
    }

    try:
        from mcp_server import catalog as mcp_catalog
    except Exception as exc:  # pragma: no cover - ambiente sem o pacote mcp
        logger.warning("Catálogo MCP indisponível: %s", exc)
        mcp_catalog = None

    if mcp_catalog is not None:
        by_name = {op.name: op for op in mcp_catalog.OPERATIONS}
        for name, label, keywords in _MCP_PROMOTED:
            operation = by_name.get(name)
            if operation is not None:
                tools[operation.name] = _mcp_tool(operation, label=label, keywords=keywords)
        # Escape genérico: procurar e invocar qualquer operação do catálogo.
        tools["mcp.search"] = GatewayTool(
            id="mcp.search",
            gateway=MCP,
            label="Procurar operação no MCP",
            description="Procura no catálogo MCP por palavra-chave. Argumento: query (str), limit (int).",
            parameters={
                "type": "object",
                "properties": {"query": {"type": "string"}, "limit": {"type": "integer", "default": 12}},
                "required": ["query"],
            },
            keywords=("operacao", "endpoint", "catalogo", "mcp"),
        )
        tools["mcp.call"] = GatewayTool(
            id="mcp.call",
            gateway=MCP,
            label="Invocar operação do MCP",
            description="Invoca uma operação do catálogo MCP pelo nome. Argumentos: operation (str), params (object).",
            parameters={
                "type": "object",
                "properties": {
                    "operation": {"type": "string"},
                    "params": {"type": "object"},
                },
                "required": ["operation"],
            },
            keywords=("invocar", "chamar", "operacao", "endpoint"),
        )
    return tools


TOOLS: Dict[str, GatewayTool] = _build_catalog()


def catalog(gateway: Optional[str] = None) -> List[Dict[str, Any]]:
    """Catálogo público das ferramentas (opcionalmente de um só gateway)."""
    items = [tool for tool in TOOLS.values() if gateway is None or tool.gateway == gateway]
    return [tool.public() for tool in sorted(items, key=lambda t: (t.gateway, t.id))]


def summary() -> List[Dict[str, Any]]:
    """Resumo por gateway: quantas ferramentas e os exemplos mais úteis."""
    out: List[Dict[str, Any]] = []
    for entry in GATEWAYS:
        items = [tool for tool in TOOLS.values() if tool.gateway == entry["id"]]
        out.append(
            {
                **entry,
                "tools": len(items),
                "examples": [tool.id for tool in sorted(items, key=lambda t: t.id)[:6]],
            }
        )
    return out


def keywords_for(tool_id: str) -> Tuple[str, ...]:
    tool = TOOLS.get(tool_id)
    return tool.keywords if tool else ()


def search_terms(question: str, *, limit: int = 6) -> str:
    """Nome público de `_search_terms` (usado pelo serviço e nos testes)."""
    return _search_terms(question, limit=limit)


# ---------------------------------------------------------------------------
# Gateway MCP — chamada dentro do processo (ASGI) ou por HTTP
# ---------------------------------------------------------------------------
def _split_params(operation: Any, params: Optional[Dict[str, Any]]) -> Tuple[Dict[str, Any], Dict[str, Any], Optional[Any]]:
    """Separa `params` em (path, query, body) segundo o catálogo MCP."""
    values = dict(params or {})
    path_params: Dict[str, Any] = {}
    query: Dict[str, Any] = {}
    body: Optional[Any] = None
    for param in operation.params:
        key = param.name if param.name in values else param.python_name
        if key not in values:
            continue
        value = values.pop(key)
        if param.location == "path":
            path_params[param.name] = value
        elif param.location == "body":
            body = value
        else:
            query[param.name] = value
    # Chaves sobrantes: vão para a query (o catálogo é curado, mas um parâmetro
    # novo no servidor não deve ser descartado em silêncio).
    for key, value in values.items():
        if value is not None:
            query[key] = value
    return path_params, query, body


def _render_path(path: str, path_params: Dict[str, Any]) -> str:
    rendered = path
    for name, value in path_params.items():
        rendered = rendered.replace("{" + name + "}", str(value))
    return rendered


async def _mcp_http_call(
    method: str,
    path: str,
    *,
    query: Dict[str, Any],
    body: Any,
    ctx: Dict[str, Any],
) -> Any:
    """Executa o pedido contra a API — em memória (ASGI) ou por HTTP."""
    headers: Dict[str, str] = {}
    token = ctx.get("token")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    app = ctx.get("app")
    if app is None:
        try:
            from api.main import app as api_app  # noqa: PLC0415

            app = api_app
        except Exception:  # pragma: no cover - import circular / arranque parcial
            app = None

    params = {key: value for key, value in query.items() if value is not None}
    if app is not None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://iqos.local", timeout=120.0) as client:
            response = await client.request(method, path, params=params, json=body, headers=headers)
    else:  # pragma: no cover - só quando o app não é importável
        base_url = os.getenv("IQOS_API_URL", "http://127.0.0.1:8002").rstrip("/")
        async with httpx.AsyncClient(base_url=base_url, timeout=120.0) as client:
            response = await client.request(method, path, params=params, json=body, headers=headers)

    if response.status_code >= 400:
        detail = response.text[:400]
        raise RuntimeError(f"MCP {method} {path} → HTTP {response.status_code}: {detail}")
    if not response.content:
        return {"ok": True, "status": response.status_code}
    try:
        return response.json()
    except Exception:
        return {"text": response.text[:2000]}


async def _run_mcp_operation(name: str, params: Optional[Dict[str, Any]], ctx: Dict[str, Any]) -> Dict[str, Any]:
    from mcp_server import catalog as mcp_catalog  # noqa: PLC0415

    operation = next((op for op in mcp_catalog.OPERATIONS if op.name == name), None)
    if operation is None:
        raise RuntimeError(f"Operação MCP desconhecida: {name}.")
    path_params, query, body = _split_params(operation, params)
    path = _render_path(operation.path, path_params)
    data = await _mcp_http_call(operation.method, path, query=query, body=body, ctx=ctx)
    return {
        "operation": name,
        "label": TOOLS[name].label if name in TOOLS else name,
        "method": operation.method,
        "path": path,
        "data": data,
    }


def _search_operations(query: str, limit: int) -> List[Dict[str, Any]]:
    from mcp_server import catalog as mcp_catalog  # noqa: PLC0415

    terms = [term for term in re.split(r"\W+", str(query or "").lower()) if len(term) > 2]
    scored: List[Tuple[int, Any]] = []
    for operation in mcp_catalog.OPERATIONS:
        haystack = f"{operation.name} {operation.summary} {operation.tag}".lower()
        score = sum(1 for term in terms if term in haystack)
        if score:
            scored.append((score, operation))
    scored.sort(key=lambda item: (-item[0], item[1].name))
    return [
        {
            "operation": operation.name,
            "method": operation.method,
            "path": operation.path,
            "summary": operation.summary,
            "tag": operation.tag,
            "read_only": operation.read_only,
            "destructive": operation.destructive,
        }
        for _, operation in scored[: max(1, min(int(limit or 12), 40))]
    ]


# ---------------------------------------------------------------------------
# Gateway Web — pesquisa e leitura de páginas
# ---------------------------------------------------------------------------
def _web_search_sync(query: str, max_results: int) -> List[Dict[str, Any]]:
    """Pesquisa na web (DuckDuckGo). Síncrono — chamar em thread."""
    try:
        from ddgs import DDGS  # type: ignore[import-not-found]
    except Exception:  # pragma: no cover - pacote antigo
        from duckduckgo_search import DDGS  # type: ignore[import-not-found]

    rows: List[Dict[str, Any]] = []
    with DDGS() as engine:
        for item in engine.text(query, max_results=max(1, min(int(max_results or WEB_MAX_RESULTS), WEB_MAX_RESULTS))):
            rows.append(
                {
                    "title": str(item.get("title") or "").strip(),
                    "url": str(item.get("href") or item.get("url") or "").strip(),
                    "snippet": str(item.get("body") or "").strip(),
                }
            )
    return [row for row in rows if row["url"]]


_DROP_TAGS = ("script", "style", "noscript", "svg", "form", "nav", "footer", "header", "aside", "iframe")


def _clean_html(raw: str) -> Tuple[str, str]:
    """Extrai (título, texto) de HTML, descartando ruído de navegação."""
    from bs4 import BeautifulSoup  # noqa: PLC0415

    soup = BeautifulSoup(raw, "html.parser")
    title = ""
    if soup.title and soup.title.string:
        title = re.sub(r"\s+", " ", soup.title.string).strip()
    if not title:
        heading = soup.find("h1")
        if heading:
            title = re.sub(r"\s+", " ", heading.get_text(" ", strip=True)).strip()
    for tag in soup(_DROP_TAGS):
        tag.decompose()
    container = soup.find("main") or soup.find("article") or soup.body or soup
    text = container.get_text("\n", strip=True)
    text = html.unescape(text)
    text = re.sub(r"\n{2,}", "\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text).strip()
    return title, text


async def _web_open(url: str) -> Dict[str, Any]:
    target = str(url or "").strip()
    if not target:
        raise RuntimeError("Indique o URL a abrir.")
    if not target.startswith(("http://", "https://")):
        raise RuntimeError("Só se abrem endereços http/https.")
    async with httpx.AsyncClient(
        timeout=WEB_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": WEB_USER_AGENT, "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.8"},
    ) as client:
        response = await client.get(target)
    response.raise_for_status()
    content_type = response.headers.get("content-type", "")
    if "html" not in content_type and "text" not in content_type:
        return {"url": str(response.url), "title": "", "text": "", "note": f"Conteúdo não textual ({content_type})."}
    title, text = _clean_html(response.text)
    return {
        "url": str(response.url),
        "title": title or str(response.url),
        "text": text[:WEB_MAX_CHARS],
        "characters": len(text),
    }


# ---------------------------------------------------------------------------
# Invocação
# ---------------------------------------------------------------------------
async def invoke(tool_id: str, args: Optional[Dict[str, Any]] = None, *, ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Executa uma ferramenta do gateway e devolve `{tool, gateway, ok, ...}`."""
    context: Dict[str, Any] = dict(ctx or {})
    values = dict(args or {})
    tool = TOOLS.get(tool_id)

    async def _hermes() -> Dict[str, Any]:
        from api import hermes_service  # noqa: PLC0415

        question = str(values.get("question") or "").strip()
        if not question:
            raise RuntimeError("A ferramenta hermes.ask precisa de `question`.")
        result = await hermes_service.ask(
            question,
            depth=str(values.get("depth") or "rapida"),
            backend=context.get("backend"),
            history=context.get("history") or [],
            scope=context.get("scope"),
            session=context.get("session"),
            country=str(context.get("country") or "PRT"),
        )
        return {"answer": result.get("answer"), "sources": result.get("sources") or [], "subquestions": result.get("subquestions") or []}

    async def _web(name: str) -> Dict[str, Any]:
        if name == "web.search":
            rows = await asyncio.to_thread(
                _web_search_sync, str(values.get("query") or ""), values.get("max_results") or WEB_MAX_RESULTS
            )
            return {"query": values.get("query"), "results": rows}
        if name == "web.open":
            return await _web_open(str(values.get("url") or ""))
        # web.research: pesquisar e abrir os melhores resultados
        query = str(values.get("query") or "").strip()
        if not query:
            raise RuntimeError("A ferramenta web.research precisa de `query`.")
        pages = max(1, min(int(values.get("max_pages") or 3), 5))
        rows = await asyncio.to_thread(_web_search_sync, query, pages + 2)
        opened: List[Dict[str, Any]] = []
        for row in rows[:pages]:
            try:
                page = await _web_open(row["url"])
            except Exception as exc:
                opened.append({"url": row["url"], "title": row.get("title"), "error": str(exc)})
                continue
            opened.append({**page, "snippet": row.get("snippet")})
        return {"query": query, "results": rows, "pages": opened}

    async def _agent(name: str) -> Dict[str, Any]:
        """Hermes Agent autónomo: delegação, skills e capacidades."""
        from api import jarvis_agent  # noqa: PLC0415

        if name == "agent.ask":
            task = str(values.get("task") or "")
            # O agente é sem estado: leva a persona (dia de hoje, dados ao lado, regras)
            # e o diálogo anterior, para uma pergunta de seguimento não chegar órfã.
            return await jarvis_agent.ask(
                task,
                system=jarvis_agent.assistant_system(task),
                history=context.get("history") or [],
            )
        if name == "agent.skills":
            return await asyncio.to_thread(
                jarvis_agent.skills, query=str(values.get("query") or "")
            )
        return await asyncio.to_thread(
            jarvis_agent.capabilities, focus=str(values.get("focus") or "")
        )

    try:
        if tool_id == "hermes.ask":
            data = await _hermes()
        elif tool_id.startswith("agent."):
            data = await _agent(tool_id)
        elif tool_id.startswith("web."):
            data = await _web(tool_id)
        elif tool_id == "mcp.search":
            data = {"results": _search_operations(str(values.get("query") or ""), values.get("limit") or 12)}
        elif tool_id == "mcp.call":
            data = await _run_mcp_operation(
                str(values.get("operation") or ""), values.get("params") or {}, context
            )
        elif tool_id in TOOLS and tool is not None and tool.gateway == MCP:
            data = await _run_mcp_operation(tool_id, values, context)
        else:
            raise RuntimeError(f"Ferramenta desconhecida: {tool_id}.")
    except Exception as exc:
        logger.info("Gateway %s falhou: %s", tool_id, exc)
        return {
            "tool": tool_id,
            "gateway": tool.gateway if tool else "?",
            "label": tool.label if tool else tool_id,
            "ok": False,
            "error": str(exc),
        }

    return {
        "tool": tool_id,
        "gateway": tool.gateway if tool else "?",
        "label": tool.label if tool else tool_id,
        "ok": True,
        "data": data,
    }


def pick_tools(question: str, *, limit: int = 3) -> List[str]:
    """Escolhe ferramentas por palavras-chave — o plano sem modelo do Jarvis.

    Só entram ferramentas para as quais se consegue construir um pedido válido a
    partir da pergunta (`default_args`); assim o plano sem modelo nunca produz
    uma chamada condenada a 422.
    """
    folded = _fold(question)
    scored: List[Tuple[int, str]] = []
    for tool in TOOLS.values():
        if tool.gateway == MCP and tool.id in {"mcp.call", "mcp.search"}:
            continue
        if default_args(tool.id, question) is None:
            continue
        score = 0
        for keyword in tool.keywords:
            if _fold(keyword) and _fold(keyword) in folded:
                score += 2 if " " in keyword else 1
        if score:
            scored.append((score, tool.id))
    scored.sort(key=lambda item: (-item[0], item[1]))
    chosen = [tool_id for _, tool_id in scored[: max(1, limit)]]
    # Um URL na pergunta é sinal claro de «abre esta página».
    if _first_url(question) and default_args("web.open", question) is not None and "web.open" not in chosen:
        chosen.insert(0, "web.open")
    if not chosen and default_args("hermes.ask", question) is not None:
        chosen = ["hermes.ask"]
    # O Hermes é a espinha dorsal da investigação, mas é caro (plano + recolha
    # federada). Acrescenta-se quando a pergunta é analítica (≥ 5 palavras) e
    # não veio já do plano; em consultas curtas bastam os dados do MCP.
    if "hermes.ask" not in chosen and len(_fold(question).split()) >= 5:
        if default_args("hermes.ask", question) is not None and len(chosen) < limit:
            chosen.append("hermes.ask")
    return chosen


def _fold(value: str) -> str:
    import unicodedata  # noqa: PLC0415

    text = unicodedata.normalize("NFD", str(value or ""))
    return "".join(char for char in text if unicodedata.category(char) != "Mn").lower()


#: Corpos JSON das operações mais usadas: o campo onde a pergunta entra. Sem
#: esta tabela, um plano sem modelo não saberia construir o corpo (as operações
#: do catálogo MCP apenas dizem «corpo JSON — ver o Swagger»).
_BODY_HINTS: Dict[str, Tuple[str, ...]] = {
    "contratos_search": ("q",),
    "contratos_chat": ("question",),
    "search360_search": ("q",),
    "search360_topic": ("q",),
    "ontology_ai_answer": ("question",),
    "sentiment_analyze_text": ("text",),
    "empresas_role_summary": ("query",),
    "rag_chat": ("question",),
    "researcher_investigate": ("question",),
    "contratos_es_search": ("q",),
}

#: Nomes de parâmetros que aceitam texto livre (a pergunta do utilizador).
_TEXT_KEYS: Tuple[str, ...] = ("q", "query", "question", "text", "term")

#: Operações que respondem com IA a partir de uma pergunta em linguagem natural.
#: Têm de receber a pergunta inteira — reduzir a palavras-chave destruiria o
#: pedido (no sentimento, o texto *é* o que se analisa).
_NATURAL_LANGUAGE_TOOLS = frozenset(
    {
        "contratos_chat",
        "rag_chat",
        "ontology_ai_answer",
        "researcher_investigate",
        "sentiment_analyze_text",
    }
)

#: Sinais de que a pergunta quer os **maiores** (por valor) e não os mais recentes.
_TOP_MARKERS: Tuple[str, ...] = (
    "maior",
    "maiores",
    "mais caro",
    "mais caros",
    "mais alto",
    "mais altos",
    "maior valor",
    "mais elevado",
    "top ",
)

#: Palavras que não distinguem nada numa pesquisa por texto (pergunta + vazias).
_SEARCH_STOPWORDS = frozenset(
    """
    a o as os um uma uns umas de da do das dos em no na nos nas por para com sem sobre que quais qual quem
    como onde quando quanto quantos quantas e ou é sao são ser estar tem têm ha há mais menos se ao aos à às
    pelo pela seus suas este esta esse essa isto aquilo me te lhe nos vos diz fala explica faz quero preciso
    meu minha meus minhas teu tua teus tuas nosso nossa nossos nossas
    podes pode lista mostra indica dados informacao informação saber the of and for with in about is are what
    which who how many much please
    """.split()
)


def _search_terms(question: str, *, limit: int = 6) -> str:
    """Palavras distintivas da pergunta, para as pesquisas por texto.

    As operações de pesquisa do MCP recebem um termo, não uma pergunta: enviar a
    frase toda («Quais são os maiores contratos públicos de energia em 2025?»)
    faz o `multi_match` do Elasticsearch trazer resultados de qualquer
    semelhança. Aqui ficam só as palavras que distinguem — os NIF e os tickers
    são preservados intactos, porque nesses casos o valor exato é que interessa.
    """
    text = str(question or "")
    # NIF (9 dígitos) e tickers (ABC.LS, ABC-D) primeiro: valem por si.
    exact = re.findall(r"\b\d{9}\b|\b[A-Z][A-Z0-9]{1,9}[.\-][A-Z]{1,3}\b", text)
    terms = [token for token in exact if token]
    for word in re.split(r"\W+", text):
        if len(word) < 3:
            continue
        folded = _fold(word)
        if folded in _SEARCH_STOPWORDS:
            continue
        # Números: um ano é distintivo («contratos de 2025»), o resto é ruído.
        if folded.isdigit() and not (len(folded) == 4 and 1900 <= int(folded) <= 2100):
            continue
        if word in terms:
            continue
        terms.append(word)
        if len(terms) >= limit:
            break
    return " ".join(terms[:limit]) or text.strip()


#: Operações com um corpo JSON construído à medida (não basta pôr a pergunta
#: num campo: há filtros e ordenações que a pergunta já diz).
_BODY_BUILDERS: Dict[str, Any] = {}


def _contratos_body(question: str) -> Dict[str, Any]:
    """Corpo de `/contracts/search` a partir da pergunta.

    «maiores contratos» tem de ordenar por valor — sem isto o Elasticsearch
    ordena por data de publicação e responde à pergunta errada. O ano, quando
    mencionado, vira filtro.
    """
    body: Dict[str, Any] = {"q": _search_terms(question)}
    folded = _fold(question)
    if any(marker in folded for marker in _TOP_MARKERS):
        body["sort_by"] = "precoContratual"
        body["sort_order"] = "desc"
    year = re.search(r"\b(?:19|20)\d{2}\b", str(question or ""))
    if year:
        body["year"] = int(year.group(0))
    return body


_BODY_BUILDERS["contratos_search"] = _contratos_body


def default_args(tool_id: str, question: str) -> Optional[Dict[str, Any]]:
    """Argumentos mínimos para chamar `tool_id` com `question`.

    Devolve `None` quando não é possível construir um pedido válido sem
    adivinhar (por exemplo uma operação que exige um `nif` ou um `dataset`).
    """
    tool = TOOLS.get(tool_id)
    if tool is None:
        return None
    properties: Dict[str, Any] = (tool.parameters or {}).get("properties") or {}
    required: List[str] = (tool.parameters or {}).get("required") or []

    # O agente autónomo come tudo com o pedido original: a tarefa é a pergunta
    # inteira (ele próprio a decompõe) e os filtros de skills/capacidades levam as
    # palavras distintivas da pergunta, para não estragar o filtro com verbos.
    if tool.gateway == AGENT:
        if "task" in properties:
            return {"task": question}
        terms = _search_terms(question) or question
        if "query" in properties:
            return {"query": terms}
        if "focus" in properties:
            return {"focus": terms}
        return None

    # As pesquisas do MCP recebem palavras distintivas; as operações que
    # respondem com IA (RAG, ontologia, sentimento, investigador) precisam da
    # pergunta inteira, e o Hermes e a web também (é para isso que existem).
    if tool.gateway == MCP and tool_id in _NATURAL_LANGUAGE_TOOLS:
        text = question
    elif tool.gateway == MCP:
        text = _search_terms(question)
    else:
        text = question

    if "payload" in properties:
        builder = _BODY_BUILDERS.get(tool_id)
        if builder is not None:
            return {"payload": builder(question)}
        fields = _BODY_HINTS.get(tool_id)
        if not fields:
            return None
        return {"payload": {field: text for field in fields}}
    if "params" in properties:  # mcp.call — exige `operation`
        return None

    args: Dict[str, Any] = {}
    for name in required:
        if name not in properties:
            return None
        if name == "url":
            url = _first_url(question)
            if not url:
                return None
            args[name] = url
        elif name in _TEXT_KEYS:
            args[name] = text
        else:
            # Parâmetro obrigatório específico (nif, ticker, id): não se adivinha.
            return None
    if not args:
        for name in _TEXT_KEYS:
            if name in properties:
                args[name] = text
                break
        else:
            return None
    return args


def _first_url(text: str) -> Optional[str]:
    match = re.search(r"https?://[^\s<>\"']+", str(text or ""))
    return match.group(0) if match else None


def status() -> Dict[str, Any]:
    """Estado dos gateways (para o `/jarvis/meta`)."""
    return {
        "gateways": summary(),
        "tools": len(TOOLS),
        "web": {"available": True, "timeout_seconds": WEB_TIMEOUT, "max_results": WEB_MAX_RESULTS},
    }


__all__ = [
    "AGENT",
    "GATEWAYS",
    "GatewayTool",
    "HERMES",
    "MCP",
    "TOOLS",
    "WEB",
    "catalog",
    "default_args",
    "invoke",
    "keywords_for",
    "pick_tools",
    "search_terms",
    "status",
    "summary",
]
