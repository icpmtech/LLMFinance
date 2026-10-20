"""Permissões de leitura e escrita por papel da conta.

Regra de base: **um `member` só lê dados**. Criar e alterar conteúdo é de `admin`
e `manager` (`gestor de plataforma`). A definição vive num documento único do
índice `finance_settings` (`id = permissions`), tal como o «Menu lateral», para
sobreviver a reinícios e ficar auditada.

Três decisões que vale a pena explicar, porque não são óbvias:

* **Há POST que são leitura.** Pesquisas, exportações, análises e simulações
  recebem o pedido no corpo (`POST /contracts/search`). Bloquear por método
  partiria a leitura, que é justamente o que o `member` pode fazer. Esses
  caminhos estão em `READ_LIKE` e passam sempre.
* **Há escritas públicas.** Encomendas da loja, newsletter, formulário de
  contacto e webhooks não têm sessão — o comércio tem de funcionar para quem
  ainda não tem conta. O bloqueio só se aplica a pedidos **com sessão válida**;
  sem sessão, a própria rota decide.
* **Escrita pessoal é self-service.** Entrar e sair, gerir a própria sessão e
  palavra-passe, subscrever e pagar, favoritos, pastas e histórico são estado do
  próprio utilizador, não conteúdo da plataforma. Ficam fora do bloqueio, senão
  o `member` não conseguiria sequer trabalhar.

O módulo é o **primeiro segmento do caminho** (`/crm/...` → `crm`). É mecânico de
propósito: uma tabela curada à mão correria o risco de atribuir mal um prefixo e
aplicar a permissão errada a uma área inteira.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from api import auth_service as auth
from api.elasticsearch_client import SETTINGS_INDEX, ensure_indices, get_es_client

logger = logging.getLogger(__name__)

DOC_ID = "permissions"
DOC_KIND = "permissions"

ACTIONS: Tuple[str, ...] = ("read", "write")

# Papéis, do mais para o menos permissivo. `member` fecha a lista.
ROLES: Tuple[str, ...] = auth.USER_ROLES

# Métodos que alteram estado. Os de leitura (`GET`/`HEAD`/`OPTIONS`) nunca são
# restringidos por aqui.
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# POST/DELETE que não criam nem alteram conteúdo da plataforma: pesquisas com
# corpo, exportações, análises, simulações e geração de documentos para o
# utilizador. São leitura em tudo menos no verbo.
READ_LIKE = re.compile(
    r"/(search|pesquisa|export|exportar|analy[sz]e|analise|preview|report|relatorio|summary|resumo"
    r"|chat|explain|estimate|estimativa|simulate|simulacao|validate|validar|check|lookup|render|plot"
    r"|download|compare|comparar|aggregate|agregacao|stats|estatisticas|overview|list|meta|match"
    r"|forecast|previsao|previsoes|autocomplete|suggest|translate|historico|history|detail|ficha|query|filter|resolve)\b",
    re.IGNORECASE,
)

# Módulos em que qualquer conta autenticada pode escrever: é estado do próprio
# utilizador (sessão, subscrição, favoritos, pastas) ou conversa.
SELF_SERVICE: Tuple[str, ...] = ("auth", "billing", "chat", "favorites", "workspace", "search")

# Módulos reservados à administração da plataforma, mesmo para `manager`.
ADMIN_ONLY: Tuple[str, ...] = ("admin", "permissions")

# Áreas de rotas. O `id` é o primeiro segmento do caminho; `label` e `group` são
# só para a página de permissões. `content=False` marca `SELF_SERVICE`.
MODULES: Tuple[Dict[str, Any], ...] = (
    {"id": "auth", "label": "Contas e sessões", "group": "Plataforma", "content": False},
    {"id": "billing", "label": "Subscrições e pagamentos", "group": "Plataforma", "content": False},
    {"id": "admin", "label": "Administração", "group": "Plataforma", "content": True},
    {"id": "permissions", "label": "Permissões", "group": "Plataforma", "content": True},
    {"id": "chat", "label": "Chat IA", "group": "Plataforma", "content": False},
    {"id": "rag", "label": "RAG · documentos", "group": "Plataforma", "content": True},
    {"id": "favorites", "label": "Favoritos", "group": "Plataforma", "content": False},
    {"id": "workspace", "label": "Pastas e histórico", "group": "Plataforma", "content": False},
    {"id": "search", "label": "Pesquisa", "group": "Plataforma", "content": False},
    {"id": "translate", "label": "Tradução", "group": "Plataforma", "content": False},
    {"id": "contracts", "label": "Contratos públicos", "group": "Contratação", "content": True},
    {"id": "contracts-es", "label": "Contratos de Espanha", "group": "Contratação", "content": True},
    {"id": "contracts-fr", "label": "Contratos de França", "group": "Contratação", "content": True},
    {"id": "vortal", "label": "Vortal", "group": "Contratação", "content": True},
    {"id": "base-impic", "label": "Base IMPIC", "group": "Contratação", "content": True},
    {"id": "administracao-central", "label": "Administração Central", "group": "Contratação", "content": True},
    {"id": "companies", "label": "Empresas", "group": "Empresas e pessoas", "content": True},
    {"id": "entities", "label": "Entidades", "group": "Empresas e pessoas", "content": True},
    {"id": "empresas", "label": "Empresas IQ", "group": "Empresas e pessoas", "content": True},
    {"id": "empresas-recolha", "label": "Recolha de empresas", "group": "Empresas e pessoas", "content": True},
    {"id": "empresas-global", "label": "Empresas global", "group": "Empresas e pessoas", "content": True},
    {"id": "trademarks", "label": "Marcas", "group": "Empresas e pessoas", "content": True},
    {"id": "firmas", "label": "Firmas", "group": "Empresas e pessoas", "content": True},
    {"id": "gleif", "label": "GLEIF", "group": "Empresas e pessoas", "content": True},
    {"id": "people", "label": "Pessoas", "group": "Empresas e pessoas", "content": True},
    {"id": "contribuintes", "label": "Contribuintes", "group": "Empresas e pessoas", "content": True},
    {"id": "remuneracoes", "label": "Remunerações", "group": "Empresas e pessoas", "content": True},
    {"id": "remuneracoes-ap", "label": "Remunerações AP", "group": "Empresas e pessoas", "content": True},
    {"id": "municipios", "label": "Municípios", "group": "Empresas e pessoas", "content": True},
    {"id": "cire", "label": "CIRE", "group": "Empresas e pessoas", "content": True},
    {"id": "citacoes", "label": "Citações", "group": "Empresas e pessoas", "content": True},
    {"id": "devedores", "label": "Devedores", "group": "Empresas e pessoas", "content": True},
    {"id": "crm", "label": "CRM", "group": "CRM", "content": True},
    {"id": "agents", "label": "Agentes", "group": "CRM", "content": True},
    {"id": "cms", "label": "CMS", "group": "Conteúdos e loja", "content": True},
    {"id": "site", "label": "Site público", "group": "Conteúdos e loja", "content": True},
    {"id": "loja", "label": "Loja", "group": "Conteúdos e loja", "content": True},
    {"id": "shop", "label": "Loja (gestão)", "group": "Conteúdos e loja", "content": True},
    {"id": "news", "label": "Notícias", "group": "Conteúdos e loja", "content": True},
    {"id": "rss", "label": "RSS", "group": "Conteúdos e loja", "content": True},
    {"id": "email", "label": "Email", "group": "Conteúdos e loja", "content": True},
    {"id": "office", "label": "Office", "group": "Conteúdos e loja", "content": True},
    {"id": "reports", "label": "Relatórios", "group": "Conteúdos e loja", "content": True},
    {"id": "benchmark", "label": "Benchmark", "group": "Análise", "content": True},
    {"id": "benchmarks", "label": "Benchmarks de produtos", "group": "Análise", "content": True},
    {"id": "padroes", "label": "Padrões", "group": "Análise", "content": True},
    {"id": "risco", "label": "Risco", "group": "Análise", "content": True},
    {"id": "esg", "label": "ESG", "group": "Análise", "content": True},
    {"id": "lorenz", "label": "Lorenz", "group": "Análise", "content": True},
    {"id": "descoberta", "label": "Descoberta", "group": "Análise", "content": True},
    {"id": "osint", "label": "OSINT", "group": "Análise", "content": True},
    {"id": "search360", "label": "Pesquisa 360", "group": "Análise", "content": True},
    {"id": "visualizador", "label": "Visualizador", "group": "Análise", "content": True},
    {"id": "deep-search", "label": "Pesquisa profunda", "group": "Análise", "content": True},
    {"id": "researcher", "label": "Investigação", "group": "Análise", "content": True},
    {"id": "mirofish", "label": "MiroFish", "group": "Análise", "content": True},
    {"id": "hermes", "label": "Hermes", "group": "Análise", "content": True},
    {"id": "hermes-agent", "label": "Hermes Agent", "group": "Análise", "content": True},
    {"id": "skills", "label": "Competências", "group": "Análise", "content": True},
    {"id": "world", "label": "Mundo", "group": "Análise", "content": True},
    {"id": "mercado", "label": "Mercado", "group": "Mercados", "content": True},
    {"id": "tickers", "label": "Tickers", "group": "Mercados", "content": True},
    {"id": "elastic", "label": "Índices de mercado", "group": "Mercados", "content": True},
    {"id": "sentiment", "label": "Sentimento", "group": "Mercados", "content": True},
    {"id": "forecast", "label": "Previsões", "group": "Mercados", "content": True},
    {"id": "scraper", "label": "Recolha de sites", "group": "Recolha", "content": True},
    {"id": "social", "label": "Redes sociais", "group": "Recolha", "content": True},
    {"id": "societario", "label": "Societário", "group": "Recolha", "content": True},
    {"id": "import", "label": "Importação", "group": "Recolha", "content": True},
    {"id": "ontology", "label": "Ontologia", "group": "Recolha", "content": True},
    {"id": "subvencoes", "label": "Subvenções", "group": "Recolha", "content": True},
    {"id": "partidos", "label": "Partidos", "group": "Recolha", "content": True},
    {"id": "erc", "label": "ERC", "group": "Recolha", "content": True},
    {"id": "providers", "label": "Fornecedores de IA", "group": "Sistema", "content": True},
    {"id": "proxy", "label": "Proxy", "group": "Sistema", "content": True},
    {"id": "cli", "label": "Terminal", "group": "Sistema", "content": True},
    {"id": "jarvis", "label": "Jarvis", "group": "Sistema", "content": True},
)

MODULE_BY_ID: Dict[str, Dict[str, Any]] = {m["id"]: dict(m) for m in MODULES}
MODULE_IDS: Tuple[str, ...] = tuple(m["id"] for m in MODULES)

# Módulos com escrita que não estão no catálogo (prefixo novo, não previsto).
# São tratados como conteúdo: um `member` não escreve onde não conhecemos a regra.
FALLBACK_MODULE = "geral"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ------------------------------------------------------------------ defaults
def default_matrix() -> Dict[str, Dict[str, Dict[str, bool]]]:
    """Matriz por omissão: `admin` tudo, `manager` conteúdo, `member` só ler."""
    matriz: Dict[str, Dict[str, Dict[str, bool]]] = {}
    for role in ROLES:
        linha: Dict[str, Dict[str, bool]] = {}
        for module_id in MODULE_IDS:
            self_service = module_id in SELF_SERVICE or not MODULE_BY_ID[module_id].get("content", True)
            if role == auth.ROLE_ADMIN:
                escrever = True
            elif module_id in ADMIN_ONLY:
                escrever = False
            elif role == auth.ROLE_MANAGER:
                escrever = True
            else:  # member
                escrever = self_service
            linha[module_id] = {"read": True, "write": escrever}
        matriz[role] = linha
    return matriz


def _normalize(matriz: Any) -> Dict[str, Dict[str, Dict[str, bool]]]:
    """Une o que veio do índice com os defaults, descartando o que não existe."""
    base = default_matrix()
    if not isinstance(matriz, dict):
        return base
    for role, linha in matriz.items():
        if role not in base or not isinstance(linha, dict):
            continue
        for module_id, acoes in linha.items():
            if module_id not in base[role] or not isinstance(acoes, dict):
                continue
            for acao in ACTIONS:
                if acao in acoes:
                    base[role][module_id][acao] = bool(acoes[acao])
    # A administração da plataforma é sempre exclusiva do `admin`: mesmo que
    # alguém grave o contrário no índice, o `manager` não a recebe.
    for role in ROLES:
        for module_id in ADMIN_ONLY:
            if module_id in base[role]:
                base[role][module_id]["write"] = role == auth.ROLE_ADMIN
    return base


# -------------------------------------------------------------- ler / gravar
def _client() -> Optional[Any]:
    client = get_es_client()
    if not client:
        return None
    try:
        ensure_indices(client)
    except Exception as exc:  # pragma: no cover - depende do Elasticsearch
        logger.debug("Permissions: índices indisponíveis: %s", exc)
    return client


def _read() -> Dict[str, Any]:
    client = _client()
    if not client:
        return {}
    try:
        documento = client.get(index=SETTINGS_INDEX, id=DOC_ID)
    except Exception:
        return {}
    return dict(documento.get("_source") or {})


def matrix() -> Dict[str, Dict[str, Dict[str, bool]]]:
    """Matriz efetiva (defaults + o que estiver gravado no índice)."""
    return _normalize(_read().get("matrix"))


def state() -> Dict[str, Any]:
    """Catálogo e matriz, para a página de permissões."""
    documento = _read()
    matriz = _normalize(documento.get("matrix"))
    return {
        "index": SETTINGS_INDEX,
        "doc_id": DOC_ID,
        "roles": [
            {"id": role, "label": auth.ROLE_LABELS.get(role, role), "is_admin": role == auth.ROLE_ADMIN}
            for role in ROLES
        ],
        "modules": [
            {
                "id": module["id"],
                "label": module["label"],
                "group": module["group"],
                "content": bool(module.get("content", True)),
                "self_service": module["id"] in SELF_SERVICE,
                "admin_only": module["id"] in ADMIN_ONLY,
            }
            for module in MODULES
        ],
        "matrix": matriz,
        "protected": list(SELF_SERVICE),
        "admin_only": list(ADMIN_ONLY),
        "read_like_note": (
            "As pesquisas, exportações e análises usam POST mas são leitura, por isso nunca são "
            "bloqueadas. Escritas públicas (loja, contacto, webhooks) não têm sessão e também passam."
        ),
        "atualizado_em": documento.get("updated_at"),
        "atualizado_por": documento.get("updated_by"),
    }


def save(matriz: Dict[str, Any], *, utilizador: str = "") -> Dict[str, Any]:
    """Grava a matriz. Os módulos de administração ficam sempre reservados ao `admin`."""
    if not isinstance(matriz, dict):
        raise ValueError("A matriz tem de ser um objeto com um papel por chave.")
    desconhecidos = [role for role in matriz if role not in ROLES]
    if desconhecidos:
        raise ValueError(f"Papel desconhecido: {', '.join(sorted(desconhecidos))}.")

    efetiva = _normalize(matriz)
    documento = {
        "kind": DOC_KIND,
        "matrix": efetiva,
        "updated_at": _now(),
        "updated_by": utilizador,
    }
    client = _client()
    if not client:
        raise ValueError("Sem ligação ao Elasticsearch: não foi possível gravar as permissões.")
    client.index(index=SETTINGS_INDEX, id=DOC_ID, document=documento, refresh=True)

    alterados = [
        f"{role}.{module}.{acao}"
        for role in ROLES
        for module in MODULE_IDS
        for acao in ACTIONS
        if matriz.get(role, {}).get(module, {}).get(acao) != efetiva[role][module][acao]
    ]
    return {"ok": True, "matrix": efetiva, "ignorados": alterados, "updated_at": documento["updated_at"]}


# ------------------------------------------------------------------- decisão
def module_for_path(path: str) -> str:
    """Módulo de um caminho: o primeiro segmento, ou `geral` se for desconhecido."""
    partes = [p for p in (path or "").split("/") if p]
    if not partes:
        return FALLBACK_MODULE
    primeiro = partes[0].lower()
    return primeiro if primeiro in MODULE_BY_ID else FALLBACK_MODULE


def is_write_operation(method: str, path: str) -> bool:
    """`True` quando o pedido cria ou altera conteúdo (e não apenas lê)."""
    if (method or "").upper() not in WRITE_METHODS:
        return False
    if READ_LIKE.search(path or ""):
        return False
    return True


def can(user: Optional[Dict[str, Any]], module_id: str, action: str = "write") -> bool:
    """Permissão de um utilizador num módulo, com a matriz por omissão como rede.

    Módulos fora do catálogo (`geral`) negam a escrita a quem não é `admin` ou
    `manager` — é preferível bloquear a deixar passar uma área que não
    classificámos.
    """
    if not user:
        return False
    role = str(user.get("role") or auth.ROLE_MEMBER)
    if role not in ROLES:
        role = auth.ROLE_MEMBER
    if action not in ACTIONS:
        raise ValueError(f"Ação desconhecida: {action}")
    if action == "read":
        # Ler é sempre permitido; o que limita a leitura é o plano (billing) e o
        # «Menu lateral», não esta matriz.
        return True
    if role == auth.ROLE_ADMIN:
        return True
    if module_id in ADMIN_ONLY:
        return False
    if module_id not in MODULE_BY_ID:
        return role == auth.ROLE_MANAGER
    return bool(matrix()[role][module_id]["write"])


def effective_for_user(user: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Resumo para o frontend: o que este utilizador pode escrever."""
    role = str((user or {}).get("role") or auth.ROLE_MEMBER)
    if role not in ROLES:
        role = auth.ROLE_MEMBER
    matriz = matrix()
    writable = [module for module in MODULE_IDS if matriz[role][module]["write"] and module not in ADMIN_ONLY]
    return {
        "role": role,
        "role_label": auth.ROLE_LABELS.get(role, role),
        "can_write_all": role in (auth.ROLE_ADMIN, auth.ROLE_MANAGER),
        "read_only": role == auth.ROLE_MEMBER,
        "writable_modules": writable,
        "self_service": list(SELF_SERVICE),
    }


def all_module_prefixes() -> Dict[str, str]:
    """Mapa prefixo → módulo, para documentação e testes."""
    return {module["id"]: "/" + module["id"] for module in MODULES}
