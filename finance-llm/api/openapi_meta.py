"""Metadados OpenAPI/Swagger unificados do **IQ OS**.

O FastAPI já gera o `openapi.json` a partir dos routers, mas as operações
inline definidas em `api/main.py` (mercado, Elasticsearch, contratos,
empresas, dossier, import, páginas SPA) não têm `tags` nem descrição de
grupo — o Swagger aparecia com uma lista de grupos incompleta e sem
explicação.

Este módulo centraliza:

* ``DESCRIPTION`` — o texto de apresentação da API (Markdown);
* ``TAGS_METADATA`` — o catálogo de grupos, com descrição, usados por
  ``/docs``, ``/redoc`` e pelo `openapi.json`;
* ``PATH_TAG_RULES`` — o mapeamento prefixo de rota → grupo, aplicado às
  operações que não declaram ``tags`` (as inline);
* ``SPA_PATHS`` — rotas que devolvem o `index.html` da interface, para não
  se confundirem com endpoints de dados;
* ``custom_openapi()`` — pós-processador que injeta o esquema de segurança
  ``bearerAuth``, os ``servers`` e as tags em falta.

`api/main.py` liga tudo com::

    from api.openapi_meta import DESCRIPTION, TAGS_METADATA, custom_openapi
    app = FastAPI(description=DESCRIPTION, openapi_tags=TAGS_METADATA, ...)
    app.openapi = lambda: custom_openapi(app)
"""
from __future__ import annotations

from typing import Any, Dict, List, Sequence, Tuple

# --------------------------------------------------------------------------
# Apresentação
# --------------------------------------------------------------------------

DESCRIPTION = """
Plataforma **IQ OS** — inteligência financeira, contratos públicos, empresas,
ontologia, recolha de dados e agentes de IA.

A API está organizada por módulos (ver a lista de grupos abaixo). Todos os
endpoints devolvem JSON, exceto os que exportam ficheiros
(`/contracts/export/*`, `/visualizador/export/*`, `/office/documents/{id}/export`)
e os que servem páginas da interface (grupo **spa**).

### Autenticação

A maioria dos endpoints aceita (e alguns exige) um *token* de sessão:

1. `POST /auth/login` com `{"email": ..., "password": ...}`;
2. copiar o `token` da resposta;
3. em `/docs`, botão **Authorize** → `Bearer <token>`.

O mesmo token segue no cabeçalho `Authorization: Bearer <token>`.

### Convenções

* Paginação por `size` + `from` (ou `offset`, em alguns módulos);
* Erros: `4xx` com `{"detail": ...}`; os serviços devolvem `{"error": ...}`
  no corpo quando a falha é de fonte de dados;
* Datas em ISO 8601 (`YYYY-MM-DD` ou `YYYY-MM-DDTHH:MM:SSZ`).

### Interfaces

| Recurso | URL |
| --- | --- |
| Swagger UI | `/docs` |
| ReDoc | `/redoc` |
| Especificação OpenAPI | `/openapi.json` |
| Resumo JSON dos grupos | `/openapi/summary` |
| Servidor MCP (ferramentas para agentes) | `python -m mcp_server` |

### Ligação a partir de agentes (MCP)

O pacote `mcp_server/` expõe o sistema via *Model Context Protocol*:
ferramentas curadas por módulo, acesso genérico a qualquer endpoint
(`iqos_api_call`) e a especificação OpenAPI como recurso
(`iqos://openapi`). Ver `docs/API_SWAGGER_MCP.md`.
"""

CONTACT: Dict[str, Any] = {"name": "IQ OS", "url": "http://127.0.0.1:8002/docs"}

LICENSE_INFO: Dict[str, Any] = {"name": "Proprietário — uso interno"}

SERVERS: List[Dict[str, Any]] = [
    {"url": "http://127.0.0.1:8002", "description": "Backend local (uvicorn)"},
    {"url": "http://127.0.0.1:8003", "description": "Backend local (porta alternativa)"},
]

# --------------------------------------------------------------------------
# Grupos
# --------------------------------------------------------------------------
# A ordem desta lista é a ordem apresentada no Swagger UI.

