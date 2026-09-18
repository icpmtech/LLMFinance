"""Rotas da área de trabalho da ontologia (`/ontology/*`): ontologias, fontes,
projetos, fichas de análise, grafo de exploração e IA de desenho.

Este módulo é acrescentado ao router principal (`api/ontology_routes.py`) e cobre
tudo o que é preciso para **construir** ontologias, não só consultá-las:

Ontologias
- `GET    /ontology/ontologies`            — catálogo (id, nome, contagens)
- `POST   /ontology/ontologies`            — criar (vazia, cópia da base ou de outra)
- `PATCH  /ontology/ontologies/{id}`       — alterar nome/descrição/cor/etiquetas/metadados
- `DELETE /ontology/ontologies/{id}`       — remover (admin; a base do IQ OS é protegida)

Fontes de dados
- `GET    /ontology/sources`               — lista (+ diagnóstico guardado)
- `POST   /ontology/sources`               — criar/alterar fonte (Elasticsearch, REST, ficheiro)
- `DELETE /ontology/sources/{id}`
- `POST   /ontology/sources/{id}/probe`    — diagnóstico real (índice, campos, exemplos)
- `POST   /ontology/sources/{id}/infer`    — gerar tipo de objeto a partir da fonte (e gravar)

Projetos e fichas de análise
- `GET|POST /ontology/projects`, `PATCH|DELETE /ontology/projects/{id}`
- `GET    /ontology/projects/{id}`         — projeto com fontes, tipos e fichas resolvidos
- `GET|POST /ontology/dossiers`, `PATCH|DELETE /ontology/dossiers/{id}`
- `POST   /ontology/dossiers/{id}/facts`   — factos verificados + relações do assunto
- `POST   /ontology/dossiers/{id}/draft`   — redigir secção (IA, com alternativa factual)

Exploração e IA
- `POST   /ontology/graph/explore`         — grafo de objetos reais a partir de um nó
- `POST   /ontology/ai/design`             — desenhar tipos/ligações (descrição + fontes)
- `POST   /ontology/ai/suggest-links`      — ligações que faltam entre tipos
- `POST   /ontology/ai/dossier`            — redigir ficha a partir de um objeto
"""
from __future__ import annotations

import logging
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from api import ontology_ai as ai
from api import ontology_registry as registry
from api import ontology_service as ontology
from api import ontology_sources as sources_service
from api.auth_routes import CurrentSession, optional_session, require_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ontology", tags=["ontology"])

Session = Annotated[Optional[CurrentSession], Depends(optional_session)]
Writer = Annotated[CurrentSession, Depends(require_session)]


def _scope(session: Optional[CurrentSession]) -> Optional[Dict[str, Any]]:
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


def _target(ontology_id: Optional[str]) -> str:
    """Ontologia do pedido (`?ontology=`), com a base do IQ OS por omissão."""
    return registry.normalize_ontology_id(ontology_id) or registry.active_ontology_id()


# ==========================================================================
# Ontologias
# ==========================================================================
@router.get("/ontologies")
def list_ontologies() -> Dict[str, Any]:
    """Catálogo das ontologias, com contagens de tipos, fontes, projetos e fichas."""
    items = registry.list_ontologies()
    return {
        "total": len(items),
        "items": items,
        "active": registry.active_ontology_id(),
    }


@router.get("/active")
def active_ontology(ontology_id: Optional[str] = Query(None, alias="ontology")) -> Dict[str, Any]:
    """Ontologia usada neste pedido, com os totais reais (tipos, fontes, projetos, fichas)."""
    target = _target(ontology_id)
    doc = registry.load_ontology(ontology_id=target)
    return {
        "ontology": doc["ontology"],
        "totals": {
            "object_types": len(doc["object_types"]),
            "link_types": len(doc["link_types"]),
            "domains": len(doc["domains"]),
            "sources": len(doc["sources"]),
            "projects": len(doc["projects"]),
            "dossiers": len(doc["dossiers"]),
        },
        "metadata": doc.get("metadata") or {},
    }


@router.post("/ontologies")
def create_ontology(payload: Dict[str, Any] = Body(...), session: Writer = None) -> Dict[str, Any]:
    """Cria uma ontologia nova (`template`: `blank`, `base` ou o id de outra)."""
    try:
        item = registry.create_ontology({**payload, "created_by": session.user.email if session else None})
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    ontology.clear_cache()
    return {"created": True, "ontology": item}


