"""Rotas da ontologia (`/ontology/*`).

A ontologia é a camada semântica do IQ OS: descreve **tipos de objeto**
(Empresa, Contrato, Ticker, Notícia, Conta, Pessoa, …), as suas propriedades,
as **ligações** entre eles e as **ações** disponíveis — tudo ligado aos dados
reais (Elasticsearch e agregados) e utilizável pela IA.

Leitura (pública):

- `GET  /ontology`                       — ontologia completa (tipos, ligações, ações)
- `GET  /ontology/summary`               — resumo + grafo de tipos/ligações
- `GET  /ontology/object-types`          — lista dos tipos de objeto
- `GET  /ontology/object-types/{id}`     — tipo + ligações + ações aplicáveis
- `GET  /ontology/link-types`            — lista das ligações
- `GET  /ontology/actions`               — lista das ações
- `GET  /ontology/graph`                 — nós/arestas para visualização
- `GET  /ontology/status`                — disponibilidade e volumetria por índice
- `POST /ontology/objects/{tipo}/query`  — consulta de objetos (pesquisa, filtros, ordenação)
- `GET  /ontology/objects/{tipo}/{id}`   — objeto individual (com ligações opcionais)
- `POST /ontology/objects/{tipo}/{id}/links` — navegação nas relações de um objeto
- `POST /ontology/resolve`               — resolução de entidades (texto → objetos canónicos)

IA (uso pela plataforma):

- `POST /ontology/ai/context`            — contexto ontológico de uma pergunta (grounding)
- `POST /ontology/ai/answer`             — resposta factual construída só com a ontologia
- `POST /ontology/ai/validate`           — validação anti-alucinação de uma resposta
- `GET  /ontology/ai/tools`              — ferramentas geradas a partir da ontologia

Escrita (requer sessão; apagar/repor exige papel `admin`):

- `POST/PATCH/DELETE /ontology/object-types…` e `/ontology/link-types…`
- `POST /ontology/reset`                 — repõe a semente da ontologia

Âmbito e privacidade: os tipos ligados ao CRM (`finance_crm`) exigem sessão —
cada utilizador só vê os seus registos, salvo se tiver o papel `admin`. Sem
sessão, esses tipos ficam de fora (nunca se expõem dados de outros utilizadores).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api import ontology_registry as registry
from api import ontology_service as ontology
from api.auth_routes import CurrentSession, optional_session, require_session
from api.elasticsearch_client import ensure_indices, get_es_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ontology", tags=["ontology"])

Session = Annotated[Optional[CurrentSession], Depends(optional_session)]


def _scope(session: Optional[CurrentSession]) -> Optional[Dict[str, Any]]:
    """Âmbito de visibilidade (o CRM é privado por utilizador; `admin` vê tudo)."""
    if not session:
        return None
    return {
        "user_id": session.user.id,
        "email": session.user.email,
        "see_all": (session.user.role or "member") == "admin",
    }


def _require_admin(session: CurrentSession) -> None:
    if (session.user.role or "member") != "admin":
        raise HTTPException(status_code=403, detail="Apenas administradores podem alterar a ontologia base.")


# ------------------------------------------------------------------- modelos
class ObjectQueryRequest(BaseModel):
    search: Optional[str] = Field(None, description="Pesquisa livre (nome, NIF, objeto do contrato, título).")
    filters: Dict[str, Any] = Field(default_factory=dict, description="Filtros por propriedade.")
    size: int = Field(20, ge=1, le=200)
    from_: int = Field(0, ge=0, alias="from")
    sort: Optional[Any] = Field(None, description="{'id': 'valor_total', 'order': 'desc'} ou o id da propriedade.")

    model_config = {"populate_by_name": True}


class ResolveRequest(BaseModel):
    text: str
    limit: int = Field(5, ge=1, le=10)
    types: Optional[List[str]] = None


class AiContextRequest(BaseModel):
    question: str
    limit: int = Field(5, ge=1, le=10)
    links_per_object: int = Field(3, ge=0, le=6)


class AiAnswerRequest(BaseModel):
    question: str


class ValidateRequest(BaseModel):
    answer: str
    question: Optional[str] = None
    context: Optional[Dict[str, Any]] = None


class ActionResolveRequest(BaseModel):
    type: Optional[str] = None
    id: Optional[str] = None
    params: Dict[str, Any] = Field(default_factory=dict)


class ObjectTypePayload(BaseModel):
    id: str
    label: Optional[str] = None
    plural: Optional[str] = None
    description: Optional[str] = None
    domain: Optional[str] = None
    icon: Optional[str] = None
    primary_key: Optional[str] = None
    title_field: Optional[str] = None
    subtitle_fields: Optional[List[str]] = None
    resolvable: Optional[bool] = None
    requires_session: Optional[bool] = None
    query_hint: Optional[str] = None
    binding: Optional[Dict[str, Any]] = None
    properties: Optional[List[Dict[str, Any]]] = None


class LinkTypePayload(BaseModel):
    """Tipos de ligação (`from`/`to` são palavras reservadas em Python, daí os aliases)."""

    id: str
    label: Optional[str] = None
    description: Optional[str] = None
    source_type: str = Field(..., alias="from")
    target_type: str = Field(..., alias="to")
    cardinality: Optional[str] = None
    binding: Optional[Dict[str, Any]] = None
    reverse: Optional[Dict[str, Any]] = None

    model_config = {"populate_by_name": True}


# ------------------------------------------------------------------ leitura
@router.get("")
def get_ontology() -> Dict[str, Any]:
    """Ontologia completa (tipos de objeto, ligações e ações)."""
    doc = registry.load_ontology()
    doc["graph"] = _graph(doc)
    return doc


@router.get("/summary")
def get_summary() -> Dict[str, Any]:
    """Resumo da ontologia + grafo de tipos (para a página de ontologia)."""
    doc = registry.load_ontology()
    counts: Dict[str, int] = {}
    for obj in doc["object_types"]:
        counts[obj["domain"]] = counts.get(obj["domain"], 0) + 1
    return {
        "version": doc["version"],
        "updated_at": doc["updated_at"],
        "domains": [
            {**domain, "object_types": counts.get(domain["id"], 0)}
            for domain in doc["domains"]
        ],
        "totals": {
            "object_types": len(doc["object_types"]),
            "link_types": len(doc["link_types"]),
            "actions": len(doc["actions"]),
            "custom": len([obj for obj in doc["object_types"] if not obj.get("builtin")]),
            "session_required": len([obj for obj in doc["object_types"] if ontology.requires_session(obj)]),
        },
        "graph": _graph(doc),
        "limits": doc["limits"],
    }


def _graph(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Nós/arestas do grafo de tipos de objeto."""
    nodes = [
        {
            "id": obj["id"],
            "label": obj["label"],
            "domain": obj["domain"],
            "icon": obj.get("icon"),
            "properties": len(obj.get("properties", [])),
            "source_kind": obj.get("binding", {}).get("kind"),
            "session_required": ontology.requires_session(obj),
        }
        for obj in doc["object_types"]
    ]
    known = {node["id"] for node in nodes}
    edges = [
        {
            "id": link["id"],
            "source": link["from"],
            "target": link["to"],
            "label": link["label"],
            "cardinality": link.get("cardinality"),
            "reverse": bool(link.get("reverse")),
        }
        for link in doc["link_types"]
        if link["from"] in known and link["to"] in known
    ]
    return {"nodes": nodes, "edges": edges}


