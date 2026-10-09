"""Rotas da **Pesquisa profunda** (`/deep-search/*`) — resposta citada sobre os dados.

- `GET  /deep-search/meta`      — âmbitos disponíveis, limites e modelo predefinido
- `GET  /deep-search/examples`  — perguntas de exemplo construídas com os dados
- `GET  /deep-search/search`    — só a recuperação de fontes (JSON, sem IA)
- `POST /deep-search/ask`       — resposta do modelo em SSE (tokens + fontes citadas)
- `POST /deep-search/ontology`  — ontologia (objectos e relações) das fontes
- `POST /deep-search/analogies` — contratos semelhantes no mercado
- `POST /deep-search/analysis`  — interpretação da ontologia e das analogias (IA ou Hermes)

Estas três últimas recebem as **fontes já recuperadas** (as mesmas que a página
mostrou no evento `sources`), para não se repetir a recuperação — que é a parte
lenta da pesquisa profunda.

A leitura usa os mesmos índices da «Pesquisa total» (`search_service`), por isso
o âmbito **CRM** só entra quando há sessão (dados privados por utilizador).
"""
from __future__ import annotations

import logging
from typing import Annotated, Any, Dict, List, Literal, Optional, Sequence

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from api import deep_search_analysis as analysis
from api import deep_search_analogies as analogies
from api import deep_search_service as deep
from api.auth_routes import CurrentSession, optional_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/deep-search", tags=["deep-search"])

Session = Annotated[Optional[CurrentSession], Depends(optional_session)]


class DeepSearchAsk(BaseModel):
    """Pedido de resposta: pergunta + âmbitos + modelo (vazio = predefinido)."""

    question: str = Field(..., description="Pergunta em linguagem natural.")
    backend: str = Field("", description="Backend/modelo (ex.: `openai:gpt-4o-mini`). Vazio = predefinição do utilizador.")
    sources: Optional[List[str]] = Field(None, description="Âmbitos a usar (ids de `/deep-search/meta`). Vazio = todos.")
    mode: str = Field(deep.DEFAULT_MODE, description="Recuperação: hybrid (palavras + semântica) | text | vector.")
    per_source: int = Field(deep.PER_SOURCE_DEFAULT, ge=deep.PER_SOURCE_MIN, le=deep.PER_SOURCE_MAX, description="Candidatos lidos por âmbito.")
    max_sources: int = Field(deep.MAX_SOURCES_DEFAULT, ge=0, le=deep.MAX_SOURCES_MAX, description="Máximo de fontes (0 = sem limite).")
    temperature: float = Field(0.2, ge=0.0, le=1.5, description="Criatividade do modelo.")
    max_tokens: int = Field(1400, ge=128, le=4096, description="Limite de tokens da resposta.")
    history: Optional[List[Dict[str, str]]] = Field(None, description="Turnos anteriores ([{role, content}]) para perguntas de seguimento.")


def _visibility(session: Optional[CurrentSession]) -> Optional[Dict[str, Any]]:
    """Âmbito de visibilidade do CRM (privado por utilizador)."""
    if not session:
        return None
    return {
        "user_id": session.user.id,
        "email": session.user.email,
        "see_all": (session.user.role or "member") == "admin",
    }


def _parse_sources(raw: Optional[str]) -> Optional[List[str]]:
    if not raw:
        return None
    return [part.strip() for part in raw.split(",") if part.strip()]


class DeepSourcesPayload(BaseModel):
    """Fontes já recuperadas (as que a página recebeu no evento `sources`)."""

    sources: List[Dict[str, Any]] = Field(default_factory=list, description="Fontes numeradas devolvidas por `/deep-search/ask`.")
    enrich: bool = Field(True, description="Consultar o cadastro de entidades para o nome oficial e o CAE.")


class DeepAnalogiesPayload(DeepSourcesPayload):
    """Analogias para os contratos que estão nas fontes."""

    contracts: int = Field(analogies.CONTRATOS_PADRAO, ge=1, le=6, description="Contratos da resposta a comparar.")
    similar: int = Field(analogies.SEMELHANTES_PADRAO, ge=1, le=analogies.SEMELHANTES_MAX, description="Semelhantes por contrato.")


class DeepAnalysisPayload(DeepSourcesPayload):
    """Pedido de interpretação da ontologia e das analogias."""

    question: str = Field(..., description="Pergunta original, para o texto não perder o contexto.")
    ontology: Optional[Dict[str, Any]] = Field(None, description="Ontologia já calculada (evita recalculá-la).")
    analogies: Optional[Dict[str, Any]] = Field(None, description="Analogias já calculadas (evita repetir o kNN).")
    engine: Literal["modelo", "hermes"] = Field("modelo", description="Quem analisa: o modelo escolhido ou o agente Hermes.")
    backend: str = Field("", description="Backend/modelo (ex.: `deepseek:deepseek-chat`). Vazio = predefinição do utilizador.")
    depth: str = Field("profunda", description="Profundidade da recolha do Hermes: rapida | profunda.")


