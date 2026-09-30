"""Ações do **Jarvis** — o que ele pode fazer *por nós* dentro da aplicação.

O Jarvis não se limita a responder: interpreta o pedido e propõe **ações**. Há
dois tipos, e a diferença importa:

- **`navigate`** — leva o utilizador a um sítio da plataforma (com ou sem termo
  de pesquisa). Não altera nada: por isso é seguro e executa-se com um clique.
- **`create`** — cria um artefacto em nome do utilizador (documento no Office,
  dossiê 360, skill na biblioteca). Escreve, por isso **exige confirmação
  explícita** e nunca acontece sozinho — mesmo que o pedido venha por voz.

Nada é executado no servidor durante a resposta: o Jarvis **propõe** e devolve
`actions` junto da resposta; quem executa é a interface (a navegação, no
cliente) ou a rota `/jarvis/actions/run` (as criações, via gateway MCP, com o
token do utilizador).

A deteção é determinística (verbos + substantivos da plataforma), para não
depender de um modelo — e o modelo, quando existe, pode acrescentar propostas
ao plano.

Rotas em `api/jarvis_routes.py` (`GET /jarvis/actions`, `POST /jarvis/actions/run`).
"""
from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

MAX_ACTIONS = 3


# ---------------------------------------------------------------------------
# Destinos da aplicação (navegação)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Destination:
    """Um sítio da plataforma onde o Jarvis pode levar o utilizador."""

    id: str
    label: str
    description: str
    view: str
    path: str
    keywords: Tuple[str, ...]
    #: Vista que aceita um termo de pesquisa inicial (`initialQuery`).
    accepts_query: bool = False

    def public(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "kind": "navigate",
            "label": self.label,
            "description": self.description,
            "view": self.view,
            "path": self.path,
            "accepts_query": self.accepts_query,
            "requires_confirmation": False,
        }


