"""Definições do MiroFish (`/mirofish/settings`) — chaves do LLM e do Zep.

O contentor `mirofish` lê as chaves do **ambiente** (`docker-compose.yml` →
`${MIROFISH_LLM_API_KEY:-${OPENAI_API_KEY:-}}`, `${MIROFISH_ZEP_API_KEY:-${ZEP_API_KEY:-}}`),
por isso a plataforma não as pode mudar a quente: tem de escrevê-las no `.env` do
projeto e recriar o contentor.

Este módulo faz exatamente isso:

1. **LLM a partir do sistema** — a chave deixa de ser copiada à mão: escolhe-se um
   fornecedor já configurado na plataforma (`finance_provider_keys`) e a chave é
   resolvida com `providers_service.resolve_key(...)`, escrevendo depois
   `MIROFISH_LLM_API_KEY` / `_BASE_URL` / `_MODEL_NAME` no `.env`.
2. **Zep com UI** — a chave do Zep Cloud (obrigatória para o MiroFish arrancar) é
   guardada nas definições da plataforma e atualizável pela página MiroFish.

Os valores **nunca** são devolvidos pela API (só máscaras, ex.: `sk-…4f2a`).
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from api.elasticsearch_client import SETTINGS_INDEX, ensure_indices, get_es_client

logger = logging.getLogger(__name__)

DOC_ID = "mirofish"
PROJECT_DIR = Path(os.getenv("MIROFISH_PROJECT_DIR") or Path(__file__).resolve().parents[1])
ENV_FILE = Path(os.getenv("MIROFISH_ENV_FILE") or PROJECT_DIR / ".env")
COMPOSE_FILE = Path(os.getenv("MIROFISH_COMPOSE_FILE") or PROJECT_DIR / "docker-compose.yml")
COMPOSE_SERVICE = os.getenv("MIROFISH_COMPOSE_SERVICE", "mirofish")
COMPOSE_PROFILE = os.getenv("MIROFISH_COMPOSE_PROFILE", "mirofish")

#: Variáveis geridas no `.env` (as restantes linhas são preservadas).
MANAGED_KEYS = (
    "MIROFISH_LLM_API_KEY",
    "MIROFISH_LLM_BASE_URL",
    "MIROFISH_LLM_MODEL_NAME",
    "MIROFISH_ZEP_API_KEY",
)

SECTION_HEADER = "# --- MiroFish: chaves geridas pela plataforma (não editar à mão) ---"

#: Fornecedores da plataforma que falam a API da OpenAI (os únicos que o MiroFish
#: consegue usar: precisa de `chat/completions` e de *tool calling*).
OPENAI_COMPATIBLE_KINDS = {"openai", "ollama"}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def mask(value: Optional[str]) -> str:
    """Pista de um segredo (nunca o valor)."""
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) <= 8:
        return "•" * len(text)
    return f"{text[:3]}…{text[-4:]}"


# ---------------------------------------------------------------------------
# Definições guardadas na plataforma (índice `finance_settings`)
# ---------------------------------------------------------------------------
_DEFAULTS: Dict[str, Any] = {
    "llm_provider": "deepseek",
    "llm_model": "",
    "llm_base_url": "",
    "llm_custom_key": "",
    "zep_api_key": "",
    "updated_at": None,
    "updated_by": None,
    "applied_at": None,
}


def _client():
    client = get_es_client()
    if client:
        ensure_indices(client)
    return client


def load_settings() -> Dict[str, Any]:
    """Definições guardadas (com os valores por omissão)."""
    settings = dict(_DEFAULTS)
    client = _client()
    if not client:
        return settings
    try:
        document = client.get(index=SETTINGS_INDEX, id=DOC_ID).get("_source") or {}
        stored = document.get("mirofish")
        if isinstance(stored, dict):
            settings.update({key: stored.get(key, settings[key]) for key in settings})
    except Exception:
        return settings
    return settings


def save_settings(patch: Dict[str, Any], *, actor: Optional[str] = None) -> Dict[str, Any]:
    """Grava um subconjunto das definições (as chaves vazias não apagam as existentes)."""
    settings = load_settings()
    for key, value in (patch or {}).items():
        if key not in settings or value is None:
            continue
        if key in {"llm_custom_key", "zep_api_key"} and str(value).strip() == "":
            continue  # campo em branco = manter o que estava
        settings[key] = value
    settings["updated_at"] = _now()
    settings["updated_by"] = actor or settings.get("updated_by")
    client = _client()
    if client:
        try:
            client.index(index=SETTINGS_INDEX, id=DOC_ID, document={"mirofish": settings}, refresh=True)
        except Exception as error:  # pragma: no cover - ES em baixo
            logger.warning("Não foi possível guardar as definições do MiroFish: %s", error)
    return settings


# ---------------------------------------------------------------------------
# Ficheiro `.env` do projeto (o que o docker compose lê)
# ---------------------------------------------------------------------------
def _read_env_lines() -> List[str]:
    if not ENV_FILE.exists():
        return []
    try:
        return ENV_FILE.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []


def env_values(keys: Tuple[str, ...] = MANAGED_KEYS) -> Dict[str, str]:
    """Valores atuais das chaves geridas no `.env` (para mascarar na UI)."""
    values: Dict[str, str] = {}
    for line in _read_env_lines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, _, value = stripped.partition("=")
        name = name.strip()
        if name in keys:
            values[name] = value.strip().strip('"').strip("'")
    return values


def write_env(values: Dict[str, str]) -> List[str]:
    """Escreve (ou atualiza) as chaves geridas no `.env`, preservando o resto.

    Devolve os nomes das variáveis escritas — nunca os valores.
    """
    wanted = {key: str(value) for key, value in (values or {}).items() if key in MANAGED_KEYS and str(value).strip()}
    lines = _read_env_lines()
    written: List[str] = []

    def _write_line(name: str, value: str) -> str:
        clean = value.replace("\n", " ").replace("\r", " ").strip()
        return f"{name}={clean}"

    for name, value in wanted.items():
        for index, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith(f"{name}=") or stripped.startswith(f"{name} ="):
                lines[index] = _write_line(name, value)
                written.append(name)
                break
        else:
            lines.append(_write_line(name, value))
            written.append(name)

    # Remover duplicados das chaves geridas (fica a última ocorrência).
    seen: set = set()
    unique: List[str] = []
    for line in reversed(lines):
        stripped = line.strip()
        name = stripped.partition("=")[0].strip() if ("=" in stripped and not stripped.startswith("#")) else ""
        if name in wanted:
            if name in seen:
                continue
            seen.add(name)
        unique.append(line)
    lines = list(reversed(unique))

    if SECTION_HEADER not in lines:
        lines = [SECTION_HEADER, *lines]

    try:
        ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
        ENV_FILE.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    except Exception as exc:  # contentor sem acesso ao projeto do host
        raise RuntimeError(
            f"não consigo escrever {ENV_FILE} a partir deste processo ({type(exc).__name__}: {exc}). "
            "Se o backend corre em Docker, escreva as chaves no .env do projeto e recrie o contentor "
            f"(`docker compose --profile {COMPOSE_PROFILE} up -d --force-recreate {COMPOSE_SERVICE}`)."
        ) from exc
    return written


def docker_available() -> bool:
    return bool(shutil.which("docker"))


def compose_recreate(timeout: float = 600.0) -> Dict[str, Any]:
    """Recria o contentor do MiroFish para carregar as chaves novas do `.env`."""
    command = [
        "docker",
        "compose",
        "--profile",
        COMPOSE_PROFILE,
        "up",
        "-d",
        "--force-recreate",
        COMPOSE_SERVICE,
    ]
    if not docker_available():
        return {"ok": False, "command": " ".join(command), "detail": "comando `docker` não disponível neste processo."}
    if not COMPOSE_FILE.exists():
        return {"ok": False, "command": " ".join(command), "detail": f"não encontrei {COMPOSE_FILE}."}
    try:
        result = subprocess.run(
            command,
            cwd=str(PROJECT_DIR),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except Exception as exc:
        return {"ok": False, "command": " ".join(command), "detail": f"{type(exc).__name__}: {exc}"}
    output = ((result.stdout or "") + (result.stderr or "")).strip().splitlines()
    return {
        "ok": result.returncode == 0,
        "command": " ".join(command),
        "exit_code": result.returncode,
        "output": output[-12:],
    }


# ---------------------------------------------------------------------------
# Vista para a UI
# ---------------------------------------------------------------------------
def llm_candidates(user_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Fornecedores da plataforma que o MiroFish consegue usar (API da OpenAI)."""
    from api import providers_service as providers

    items: List[Dict[str, Any]] = []
    for spec in providers.PROVIDERS:
        if spec.get("kind") not in OPENAI_COMPATIBLE_KINDS:
            continue
        key, origin = providers.resolve_key(user_id, spec["id"])
        base_url = providers.resolve_provider_url(user_id, spec["id"]) or spec.get("base_url") or ""
        model = providers.resolve_provider_model(user_id, spec["id"]) or spec.get("default_model") or ""
        items.append(
            {
                "id": spec["id"],
                "label": spec.get("label") or spec["id"],
                "base_url": base_url,
                "default_model": model,
                "models": list(spec.get("models") or []),
                "docs_url": spec.get("docs_url"),
                "key_optional": bool(spec.get("key_optional")),
                "configured": bool(key) or bool(spec.get("key_optional")),
                "key_source": origin,
                "key_hint": mask(key),
                "usable": bool(key) or bool(spec.get("key_optional")),
            }
        )
    return items


