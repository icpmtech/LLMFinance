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

import asyncio
import json
import logging
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

# Tempos limite. O `connect` era 10 s e falhava de vez em quando a ligar a
# `api.deepseek.com` (medido: 1 em 10 pedidos, aos 10,1 s, sem enviar um único
# pedaço) — daí a mensagem «não respondeu a tempo», que na verdade queria dizer
# «não consegui ligar». O `read` é generoso porque um modelo pode demorar a
# produzir o primeiro pedaço.
CONNECT_TIMEOUT = 20.0
POOL_TIMEOUT = 30.0
WRITE_TIMEOUT = 30.0
READ_TIMEOUT = 180.0
#: Tentativas totais quando a falha é de **ligação** e nada foi transmitido
#: (repetir depois de já haver texto duplicaria a resposta).
MAX_TENTATIVAS_LIGACAO = 3
TENTATIVA_ESPERA = 0.8

REQUEST_TIMEOUT = httpx.Timeout(
    connect=CONNECT_TIMEOUT, read=READ_TIMEOUT, write=WRITE_TIMEOUT, pool=POOL_TIMEOUT
)
ANTHROPIC_VERSION = "2023-06-01"


def _mensagem_de_timeout(erro: httpx.TimeoutException, label: str) -> str:
    """Mensagem que diz **o que** falhou, não apenas que «não respondeu a tempo».

    O `TimeoutException` do httpx cobre quatro situações muito diferentes; uma
    mensagem única mandava o utilizador procurar o problema no sítio errado.
    """
    if isinstance(erro, httpx.ConnectTimeout):
        return (
            f"Não foi possível ligar a {label} (ligação não estabelecida em {CONNECT_TIMEOUT:.0f} s). "
            "Confirme a ligação à Internet e tente novamente."
        )
    if isinstance(erro, httpx.PoolTimeout):
        return f"{label} não aceitou a ligação a tempo ({POOL_TIMEOUT:.0f} s). Tente novamente daqui a pouco."
    if isinstance(erro, httpx.WriteTimeout):
        return f"A ligação a {label} ficou presa ao enviar o pedido ({WRITE_TIMEOUT:.0f} s). Tente novamente."
    return (
        f"{label} deixou de enviar dados durante {READ_TIMEOUT:.0f} s e o pedido foi interrompido. "
        "Tente novamente ou escolha outro modelo."
    )


def _falha_de_ligacao(erro: Exception) -> bool:
    """Falhas que valem a pena repetir: ainda não chegou nada do fornecedor."""
    return isinstance(erro, (httpx.ConnectTimeout, httpx.PoolTimeout, httpx.ConnectError, httpx.WriteTimeout))


class CloudError(RuntimeError):
    """Erro de um fornecedor externo, já com mensagem apresentável."""

    def __init__(self, message: str, *, status: Optional[int] = None, provider: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.provider = provider


class _FalhaDeTransporte(RuntimeError):
    """Falha de rede/ligação numa tentativa (ver `stream_answer`).

    Serve para o ciclo de tentativas distinguir «não chegou nada do fornecedor»
    (vale a pena repetir) de um erro do próprio fornecedor (não vale).
    """


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


def _ollama_body(
    model: str,
    system: str,
    conversation: List[Dict[str, str]],
    temperature: float,
    max_tokens: int,
    stream: bool,
) -> Dict[str, Any]:
    """Body nativo do Ollama (/api/chat)."""
    messages: List[Dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.extend(conversation)
    body: Dict[str, Any] = {"model": model, "messages": messages, "stream": stream}
    options: Dict[str, Any] = {}
    if temperature is not None:
        options["temperature"] = float(temperature)
    if max_tokens:
        options["num_predict"] = int(max_tokens)
    if options:
        body["options"] = options
    return body


def _ollama_delta(payload: Dict[str, Any]) -> str:
    """Extrai texto dos chunks NDJSON do Ollama."""
    message = payload.get("message") or {}
    return str(message.get("content") or "")


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
    elif kind == "ollama":
        url = f"{base_url}/api/chat"
        body = _ollama_body(model, system, conversation, temperature, max_tokens, True)
        extract = _ollama_delta
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
    elif kind == "ollama" and api_key:
        # Ollama Cloud pode exigir Bearer token se configurado.
        headers = {"content-type": "application/json", "authorization": f"Bearer {api_key}"}

    async def uma_vez() -> AsyncIterator[str]:
        """Uma tentativa: abre a ligação e itera os pedaços."""
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
                        if not line or not line:
                            continue
                        data = line.strip()
                        if data == "[DONE]" or not data:
                            continue
                        # Ollama devolve NDJSON (linhas JSON, não SSE data:).
                        if kind == "ollama":
                            try:
                                payload = json.loads(data)
                            except json.JSONDecodeError:
                                continue
                            if payload.get("done"):
                                continue
                        else:
                            if not line.startswith("data:"):
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
            except httpx.HTTPError as error:
                # Convertido depois, no ciclo de tentativas (que sabe se já houve texto).
                raise _FalhaDeTransporte(str(error)) from error

    label = spec.get("label") or provider
    for tentativa in range(1, MAX_TENTATIVAS_LIGACAO + 1):
        emitido = 0
        try:
            async for chunk in uma_vez():
                emitido += 1
                yield chunk
            return
        except _FalhaDeTransporte as envolucro:
            causa = envolucro.__cause__ or envolucro
            if isinstance(causa, httpx.TimeoutException):
                mensagem = _mensagem_de_timeout(causa, label)
            else:
                mensagem = f"Falha de rede a contactar {label}: {causa}"
            pode_repetir = emitido == 0 and _falha_de_ligacao(causa) and tentativa < MAX_TENTATIVAS_LIGACAO
            if not pode_repetir:
                raise CloudError(mensagem, provider=provider) from causa
            logger.warning(
                "%s: %s — a repetir (%d/%d)", label, mensagem, tentativa + 1, MAX_TENTATIVAS_LIGACAO
            )
            await asyncio.sleep(TENTATIVA_ESPERA * tentativa)


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


async def list_ollama_models(base_url: str, api_key: Optional[str] = None) -> List[str]:
    """Devolve os modelos disponíveis numa instância Ollama via /api/tags."""
    url = f"{base_url.rstrip('/')}/api/tags"
    headers: Dict[str, str] = {"content-type": "application/json"}
    if api_key:
        headers["authorization"] = f"Bearer {api_key}"
    async with httpx.AsyncClient(timeout=httpx.Timeout(connect=CONNECT_TIMEOUT, read=30.0, write=WRITE_TIMEOUT, pool=POOL_TIMEOUT)) as client:
        try:
            response = await client.get(url, headers=headers)
            if response.status_code >= 400:
                body = response.text[:300]
                raise CloudError(
                    _friendly_status(response.status_code, "Ollama (cloud)", body),
                    status=response.status_code,
                    provider="ollama-cloud",
                )
            payload = response.json()
            models = [str(m.get("name") or m.get("model")) for m in payload.get("models", []) if m]
            return sorted({m for m in models if m})
        except httpx.TimeoutException as error:
            raise CloudError(_mensagem_de_timeout(error, "Ollama (cloud)"), provider="ollama-cloud") from error
        except httpx.HTTPError as error:
            raise CloudError(f"Falha de rede a contactar Ollama (cloud): {error}", provider="ollama-cloud") from error


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
