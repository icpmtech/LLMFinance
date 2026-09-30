"""Catálogo curado de operações do IQ OS expostas pelo servidor MCP.

Cada entrada liga uma ferramenta MCP (nome legível + descrição em português)
a um endpoint real do backend. O catálogo cobre todos os módulos da
plataforma; o que não estiver aqui continua acessível pelas ferramentas
genéricas ``iqos_api_call``, ``iqos_search_endpoints`` e
``iqos_describe_endpoint``, que leem a especificação OpenAPI em tempo real.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

_QUERY = "query"
_PATH = "path"
_BODY = "body"


@dataclass(frozen=True)
class Param:
    """Parâmetro de uma operação (query, path ou corpo JSON)."""

    name: str
    type: str = "str"
    description: str = ""
    required: bool = False
    location: str = _QUERY
    default: Any = None

    @property
    def python_name(self) -> str:
        """Nome válido em Python (``from`` → ``from_``, ``type`` → ``type_``)."""
        import keyword

        candidate = self.name.replace("-", "_").replace(".", "_")
        if not candidate.isidentifier() or keyword.iskeyword(candidate):
            candidate = f"{candidate}_"
        return candidate


@dataclass(frozen=True)
class Operation:
    """Uma ferramenta MCP e o endpoint correspondente."""

    name: str
    method: str
    path: str
    summary: str
    tag: str
    params: Tuple[Param, ...] = field(default_factory=tuple)
    read_only: bool = True
    destructive: bool = False

    @property
    def body_param(self) -> Optional[Param]:
        for param in self.params:
            if param.location == _BODY:
                return param
        return None

    @property
    def query_params(self) -> List[Param]:
        return [p for p in self.params if p.location == _QUERY]

    @property
    def path_params(self) -> List[Param]:
        return [p for p in self.params if p.location == _PATH]


def Q(name: str, type: str = "str", description: str = "", default: Any = None) -> Param:
    """Parâmetro de *query* opcional."""
    return Param(name, type, description, False, _QUERY, default)


def RQ(name: str, type: str = "str", description: str = "") -> Param:
    """Parâmetro de *query* obrigatório."""
    return Param(name, type, description, True, _QUERY, None)


def PTH(name: str, type: str = "str", description: str = "") -> Param:
    """Parâmetro de caminho (obrigatório)."""
    return Param(name, type, description, True, _PATH, None)


def PAY(description: str = "Corpo JSON do pedido (ver o esquema no Swagger).") -> Param:
    """Corpo JSON (`dict`)."""
    return Param("payload", "dict", description, False, _BODY, None)


def _ops(*items: Operation) -> List[Operation]:
    return list(items)


def _read(name: str, method: str, path: str, summary: str, tag: str, *params: Param) -> Operation:
    return Operation(name, method, path, summary, tag, tuple(params), True, False)


def _write(name: str, method: str, path: str, summary: str, tag: str, *params: Param) -> Operation:
    return Operation(name, method, path, summary, tag, tuple(params), False, False)


def _danger(name: str, method: str, path: str, summary: str, tag: str, *params: Param) -> Operation:
    return Operation(name, method, path, summary, tag, tuple(params), False, True)


# ---------------------------------------------------------------------------
# Catálogo
# ---------------------------------------------------------------------------

OPERATIONS: List[Operation] = _ops(
    # -- core ------------------------------------------------------------
    _read("iqos_health", "GET", "/health", "Estado do serviço: modelos e features carregados.", "core"),
    _read("iqos_root", "GET", "/", "Identificação do serviço e features.", "core"),
    _read("iqos_openapi_summary", "GET", "/openapi/summary", "Resumo do catálogo OpenAPI (grupos, segurança, ligações úteis).", "core"),
    _write("iqos_chat", "POST", "/chat", "Responde no chat seguindo a skill do pedido.", "core",
           Q("backend", "str", "Modelo a usar (gpt2, mistral, …)", "gpt2"), PAY()),
    # -- auth ------------------------------------------------------------
    _read("auth_me", "GET", "/auth/me", "Dados da conta autenticada.", "auth"),
    _read("auth_sessions", "GET", "/auth/sessions", "Sessões ativas da conta.", "auth"),
    _read("auth_stats", "GET", "/auth/stats", "Números do sistema de contas (administradores).", "auth"),
    _write("auth_login", "POST", "/auth/login", "Autentica e devolve token de sessão.", "auth", PAY()),
    _write("auth_register", "POST", "/auth/register", "Cria conta e inicia sessão.", "auth", PAY()),
    _write("auth_logout", "POST", "/auth/logout", "Termina a sessão atual.", "auth"),
    # -- admin -----------------------------------------------------------
    _read("admin_overview", "GET", "/admin/overview", "Panorama geral da solução (painel de administração).", "admin"),
    _read("admin_users", "GET", "/admin/users", "Lista contas, com pesquisa e filtros de papel/estado.", "admin",
          Q("q", "str", "Pesquisa por nome ou email"), Q("role", "str", "admin | member"),
          Q("status", "str", "active | suspended"), Q("limit", "int", "Máximo de contas", 200)),
    _read("admin_events", "GET", "/admin/events", "Visualizador de eventos com filtros e paginação.", "admin",
          Q("level", "str", "info,warning,error"), Q("source", "str", "api, auth, admin, app"),
          Q("q", "str", "Pesquisa livre"), Q("since", "str", "ISO 8601"), Q("until", "str", "ISO 8601"),
          Q("size", "int", "Resultados", 50)),
    _read("admin_events_stats", "GET", "/admin/events/stats", "Contagens de eventos por nível, origem e hora.", "admin",
          Q("hours", "int", "Janela em horas", 24)),
    _read("admin_logs", "GET", "/admin/logs", "Lista os ficheiros de log disponíveis.", "admin"),
    _read("admin_log_tail", "GET", "/admin/logs/{name}", "Últimas linhas de um ficheiro de log.", "admin",
          PTH("name", "str", "Nome do ficheiro"), Q("lines", "int", "Linhas", 200)),
    # -- rag -------------------------------------------------------------
    _read("rag_documents", "GET", "/rag/documents", "Lista os documentos indexados no RAG.", "rag"),
    _read("rag_document", "GET", "/rag/documents/{doc_id}", "Detalhes de um documento do RAG.", "rag",
          PTH("doc_id")),
    _read("rag_document_history", "GET", "/rag/documents/{doc_id}/history", "Histórico de ações de um documento.", "rag",
          PTH("doc_id")),
    _read("rag_document_graph", "GET", "/rag/documents/{doc_id}/graph", "Grafo de chunks do documento.", "rag",
          PTH("doc_id"), Q("top_k", "int", "Vizinhos por chunk", 5)),
    _write("rag_chat", "POST", "/rag/chat", "Responde a uma pergunta com RAG sobre os documentos.", "rag",
           Q("mode", "str", "dense | hybrid | hybrid_rerank | crag | crag_rerank"), PAY()),
    _write("rag_explain", "POST", "/rag/explain", "Explica como a resposta RAG foi construída.", "rag", PAY()),
    _write("rag_reprocess", "POST", "/rag/documents/{doc_id}/reprocess", "Reprocessa um documento (Markdown, chunks, embeddings).", "rag",
           PTH("doc_id"), Q("converter", "str", "auto | markitdown | pymupdf")),
    # -- market ----------------------------------------------------------
    _read("market_tickers", "GET", "/tickers", "Lista os tickers conhecidos.", "market",
          Q("query", "str", "Filtro por símbolo ou nome")),
    _read("market_search_yahoo", "GET", "/tickers/search/yahoo", "Pesquisa tickers/empresas no Yahoo Finance.", "market",
          RQ("query", "str", "Termo a pesquisar")),
    _read("market_info", "GET", "/tickers/{ticker}/info", "Informação fundamental de um ticker.", "market",
          PTH("ticker")),
    _read("market_history", "GET", "/tickers/{ticker}/history", "Histórico de preços de um ticker.", "market",
          PTH("ticker"), Q("period", "str", "1mo|3mo|6mo|1y|2y|5y|10y|max", "1y")),
    _read("market_news", "GET", "/tickers/{ticker}/news", "Notícias recentes de um ticker.", "market",
          PTH("ticker"), Q("max_items", "int", "Nº de notícias", 10)),
    _read("market_financials", "GET", "/tickers/{ticker}/financials", "Demonstrações financeiras anuais e trimestrais.", "market",
          PTH("ticker")),
    _read("market_sec_filings", "GET", "/tickers/{ticker}/sec-filings", "SEC filings publicados no Yahoo Finance.", "market",
          PTH("ticker"), Q("days", "int", "Janela em dias", 365)),
    _read("market_holders", "GET", "/tickers/{ticker}/holders", "Detentores institucionais e transações de insiders.", "market",
          PTH("ticker")),
    _read("market_recommendations", "GET", "/tickers/{ticker}/recommendations", "Recomendações de analistas e upgrades/downgrades.", "market",
          PTH("ticker")),
    _read("market_calendar", "GET", "/tickers/{ticker}/calendar", "Calendário e datas de resultados.", "market",
          PTH("ticker")),
    _read("market_sustainability", "GET", "/tickers/{ticker}/sustainability", "Indicadores ESG.", "market",
          PTH("ticker")),
    _read("market_technical", "GET", "/tickers/{ticker}/technical", "Indicadores técnicos calculados do histórico.", "market",
          PTH("ticker"), Q("period", "str", "1mo|3mo|6mo|1y|2y|5y|10y|max", "1y")),
    _read("market_technical_explain", "GET", "/tickers/{ticker}/technical/explain", "Resumo textual dos painéis técnicos.", "market",
          PTH("ticker"), Q("period", "str", "Período", "1y")),
    _write("market_forecast", "POST", "/forecast", "Pipeline ARIMA/Kronos: previsões e séries.", "market", PAY()),
    _write("market_ticker_sentiment", "POST", "/sentiment/analyze/{ticker}", "Sentimento + previsão blended de um ticker.", "market",
           PTH("ticker"), Q("backend", "str", "arima | kronos", "kronos"),
           Q("future_days", "int", "Dias a prever", 5), Q("period", "str", "Período", "1y")),
    # -- elastic ---------------------------------------------------------
    _read("elastic_status", "GET", "/elastic/status", "Estado da ligação ao Elasticsearch.", "elastic"),
    _read("elastic_indices", "GET", "/elastic/indices", "Índices da plataforma com contagem de documentos.", "elastic"),
    _read("elastic_tickers", "GET", "/elastic/tickers", "Tickers com preços indexados.", "elastic"),
    _read("elastic_search_prices", "GET", "/elastic/search/prices/{ticker}", "Pesquisa preços indexados por ticker e datas.", "elastic",
          PTH("ticker"), Q("start_date", "str", "YYYY-MM-DD"), Q("end_date", "str", "YYYY-MM-DD"),
          Q("size", "int", "Pontos", 1000)),
    _read("elastic_search_news", "GET", "/elastic/search/news/{ticker}", "Pesquisa notícias indexadas de um ticker.", "elastic",
          PTH("ticker"), Q("q", "str", "Termo no título/resumo"), Q("start_date", "str", "YYYY-MM-DD"),
          Q("end_date", "str", "YYYY-MM-DD"), Q("size", "int", "Resultados", 50)),
    _read("elastic_search_global", "GET", "/elastic/search/global", "Pesquisa global (tipo Google) em todas as notícias.", "elastic",
          RQ("q", "str", "Termo a pesquisar"), Q("from", "int", "Offset", 0),
          Q("size", "int", "Resultados", 20), Q("source", "str", "Publisher"), Q("sentiment", "str", "Filtro de sentimento")),
    _read("elastic_autocomplete", "GET", "/elastic/search/autocomplete", "Sugestões de autocomplete (tickers, títulos, publishers, tópicos).", "elastic",
          RQ("q", "str", "Prefixo"), Q("size", "int", "Sugestões", 12)),
    _read("elastic_news_graph", "GET", "/elastic/graph/news/{ticker}", "Grafo de notícias e entidades de um ticker.", "elastic",
          PTH("ticker"), Q("source", "str", "es | build", "es")),
    _write("elastic_analyze_news", "POST", "/elastic/analyze/news/{ticker}", "Analisa notícias indexadas com NLP (sentimento, PT, entidades).", "elastic",
           PTH("ticker"), Q("q", "str", "Termo"), Q("size", "int", "Notícias", 50),
           Q("backend", "str", "gpt2 | mistral", "gpt2")),
    # -- contratos (PT) --------------------------------------------------
    _read("contratos_status", "GET", "/contracts/status", "Contagem total e anos indexados de contratos PT.", "contratos"),
    _read("contratos_years", "GET", "/contracts/years", "Anos disponíveis e total indexado por ano.", "contratos"),
    _write("contratos_search", "POST", "/contracts/search", "Pesquisa contratos públicos portugueses com filtros.", "contratos", PAY()),
    _read("contratos_analytics", "GET", "/contracts/analytics", "Agregações para o dashboard de contratos PT.", "contratos",
          Q("q", "str", "Texto livre"), Q("year", "int", "Ano"), Q("entity", "str", "Entidade"),
          Q("nif", "str", "NIF"), Q("cpv_code", "str", "CPV"), Q("region", "str", "Região NUTS"),
          Q("min_price", "float", "Valor mínimo"), Q("max_price", "float", "Valor máximo"),
          Q("top_entities", "int", "Top entidades", 8), Q("top_cpv", "int", "Top CPV", 8)),
    _read("contratos_regional", "GET", "/contracts/analytics/regional", "Agrega contratos por região NUTS.", "contratos",
          Q("year", "int", "Ano"), Q("size", "int", "Regiões", 30)),
    _read("contratos_network", "GET", "/contracts/analytics/network", "Rede de entidades ligadas por contratos.", "contratos",
          Q("limit", "int", "Nós", 500), Q("region", "str", "Região"), Q("nif", "str", "NIF"), Q("role", "str", "all | adjudicante | adjudicatario")),
    _read("contratos_relations", "GET", "/contracts/analytics/relations", "Relações agregadas adjudicante↔adjudicatário.", "contratos",
          Q("limit", "int", "Relações", 1000), Q("region", "str", "Região"), Q("nif", "str", "NIF"),
          Q("counterparty_nif", "str", "Contraparte"), Q("role", "str", "Papel")),
    _read("contratos_graph_dimensions", "GET", "/contracts/analytics/graph/dimensions", "Dimensões disponíveis para construir grafos de contratos.", "contratos"),
    _read("contratos_graph", "GET", "/contracts/analytics/graph", "Constrói um grafo de contratos a partir de dimensões.", "contratos",
          RQ("dimension_a", "str", "Dimensão dos nós (adjudicante, cpv_classe, regiao…)"),
          Q("dimension_b", "str", "Dimensão das arestas"), Q("metric", "str", "valor | contratos", "valor"),
          Q("mode", "str", "auto | exato | amostra", "auto"), Q("year", "int", "Ano"), Q("region", "str", "Região"),
          Q("limit", "int", "Nós a manter (0 = todos)", 60), Q("edge_limit", "int", "Arestas (0 = todas)", 400)),
    _read("contratos_autocomplete", "GET", "/contracts/autocomplete", "Autocomplete de entidades e CPV.", "contratos",
          RQ("q", "str", "Prefixo"), Q("size", "int", "Sugestões", 12)),
    _read("contrato_detail", "GET", "/contracts/{idcontrato}", "Ficha de um contrato individual.", "contratos",
          PTH("idcontrato")),
    _write("contratos_chat", "POST", "/contracts/chat", "Responde a perguntas sobre contratos públicos com RAG.", "contratos", PAY()),
    _write("contrato_analyze", "POST", "/contracts/{idcontrato}/analyze", "Analisa um contrato com IA e pesquisa relacionada.", "contratos",
           PTH("idcontrato"), PAY()),
    # -- contratos Espanha ------------------------------------------------
    _read("contratos_es_status", "GET", "/contracts-es/status", "Volumetria do índice de contratos de Espanha.", "contratos-es"),
    _read("contratos_es_meta", "GET", "/contracts-es/meta", "ZIPs disponíveis, JSONL normalizados e listas CODICE.", "contratos-es"),
    _read("contratos_es_analytics", "GET", "/contracts-es/analytics", "Agregações do dashboard de contratos de Espanha.", "contratos-es",
          Q("q", "str", "Texto livre"), Q("ano", "int", "Ano"), Q("fonte", "str", "licitaciones | menores"),
          Q("tipo", "str", "Código ou rótulo CODICE"), Q("estado", "str", "PUB/ADJ/RES…"),
          Q("organo", "str", "Órgão"), Q("adjudicatario", "str", "Adjudicatário"),
          Q("min_value", "float", "Valor mínimo"), Q("max_value", "float", "Valor máximo")),
    _write("contratos_es_search", "POST", "/contracts-es/search", "Pesquisa contratos de Espanha com filtros e facetas.", "contratos-es", PAY()),
    _read("contratos_es_autocomplete", "GET", "/contracts-es/autocomplete", "Sugestões de órgãos, adjudicatários e CPV (Espanha).", "contratos-es",
          RQ("q", "str", "Prefixo"), Q("size", "int", "Sugestões", 10)),
    _read("contratos_es_entities", "GET", "/contracts-es/entities", "Entidades de Espanha (órgãos e adjudicatárias) por agregação.", "contratos-es",
          Q("q", "str", "Nome (total ou parcial)"), Q("kind", "str", "organo | adjudicatario | all", "all"),
          Q("ano", "int", "Ano"), Q("size", "int", "Resultados", 20)),
    _read("contratos_es_imports", "GET", "/contracts-es/imports", "Importações em curso e recentes.", "contratos-es"),
    _read("contrato_es_detail", "GET", "/contracts-es/{doc_id}", "Detalhe de um contrato de Espanha.", "contratos-es",
          PTH("doc_id", "str", "Id do documento no Elasticsearch")),
    _danger("contratos_es_import", "POST", "/contracts-es/import", "Arranca a importação de um ano do PLACSP em segundo plano.", "contratos-es", PAY()),
    # -- empresas --------------------------------------------------------
    _read("empresas_search", "GET", "/entities/search", "Pesquisa empresas no cadastro de entidades.", "empresas",
          Q("q", "str", "Nome ou NIF"), Q("country", "str", "País"), Q("role", "str", "all | adjudicante | adjudicatario"),
          Q("min_contracts", "int", "Mínimo de contratos"), Q("min_value", "float", "Valor mínimo"),
          Q("sort_by", "str", "name | contracts_count | total_value"), Q("sort_order", "str", "asc | desc"),
          Q("size", "int", "Resultados", 20), Q("from", "int", "Offset", 0)),
    _read("empresas_stats", "GET", "/entities/stats", "Estatísticas do cadastro de entidades.", "empresas"),
    _read("empresas_countries", "GET", "/entities/countries", "Países disponíveis no cadastro.", "empresas"),
    _read("empresas_autocomplete", "GET", "/entities/autocomplete", "Sugestões de empresas para autocompletar.", "empresas",
          RQ("q", "str", "Prefixo"), Q("size", "int", "Sugestões", 10)),
    _read("empresa_detail", "GET", "/entities/{nif}", "Ficha da empresa (cadastro + enriquecimento guardado).", "empresas",
          PTH("nif")),
    _read("empresa_contratos", "GET", "/companies/{nif}/contracts", "Contratos de uma empresa.", "empresas",
          PTH("nif"), Q("role", "str", "all | adjudicante | adjudicatario", "all"),
          Q("size", "int", "Contratos", 20), Q("from", "int", "Offset", 0)),
    _read("empresa_analytics", "GET", "/companies/{nif}/analytics", "Dashboard de analytics de uma empresa.", "empresas",
          PTH("nif"), Q("role", "str", "Papel", "all"), Q("year", "int", "Ano")),
    _read("empresa_marcas", "GET", "/companies/{nif}/trademarks", "Marcas do INPI indexadas na ficha da empresa.", "empresas",
          PTH("nif"), Q("q", "str", "Filtro pelo nome da marca"), Q("size", "int", "Marcas", 100)),
    _read("empresa_firmas", "GET", "/companies/{nif}/firmas", "Firmas/nomes comerciais (RNPC) da empresa.", "empresas",
          PTH("nif"), Q("q", "str", "Filtro pelo nome da firma"), Q("size", "int", "Firmas", 100)),
    _read("empresas_role_summary", "POST", "/companies/role-summary", "Dashboard agregado por papel (adjudicantes, adjudicatários ou ambos).", "empresas", PAY()),
    _write("empresa_enriquecer", "POST", "/companies/{nif}/enrich", "Obtém marcas (INPI) e/ou firmas (RNPC) e guarda na ficha.", "empresas",
           PTH("nif"), Q("include_trademarks", "bool", "Obter marcas do INPI", True),
           Q("include_firmas", "bool", "Obter firmas do RNPC", True),
           Q("max_trademarks", "int", "Máximo de marcas", 50), Q("max_firmas", "int", "Máximo de firmas", 20)),
    _read("marcas_search", "GET", "/trademarks/search", "Pesquisa marcas indexadas (INPI).", "empresas",
          Q("q", "str", "Nome da marca"), Q("holder_name", "str", "Titular"), Q("nice_class", "str", "Classe de Nice"),
          Q("mark_type", "str", "Tipo de marca"), Q("size", "int", "Resultados", 20)),
    _read("firmas_search", "GET", "/firmas/search", "Pesquisa firmas/nomes comerciais (RNPC).", "empresas",
          Q("q", "str", "Nome"), Q("concelho", "str", "Concelho"), Q("cae", "str", "CAE"),
          Q("situacao", "str", "Situação"), Q("size", "int", "Resultados", 20)),
    _read("enrichment_indices", "GET", "/enrichment/indices", "Estado dos índices de enriquecimento (INPI e RNPC).", "empresas"),
    # -- companies-global ------------------------------------------------
    _read("empresas_global_sources", "GET", "/companies-global/sources", "Fontes disponíveis na pesquisa global.", "companies-global"),
    _read("empresas_global_search", "GET", "/companies-global/search", "Pesquisa empresas/entidades em todas as fontes.", "companies-global",
          Q("q", "str", "Nome, NIF, marca, órgão ou conta"),
          Q("source", "str", "all | entity | firma | trademark | organo_es | adjudicataria_es | crm", "all"),
          Q("size", "int", "Resultados", 24), Q("offset", "int", "Offset", 0)),
    # -- search ----------------------------------------------------------
    _read("search_scopes", "GET", "/search/scopes", "Âmbitos disponíveis na pesquisa da plataforma.", "search"),
    _read("search_unified", "GET", "/search/unified", "Pesquisa em todos os âmbitos em paralelo, com resultados agrupados.", "search",
          Q("q", "str", "Texto a pesquisar"),
          Q("scope", "str", "all | scraped | contracts | contracts_es | entities | trademarks | firmas | news | market | crm", "all"),
          Q("size", "int", "Resultados por âmbito", 8), Q("offset", "int", "Offset", 0)),
    _read("search_suggest", "GET", "/search/suggest", "Sugestões para autocompletar a pesquisa.", "search",
          RQ("q", "str", "Prefixo"), Q("limit", "int", "Sugestões", 8)),
    # -- search360 -------------------------------------------------------
    _read("search360_meta", "GET", "/search360/meta", "Metamodelo: fontes, famílias, capacidades e índices.", "search360"),
    _read("search360_status", "GET", "/search360/status", "Diagnóstico das fontes e volumetria interna.", "search360"),
    _read("search360_suggest", "GET", "/search360/suggest", "Sugestões de tema (entidades e enciclopédia).", "search360",
          RQ("q", "str", "Tema"), Q("limit", "int", "Sugestões", 6)),
    _write("search360_search", "POST", "/search360/search", "Pesquisa federada: um tema, todas as fontes escolhidas.", "search360", PAY()),
    _write("search360_topic", "POST", "/search360/topic", "Dossiê 360 de um tema: resultados, biblioteca, grafo, indicadores e síntese.", "search360", PAY()),
    _write("search360_library", "POST", "/search360/library", "Organiza o tema em pastas e ficheiros por família/tipo.", "search360", PAY()),
    _write("search360_graph", "POST", "/search360/graph", "Grafo de navegação: tema no centro, entidades e documentos em volta.", "search360", PAY()),
    _write("search360_synthesis", "POST", "/search360/ai/synthesis", "Síntese do tema com citações das fontes.", "search360", PAY()),
    _read("search360_dossiers", "GET", "/search360/dossiers", "Dossiês 360 guardados (resumo).", "search360",
          Q("project_id", "str", "Projeto"), Q("term", "str", "Tema"), Q("limit", "int", "Resultados", 60)),
    _read("search360_dossier", "GET", "/search360/dossiers/{dossier_id}", "Dossiê guardado completo (retrato + síntese).", "search360",
          PTH("dossier_id")),
    _write("search360_save_dossier", "POST", "/search360/dossiers", "Guarda o dossiê 360 de um tema num projeto.", "search360", PAY()),
    _read("search360_projects", "GET", "/search360/projects", "Projetos (áreas de trabalho) com o número de dossiês.", "search360"),
    # -- hermes ----------------------------------------------------------
    _read("hermes_meta", "GET", "/hermes/meta", "Metamodelo do Hermes: modos, fontes, índices e modelo de IA.", "hermes"),
    _write("hermes_ask", "POST", "/hermes/ask", "Investiga a pergunta e devolve resposta citada, evidências e sub-perguntas.", "hermes", PAY()),
    # -- jarvis ----------------------------------------------------------
    _read("jarvis_meta", "GET", "/jarvis/meta", "Metamodelo do Jarvis: gateways (Hermes, MCP, web), ferramentas, vozes e modelo.", "jarvis"),
    _read("jarvis_tools", "GET", "/jarvis/tools", "Catálogo de ferramentas dos gateways do Jarvis.", "jarvis",
          Q("gateway", "str", "Limitar a um gateway: hermes, mcp ou web")),
    _read("jarvis_voice", "GET", "/jarvis/voice", "Estado da voz do Jarvis: transcrição (STT), síntese (TTS) e vozes.", "jarvis"),
    _write(
        "jarvis_ask",
        "POST",
        "/jarvis/ask",
        "Pergunta ao Jarvis: passa pelos gateways (Hermes, MCP do sistema e browser) e devolve resposta, "
        "plano, passos e citações. Corpo: question (obrigatório), depth, backend, history, voice, speak.",
        "jarvis",
        PAY(),
    ),
    _write("jarvis_speak", "POST", "/jarvis/speak", "Sintetiza texto em áudio (mp3) com a voz do servidor.", "jarvis", PAY()),
    # -- researcher ------------------------------------------------------
    _read("researcher_tools", "GET", "/researcher/tools", "Catálogo fechado de ferramentas do investigador.", "researcher"),
    _write("researcher_investigate", "POST", "/researcher/investigate", "Executa uma investigação e devolve relatório com audit trail.", "researcher", PAY()),
    # -- agents ----------------------------------------------------------
    _read("agents_list", "GET", "/agents", "Lista os agentes dinâmicos acessíveis.", "agents"),
    _read("agent_get", "GET", "/agents/{agent_id}", "Configuração de um agente dinâmico.", "agents", PTH("agent_id")),
    _read("agents_tools_catalog", "GET", "/agents/tools/catalog", "Catálogo de ferramentas para construir agentes.", "agents"),
    _write("agent_run", "POST", "/agents/{agent_id}/run", "Executa um agente dinâmico e devolve a resposta final.", "agents",
           PTH("agent_id"), PAY()),
    _write("agent_create", "POST", "/agents", "Cria ou atualiza a configuração de um agente.", "agents", PAY()),
    # -- ontology --------------------------------------------------------
    _read("ontology_get", "GET", "/ontology", "Ontologia completa (tipos de objeto, ligações e ações).", "ontology"),
    _read("ontology_summary", "GET", "/ontology/summary", "Resumo da ontologia + grafo de tipos.", "ontology"),
    _read("ontology_status", "GET", "/ontology/status", "Disponibilidade das fontes e volumetria por índice.", "ontology"),
    _read("ontology_object_types", "GET", "/ontology/object-types", "Tipos de objeto com contagens, domínio e origem.", "ontology"),
    _read("ontology_object_type", "GET", "/ontology/object-types/{type_id}", "Detalhe de um tipo: propriedades, origens, ligações e ações.", "ontology",
          PTH("type_id")),
    _read("ontology_link_types", "GET", "/ontology/link-types", "Tipos de ligação da ontologia.", "ontology"),
    _read("ontology_actions", "GET", "/ontology/actions", "Ações disponíveis na ontologia.", "ontology",
          Q("object_type", "str", "Filtrar por tipo de objeto")),
    _read("ontology_object", "GET", "/ontology/objects/{type_id}/{object_id}", "Objeto individual, com origem e ligações opcionais.", "ontology",
          PTH("type_id"), PTH("object_id"), Q("include_source", "bool", "Incluir documento de origem", False),
          Q("with_links", "bool", "Incluir ligações", False)),
    _write("ontology_query_objects", "POST", "/ontology/objects/{type_id}/query", "Consulta objetos de um tipo (pesquisa, filtros, ordenação).", "ontology",
           PTH("type_id"), PAY()),
    _write("ontology_object_links", "POST", "/ontology/objects/{type_id}/{object_id}/links", "Navega nas relações de um objeto.", "ontology",
           PTH("type_id"), PTH("object_id"), Q("link", "str", "Filtrar por ligação"), Q("size", "int", "Ligações", 10)),
    _write("ontology_resolve", "POST", "/ontology/resolve", "Resolve texto livre (NIF, nome, ticker) em objetos canónicos.", "ontology", PAY()),
    _write("ontology_ai_context", "POST", "/ontology/ai/context", "Contexto ontológico de uma pergunta (objetos, relações, grounding).", "ontology", PAY()),
    _write("ontology_ai_answer", "POST", "/ontology/ai/answer", "Resposta factual construída só com objetos e relações da ontologia.", "ontology", PAY()),
    _write("ontology_ai_validate", "POST", "/ontology/ai/validate", "Validação anti-alucinação de uma resposta.", "ontology", PAY()),
    _write("ontology_ai_design", "POST", "/ontology/ai/design", "Propõe tipos de objeto, propriedades e ligações para a ontologia ativa.", "ontology", PAY()),
    _write("ontology_graph_explore", "POST", "/ontology/graph/explore", "Grafo de exploração a partir de um objeto.", "ontology", PAY()),
    _read("ontology_ai_tools", "GET", "/ontology/ai/tools", "Ferramentas (esquemas de função) geradas a partir da ontologia.", "ontology",
          Q("include_crm", "bool", "Incluir ferramentas de CRM", False)),
    _read("ontology_sources", "GET", "/ontology/sources", "Fontes de dados da ontologia e último diagnóstico.", "ontology"),
    _read("ontology_projects", "GET", "/ontology/projects", "Projetos (áreas de trabalho) da ontologia.", "ontology"),
    _read("ontology_dossiers", "GET", "/ontology/dossiers", "Fichas de análise (todas ou de um projeto).", "ontology",
          Q("project_id", "str", "Projeto")),
    # -- crm -------------------------------------------------------------
    _read("crm_meta", "GET", "/crm/meta", "Fases, estados e tipos do CRM.", "crm"),
    _read("crm_overview", "GET", "/crm/overview", "Indicadores do CRM: pipeline, previsão, conversão e agenda.", "crm",
          Q("months", "int", "Janela em meses", 6)),
    _read("crm_accounts", "GET", "/crm/accounts", "Contas (empresas) do utilizador.", "crm",
          Q("q", "str", "Nome, NIF, email, cidade"), Q("status", "str", "Estado"), Q("sector", "str", "Setor"),
          Q("country", "str", "País"), Q("size", "int", "Resultados", 200), Q("from", "int", "Offset", 0)),
    _read("crm_contacts", "GET", "/crm/contacts", "Contactos, opcionalmente filtrados por conta.", "crm",
          Q("q", "str", "Pesquisa"), Q("account_id", "str", "Conta"), Q("size", "int", "Resultados", 200)),
    _read("crm_deals", "GET", "/crm/deals", "Oportunidades do pipeline.", "crm",
          Q("q", "str", "Pesquisa"), Q("stage", "str", "Fase"), Q("account_id", "str", "Conta"),
          Q("size", "int", "Resultados", 300)),
    _read("crm_activities", "GET", "/crm/activities", "Atividades e compromissos (agenda comercial).", "crm",
          Q("q", "str", "Pesquisa"), Q("account_id", "str", "Conta"), Q("deal_id", "str", "Oportunidade"),
          Q("done", "bool", "Concluídas"), Q("size", "int", "Resultados", 300)),
    _read("crm_entities_search", "GET", "/crm/entities/search", "Sugestões do EmpresasIQ para ligar a uma conta.", "crm",
          RQ("q", "str", "Nome ou NIF"), Q("size", "int", "Sugestões", 10)),
    _read("crm_account_timeline", "GET", "/crm/accounts/{account_id}/timeline", "Conta com contactos, oportunidades e atividades.", "crm",
          PTH("account_id")),
    _read("crm_record_get", "GET", "/crm/{kind}/{record_id}", "Devolve um registo do CRM (account, contact, deal, activity).", "crm",
          PTH("kind"), PTH("record_id")),
    _write("crm_record_create", "POST", "/crm/{kind}", "Cria um registo do CRM (account, contact, deal, activity).", "crm",
           PTH("kind"), PAY()),
    _write("crm_record_update", "PATCH", "/crm/{kind}/{record_id}", "Atualiza parcialmente um registo do CRM.", "crm",
           PTH("kind"), PTH("record_id"), PAY()),
    _write("crm_account_from_entity", "POST", "/crm/accounts/from-entity", "Cria uma conta de CRM a partir de um NIF do cadastro.", "crm", PAY()),
    _danger("crm_record_delete", "DELETE", "/crm/{kind}/{record_id}", "Apaga um registo do CRM (apagar uma conta arrasta os ligados).", "crm",
            PTH("kind"), PTH("record_id")),
    # -- office ----------------------------------------------------------
    _read("office_documents", "GET", "/office/documents", "Documentos do Office (resumos), com pastas e panorama.", "office",
          Q("folder_id", "str", "Pasta (root = sem pasta)"), Q("q", "str", "Título, texto ou etiquetas"),
          Q("kind", "str", "Tipo"), Q("tag", "str", "Etiqueta"), Q("limit", "int", "Documentos", 200)),
    _read("office_document", "GET", "/office/documents/{document_id}", "Documento completo (título, Markdown, pasta, etiquetas).", "office",
          PTH("document_id")),
    _read("office_stats", "GET", "/office/stats", "Panorama do Office: documentos, pastas, palavras.", "office"),
    _read("office_folders", "GET", "/office/folders", "Pastas do Office com número de documentos.", "office"),
    _read("office_dossiers_available", "GET", "/office/dossiers/available", "Dossiês 360 disponíveis para trazer para o Office.", "office",
          Q("limit", "int", "Resultados", 40)),
    _write("office_save_document", "POST", "/office/documents", "Cria ou altera um documento do Office.", "office", PAY()),
    _write("office_patch_document", "PATCH", "/office/documents/{document_id}", "Alteração parcial de um documento (título, pasta, etiquetas, fixar).", "office",
           PTH("document_id"), PAY()),
    _write("office_document_from_dossier", "POST", "/office/documents/from-dossier/{dossier_id}", "Traz um dossiê 360 guardado para o Office.", "office",
           PTH("dossier_id"), PAY("Opcional: {\"create_new\": true}")),
    _danger("office_delete_document", "DELETE", "/office/documents/{document_id}", "Apaga um documento do Office.", "office",
            PTH("document_id")),
    # -- email -----------------------------------------------------------
    _read("email_meta", "GET", "/email/meta", "Fornecedores suportados (servidores, portas) e o que a app faz.", "email"),
    _read("email_stats", "GET", "/email/stats", "Panorama das contas de email do utilizador.", "email"),
    _read("email_accounts", "GET", "/email/accounts", "Contas de email do utilizador (sem palavra-passe).", "email"),
    _read("email_folders", "GET", "/email/accounts/{account_id}/folders", "Pastas da caixa de correio com mensagens e não lidas.", "email",
          PTH("account_id")),
    _read("email_messages", "GET", "/email/accounts/{account_id}/messages", "Mensagens de uma pasta, mais recentes primeiro.", "email",
          PTH("account_id"), Q("folder", "str", "Pasta IMAP", "INBOX"), Q("limit", "int", "Mensagens", 40),
          Q("q", "str", "Assunto ou remetente"), Q("unread", "bool", "Apenas não lidas", False),
          Q("flagged", "bool", "Apenas destacadas", False)),
    _read("email_message", "GET", "/email/accounts/{account_id}/messages/{uid}", "Mensagem completa: texto, HTML, anexos e cabeçalhos.", "email",
          PTH("account_id"), PTH("uid"), Q("folder", "str", "Pasta IMAP", "INBOX")),
    _write("email_send", "POST", "/email/accounts/{account_id}/send", "Envia correio (to, cc, bcc, subject, body, anexos).", "email",
           PTH("account_id"), PAY()),
    # -- sentiment -------------------------------------------------------
    _read("sentiment_sources", "GET", "/sentiment/sources", "Fontes do sistema disponíveis para análise de sentimento.", "sentiment"),
    _read("sentiment_meta", "GET", "/sentiment/meta", "Motores de análise disponíveis e integrações.", "sentiment"),
    _write("sentiment_analyze_text", "POST", "/sentiment/analyze", "Analisa um texto livre (indicadores, frases, termos, relatório).", "sentiment", PAY()),
    _write("sentiment_analyze_corpus", "POST", "/sentiment/corpus", "Analisa um corpus de qualquer fonte do sistema.", "sentiment", PAY()),
    _write("sentiment_save_dossier", "POST", "/sentiment/save/dossier", "Anexa a análise ao dossiê (passa a constar do Office).", "sentiment", PAY()),
    _write("sentiment_save_office", "POST", "/sentiment/save/office", "Cria/atualiza um documento no Office com o relatório.", "sentiment", PAY()),
    # -- visualizador ----------------------------------------------------
    _read("visualizador_meta", "GET", "/visualizador/meta", "Catálogo de datasets, tipos de gráfico, operadores e limites.", "visualizador"),
    _read("visualizador_dataset", "GET", "/visualizador/datasets/{dataset_id}", "Dimensões, medidas, filtros e sugestões de um dataset.", "visualizador",
          PTH("dataset_id")),
    _read("visualizador_templates", "GET", "/visualizador/templates", "Dashboards-modelo prontos a usar.", "visualizador"),
    _read("visualizador_dashboards", "GET", "/visualizador/dashboards", "Dashboards do utilizador (admins veem os da equipa).", "visualizador"),
    _read("visualizador_dashboard", "GET", "/visualizador/dashboards/{dashboard_id}", "Definição de um dashboard.", "visualizador",
          PTH("dashboard_id")),
    _write("visualizador_query", "POST", "/visualizador/query", "Consulta analítica: dimensões × medidas (+ fórmulas), pronta a desenhar.", "visualizador", PAY()),
    _write("visualizador_records", "POST", "/visualizador/records", "Registos individuais (drill-through dos visuais).", "visualizador", PAY()),
    _write("visualizador_values", "POST", "/visualizador/values", "Valores distintos de uma dimensão (para seletores de filtros).", "visualizador", PAY()),
    _write("visualizador_save_dashboard", "POST", "/visualizador/dashboards", "Cria ou atualiza um dashboard do utilizador.", "visualizador", PAY()),
    # -- scraper ---------------------------------------------------------
    _read("scraper_meta", "GET", "/scraper/meta", "Metadados para construir o formulário de definições.", "scraper"),
    _read("scraper_status", "GET", "/scraper/status", "Diagnóstico: Scrapling/browsers, Elasticsearch e agendador.", "scraper"),
    _read("scraper_stats", "GET", "/scraper/stats", "Resumo do módulo: fontes, execuções e itens recolhidos/indeixados.", "scraper"),
    _read("scraper_sources", "GET", "/scraper/sources", "Fontes de recolha configuradas.", "scraper"),
    _read("scraper_source", "GET", "/scraper/sources/{source_id}", "Definição de uma fonte de recolha.", "scraper",
          PTH("source_id")),
    _read("scraper_runs", "GET", "/scraper/runs", "Execuções de recolha (mais recentes primeiro).", "scraper",
          Q("source_id", "str", "Fonte"), Q("limit", "int", "Resultados", 50)),
    _read("scraper_run_items", "GET", "/scraper/runs/{run_id}/items", "Itens recolhidos numa execução.", "scraper",
          PTH("run_id"), RQ("source_id", "str", "Fonte da execução"), Q("limit", "int", "Itens", 100),
          Q("offset", "int", "Offset", 0)),
    _read("scraper_search", "GET", "/scraper/search", "Pesquisa no corpus recolhido (título, resumo, texto e campos).", "scraper",
          Q("q", "str", "Texto livre"), Q("source_id", "str", "Fonte"), Q("size", "int", "Resultados", 20),
          Q("sort", "str", "recent | oldest | relevance", "recent")),
    _read("scraper_jobs", "GET", "/scraper/jobs", "Agendamentos (cron) ativos.", "scraper"),
    _write("scraper_create_source", "POST", "/scraper/sources", "Cria uma fonte de recolha.", "scraper", PAY()),
    _write("scraper_preview_source", "POST", "/scraper/preview", "Testa uma definição antes de guardar e devolve uma amostra.", "scraper", PAY()),
    _write("scraper_suggest", "POST", "/scraper/suggest", "Analisa uma página e propõe a definição (IA + heurística).", "scraper", PAY()),
    _write("scraper_run_source", "POST", "/scraper/sources/{source_id}/run", "Arranca uma recolha imediata em segundo plano.", "scraper",
           PTH("source_id")),
    # -- vectors ---------------------------------------------------------
    _read("vectors_status", "GET", "/elastic/vectors/status", "Estatísticas de embeddings por índice.", "vectors"),
    _read("vectors_jobs", "GET", "/elastic/vectors/index/jobs", "Tarefas de indexação de embeddings.", "vectors"),
    _write("vectors_search", "POST", "/elastic/vectors/search", "Pesquisa semântica/híbrida sobre contratos ou entidades.", "vectors", PAY()),
    _write("vectors_index", "POST", "/elastic/vectors/index", "Indexa embeddings nos documentos que ainda não os têm.", "vectors", PAY()),
    # -- skills ----------------------------------------------------------
    _read("skills_list", "GET", "/skills", "Biblioteca de skills (mais usadas primeiro).", "skills"),
    _read("skills_get", "GET", "/skills/{skill_id}", "Detalhe de uma skill.", "skills", PTH("skill_id")),
    _write("skills_match", "POST", "/skills/match", "Skill da biblioteca que serviria esta pergunta (sem criar nada).", "skills", PAY()),
    _write("skills_ensure", "POST", "/skills/ensure", "Escolhe a skill do pedido ou cria uma nova.", "skills", PAY()),
    _write("skills_save", "POST", "/skills", "Guarda uma skill na biblioteca.", "skills", PAY()),
    # -- providers / cli / proxy -----------------------------------------
    _read("providers_list", "GET", "/providers", "Catálogo de fornecedores de IA com o estado das chaves.", "providers"),
    _read("providers_chat_models", "GET", "/providers/chat-models", "Modelos utilizáveis, para o selector do chat.", "providers"),
    _write("providers_test", "POST", "/providers/test", "Testa um fornecedor com um pedido mínimo.", "providers", PAY()),
    _read("cli_commands", "GET", "/cli/commands", "Comandos disponíveis no terminal da interface.", "cli"),
    _write("cli_run", "POST", "/cli/run", "Executa um comando do CLI e devolve stdout/stderr.", "cli", PAY()),
    _read("proxy_status", "GET", "/proxy/status", "Limites e estado do proxy de páginas.", "proxy"),
    _read("proxy_get", "GET", "/proxy", "Lê uma página externa e devolve-a pronta a incorporar.", "proxy",
          RQ("url", "str", "Endereço http(s) a ler")),
    # -- dossier / import ------------------------------------------------
    _read("favorites_list", "GET", "/favorites", "Fichas favoritas (entidades e contratos).", "dossier"),
    _read("workspace_get", "GET", "/workspace", "Dossier: pastas de fichas e histórico de consultas.", "dossier"),
    _write("import_ingest", "POST", "/import/ingest", "Indexa linhas pré-visualizadas (contratos no ES; entidades em JSONL).", "import", PAY()),
)

# Índice por nome, para resolver as chamadas dos handlers.
BY_NAME: Dict[str, Operation] = {op.name: op for op in OPERATIONS}

# Grupos na ordem em que aparecem no catálogo.
TAGS: List[str] = list(dict.fromkeys(op.tag for op in OPERATIONS))