DESTINATIONS: Tuple[Destination, ...] = (
    Destination("contratos", "Abrir contratos públicos", "Pesquisa de contratos do Portal BASE.",
                "contracts-search", "/contracts/search",
                ("contrato", "contratos", "base", "adjudicacao", "adjudicacao publica")),
    Destination("contratos_dashboard", "Abrir dashboard de contratos", "Indicadores agregados da contratação pública.",
                "contracts-dashboard", "/contracts/dashboard",
                ("dashboard de contratos", "estatisticas de contratos", "indicadores de contratos")),
    Destination("contratos_mapa", "Abrir mapa de contratos", "Distribuição geográfica da contratação.",
                "contracts-map", "/contracts/map",
                ("mapa", "mapa de contratos", "geografia")),
    Destination("empresas", "Abrir pesquisa de entidades", "Diretório de entidades adjudicantes e adjudicatárias.",
                "entities-search", "/entities/search",
                ("entidade", "entidades", "adjudicante", "adjudicatario")),
    Destination("empresas_iq", "Abrir EmpresasIQ", "Inteligência contratual por empresa.",
                "empresas-iq", "/empresas-iq",
                ("empresasiq", "ficha de empresa", "perfil da empresa")),
    Destination("pessoas", "Abrir PessoasIQ", "Pessoas, cargos e relações societárias.",
                "pessoas-iq", "/pessoas-iq",
                ("pessoa", "pessoas", "gerente", "cargos", "socios")),
    Destination("empresas_global", "Abrir Empresas Global", "Entidades de todo o sistema (Portugal, Espanha e CRM).",
                "companies-global", "/empresas-global",
                ("empresas global", "todas as empresas", "directorio global")),
    Destination("risco", "Abrir Empresas & Risco", "Nível de risco, comparação e grafos 360.",
                "risco", "/empresas-risco",
                ("risco", "rating", "comparar empresas")),
    Destination("insolvencias", "Abrir insolvências (CIRE)", "Processos de insolvência publicados.",
                "cire", "/cire",
                ("insolvencia", "insolvencias", "cire", "processos de insolvencia")),
    Destination("citacoes", "Abrir citações e editais", "Publicações em citações e editais.",
                "citacoes", "/citacoes",
                ("citacao", "citacoes", "edital", "editais")),
    Destination("contribuintes", "Abrir contribuintes", "Dívidas e papéis dos contribuintes.",
                "contribuintes", "/contribuintes",
                ("contribuinte", "contribuintes", "dividas", "financas")),
    Destination("gleif", "Abrir registos LEI (GLEIF)", "Identificadores LEI e hierarquias de entidades.",
                "gleif", "/gleif",
                ("lei", "gleif", "identificador lei")),
    Destination("mercados", "Abrir mercados", "Cotações, gráficos e detalhe de tickers.",
                "tickers", "/tickers",
                ("cotacao", "cotacoes", "acao", "acoes", "mercado", "mercados", "bolsa", "ticker", "tickers")),
    Destination("previsao", "Abrir previsões", "Previsões de séries com ARIMA e Kronos.",
                "forecast", "/forecast",
                ("previsao", "previsoes", "forecast", "arima")),
    Destination("documentos", "Abrir documentos (RAG)", "Documentos indexados e chat sobre eles.",
                "rag", "/rag",
                ("documento", "documentos", "rag", "pdf", "relatorio guardado")),
    Destination("pesquisa360", "Abrir Pesquisa 360", "Dossiê federado por tema, com biblioteca e grafo.",
                "search360", "/search360",
                ("pesquisa 360", "pesquisa360", "dossie 360", "dossies")),
    Destination("hermes", "Abrir Hermes", "Investigação citada com evidências.",
                "hermes", "/hermes",
                ("hermes",)),
    Destination("investigador", "Abrir Investigador", "Investigação autónoma com relatório e audit trail.",
                "researcher", "/researcher",
                ("investigador", "researcher")),
    Destination("ontologia", "Abrir Ontologia", "Objetos canónicos, ligações e IA semântica.",
                "ontology", "/ontology",
                ("ontologia", "objetos", "ligacoes semanticas")),
    Destination("bi", "Abrir Visualizador", "Analisar dados, criar métricas e dashboards.",
                "visualizador", "/visualizador",
                ("visualizador", "dashboard", "bi", "metricas", "relatorios bi")),
    Destination("sentimento", "Abrir Sentimento", "Análise de sentimento da recolha e das notícias.",
                "sentimento", "/sentimento",
                ("sentimento", "opiniao", "analise de sentimento")),
    Destination("office", "Abrir Office", "Documentos Markdown: notas, relatórios e dossiês.",
                "office", "/office",
                ("office", "documentos de trabalho", "notas", "relatorio")),
    Destination("email", "Abrir Email", "Contas e mensagens de correio.",
                "email", "/email",
                ("email", "correio", "mensagens", "caixa de entrada")),
    Destination("rss", "Abrir leitor RSS", "Feeds de notícias, guardados e digest.",
                "rss", "/rss",
                ("rss", "feeds", "noticias", "leitor de noticias")),
    Destination("crm", "Abrir CRM", "Contas, contactos, oportunidades e agenda.",
                "crm-accounts", "/crm/accounts",
                ("crm", "clientes", "conta de cliente", "contactos", "oportunidades")),
    Destination("recolha", "Abrir recolha de dados", "Recolha de sites, templates e execuções.",
                "scraper", "/scraper",
                ("recolha", "scraper", "scraping", "extracao")),
    Destination("social", "Abrir redes sociais", "Canais, execuções e agenda da pesquisa social.",
                "social", "/social",
                ("redes sociais", "social", "canais sociais")),
    Destination("loja", "Abrir loja", "Catálogo, encomendas e clientes da loja.",
                "shop", "/shop",
                ("loja", "shop", "encomendas", "catalogo")),
    Destination("browser", "Abrir browser", "Navegar e ler páginas dentro da plataforma.",
                "browser", "/browser",
                ("browser", "navegador")),
    Destination("world", "Abrir World Model", "Estado do mundo e rede neuronal dinâmica.",
                "world", "/world",
                ("world model", "estado do mundo", "rede neuronal")),
    Destination("simulador", "Abrir Simulador IQ OS", "Simulações por enxame de agentes.",
                "simulador", "/simulador",
                ("simulador", "simulacao", "mirofish")),
    Destination("padroes", "Abrir padrões", "Padrões e cargos extraídos.",
                "padroes", "/padroes",
                ("padroes", "cargos extraidos")),
    Destination("elastic", "Abrir Elasticsearch", "Índices, mapeamentos e estado do motor.",
                "elastic", "/elastic",
                ("elasticsearch", "indices", "elastic")),
    Destination("pesquisa_total", "Abrir Pesquisa total", "Pesquisa unificada em todo o sistema.",
                "pesquisa", "/pesquisa",
                ("pesquisa total", "pesquisar em tudo", "pesquisa unificada", "procurar em tudo"),
                accepts_query=True),
    Destination("pesquisa_global", "Abrir Pesquisa Global", "Pesquisa global ao estilo motor de busca.",
                "search", "/search",
                ("pesquisa global", "motor de busca", "procurar"),
                accepts_query=True),
    Destination("definicoes", "Abrir Definições", "Conta, fornecedores de IA, preferências.",
                "settings", "/settings",
                ("definicoes", "configuracao", "configuracoes", "fornecedores de ia")),
    Destination("administracao", "Abrir Administração", "Painel de administração da plataforma.",
                "admin", "/admin",
                ("administracao", "admin", "painel de administracao")),
)