@router.patch("/ontologies/{ontology_id}")
def update_ontology(ontology_id: str, payload: Dict[str, Any] = Body(...), session: Writer = None) -> Dict[str, Any]:
    """Altera os metadados de uma ontologia (nome, descrição, cor, etiquetas, metadados)."""
    try:
        item = registry.update_ontology(ontology_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    ontology.clear_cache()
    return {"saved": True, "ontology": item}


@router.delete("/ontologies/{ontology_id}")
def delete_ontology(ontology_id: str, session: Writer = None) -> Dict[str, Any]:
    """Remove uma ontologia (admin ou quem a criou; a base do IQ OS é protegida)."""
    try:
        entry = registry.get_ontology_entry(ontology_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    role = (session.user.role or "member") if session else "member"
    owner = str(entry.get("created_by") or "").strip().lower()
    email = (session.user.email or "").strip().lower() if session else ""
    if role != "admin" and (not owner or owner != email):
        raise HTTPException(status_code=403, detail="Só o autor da ontologia ou um administrador a podem remover.")
    try:
        removed = registry.delete_ontology(entry["id"])
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    ontology.clear_cache()
    return {"removed": removed, "id": entry["id"]}


# ==========================================================================
# Fontes de dados
# ==========================================================================
@router.get("/sources")
def list_sources(ontology_id: Optional[str] = Query(None, alias="ontology")) -> Dict[str, Any]:
    """Fontes de dados da ontologia, com o último diagnóstico guardado."""
    target = _target(ontology_id)
    items = registry.list_sources(target)
    in_use: Dict[str, List[str]] = {}
    for obj in registry.load_ontology(ontology_id=target)["object_types"]:
        source_id = (obj.get("binding") or {}).get("source")
        if source_id:
            in_use.setdefault(str(source_id), []).append(obj["id"])
    return {
        "total": len(items),
        "items": [{**item, "used_by": in_use.get(item["id"], [])} for item in items],
        "kinds": [
            {"id": "elasticsearch", "label": "Elasticsearch (índice)", "hint": "Documentos indexados: pesquisa, filtros e agregados."},
            {"id": "rest", "label": "API REST (JSON)", "hint": "Endpoint HTTP que devolve JSON (leitura instantânea)."},
            {"id": "file", "label": "Ficheiro (JSON/CSV)", "hint": "Ficheiro local lido a pedido."},
            {"id": "derived", "label": "Derivado (código da plataforma)", "hint": "Resolvedor Python já existente na plataforma."},
        ],
    }


@router.post("/sources")
def upsert_source(
    payload: Dict[str, Any] = Body(...),
    ontology_id: Optional[str] = Query(None, alias="ontology"),
    session: Writer = None,
) -> Dict[str, Any]:
    """Cria ou altera uma fonte de dados da ontologia."""
    try:
        item = registry.upsert_source(payload, _target(ontology_id))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    ontology.clear_cache()
    return {"saved": True, "source": item}


@router.delete("/sources/{source_id}")
def delete_source(source_id: str, ontology_id: Optional[str] = Query(None, alias="ontology"), session: Writer = None) -> Dict[str, Any]:
    removed = registry.delete_workspace_item("sources", source_id, _target(ontology_id))
    ontology.clear_cache()
    return {"removed": removed, "id": source_id}


@router.post("/sources/{source_id}/probe")
def probe_source(
    source_id: str,
    save: bool = Query(True, description="Guardar o diagnóstico na fonte (estado e campos)."),
    with_samples: bool = Query(True, description="Recolher exemplos de valores (só Elasticsearch)."),
    ontology_id: Optional[str] = Query(None, alias="ontology"),
    session: Writer = None,
) -> Dict[str, Any]:
    """Diagnóstico real da fonte: índice e documentos, campos e tipos, exemplos de valores."""
    target = _target(ontology_id)
    try:
        source = registry.get_workspace_item("sources", source_id, target)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    diagnostic = sources_service.probe(source, with_samples=with_samples)
    saved = None
    if save:
        saved = registry.upsert_source(
            {
                **source,
                "fields": diagnostic.get("fields") or source.get("fields") or [],
                "status": {
                    "state": diagnostic.get("state"),
                    "ok": bool(diagnostic.get("ok")),
                    "checked_at": registry._now(),
                    "documents": diagnostic.get("documents"),
                    "bytes": diagnostic.get("bytes"),
                    "status_code": diagnostic.get("status"),
                    "fields": len(diagnostic.get("fields") or []),
                    "note": diagnostic.get("note"),
                },
            },
            target,
        )
    ontology.clear_cache()
    return {"source": saved or source, "diagnostic": diagnostic, "saved": save}


@router.post("/sources/{source_id}/infer")
def infer_from_source(
    source_id: str,
    payload: Dict[str, Any] = Body(default_factory=dict),
    ontology_id: Optional[str] = Query(None, alias="ontology"),
    session: Writer = None,
) -> Dict[str, Any]:
    """Gera um tipo de objeto a partir dos campos reais da fonte (com opção de gravar)."""
    target = _target(ontology_id)
    try:
        source = registry.get_workspace_item("sources", source_id, target)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    diagnostic = sources_service.probe(source)
    fields = diagnostic.get("fields") or source.get("fields") or []
    if not fields:
        raise HTTPException(status_code=422, detail=diagnostic.get("note") or "A fonte não devolveu campos utilizáveis.")
    proposal = sources_service.infer_object_type(
        source,
        fields=fields,
        type_id=payload.get("id"),
        label=payload.get("label"),
        domain=payload.get("domain"),
        samples=diagnostic.get("samples") or {},
    )
    result: Dict[str, Any] = {"proposal": proposal, "source": source, "diagnostic": {"fields": len(fields), "documents": diagnostic.get("documents")}}
    if payload.get("apply"):
        body = dict(proposal)
        if payload.get("domain"):
            body["domain"] = payload["domain"]
        item = registry.upsert_object_type(body, target)
        ontology.clear_cache()
        result["applied"] = {"object_type": item}
    return result


# ==========================================================================
# Projetos
# ==========================================================================
@router.get("/projects")
def list_projects(ontology_id: Optional[str] = Query(None, alias="ontology")) -> Dict[str, Any]:
    """Projetos (áreas de trabalho) da ontologia, com fichas e fontes associadas."""
    target = _target(ontology_id)
    items = registry.list_projects(target)
    dossiers = registry.list_dossiers(target)
    for project in items:
        project["dossier_count"] = len([item for item in dossiers if item.get("project_id") == project["id"]])
    return {"total": len(items), "items": items, "dossiers_total": len(dossiers)}


@router.post("/projects")
def upsert_project(
    payload: Dict[str, Any] = Body(...),
    ontology_id: Optional[str] = Query(None, alias="ontology"),
    session: Writer = None,
) -> Dict[str, Any]:
    """Cria ou altera um projeto (área de trabalho da ontologia)."""
    body = dict(payload)
    if not body.get("id") and not body.get("owner"):
        body["owner"] = session.user.email if session else None
    try:
        item = registry.upsert_project(body, _target(ontology_id))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"saved": True, "project": item}


@router.get("/projects/{project_id}")
def get_project(project_id: str, ontology_id: Optional[str] = Query(None, alias="ontology")) -> Dict[str, Any]:
    """Projeto com fontes, tipos de objeto e fichas resolvidos em nomes."""
    target = _target(ontology_id)
    try:
        project = registry.get_workspace_item("projects", project_id, target)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    doc = registry.load_ontology(ontology_id=target)
    labels = {item["id"]: item["label"] for item in doc["object_types"]}
    source_labels = {item["id"]: item.get("label") or item["id"] for item in registry.list_sources(target)}
    dossiers = [item for item in registry.list_dossiers(target) if item.get("project_id") == project_id]
    return {
        "project": project,
        "sources": [
            {"id": source_id, "label": source_labels.get(source_id, source_id)}
            for source_id in project.get("source_ids") or []
        ],
        "object_types": [
            {"id": type_id, "label": labels.get(type_id, type_id)} for type_id in project.get("type_ids") or []
        ],
        "dossiers": dossiers,
        "available_sources": sorted(source_labels.items(), key=lambda entry: entry[1]),
        "available_object_types": sorted(labels.items(), key=lambda entry: entry[1]),
    }


@router.delete("/projects/{project_id}")
def delete_project(project_id: str, ontology_id: Optional[str] = Query(None, alias="ontology"), session: Writer = None) -> Dict[str, Any]:
    removed = registry.delete_workspace_item("projects", project_id, _target(ontology_id))
    return {"removed": removed, "id": project_id}


# ==========================================================================
# Fichas de análise
# ==========================================================================
@router.get("/dossiers")
def list_dossiers(
    project_id: Optional[str] = Query(None),
    ontology_id: Optional[str] = Query(None, alias="ontology"),
) -> Dict[str, Any]:
    """Fichas de análise (todas ou as de um projeto)."""
    items = registry.list_dossiers(_target(ontology_id))
    if project_id:
        items = [item for item in items if item.get("project_id") == project_id]
    return {"total": len(items), "items": items}


@router.post("/dossiers")
def upsert_dossier(
    payload: Dict[str, Any] = Body(...),
    ontology_id: Optional[str] = Query(None, alias="ontology"),
    session: Writer = None,
) -> Dict[str, Any]:
    """Cria ou altera uma ficha de análise."""
    body = dict(payload)
    if not body.get("id"):
        body["author"] = body.get("author") or (session.user.email if session else None)
    try:
        item = registry.upsert_dossier(body, _target(ontology_id))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"saved": True, "dossier": item}