@router.get("/object-types")
def list_object_types() -> Dict[str, Any]:
    """Lista dos tipos de objeto com metadados (contagens, domínio, origem)."""
    doc = registry.load_ontology()
    items = []
    for obj in doc["object_types"]:
        items.append(
            {
                "id": obj["id"],
                "label": obj["label"],
                "plural": obj.get("plural"),
                "description": obj.get("description"),
                "domain": obj["domain"],
                "icon": obj.get("icon"),
                "primary_key": ontology._pk_prop(obj)["id"],
                "title_field": ontology._title_field(obj),
                "source_kind": obj.get("binding", {}).get("kind"),
                "sources": obj.get("binding", {}).get("sources", []),
                "resolvable": bool(obj.get("resolvable")),
                "builtin": bool(obj.get("builtin")),
                "session_required": ontology.requires_session(obj),
                "properties": len(obj.get("properties", [])),
                "links": obj.get("link_counts", {}),
                "actions": obj.get("action_count", 0),
            }
        )
    return {"total": len(items), "items": items, "domains": registry.load_ontology()["domains"]}


@router.get("/object-types/{type_id}")
def get_object_type_detail(type_id: str) -> Dict[str, Any]:
    """Detalhe de um tipo: propriedades, origens de dados, ligações e ações."""
    try:
        obj_type = ontology.get_object_type(type_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {
        "object_type": obj_type,
        "links": ontology.links_for_type(type_id),
        "actions": [action for action in ontology.actions() if action.get("object_type") == type_id],
        "source_kind": obj_type.get("binding", {}).get("kind"),
        "session_required": ontology.requires_session(obj_type),
    }


@router.get("/link-types")
def list_link_types() -> Dict[str, Any]:
    doc = registry.load_ontology()
    labels = {obj["id"]: obj["label"] for obj in doc["object_types"]}
    items = [
        {
            **link,
            "from_label": labels.get(link["from"], link["from"]),
            "to_label": labels.get(link["to"], link["to"]),
            "has_reverse": bool(link.get("reverse")),
        }
        for link in doc["link_types"]
    ]
    return {"total": len(items), "items": items}


@router.get("/actions")
def list_actions(object_type: Optional[str] = None) -> Dict[str, Any]:
    items = [action for action in ontology.actions() if not object_type or action.get("object_type") == object_type]
    return {"total": len(items), "items": items}


@router.get("/graph")
def get_graph() -> Dict[str, Any]:
    return _graph(registry.load_ontology())


@router.get("/status")
def get_status() -> Dict[str, Any]:
    """Disponibilidade das fontes e volumetria por índice."""
    es = get_es_client()
    doc = registry.load_ontology()
    sources: Dict[str, Dict[str, Any]] = {}
    if es:
        ensure_indices(es)
        for obj in doc["object_types"]:
            binding = obj.get("binding", {})
            index = binding.get("index")
            if not index:
                continue
            entry = sources.setdefault(index, {"index": index, "object_types": [], "documents": None})
            entry["object_types"].append(obj["id"])
        for entry in sources.values():
            try:
                entry["documents"] = int(es.count(index=entry["index"]).get("count", 0))
            except Exception:
                entry["documents"] = None
    return {
        "elasticsearch": bool(es),
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "sources": list(sources.values()) or [
            {"index": index, "object_types": [], "documents": None}
            for index in sorted({obj.get("binding", {}).get("index") for obj in doc["object_types"] if obj.get("binding", {}).get("index")})
        ],
        "notes": ["Sem Elasticsearch disponível: os tipos derivados e agregados não devolvem dados."] if not es else [],
    }


# --------------------------------------------------------------- consultas
@router.post("/objects/{type_id}/query")
def query_objects(type_id: str, payload: ObjectQueryRequest, session: Session) -> Dict[str, Any]:
    """Consulta objetos de um tipo (pesquisa, filtros por propriedade, ordenação)."""
    try:
        return ontology.query_objects(
            type_id,
            search=payload.search,
            filters=payload.filters,
            size=payload.size,
            from_=payload.from_,
            sort=payload.sort,
            scope=_scope(session),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc))