TAGS_METADATA: List[Dict[str, str]] = [
    {
        "name": "core",
        "description": (
            "Estado do serviço e chat principal. `/health` confirma os modelos e "
            "*features* carregados; `/chat` responde seguindo a *skill* do pedido; "
            "`/chat/stream` faz streaming SSE."
        ),
    },
    {
        "name": "auth",
        "description": (
            "Contas e sessões: registo, login/logout, perfil, palavra-passe, "
            "dispositivos ligados e estatísticas de administração."
        ),
    },
    {
        "name": "admin",
        "description": (
            "Consola de administração: panorama geral, gestão de contas e sessões, "
            "visualizador de eventos e leitura de ficheiros de log."
        ),
    },
    {
        "name": "rag",
        "description": (
            "RAG de documentos: carregar PDF, listar/editar/apagar documentos, "
            "reprocessar, responder com citações, explicar a resposta e grafo de "
            "*chunks*."
        ),
    },
    {
        "name": "market",
        "description": (
            "Mercado e ativos: lista/pesquisa de tickers (Yahoo Finance), preços, "
            "informação fundamental, demonstrações financeiras, SEC filings, "
            "detentores, recomendações, calendário, notícias, opções, ações "
            "societárias, indicadores técnicos e previsão (ARIMA/Kronos)."
        ),
    },
    {
        "name": "elastic",
        "description": (
            "Camada Elasticsearch: estado, ingestão de preços/notícias, pesquisa "
            "(preços, notícias, global, autocomplete), análise NLP de notícias, "
            "grafo de notícias/entidades e índices da plataforma."
        ),
    },
    {
        "name": "contratos",
        "description": (
            "Contratos públicos portugueses (BASE.gov): pesquisa e ficha, "
            "analytics e agregações, região/NUTS, rede de entidades, relações "
            "adjudicante↔adjudicatário, grafos por dimensão, ingestão e exportação "
            "Excel/PDF."
        ),
    },
    {
        "name": "contratos-es",
        "description": (
            "Contratos públicos de Espanha (PLACSP): volumetria, metadados e listas "
            "CODICE, analytics do dashboard, pesquisa, autocomplete, entidades, "
            "importação por ano e detalhe de contrato."
        ),
    },
    {
        "name": "empresas",
        "description": (
            "Cadastro de entidades e empresas: pesquisa (GET/POST), estatísticas, "
            "países, autocomplete, ficha por NIF, contratos, analytics, marcas "
            "(INPI) e firmas (RNPC), enriquecimento a partir dos serviços públicos."
        ),
    },
    {
        "name": "companies-global",
        "description": (
            "Pesquisa global de empresas em todas as fontes (entidades, firmas, "
            "marcas, órgãos e adjudicatárias de Espanha, CRM), com contagem por "
            "fonte."
        ),
    },
    {
        "name": "societario",
        "description": (
            "Publicações de atos societários (publicacoes.mj.pt): recolha assistida "
            "por entidade (a pesquisa do portal exige reCAPTCHA), pesquisa das "
            "publicações indexadas, alvos com contratos no Portal BASE e ficha por NIF."
        ),
    },
    {
        "name": "search",
        "description": (
            "Pesquisa unificada da plataforma: âmbitos disponíveis, pesquisa em "
            "paralelo com resultados agrupados e sugestões para autocompletar."
        ),
    },
    {
        "name": "search360",
        "description": (
            "Dossiê 360: pesquisa federada por tema, biblioteca organizada, grafo de "
            "navegação, síntese com citações, projetos e dossiês guardados "
            "(criar, refrescar, exportar)."
        ),
    },
    {
        "name": "hermes",
        "description": (
            "Investigador Hermes: metamodelo (modos, fontes, índices) e `/hermes/ask` "
            "para respostas citadas com evidências e sub-perguntas."
        ),
    },
    {
        "name": "jarvis",
        "description": (
            "Jarvis: o assistente operacional com voz. Fala com o sistema por gateways "
            "(Hermes, MCP do sistema e browser), segue as skills partilhadas e interage por "
            "áudio — `/jarvis/ask` (e em streaming), `/jarvis/transcribe` e `/jarvis/speak`."
        ),
    },
    {
        "name": "hermes-agent",
        "description": (
            "Motor do Hermes Agent: liga o container autónomo (perfil `agents`) aos fornecedores "
            "de IA da plataforma. Resolve a chave guardada, escreve-a no volume do container "
            "(`config.yaml` + `.env`) e recria-o — `/hermes-agent/settings` e `/hermes-agent/diagnose`."
        ),
    },
    {
        "name": "researcher",
        "description": (
            "Agente de investigação com *audit trail* e catálogo fechado de "
            "ferramentas."
        ),
    },
    {
        "name": "agents",
        "description": (
            "Agentes dinâmicos (LangGraph): criar/editar/remover configurações, "
            "executar (normal ou SSE) e catálogo de ferramentas disponíveis."
        ),
    },
    {
        "name": "ontology",
        "description": (
            "Ontologia: tipos de objeto e de ligação, ações, consulta de objetos, "
            "resolução de entidades, contexto/resposta factuais, validação "
            "anti-alucinação, desenho e sugestões com IA, projetos, fichas e fontes "
            "de dados."
        ),
    },
    {
        "name": "crm",
        "description": (
            "CRM: metamodelo (fases, estados, tipos), panorama do pipeline, contas, "
            "contactos, oportunidades, atividades, ligação ao EmpresasIQ e "
            "criação/edição de registos."
        ),
    },
    {
        "name": "office",
        "description": (
            "Office: documentos Markdown com pastas e etiquetas, estatísticas, "
            "duplicar, exportar (MD/HTML) e trazer dossiês 360 como documentos "
            "editáveis."
        ),
    },
    {
        "name": "cms",
        "description": (
            "CMS: páginas por blocos, conteúdos reutilizáveis, blog com taxonomia, "
            "media, modelos, menus e aparência — com rascunho, agendamento, "
            "publicação, revisões e auditoria. O resultado público é servido em "
            "`/site/…` (HTML com SEO, RSS, sitemap e robots.txt)."
        ),
    },
    {
        "name": "rss",
        "description": (
            "Leitor de RSS: fontes RSS/Atom (por endereço ou OPML) agrupadas em "
            "pastas, recolha manual ou por agenda cron, artigos com lido/favorito/"
            "guardado, pesquisa e integrações com o Office, o sentimento, o CRM e o "
            "RAG, além de resumos e boletins por IA."
        ),
    },
    {
        "name": "email",
        "description": (
            "Correio: contas IMAP/SMTP, pastas e mensagens, sinalizadores, mover, "
            "apagar e enviar (com anexos)."
        ),
    },
    {
        "name": "sentiment",
        "description": (
            "Análise de sentimento: fontes disponíveis, motores (léxico/neural), "
            "análise de texto livre e de corpora, gravação em dossiê e em documento "
            "Office."
        ),
    },
    {
        "name": "visualizador",
        "description": (
            "Business Intelligence: catálogo de datasets, consultas analíticas "
            "(dimensões × medidas × fórmulas), registos (drill-through), valores de "
            "dimensão, exportação CSV/Excel e dashboards (templates, guardar, "
            "duplicar, exportar)."
        ),
    },
    {
        "name": "scraper",
        "description": (
            "Recolha de dados (scraping): templates de sites prontos a usar, "
            "definições de fontes, pré-visualização, sugestão assistida por IA, "
            "execuções e itens recolhidos (incluindo o texto integral dos artigos), "
            "pesquisa no corpus recolhido e agendamentos (cron)."
        ),
    },
    {
        "name": "social",
        "description": (
            "Pesquisa social: recolha de LinkedIn, TikTok, Reddit e Facebook por "
            "canais (plataforma + variante + alvo), teste de amostra, execuções, "
            "publicações indexadas em `finance_social`, pesquisa com facetas e "
            "sentimento, agendamentos (cron) e o estado das credenciais de cada canal."
        ),
    },
    {
        "name": "vectors",
        "description": (
            "Embeddings e pesquisa semântica: indexar embeddings, estado das "
            "tarefas, pesquisa vetorial/híbrida e garantia de mapeamentos "
            "`dense_vector`."
        ),
    },
    {
        "name": "skills",
        "description": (
            "Biblioteca de *skills* (métodos) usada pelos assistentes: listar, "
            "guardar, escolher a skill de uma pergunta, garantir/criar, editar e "
            "apagar."
        ),
    },
    {
        "name": "providers",
        "description": (
            "Fornecedores de IA (OpenAI, DeepSeek, Ollama, …): catálogo com estado "
            "das chaves, modelos disponíveis para o chat, guardar chaves e "
            "predefinições, e teste de ligação."
        ),
    },
    {
        "name": "cli",
        "description": "Terminal da interface: comandos disponíveis e execução de comandos do CLI do IQ OS.",
    },
    {
        "name": "proxy",
        "description": "Proxy para ler páginas externas e incorporá-las na interface (iframe), com limites e estado.",
    },
    {
        "name": "dossier",
        "description": (
            "Dossier do utilizador: fichas favoritas (entidades e contratos) e "
            "pastas/histórico de consultas."
        ),
    },
    {
        "name": "import",
        "description": (
            "Importação de ficheiros (.zip/.xlsx/.json): pré-visualização das linhas "
            "e indexação (contratos no Elasticsearch, entidades em JSONL)."
        ),
    },
    {
        "name": "contribuintes",
        "description": (
            "Contribuintes: índice único com todos os NIF/NIPC do sistema "
            "(agregado dos contratos PT/ES, cadastro de entidades, publicações "
            "societárias, CIRE, PessoasIQ, firmas, marcas e CRM), pesquisa e ficha "
            "por NIF, e sincronização manual/agendada (cron) a partir de todos os "
            "índices da plataforma."
        ),
    },
    {
        "name": "gleif",
        "description": (
            "GLEIF / LEI: registos *Legal Entity Identifier* do *Golden Copy* "
            "(Golden Copy em ficheiro `data/gleif/lei.jsonl` e índice "
            "`finance_gleif_lei`), pesquisa por nome/LEI/cidade com facetas, "
            "agregado por país/região para o mapa e ingestão a partir da API "
            "oficial ou dos ficheiros Golden Copy (LEI-CDF)."
        ),
    },
    {
        "name": "world",
        "description": (
            "World Model: estado materializado do mundo da contratação pública "
            "(entidades, contratos, relações, eventos e histórico), rede neuronal "
            "dinâmica (crescimento, poda, memória e previsão — mostrada como grafo), "
            "motor de grafo/tempo (relações, timestamps e causalidade candidata), "
            "simulador de futuro (t0 → t3 com cenários e Monte Carlo) e agente de "
            "investigação (Observe → Hypothesize → Search → Validate → Simulate → "
            "Evidence Report)."
        ),
    },
    {
        "name": "spa",
        "description": (
            "Páginas da interface (single-page app). Devolvem o `index.html` e "
            "existem para permitir abrir os ecrãs diretamente pelo endereço — não "
            "são endpoints de dados."
        ),
    },
]