@router.delete("/dossiers/{dossier_id}")
def delete_dossier(dossier_id: str, ontology_id: Optional[str] = Query(None, alias="ontology"), session: Writer = None) -> Dict[str, Any]:
    removed = registry.delete_workspace_item("dossiers", dossier_id, _target(ontology_id))
    return {"removed": removed, "id": dossier_id}


@router.post("/dossiers/{dossier_id}/facts")
def dossier_facts(
    dossier_id: str,
    ontology_id: Optional[str] = Query(None, alias="ontology"),
    session: Session = None,
) -> Dict[str, Any]:
    """Factos verificados do assunto da ficha: objeto, propriedades e relações reais."""
    target = _target(ontology_id)
    try:
        dossier = registry.get_workspace_item("dossiers", dossier_id, target)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    subject = dossier.get("subject") or {}
    if not subject.get("type_id") or not subject.get("object_id"):
        raise HTTPException(status_code=422, detail="A ficha ainda não tem um objeto da ontologia como assunto.")
    scope = _scope(session)
    try:
        detail = ontology.get_object(
            subject["type_id"], str(subject["object_id"]), scope=scope, with_links=True
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    try:
        links = ontology.object_links(subject["type_id"], str(subject["object_id"]), size=8, scope=scope)
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    groups = [
        {
            "id": group.get("id"),
            "label": group.get("label"),
            "total": group.get("count") or len(group.get("items") or []),
            "items": [
                {"id": item.get("_id"), "label": item.get("_label")} for item in (group.get("items") or [])[:6]
            ],
        }
        for group in links.get("links") or []
    ]
    facts = ai._facts_for(subject, {**links, "links": groups}, detail)
    return {"dossier": dossier, "object": detail.get("object"), "links": groups, "facts": facts}


@router.post("/dossiers/{dossier_id}/draft")
async def draft_dossier(
    dossier_id: str,
    payload: Dict[str, Any] = Body(default_factory=dict),
    ontology_id: Optional[str] = Query(None, alias="ontology"),
    session: Session = None,
) -> Dict[str, Any]:
    """Redige uma secção da ficha (com IA quando há fornecedor configurado)."""
    target = _target(ontology_id)
    try:
        dossier = registry.get_workspace_item("dossiers", dossier_id, target)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    body = dict(payload or {})
    if body.get("subject") is None and dossier.get("subject"):
        body["subject"] = dossier["subject"]
    body.setdefault("scope", _scope(session))
    return await ai.draft_dossier(
        dossier=dossier,
        payload=body,
        session=session,
        backend=body.get("backend"),
        ontology_id=target,
        apply=bool(body.get("apply", True)),
    )


@router.post("/ai/dossier")
async def ai_dossier(payload: Dict[str, Any] = Body(...), session: Session = None) -> Dict[str, Any]:
    """Redige uma ficha a partir de um objeto da ontologia (sem precisar de a ter criado antes)."""
    subject = payload.get("subject") or {}
    if not subject.get("type_id") or not subject.get("object_id"):
        raise HTTPException(status_code=422, detail="Indique o objeto (`subject.type_id` e `subject.object_id`).")
    dossier = {
        "title": payload.get("title") or f"Análise de {subject.get('object_id')}",
        "subject": subject,
        "sections": payload.get("sections") or [],
    }
    result = await ai.draft_dossier(
        dossier=dossier,
        payload={**payload, "scope": _scope(session)},
        session=session,
        backend=payload.get("backend"),
        ontology_id=payload.get("ontology"),
        apply=False,
    )
    return result


# ==========================================================================
# Grafo de exploração
# ==========================================================================
@router.post("/graph/explore")
def explore_graph(payload: Dict[str, Any] = Body(...), session: Session = None) -> Dict[str, Any]:
    """Grafo de exploração: parte de um objeto e expande as relações reais (dados, não modelo)."""
    type_id = str(payload.get("type_id") or "").strip()
    object_id = str(payload.get("object_id") or "").strip()
    if not type_id or not object_id:
        raise HTTPException(status_code=422, detail="Indique `type_id` e `object_id` do objeto de partida.")
    try:
        return ontology.explore_graph(
            type_id,
            object_id,
            depth=int(payload.get("depth") or 2),
            node_limit=int(payload.get("node_limit") or 60),
            links_per_object=int(payload.get("links_per_object") or 5),
            link_ids=payload.get("link_ids"),
            scope=_scope(session),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc))