@router.get("/objects/{type_id}/{object_id}")
def get_object(
    type_id: str,
    object_id: str,
    session: Session,
    include_source: bool = False,
    with_links: bool = False,
) -> Dict[str, Any]:
    """Objeto individual, com documento de origem e ligações opcionais."""
    try:
        result = ontology.get_object(
            type_id,
            object_id,
            scope=_scope(session),
            include_source=include_source,
            with_links=with_links,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    if not result.get("found"):
        raise HTTPException(status_code=404, detail=f"Objeto {type_id}/{object_id} não encontrado.")
    result["actions"] = [
        action for action in ontology.actions() if action.get("object_type") == type_id
    ]
    if not result.get("links"):
        result["available_links"] = ontology.links_for_type(type_id)
    return result


@router.post("/objects/{type_id}/{object_id}/links")
def get_object_links(
    type_id: str,
    object_id: str,
    session: Session,
    link: Optional[str] = Query(None, description="Filtrar por ligação (id)."),
    size: int = Query(10, ge=1, le=50),
) -> Dict[str, Any]:
    """Navega nas relações de um objeto (contratos, marcas, contactos, notícias, …)."""
    try:
        result = ontology.object_links(type_id, object_id, link_id=link, size=size, scope=_scope(session))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    if not result.get("found"):
        raise HTTPException(status_code=404, detail=f"Objeto {type_id}/{object_id} não encontrado.")
    return result


@router.post("/resolve")
def resolve_entities(payload: ResolveRequest, session: Session) -> Dict[str, Any]:
    """Resolve texto livre (NIF, nome, ticker) em objetos canónicos da ontologia."""
    return ontology.resolve_entities(payload.text, limit=payload.limit, type_ids=payload.types, scope=_scope(session))


# ---------------------------------------------------------------------- IA
@router.post("/ai/context")
def ai_context(payload: AiContextRequest, session: Session) -> Dict[str, Any]:
    """Contexto ontológico de uma pergunta: objetos resolvidos, relações e bloco de grounding."""
    return ontology.ai_context(
        payload.question,
        limit=payload.limit,
        links_per_object=payload.links_per_object,
        scope=_scope(session),
    )


@router.post("/ai/answer")
def ai_answer(payload: AiAnswerRequest, session: Session) -> Dict[str, Any]:
    """Resposta factual construída apenas com objetos e relações da ontologia (sem modelo generativo)."""
    return ontology.grounded_answer(payload.question, scope=_scope(session))


@router.post("/ai/validate")
def validate(payload: ValidateRequest, session: Session) -> Dict[str, Any]:
    """Validação anti-alucinação: confirma se as entidades e valores existem nos dados."""
    return ontology.validate_answer(payload.answer, question=payload.question, context=payload.context, scope=_scope(session))


@router.get("/ai/tools")
def ai_tools(include_crm: bool = False) -> Dict[str, Any]:
    """Ferramentas (esquemas de função) geradas a partir da ontologia, para agentes de IA."""
    tools = ontology.generated_tools(include_crm=include_crm)
    return {"total": len(tools), "items": tools}


# ---------------------------------------------------------------- ações
@router.post("/actions/{action_id}/resolve")
def resolve_action(action_id: str, payload: ActionResolveRequest, session: Session) -> Dict[str, Any]:
    """Traduz uma ação da ontologia num pedido concreto (método, URL, corpo)."""
    try:
        return ontology.resolve_action(
            action_id,
            object_id=payload.id,
            type_id=payload.type,
            params=payload.params,
            scope=_scope(session),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc))


