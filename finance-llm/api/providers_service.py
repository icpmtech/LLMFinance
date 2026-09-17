"""Fornecedores de IA (locais e cloud) e chaves de API.

A plataforma pode responder no chat com três modelos locais (GPT-2, Mistral
financeiro e BloombergGPT-style/RAG) e com **fornecedores externos**
compatíveis com a API de *chat completions* da OpenAI — OpenAI, DeepSeek, xAI
(Grok), Groq, Mistral, OpenRouter e Ollama local — mais a Anthropic (Claude) e
o Google (Gemini), que têm formatos próprios.

As chaves de API são **por utilizador**: ficam no índice
`finance_provider_keys` (`_id` = id do utilizador), nunca são devolvidas em
claro (só uma pista mascarada) e podem ser substituídas por variáveis de
ambiente do servidor (`OPENAI_API_KEY`, `DEEPSEEK_API_KEY`, `XAI_API_KEY`, …).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from api.elasticsearch_client import PROVIDER_KEYS_INDEX, ensure_indices, get_es_client

logger = logging.getLogger(__name__)

# --- catálogo -----------------------------------------------------------------

PROVIDERS: List[Dict[str, Any]] = [
    {
        "id": "openai",
        "label": "OpenAI",
        "kind": "openai",
        "base_url": "https://api.openai.com/v1",
        "env": "OPENAI_API_KEY",
        "docs_url": "https://platform.openai.com/api-keys",
        "models": ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini", "gpt-4.1", "o4-mini"],
        "default_model": "gpt-4o-mini",
        "notes": "Modelos GPT; excelente equilíbrio entre custo e qualidade.",
    },
    {
        "id": "deepseek",
        "label": "DeepSeek",
        "kind": "openai",
        "base_url": "https://api.deepseek.com/v1",
        "env": "DEEPSEEK_API_KEY",
        "docs_url": "https://platform.deepseek.com/api_keys",
        "models": ["deepseek-chat", "deepseek-reasoner"],
        "default_model": "deepseek-chat",
        "notes": "Muito económico; o `deepseek-reasoner` faz raciocínio passo a passo.",
    },
    {
        "id": "xai",
        "label": "xAI (Grok)",
        "kind": "openai",
        "base_url": "https://api.x.ai/v1",
        "env": "XAI_API_KEY",
        "docs_url": "https://console.x.ai",
        "models": ["grok-3", "grok-3-mini", "grok-2-1212", "grok-beta"],
        "default_model": "grok-3-mini",
        "notes": "Modelos Grok, com acesso a informação recente.",
    },
    {
        "id": "anthropic",
        "label": "Anthropic (Claude)",
        "kind": "anthropic",
        "base_url": "https://api.anthropic.com/v1",
        "env": "ANTHROPIC_API_KEY",
        "docs_url": "https://console.anthropic.com/settings/keys",
        "models": ["claude-sonnet-4-5", "claude-opus-4-1", "claude-3-5-haiku-latest"],
        "default_model": "claude-sonnet-4-5",
        "notes": "Forte em análises longas e documentos.",
    },
    {
        "id": "google",
        "label": "Google (Gemini)",
        "kind": "google",
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "env": "GEMINI_API_KEY",
        "docs_url": "https://aistudio.google.com/app/apikey",
        "models": ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"],
        "default_model": "gemini-2.5-flash",
        "notes": "Contexto muito grande; bom para resumos de contratos.",
    },
    {
        "id": "groq",
        "label": "Groq",
        "kind": "openai",
        "base_url": "https://api.groq.com/openai/v1",
        "env": "GROQ_API_KEY",
        "docs_url": "https://console.groq.com/keys",
        "models": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768"],
        "default_model": "llama-3.3-70b-versatile",
        "notes": "Inferência muito rápida (LPU) para modelos abertos.",
    },
    {
        "id": "mistral-ai",
        "label": "Mistral AI (cloud)",
        "kind": "openai",
        "base_url": "https://api.mistral.ai/v1",
        "env": "MISTRAL_API_KEY",
        "docs_url": "https://console.mistral.ai/api-keys",
        "models": ["mistral-large-latest", "mistral-small-latest", "open-mistral-nemo"],
        "default_model": "mistral-small-latest",
        "notes": "Modelos europeus; o `mistral-small` é barato e rápido.",
    },
    {
        "id": "openrouter",
        "label": "OpenRouter",
        "kind": "openai",
        "base_url": "https://openrouter.ai/api/v1",
        "env": "OPENROUTER_API_KEY",
        "docs_url": "https://openrouter.ai/keys",
        "models": [
            "openai/gpt-4o-mini",
            "anthropic/claude-sonnet-4.5",
            "deepseek/deepseek-chat",
            "meta-llama/llama-3.3-70b-instruct",
        ],
        "default_model": "openai/gpt-4o-mini",
        "notes": "Uma chave só para muitos modelos (com encaminhamento automático).",
    },
    {
        "id": "ollama",
        "label": "Ollama (local)",
        "kind": "openai",
        "base_url": os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1"),
        "env": "OLLAMA_API_KEY",
        "docs_url": "https://ollama.com/download",
        "models": ["llama3.2", "qwen2.5", "mistral", "phi4"],
        "default_model": "llama3.2",
        "notes": "Corre no seu computador — não precisa de chave (a chave é ignorada).",
        "key_optional": True,
    },
]

# Modelos locais da plataforma (o backend é o próprio nome).
LOCAL_BACKENDS: List[Dict[str, Any]] = [
    {"id": "gpt2", "label": "GPT-2 Finance (local)", "kind": "local", "models": ["finance-llm"]},
    {"id": "mistral", "label": "Mistral Finance (local)", "kind": "local", "models": ["mistral-finance"]},
    {"id": "bloomberg", "label": "BloombergGPT-style (RAG, local)", "kind": "local", "models": ["finance-llm-rag"]},
]

# Nota: o modelo local chama-se `mistral`; o fornecedor cloud usa `mistral-ai`
# para não haver identificadores duplicados no selector do chat.

PROVIDERS_BY_ID = {spec["id"]: spec for spec in PROVIDERS}

STATE_FIELDS = ("api_key", "default_model", "updated_at")


# --- chaves por utilizador ----------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _client():
    client = get_es_client()
    if client:
        ensure_indices(client)
    return client


def load_user_config(user_id: str) -> Dict[str, Any]:
    """Configuração guardada do utilizador (`{keys: {...}, defaults: {...}}`)."""
    client = _client()
    if not client or not user_id:
        return {"keys": {}, "defaults": {}}
    try:
        response = client.get(index=PROVIDER_KEYS_INDEX, id=str(user_id))
        source = dict(response.get("_source") or {})
        return {"keys": source.get("keys") or {}, "defaults": source.get("defaults") or {}}
    except Exception:
        return {"keys": {}, "defaults": {}}


def _save_user_config(user_id: str, config: Dict[str, Any]) -> None:
    client = _client()
    if not client or not user_id:
        return
    document = {
        "user_id": str(user_id),
        "keys": config.get("keys") or {},
        "defaults": config.get("defaults") or {},
        "updated_at": _now(),
    }
    try:
        client.index(index=PROVIDER_KEYS_INDEX, id=str(user_id), document=document, refresh=True)
    except Exception as error:
        logger.warning("Não foi possível guardar as chaves do utilizador %s: %s", user_id, error)


def save_api_key(user_id: str, provider: str, api_key: Optional[str]) -> Dict[str, Any]:
    """Guarda (ou remove, com `api_key` vazio) a chave de um fornecedor."""
    if provider not in PROVIDERS_BY_ID:
        raise ValueError("Fornecedor desconhecido.")
    config = load_user_config(user_id)
    keys = dict(config.get("keys") or {})
    value = (api_key or "").strip()
    if value:
        keys[provider] = {"value": value, "updated_at": _now()}
    else:
        keys.pop(provider, None)
    config["keys"] = keys
    _save_user_config(user_id, config)
    return config


def save_defaults(user_id: str, defaults: Dict[str, Any]) -> Dict[str, Any]:
    """Guarda o fornecedor/modelo predefinidos do chat."""
    config = load_user_config(user_id)
    current = dict(config.get("defaults") or {})
    for key in ("provider", "model"):
        if key in defaults and defaults[key]:
            current[key] = str(defaults[key])
    config["defaults"] = current
    _save_user_config(user_id, config)
    return config


def env_key(provider: str) -> Optional[str]:
    """Chave definida no ambiente do servidor, se existir."""
    spec = PROVIDERS_BY_ID.get(provider)
    if not spec:
        return None
    value = os.getenv(spec.get("env") or "")
    return value.strip() if value and value.strip() else None


def resolve_key(user_id: Optional[str], provider: str) -> tuple[Optional[str], str]:
    """Chave efetiva do fornecedor: `(valor, origem)` com origem `user`/`env`/`none`."""
    if user_id:
        config = load_user_config(user_id)
        entry = (config.get("keys") or {}).get(provider) or {}
        value = (entry.get("value") or "").strip() if isinstance(entry, dict) else ""
        if value:
            return value, "user"
    value = env_key(provider)
    if value:
        return value, "env"
    return None, "none"


def mask_key(value: Optional[str]) -> str:
    """Pista de uma chave (nunca a chave completa)."""
    if not value:
        return ""
    if len(value) <= 8:
        return "•" * len(value)
    return f"{value[:3]}…{value[-4:]}"


def provider_catalog(user_id: Optional[str] = None) -> Dict[str, Any]:
    """Catálogo para a interface: fornecedores, chaves mascaradas e predefinições."""
    config = load_user_config(user_id) if user_id else {"keys": {}, "defaults": {}}
    saved_keys = config.get("keys") or {}
    items: List[Dict[str, Any]] = []

    for entry in LOCAL_BACKENDS:
        items.append(
            {
                **{key: value for key, value in entry.items() if key != "models"},
                "models": list(entry["models"]),
                "default_model": entry["models"][0],
                "requires_key": False,
                "configured": True,
                "key_source": "local",
                "key_hint": "",
                "id_prefix": "",
            }
        )

    for spec in PROVIDERS:
        value, source = resolve_key(user_id, spec["id"])
        requires_key = not spec.get("key_optional")
        items.append(
            {
                **{key: value for key, value in spec.items() if key != "models"},
                "models": list(spec["models"]),
                "default_model": spec["default_model"],
                "requires_key": requires_key,
                "configured": bool(value) or not requires_key,
                "key_source": source,
                "key_hint": mask_key(value) if source == "user" else "",
                "has_user_key": bool(((saved_keys.get(spec["id"]) or {}) if isinstance(saved_keys.get(spec["id"]), dict) else {}).get("value")),
                "id_prefix": f"{spec['id']}:",
            }
        )

    return {
        "providers": items,
        "defaults": config.get("defaults") or {},
    }


def parse_backend(backend: str) -> Dict[str, Any]:
    """Interpreta o `backend` do chat.

    Formatos aceites:
    - `gpt2` / `mistral` / `bloomberg` → modelos locais;
    - `openai:gpt-4o-mini` / `deepseek:deepseek-chat` → fornecedor cloud + modelo;
    - `openai` (só o fornecedor) → usa o modelo predefinido do catálogo.
    """
    value = (backend or "gpt2").strip()
    if ":" in value:
        provider_id, model = value.split(":", 1)
    elif value in PROVIDERS_BY_ID:
        provider_id, model = value, ""
    else:
        return {"kind": "local", "backend": value, "provider": None, "model": None}

    provider_id = provider_id.strip().lower()
    spec = PROVIDERS_BY_ID.get(provider_id)
    if not spec:
        return {"kind": "local", "backend": value, "provider": None, "model": None, "error": f"Fornecedor desconhecido: {provider_id}"}
    return {
        "kind": "cloud",
        "backend": value,
        "provider": provider_id,
        "model": (model or spec.get("default_model") or "").strip(),
        "spec": spec,
    }
