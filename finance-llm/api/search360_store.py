"""Persistência da Pesquisa 360: projetos e dossiês guardados.

Um projeto é uma área de trabalho (ex.: «Transição energética») e um dossiê é o
retrato de um tema num momento: a pesquisa, o dossiê, o grafo, os indicadores e a
síntese que o utilizador viu. Guardar um dossiê é portanto guardar **evidência**,
não uma consulta: fica com data, fontes e citações, e pode ser reaberto sem
depender das fontes externas (que mudam) ou atualizado quando se quiser.

Tudo vive no registo da ontologia (`data/ontology/<id>.json`, chaves `projects` e
`dossiers`), pela mesma via da Ontologia — assim o mesmo projeto e a mesma ficha
são visíveis nas duas aplicações, e herdam a persistência atómica já existente.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Sequence

from api import ontology_registry as registry

logger = logging.getLogger(__name__)

MAX_SNAPSHOT_ITEMS = 80
MAX_SNAPSHOT_EVIDENCE = 30
SOURCE_MARK = "search360"


def _ontology(ontology_id: Optional[str]) -> str:
    return registry.normalize_ontology_id(ontology_id) or registry.active_ontology_id()


def _trim_snapshot(topic: Dict[str, Any]) -> Dict[str, Any]:
    """Guarda o dossiê com o essencial (evita ficheiros gigantes)."""
    snapshot = {
        "term": topic.get("term"),
        "plan": topic.get("plan"),
        "items": (topic.get("items") or [])[:MAX_SNAPSHOT_ITEMS],
        "facets": topic.get("facets"),
        "per_source": topic.get("per_source"),
        "stats": topic.get("stats"),
        "warnings": topic.get("warnings") or [],
        "library": topic.get("library"),
        "graph": topic.get("graph"),
        "metrics": topic.get("metrics") or [],
        "generated_at": topic.get("generated_at"),
        "truncated": len(topic.get("items") or []) > MAX_SNAPSHOT_ITEMS,
    }
    synthesis = dict(topic.get("synthesis") or {})
    if synthesis:
        synthesis["evidence"] = (synthesis.get("evidence") or [])[:MAX_SNAPSHOT_EVIDENCE]
        snapshot["synthesis"] = synthesis
    return snapshot


def _summary(dossier: Dict[str, Any]) -> Dict[str, Any]:
    """Versão leve de um dossiê para listagens."""
    snapshot = dossier.get("snapshot") or {}
    synthesis = snapshot.get("synthesis") or {}
    return {
        "id": dossier.get("id"),
        "title": dossier.get("title"),
        "term": dossier.get("term") or snapshot.get("term"),
        "project_id": dossier.get("project_id"),
        "tags": dossier.get("tags") or [],
        "notes": dossier.get("notes"),
        "source": dossier.get("source") or SOURCE_MARK,
        "author": dossier.get("author"),
        "created_at": dossier.get("created_at"),
        "updated_at": dossier.get("updated_at"),
        "saved_at": dossier.get("saved_at") or dossier.get("created_at"),
        "sources": (snapshot.get("stats") or {}).get("sources_queried"),
        "items": (snapshot.get("stats") or {}).get("items"),
        "metrics": len(snapshot.get("metrics") or []),
        "evidence": len(synthesis.get("evidence") or []),
        "synthesis_mode": synthesis.get("mode"),
        "generated_at": snapshot.get("generated_at"),
    }


# --------------------------------------------------------------------------
# Projetos
# --------------------------------------------------------------------------
def list_projects(ontology_id: Optional[str] = None) -> Dict[str, Any]:
    target = _ontology(ontology_id)
    projects = registry.list_projects(target)
    dossiers = registry.list_dossiers(target)
    counts: Dict[str, int] = {}
    for dossier in dossiers:
        key = str(dossier.get("project_id") or "")
        if key:
            counts[key] = counts.get(key, 0) + 1
    items = []
    for project in projects:
        items.append(
            {
                **project,
                "dossier_count": counts.get(str(project.get("id")), 0),
                "kind": project.get("kind") or SOURCE_MARK,
            }
        )
    items.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
    return {
        "ontology": target,
        "total": len(items),
        "items": items,
        "dossiers_total": len(dossiers),
        "dossiers_without_project": len([item for item in dossiers if not item.get("project_id")]),
    }


def save_project(payload: Dict[str, Any], ontology_id: Optional[str] = None) -> Dict[str, Any]:
    target = _ontology(ontology_id)
    body = {
        "id": payload.get("id"),
        "name": str(payload.get("name") or "").strip(),
        "description": payload.get("description"),
        "color": payload.get("color") or "99,102,241",
        "tags": payload.get("tags") or [],
        "kind": SOURCE_MARK,
        "owner": payload.get("owner"),
        "ontology_id": target,
    }
    item = registry.upsert_project(body, target)
    return item


def delete_project(project_id: str, ontology_id: Optional[str] = None) -> Dict[str, Any]:
    target = _ontology(ontology_id)
    dossiers = [item for item in registry.list_dossiers(target) if item.get("project_id") == project_id]
    removed = registry.delete_workspace_item("projects", project_id, target)
    return {"removed": removed, "id": project_id, "dossiers_kept": len(dossiers)}


# --------------------------------------------------------------------------
# Dossiês
# --------------------------------------------------------------------------
def list_dossiers(
    *,
    project_id: Optional[str] = None,
    term: Optional[str] = None,
    limit: int = 60,
    ontology_id: Optional[str] = None,
) -> Dict[str, Any]:
    target = _ontology(ontology_id)
    items = registry.list_dossiers(target)
    if project_id:
        items = [item for item in items if item.get("project_id") == project_id]
    if term:
        needle = term.strip().lower()
        items = [
            item
            for item in items
            if needle in str(item.get("term") or "").lower() or needle in str(item.get("title") or "").lower()
        ]
    items.sort(key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""), reverse=True)
    return {"ontology": target, "total": len(items), "items": [_summary(item) for item in items[:limit]]}


def get_dossier(dossier_id: str, ontology_id: Optional[str] = None) -> Dict[str, Any]:
    target = _ontology(ontology_id)
    return registry.get_workspace_item("dossiers", dossier_id, target)


def delete_dossier(dossier_id: str, ontology_id: Optional[str] = None) -> Dict[str, Any]:
    target = _ontology(ontology_id)
    removed = registry.delete_workspace_item("dossiers", dossier_id, target)
    return {"removed": removed, "id": dossier_id}


def save_dossier(
    payload: Dict[str, Any],
    *,
    topic: Optional[Dict[str, Any]] = None,
    ontology_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Guarda (ou atualiza) um dossiê a partir do dossiê que está no ecrã.

    `topic` é o dossiê devolvido por `/search360/topic`; se vier vazio, é preciso
    `payload.snapshot` (já guardado antes).
    """
    target = _ontology(ontology_id)
    term = str(payload.get("term") or (topic or {}).get("term") or "").strip()
    title = str(payload.get("title") or "").strip() or (f"{term} — dossiê 360" if term else "Dossiê 360")
    snapshot = _trim_snapshot(topic) if topic else (payload.get("snapshot") or {})
    if not snapshot:
        raise ValueError("Nada para guardar: construa o dossiê 360 primeiro (ou envie um snapshot).")
    body: Dict[str, Any] = {
        "id": payload.get("id"),
        "title": title,
        "term": term or snapshot.get("term"),
        "project_id": payload.get("project_id") or payload.get("project"),
        "tags": [str(tag) for tag in (payload.get("tags") or []) if str(tag).strip()],
        "notes": payload.get("notes"),
        "source": SOURCE_MARK,
        "author": payload.get("author"),
        "scope_term": term or snapshot.get("term"),
        "snapshot": snapshot,
        "saved_at": registry._now(),
        "sources": (snapshot.get("per_source") or []),
        "ontology_id": target,
    }
    item = registry.upsert_dossier(body, target)
    return {"saved": True, "dossier": item, "summary": _summary(item)}


