"""Backend FastAPI para a Chat UI do FinanceLLM."""
import json
from pathlib import Path
from typing import Annotated, List

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from api.models import ChatMessage, ChatRequest, ChatResponse
from api.agent import run_chat, stream_chat


ROOT = Path(__file__).resolve().parents[1]

app = FastAPI(
    title="FinanceLLM API",
    version="0.2.0",
    description="API de chat para os modelos de finanças FinanceLLM (GPT-2 e Mistral).",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def read_root():
    return {"status": "ok", "service": "FinanceLLM API", "models": ["gpt2", "mistral"]}


@app.get("/health")
def health():
    return {"status": "healthy", "models": ["gpt2", "mistral"]}


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, backend: str = Query("gpt2", pattern="^(gpt2|mistral)$")):
    result = run_chat(req.messages, backend=backend)
    return ChatResponse(
        message=result["message"],
        sources=result["sources"],
        tools=result["tools"],
    )


@app.post("/chat/stream")
def chat_stream_post(req: ChatRequest, backend: str = Query("gpt2", pattern="^(gpt2|mistral)$")):
    return StreamingResponse(
        stream_chat(req.messages, backend=backend),
        media_type="text/event-stream",
    )


@app.get("/chat/stream")
def chat_stream_get(_payload: Annotated[str, Query(...)], backend: str = Query("gpt2", pattern="^(gpt2|mistral)$")):
    payload = json.loads(_payload)
    req = ChatRequest(**payload)
    return StreamingResponse(
        stream_chat(req.messages, backend=backend),
        media_type="text/event-stream",
    )