def resolve_llm(settings: Dict[str, Any], user_id: Optional[str] = None) -> Dict[str, Any]:
    """Resolve a chave/URL/modelo do LLM a escrever no `.env`.

    Ordem: chave personalizada guardada nas definições > chave do fornecedor
    escolhido (chave do utilizador na plataforma ou variável de ambiente).
    """
    from api import providers_service as providers

    provider = str(settings.get("llm_provider") or "").strip()
    custom = str(settings.get("llm_custom_key") or "").strip()
    spec = providers.PROVIDERS_BY_ID.get(provider) if provider else None
    if custom:
        base_url = str(settings.get("llm_base_url") or (spec or {}).get("base_url") or "").strip()
        model = str(settings.get("llm_model") or (spec or {}).get("default_model") or "").strip()
        return {"key": custom, "base_url": base_url, "model": model, "source": "custom", "provider": provider or "custom"}
    if not spec:
        return {"key": "", "base_url": "", "model": "", "source": "none", "provider": ""}
    key, origin = providers.resolve_key(user_id, provider)
    base_url = str(settings.get("llm_base_url") or providers.resolve_provider_url(user_id, provider) or spec.get("base_url") or "").strip()
    model = str(settings.get("llm_model") or providers.resolve_provider_model(user_id, provider) or spec.get("default_model") or "").strip()
    return {"key": key or "", "base_url": base_url, "model": model, "source": origin, "provider": provider}


