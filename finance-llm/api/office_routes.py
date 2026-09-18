"""Rotas do Office IQ OS (`/office/*`).

A aplicação de leitura e escrita de conteúdos da plataforma: documentos em
Markdown (notas, dossiês, relatórios, atas, páginas) com pastas, etiquetas,
pesquisa, duplicação, exportação (.md/.html) e importação dos **dossiês 360**
guardados.

- `GET  /office/documents`            — lista (pasta, pesquisa, tipo, etiqueta)
- `POST /office/documents`            — criar/alterar (requer sessão)
- `GET  /office/documents/{id}`       — documento completo
- `PATCH /office/documents/{id}`      — alteração parcial (título, pasta, etiquetas, fixar)
- `DELETE /office/documents/{id}`     — apagar
- `POST /office/documents/{id}/duplicate`
- `GET  /office/documents/{id}/export?format=md|html`
- `POST /office/documents/from-dossier/{dossier_id}` — traz um dossiê 360 para edição
- `GET|POST|PATCH|DELETE /office/folders…` — pastas
- `GET  /office/stats`                — panorama (documentos, palavras, recentes)
"""
from __future__ import annotations

import logging
from typing import Annotated, Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import Response

from api import office_store as store
from api import search360_store as dossier_store
from api.auth_routes import CurrentSession, optional_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/office", tags=["office"])

Session = Annotated[Optional[CurrentSession], Depends(optional_session)]


def _writer(session: Optional[CurrentSession]) -> CurrentSession:
    if not session:
        raise HTTPException(status_code=401, detail="Entrar na plataforma para escrever documentos.")
    return session


# ------------------------------------------------------------------ leitura
@router.get("/documents")
def list_documents(
    folder_id: Optional[str] = Query(None, description="Filtrar por pasta (`root` para as sem pasta)."),
    q: Optional[str] = Query(None, description="Pesquisa no título, no texto e nas etiquetas."),
    kind: Optional[str] = Query(None),
    tag: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=500),
    content: bool = Query(False, description="Incluir o Markdown de cada documento."),
) -> Dict[str, Any]:
    """Documentos do Office (resumos), com pastas e panorama."""
    folder = None if folder_id in (None, "", "all") else ("__root__" if folder_id == "root" else folder_id)
    payload = store.list_documents(folder_id=folder, query=q, kind=kind, tag=tag, limit=limit, with_content=content)
    if folder == "__root__":
        payload["items"] = [item for item in payload["items"] if not item.get("folder_id")]
        payload["total"] = len(payload["items"])
    return payload