# --------------------------------------------------------------------------
# Rotas da interface (SPA) e regras de atribuição de grupo
# --------------------------------------------------------------------------

SPA_PATHS: Tuple[str, ...] = (
    "/companies",
    "/companies/dashboard",
    "/companies/search",
    "/adjudicatarios",
    "/adjudicantes",
    "/entities/dashboard",
    "/entities/compare",
    "/entities/adjudicantes",
    "/entities/adjudicatarios",
    "/empresas-iq",
    "/empresas-global",
    "/pesquisa",
    "/sentimento",
    "/import",
    "/search",
    "/office",
    "/office/documentos",
    "/office/dossies",
    "/hermes",
    "/search360",
    "/search360/biblioteca",
    "/search360/grafo",
    "/search360/projetos",
    "/search360/dossie",
    "/scraper",
    "/scraper/agenda",
    "/scraper/fontes",
    "/scraper/execucoes",
    "/scraper/pesquisa",
    "/scraper/modelos",
    "/crm",
    "/crm/agenda",
    "/crm/contactos",
    "/crm/contas",
    "/crm/relatorios",
    "/contracts",
    "/contracts/dashboard",
    "/contracts/search",
    "/contracts/map",
    "/contratos-es",
    "/contribuintes",
    "/world",
    "/world/rede",
    "/gleif",
    "/gleif/mapa",
    "/gleif/ingestao",
    "/elastic",
    "/rag",
    "/forecast",
    "/trading",
    "/ticker-detail",
)

