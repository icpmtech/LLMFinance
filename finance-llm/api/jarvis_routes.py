"""Rotas do **Jarvis** (`/jarvis/*`) — o assistente com voz e browser.

O Jarvis é o assistente operacional do IQ OS. Fala com o sistema por três
gateways (Hermes, MCP do sistema e browser), segue as skills partilhadas com o
Hermes e o Chat IA, e interage por voz (áudio → texto → resposta falada).

Rotas:

- `GET  /jarvis/meta`              — capacidades, gateways, ferramentas, vozes e modelo
- `GET  /jarvis/tools`             — catálogo de ferramentas dos gateways
- `GET  /jarvis/actions`           — catálogo de ações (destinos da app e criações)
- `POST /jarvis/actions/run`       — executa uma criação em nome do utilizador
- `GET  /jarvis/voice`             — estado da voz (STT/TTS) e vozes disponíveis
- `POST /jarvis/ask`               — pergunta → resposta (com plano, passos e citações)
- `POST /jarvis/ask/stream`        — o mesmo, em SSE (`passo`, `ferramenta`, `resposta`, `fim`)
- `POST /jarvis/transcribe`        — áudio (multipart) → texto
- `POST /jarvis/speak`             — texto → áudio (mp3)

O `ask` aceita:

```json
{
  "question": "Quais são os maiores contratos públicos de energia em 2025?",
  "depth": "rapida | profunda",
  "backend": "openai:gpt-4o-mini",
  "history": [{"role": "user", "content": "..."}],
  "voice": "pt-PT-RaquelNeural",
  "speak": true
}
```

Quando `speak` é `true` e a síntese do servidor está disponível, a resposta
inclui também o áudio em base64 (`audio`); sem motor no servidor, a interface
usa as vozes do sistema (Web Speech API) e o campo vem `null`.
"""
from __future__ import annotations

import base64
import logging
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from api import jarvis_actions as actions_catalogue
from api import jarvis_gateway as gateway
from api import jarvis_service as service
from api.auth_routes import CurrentSession, optional_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/jarvis", tags=["jarvis"])

Session = Annotated[Optional[CurrentSession], Depends(optional_session)]

MAX_AUDIO_BYTES = 25 * 1024 * 1024


class AskPayload(BaseModel):
    """Pergunta ao Jarvis."""

    question: str = Field(..., description="Pergunta em linguagem natural (pode vir da transcrição de voz).")
    depth: str = Field("rapida", description="`rapida` ou `profunda` (usada pelo gateway do Hermes).")
    backend: Optional[str] = Field(None, description="Modelo a usar (`provider:modelo`); vazio usa o predefinido da conta.")
    history: List[Dict[str, Any]] = Field(default_factory=list, description="Turnos anteriores da conversa.")
    voice: Optional[str] = Field(None, description="Voz para a síntese (id de `/jarvis/voice`).")
    speak: bool = Field(False, description="Devolver também o áudio da resposta (base64).")


class SpeakPayload(BaseModel):
    """Pedido de síntese de voz."""

    text: str = Field(..., description="Texto a sintetizar.")
    voice: Optional[str] = Field(None, description="Voz (id de `/jarvis/voice`).")
    rate: str = Field("+0%", description="Velocidade relativa, por exemplo `+10%` ou `-10%`.")


class ActionRunPayload(BaseModel):
    """Execução de uma ação proposta pelo Jarvis (só as de criação)."""

    action: str = Field(..., description="Identificador da ação (ver `GET /jarvis/actions`).")
    question: str = Field("", description="Pergunta que originou a ação (para o título).")
    answer: str = Field("", description="Resposta sobre a qual a ação atua.")
    params: Dict[str, Any] = Field(default_factory=dict, description="Ajustes ao corpo da operação.")


def _scope(session: Optional[CurrentSession]) -> Optional[Dict[str, Any]]:
    """Âmbito de leitura dos dados privados (CRM) quando há sessão."""
    if not session:
        return None
    return {
        "user_id": session.user.id,
        "email": session.user.email,
        "see_all": (session.user.role or "member") == "admin",
    }


def _token_of(session: Optional[CurrentSession]) -> Optional[str]:
    """Token da sessão, para o gateway MCP chamar a API em nome do utilizador."""
    for attribute in ("token", "access_token", "raw_token"):
        value = getattr(session, attribute, None)
        if value:
            return str(value)
    token = getattr(session, "session", None)
    if isinstance(token, dict):
        for key in ("token", "access_token"):
            if token.get(key):
                return str(token[key])
    return None


@router.get("/meta")
def meta(
    session: Session = None,
    backend: Optional[str] = Query(None, description="Modelo a considerar no estado devolvido."),
) -> Dict[str, Any]:
    """Capacidades do Jarvis: gateways, ferramentas, vozes e modelo disponível."""
    return service.meta(session, backend)


