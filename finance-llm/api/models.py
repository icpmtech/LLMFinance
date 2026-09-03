"""Esquemas Pydantic para a API FinanceLLM Chat."""
from pydantic import BaseModel
from typing import List, Optional, Literal


class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str
    timestamp: Optional[str] = None


class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    model: str = "finance-llm"
    backend: str = "gpt2"
    stream: bool = False


class Source(BaseModel):
    name: str
    url: Optional[str] = None
    value: Optional[str] = None


class ToolCall(BaseModel):
    tool: str
    input: dict
    output: Optional[str] = None


class ChatResponse(BaseModel):
    message: ChatMessage
    sources: List[Source] = []
    tools: List[ToolCall] = []
    cha