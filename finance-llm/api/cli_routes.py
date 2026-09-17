"""Execução do CLI a partir da interface web (`/cli/*`).

A página "Terminal" do frontend envia uma linha de comando (ex.:
`contracts search "obras" --year 2025`) e este módulo corre o CLI num
subprocesso, devolvendo stdout/stderr e o código de saída.

Segurança: **não** há shell pelo meio (`shell=False`, argumentos em lista) e
apenas é permitido o que o próprio parser do CLI define, com uma lista de
exceções para operações de conta (login, registo, logout, alteração de
palavra-passe). O token da sessão do pedido é injetado no CLI, pelo que os
comandos autenticados correm como o utilizador que está a usar o browser.
"""
from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Annotated, Any, Dict, List, Set, Tuple

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth_routes import CurrentSession, require_session

ROOT = Path(__file__).resolve().parents[1]

router = APIRouter(prefix="/cli", tags=["cli"])

MAX_OUTPUT_BYTES = 200_000
MAX_ARGS = 24
MAX_ARG_LEN = 400
DEFAULT_TIMEOUT = 120
SLOW_TIMEOUT = 900

# Comandos de topo que podem ser executados a partir do browser.
ALLOWED_COMMANDS: Set[str] = {
    "status",
    "contracts",
    "companies",
    "entities",
    "market",
    "forecast",
    "chat",
    "users",
    "search",
    "open",
    "config",
    "auth",
}

# Operações que alteram a conta ou a configuração local: não são executáveis
# a partir do browser (têm de ser feitas no terminal ou nas Definições).
BLOCKED: Set[Tuple[str, ...]] = {
    ("auth", "login"),
    ("auth", "register"),
    ("auth", "logout"),
    ("auth", "password"),
    ("auth", "profile"),
    ("config",),
    ("open",),
}

# Opções que o servidor decide (evita apontar o CLI para outro servidor).
BLOCKED_FLAGS = {"--api", "--token"}

SLOW_PATHS: Set[Tuple[str, ...]] = {
    ("forecast",),
    ("chat",),
    ("contracts", "analytics"),
    ("search",),
    ("entities", "stats"),
}


class CliRequest(BaseModel):
    command: str = Field(..., max_length=1000, description="Linha de comando, sem `python -m cli`")


class CliResult(BaseModel):
    command: str
    argv: List[str]
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False


def _parser_tree(parser: argparse.ArgumentParser) -> Dict[str, Any]:
    """Converte o parser do CLI numa árvore `{comando: {subcomando: {...}}}`."""
    tree: Dict[str, Any] = {}
    for action in parser._actions:  # noqa: SLF001 - não há API pública para isto
        if isinstance(action, argparse._SubParsersAction):  # noqa: SLF001
            for name, sub in action.choices.items():
                tree[name] = _parser_tree(sub)
    return tree


def _cli_tree() -> Dict[str, Any]:
    """Árvore de comandos do CLI (importado do próprio definidor de argumentos)."""
    try:
        from cli.main import build_parser  # importação leve: argparse + requests

        return _parser_tree(build_parser())
    except Exception:  # noqa: BLE001 - se o CLI não estiver disponível, degrada
        return {}


def allowed_commands() -> List[Dict[str, Any]]:
    """Catálogo de comandos permitidos (alimenta a paleta da interface)."""
    tree = _cli_tree()
    catalog: List[Dict[str, Any]] = []
    for name in sorted(ALLOWED_COMMANDS & set(tree or {})):
        # Só desaparece do catálogo o comando bloqueado por inteiro (`config`, `open`);
        # em `auth` mostra-se apenas o que é permitido (whoami, sessions).
        if (name,) in BLOCKED:
            continue
        subcommands = sorted(sub for sub in (tree.get(name) or {}) if (name, sub) not in BLOCKED)
        catalog.append({"command": name, "subcommands": subcommands})
    return catalog


def _command_path(argv: List[str]) -> Tuple[str, ...]:
    """Caminho do comando (topo + ação), ignorando as opções."""
    words = [arg for arg in argv if not arg.startswith("-")]
    return tuple(words[:2]) if len(words) > 1 else tuple(words[:1])