# Prefixo → grupo, aplicado por ordem (o mais específico primeiro).
PATH_TAG_RULES: Sequence[Tuple[str, str]] = (
    ("/adjudicat", "spa"),
    ("/empresas", "spa"),
    ("/pesquisa", "spa"),
    ("/sentimento", "spa"),
    ("/contracts/export", "contratos"),
    ("/contracts/analytics", "contratos"),
    ("/contracts/search", "contratos"),
    ("/contracts/status", "contratos"),
    ("/contracts/years", "contratos"),
    ("/contracts/autocomplete", "contratos"),
    ("/contracts/ingest", "contratos"),
    ("/contracts/chat", "contratos"),
    ("/contracts/dashboard", "spa"),
    ("/contracts/map", "spa"),
    ("/contracts", "contratos"),
    ("/companies-global", "companies-global"),
    ("/contribuintes", "contribuintes"),
    ("/world/rede", "spa"),
    ("/world", "world"),
    ("/gleif/mapa", "spa"),
    ("/gleif/ingestao", "spa"),
    ("/gleif", "gleif"),
    ("/societario", "societario"),
    ("/companies/role-summary", "empresas"),
    ("/companies", "empresas"),
    ("/entities/ingest", "empresas"),
    ("/entities/search", "empresas"),
    ("/entities/stats", "empresas"),
    ("/entities/countries", "empresas"),
    ("/entities/autocomplete", "empresas"),
    ("/entities", "empresas"),
    ("/trademarks", "empresas"),
    ("/firmas", "empresas"),
    ("/enrichment", "empresas"),
    ("/elastic/vectors", "vectors"),
    ("/elastic", "elastic"),
    ("/tickers", "market"),
    ("/forecast", "market"),
    ("/trading", "spa"),
    ("/ticker-detail", "spa"),
    ("/sentiment/analyze", "market"),
    ("/sentiment", "sentiment"),
    ("/favorites", "dossier"),
    ("/workspace", "dossier"),
    ("/import", "import"),
    ("/office/documentos", "spa"),
    ("/office/dossies", "spa"),
    ("/office", "spa"),
    ("/site", "cms"),
    ("/cms", "cms"),
    ("/hermes", "spa"),
    ("/search360", "spa"),
    ("/scraper", "spa"),
    ("/crm", "spa"),
    ("/rag", "spa"),
    ("/elastic", "spa"),
    ("/health", "core"),
    ("/chat", "core"),
)


