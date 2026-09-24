"""Rotas da análise de sentimento (`/sentiment/*`).

- `GET  /sentiment/meta`            — motores disponíveis (léxico/neuronal) e integrações
- `POST /sentiment/analyze`         — analisar um texto livre
- `POST /sentiment/corpus`          — analisar um corpus (recolha, notícias, dossiê ou documento Office)
- `POST /sentiment/save/dossier`    — guardar a análise num dossiê de análise (Pesquisa 360)
- `POST /sentiment/save/office`     — criar/atualizar um documento no editor Office

Analisar é leitura (público). Guardar exige sessão — o dossiê e o Office são
espaços de trabalho do utilizador.
"""
from __future__ import annotations

import logging
from typing import Annotated, Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field

from api import sentiment_service as sentiment
from api.auth_routes import CurrentSession, optional_session, require_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sentiment", tags=["sentiment"])

Session = Annotated[Optional[CurrentSession], Depends(optional_session)]
Writer = Annotated[CurrentSession, Depends(require_session)]


def _scope(session: Optional[CurrentSession]) -> Optional[Dict[str, Any]]:
    """Âmbito de visibilidade (o CRM e o email são privados por utilizador)."""
    if not session:
        return None
    return {
        "user_id": session.user.id,
        "email": session.user.email,
        "see_all": (session.user.role or "member") == "admin",
    }


class AnalyzePayload(BaseModel):
    text: str = Field(..., min_length=1, description="Texto a analisar.")
    title: Optional[str] = None
    engine: str = Field("lexicon", description="lexicon | neural | auto")
    model: Optional[str] = None


class CorpusPayload(BaseModel):
    origin: str = Field(
        "scraped",
        description="scraped | news | contracts | firmas | trademarks | rag | dossier | office | crm | email | text",
    )
    q: Optional[str] = None
    source_id: Optional[str] = None
    dossier_id: Optional[str] = None
    document_id: Optional[str] = None
    account_id: Optional[str] = None
    folder: str = Field("INBOX", description="Pasta de email (INBOX, …)")
    limit: int = Field(60, ge=1, le=200)
    engine: str = Field("lexicon", description="lexicon | neural | auto")
    model: Optional[str] = None
    title: Optional[str] = None
    term: Optional[str] = None
    ontology: Optional[str] = None


class SaveDossierPayload(CorpusPayload):
    dossier_id: str


class SaveOfficePayload(BaseModel):
    title: str
    analysis: Optional[Dict[str, Any]] = None
    corpus: Optional[CorpusPayload] = None
    folder_id: Optional[str] = None
    tags: Optional[list] = None
    dossier_id: Optional[str] = None


def _corpus(payload: CorpusPayload, session: Optional[CurrentSession]) -> list:
    """Resolve o corpus a analisar conforme a fonte pedida."""
    origin = (payload.origin or "scraped").strip().lower()
    limit = payload.limit
    if origin == "scraped":
        return sentiment.corpus_from_scraped(q=payload.q, source_id=payload.source_id, limit=limit)
    if origin == "social":
        return sentiment.corpus_from_social(q=payload.q, channel_id=payload.source_id, limit=limit)
    if origin == "news":
        return sentiment.corpus_from_news(q=payload.q, limit=limit)
    if origin == "contracts":
        return sentiment.corpus_from_contracts(q=payload.q, limit=limit)
    if origin == "firmas":
        return sentiment.corpus_from_firmas(q=payload.q, limit=limit)
    if origin == "trademarks":
        return sentiment.corpus_from_trademarks(q=payload.q, limit=limit)
    if origin == "rag":
        return sentiment.corpus_from_rag(limit=limit)
    if origin == "dossier":
        if not payload.dossier_id:
            raise HTTPException(status_code=422, detail="Indique `dossier_id` para analisar um dossiê.")
        return sentiment.corpus_from_dossier(payload.dossier_id, payload.ontology)
    if origin == "office":
        if not payload.document_id:
            raise HTTPException(status_code=422, detail="Indique `document_id` para analisar um documento do Office.")
        return sentiment.corpus_from_office(payload.document_id)
    if origin == "crm":
        if not session:
            raise HTTPException(status_code=401, detail="O CRM exige sessão iniciada (é privado por utilizador).")
        return sentiment.corpus_from_crm(_scope(session) or {}, q=payload.q, limit=limit)
    if origin == "email":
        if not session:
            raise HTTPException(status_code=401, detail="O email exige sessão iniciada.")
        if not payload.account_id:
            raise HTTPException(status_code=422, detail="Escolha a conta de email (`account_id`).")
        return sentiment.corpus_from_email(session.user.id, payload.account_id, folder=payload.folder, limit=limit)
    raise HTTPException(status_code=422, detail=f"Origem desconhecida: {origin}")