@router.get("/tools")
def tools(gateway_id: Optional[str] = Query(None, alias="gateway")) -> Dict[str, Any]:
    """Catálogo de ferramentas dos gateways (opcionalmente de um só gateway)."""
    items = gateway.catalog(gateway_id)
    if gateway_id and not items and gateway_id not in {entry["id"] for entry in gateway.GATEWAYS}:
        raise HTTPException(status_code=404, detail=f"Gateway desconhecido: {gateway_id}.")
    return {"gateway": gateway_id, "tools": items, "total": len(items)}


@router.get("/voice")
def voice() -> Dict[str, Any]:
    """Estado da voz: transcrição (STT), síntese (TTS) e vozes disponíveis."""
    return {"stt": service.stt_status(), "tts": service.tts_status()}


@router.get("/actions")
def actions() -> Dict[str, Any]:
    """Catálogo de ações: destinos da aplicação (navegar) e criações (guardar)."""
    catalogue = actions_catalogue.catalogue()
    return {**catalogue, "total": len(catalogue["destinations"]) + len(catalogue["creations"])}


@router.post("/actions/run")
async def run_action(payload: ActionRunPayload, session: Session = None) -> Dict[str, Any]:
    """Executa uma **criação** em nome do utilizador (documento, dossiê, skill).

    A navegação não passa por aqui: é o cliente que muda de vista. Só as ações
    de criação — que escrevem na plataforma — chegam ao servidor, e apenas
    depois de o utilizador confirmar na interface.
    """
    try:
        return await actions_catalogue.run(
            payload.action,
            question=payload.question,
            answer=payload.answer,
            params=payload.params,
            ctx={
                "session": session,
                "scope": _scope(session),
                "token": _token_of(session),
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/ask")
async def ask(payload: AskPayload, session: Session = None) -> Dict[str, Any]:
    """Responde à pergunta, passando pelos gateways do Jarvis."""
    depth = str(payload.depth or "rapida")
    if depth not in {"rapida", "profunda"}:
        raise HTTPException(status_code=422, detail=f"Modo de investigação desconhecido: {depth}.")
    try:
        result = await service.ask(
            payload.question,
            session=session,
            backend=payload.backend,
            depth=depth,
            history=payload.history,
            scope=_scope(session),
            token=_token_of(session),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    result["audio"] = None
    if payload.speak:
        try:
            audio, engine = await service.synthesize(result.get("speech") or result.get("answer") or "", voice=payload.voice)
            result["audio"] = {"mime": "audio/mpeg", "engine": engine, "base64": base64.b64encode(audio).decode("ascii")}
        except Exception as exc:
            logger.info("Síntese no servidor indisponível: %s", exc)
            result["audio_error"] = str(exc)
    return result


@router.post("/ask/stream")
async def ask_stream(payload: AskPayload, session: Session = None) -> StreamingResponse:
    """O mesmo que `/jarvis/ask`, em SSE (passos, ferramentas e resposta)."""
    depth = str(payload.depth or "rapida")
    if depth not in {"rapida", "profunda"}:
        raise HTTPException(status_code=422, detail=f"Modo de investigação desconhecido: {depth}.")

    events = service.stream(
        payload.question,
        session=session,
        backend=payload.backend,
        depth=depth,
        history=payload.history,
        scope=_scope(session),
        token=_token_of(session),
    )
    return StreamingResponse(events, media_type="text/event-stream")


@router.post("/transcribe")
async def transcribe(
    audio: UploadFile = File(..., description="Áudio capturado no microfone (webm/wav/mp3/ogg/m4a)."),
    language: str = Query("pt", description="Idioma esperado do áudio."),
) -> Dict[str, Any]:
    """Transcreve áudio em texto (faster-whisper)."""
    data = await audio.read()
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="O áudio excede o limite de 25 MB.")
    try:
        return await run_in_threadpool(service.transcribe, data, filename=audio.filename or "audio.webm", language=language)
    except RuntimeError as exc:
        # 501: a interface deve cair para o reconhecimento de voz do browser.
        raise HTTPException(status_code=501, detail=str(exc)) from exc


@router.post("/speak")
async def speak(payload: SpeakPayload) -> Response:
    """Sintetiza texto em áudio (mp3)."""
    try:
        audio, engine = await service.synthesize(payload.text, voice=payload.voice, rate=payload.rate)
    except RuntimeError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    return Response(
        content=audio,
        media_type="audio/mpeg",
        headers={"X-Jarvis-Voice-Engine": engine, "Cache-Control": "no-store"},
    )
