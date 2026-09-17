"""Chamadas de chat aos fornecedores externos.

Suporta três dialectos, cobrindo os fornecedores do catálogo:

- **OpenAI-compatible** (`/chat/completions`): OpenAI, DeepSeek, xAI, Groq,
  Mistral, OpenRouter e Ollama local;
- **Anthropic** (`/messages` com cabeçalho `x-api-key`);
- **Google Gemini** (`/models/<modelo>:streamGenerateContent`).

Tudo é exposto como *stream* assíncrono de pedaços de texto (`stream_answer`),
o que permite reutilizar o mesmo caminho para o chat em direto da plataforma e,
com `complete_answer`, obter a resposta completa. Os erros do fornecedor são
traduzidos em mensagens legíveis em português.
"""
from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = httpx.Timeout(connect=10.0, read=180.0, write=30.0, pool=10.0)
ANTHROPIC_VERSION = "2023-06-01"


class CloudError(RuntimeError):
    """Erro de um fornecedor externo, já com mensagem apresentável."""

    def __init__(self, message: str, *, status: Optional[int] = None, provider: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.provider = provider


def _friendly_status(status: int, provider: str, body: str) -> str:
    detail = (body or "").strip()[:300]
    if status == 401:
        return f"Chave de API recusada por {provider}. Confirme a chave em Definições → Fornecedores de IA."
    if status == 403:
        return f"{provider} recusou o pedido (403). A chave pode não ter acesso a este modelo."
    if status == 404:
        return f"Modelo não encontrado em {provider}. Verifique o nome do modelo.{f' ({detail})' if detail else ''}"
    if status == 429:
        return f"Limite de utilização/plano excedido em {provider}. Tente novamente mais tarde."
    if status >= 500:
        return f"{provider} está com problemas ({status}). Tente novamente."
    return f"Erro de {provider} ({status}).{f' {detail}' if detail else ''}"


def _headers(provider: str, spec: Dict[str, Any], api_key: Optional[str]) -> Dict[str, str]:
    kind = spec.get("kind")
    if kind == "anthropic":
        return {
            "x-api-key": api_key or "",
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }
    headers = {"content-type": "application/json"}
    if api_key:
        headers["authorization"] = f"Bearer {api_key}"
    if provider == "openrouter":
        headers["http-referer"] = "https://localhost"
        headers["x-title"] = "IQ OS"
    return headers


def _split_messages(messages: List[Dict[str, str]]) -> tuple[str, List[Dict[str, str]]]:
    """Separa o `system` das restantes mensagens (a Anthropic e o Gemini não o aceitam na lista)."""
    system_parts: List[str] = []
    conversation: List[Dict[str, str]] = []
    for message in messages:
        role = str(message.get("role") or "user")
        content = str(message.get("content") or "")
        if role == "system":
            system_parts.append(content)
            continue
        conversation.append({"role": "assistant" if role == "assistant" else "user", "content": content})
    return "\n\n".join(part for part in system_parts if part), conversation


def _build_openai_body(model: str, system: str, conversation: List[Dict[str, str]], temperature: float, max_tokens: int, stream: bool) -> Dict[str, Any]:
    messages: List[Dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.extend(conversation)
    body: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": stream,
    }
    if temperature is not None:
        body["temperature"] = float(temperature)
    if max_tokens:
        body["max_tokens"] = int(max_tokens)
    return body


def _anthropic_body(model: str, system: str, conversation: List[Dict[str, str]], temperature: float, max_tokens: int, stream: bool) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "model": model,
        "messages": conversation,
        "max_tokens": int(max_tokens or 2048),
        "stream": stream,
    }
    if system:
        body["system"] = system
    if temperature is not None:
        body["temperature"] = float(temperature)
    return body


def _google_body(system: str, conversation: List[Dict[str, str]], temperature: float, max_tokens: int) -> Dict[str, Any]:
    contents = []
    for message in conversation:
        contents.append(
            {
                "role": "model" if message["role"] == "assistant" else "user",
                "parts": [{"text": message["content"]}],
            }
        )
    body: Dict[str, Any] = {"contents": contents}
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    generation: Dict[str, Any] = {}
    if temperature is not None:
        generation["temperature"] = float(temperature)
    if max_tokens:
        generation["maxOutputTokens"] = int(max_tokens)
    if generation:
        body["generationConfig"] = generation
    return body