def _describe(payload: CorpusPayload, documents: list) -> str:
    if payload.title:
        return payload.title
    origin = (payload.origin or "scraped").strip().lower()
    label = next((entry["label"] for entry in sentiment.ORIGINS if entry["id"] == origin), origin)
    detail = payload.q or payload.source_id or payload.dossier_id or payload.document_id or payload.account_id or ""
    return f"Análise de sentimento — {label}{f' · {detail}' if detail else ''}"


@router.get("/sources")
def sentiment_sources(session: Session = None) -> Dict[str, Any]:
    """Fontes do sistema disponíveis para análise, com quantos documentos têm."""
    scope = _scope(session)
    return sentiment.available_sources(scope, owner=session.user.id if session else None)


@router.get("/meta")
def sentiment_meta() -> Dict[str, Any]:
    """Motores de análise disponíveis e integrações."""
    return sentiment.meta()


@router.post("/analyze")
def analyze(payload: AnalyzePayload) -> Dict[str, Any]:
    """Analisa um texto livre (devolve indicadores, frases, termos e o relatório)."""
    analysis = sentiment.analyze_documents(
        [{"id": "texto", "title": payload.title or "Texto colado", "source": "Texto", "text": payload.text}],
        engine=payload.engine,
        model=payload.model,
    )
    title = payload.title or "Análise de sentimento — texto"
    analysis["markdown"] = sentiment.build_markdown(analysis, title=title)
    analysis["csv"] = sentiment.to_csv(analysis)
    return analysis


@router.post("/corpus")
def analyze_corpus(payload: CorpusPayload, session: Session = None) -> Dict[str, Any]:
    """Analisa um corpus de qualquer fonte do sistema."""
    documents = _corpus(payload, session)
    if not documents:
        raise HTTPException(status_code=404, detail="Não há documentos para analisar com esta origem/filtro.")
    analysis = sentiment.analyze_documents(documents, engine=payload.engine, model=payload.model)
    analysis["markdown"] = sentiment.build_markdown(analysis, title=_describe(payload, documents), term=payload.term or payload.q or "")
    analysis["csv"] = sentiment.to_csv(analysis)
    analysis["origin"] = payload.origin
    analysis["documents_used"] = len(documents)
    return analysis


@router.post("/save/dossier")
def save_to_dossier(payload: SaveDossierPayload, session: Writer) -> Dict[str, Any]:
    """Anexa a análise ao dossiê de análise (passa a constar do dossiê e do Office)."""
    documents = _corpus(payload, session)
    if not documents:
        raise HTTPException(status_code=404, detail="Não há documentos para analisar com esta origem/filtro.")
    analysis = sentiment.analyze_documents(documents, engine=payload.engine, model=payload.model)
    try:
        result = sentiment.save_to_dossier(payload.dossier_id, analysis, title=payload.title, ontology_id=payload.ontology)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Dossiê não encontrado: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {**result, "analysis": analysis, "documents_used": len(documents)}


@router.post("/save/office")
def save_to_office(payload: SaveOfficePayload, session: Writer) -> Dict[str, Any]:
    """Cria/atualiza um documento no Office com o relatório de sentimento."""
    analysis = payload.analysis
    if not analysis:
        if not payload.corpus:
            raise HTTPException(status_code=422, detail="Envie `analysis` ou um `corpus` para analisar.")
        documents = _corpus(payload.corpus, session)
        if not documents:
            raise HTTPException(status_code=404, detail="Não há documentos para analisar com esta origem/filtro.")
        analysis = sentiment.analyze_documents(documents, engine=payload.corpus.engine, model=payload.corpus.model)
    try:
        return sentiment.save_to_office(
            analysis,
            title=payload.title,
            tags=payload.tags,
            folder_id=payload.folder_id,
            author=session.user.email,
            dossier_id=payload.dossier_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