def settings_view(user_id: Optional[str] = None) -> Dict[str, Any]:
    """Estado completo para a página MiroFish: definições, `.env` e comandos."""
    settings = load_settings()
    env = env_values()
    llm = resolve_llm(settings, user_id)
    zep = str(settings.get("zep_api_key") or "").strip()
    env_llm = env.get("MIROFISH_LLM_API_KEY", "")
    env_zep = env.get("MIROFISH_ZEP_API_KEY", "")
    return {
        "settings": {
            "llm_provider": settings.get("llm_provider"),
            "llm_model": settings.get("llm_model") or llm.get("model"),
            "llm_base_url": settings.get("llm_base_url") or llm.get("base_url"),
            "llm_key_hint": mask(llm.get("key")),
            "llm_key_source": llm.get("source"),
            "llm_custom": bool(settings.get("llm_custom_key")),
            "zep_key_set": bool(zep),
            "zep_key_hint": mask(zep),
            "updated_at": settings.get("updated_at"),
            "updated_by": settings.get("updated_by"),
            "applied_at": settings.get("applied_at"),
        },
        "providers": llm_candidates(user_id),
        "env": {
            "path": str(ENV_FILE),
            "exists": ENV_FILE.exists(),
            "llm_key_hint": mask(env_llm),
            "zep_key_hint": mask(env_zep),
            "llm_base_url": env.get("MIROFISH_LLM_BASE_URL", ""),
            "llm_model": env.get("MIROFISH_LLM_MODEL_NAME", ""),
            "in_sync": (env_llm == str(llm.get("key") or "") and env_zep == zep) if (llm.get("key") or zep) else False,
        },
        "docker": {"available": docker_available(), "project_dir": str(PROJECT_DIR)},
        "commands": {
            "apply": f"docker compose --profile {COMPOSE_PROFILE} up -d --force-recreate {COMPOSE_SERVICE}",
            "logs": f"docker compose --profile {COMPOSE_PROFILE} logs {COMPOSE_SERVICE}",
            "start": f"docker compose --profile {COMPOSE_PROFILE} up -d",
        },
    }


def apply_settings(user_id: Optional[str] = None, *, recreate: bool = True) -> Dict[str, Any]:
    """Escreve as chaves no `.env` e (por omissão) recria o contentor do MiroFish."""
    settings = load_settings()
    llm = resolve_llm(settings, user_id)
    values = {
        "MIROFISH_LLM_API_KEY": str(llm.get("key") or ""),
        "MIROFISH_LLM_BASE_URL": str(llm.get("base_url") or ""),
        "MIROFISH_LLM_MODEL_NAME": str(llm.get("model") or ""),
        "MIROFISH_ZEP_API_KEY": str(settings.get("zep_api_key") or ""),
    }
    if not values["MIROFISH_LLM_API_KEY"] and not values["MIROFISH_ZEP_API_KEY"]:
        raise RuntimeError(
            "Não há nada para aplicar: escolha um fornecedor de LLM com chave (ou cole uma chave) e "
            "preencha a chave do Zep Cloud."
        )
    written = write_env(values)
    save_settings({"applied_at": _now()})
    result: Dict[str, Any] = {
        "written": written,
        "env_path": str(ENV_FILE),
        "llm": {"provider": llm.get("provider"), "model": llm.get("model"), "base_url": llm.get("base_url"), "key_hint": mask(llm.get("key")), "source": llm.get("source")},
        "zep": {"key_hint": mask(values["MIROFISH_ZEP_API_KEY"])},
        "recreate": None,
    }
    if recreate:
        result["recreate"] = compose_recreate()
    return result
