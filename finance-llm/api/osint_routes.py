"""Rotas do módulo OSINT (`/osint/*`) — pesquisa de usernames/emails.

Integra o ``user-scanner`` (kaifcodec/user-scanner) para verificar a
existência de perfis numa plataforma. Os resultados são guardados no
Elasticsearch no índice ``finance_osint`` e podem ser consultados/grafo.

Leitura (sessão)
- ``GET    /osint/categories``      — categorias disponíveis
- ``POST   /osint/search``          — pesquisar scans guardados
- ``GET    /osint/saved/{doc_id}``  — detalhe completo de um scan guardado
- ``GET    /osint/graph/{doc_id}``  — devolver grafo de um scan guardado
- ``GET    /osint/report/{doc_id}`` — exportar (json, csv ou pdf)

Escrita (sessão)
- ``POST   /osint/scan``            — executar scan e guardar resultado
"""
from __future__ import annotations

import csv
import io
import json
import logging
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response
from fastapi.responses import StreamingResponse

from api.auth_routes import CurrentSession, require_session
from api.models import (
    OsintGraph,
    OsintPivot,
    OsintProfileHit,
    OsintScanRequest,
    OsintScanResponse,
    OsintSearchRequest,
    OsintSearchResponse,
    OsintStats,
)
from api.osint_service import (
    DEFAULT_CATEGORY,
    delete_saved_scan,
    get_saved_scan,
    save_scan,
    scan_target,
    scan_to_csv,
    scan_to_pdf,
    search_saved_scans,
)
from user_scanner.core import engine as us_engine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/osint", tags=["osint"])

Session = Annotated[CurrentSession, Depends(require_session)]


@router.get("/categories")
async def list_osint_categories(session: Session) -> Dict[str, Any]:
    """Categorias de username/email do user-scanner e qual é a usada por defeito.

    O UI usa `defaults` para rotular/ordenar a escolha, para não mostrar uma
    categoria que não existe (era o caso de `global` no tipo email).
    """
    username_categories = list(us_engine.load_categories(is_email=False).keys())
    email_categories = list(us_engine.load_categories(is_email=True).keys())
    defaults = {
        kind: value if value in cats else (cats[0] if cats else None)
        for kind, (value, cats) in {
            "username": (DEFAULT_CATEGORY.get("username"), username_categories),
            "email": (DEFAULT_CATEGORY.get("email"), email_categories),
        }.items()
    }
    return {
        "username": username_categories,
        "email": email_categories,
        "defaults": defaults,
    }


@router.post("/scan")
async def osint_scan(payload: OsintScanRequest, session: Session) -> OsintScanResponse:
    """Executa um scan e, por defeito, guarda o resultado em ``finance_osint``."""
    try:
        result = await scan_target(
            target=payload.target,
            kind=payload.kind,
            category=payload.category,
            full_scan=payload.full_scan,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.warning("Erro no scan OSINT %s (%s): %s", payload.target, payload.kind, exc)
        raise HTTPException(status_code=502, detail=f"Erro no motor OSINT: {exc}") from exc

    saved = {"saved": False}
    if payload.save:
        saved = save_scan(result)

    return OsintScanResponse(
        target=result["target"],
        kind=result["kind"],
        total=result["total"],
        found=result["found"],
        not_found=result["not_found"],
        errors=result["errors"],
        duration_s=result["duration_s"],
        category=result["category"],
        hits=[OsintProfileHit(**h) for h in result["hits"]],
        pivots=[OsintPivot(**p) for p in result.get("pivots", [])],
        stats=OsintStats(**result.get("stats", {})),
        graph=OsintGraph(**result["graph"]),
        saved=saved.get("saved", False),
        saved_id=saved.get("saved_id"),
        error=saved.get("error"),
    )


@router.post("/search")
async def osint_search(payload: OsintSearchRequest, session: Session) -> OsintSearchResponse:
    """Pesquisa scans guardados no índice finance_osint."""
    data = search_saved_scans(
        q=payload.q,
        kind=payload.kind,
        size=payload.size,
        from_=payload.from_,
    )
    return OsintSearchResponse(
        total=data.get("total", 0),
        items=data.get("items", []),
        from_=data.get("from_", 0),
        size=data.get("size", payload.size),
        error=data.get("error"),
    )


@router.get("/graph/{doc_id}")
async def osint_graph(doc_id: str, session: Session) -> OsintGraph:
    """Devolve o grafo de um scan guardado."""
    doc = get_saved_scan(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Scan não encontrado")
    graph = doc.get("graph") or {"nodes": [], "edges": []}
    return OsintGraph(**graph)


@router.get("/saved/{doc_id}")
async def osint_saved_detail(doc_id: str, session: Session) -> Dict[str, Any]:
    """Detalhe completo de um scan guardado (perfis, pistas, contas cruzadas)."""
    doc = get_saved_scan(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Scan não encontrado")
    return doc


@router.get("/report/{doc_id}")
async def osint_report(
    doc_id: str,
    session: Session,
    format: str = Query("json", pattern="^(json|csv|pdf)$", description="Formato do relatório"),
) -> Response:
    """Exporta o scan guardado em JSON, CSV (abre no Excel) ou PDF."""
    doc = get_saved_scan(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Scan não encontrado")

    target = str(doc.get("target") or "alvo").replace("@", "_at_")
    stem = f"osint-{doc.get('kind') or 'scan'}-{target}"

    if format == "csv":
        return Response(
            content=scan_to_csv(doc),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{stem}.csv"'},
        )

    if format == "pdf":
        pdf = scan_to_pdf(doc)
        if pdf is None:
            raise HTTPException(
                status_code=503,
                detail="Geração de PDF indisponível (falta o extra do user-scanner).",
            )
        return Response(
            content=pdf,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{stem}.pdf"'},
        )

    payload = json.dumps(doc, ensure_ascii=False, indent=2)
    return Response(
        content=payload,
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{stem}.json"'},
    )


@router.delete("/saved/{doc_id}")
async def osint_delete_saved(doc_id: str, session: Session) -> Dict[str, Any]:
    """Apaga um scan guardado."""
    result = delete_saved_scan(doc_id)
    if not result.get("deleted"):
        raise HTTPException(status_code=400, detail=result.get("error") or "Falha ao apagar")
    return result