DESTINATIONS_BY_ID = {item.id: item for item in DESTINATIONS}

#: Verbos que indicam «leva-me lá».
_NAVIGATE_VERBS = (
    "abre", "abrir", "mostra", "mostrar", "vai", "ir para", "navega", "navegar", "leva-me",
    "levar", "quero ver", "passa para", "entra", "entrar em", "vamos a", "ecra", "pagina",
)


# ---------------------------------------------------------------------------
# Criações (escrevem — exigem confirmação)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Creation:
    """Um artefacto que o Jarvis pode criar em nome do utilizador."""

    id: str
    label: str
    description: str
    operation: str
    keywords: Tuple[str, ...]
    #: Constrói o corpo da operação a partir da pergunta e da resposta.
    build: Callable[[str, str], Dict[str, Any]] = field(repr=False, default=lambda q, a: {})

    def public(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "kind": "create",
            "label": self.label,
            "description": self.description,
            "operation": self.operation,
            "keywords": list(self.keywords),
            "requires_confirmation": True,
        }


def _title_from(question: str) -> str:
    """Título curto e legível a partir do pedido (sem as muletas do pedido)."""
    clean = re.sub(r"\s+", " ", str(question or "")).strip()
    clean = re.sub(r"^(por favor,?\s*)?(guarda|grava|salva|arquiva|cria|exporta|adiciona)\s*", "", clean, flags=re.I)
    # Muletas que não dizem nada num título («… isto no office», «… como skill»).
    clean = re.sub(r"\b(isto|isso|esta resposta|este metodo|este resultado)\b", "", clean, flags=re.I)
    clean = re.sub(r"\b(no|para o|para a)\s+office\b", "", clean, flags=re.I)
    clean = re.sub(r"\bcomo\s+skill\b", "", clean, flags=re.I)
    clean = re.sub(r"\b(num|um)\s+dossi[êe](\s+360)?\b", "", clean, flags=re.I)
    return re.sub(r"\s{2,}", " ", clean).strip(" .,:;,-")[:120]


def _stamp() -> str:
    from datetime import datetime

    return datetime.now().strftime("%d/%m/%Y %H:%M")