@router.get("/meta")
def deep_search_meta(session: Session = None) -> Dict[str, Any]:
    """Catálogo de âmbitos + limites + backend predefinido do utilizador."""
    user_id = getattr(getattr(session, "user", None), "id", None)
    defaults: Dict[str, Any] = {}
    if user_id:
        from api import providers_service as providers

        defaults = providers.load_user_config(user_id).get("defaults") or {}
    catalog = deep.source_catalog()
    return {
        **catalog,
        "defaults": {
            "sources": catalog["defaults"],
            "provider": defaults.get("provider") or "",
            "model": defaults.get("model") or "",
            "backend": (
                f"{defaults['provider']}:{defaults.get('model') or ''}".rstrip(":")
                if defaults.get("provider")
                else ""
            ),
        },
        "has_session": bool(user_id),
    }


@router.get("/suggest")
def deep_search_suggest(
    q: str = Query(..., description="Texto escrito na caixa da pergunta."),
    limit: int = Query(8, ge=1, le=20, description="Número máximo de sugestões."),
    session: Session = None,
) -> Dict[str, Any]:
    """Sugestões de autocompletar: empresas, contratos de Espanha, recolha e mercado."""
    return deep.suggest_terms(q, limit=limit, session_scope=_visibility(session))


@router.get("/examples")
def deep_search_examples(
    limit: int = Query(8, ge=1, le=20, description="Número máximo de exemplos."),
) -> Dict[str, Any]:
    """Perguntas de exemplo construídas com os dados indexados.

    Rota própria (e não dentro do `/meta`) porque implica agregações no
    Elasticsearch — alguns segundos. A página desenha logo as sugestões de
    recurso que vêm no `/meta` e substitui-as quando estas chegam.
    """
    return {"examples": deep.dynamic_examples()[:limit]}


@router.get("/search")
def deep_search_sources(
    q: str = Query(..., description="Pergunta ou termos a pesquisar."),
    sources: Optional[str] = Query(None, description="Âmbitos separados por vírgula (ex.: `contracts,imprensa`)."),
    mode: str = Query(deep.DEFAULT_MODE, description="Recuperação: hybrid | text | vector."),
    per_source: int = Query(deep.PER_SOURCE_DEFAULT, ge=deep.PER_SOURCE_MIN, le=deep.PER_SOURCE_MAX),
    max_sources: int = Query(deep.MAX_SOURCES_DEFAULT, ge=0, le=deep.MAX_SOURCES_MAX, description="Máximo de fontes (0 = sem limite)."),
    session: Session = None,
) -> Dict[str, Any]:
    """Só a recuperação: devolve as fontes numeradas, sem chamar nenhum modelo."""
    return deep.retrieve(
        q,
        sources=_parse_sources(sources),
        per_source=per_source,
        max_sources=max_sources,
        session_scope=_visibility(session),
        mode=mode,
    )


@router.post("/analysis")
async def deep_search_analysis(payload: DeepAnalysisPayload, session: Session = None) -> Dict[str, Any]:
    """Interpreta a ontologia e as analogias — pelo modelo escolhido ou pelo Hermes.

    A ontologia é recalculada aqui se não vier no pedido (é barata); as analogias
    só se calculam se faltarem, porque implicam kNN no Elasticsearch.
    """
    user_id = getattr(getattr(session, "user", None), "id", None)
    ontologia = payload.ontology or (
        analysis.ontologia_das_fontes(payload.sources, enriquecer=payload.enrich) if payload.sources else None
    )
    analogias_calculadas = payload.analogies
    if analogias_calculadas is None and payload.sources:
        analogias_calculadas = analogies.analogias(payload.sources)
    return await analysis.analisar(
        payload.question,
        ontologia=ontologia,
        analogias=analogias_calculadas,
        sources=payload.sources,
        motor=payload.engine,
        backend=payload.backend,
        user_id=user_id,
        session=session,
        depth=payload.depth,
    )


@router.post("/ontology")
def deep_search_ontology(payload: DeepSourcesPayload) -> Dict[str, Any]:
    """Ontologia das fontes: objectos (contratos, empresas, CPV, anos) e relações.

    Sai no mesmo envelope do grafo de contratos (`build_contract_graph`), para a
    interface reutilizar o mesmo desenho, mais `legend`, `totals` e `mermaid`.
    """
    return analysis.ontologia_das_fontes(payload.sources, enriquecer=payload.enrich)


@router.post("/analogies")
def deep_search_analogies(payload: DeepAnalogiesPayload) -> Dict[str, Any]:
    """Contratos semelhantes do mercado para os contratos que estão nas fontes."""
    return analogies.analogias(payload.sources, contratos=payload.contracts, semelhantes=payload.similar)


@router.post("/ask")
async def deep_search_ask(req: DeepSearchAsk, session: Session = None):
    """Responde à pergunta em SSE: primeiro as fontes, depois os tokens da resposta."""
    user_id = getattr(getattr(session, "user", None), "id", None)
    stream = deep.stream_answer(
        req.question,
        backend=req.backend,
        user_id=user_id,
        sources=req.sources,
        per_source=req.per_source,
        max_sources=req.max_sources,
        temperature=req.temperature,
        max_tokens=req.max_tokens,
        history=req.history,
        session_scope=_visibility(session),
        mode=req.mode,
    )
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            # Sem isto, um proxy à frente (nginx) acumula a resposta inteira.
            "X-Accel-Buffering": "no",
        },
    )
