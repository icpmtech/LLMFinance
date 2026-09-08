"""Endpoints FastAPI para RAG: upload de PDFs, chat, documentos e explicação."""
import json
from pathlib import Path
from typing import List

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse

from api.models import (
    RagChatRequest,
    RagChatResponse,
    RagDocument,
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
        return UploadPdfResponse(
            doc_id=entry.doc_id,
            title=entry.title,
            filename=entry.filename,
            pages=entry.pages,
            indexed=entry.indexed,
            message="Documento já existia; não foi re-ingerido.",
        )

    use_markitdown = converter in ("auto", "markitdown")
    md_meta = convert_pdf_to_markdown(
        pdf_path,
        MARKDOWN_DIR,
        title=file.filename[:-4],
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
    docs = engine.list_documents()
    return RagDocumentsResponse(
        documents=[
            RagDocument(
                doc_id=d["doc_id"],
                title=d["title"],
                filename=d["filename"],
                pages=d["pages"],
                indexed=d["indexed"],
            )
            for d in docs
        ]
    )


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
def rag_chat(req: RagChatRequest):
    """Responde a uma pergunta usando o RAG com contexto dos documentos."""
    engine = get_rag_engine()
    result = engine.answer(
        req.question,
        top_k=req.top_k,
        max_new_tokens=req.max_new_tokens,
        temperature=req.temperature,
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
def rag_chat_stream(req: RagChatRequest):
    """Responde via SSE com as sources primeiro e depois os tokens gerados."""
    engine = get_rag_engine()

    def event_stream():
        sources_sent = False
        for event in engine.stream_answer(
            req.question,
            top_k=req.top_k,
            max_new_tokens=req.max_new_tokens,
            temperature=req.temperature,
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
def explain_rag_answer(req: RagChatRequest):
    """Explica como a resposta RAG foi construída."""
    engine = get_rag_engine()
    result = engine.answer(
        req.question,
        top_k=req.top_k,
        max_new_tokens=req.max_new_tokens,
        temperature=req.temperature,
    )
    explanation = explain_prediction(
        req.question,
        result["answer"],
        result["sources"],
        model_name=result.get("model_used"),
    )
    return RagExplainResponse(**explanation)
