"""Gateway do **Hermes Agent** — o agente autónomo do IQ OS e tudo o que ele sabe fazer.

O container `hermes-agent` não é só um dashboard: é um **agente autónomo** com biblioteca
de *skills* própria (58 skills em 12 categorias — investigação, web, devops, email, media,
notas, produtividade, redes sociais, desenvolvimento, …) e **29 toolsets** (browser,
terminal, ficheiros, execução de código, visão, geração de imagem/vídeo, tarefas, memória,
pesquisa de sessões, cron, delegação, A2A, …). Expõe tudo isso numa API
OpenAI-compatível:

- `GET  /health`                — está vivo?
- `GET  /v1/models`             — o modelo servido (`hermes-agent`)
- `GET  /v1/toolsets`           — as capacidades declaradas (nome, etiqueta, descrição)
- `POST /v1/chat/completions`   — **delegação**: entrega-se a tarefa e o agente corre-a
  com as skills e as ferramentas dele (é o que dá ao Jarvis «todas as capacidades»).

O Jarvis usa este módulo por duas vias:

1. **Ferramentas** (`agent.ask`, `agent.skills`, `agent.capabilities`) — registadas no
   catálogo do gateway (`api/jarvis_gateway.py`), entram no plano como qualquer outra.
2. **Metamodelo** — `state()` alimenta o `/jarvis/meta`, para o Control Center mostrar se
   o agente está acessível, com que modelo e quantas skills/capacidades traz.

Nada aqui levanta exceção para fora: sem `docker` (skills), sem rede ou com o agente
desligado, devolve-se `{"available": False, "error": …}` e o Jarvis continua a funcionar
com os outros gateways.

Configuração
------------
``JARVIS_AGENT_URL``
    Base da API do agente. Dentro do compose é `http://hermes-agent:8642`; fora do Docker
    o porto publicado (`http://127.0.0.1:8642`) já responde por omissão.
``JARVIS_AGENT_KEY`` (ou ``HERMES_API_KEY``)
    Chave da API (`API_SERVER_KEY` do container).
``JARVIS_AGENT_TIMEOUT``
    Segundos que uma delegação pode demorar (por omissão 300 — o agente corre um ciclo
    autónomo completo, com skills e ferramentas, e pode levar minutos).
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

NAME = "Hermes Agent"
MODEL = "hermes-agent"

PROBE_TIMEOUT = 12.0
ASK_TIMEOUT = float(os.getenv("JARVIS_AGENT_TIMEOUT", "300"))
CACHE_TTL = 300.0
MAX_SKILLS = 120

#: Tecto por turno do histórico enviado ao agente (o contexto dele já é grande).
MAX_HISTORY_CHARS = int(os.getenv("JARVIS_AGENT_HISTORY_CHARS", "4000"))

#: Persona com que o agente é chamado quando o Jarvis lhe delega uma tarefa. Sem isto o
#: agente responde como modelo genérico: não sabe que dia é, não sabe que tem a
#: «pesquisa total» do IQ OS ao lado e não cita fontes.
PERSONA = os.getenv(
    "JARVIS_AGENT_PERSONA",
    "És o assistente do IQ OS (inteligência financeira, contratos públicos, empresas e "
    "pessoas). Falas sempre em português de Portugal, tratas o utilizador por «você» e "
    "és direto: respondes ao que foi perguntado, sem preâmbulos nem repetir a pergunta.",
)

#: Regras que fazem a diferença entre «modelo» e «assistente» (o resto vem das skills).
RULES = (
    "Regras:\n"
    "1. Tens skills próprias — lê a SKILL.md relevante antes de improvisar. Para dados "
    "portugueses/espanhóis usa a skill `pesquisa-total`; para perguntas que exigem "
    "**resposta fundamentada com citações `[n]`** (insolvências, atos societários, "
    "quanto vale um contrato), usa a skill `pesquisa-profunda`, que chama a Pesquisa "
    "profunda do IQ OS; para a web aberta, `websearch`.\n"
    "2. Não inventes: números, datas, nomes e URL têm de vir de uma fonte que consultaste.\n"
    "3. Cita sempre a fonte (nome do âmbito/ficheiro e URL quando existir).\n"
    "4. Se a pergunta for ambígua ou faltar um dado essencial, faz uma pergunta curta em "
    "vez de adivinhar; se for grande, divide-a e resolve-a por partes.\n"
    "5. Trabalha até ter a resposta: usa as ferramentas que precisares em vez de dizer "
    "que não consegues. Se uma via falhar, tenta outra (o terminal, o browser, a API).\n"
    "6. Termina com a resposta final pronta a ler — sem descrever como a obtiveste."
)

_WEEKDAYS = ("segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo")
_MONTHS = (
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
)

_CACHE: Dict[str, Tuple[float, Any]] = {}

#: Linhas da tabela do `hermes skills list` (nome │ categoria │ origem │ confiança │ estado).
_SKILL_ROW = re.compile(r"^[\u2502|]\s*(?P<name>[^│|]+?)\s*[\u2502|]\s*(?P<category>[^│|]*?)\s*[\u2502|]")


def base_url() -> str:
    """Base da API do agente (sem barra final)."""
    raw = (
        os.getenv("JARVIS_AGENT_URL")
        or os.getenv("HERMES_AGENT_URL")
        or "http://127.0.0.1:8642"
    )
    return raw.strip().rstrip("/")


def api_key() -> str:
    return (
        os.getenv("JARVIS_AGENT_KEY")
        or os.getenv("HERMES_API_KEY")
        or "iqos-hermes-api-key-please-change"
    ).strip()


def _headers() -> Dict[str, str]:
    return {"Authorization": f"Bearer {api_key()}", "Accept": "application/json"}


def _cache_get(key: str) -> Optional[Any]:
    entry = _CACHE.get(key)
    if entry is None:
        return None
    expires_at, value = entry
    if expires_at < time.time():
        _CACHE.pop(key, None)
        return None
    return value


def _cache_put(key: str, value: Any, ttl: float = CACHE_TTL) -> Any:
    _CACHE[key] = (time.time() + ttl, value)
    return value


def invalidate() -> None:
    """Esquece o que está em cache (usado nos testes e depois de mexer no agente)."""
    _CACHE.clear()


# --------------------------------------------------------------------------- API do agente
def _get_json(path: str, *, timeout: float = PROBE_TIMEOUT) -> Dict[str, Any]:
    url = f"{base_url()}{path}"
    with httpx.Client(timeout=timeout, headers=_headers()) as client:
        response = client.get(url)
        response.raise_for_status()
        data = response.json()
    return data if isinstance(data, dict) else {"data": data}


def _toolsets(*, timeout: float = PROBE_TIMEOUT) -> List[Dict[str, Any]]:
    """As capacidades declaradas do agente (`GET /v1/toolsets`)."""
    cached = _cache_get("toolsets")
    if cached is not None:
        return cached
    try:
        payload = _get_json("/v1/toolsets", timeout=timeout)
    except Exception as exc:  # rede, 401, 404 de versões antigas
        logger.info("Hermes Agent: capacidades indisponíveis (%s)", exc)
        return _cache_put("toolsets", [], ttl=60.0)
    rows = payload.get("data") or payload.get("toolsets") or []
    items = [
        {
            "id": str(row.get("name") or row.get("id") or ""),
            "label": str(row.get("label") or ""),
            "description": str(row.get("description") or ""),
        }
        for row in rows
        if isinstance(row, dict)
    ]
    return _cache_put("toolsets", items)


def _skills_dir() -> Optional[str]:
    """Pasta onde o container do agente guarda as skills (vista de fora).

    No compose o volume `hermes-data` é montado **read-only** no backend em
    `/hermes-data`, para se poder ler a biblioteca de skills sem depender do
    `docker` (que um backend a correr *dentro* de um container não tem).
    """
    raw = os.getenv("JARVIS_AGENT_SKILLS_DIR") or "/hermes-data/skills"
    path = raw.strip()
    return path if path and os.path.isdir(path) else None


def _skills_from_dir() -> List[Dict[str, Any]]:
    """Lê as skills diretamente do volume do agente (sem `docker`).

    Layout: `<raiz>/<categoria>/<skill>/SKILL.md`, com *front matter* YAML
    (`name`, `description`, `platforms`). Não se usa um parser de YAML para isto:
    basta tirar as duas linhas que interessam, e assim não há dependência nova.
    """
    root = _skills_dir()
    if not root:
        return []

    skills: List[Dict[str, Any]] = []
    for dirpath, _dirnames, filenames in os.walk(root):
        if "SKILL.md" not in filenames:
            continue
        category = os.path.basename(os.path.dirname(dirpath)) or ""
        fallback = os.path.basename(dirpath)
        name, description = "", ""
        try:
            with open(os.path.join(dirpath, "SKILL.md"), encoding="utf-8", errors="replace") as handle:
                lines = [next(handle, "") for _ in range(12)]
        except OSError:
            continue
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("name:") and not name:
                name = stripped.split(":", 1)[1].strip().strip('"\'')
            elif stripped.startswith("description:") and not description:
                description = stripped.split(":", 1)[1].strip().strip('"\'')
        skills.append(
            {
                "name": name or fallback,
                "category": category,
                "description": description[:160],
            }
        )
        if len(skills) >= MAX_SKILLS:
            break
    skills.sort(key=lambda item: (item["category"], item["name"]))
    return skills


def _skills_from_cli() -> List[Dict[str, Any]]:
    """Lê a biblioteca de skills do container pelo CLI do próprio Hermes.

    O `hermes skills list` é a fonte de verdade (é o que o agente tem instalado), mas
    exige `docker` acessível a quem corre o backend — como o painel «Motor do Hermes
    Agent». Sem isso, devolve-se lista vazia em vez de falhar.
    """
    try:
        from api import hermes_agent_settings  # noqa: PLC0415

        # `COLUMNS` largo: sem isso o CLI trunca os nomes das skills com «…»
        # (`songwriting-and-ai-mus…`). Vai por `sh -c` porque tem de chegar ao
        # ambiente **dentro** do container (o `docker exec` é quem o passa).
        code, stdout, stderr = hermes_agent_settings._exec(  # noqa: SLF001
            ["sh", "-c", "COLUMNS=200 hermes skills list"], as_user=True, timeout=60.0
        )
    except Exception as exc:
        logger.info("Hermes Agent: skills indisponíveis (%s)", exc)
        return []
    if code != 0:
        logger.info("Hermes Agent: `hermes skills list` falhou (%s)", (stderr or "").strip()[:200])
        return []

    skills: List[Dict[str, Any]] = []
    for line in (stdout or "").splitlines():
        match = _SKILL_ROW.match(line.strip())
        if not match:
            continue
        name = match.group("name").strip()
        if not name or name.lower() == "name" or set(name) <= set("─- "):
            continue
        skills.append({"name": name, "category": match.group("category").strip()})
        if len(skills) >= MAX_SKILLS:
            break
    return skills


def skills(*, query: str = "") -> Dict[str, Any]:
    """Skills instaladas no agente (com filtro opcional por nome/categoria).

    Duas fontes, por ordem: o CLI dentro do container (`hermes skills list`, que é
    a lista **ativa** — precisa de `docker`) e, se não houver `docker`, a leitura
    direta do volume do agente (todas as skills que ele tem em disco).
    """
    cached = _cache_get("skills")
    if cached is None:
        from_cli = _skills_from_cli()
        if from_cli:
            cached = _cache_put(
                "skills", {"items": from_cli, "source": "hermes skills list (container)"}
            )
        else:
            cached = _cache_put(
                "skills",
                {
                    "items": _skills_from_dir(),
                    "source": "volume do agente (skills em disco)",
                },
            )
    items_all: List[Dict[str, Any]] = cached["items"]
    needle = _fold(query)
    items = [
        item
        for item in items_all
        if not needle or needle in _fold(item["name"]) or needle in _fold(item["category"])
    ]
    categories: Dict[str, int] = {}
    for item in items_all:
        categories[item["category"]] = categories.get(item["category"], 0) + 1
    return {
        "available": bool(items_all),
        "total": len(items_all),
        "matched": len(items),
        "categories": [{"name": name, "skills": count} for name, count in sorted(categories.items())],
        "skills": items[:40],
        "source": cached["source"],
    }


def state(*, force: bool = False) -> Dict[str, Any]:
    """Retrato rápido do agente, para o `/jarvis/meta` (nunca levanta)."""
    if force:
        invalidate()
    cached = _cache_get("state")
    if cached is not None:
        return cached

    report: Dict[str, Any] = {
        "id": "agent",
        "label": NAME,
        "url": base_url(),
        "model": MODEL,
        "available": False,
        "version": None,
        "toolsets": 0,
        "skills": 0,
        "categories": 0,
        "error": None,
    }
    try:
        health = _get_json("/health", timeout=8.0)
        report["version"] = health.get("version")
        report["available"] = str(health.get("status") or "") == "ok"
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"[:200]
        return _cache_put("state", report, ttl=30.0)

    try:
        models = _get_json("/v1/models", timeout=8.0)
        served = [str(row.get("id")) for row in models.get("data") or [] if isinstance(row, dict)]
        if served:
            report["model"] = served[0]
    except Exception:
        pass

    report["toolsets"] = len(_toolsets())
    skills_report = skills()
    report["skills"] = skills_report["total"]
    report["categories"] = len(skills_report["categories"])
    return _cache_put("state", report, ttl=60.0)


def capabilities(*, focus: str = "") -> Dict[str, Any]:
    """As capacidades do agente (toolsets), com destaque para as que interessam ao pedido."""
    items = _toolsets()
    needle = _fold(focus)
    matched = [
        item
        for item in items
        if needle
        and (
            needle in _fold(item["id"])
            or needle in _fold(item["label"])
            or needle in _fold(item["description"])
        )
    ]
    return {
        "available": bool(items),
        "total": len(items),
        "focus": focus,
        "matched": matched[:12] if needle else [],
        "items": items,
        "note": (
            "Estas são as capacidades que o agente pode usar sozinho quando se delega uma "
            "tarefa com `agent.ask`."
        ),
    }


def assistant_system(task: str = "") -> str:
    """System prompt do agente quando é o Jarvis a delegar-lhe uma tarefa.

    Dá ao agente o que ele **não** pode saber sozinho: a persona, o dia de hoje (é o
    motivo mais comum para uma resposta errada em pedidos com «hoje», «esta semana»,
    «quanto tempo falta»), os endereços internos que as skills usam e as regras de
    resposta. A lista de skills e de toolsets é injectada pelo próprio agente.
    """
    today = _today_pt()
    api = os.getenv("IQOS_API_BASE") or os.getenv("IQOS_API_URL") or "http://backend:8000"
    searx = os.getenv("IQOS_SEARXNG_URL") or "http://searxng:8080"
    lines = [
        PERSONA,
        f"Hoje é {today}.",
        "",
        "Dados que tens ao lado (rede interna, sem chave):",
        f"- Pesquisa total do IQ OS: `GET {api}/search/unified?q=<termo>&scope=all&size=5` "
        "(âmbitos: all, scraped, social, contracts, contracts_es, entities, entities_es, "
        "contribuintes, pessoas, cire, societario, citacoes, politicos, wikipedia, "
        "trademarks, firmas, news, imprensa, market, crm). "
        "Resposta agrupada com contagens (`total`) e itens com `title`/`url`.",
        f"- Pesquisa profunda do IQ OS (skill `pesquisa-profunda`): "
        f"`GET {api}/deep-search/search?q=<pergunta>` devolve as fontes numeradas `[n]` "
        f"(sem modelo) e `POST {api}/deep-search/ask` {{\"question\": …}} devolve a "
        "resposta citada (SSE). Âmbitos: `contracts`, `entities`, `contribuintes`, `cire` "
        "(insolvências), `societario` (atos societários), `citacoes`, `pessoas`, "
        "`imprensa`, `scraped`, `wikipedia`, `trademarks`, `firmas`, `market`.",
        f"- Metasearch interno: `GET {searx}/search?q=<termo>&format=json` (SearXNG, JSON).",
        "- Plataforma: `" + api + "` (contratos, empresas, pessoas, contribuintes, "
        "insolvências, atos societários, citações edital, mercado — ver as skills "
        "`pesquisa-total` e `pesquisa-profunda`).",
        "",
        RULES,
    ]
    if task:
        lines += ["", f"Pedido do utilizador: {task.strip()[:400]}"]
    return "\n".join(lines)


def _today_pt() -> str:
    """Data de hoje em português (sem depender do locale do container)."""
    from datetime import date  # noqa: PLC0415

    today = date.today()
    return f"{_WEEKDAYS[today.weekday()]}, {today.day} de {_MONTHS[today.month - 1]} de {today.year}"


async def ask(
    task: str,
    *,
    timeout: Optional[float] = None,
    system: Optional[str] = None,
    history: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """**Delega** uma tarefa ao agente: ele usa as skills e as ferramentas que tiver.

    É o único caminho que dá ao Jarvis «tudo o que o agente sabe fazer» — o agente
    decide sozinho que skills seguir e que toolsets usar (browser, terminal, ficheiros,
    código, cron, …). É lento por natureza: um ciclo completo pode levar minutos.

    `system` é a persona (por omissão `assistant_system()`); `history` é o diálogo
    anterior, para uma pergunta de seguimento («e quanto é que isso valeu?») não chegar
    ao agente sem contexto — o agente é sem estado e sem isto respondería a um pedido
    isolado.
    """
    question = str(task or "").strip()
    if not question:
        raise RuntimeError("A ferramenta agent.ask precisa de `task`.")

    messages: List[Dict[str, str]] = []
    prompt = assistant_system(question) if system is None else str(system)
    if prompt.strip():
        messages.append({"role": "system", "content": prompt})
    for turn in history or []:
        role = str(turn.get("role") or "").lower()
        content = str(turn.get("content") or "").strip()
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content[:MAX_HISTORY_CHARS]})
    messages.append({"role": "user", "content": question})

    payload = {"model": MODEL, "messages": messages, "stream": False}
    limit = float(timeout or ASK_TIMEOUT)
    url = f"{base_url()}/v1/chat/completions"
    try:
        async with httpx.AsyncClient(timeout=limit, headers=_headers()) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(
            f"O Hermes Agent respondeu HTTP {exc.response.status_code} "
            f"({exc.response.text[:200]})"
        ) from exc
    except httpx.TimeoutException as exc:
        raise RuntimeError(
            f"O Hermes Agent excedeu {limit:.0f}s nesta tarefa — o agente corre um ciclo "
            "autónomo completo (skills + ferramentas); simplifique o pedido ou aumente "
            "`JARVIS_AGENT_TIMEOUT`."
        ) from exc
    except Exception as exc:
        raise RuntimeError(f"Não foi possível contactar o Hermes Agent em {url}: {exc}") from exc

    choices = data.get("choices") or [{}]
    message = choices[0].get("message") or {}
    return {
        "answer": str(message.get("content") or "").strip(),
        "model": str(data.get("model") or MODEL),
        "usage": data.get("usage") or {},
        "tool_calls": len(message.get("tool_calls") or []),
        "task": question,
    }


def _fold(value: Any) -> str:
    import unicodedata  # noqa: PLC0415

    text = unicodedata.normalize("NFD", str(value or ""))
    return "".join(char for char in text if unicodedata.category(char) != "Mn").lower()


def toolset_ids() -> List[str]:
    """Ids das capacidades (atajo para os testes e para o prompt do planeador)."""
    return [item["id"] for item in _toolsets()]


async def _main() -> None:  # pragma: no cover - utilitário de linha de comandos
    print("base:", base_url())
    print("estado:", await asyncio.to_thread(state, force=True))
    print("capacidades:", toolset_ids())
    report = await asyncio.to_thread(skills)
    print("skills:", report["total"], "em", report["categories"])


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(_main())