@router.get("/documents/{document_id}")
def get_document(document_id: str) -> Dict[str, Any]:
    """Documento completo (título, Markdown, pasta, etiquetas, origem)."""
    try:
        return {"document": store.get_document(document_id)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/documents/{document_id}/export")
def export_document(document_id: str, format: str = Query("md", pattern="^(md|html)$")) -> Response:
    """Exporta em Markdown (com cabeçalho YAML) ou numa página HTML pronta a imprimir."""
    try:
        document = store.get_document(document_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    content, media_type, filename = store.export_document(document, format)
    return Response(content=content, media_type=media_type, headers={"content-disposition": f'attachment; filename="{filename}"'})


@router.get("/stats")
def stats() -> Dict[str, Any]:
    """Panorama do Office: documentos, pastas, palavras e últimos alterados."""
    return store.stats()


@router.get("/folders")
def list_folders() -> Dict[str, Any]:
    """Pastas do Office com o número de documentos."""
    folders = store.list_folders()
    return {"total": len(folders), "items": folders, "kinds": [{"id": key, "label": label} for key, label in store.KIND_LABELS.items()]}


# ------------------------------------------------------------------ escrita
@router.post("/documents")
def save_document(payload: Dict[str, Any] = Body(...), session: Session = None) -> Dict[str, Any]:
    """Cria ou altera um documento (`title`, `markdown`, `kind`, `folder_id`, `tags`, `template`)."""
    writer = _writer(session)
    try:
        document = store.save_document({**payload, "author": payload.get("author") or writer.user.email}, author=writer.user.email)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"saved": True, "document": document}


@router.patch("/documents/{document_id}")
def patch_document(document_id: str, payload: Dict[str, Any] = Body(...), session: Session = None) -> Dict[str, Any]:
    """Alteração parcial: título, pasta, etiquetas, fixar, arquivar (`markdown` opcional)."""
    _writer(session)
    try:
        store.get_document(document_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    body = dict(payload)
    body["id"] = document_id
    if "folder_id" in body and not body["folder_id"]:
        body["folder_id"] = None
    document = store.save_document(body)
    return {"saved": True, "document": document}


@router.delete("/documents/{document_id}")
def delete_document(document_id: str, session: Session = None) -> Dict[str, Any]:
    """Apaga um documento."""
    _writer(session)
    return store.delete_document(document_id)


@router.post("/documents/{document_id}/duplicate")
def duplicate_document(document_id: str, payload: Dict[str, Any] = Body(default_factory=dict), session: Session = None) -> Dict[str, Any]:
    """Duplica um documento (útil para partir de um modelo já escrito)."""
    _writer(session)
    try:
        document = store.duplicate_document(document_id, title=payload.get("title"))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"duplicated": True, "document": document}


@router.post("/folders")
def save_folder(payload: Dict[str, Any] = Body(...), session: Session = None) -> Dict[str, Any]:
    """Cria ou altera uma pasta."""
    _writer(session)
    try:
        folder = store.save_folder(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"saved": True, "folder": folder}


@router.delete("/folders/{folder_id}")
def delete_folder(folder_id: str, session: Session = None) -> Dict[str, Any]:
    """Apaga uma pasta (os documentos ficam, sem pasta)."""
    _writer(session)
    return store.delete_folder(folder_id)


# ------------------------------------------------------ integração 360
@router.post("/documents/from-dossier/{dossier_id}")
def document_from_dossier(
    dossier_id: str,
    payload: Dict[str, Any] = Body(default_factory=dict),
    session: Session = None,
) -> Dict[str, Any]:
    """Traz um dossiê 360 guardado para o Office, como documento editável.

    Por omissão **atualiza** o documento que já esteja ligado a esse dossiê (o
    dossiê vivo muda, o texto mantém-se na mesma página); com `create_new: true`
    cria sempre um documento novo (para comparar versões).
    """
    writer = _writer(session)
    try:
        dossier = dossier_store.get_dossier(dossier_id, payload.get("ontology"))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    markdown = dossier_store.dossier_markdown(dossier)
    document = store.document_from_dossier(
        dossier,
        markdown,
        author=writer.user.email,
        folder_id=payload.get("folder_id"),
        create_new=bool(payload.get("create_new")),
    )
    # O dossiê é a fonte do título: se por alguma razão vier vazio, não deixar
    # o documento ficar como «Sem título».
    if not str(document.get("title") or "").strip() or document.get("title") == "Sem título":
        fallback = str(dossier.get("title") or "").strip() or f"{str(dossier.get('term') or 'Dossiê').strip()} — dossiê 360"
        document = store.save_document({"id": document["id"], "title": fallback})
    return {"saved": True, "document": document, "dossier": {"id": dossier.get("id"), "title": dossier.get("title"), "term": dossier.get("term")}}


@router.get("/dossiers/available")
def available_dossiers(limit: int = Query(40, ge=1, le=200)) -> Dict[str, Any]:
    """Dossiês 360 guardados disponíveis para trazer para o Office (com o documento ligado, se existir)."""
    dossiers = dossier_store.list_dossiers(limit=limit)
    documents = {str((item.get("source") or {}).get("id")): item.get("id") for item in store.list_documents(limit=500)["items"] if (item.get("source") or {}).get("type") == "dossier360"}
    return {
        "total": dossiers["total"],
        "items": [
            {
                **dossier,
                "document_id": documents.get(str(dossier.get("id"))),
            }
            for dossier in dossiers["items"]
        ],
    }