# ==========================================================================
# IA de desenho
# ==========================================================================
@router.post("/ai/design")
async def ai_design(payload: Dict[str, Any] = Body(...), session: Session = None) -> Dict[str, Any]:
    """Propõe tipos de objeto, propriedades e ligações para a ontologia ativa.

    Usa as fontes de dados registadas (campos reais e exemplos) e a descrição do
    utilizador. Com `apply: true` grava a proposta na ontologia (requer sessão).
    """
    ontology_id = payload.get("ontology")
    target = _target(ontology_id)
    result = await ai.design_ontology(
        description=str(payload.get("description") or ""),
        source_ids=payload.get("source_ids"),
        domain=payload.get("domain"),
        backend=payload.get("backend"),
        session=session,
        ontology_id=target,
        sample_text=payload.get("sample_text"),
        instructions=payload.get("instructions"),
    )
    if payload.get("apply"):
        if not session:
            raise HTTPException(status_code=401, detail="Entrar na plataforma para aplicar a proposta.")
        proposal = result.get("proposal") or {}
        result["applied"] = ai.apply_proposal(proposal, ontology_id=target)
    return result


@router.post("/ai/suggest-links")
async def ai_suggest_links(payload: Dict[str, Any] = Body(default_factory=dict), session: Session = None) -> Dict[str, Any]:
    """Sugere ligações em falta entre os tipos de objeto existentes."""
    return await ai.suggest_links(
        backend=payload.get("backend"),
        session=session,
        ontology_id=payload.get("ontology"),
        type_ids=payload.get("type_ids"),
        apply=bool(payload.get("apply")),
    )


