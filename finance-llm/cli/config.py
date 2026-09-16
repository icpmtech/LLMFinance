"""Configuração do CLI (URL da API e credenciais).

Fica em `~/.finance-llm/config.json` (ou em `$FINANCE_LLM_HOME`). A precedência é:

1. `--api` / `--token` na linha de comandos
2. variáveis de ambiente `FINANCE_LLM_API` / `FINANCE_LLM_TOKEN`
3. ficheiro de configuração
4. predefinição `http://127.0.0.1:8002`
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

DEFAULT_API = "http://127.0.0.1:8002"
CONFIG_DIR = Path(os.getenv("FINANCE_LLM_HOME") or (Path.home() / ".finance-llm"))
CONFIG_FILE = CONFIG_DIR / "config.json"


def load_config() -> Dict[str, Any]:
    """Lê o ficheiro de configuração (devolve `{}` se não existir/corrompido)."""
    try:
        if not CONFIG_FILE.exists():
            return {}
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_config(config: Dict[str, Any]) -> None:
    """Grava a configuração com permissões restritas (contém um token)."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(CONFIG_FILE, 0o600)
    except OSError:
        # Windows: o modo POSIX não se aplica.
        pass


def update_config(**changes: Any) -> Dict[str, Any]:
    """Atualiza chaves da configuração (com `None` a remover a chave)."""
    config = load_config()
    for key, value in changes.items():
        if value is None:
            config.pop(key, None)
        else:
            config[key] = value
    save_config(config)
    return config


def resolve_api_url(override: Optional[str] = None) -> str:
    """URL da API a usar nesta execução."""
    return (override or os.getenv("FINANCE_LLM_API") or load_config().get("api_url") or DEFAULT_API).rstrip("/")


def resolve_token(override: Optional[str] = None) -> Optional[str]:
    """Token de sessão a usar nesta execução."""
    return override or os.getenv("FINANCE_LLM_TOKEN") or load_config().get("token")


def config_path() -> Path:
    return CONFIG_FILE
