"""Rotas do **modelo de contratos** (`/llm/modelo/*`).

O modelo é o resultado do fine-tuning LoRA descrito em
`docs/modelo-contratos.md`: `Qwen/Qwen2.5-0.5B-Instruct` afinado com pares
extraídos dos índices `contratos`, `finance_entities` e `finance_subvencoes`.

Leitura é pública (a ficha do modelo e a curva de treino não são segredo e
alimentam a página). Gerar uma resposta ou correr uma avaliação custa CPU
durante dezenas de segundos — exige sessão.
"""
from __future__ import annotations

import logging
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from api import llm_contratos_service as service
from api.auth_routes import CurrentSession, require_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/llm/modelo", tags=["llm"])

Session = Annotated[CurrentSession, Depends(require_session)]


class ChatRequest(BaseModel):
    instrucao: str = Field(
        ...,
        min_length=3,
        max_length=400,
        description="O que se quer saber, ex.: «Descreve este contrato público português.»",
    )
    dados: str = Field(..., min_length=3, max_length=6000, description="O documento (campos do Elasticsearch)")
    max_tokens: int = Field(160, ge=16, le=400)
    temperatura: float = Field(0.2, ge=0.0, le=1.5)


class ChatResponse(BaseModel):
    resposta: str
    modelo: str
    adaptador: Optional[str] = None
    prompt_tokens: int = 0
    tokens_gerados: int = 0


class AvaliarRequest(BaseModel):
    limite: int = Field(8, ge=1, le=40, description="Pares held-out a medir")
    gerar: int = Field(2, ge=0, le=6, description="Respostas geradas para medir fidelidade")
    holdout: int = Field(60, ge=0, le=2000)
    seed: int = 42


@router.get("", summary="Ficha do modelo de contratos")
def estado_do_modelo() -> Dict[str, Any]:
    """Adaptador, metadados do treino e curva de perda (últimos passos)."""
    return service.model_state()


@router.get("/metricas", summary="Curva de perda do treino")
def metricas(limite: int = Query(200, ge=1, le=2000)) -> Dict[str, Any]:
    """Pontos de `metrics.jsonl` — a mesma curva que a página desenha."""
    pontos: List[Dict[str, Any]] = service.read_metrics(limit=limite)
    return {"pontos": pontos, "total": len(pontos)}


@router.post("/chat", response_model=ChatResponse, summary="Resposta do modelo afinado")
async def chat(req: ChatRequest, session: Session) -> ChatResponse:  # noqa: ARG001
    """Gera a resposta em CPU (segundos) — corre fora do event loop."""
    try:
        resultado = await run_in_threadpool(
            service.chat,
            req.instrucao,
            req.dados,
            req.max_tokens,
            req.temperatura,
        )
    except Exception as error:  # pragma: no cover - depende do modelo em disco
        logger.exception("Falha ao gerar resposta com o modelo de contratos")
        raise HTTPException(status_code=503, detail=f"Modelo indisponível: {error}") from error
    return ChatResponse(**resultado)


@router.post("/avaliar", summary="Correr a avaliação base vs adaptador")
async def avaliar(req: AvaliarRequest, session: Session) -> Dict[str, Any]:  # noqa: ARG001
    """Mede o held-out e guarda o resultado em `finance_llm_model_evals`."""
    try:
        return await run_in_threadpool(service.avaliar, req.limite, req.gerar, req.holdout, req.seed)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:  # pragma: no cover - depende do modelo em disco
        logger.exception("Falha na avaliação do modelo de contratos")
        raise HTTPException(status_code=503, detail=f"Avaliação indisponível: {error}") from error


@router.get("/avaliacoes", summary="Histórico de avaliações")
def avaliacoes(size: int = Query(20, ge=1, le=100)) -> Dict[str, Any]:
    """Últimas avaliações guardadas no Elasticsearch (vazio se o cluster faltar)."""
    docs = service.list_evals(size=size)
    return {"avaliacoes": docs, "total": len(docs)}
