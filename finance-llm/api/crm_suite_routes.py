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

Este router é registado **antes** do router do CRM comercial (`api.crm_routes`),
para que os caminhos genéricos não colidam com `/crm/{tipo}/{id}`.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request

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