def _task_title(question: str) -> str:
    """Título do artefacto: o pedido limpo ou, sem ele, a data."""
    return _title_from(question) or f"Jarvis — {_stamp()}"


def _office_body(question: str, answer: str) -> Dict[str, Any]:
    title = _task_title(question)
    markdown = (
        f"# {title}\n\n"
        f"> Resposta do Jarvis, {_stamp()}.\n\n"
        f"{str(answer or '').strip()}\n"
    )
    return {
        "title": title,
        "markdown": markdown,
        "kind": "note",
        "tags": ["jarvis"],
    }


def _dossier_body(question: str, answer: str) -> Dict[str, Any]:
    from api.jarvis_gateway import search_terms

    # O tema não deve incluir o verbo do pedido («grava um dossiê sobre energia»).
    term = search_terms(_title_from(question), limit=6)
    return {"term": term, "notes": str(answer or "")[:4000]}


def _skill_body(question: str, answer: str) -> Dict[str, Any]:
    description = re.sub(r"\s+", " ", str(answer or "")).strip()
    return {
        "name": _task_title(question),
        "question": str(question or ""),
        "summary": description[:400],
    }


CREATIONS: Tuple[Creation, ...] = (
    Creation(
        "guardar_office",
        "Guardar no Office",
        "Cria um documento Markdown no Office com esta resposta.",
        "office_save_document",
        ("office", "documento", "guardar", "gravar", "salvar", "exportar", "nota", "relatorio", "arquivar"),
        _office_body,
    ),
    Creation(
        "guardar_dossie",
        "Guardar dossiê 360",
        "Constrói e guarda um dossiê 360 do tema desta investigação.",
        "search360_save_dossier",
        ("dossie", "dossier", "360", "guardar dossie", "arquivar tema"),
        _dossier_body,
    ),
    Creation(
        "guardar_skill",
        "Guardar como skill",
        "Guarda este método na biblioteca de skills dos assistentes.",
        "skills_save",
        ("skill", "metodo", "procedimento", "receita", "passos"),
        _skill_body,
    ),
)

CREATIONS_BY_ID = {item.id: item for item in CREATIONS}

#: Verbos que indicam «cria/guarda isto».
_CREATE_VERBS = (
    "guarda", "guardar", "grava", "gravar", "salva", "salvar", "arquiva", "arquivar",
    "cria", "criar", "exporta", "exportar", "poe", "poem", "adiciona", "registar",
)


# ---------------------------------------------------------------------------
# Deteção
# ---------------------------------------------------------------------------
def _fold(value: Any) -> str:
    text = unicodedata.normalize("NFD", str(value or ""))
    return "".join(char for char in text if unicodedata.category(char) != "Mn").lower()


def _has_word(text: str, word: str) -> bool:
    return re.search(rf"\b{re.escape(word)}\b", text) is not None


def detect_destinations(question: str, *, limit: int = 2) -> List[Destination]:
    """Destinos pedidos na pergunta (verbos de navegação + palavras do destino).

    Uma **pergunta** sobre contratos («quais são os maiores contratos?») não é um
    pedido para abrir a página de contratos. Só há navegação quando o utilizador
    pede para ir a algum lado, ou quando diz apenas o nome do sítio («contratos»,
    «insolvências») — daí a exigência do verbo ou de uma frase muito curta.
    """
    folded = _fold(question)
    words = [word for word in folded.split() if word]
    wants_move = any(_fold(verb) in folded for verb in _NAVIGATE_VERBS)
    if not wants_move and len(words) > 3:
        return []

    scored: List[Tuple[int, Destination]] = []
    for destination in DESTINATIONS:
        score = 0
        for keyword in destination.keywords:
            key = _fold(keyword)
            if not key:
                continue
            # Palavras inteiras para termos curtos (evita «lei» dentro de «leitura»).
            if " " in key:
                if key in folded:
                    score += 3
            elif len(key) <= 4:
                if _has_word(folded, key):
                    score += 3
            elif key in folded:
                score += 3
        if score:
            if wants_move:
                score += 2
            scored.append((score, destination))

    scored.sort(key=lambda item: (-item[0], item[1].id))
    chosen = [destination for score, destination in scored if score >= 2][:limit]
    if not chosen and wants_move:
        # «abre a pesquisa» sem destino explícito → pesquisa total.
        chosen = [DESTINATIONS_BY_ID["pesquisa_total"]]
    return chosen