# --------------------------------------------------------------- escrita
@router.post("/object-types")
def upsert_object_type(payload: ObjectTypePayload, session: Annotated[CurrentSession, Depends(require_session)]) -> Dict[str, Any]:
    """Cria ou altera um tipo de objeto (os tipos base guardam-se como alterações)."""
    try:
        item = registry.upsert_object_type(payload.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    ontology.clear_cache()
    return {"saved": True, "object_type": item}


@router.patch("/object-types/{type_id}")
def patch_object_type(type_id: str, payload: ObjectTypePayload, session: Annotated[CurrentSession, Depends(require_session)]) -> Dict[str, Any]:
    body = payload.model_dump(exclude_none=True)
    body["id"] = type_id
    try:
        item = registry.upsert_object_type(body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    ontology.clear_cache()
    return {"saved": True, "object_type": item}


@router.delete("/object-types/{type_id}")
def delete_object_type(type_id: str, session: Annotated[CurrentSession, Depends(require_session)]) -> Dict[str, Any]:
    _require_admin(session)
    removed = registry.delete("object_types", type_id)
    ontology.clear_cache()
    return {"removed": removed, "id": type_id}


@router.post("/link-types")
def upsert_link_type(payload: LinkTypePayload, session: Annotated[CurrentSession, Depends(require_session)]) -> Dict[str, Any]:
    """Cria ou altera um tipo de ligação."""
    body = payload.model_dump(by_alias=True, exclude_none=True)
    try:
        item = registry.upsert_link_type(body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    ontology.clear_cache()
    return {"saved": True, "link_type": item}


@router.patch("/link-types/{link_id}")
def patch_link_type(link_id: str, payload: LinkTypePayload, session: Annotated[CurrentSession, Depends(require_session)]) -> Dict[str, Any]:
    body = payload.model_dump(by_alias=True, exclude_none=True)
    body["id"] = link_id
    try:
        item = registry.upsert_link_type(body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    ontology.clear_cache()
    return {"saved": True, "link_type": item}


@router.delete("/link-types/{link_id}")
def delete_link_type(link_id: str, session: Annotated[CurrentSession, Depends(require_session)]) -> Dict[str, Any]:
    _require_admin(session)
    removed = registry.delete("link_types", link_id)
    ontology.clear_cache()
    return {"removed": removed, "id": link_id}


@router.post("/reset")
def reset(
    session: Annotated[CurrentSession, Depends(require_session)],
    confirm: bool = Body(False, embed=True),
) -> Dict[str, Any]:
    """Repõe a ontologia base (remove tipos personalizados, alterações e desativações)."""
    _require_admin(session)
    if not confirm:
        raise HTTPException(status_code=422, detail="Confirmação necessária: envie {'confirm': true}.")
    doc = registry.reset_ontology()
    ontology.clear_cache()
    return {"reset": True, "object_types": len(doc["object_types"]), "link_types": len(doc["link_types"])}