@router.post("/ai/extract")
async def ai_extract(payload: Dict[str, Any] = Body(...), session: Session = None) -> Dict[str, Any]:
    """Extrai candidatos (objetos, fontes, metadados) de um texto livre.

    A resposta é uma proposta de metadados e relações para o utilizador confirmar —
    nunca escreve dados sozinha.
    """
    text = str(payload.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=422, detail="Envie o texto a analisar.")
    target = _target(payload.get("ontology"))
    doc = registry.load_ontology(ontology_id=target)
    chosen = ai.available_backend(session, payload.get("backend"))
    resolved = ontology.resolve_entities(text, limit=5, scope=_scope(session))
    mentions = [
        {"text": candidate.get("text"), "type_id": candidate.get("type_id"), "label": candidate.get("label")}
        for candidate in (resolved.get("candidates") or [])[:6]
    ]
    suggestion: Dict[str, Any] = {
        "ontology": {"id": target, "name": doc["ontology"]["name"]},
        "backend": {"kind": chosen["kind"], "provider": chosen.get("provider"), "model": chosen.get("model")},
        "entities": mentions,
        "sources": [{"id": item["id"], "label": item.get("label")} for item in doc.get("sources") or []],
        "metadata": {},
        "notes": [],
    }
    if chosen["kind"] == "cloud":
        prompt = (
            "Analisa o texto e devolve APENAS JSON com:\n"
            '{"metadata": {"chave": "valor"}, "object_types": ["ids sugeridos"], "link_types": ["ids sugeridos"], "notes": ["..."]}\n'
            "Metadados úteis: setor, geografia, período, entidades mencionadas, tema, confiança.\n\n"
            f"Ontologia: {doc['ontology']['name']}\n"
            f"Tipos disponíveis: {', '.join(item['id'] for item in doc['object_types'])}\n"
            f"Texto:\n{text[:6000]}"
        )
        try:
            raw = await ai.ask_model(chosen, system=ai.SYSTEM_DESIGN, prompt=prompt, max_tokens=1200)
            parsed = ai.extract_json(raw) or {}
            suggestion["metadata"] = parsed.get("metadata") or {}
            suggestion["suggested_object_types"] = parsed.get("object_types") or []
            suggestion["suggested_link_types"] = parsed.get("link_types") or []
            suggestion["notes"].extend(parsed.get("notes") or [])
        except Exception as exc:
            suggestion["notes"].append(f"IA indisponível ({exc}); devolvidas as entidades reconhecidas pelos dados.")
    else:
        suggestion["notes"].append("Sem modelo configurado: devolvidas as entidades reconhecidas pelos dados reais.")
    return suggestion