def _validate(argv: List[str]) -> None:
    """Valida a linha de comando contra a lista de permitidos."""
    if not argv:
        raise HTTPException(status_code=422, detail="Escreva um comando (ex.: `status`).")
    if len(argv) > MAX_ARGS:
        raise HTTPException(status_code=422, detail=f"Demasiados argumentos (máximo {MAX_ARGS}).")
    for arg in argv:
        if len(arg) > MAX_ARG_LEN:
            raise HTTPException(status_code=422, detail="Argumento demasiado longo.")
        if any(char in arg for char in ("\n", "\r", "\x00")):
            raise HTTPException(status_code=422, detail="Argumentos com caracteres inválidos.")
        flag = arg.split("=", 1)[0]
        if flag in BLOCKED_FLAGS:
            raise HTTPException(status_code=403, detail=f"A opção {flag} é definida pelo servidor.")

    head = argv[0]
    if head.startswith("-"):
        raise HTTPException(status_code=422, detail="Comece pelo comando (ex.: `status`, `contracts search …`).")
    if head not in ALLOWED_COMMANDS:
        raise HTTPException(
            status_code=403,
            detail=f"«{head}» não está disponível no terminal da interface. Use: {', '.join(sorted(ALLOWED_COMMANDS))}.",
        )

    path = _command_path(argv)
    if any(path[: len(blocked)] == blocked for blocked in BLOCKED):
        raise HTTPException(
            status_code=403,
            detail="Esta operação altera a conta ou a configuração local. Faça-a no terminal ou nas Definições.",
        )

    tree = _cli_tree()
    if not tree:
        return
    if head not in tree:
        raise HTTPException(status_code=403, detail=f"Comando «{head}» desconhecido.")
    actions = sorted(tree[head])
    if not actions:
        return
    if len(path) < 2:
        raise HTTPException(status_code=422, detail=f"Indique a ação de «{head}»: {', '.join(actions)}.")
    if path[1] not in tree[head]:
        raise HTTPException(
            status_code=422,
            detail=f"Ação «{path[1]}» inválida para «{head}». Opções: {', '.join(actions)}.",
        )


def _timeout_for(argv: List[str]) -> int:
    """Tempo máximo conforme o custo esperado do comando."""
    head = tuple(argv[:2]) if len(argv) > 1 else (argv[0],)
    if head in SLOW_PATHS or (argv[0],) in SLOW_PATHS:
        return SLOW_TIMEOUT
    return DEFAULT_TIMEOUT


def _truncate(text: str) -> str:
    if len(text) <= MAX_OUTPUT_BYTES:
        return text
    return text[:MAX_OUTPUT_BYTES] + "\n… (saída truncada)"


@router.get("/commands")
def cli_commands(session: Annotated[CurrentSession, Depends(require_session)]) -> Dict[str, Any]:
    """Comandos disponíveis no terminal da interface (para a paleta de ajuda)."""
    return {
        "commands": allowed_commands(),
        "user": {"email": session.user.email, "name": session.user.name, "role": session.user.role},
    }


@router.post("/run", response_model=CliResult)
def cli_run(
    payload: CliRequest,
    session: Annotated[CurrentSession, Depends(require_session)],
) -> CliResult:
    """Executa um comando do CLI e devolve a saída (stdout/stderr e código)."""
    try:
        argv = shlex.split(payload.command.strip(), posix=False)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=f"Linha de comando inválida: {error}") from error

    # `posix=False` mantém as aspas nos argumentos: remove-as para os valores.
    argv = [arg[1:-1] if len(arg) >= 2 and arg[0] == arg[-1] and arg[0] in "\"'" else arg for arg in argv]
    _validate(argv)

    # O token vai por variável de ambiente (nunca em `argv`, que é visível na
    # lista de processos do sistema).
    command = [sys.executable, "-m", "cli", "--no-color", *argv]
    environment = {**os.environ, "FINANCE_LLM_TOKEN": session.token, "PYTHONIOENCODING": "utf-8"}
    display = f"python -m cli {' '.join(shlex.quote(arg) for arg in argv)}"

    started = time.perf_counter()
    timed_out = False
    try:
        completed = subprocess.run(  # noqa: S603 - sem shell, argumentos validados
            command,
            cwd=str(ROOT),
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_timeout_for(argv),
            check=False,
        )
        stdout, stderr, code = completed.stdout, completed.stderr, completed.returncode
    except subprocess.TimeoutExpired as error:
        timed_out = True
        stdout = error.stdout.decode("utf-8", "replace") if isinstance(error.stdout, bytes) else (error.stdout or "")
        stderr = (
            error.stderr.decode("utf-8", "replace") if isinstance(error.stderr, bytes) else (error.stderr or "")
        ) + f"\nTempo limite excedido ({_timeout_for(argv)}s)."
        code = 124
    except OSError as error:
        raise HTTPException(status_code=500, detail=f"Não foi possível executar o CLI: {error}") from error

    duration = int((time.perf_counter() - started) * 1000)
    return CliResult(
        command=display,
        argv=argv,
        exit_code=code,
        stdout=_truncate(stdout),
        stderr=_truncate(stderr),
        duration_ms=duration,
        timed_out=timed_out,
    )
