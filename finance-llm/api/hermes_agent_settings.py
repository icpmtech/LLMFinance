"""Motor do **Hermes Agent** — liga o container aos fornecedores de IA do IQ OS.

O container `hermes-agent` (perfil `agents` do compose) é um agente autónomo
independente: não partilha nada com a plataforma além do **login do dashboard**
(o plugin `dashboard-auth-iqos` valida as contas do IQ OS) e vive do seu próprio
volume `hermes-data` (`/opt/data/config.yaml` + `/opt/data/.env`). Sem
configuração, esse volume fica com o `config.yaml` de exemplo — `provider: auto`
e `default: anthropic/claude-opus-4.6` — e **sem chave nenhuma**, ou seja, o
agente arranca sem modelo.

Este módulo fecha essa lacuna, com o mesmo padrão do MiroFish
(`api/mirofish_settings.py`): a plataforma resolve a chave que já tem guardada
para o utilizador (`finance_provider_keys`, via `providers_service`) e
escreve-a onde o Hermes a lê.

**Onde escrever** (descoberto no container, não assumido):

1. `$HERMES_HOME/config.yaml` → `model.provider`, `model.default`,
   `model.base_url`, `model.api_key`. Feito com o CLI do próprio Hermes
   (`hermes config set|unset`), que valida as chaves contra o esquema da versão
   instalada e trata das migrações — em vez de reescrever o YAML à mão.
2. `$HERMES_HOME/.env` → a chave do fornecedor na variável que o **perfil de
   modelo** do Hermes espera (`DEEPSEEK_API_KEY`, `ANTHROPIC_API_KEY`,
   `GEMINI_API_KEY`, …). A lista de perfis e das suas variáveis é lida do
   próprio container (`/opt/hermes/plugins/model-providers/*/__init__.py`), para
   não envelhecer com o upstream.

Quando o fornecedor do IQ OS não tem perfil equivalente no Hermes (OpenAI, Groq
e Mistral, por exemplo — o Hermes trata esses por `custom`), a configuração vai
toda para o `config.yaml`, com `provider: custom` + `base_url` + `api_key`.

Aplica-se ainda a **pesquisa web** do agente: a plataforma já corre um SearXNG
(`http://searxng:8080` dentro da rede do compose), pelo que o Hermes passa a
pesquisar por lá em vez de exigir uma chave externa.

Rotas em `api/hermes_agent_routes.py` (`/hermes-agent/*`).
"""
from __future__ import annotations

import json
import logging
import os
import re
import shlex
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from api import providers_service

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
PROJECT_DIR = ROOT
COMPOSE_FILE = PROJECT_DIR / "docker-compose.yml"

DOC_ID = "hermes_agent"
CONTAINER = os.getenv("HERMES_AGENT_CONTAINER", "finance-llm-hermes-agent")
COMPOSE_PROFILE = "agents"
COMPOSE_SERVICE = "hermes-agent"
HERMES_HOME = "/opt/data"
ENV_PATH = f"{HERMES_HOME}/.env"
PROVIDERS_DIR = "/opt/hermes/plugins/model-providers"
CONTAINER_USER = "hermes"

EXEC_TIMEOUT = 60.0
RECREATE_TIMEOUT = 600.0
REGISTRY_TTL = 300.0

#: Nome do fornecedor no IQ OS → nome do perfil no Hermes, quando os nomes
#: diferem. Só entra aqui o que não se descobre sozinho: o resto é casado pelo
#: nome do diretório do perfil.
PROVIDER_ALIASES: Dict[str, str] = {
    "google": "gemini",
    "mistral-ai": "mistral",
    "ollama-cloud": "ollama-cloud",
}

#: Variáveis que a plataforma gere no `.env` do container. Ao trocar de
#: fornecedor, as que não forem reescritas são **removidas** (senão ficava lá a
#: chave antiga, e o Hermes podia escolhê-la em modo `auto`).
MANAGED_ENV_KEYS: Tuple[str, ...] = (
    "DEEPSEEK_API_KEY",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_TOKEN",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "GROQ_API_KEY",
    "MISTRAL_API_KEY",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "XAI_API_KEY",
    "OLLAMA_API_KEY",
    "OLLAMA_BASE_URL",
    "SEARXNG_URL",
    "BRAVE_SEARCH_API_KEY",
)

