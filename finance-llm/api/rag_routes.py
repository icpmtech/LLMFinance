"""Endpoints FastAPI para RAG: upload de PDFs, chat, documentos e explicação."""
import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import List

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse

from api.models import (
    RagChatRequest,
    RagChatResponse,
    RagDocument,
    RagDocumentGraphEdge,
    RagDocumentGraphNode,
    RagDocumentGraphResponse,
    RagDocumentUpdate,
    RagDocumentsResponse,
    RagExplainResponse,
    RagSource,
    UploadPdfResponse,
)
from api.rag_service import get_rag_engine, reset_rag_engine
from rag.chat.explain_predictions import explain_prediction
from rag.ingestion.chunker import chunk_markdown, save_chunks
from rag.ingestion.pdf_to_markdown import convert_pdf_to_markdown
from rag.paths import MARKDOWN_DIR, UPLOADS_DIR
from rag.storage.document_store import DocumentEntry

router = APIRouter(prefix="/rag", tags=["rag"])

# Executor para operações de ingestão pesadas (PDF → Markdown, chunks, embeddings, grafo)
_ingest_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="rag_ingest_")

# Cache simples para grafos: (doc_id, updated_at, top_k) -> dict
_graph_cache: dict[str, tuple[float, int, dict]] = {}


@router.post("/upload", response_model=UploadPdfResponse)
async def upload_pdf(
    file: UploadFile = File(...),
    converter: str = Query("auto", pattern="^(auto|markitdown|pymupdf)$"),
):
    """Recebe um PDF, converte para Markdown, cria chunks e indexa no vector store.

    Args:
        file: ficheiro PDF a ingerir.
        converter: conversor a usar. `auto` tenta markitdown primeiro e recai para PyMuPDF.
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Apenas ficheiros PDF são aceites.")

    pdf_path = UPLOADS_DIR / file.filename
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    content = await file.read()
    pdf_path.write_bytes(content)

    engine = get_rag_engine()
    existing_id = engine.document_store.exists(hashlib_sha256(content))
    if existing_id:
        entry = engine.document_store.get(existing_id)
        engine.document_store.add_history(existing_id, "upload", "tentativa duplicada")
        return UploadPdfResponse(
            doc_id=entry.doc_id,
            title=entry.title,
            filename=entry.filename,
            pages=entry.pages,
            indexed=entry.indexed,
            message="Documento já existia; não foi re-ingerido.",
        )

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        _ingest_executor, _ingest_pdf, pdf_path, content, engine, converter
    )


def _ingest_pdf(pdf_path: Path, content: bytes, engine, converter: str) -> UploadPdfResponse:
    use_markitdown = converter in ("auto", "markitdown")
    md_meta = convert_pdf_to_markdown(
        pdf_path,
        MARKDOWN_DIR,
        title=pdf_path.stem,
        use_markitdown=use_markitdown,
    )
    md_path = Path(md_meta["md_path"])
    chunks = chunk_markdown(
        md_path,
        doc_id=md_meta["id"],
        doc_title=md_meta["title"],
    )
    chunk_file = md_path.parent / f"{md_meta['id']}_chunks.jsonl"
    save_chunks(chunks, chunk_file)

    extra = {"converter": converter}
    engine.document_store.add(
        DocumentEntry(
            doc_id=md_meta["id"],
            title=md_meta["title"],
            filename=md_meta["filename"],
            pages=md_meta["pages"],
            size_bytes=md_meta["size_bytes"],
            hash=md_meta["hash"],
            md_path=md_meta["md_path"],
            chunk_file=str(chunk_file),
            indexed=True,
            converter=converter,
            extra=extra,
        )
    )

    engine.vector_store.add(
        [
            {
                "chunk_id": c.chunk_id,
                "doc_id": c.doc_id,
                "doc_title": c.doc_title,
                "page": c.page,
                "text": c.text,
            }
            for c in chunks
        ]
    )
    engine.document_store.set_indexed(md_meta["id"], True)
    engine.document_store.add_history(md_meta["id"], "ingest", f"converter={converter}")

    return UploadPdfResponse(
        doc_id=md_meta["id"],
        title=md_meta["title"],
        filename=md_meta["filename"],
        pages=md_meta["pages"],
        indexed=True,
        message="PDF ingerido, convertido para Markdown e indexado com sucesso.",
    )


def hashlib_sha256(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


@router.get("/documents", response_model=RagDocumentsResponse)
def list_documents():
    """Lista os documentos PDF/Markdown disponíveis para o RAG."""
    engine = get_rag_engine()
    docs = engine.document_store.list()
    return RagDocumentsResponse(
        documents=[
            RagDocument(
                doc_id=d.doc_id,
                title=d.title,
                filename=d.filename,
                pages=d.pages,
                indexed=d.indexed,
                size_bytes=d.size_bytes,
                created_at=d.created_at,
                updated_at=d.updated_at,
                converter=d.converter,
            )
            for d in docs
        ]
    )


@router.get("/documents/{doc_id}", response_model=RagDocument)
def get_document(doc_id: str):
    """Devolve os detalhes de um documento indexado."""
    engine = get_rag_engine()
    entry = engine.document_store.get(doc_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Documento não encontrado.")
    return RagDocument(
        doc_id=entry.doc_id,
        title=entry.title,
        filename=entry.filename,
        pages=entry.pages,
        indexed=entry.indexed,
        size_bytes=entry.size_bytes,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
        converter=entry.converter,
    )


@router.get("/documents/{doc_id}/history")
def document_history(doc_id: str):
    """Devolve o histórico de ações (upload, ingest, update, reprocess, delete) de um documento."""
    engine = get_rag_engine()
    entry = engine.document_store.get(doc_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Documento não encontrado.")
    history = engine.document_store.get_history(doc_id)
    return {"doc_id": doc_id, "history": history}


@router.patch("/documents/{doc_id}", response_model=RagDocument)
def update_document(doc_id: str, payload: RagDocumentUpdate):
    """Edita o título de um documento indexado."""
    engine = get_rag_engine()
    updated = engine.document_store.update(doc_id, payload.title)
    if not updated:
        raise HTTPException(status_code=404, detail="Documento não encontrado.")
    engine.document_store.add_history(doc_id, "update", f"title={payload.title}")
    return RagDocument(
        doc_id=updated.doc_id,
        title=updated.title,
        filename=updated.filename,
        pages=updated.pages,
        indexed=updated.indexed,
        size_bytes=updated.size_bytes,
        created_at=updated.created_at,
        updated_at=updated.updated_at,
        converter=updated.converter,
    )


@router.post("/documents/{doc_id}/reprocess", response_model=UploadPdfResponse)
async def reprocess_document(
    doc_id: str,
    converter: str = Query("auto", pattern="^(auto|markitdown|pymupdf)$"),
):
    """Reprocessa um documento já carregado, regenerando Markdown, chunks e embeddings."""
    engine = get_rag_engine()
    entry = engine.document_store.get(doc_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Documento não encontrado.")

    pdf_path = UPLOADS_DIR / entry.filename
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="Ficheiro PDF original não encontrado.")

    # remover embeddings antigos
    engine.vector_store.delete_by_doc_id(doc_id)
    # limpar ficheiros antigos
    old_md = Path(entry.md_path)
    if old_md.exists():
        old_md.unlink()
    old_chunks = Path(entry.chunk_file)
    if old_chunks.exists():
        old_chunks.unlink()
    # remover entrada para permitir nova ingestão
    engine.document_store._docs.pop(doc_id, None)
    engine.document_store._save()

    content = pdf_path.read_bytes()
    loop = asyncio.get_running_loop()
    resp = await loop.run_in_executor(
        _ingest_executor, _ingest_pdf, pdf_path, content, engine, converter
    )
    engine.document_store.add_history(resp.doc_id, "reprocess", f"converter={converter}")
    return resp


@router.delete("/documents/{doc_id}")
def delete_document(doc_id: str):
    """Remove um documento, os seus chunks e os seus embeddings."""
    engine = get_rag_engine()
    engine.vector_store.delete_by_doc_id(doc_id)
    ok = engine.document_store.delete(doc_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Documento não encontrado.")
    return {"status": "ok", "doc_id": doc_id}


@router.post("/chat", response_model=RagChatResponse)
async def rag_chat(req: RagChatRequest):
    """Responde a uma pergunta usando o RAG com contexto dos documentos."""
    engine = get_rag_engine()
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None,
        engine.answer,
        req.question,
        req.top_k,
        req.max_new_tokens,
        req.temperature,
        True,
        req.doc_id,
    )
    return RagChatResponse(
        answer=result["answer"],
        model_used=result.get("model_used"),
        sources=[
            RagSource(
                chunk_id=s.get("chunk_id", ""),
                doc_id=s.get("doc_id", ""),
                doc_title=s.get("doc_title", ""),
                page=s.get("page"),
                text=s.get("text", ""),
                score=s.get("score"),
            )
            for s in result["sources"]
        ],
    )


@router.post("/chat/stream")
async def rag_chat_stream(req: RagChatRequest):
    """Responde via SSE com as sources primeiro e depois os tokens gerados."""
    engine = get_rag_engine()

    def event_stream():
        sources_sent = False
        for event in engine.stream_answer(
            req.question,
            top_k=req.top_k,
            max_new_tokens=req.max_new_tokens,
            temperature=req.temperature,
            doc_id=req.doc_id,
        ):
            if event["type"] == "sources":
                sources_sent = True
                yield f"event: sources\ndata: {json.dumps(event['sources'], ensure_ascii=False)}\n\n"
            else:
                if not sources_sent:
                    sources_sent = True
                    yield f"event: sources\ndata: {json.dumps([], ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'token': event['token']}, ensure_ascii=False)}\n\n"
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
    )


@router.post("/explain", response_model=RagExplainResponse)
async def explain_rag_answer(req: RagChatRequest):
    """Explica como a resposta RAG foi construída."""
    engine = get_rag_engine()
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None,
        engine.answer,
        req.question,
        req.top_k,
        req.max_new_tokens,
        req.temperature,
        True,
        req.doc_id,
    )
    explanation = explain_prediction(
        req.question,
        result["answer"],
        result["sources"],
        model_name=result.get("model_used"),
    )
    return RagExplainResponse(**explanation)


def _build_document_graph(doc_id: str, top_k: int = 5):
    """Devolve um grafo de chunks do documento ligados por similaridade."""
    engine = get_rag_engine()
    entry = engine.document_store.get(doc_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Documento não encontrado.")

    chunks = [c for c in engine.vector_store._chunks if c.get("doc_id") == doc_id]
    if not chunks:
        return {"doc_id": doc_id, "title": entry.title, "nodes": [], "edges": []}

    import numpy as np

    embeddings = engine.vector_store.model.encode(
        [c["text"] for c in chunks],
        convert_to_numpy=True,
        normalize_embeddings=True,
    )
    sim_matrix = np.matmul(embeddings, embeddings.T)
    n = len(chunks)

    node_dicts = [
        {
            "id": c.get("chunk_id", f"{doc_id}_chunk_{i}"),
            "doc_id": doc_id,
            "page": c.get("page"),
            "text_preview": c.get("text", "")[:180].replace("\n", " "),
            "section": c.get("metadata", {}).get("section") if isinstance(c.get("metadata"), dict) else None,
            "chunk_index": i,
        }
        for i, c in enumerate(chunks)
    ]

    edge_dicts = []
    for i in range(n):
        ranked = sorted(
            [(j, float(sim_matrix[i][j])) for j in range(n) if j != i],
            key=lambda x: x[1],
            reverse=True,
        )[:top_k]
        for j, weight in ranked:
            # Evita duplicatas simétricas mantendo apenas i < j com peso > threshold.
            if i < j and weight > 0.55:
                edge_dicts.append({"source": node_dicts[i]["id"], "target": node_dicts[j]["id"], "weight": weight})

    return {"doc_id": doc_id, "title": entry.title, "nodes": node_dicts, "edges": edge_dicts}


@router.get("/documents/{doc_id}/graph", response_model=RagDocumentGraphResponse)
async def get_document_graph(doc_id: str, top_k: int = Query(5, ge=1, le=20)):
    """Devolve um grafo de chunks do documento ligados por similaridade (async, cache)."""
    engine = get_rag_engine()
    entry = engine.document_store.get(doc_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Documento não encontrado.")

    cache_key = f"{doc_id}:{top_k}"
    cached = _graph_cache.get(cache_key)
    if cached and cached[0] == getattr(entry, "updated_at", 0) and cached[1] == top_k:
        return RagDocumentGraphResponse(**cached[2])

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        _ingest_executor,
        lambda: _build_document_graph(doc_id, top_k),
    )
    _graph_cache[cache_key] = (getattr(entry, "updated_at", 0), top_k, result)
    return RagDocumentGraphResponse(**result)