def _is_spa_operation(path: str, method: str, summary: str) -> bool:
    """Diz se a operação devolve o `index.html` da interface.

    As rotas SPA são reconhecidas pelo nome da função/summary ("Serve Spa
    Page", "Serve Companies Spa Page", …). Assim, caminhos que servem página
    *e* dados (ex.: `GET /forecast` é ecrã, `POST /forecast` é previsão)
    recebem grupos diferentes.
    """
    if path.startswith("/{full_path}"):
        return True
    if path.rstrip("/") not in SPA_PATHS and path.rstrip("/") != "":
        return False
    if method.upper() != "GET":
        return False
    if not summary:
        return True
    return "spa page" in summary.lower()


def tag_for_path(path: str, method: str = "get", summary: str = "") -> str:
    """Devolve o grupo a atribuir a uma operação sem ``tags`` declaradas."""
    normalized = path.rstrip("/") or "/"
    if normalized == "/":
        return "core"
    if _is_spa_operation(path, method, summary):
        return "spa"
    for prefix, tag in PATH_TAG_RULES:
        if normalized == prefix or normalized.startswith(prefix + "/"):
            return tag
    return "core"


# --------------------------------------------------------------------------
# Segurança
# --------------------------------------------------------------------------

SECURITY_SCHEME_NAME = "bearerAuth"