ENV_HEADER = "# --- Hermes Agent: valores geridos pela plataforma IQ OS (não editar à mão) ---"

#: Valores por omissão das definições (o que a UI mostra e grava).
DEFAULTS: Dict[str, Any] = {
    "llm_provider": "deepseek",
    "llm_model": "",
    "llm_base_url": "",
    "llm_custom_key": "",
    "search_provider": "searxng",
    "searxng_url": "http://searxng:8080",
    "brave_key": "",
    "updated_at": "",
    "updated_by": "",
    "applied_at": "",
}

SEARCH_PROVIDERS: List[Dict[str, str]] = [
    {
        "id": "searxng",
        "label": "SearXNG da plataforma",
        "description": "Usa o metabuscador que já corre no compose (sem chave externa).",
    },
    {
        "id": "brave",
        "label": "Brave Search",
        "description": "Usa a chave BRAVE_API_KEY da plataforma.",
    },
    {
        "id": "off",
        "label": "Desligada",
        "description": "O agente não pesquisa na web (ficam só as ferramentas locais).",
    },
]

_REGISTRY_CACHE: Dict[str, Any] = {"at": 0.0, "data": {}}
_REGISTRY_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# Definições (Elasticsearch `finance_settings`, documento `hermes_agent`)
# ---------------------------------------------------------------------------
def _es():
    from api.elasticsearch_client import get_es_client, SETTINGS_INDEX

    client = get_es_client()
    if client is None:
        raise RuntimeError("Elasticsearch indisponível: não é possível ler as definições do Hermes Agent.")
    return client, SETTINGS_INDEX


def read_settings() -> Dict[str, Any]:
    """Definições atuais (tolerante a falhas: devolve os valores por omissão)."""
    settings = dict(DEFAULTS)
    try:
        client, index = _es()
        document = client.get(index=index, id=DOC_ID, ignore=[404])
        stored = (document or {}).get("_source") or {}
        if isinstance(stored.get(DOC_ID), dict):
            settings.update(stored[DOC_ID])
        elif isinstance(stored, dict):
            settings.update({key: value for key, value in stored.items() if key in DEFAULTS})
    except Exception as exc:
        logger.info("Hermes Agent: definições indisponíveis (%s); uso as por omissão.", exc)
    return settings


def save_settings(patch: Dict[str, Any], user: str = "") -> Dict[str, Any]:
    """Grava um patch das definições e devolve-as completas."""
    client, index = _es()
    settings = read_settings()
    for key, value in patch.items():
        if key in DEFAULTS:
            settings[key] = value
    settings["updated_at"] = _now()
    if user:
        settings["updated_by"] = user
    client.index(index=index, id=DOC_ID, document={DOC_ID: settings}, refresh=True)
    return settings


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Perfis de modelo do Hermes (lidos do container)
# ---------------------------------------------------------------------------
def provider_registry(force: bool = False) -> Dict[str, List[str]]:
    """Perfis de modelo do Hermes → variáveis de ambiente que cada um aceita.

    Lido de `/opt/hermes/plugins/model-providers/*/__init__.py` dentro do
    container, para acompanhar a versão instalada em vez de a fixar no código.
    """
    with _REGISTRY_LOCK:
        cached = _REGISTRY_CACHE["data"]
        fresh = cached and (time.time() - _REGISTRY_CACHE["at"]) < REGISTRY_TTL
        if fresh and not force:
            return dict(cached)

    script = (
        "import json, os, re\n"
        f"root = {PROVIDERS_DIR!r}\n"
        "out = {}\n"
        "if os.path.isdir(root):\n"
        "    for name in sorted(os.listdir(root)):\n"
        "        path = os.path.join(root, name, '__init__.py')\n"
        "        if not os.path.isfile(path):\n"
        "            continue\n"
        "        text = open(path, encoding='utf-8', errors='ignore').read()\n"
        "        match = re.search(r'env_vars\\s*=\\s*\\(([^)]*)\\)', text)\n"
        "        envs = re.findall(r'[\"\\']([A-Z0-9_]+)[\"\\']', match.group(1)) if match else []\n"
        "        out[name] = envs\n"
        "print(json.dumps(out))\n"
    )
    code, stdout, _ = _exec(["sh", "-c", f"python3 -c {shlex.quote(script)}"], as_user=True)
    registry: Dict[str, List[str]] = {}
    if code == 0 and stdout.strip():
        try:
            registry = json.loads(stdout.strip().splitlines()[-1])
        except Exception as exc:
            logger.info("Hermes Agent: registo de perfis ilegível (%s).", exc)

    if registry:
        with _REGISTRY_LOCK:
            _REGISTRY_CACHE.update({"at": time.time(), "data": registry})
    return registry