def detect_creations(question: str, answer: str, *, limit: int = 2) -> List[Creation]:
    """Criações pedidas na pergunta (verbo de criação + substantivo do artefacto)."""
    folded = _fold(question)
    wants_create = any(_fold(verb) in folded for verb in _CREATE_VERBS)
    if not wants_create or not str(answer or "").strip():
        return []

    chosen: List[Creation] = []
    for creation in CREATIONS:
        if any(_fold(keyword) in folded for keyword in creation.keywords):
            chosen.append(creation)
    if not chosen:
        # Verbo de criação sem artefacto dito: o documento é o que faz sentido.
        chosen = [CREATIONS_BY_ID["guardar_office"]]
    return chosen[:limit]


def propose(
    question: str,
    answer: str = "",
    *,
    tools_used: Sequence[str] = (),
    extra: Optional[Sequence[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Ações a propor ao utilizador (navegação primeiro, criações depois).

    `extra` são propostas vindas do modelo (validadas contra o catálogo).
    """
    actions: List[Dict[str, Any]] = []

    def _add(item: Dict[str, Any]) -> None:
        if len(actions) >= MAX_ACTIONS:
            return
        if any(existing["id"] == item["id"] for existing in actions):
            return
        actions.append(item)

    # 1. O que o modelo propôs (se propôs algo válido).
    for candidate in extra or []:
        if not isinstance(candidate, dict):
            continue
        action_id = str(candidate.get("action") or candidate.get("id") or "").strip()
        if action_id in DESTINATIONS_BY_ID:
            _add(render(action_id, question, answer, candidate.get("params")))
        elif action_id in CREATIONS_BY_ID:
            _add(render(action_id, question, answer, candidate.get("params")))

    # 2. Criações detetadas na pergunta. Quando o utilizador pede para **guardar**
    #    algo, não se propõe ir a um sítio: o que ele quer é o artefacto.
    creations = detect_creations(question, answer)
    for creation in creations:
        _add(render(creation.id, question, answer))

    # 3. Só se não houver nada para criar é que a navegação interessa.
    if not creations:
        for destination in detect_destinations(question):
            _add(render(destination.id, question, answer))

    return actions


#: Campos que o utilizador (ou o modelo) pode acrescentar/ajustar no corpo de
#: uma criação, além dos que o construtor já produz.
_EXTRA_BODY_KEYS = frozenset(
    {"title", "markdown", "kind", "tags", "folder_id", "template", "term", "notes", "name", "summary", "question", "project_id"}
)


def _merge_params(body: Dict[str, Any], params: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Junta os ajustes ao corpo, aceitando também campos que o construtor não traz.

    Sem isto, escolher a pasta de destino no Office (um campo que o construtor de
    documento não produz) era silenciosamente ignorado.
    """
    for key, value in (params or {}).items():
        if key in _EXTRA_BODY_KEYS and value not in (None, ""):
            body[key] = value
    return body


def render(
    action_id: str,
    question: str,
    answer: str = "",
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Constrói a ação pronta a executar, com o corpo já resolvido."""
    if action_id in DESTINATIONS_BY_ID:
        destination = DESTINATIONS_BY_ID[action_id]
        payload = dict(destination.public())
        query = str((params or {}).get("query") or (params or {}).get("term") or "").strip()
        if destination.accepts_query and query:
            payload["query"] = query
        else:
            payload["query"] = None
        return payload

    creation = CREATIONS_BY_ID[action_id]
    payload = {**creation.public(), "operation": creation.operation}
    payload["params"] = _merge_params(creation.build(question, answer), params)
    return payload


def catalogue() -> Dict[str, Any]:
    """Catálogo completo (para a UI e para o planeador)."""
    return {
        "destinations": [item.public() for item in DESTINATIONS],
        "creations": [item.public() for item in CREATIONS],
    }


def planner_catalogue(limit: int = 40) -> List[Dict[str, str]]:
    """Lista curta para o prompt do planeador."""
    items: List[Any] = [*DESTINATIONS[:limit], *CREATIONS]
    return [
        {
            "action": item.id,
            "kind": "navigate" if item.id in DESTINATIONS_BY_ID else "create",
            "description": item.description,
        }
        for item in items
    ]


# ---------------------------------------------------------------------------
# Execução (só criações; a navegação é do cliente)
# ---------------------------------------------------------------------------
def _mcp_params(operation_name: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """Adapta o corpo da criação ao envelope que o `mcp.call` espera.

    O catálogo MCP declara o corpo JSON como um parâmetro com nome próprio
    (`payload`). Passar o corpo «solto» fazia com que ele fosse parar ao *query
    string* e o endpoint respondesse 422 por falta de corpo — por isso a
    tradução é feita aqui, a partir do catálogo, e não à mão.
    """
    try:
        from mcp_server import catalog as mcp_catalog  # noqa: PLC0415
    except Exception:  # pragma: no cover - ambiente sem o pacote mcp
        return {"payload": body}

    operation = next((op for op in mcp_catalog.OPERATIONS if op.name == operation_name), None)
    if operation is None:  # pragma: no cover - catálogo sem a operação
        return {"payload": body}

    params: Dict[str, Any] = {}
    rest = dict(body)
    for param in operation.params:
        if param.location == "path" and param.name in rest:
            params[param.name] = rest.pop(param.name)
    body_param = operation.body_param
    if body_param is not None:
        params[body_param.name] = rest
    else:
        params.update(rest)
    return params


async def run(
    action_id: str,
    *,
    question: str = "",
    answer: str = "",
    params: Optional[Dict[str, Any]] = None,
    ctx: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Executa uma criação via gateway MCP, em nome do utilizador.

    Devolve `{ok, action, operation, result}` ou `{ok: False, error}`.
    """
    from api import jarvis_gateway

    if action_id not in CREATIONS_BY_ID:
        raise ValueError(
            f"A ação «{action_id}» não é executável no servidor. "
            f"Executáveis: {', '.join(sorted(CREATIONS_BY_ID))}."
        )
    creation = CREATIONS_BY_ID[action_id]
    body = _merge_params(creation.build(question, answer), params)
    if not str(answer or "").strip() and not params:
        raise ValueError("Não há nada para criar: a resposta está vazia.")

    result = await jarvis_gateway.invoke(
        # Via `mcp.call` de propósito: as operações que escrevem **não** estão no
        # catálogo curado de ferramentas, para o modelo nunca as poder escolher
        # sozinho. Só chegam aqui depois de o utilizador confirmar a ação.
        "mcp.call",
        {"operation": creation.operation, "params": _mcp_params(creation.operation, body)},
        ctx=ctx or {},
    )
    return {
        "ok": bool(result.get("ok")),
        "action": action_id,
        "label": creation.label,
        "operation": creation.operation,
        "result": result.get("data"),
        "error": result.get("error"),
    }


__all__ = [
    "CREATIONS",
    "CREATIONS_BY_ID",
    "DESTINATIONS",
    "DESTINATIONS_BY_ID",
    "Destination",
    "Creation",
    "catalogue",
    "detect_creations",
    "detect_destinations",
    "planner_catalogue",
    "propose",
    "render",
    "run",
]