SECURITY_SCHEMES: Dict[str, Any] = {
    SECURITY_SCHEME_NAME: {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "JWT",
        "description": (
            "Token de sessão devolvido por `POST /auth/login`. "
            "Enviar como `Authorization: Bearer <token>`."
        ),
    }
}

# Endpoints que não exigem sessão (usados para marcar a segurança global).
PUBLIC_PREFIXES: Tuple[str, ...] = (
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/openapi",
    "/auth/login",
    "/auth/register",
    "/proxy/status",
    # O site publicado é público: leitura sem sessão em `/site/…`.
    "/site",
)


# --------------------------------------------------------------------------
# Pós-processador
# --------------------------------------------------------------------------

_SPA_SUMMARY = "Página da interface (SPA)"


def custom_openapi(app: Any) -> Dict[str, Any]:
    """Constrói o `openapi.json` do IQ OS com grupos, segurança e servidores.

    É idempotente: guarda o resultado em ``app.openapi_schema``.
    """
    if getattr(app, "openapi_schema", None):
        return app.openapi_schema

    from fastapi.openapi.utils import get_openapi

    schema = get_openapi(
        title=app.title,
        version=app.version,
        openapi_version=app.openapi_version,
        description=app.description,
        routes=app.routes,
        tags=app.openapi_tags,
        servers=app.servers,
        terms_of_service=getattr(app, "terms_of_service", None),
        contact=getattr(app, "contact", None),
        license_info=getattr(app, "license_info", None),
    )

    components = schema.setdefault("components", {})
    if SECURITY_SCHEMES:
        components.setdefault("securitySchemes", {}).update(SECURITY_SCHEMES)

    known_tags = {tag["name"] for tag in TAGS_METADATA}

    for path, operations in schema.get("paths", {}).items():
        for method, operation in operations.items():
            if method.lower() not in {"get", "post", "put", "patch", "delete", "head", "options"}:
                continue
            if not isinstance(operation, dict):
                continue

            tags = operation.get("tags") or []
            tags = [tag for tag in tags if tag in known_tags]
            summary = operation.get("summary") or ""
            if not tags:
                tags = [tag_for_path(path, method, summary)]
            operation["tags"] = tags

            if _is_spa_operation(path, method, summary):
                if summary in {"Serve Spa Page", "Serve Spa Deep Link"} or not summary:
                    operation["summary"] = _SPA_SUMMARY
                    operation.setdefault(
                        "description",
                        "Devolve o `index.html` da interface; as rotas de dados "
                        "estão nos restantes grupos.",
                    )

            if not operation.get("description") and operation.get("summary"):
                operation["description"] = operation["summary"]

            is_public = any(path.startswith(prefix) for prefix in PUBLIC_PREFIXES)
            if not is_public and SECURITY_SCHEMES:
                operation.setdefault("security", [{SECURITY_SCHEME_NAME: []}])

    schema["tags"] = TAGS_METADATA
    schema.setdefault("info", {})["x-logo"] = {"url": "/docs"}
    app.openapi_schema = schema
    return schema


def describe() -> Dict[str, Any]:
    """Resumo legível do catálogo (usado por `/openapi/summary`)."""
    return {
        "title": "IQ OS API",
        "tags": [
            {"name": tag["name"], "description": tag["description"]}
            for tag in TAGS_METADATA
        ],
        "groups": len(TAGS_METADATA),
        "security": list(SECURITY_SCHEMES),
        "servers": SERVERS,
        "docs": {"swagger": "/docs", "redoc": "/redoc", "spec": "/openapi.json"},
        "mcp": {"command": "python -m mcp_server", "module": "mcp_server"},
    }