def rename_dossier(dossier_id: str, payload: Dict[str, Any], ontology_id: Optional[str] = None) -> Dict[str, Any]:
    target = _ontology(ontology_id)
    current = registry.get_workspace_item("dossiers", dossier_id, target)
    body = dict(current)
    for key in ("title", "notes", "tags"):
        if key in payload and payload[key] is not None:
            body[key] = payload[key]
    # O projeto pode ser explicitamente removido (`null`) para o dossiê ficar solto.
    clear: List[str] = []
    if "project_id" in payload:
        if payload["project_id"]:
            body["project_id"] = payload["project_id"]
        else:
            clear.append("project_id")
    if payload.get("project"):
        body["project_id"] = payload["project"]
    item = registry.upsert_dossier(body, target, clear=tuple(clear))
    return {"saved": True, "dossier": item, "summary": _summary(item)}


def refresh_dossier(
    dossier_id: str,
    *,
    topic: Dict[str, Any],
    keep_title: bool = True,
    ontology_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Atualiza o retrato de um dossiê guardado com uma nova pesquisa."""
    target = _ontology(ontology_id)
    current = registry.get_workspace_item("dossiers", dossier_id, target)
    body = dict(current)
    previous = (current.get("snapshot") or {}).get("generated_at")
    body["snapshot"] = _trim_snapshot(topic)
    body["term"] = topic.get("term") or body.get("term")
    body["sources"] = (topic.get("per_source") or [])
    history = list(current.get("history") or [])
    if previous:
        history.append({"generated_at": previous, "items": (current.get("snapshot") or {}).get("stats", {}).get("items")})
    body["history"] = history[-10:]
    body["saved_at"] = registry._now()
    if not keep_title:
        body["title"] = f"{body['term']} — dossiê 360"
    item = registry.upsert_dossier(body, target)
    return {"updated": True, "dossier": item, "summary": _summary(item), "previous_generated_at": previous}


# --------------------------------------------------------------------------
# Exportação
# --------------------------------------------------------------------------
def dossier_markdown(dossier: Dict[str, Any]) -> str:
    """Exporta um dossiê guardado em Markdown, com as fontes e as citações."""
    snapshot = dossier.get("snapshot") or {}
    synthesis = snapshot.get("synthesis") or {}
    lines: List[str] = []
    lines.append(f"# {dossier.get('title') or 'Dossiê 360'}")
    lines.append("")
    meta = [
        f"**Tema:** {dossier.get('term') or snapshot.get('term') or '—'}",
        f"**Gerado em:** {snapshot.get('generated_at') or '—'}",
        f"**Guardado em:** {dossier.get('saved_at') or dossier.get('created_at') or '—'}",
        f"**Fontes consultadas:** {(snapshot.get('stats') or {}).get('sources_queried', '—')}",
        f"**Itens:** {(snapshot.get('stats') or {}).get('items', '—')}",
    ]
    if dossier.get("tags"):
        meta.append(f"**Etiquetas:** {', '.join(str(tag) for tag in dossier['tags'])}")
    lines.extend(meta)
    lines.append("")
    if dossier.get("notes"):
        lines.append("## Notas")
        lines.append("")
        lines.append(str(dossier["notes"]))
        lines.append("")
    if synthesis.get("text"):
        lines.append("## Síntese")
        lines.append("")
        lines.append(str(synthesis["text"]))
        lines.append("")
        evidence = synthesis.get("evidence") or []
        if evidence:
            lines.append("### Evidências citadas")
            lines.append("")
            for entry in evidence:
                url = f" — {entry['url']}" if entry.get("url") else ""
                lines.append(f"{entry.get('n')}. **{entry.get('title')}** ({entry.get('source')}){url}")
            lines.append("")
    metrics = snapshot.get("metrics") or []
    if metrics:
        lines.append("## Indicadores")
        lines.append("")
        lines.append("| Indicador | País | Primeiro | Último | Variação |")
        lines.append("| --- | --- | --- | --- | --- |")
        for metric in metrics:
            first = metric.get("first") or {}
            last = metric.get("last") or {}
            change = metric.get("change")
            lines.append(
                f"| {metric.get('label')} | {metric.get('country')} | {first.get('value')} ({first.get('year')}) | "
                f"{last.get('value')} ({last.get('year')}) | {change} |"
            )
        lines.append("")
    lines.append("## O que cada fonte deu")
    lines.append("")
    lines.append("| Fonte | Itens | Tempo (ms) | Estado |")
    lines.append("| --- | --- | --- | --- |")
    for row in snapshot.get("per_source") or []:
        lines.append(f"| {row.get('label')} | {row.get('items')} | {row.get('ms')} | {'ok' if row.get('ok') else 'falhou'} |")
    lines.append("")
    items = snapshot.get("items") or []
    if items:
        lines.append("## Resultados")
        lines.append("")
        for entry in items:
            url = f" — {entry['url']}" if entry.get("url") else ""
            date = f" ({entry['date']})" if entry.get("date") else ""
            lines.append(f"- **{entry.get('title')}** · {entry.get('source_label')} · {entry.get('kind')}{date}{url}")
            if entry.get("snippet"):
                lines.append(f"  {entry['snippet']}")
        lines.append("")
    if snapshot.get("warnings"):
        lines.append("## Avisos")
        lines.append("")
        for warning in snapshot["warnings"]:
            lines.append(f"- {warning}")
        lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("Gerado pelo IQ OS · Pesquisa 360 (metamodelo de analítica).")
    return "\n".join(lines)


def dossier_json(dossier: Dict[str, Any]) -> str:
    return json.dumps(dossier, ensure_ascii=False, indent=2, default=str)


def families_summary(dossiers: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Contagens rápidas para o painel de projetos."""
    tags: Dict[str, int] = {}
    for dossier in dossiers:
        for tag in dossier.get("tags") or []:
            tags[str(tag)] = tags.get(str(tag), 0) + 1
    return {
        "dossiers": len(dossiers),
        "with_project": len([item for item in dossiers if item.get("project_id")]),
        "tags": [{"value": key, "count": value} for key, value in sorted(tags.items(), key=lambda pair: -pair[1])[:12]],
    }
