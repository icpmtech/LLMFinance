"""Rotas da arquitetura de CRM (`/crm/suite`, `/crm/mod/*`, `/crm/rbac/*`, `/crm/ai/*`).

Uma só família de rotas serve os 24 módulos definidos em `api.crm_registry`:
o módulo é um parâmetro do caminho e o motor (`api.crm_suite`) aplica o perfil do
utilizador (módulos, ações e âmbito de visibilidade).

- `GET    /crm/suite`                        — arquitetura completa (grupos, módulos, campos, permissões)
- `GET    /crm/suite/overview`                — painel geral do CRM
- `GET    /crm/me`                           — o perfil de CRM do utilizador
- `GET    /crm/rbac`                         — matriz de áreas, departamentos, perfis e módulos
- `POST   /crm/rbac/sync`                    — cria as atribuições em falta para os utilizadores existentes
- `PATCH  /crm/mod/users/{user_id}`          — atribuir perfil/área/departamento/equipa
- `GET    /crm/mod/{módulo}`                 — listar/pesquisar
- `POST   /crm/mod/{módulo}`                 — criar
- `GET    /crm/mod/{módulo}/stats`           — indicadores do módulo
- `GET    /crm/mod/{módulo}/references`      — mapa id→etiqueta dos campos de referência
- `GET    /crm/mod/{módulo}/{id}`            — obter
- `PATCH  /crm/mod/{módulo}/{id}`            — alterar (parcial)
- `DELETE /crm/mod/{módulo}/{id}`            — eliminar (com cascata quando aplicável)
- `POST   /crm/ai/insights/generate`         — gerar perceções de IA a partir dos dados reais
- `POST   /crm/ai/ask`                       — perguntar ao assistente de CRM
- `GET    /crm/analytics`                    — painel de analytics (vendas, clientes, operações, compras)
- `GET    /crm/analytics/datasets`           — catálogo dos conjuntos de dados analíticos
- `GET    /crm/analytics/datasets/{id}`      — linhas de um conjunto de dados (base dos gráficos)
- `POST   /crm/analytics/cross-sell`         — público de cross-sell/upsell
- `POST   /crm/analytics/opportunities`      — criar oportunidades para esse público

Este router é registado **antes** do router do CRM comercial (`api.crm_routes`),
para que os caminhos genéricos não colidam com `/crm/{tipo}/{id}`.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from api import crm_analytics as analytics
from api import crm_datasets as datasets_engine
from api import crm_registry as registry
from api import crm_suite as suite
from api.auth_routes import CurrentSession, require_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/crm", tags=["crm-suite"])


# --------------------------------------------------------------- dependências
@dataclass
class CrmContext:
    """Utilizador autenticado + atribuição de CRM + permissões resolvidas."""

    session: CurrentSession
    assignment: Dict[str, Any]
    perm: Dict[str, Any]

    def can(self, slug: str, action: str) -> bool:
        return suite.can(self.perm, slug, action)

    def module(self, slug: str, action: str = "read") -> registry.Module:
        module = registry.resolve_module(slug)
        if module is None:
            raise HTTPException(status_code=404, detail=f"Módulo de CRM desconhecido: {slug}")
        if not self.can(module.slug, action):
            raise HTTPException(
                status_code=403,
                detail=f"O perfil «{self.perm.get('role_label')}» não permite {action} em «{module.label}»",
            )
        return module

    def audit_context(self, request: Request) -> Dict[str, str]:
        client = request.client.host if request.client else ""
        forwarded = request.headers.get("x-forwarded-for", "")
        return {
            "ip": (forwarded.split(",")[0].strip() if forwarded else client) or "",
            "user_agent": request.headers.get("user-agent", ""),
        }


def crm_context(session: Annotated[CurrentSession, Depends(require_session)]) -> CrmContext:
    assignment = suite.get_assignment(session.user)
    perm = suite.permissions(assignment, auth_role=str(getattr(session.user, "role", "") or ""))
    return CrmContext(session=session, assignment=assignment, perm=perm)


Context = Annotated[CrmContext, Depends(crm_context)]


def _require_manage(ctx: CrmContext) -> None:
    if not (ctx.perm.get("is_admin") or "manage" in (ctx.perm.get("actions") or [])):
        raise HTTPException(
            status_code=403,
            detail="Esta operação exige o perfil de administração do CRM (ação «manage»)",
        )


def _fail(result: Dict[str, Any], status: int = 400) -> None:
    detail = result.get("error") or "Operação do CRM falhou"
    if detail == "Registo não encontrado":
        raise HTTPException(status_code=404, detail=detail)
    if detail.startswith("Sem permissão"):
        raise HTTPException(status_code=403, detail=detail)
    raise HTTPException(status_code=status, detail=detail)


def _int_or_none(value: Any) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------------ arquitetura
@router.get("/suite")
def crm_suite_meta(ctx: Context):
    """Arquitetura completa do CRM, filtrada pelo perfil do utilizador."""
    return suite.suite_meta(ctx.perm)


@router.get("/suite/overview")
def crm_suite_overview(ctx: Context):
    """Painel geral: volume por módulo, pipeline, apoio, campanhas e auditoria."""
    result = suite.overview(ctx.perm)
    if result.get("error"):
        _fail(result, status=502)
    return result


@router.get("/me")
def crm_me(ctx: Context):
    """Perfil de CRM do utilizador: perfil, área, departamento, equipa e permissões."""
    return {
        "assignment": ctx.assignment,
        "permissions": ctx.perm,
        "modules": suite.visible_modules(ctx.perm),
    }


@router.get("/rbac")
def crm_rbac(ctx: Context):
    """Matriz completa de acesso: áreas, departamentos, perfis, módulos e ações."""
    _require_manage(ctx)
    roles = [role.to_public() for role in registry.ROLES]
    role_index = {role["key"]: role for role in roles}
    members = (
        suite.list_module(registry.MODULE_BY_SLUG["users"], ctx.perm, size=500)
        if ctx.can("users", "read")
        else {"items": [], "total": 0}
    )
    teams = (
        suite.list_module(registry.MODULE_BY_SLUG["teams"], ctx.perm, size=200)
        if ctx.can("teams", "read")
        else {"items": [], "total": 0}
    )

    matrix: List[Dict[str, Any]] = []
    for module in registry.MODULES:
        entry = {
            "module": module.slug,
            "label": module.label,
            "group": module.group,
            "admin_only": module.admin_only,
            "read_only": module.read_only,
            "roles": {},
        }
        for role in roles:
            modules = role["modules"]
            actions = role["actions"]
            allows = "*" in modules or module.slug in modules
            if module.admin_only and "manage" not in actions and "*" not in actions:
                allows = False
            entry["roles"][role["key"]] = {
                "scope": role["scope"] if allows else None,
                "actions": sorted(
                    [
                        action
                        for action in registry.ACTION_IDS
                        if allows and ("*" in actions or action in actions)
                    ]
                ),
                "allowed": allows,
            }
        matrix.append(entry)

    return {
        "areas": list(registry.AREAS),
        "departments": list(registry.DEPARTMENTS),
        "roles": roles,
        "role_index": role_index,
        "actions": list(registry.ACTIONS),
        "scopes": list(registry.SCOPES),
        "modules": [module.to_public() for module in registry.MODULES],
        "matrix": matrix,
        "members": members.get("items", []),
        "members_total": members.get("total", 0),
        "teams": teams.get("items", []),
    }


@router.post("/rbac/sync")
def crm_rbac_sync(ctx: Context):
    """Cria atribuições de CRM para os utilizadores da plataforma que não as tenham."""
    _require_manage(ctx)
    created = suite.sync_members(force=True)
    return {"ok": True, "created": created}


# ------------------------------------------------------------------- módulos
@router.get("/mod/{module}")
def module_list(
    module: str,
    ctx: Context,
    request: Request,
    q: Optional[str] = Query(None, description="Pesquisa livre nos campos de texto do módulo"),
    size: int = Query(suite.DEFAULT_SIZE, ge=1, le=suite.MAX_SIZE),
    from_: int = Query(0, ge=0, alias="from"),
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = Query(None, pattern="^(asc|desc)$"),
):
    """Lista/pesquisa registos de um módulo (os filtros chegam como query string)."""
    spec = ctx.module(module, "read")
    filters: Dict[str, Any] = {}
    for field in spec.filter_fields:
        value = request.query_params.get(field.key)
        if value not in (None, ""):
            filters[field.key] = value
    result = suite.list_module(
        spec,
        ctx.perm,
        q=q,
        filters=filters,
        size=size,
        from_=from_,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    if result.get("error"):
        _fail(result, status=502)
    return result


@router.post("/mod/{module}", status_code=201)
def module_create(module: str, ctx: Context, request: Request, payload: Dict[str, Any] = Body(default_factory=dict)):
    """Cria um registo no módulo indicado."""
    spec = ctx.module(module, "create")
    result = suite.save_module(spec, payload, ctx.perm, **ctx.audit_context(request))
    if result.get("error"):
        _fail(result)
    return result


@router.get("/mod/{module}/stats")
def module_statistics(module: str, ctx: Context):
    """Indicadores de um módulo: totais, distribuições, somas e evolução mensal."""
    spec = ctx.module(module, "read")
    result = suite.module_stats(spec, ctx.perm)
    if result.get("error"):
        _fail(result, status=502)
    return result


@router.get("/mod/{module}/references")
def module_references(module: str, ctx: Context, size: int = Query(300, ge=1, le=suite.MAX_SIZE)):
    """Mapa `id → etiqueta` dos campos de referência do módulo (para listas e fichas)."""
    spec = ctx.module(module, "read")
    return suite.reference_options(spec, ctx.perm, size=size)


@router.get("/mod/{module}/{record_id}")
def module_get(module: str, record_id: str, ctx: Context):
    """Devolve um registo do módulo."""
    spec = ctx.module(module, "read")
    result = suite.get_module(spec, record_id, ctx.perm)
    if result.get("error"):
        _fail(result, status=404 if result["error"] == "Registo não encontrado" else 403)
    return result


@router.patch("/mod/{module}/{record_id}")
def module_update(
    module: str,
    record_id: str,
    ctx: Context,
    request: Request,
    payload: Dict[str, Any] = Body(default_factory=dict),
):
    """Altera parcialmente um registo (só os campos enviados)."""
    spec = ctx.module(module, "update")
    if not payload:
        raise HTTPException(status_code=400, detail="Nada para atualizar")
    result = suite.save_module(spec, payload, ctx.perm, record_id=record_id, **ctx.audit_context(request))
    if result.get("error"):
        _fail(result)
    return result


@router.delete("/mod/{module}/{record_id}")
def module_delete(module: str, record_id: str, ctx: Context, request: Request):
    """Apaga um registo (com cascata nos registos que dependem dele)."""
    spec = ctx.module(module, "delete")
    result = suite.delete_module(spec, record_id, ctx.perm, **ctx.audit_context(request))
    if result.get("error"):
        _fail(result)
    return result


# ------------------------------------------------------------------------ IA
@router.post("/ai/insights/generate")
def ai_insights_generate(ctx: Context):
    """Analisa os dados reais do CRM e cria/atualiza perceções."""
    ctx.module("ai-insights", "create")
    result = suite.generate_insights(ctx.perm)
    if result.get("error"):
        _fail(result)
    return result


@router.post("/ai/ask")
def ai_ask(ctx: Context, payload: Dict[str, Any] = Body(default_factory=dict)):
    """Pergunta ao assistente de CRM (responde com factos reais do pipeline)."""
    question = str(payload.get("question") or "").strip()
    if len(question) < 3:
        raise HTTPException(status_code=400, detail="Escreva uma pergunta com pelo menos 3 caracteres")
    ctx.module("ai-interactions", "create")
    module = str(payload.get("module") or "")
    if module:
        spec = registry.resolve_module(module)
        module = spec.slug if spec else ""
    result = suite.ask(
        question,
        ctx.perm,
        session=ctx.session,
        backend=str(payload.get("backend") or "") or None,
        module=module,
        record_id=str(payload.get("record_id") or ""),
    )
    if result.get("error"):
        _fail(result)
    return result


# --------------------------------------------------------------- analytics
# A camada de analytics trabalha sobre contas, produtos, encomendas, linhas e
# ordens de trabalho e fecha o ciclo «perceção → ação»: além dos indicadores,
# cria oportunidades para um público concreto.
ANALYTICS_SOURCES = ("orders", "order-lines", "products", "suppliers", "accounts", "work-orders")


def _require_analytics(ctx: CrmContext) -> None:
    """Exige acesso de leitura a pelo menos uma das fontes de venda/operação."""
    if ctx.perm.get("is_admin") or any(ctx.can(slug, "read") for slug in ANALYTICS_SOURCES):
        return
    raise HTTPException(
        status_code=403,
        detail=f"O perfil «{ctx.perm.get('role_label')}» não tem acesso aos dados de vendas e operação",
    )


def _resolve_product(ctx: CrmContext, reference: Optional[str]) -> Optional[Dict[str, Any]]:
    """Aceita um id, um nome ou uma referência de produto e devolve o produto real."""
    text = (reference or "").strip()
    if not text:
        return None
    catalogue = analytics.product_catalogue(ctx.perm)
    for product in catalogue:
        if str(product.get("id")) == text:
            return product
    return analytics.match_product(text, catalogue)


class CrossSellPayload(BaseModel):
    """Público de cross-sell: quem comprou (ou não) um produto, com receita mínima."""

    have_product: Optional[str] = Field(None, description="Produto que o cliente já comprou (id, nome ou referência)")
    missing_product: Optional[str] = Field(None, description="Produto que o cliente ainda não tem")
    min_spend: Optional[float] = Field(None, ge=0, description="Receita mínima no período")
    months: int = Field(12, ge=1, le=36)
    limit: int = Field(50, ge=1, le=200)
    exclude_with_open_opportunity: bool = True


class AnalyticsActionPayload(CrossSellPayload):
    """Ação de CRM: criar oportunidades para o público encontrado."""

    title: Optional[str] = Field(None, description="Título das oportunidades (por omissão, «Cross-sell: <produto>»)")
    amount: Optional[float] = Field(None, ge=0, description="Valor fixo por oportunidade")
    amount_from: str = Field("revenue_pct", pattern="^(revenue_pct|revenue|fixed)$")
    stage: str = "prospeccao"
    expected_days: int = Field(60, ge=1, le=365)
    dry_run: bool = Field(False, description="Simular sem gravar (mostra o que seria criado)")


@router.get("/analytics")
def crm_analytics_board(
    ctx: Context,
    months: int = Query(12, ge=1, le=36, description="Janela de análise, em meses"),
    top: int = Query(10, ge=3, le=50, description="Dimensão das listas de ranking"),
    days_without_purchase: int = Query(90, ge=7, le=730, description="Dias sem compra a partir dos quais o cliente é «em risco»"),
):
    """Painel de analytics: vendas (receita, margem, produtos, vendedores), clientes
    (CLV, frequência, inatividade) e operações (encomendas, ordens, SLA, capacidade)."""
    _require_analytics(ctx)
    return analytics.snapshot(ctx.perm, months=months, top=top, days_without_purchase=days_without_purchase)


@router.get("/analytics/datasets")
def crm_analytics_datasets(ctx: Context):
    """Catálogo de conjuntos de dados analíticos que o perfil pode usar.

    É a base do construtor de quadros (`dashboards`): o utilizador escolhe o
    dataset, a métrica e o tipo de gráfico.
    """
    _require_analytics(ctx)
    return datasets_engine.catalogue(ctx.perm)


@router.get("/analytics/datasets/{dataset_id}")
def crm_analytics_dataset_rows(
    dataset_id: str,
    ctx: Context,
    months: int = Query(12, ge=1, le=36, description="Janela de análise, em meses"),
    limit: Optional[int] = Query(None, ge=1, le=datasets_engine.MAX_LIMIT, description="Número de linhas devolvidas"),
):
    """Linhas de um conjunto de dados (dimensão + métricas), já agregadas."""
    _require_analytics(ctx)
    result = datasets_engine.rows(dataset_id, ctx.perm, months=months, limit=limit)
    if result.get("error"):
        _fail(result, status=403)
    return result


@router.post("/analytics/cross-sell")
def crm_analytics_cross_sell(ctx: Context, payload: CrossSellPayload = Body(default_factory=CrossSellPayload)):
    """Clientes que compraram um produto mas não têm outro (cross-sell/upsell)."""
    _require_analytics(ctx)
    have = _resolve_product(ctx, payload.have_product)
    missing = _resolve_product(ctx, payload.missing_product)
    if payload.have_product and have is None:
        raise HTTPException(status_code=404, detail=f"Produto não encontrado no catálogo: {payload.have_product}")
    if payload.missing_product and missing is None:
        raise HTTPException(status_code=404, detail=f"Produto não encontrado no catálogo: {payload.missing_product}")
    return analytics.cross_sell(
        ctx.perm,
        have_product_id=(have or {}).get("id"),
        missing_product_id=(missing or {}).get("id"),
        min_spend=payload.min_spend,
        months=payload.months,
        limit=payload.limit,
        exclude_with_open_opportunity=payload.exclude_with_open_opportunity,
    )


@router.post("/analytics/opportunities")
def crm_analytics_opportunities(ctx: Context, payload: AnalyticsActionPayload = Body(default_factory=AnalyticsActionPayload)):
    """Cria oportunidades para o público encontrado (o «Insight → Ação» do CRM).

    Sem `dry_run`, grava uma oportunidade por conta, na fase indicada, com a fonte
    `ia-cross-sell` e as notas a explicar o critério — e fica registado na auditoria.
    """
    _require_analytics(ctx)
    missing = _resolve_product(ctx, payload.missing_product)
    have = _resolve_product(ctx, payload.have_product)
    if payload.missing_product and missing is None:
        raise HTTPException(status_code=404, detail=f"Produto não encontrado no catálogo: {payload.missing_product}")
    if payload.have_product and have is None:
        raise HTTPException(status_code=404, detail=f"Produto não encontrado no catálogo: {payload.have_product}")

    audience = analytics.cross_sell(
        ctx.perm,
        have_product_id=(have or {}).get("id"),
        missing_product_id=(missing or {}).get("id"),
        min_spend=payload.min_spend,
        months=payload.months,
        limit=max(payload.limit, 1),
        exclude_with_open_opportunity=payload.exclude_with_open_opportunity,
    )
    title = (payload.title or "").strip() or analytics.suggest_title(str((missing or {}).get("name") or ""))
    action = analytics.create_opportunities(
        ctx.perm,
        audience=audience["accounts"],
        title=title,
        amount=payload.amount,
        amount_from=payload.amount_from,
        stage=payload.stage,
        source="ia-cross-sell",
        dry_run=payload.dry_run,
        limit=min(payload.limit, analytics.MAX_CREATE),
    )
    if action.get("error"):
        _fail(action, status=403)
    return {**action, "title": title, "publico": audience, "critério": audience.get("filtros")}