def hermes_provider_for(
    provider: str,
    registry: Optional[Dict[str, List[str]]] = None,
    preferred_env: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """Perfil do Hermes e variável da chave para um fornecedor do IQ OS.

    Devolve `(None, None)` quando não há perfil equivalente: nesse caso a
    configuração segue por `custom` (OpenAI-compatível), com o `base_url` e a
    chave no `config.yaml`.

    Quando o perfil aceita várias variáveis (o `gemini`, por exemplo, lê
    `GOOGLE_API_KEY` ou `GEMINI_API_KEY`), prefere-se a que a própria
    plataforma usa — assim há um nome só em todo o sistema.
    """
    registry = registry if registry is not None else provider_registry()
    candidate = PROVIDER_ALIASES.get(provider, provider)
    if candidate not in registry:
        return None, None
    envs = registry[candidate]
    if not envs:
        return candidate, None
    if preferred_env and preferred_env in envs:
        return candidate, preferred_env
    return candidate, envs[0]


# ---------------------------------------------------------------------------
# Resolução do modelo
# ---------------------------------------------------------------------------
def resolve_llm(settings: Dict[str, Any], user_id: Optional[str] = None) -> Dict[str, Any]:
    """Resolve o fornecedor, a chave, o `base_url` e o modelo a aplicar.

    A ordem é a mesma do MiroFish: **chave personalizada** (escrita à mão na UI)
    e, sem ela, a **chave do fornecedor que a plataforma já tem** para o
    utilizador (`finance_provider_keys`), caindo para as variáveis de ambiente
    do processo quando a conta ainda não tem chave própria.
    """
    provider = str(settings.get("llm_provider") or DEFAULTS["llm_provider"])
    spec = providers_service.PROVIDERS_BY_ID.get(provider)
    registry = provider_registry()
    hermes_provider, env_var = hermes_provider_for(
        provider, registry, preferred_env=(spec or {}).get("env")
    )

    custom_key = str(settings.get("llm_custom_key") or "").strip()
    if custom_key:
        key, source = custom_key, "custom"
    elif spec is None:
        key, source = "", "none"
    else:
        key, source = providers_service.resolve_key(user_id, provider)

    base_url = str(settings.get("llm_base_url") or "").strip()
    if not base_url and spec is not None:
        base_url = providers_service.resolve_provider_url(user_id, provider) or str(spec.get("base_url") or "")
    model = str(settings.get("llm_model") or "").strip()
    if not model and spec is not None:
        model = providers_service.resolve_provider_model(user_id, provider) or str(spec.get("default_model") or "")

    return {
        "provider": provider,
        "label": (spec or {}).get("label") or provider,
        "known": spec is not None,
        "hermes_provider": hermes_provider,
        "env_var": env_var,
        "key": key or "",
        "source": source,
        "base_url": base_url,
        "model": model,
        "uses_custom_provider": hermes_provider is None,
    }


def build_plan(
    settings: Dict[str, Any],
    user_id: Optional[str] = None,
    *,
    registry: Optional[Dict[str, List[str]]] = None,
) -> Dict[str, Any]:
    """O que escrever no container, sem tocar em nada (função pura).

    Devolve `config` (chaves do `config.yaml` → valor ou `None` para remover),
    `env` (variáveis a gravar no `.env`) e `notes` (o que explicar ao
    utilizador).
    """
    resolved = resolve_llm(settings, user_id)
    notes: List[str] = []
    config: Dict[str, Optional[str]] = {}
    env: Dict[str, str] = {}

    if not resolved["known"]:
        return {
            "resolved": resolved,
            "config": {},
            "env": {},
            "clear_env": list(MANAGED_ENV_KEYS),
            "notes": [f"Fornecedor desconhecido: {resolved['provider']}."],
        }

    if not resolved["key"]:
        notes.append(
            f"O fornecedor {resolved['label']} ainda não tem chave na plataforma "
            "(Definições → Fornecedores de IA) nem chave personalizada."
        )

    model = resolved["model"]
    if not model:
        notes.append("Sem modelo indicado e o fornecedor não tem modelo por omissão: indique um modelo.")

    hermes_provider = resolved["hermes_provider"]
    if hermes_provider:
        # Perfil nativo: a chave vai na variável que o perfil espera.
        config["model.provider"] = hermes_provider
        config["model.default"] = model or None
        # O perfil já sabe o endpoint: um `base_url` a mais só pode atrapalhar.
        config["model.base_url"] = None
        config["model.api_key"] = None
        # Sem chave não se escreve a variável: um `DEEPSEEK_API_KEY=` vazio
        # deixaria o `.env` a mentir (dizia que a chave lá estava).
        if resolved["env_var"] and resolved["key"]:
            env[resolved["env_var"]] = resolved["key"]
        notes.append(
            f"Perfil nativo do Hermes: `{hermes_provider}`"
            + (f" (chave em `{resolved['env_var']}`)." if resolved["env_var"] else ".")
        )
    else:
        # Sem perfil equivalente: `custom` (OpenAI-compatível) com tudo explícito.
        config["model.provider"] = "custom"
        config["model.default"] = model or None
        config["model.base_url"] = _container_url(resolved["base_url"]) or None
        config["model.api_key"] = resolved["key"] or None
        notes.append(
            f"Sem perfil equivalente no Hermes: usa-se `custom` com "
            f"`{_container_url(resolved['base_url']) or '(base_url em falta)'}`."
        )

    # Pesquisa web do agente: a plataforma já corre um SearXNG.
    search = str(settings.get("search_provider") or DEFAULTS["search_provider"])
    if search == "searxng":
        url = str(settings.get("searxng_url") or DEFAULTS["searxng_url"]).strip()
        if url:
            env["SEARXNG_URL"] = url
            notes.append(f"Pesquisa web pelo SearXNG da plataforma (`{url}`).")
    elif search == "brave":
        key = str(settings.get("brave_key") or "").strip() or os.getenv("BRAVE_API_KEY", "")
        if key:
            env["BRAVE_SEARCH_API_KEY"] = key
            notes.append("Pesquisa web pela Brave Search (chave da plataforma).")
        else:
            notes.append("Brave escolhida mas sem chave: defina-a aqui ou em BRAVE_API_KEY.")

    if not resolved["key"] and not env:
        notes.append("Sem chave não há como configurar o modelo — o agente fica sem LLM.")

    keep = set(env)
    clear = [name for name in MANAGED_ENV_KEYS if name not in keep]
    return {"resolved": resolved, "config": config, "env": env, "clear_env": clear, "notes": notes}


def _container_url(url: str) -> str:
    """Reescreve endereços de loopback para o host, vistos de dentro do container.

    Um `http://127.0.0.1:11434/v1` (Ollama no host) não existe dentro do
    container: lá, o host é `host.docker.internal`.
    """
    value = str(url or "").strip()
    if not value:
        return ""
    return re.sub(
        r"^(https?://)(127\.0\.0\.1|localhost)(?=[:/]|$)",
        r"\1host.docker.internal",
        value,
    )


# ---------------------------------------------------------------------------
# `.env` — leitura e escrita (funções puras, testáveis)
# ---------------------------------------------------------------------------
def _env_names(text: str) -> List[str]:
    """Nomes das variáveis definidas num `.env` (com valor não vazio)."""
    names: List[str] = []
    for line in str(text or "").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, _, value = stripped.partition("=")
        name = name.strip()
        if name and value.strip():
            names.append(name)
    return names


def upsert_env(text: str, values: Dict[str, str], managed: Sequence[str] = MANAGED_ENV_KEYS) -> Tuple[str, List[str], List[str]]:
    """Grava/atualiza `values` no `.env` e limpa as variáveis geridas que sobram.

    Preserva comentários, linhas desconhecidas e a ordem; devolve
    `(novo_texto, escritos, removidos)`.
    """
    lines = str(text or "").splitlines()
    written: List[str] = []
    removed: List[str] = []
    seen: set = set()

    out: List[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            out.append(line)
            continue
        name = stripped.split("=", 1)[0].strip()
        if name in values:
            out.append(f"{name}={values[name]}")
            written.append(name)
            seen.add(name)
        elif name in managed:
            removed.append(name)  # variável gerida que já não se aplica
        else:
            out.append(line)

    for name, value in values.items():
        if name in seen:
            continue
        out.append(f"{name}={value}")
        written.append(name)

    # Uma linha em branco antes do bloco gerido, se ainda não existir o cabeçalho.
    if (written or removed) and ENV_HEADER not in out:
        out.append("")
        out.append(ENV_HEADER)

    text_out = "\n".join(out).rstrip("\n") + "\n"
    return text_out, written, removed


def _mask(value: str, keep: int = 4) -> str:
    text = str(value or "")
    if not text:
        return ""
    if len(text) <= keep:
        return "•" * len(text)
    return f"{text[:keep]}…{text[-4:]}" if len(text) > keep + 4 else f"{text[:keep]}…"


# ---------------------------------------------------------------------------
# Acesso ao container
# ---------------------------------------------------------------------------
def docker_path() -> Optional[str]:
    return shutil.which("docker")


def container_running() -> bool:
    code, stdout, _ = _exec_raw(["ps", "--filter", f"name={CONTAINER}", "--format", "{{.Names}}"])
    return code == 0 and CONTAINER in stdout


def _exec_raw(args: Sequence[str], *, input_text: Optional[str] = None, timeout: float = EXEC_TIMEOUT):
    docker = docker_path()
    if not docker:
        raise RuntimeError(
            "O comando `docker` não está disponível neste processo: para configurar o Hermes Agent, "
            "corra o backend no host (não dentro de um container) ou monte o socket do Docker."
        )
    command = [docker, *args]
    try:
        process = subprocess.run(
            command,
            input=input_text,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"O comando `{' '.join(command)}` excedeu {timeout:.0f}s.") from exc
    except OSError as exc:
        raise RuntimeError(f"Falha ao executar `{' '.join(command)}`: {exc}") from exc
    return process.returncode, process.stdout or "", process.stderr or ""


def _exec(args: Sequence[str], *, as_user: bool = False, input_text: Optional[str] = None, timeout: float = EXEC_TIMEOUT):
    """Executa um comando no container (por omissão como o utilizador `hermes`)."""
    prefix = ["exec"]
    if as_user:
        prefix += ["-u", CONTAINER_USER]
    if input_text is not None:
        prefix += ["-i"]
    return _exec_raw([*prefix, CONTAINER, *args], input_text=input_text, timeout=timeout)


def hermes_cli(args: Sequence[str], *, input_text: Optional[str] = None, timeout: float = EXEC_TIMEOUT):
    """Corre o CLI do Hermes dentro do container, como o utilizador `hermes`."""
    return _exec(["hermes", *args], as_user=True, input_text=input_text, timeout=timeout)


def read_container_env() -> str:
    code, stdout, _ = _exec(["cat", ENV_PATH], as_user=True)
    if code != 0:
        return ""
    return stdout


def write_container_env(text: str) -> None:
    """Escreve o `.env` do container preservando o dono do ficheiro."""
    _exec(["sh", "-c", f"cat > {ENV_PATH} && chmod 600 {ENV_PATH}"], input_text=text)


def read_config_values(keys: Sequence[str]) -> Dict[str, Optional[str]]:
    """Lê valores do `config.yaml` pelo CLI (`model.provider`, `model.default`, …)."""
    values: Dict[str, Optional[str]] = {}
    for key in keys:
        code, stdout, stderr = hermes_cli(["config", "get", key])
        if code == 0 and stdout.strip():
            values[key] = stdout.strip().splitlines()[-1].strip()
        else:
            values[key] = None
    return values


def apply_config(config: Dict[str, Optional[str]]) -> List[str]:
    """Aplica as chaves do `config.yaml` pelo CLI do Hermes (set/unset).

    `hermes config unset` sai com código 1 quando a chave já não existe — mas o
    estado pedido («não definida») está cumprido, por isso isso conta como
    sucesso e é relatado.
    """
    applied: List[str] = []
    for key, value in config.items():
        if value in (None, ""):
            code, _, stderr = hermes_cli(["config", "unset", key])
            message = (stderr or "").lower()
            if code == 0 or "not set" in message:
                applied.append(f"-{key}")
            else:
                logger.info("Hermes Agent: não removi %s (%s).", key, stderr.strip()[:120])
            continue
        code, _, stderr = hermes_cli(["config", "set", key, str(value)])
        if code == 0:
            applied.append(f"{key}={_mask(str(value)) if key.endswith('api_key') else value}")
        else:
            raise RuntimeError(f"`hermes config set {key}` falhou: {stderr.strip()[:300]}")
    return applied


def compose_recreate(timeout: float = RECREATE_TIMEOUT) -> str:
    """Recria o container do Hermes Agent para aplicar a configuração."""
    docker = docker_path()
    if not docker:
        raise RuntimeError(
            "O comando `docker` não está disponível neste processo: recrie o container à mão "
            f"(`docker compose --profile {COMPOSE_PROFILE} up -d --force-recreate {COMPOSE_SERVICE}`)."
        )
    if not COMPOSE_FILE.exists():
        raise RuntimeError(f"docker-compose.yml não encontrado em {COMPOSE_FILE}.")

    command = [
        docker,
        "compose",
        "-f",
        str(COMPOSE_FILE),
        "--profile",
        COMPOSE_PROFILE,
        "up",
        "-d",
        "--force-recreate",
        COMPOSE_SERVICE,
    ]
    try:
        process = subprocess.run(
            command,
            cwd=str(PROJECT_DIR),
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"A recriação do container excedeu {timeout:.0f}s.") from exc
    if process.returncode != 0:
        raise RuntimeError(f"`docker compose up` falhou: {(process.stderr or process.stdout).strip()[:400]}")
    return (process.stdout or "").strip()[:400]


# ---------------------------------------------------------------------------
# Aplicar
# ---------------------------------------------------------------------------
def apply_settings(
    user_id: Optional[str] = None,
    user: str = "",
    *,
    patch: Optional[Dict[str, Any]] = None,
    recreate: bool = True,
) -> Dict[str, Any]:
    """Resolve o fornecedor, escreve no container e (por omissão) recria-o."""
    if patch:
        save_settings(patch, user)
    settings = read_settings()
    plan = build_plan(settings, user_id)

    if not plan["env"] and not plan["resolved"]["key"]:
        raise RuntimeError(
            "Nada para aplicar: escolha um fornecedor com chave na plataforma "
            "(Definições → Fornecedores de IA) ou indique uma chave personalizada."
        )
    if not plan["resolved"]["key"]:
        # Sem chave de modelo não vale a pena recriar o container: ficaria sem
        # LLM e a pesquisa configurada não compensa a interrupção do serviço.
        raise RuntimeError(
            f"O fornecedor {plan['resolved']['label']} não tem chave: guarde-a em "
            "Definições → Fornecedores de IA, escreva uma chave personalizada, ou deixe "
            "`BRAVE_API_KEY`/`DEEPSEEK_API_KEY`… no ambiente do backend."
        )

    applied_config = apply_config(plan["config"])

    previous = read_container_env()
    new_env, written, removed = upsert_env(previous, plan["env"])
    if new_env != previous:
        write_container_env(new_env)

    recreated = ""
    if recreate:
        recreated = compose_recreate()

    saved = save_settings({"applied_at": _now()}, user)
    # A chave nunca sai daqui em claro: a resposta passa por uma API e por
    # registos, e já está escrita no container onde é precisa.
    resolved = dict(plan["resolved"])
    resolved["key"] = _mask(resolved["key"])
    return {
        "applied_at": saved["applied_at"],
        "resolved": resolved,
        "config": applied_config,
        "env_written": written,
        "env_removed": removed,
        "recreated": bool(recreate),
        "compose_output": recreated,
        "notes": plan["notes"],
    }


# ---------------------------------------------------------------------------
# Diagnóstico e vista para a UI
# ---------------------------------------------------------------------------
CONFIG_KEYS = ("model.provider", "model.default", "model.base_url", "model.api_key")


def diagnose(user_id: Optional[str] = None) -> Dict[str, Any]:
    """Compara o que está no container com o que a plataforma quer aplicar."""
    settings = read_settings()
    plan = build_plan(settings, user_id)

    report: Dict[str, Any] = {
        "container": CONTAINER,
        "docker_available": bool(docker_path()),
        "running": False,
        "config": {},
        "env_keys": [],
        "applied_at": settings.get("applied_at") or "",
        "wanted": {
            "provider": plan["config"].get("model.provider"),
            "model": plan["config"].get("model.default"),
            "base_url": plan["config"].get("model.base_url"),
            "env": sorted(plan["env"]),
        },
        "notes": plan["notes"],
        "in_sync": False,
        "problems": [],
    }

    if not report["docker_available"]:
        report["problems"].append(
            "Sem acesso ao `docker`: o backend está dentro de um container e não pode ler nem escrever no "
            "Hermes Agent. Corra o backend no host ou monte o socket do Docker."
        )
        return report

    report["running"] = container_running()
    if not report["running"]:
        report["problems"].append(
            f"O container `{CONTAINER}` não está a correr (`docker compose --profile {COMPOSE_PROFILE} up -d "
            f"{COMPOSE_SERVICE}`)."
        )
        return report

    values = read_config_values(CONFIG_KEYS)
    masked = dict(values)
    if masked.get("model.api_key"):
        masked["model.api_key"] = _mask(masked["model.api_key"] or "")
    report["config"] = masked
    report["config_has_api_key"] = bool(values.get("model.api_key"))

    names = set(_env_names(read_container_env()))
    report["env_keys"] = sorted(name for name in names if name in MANAGED_ENV_KEYS)

    wanted_env = set(plan["env"])
    provider_ok = values.get("model.provider") == plan["config"].get("model.provider")
    model_ok = values.get("model.default") == plan["config"].get("model.default")
    env_ok = wanted_env.issubset(names)
    key_ok = bool(values.get("model.api_key")) or env_ok

    if not key_ok:
        report["problems"].append("O agente não tem chave de modelo: configure-a e aplique.")
    if not provider_ok or not model_ok:
        report["problems"].append(
            "O container não está com o fornecedor/modelo da plataforma — aplique as definições."
        )
    if not env_ok:
        report["problems"].append(
            "Faltam variáveis no `.env` do container: " + ", ".join(sorted(wanted_env - names)) + "."
        )

    report["in_sync"] = provider_ok and model_ok and env_ok and key_ok
    return report


def llm_candidates(user_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Fornecedores do IQ OS com o estado das chaves (para o seletor da UI)."""
    registry = provider_registry()
    out: List[Dict[str, Any]] = []
    for spec in providers_service.PROVIDERS:
        provider_id = spec["id"]
        key, origin = providers_service.resolve_key(user_id, provider_id)
        hermes_provider, env_var = hermes_provider_for(provider_id, registry, preferred_env=spec.get("env"))
        out.append(
            {
                "id": provider_id,
                "label": spec.get("label") or provider_id,
                "usable": bool(key) or bool(spec.get("key_optional")),
                "key_hint": _mask(key) if key else "",
                "key_source": origin,
                "default_model": providers_service.resolve_provider_model(user_id, provider_id)
                or spec.get("default_model"),
                "models": list(spec.get("models") or []),
                "base_url": providers_service.resolve_provider_url(user_id, provider_id)
                or spec.get("base_url"),
                "hermes_provider": hermes_provider,
                "hermes_env": env_var,
                "mode": "perfil nativo" if hermes_provider else "custom (OpenAI-compatível)",
            }
        )
    return out


def _mask_value(key: str, value: Any) -> Any:
    """Mascara um valor só quando é mesmo uma chave com conteúdo.

    `None` (remover) e `""` têm de passar intactos, senão a UI mostra uma chave
    mascarada onde o plano diz «remover».
    """
    if value in (None, ""):
        return value
    return _mask(str(value)) if key.endswith("api_key") else value


def settings_view(user_id: Optional[str] = None, user: str = "") -> Dict[str, Any]:
    """Estado completo para a página (definições, plano, diagnóstico e comandos)."""
    settings = read_settings()
    plan = build_plan(settings, user_id)
    resolved = plan["resolved"]
    return {
        "about": {
            "container": CONTAINER,
            "profile": COMPOSE_PROFILE,
            "service": COMPOSE_SERVICE,
            "home": HERMES_HOME,
            "note": (
                "O Hermes Agent é um agente independente: a plataforma liga-o ao fornecedor de IA que já "
                "tem guardado, escrevendo no volume do container e recriando-o."
            ),
        },
        "settings": {
            "llm_provider": settings.get("llm_provider"),
            "llm_model": settings.get("llm_model"),
            "llm_base_url": settings.get("llm_base_url"),
            "llm_custom_key_set": bool(settings.get("llm_custom_key")),
            "search_provider": settings.get("search_provider"),
            "searxng_url": settings.get("searxng_url"),
            "brave_key_set": bool(settings.get("brave_key")),
            "applied_at": settings.get("applied_at") or "",
            "updated_at": settings.get("updated_at") or "",
            "updated_by": settings.get("updated_by") or "",
        },
        "resolved": {**resolved, "key": _mask(resolved["key"])},
        "plan": {
            "config": {key: _mask_value(key, value) for key, value in plan["config"].items()},
            "env": sorted(plan["env"]),
            "clear_env": plan["clear_env"],
            "notes": plan["notes"],
        },
        "providers": llm_candidates(user_id),
        "search_providers": SEARCH_PROVIDERS,
        "registry": {
            "total": len(provider_registry()),
            "native": sorted(provider_registry())[:40],
        },
        "diagnose": diagnose(user_id),
        "commands": {
            "apply": "docker compose --profile agents up -d --force-recreate hermes-agent",
            "logs": f"docker logs --tail 100 {CONTAINER}",
            "status": f"docker exec -u {CONTAINER_USER} {CONTAINER} hermes status",
            "config": f"docker exec -u {CONTAINER_USER} {CONTAINER} hermes config show",
        },
    }


__all__ = [
    "CONFIG_KEYS",
    "CONTAINER",
    "DEFAULTS",
    "MANAGED_ENV_KEYS",
    "SEARCH_PROVIDERS",
    "apply_config",
    "apply_settings",
    "build_plan",
    "compose_recreate",
    "container_running",
    "diagnose",
    "docker_path",
    "hermes_cli",
    "hermes_provider_for",
    "llm_candidates",
    "provider_registry",
    "read_config_values",
    "read_container_env",
    "read_settings",
    "resolve_llm",
    "save_settings",
    "settings_view",
    "upsert_env",
    "write_container_env",
]