def _openai_delta(payload: Dict[str, Any]) -> str:
    try:
        return payload["choices"][0].get("delta", {}).get("content") or ""
    except (KeyError, IndexError, TypeError):
        return ""


def _anthropic_delta(payload: Dict[str, Any]) -> str:
    if payload.get("type") == "content_block_delta":
        delta = payload.get("delta") or {}
        if delta.get("type") == "text_delta":
            return delta.get("text") or ""
    return ""


def _google_delta(payload: Dict[str, Any]) -> str:
    try:
        parts = payload["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError, TypeError):
        return ""
    return "".join(part.get("text") or "" for part in parts if isinstance(part, dict))


async def stream_answer(
    *,
    provider: str,
    spec: Dict[str, Any],
    model: str,
    messages: List[Dict[str, str]],
    api_key: Optional[str],
    temperature: float = 0.3,
    max_tokens: int = 1024,
) -> AsyncIterator[str]:
    """Itera os pedaços de texto da resposta do fornecedor."""
    kind = spec.get("kind") or "openai"
    base_url = (spec.get("base_url") or "").rstrip("/")
    system, conversation = _split_messages(messages)
    if not conversation:
        conversation = [{"role": "user", "content": "Olá"}]

    if kind == "anthropic":
        url = f"{base_url}/messages"
        body = _anthropic_body(model, system, conversation, temperature, max_tokens, True)
        extract = _anthropic_delta
    elif kind == "google":
        url = f"{base_url}/models/{model}:streamGenerateContent?alt=sse"
        body = _google_body(system, conversation, temperature, max_tokens)
        extract = _google_delta
    else:
        url = f"{base_url}/chat/completions"
        body = _build_openai_body(model, system, conversation, temperature, max_tokens, True)
        extract = _openai_delta

    headers = _headers(provider, spec, api_key)
    if kind == "google":
        # A Gemini usa a chave no parâmetro `key` da query (o cabeçalho é também aceite).
        separator = "&" if "?" in url else "?"
        url = f"{url}{separator}key={api_key or ''}"
        headers = {"content-type": "application/json"}

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        try:
            async with client.stream("POST", url, headers=headers, json=body) as response:
                if response.status_code >= 400:
                    text = (await response.aread()).decode("utf-8", errors="replace")
                    raise CloudError(
                        _friendly_status(response.status_code, spec.get("label") or provider, text),
                        status=response.status_code,
                        provider=provider,
                    )
                async for line in response.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if not data or data == "[DONE]":
                        continue
                    try:
                        payload = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(payload, dict) and payload.get("error"):
                        error = payload["error"]
                        message = error.get("message") if isinstance(error, dict) else str(error)
                        raise CloudError(f"{spec.get('label') or provider}: {message}", provider=provider)
                    chunk = extract(payload)
                    if chunk:
                        yield chunk
        except httpx.TimeoutException as error:
            raise CloudError(f"{spec.get('label') or provider} não respondeu a tempo.", provider=provider) from error
        except httpx.HTTPError as error:
            raise CloudError(f"Falha de rede a contactar {spec.get('label') or provider}: {error}", provider=provider) from error


async def complete_answer(
    *,
    provider: str,
    spec: Dict[str, Any],
    model: str,
    messages: List[Dict[str, str]],
    api_key: Optional[str],
    temperature: float = 0.3,
    max_tokens: int = 1024,
) -> str:
    """Resposta completa (acumula o stream do fornecedor)."""
    parts: List[str] = []
    async for chunk in stream_answer(
        provider=provider,
        spec=spec,
        model=model,
        messages=messages,
        api_key=api_key,
        temperature=temperature,
        max_tokens=max_tokens,
    ):
        parts.append(chunk)
    return "".join(parts).strip()


async def test_provider(*, provider: str, spec: Dict[str, Any], model: str, api_key: Optional[str]) -> Dict[str, Any]:
    """Testa a ligação com um pedido mínimo de uma palavra."""
    answer = await complete_answer(
        provider=provider,
        spec=spec,
        model=model,
        messages=[{"role": "user", "content": "Responde apenas com a palavra: OK"}],
        api_key=api_key,
        temperature=0.0,
        max_tokens=16,
    )
    return {"ok": True, "message": f"Ligação estabelecida ({answer[:40] or 'sem texto'})."}
