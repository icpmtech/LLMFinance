"""Jarvis — o assistente operacional do IQ OS, com voz e browser.

O Jarvis é diferente dos outros assistentes da plataforma em três aspetos:

1. **Fala com o sistema por gateways** (`api/jarvis_gateway.py`): o Hermes
   (investigação citada), o servidor **MCP** do sistema (todas as operações
   curadas) e o **browser** (pesquisa e leitura de páginas).
2. **Segue uma skill** — como o Hermes e o Chat IA, escolhe (ou cria) o método
   antes de responder, na biblioteca partilhada (`api/skills_service.py`).
3. **Fala e ouve** — transcreve áudio (STT) e devolve a resposta sintetizada
   (TTS). O servidor usa `faster-whisper`/`edge-tts` quando existem; sem eles,
   a interface usa as vozes nativas do browser (não bloqueia nada).

O ciclo de uma pergunta:

    pergunta → skill → plano (gateways) → execução → resposta → fala

Cada passo é devolvido em `steps`, para a interface desenhar a coreografia
(o que o Jarvis está a fazer) em vez de um simples indicador de espera.

Rotas em `api/jarvis_routes.py` (`/jarvis/*`).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import tempfile
import time
import unicodedata
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional, Sequence, Tuple

from api import jarvis_actions as actions_catalogue
from api import jarvis_gateway as gateway

logger = logging.getLogger(__name__)

NAME = "Jarvis"
GREETING = (
    "Olá. Sou o Jarvis, o assistente operacional do IQ OS. Posso investigar dados da plataforma, "
    "consultar o catálogo MCP e ir à web — basta falar ou escrever."
)

MAX_QUESTION_CHARS = 2000
MAX_HISTORY = 8
MAX_TOOLS_PER_PLAN = 4
MAX_ACTIONS_PER_PLAN = 3
MAX_EVIDENCE_CHARS = 9000
PLAN_MAX_TOKENS = 700
ANSWER_MAX_TOKENS = 1600
SPEECH_MAX_CHARS = 900

DEFAULT_VOICE = os.getenv("JARVIS_VOICE", "pt-PT-RaquelNeural")
DEFAULT_STT_MODEL = os.getenv("JARVIS_STT_MODEL", "small")

#: Palavras de ativação («wake words»). O modo de escuta contínua transcreve
#: localmente com `faster-whisper` e só acorda quando ouve uma delas — o resto do
#: áudio nunca chega a virar pergunta. Configurável por `JARVIS_WAKE_WORDS`
#: (lista separada por vírgulas).
DEFAULT_WAKE_WORDS: Tuple[str, ...] = (
    "jarvis",
    "hey jarvis",
    "olá jarvis",
    "apollo",
    "hey hermes",
)
WAKE_WORDS: Tuple[str, ...] = tuple(
    sorted(
        {
            word.strip().lower()
            for chunk in (os.getenv("JARVIS_WAKE_WORDS") or "").split(",")
            for word in [chunk]
            if word.strip()
        }
        or DEFAULT_WAKE_WORDS,
        key=len,
        reverse=True,
    )
)

#: Modelo usado **enquanto se espera** pela palavra de ativação. Tem de ser o mais
#: rápido possível (`tiny` com `int8` chega para reconhecer duas palavras) — é
#: isto que faz a latência ser baixa: o modelo corre localmente, por trechos
#: curtos, sem enviar áudio para fora.
WAKE_MODEL = os.getenv("JARVIS_WAKE_MODEL", "tiny")

#: Enviesamento do descodificador para as palavras de ativação. **Sem isto o
#: `tiny` não serve**: medido com fala sintética em pt-PT, ouvia «Serviço» em vez
#: de «Jarvis» e acertava 1 em 4; com o prompt acerta 4 em 4 (e o `base`, que é
#: ~50% mais lento, não melhora).
WAKE_PROMPT = os.getenv(
    "JARVIS_WAKE_PROMPT",
    "Português de Portugal. " + ", ".join(DEFAULT_WAKE_WORDS) + ".",
)

# Palavras que sugerem que a pergunta precisa da web (e não só dos dados internos).
_WEB_HINTS = ("web", "internet", "online", "site", "noticia de hoje", "o que se diz", "fora da plataforma")

SYSTEM_PLANNER = (
    "És o planeador do Jarvis, o assistente do IQ OS. Recebes uma pergunta, a lista de ferramentas "
    "disponíveis (id, gateway, descrição) e a lista de ações que ele pode propor ao utilizador, e "
    "devolves APENAS um objeto JSON com o plano:\n"
    '{"tools": [{"tool": "<id>", "args": {...}}], "actions": [{"action": "<id>", "params": {}}], "reason": "<uma frase>"}\n'
    "Regras: usa no máximo 4 ferramentas; usa `hermes.ask` quando a pergunta for sobre dados, contratos, "
    "empresas ou investigação; usa `agent.ask` (gateway `agent`) quando o pedido for trabalho autónomo ou "
    "multi-passo que a plataforma não cobre (usar o browser do agente, mexer em ficheiros, escrever ou "
    "executar código, investigar a fundo com métodos dele) — é lento, por isso só quando vale a pena; usa "
    "`agent.skills`/`agent.capabilities` quando a pergunta for sobre o que o agente sabe fazer; usa as "
    "ferramentas do gateway `mcp` para factos concretos do sistema; usa "
    "`web.search`/`web.research` só quando a pergunta pedir explicitamente informação externa ou da web.\n"
    "Nas `actions`, propõe **só** o que a pergunta pede explicitamente: um destino, quando o utilizador "
    "pede para ir a algum lado (ex.: «abre as insolvências»); uma criação, quando pede para guardar ou "
    "criar algo (ex.: «guarda isto no Office»). Não proponhas ações para perguntas normais — nesse caso "
    "devolve `\"actions\": []`.\n"
    'Se nenhuma ferramenta servir, devolve {"tools": [], "actions": [], "reason": "..."}. Escreve apenas o JSON.'
)

SYSTEM_ANSWER = (
    "És o Jarvis, o assistente operacional do IQ OS (plataforma portuguesa de contratos públicos, "
    "empresas, mercados e inteligência financeira). Respondes em português de Portugal, em texto simples "
    "(sem markdown), de forma direta e falada — as respostas são lidas em voz alta.\n"
    "Usa **apenas** as evidências fornecidas. Cita a origem quando existir (por exemplo «segundo o Hermes» "
    "ou «segundo os dados de contratos»). Nunca inventas números, datas ou nomes: o que não estiver nas "
    "evidências é declarado como não encontrado.\n"
    "Estrutura: 1) resposta direta (2 a 4 frases); 2) dados de apoio com números; 3) o que falta. "
    "Máximo 300 palavras. Não uses listas com asteriscos nem tabelas."
)

_SKILL_HINT_FOR_VOICE = "as respostas são lidas em voz alta"


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def clean_question(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:MAX_QUESTION_CHARS]


#: Marcas de que a pergunta só se entende com o turno anterior.
_FOLLOWUP_STARTS = (
    "e ", "e?", "e o", "e a", "e os", "e as", "e em", "e de", "e para", "e quanto", "e quais",
    "e qual", "entao", "então", "tambem", "também", "agora ", "dai", "daí",
)
_FOLLOWUP_WORDS = (
    "desses", "dessas", "desse", "dessa", "disso", "disto", "deste", "desta", "esse", "essa",
    "esses", "essas", "aqueles", "aquelas", "o mesmo", "a mesma", "os mesmos", "as mesmas",
    "essa empresa", "essa entidade", "desse contrato",
)
#: Acima disto a pergunta tem assunto próprio — não precisa do turno anterior.
MAX_FOLLOWUP_WORDS = 9


def _is_followup(question: str, history: Optional[Sequence[Dict[str, Any]]]) -> bool:
    """A pergunta (curta) só faz sentido com o turno anterior?

    Sem isto, «e desses, quantos são de Portugal?» era planeada do zero: o Jarvis não
    sabia a que «desses» se referia, criava uma skill nova e respondia que não tinha
    acesso ao conjunto anterior.
    """
    if not history:
        return False
    text = _fold(question).strip()
    if not text or len(text.split()) > MAX_FOLLOWUP_WORDS:
        return False
    if text.startswith(_FOLLOWUP_STARTS):
        return True
    return any(word in text for word in _FOLLOWUP_WORDS)


def _last_turn(history: Optional[Sequence[Dict[str, Any]]]) -> Tuple[str, str]:
    """(pergunta, resposta) do último turno com conteúdo."""
    pergunta, resposta = "", ""
    for turn in reversed(list(history or [])):
        role = str(turn.get("role") or "").lower()
        content = re.sub(r"\s+", " ", str(turn.get("content") or "")).strip()
        if not content:
            continue
        if role == "user" and not pergunta:
            pergunta = content[:400]
        elif role == "assistant" and not resposta:
            resposta = content[:600]
        if pergunta and resposta:
            break
    return pergunta, resposta


def _context_text(question: str, history: Optional[Sequence[Dict[str, Any]]]) -> str:
    """A pergunta com o tema do turno anterior colado, quando a atual é um seguimento.

    É este o texto que vai ao planeador e aos argumentos das ferramentas: «e desses,
    quantos são de Portugal?» passa a levar «Mota-Engil» agarrado e a pesquisa volta ao
    assunto certo. A pergunta original continua a ser a que se mostra ao utilizador.
    """
    if not _is_followup(question, history):
        return question
    anterior, _ = _last_turn(history)
    if not anterior:
        return question
    return clean_question(f"{anterior} {question}")


def _conversation_block(history: Optional[Sequence[Dict[str, Any]]], limit: int = 2) -> str:
    """A conversa recente, em texto, para o planeador e para a resposta final."""
    turns: List[str] = []
    for turn in list(history or [])[-limit * 2 :]:
        role = str(turn.get("role") or "").lower()
        content = re.sub(r"\s+", " ", str(turn.get("content") or "")).strip()
        if not content or role not in {"user", "assistant"}:
            continue
        quem = "Utilizador" if role == "user" else "Jarvis"
        turns.append(f"{quem}: {content[:600]}")
    return "\n".join(turns)


def _fold(value: Any) -> str:
    text = unicodedata.normalize("NFD", str(value or ""))
    return "".join(char for char in text if unicodedata.category(char) != "Mn").lower()


def speech_text(text: str) -> str:
    """Prepara o texto para leitura em voz alta (sem markdown, curto)."""
    value = str(text or "")
    # 1. Blocos e código inline
    value = re.sub(r"```.*?```", " ", value, flags=re.S)
    value = re.sub(r"`([^`]*)`", r"\1", value)
    # 2. Títulos e ênfase (antes das listas, senão o `**` é comido como marcador)
    value = re.sub(r"^\s*#{1,6}\s*", "", value, flags=re.M)
    value = re.sub(r"\*\*\*(.+?)\*\*\*", r"\1", value, flags=re.S)
    value = re.sub(r"\*\*(.+?)\*\*", r"\1", value, flags=re.S)
    value = re.sub(r"(?<!\w)\*(?!\s)(.+?)(?<!\s)\*(?!\w)", r"\1", value, flags=re.S)
    value = re.sub(r"(?<!\w)_(?!\s)(.+?)(?<!\s)_(?!\w)", r"\1", value, flags=re.S)
    value = re.sub(r"^>\s?", "", value, flags=re.M)
    # 3. Citações [n] → «(fonte n)»
    value = re.sub(r"\[(\d+)\]", r" (fonte \1)", value)
    # 4. Marcadores de lista e tabelas
    value = re.sub(r"^\s*[-*•+]\s+", "", value, flags=re.M)
    value = re.sub(r"^\s*\d+[.)]\s+", "", value, flags=re.M)
    # Linhas de separação de tabelas (`|---|---|`) e réguas horizontais (`---`)
    value = re.sub(r"^\s*\|?[\s:|-]*-[\s:|-]*\|?\s*$", "", value, flags=re.M)
    value = re.sub(r"^\s*[-=*_]{3,}\s*$", "", value, flags=re.M)
    value = value.replace("|", " ")
    # 5. Espaço e pontuação
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{2,}", ". ", value).replace("\n", ". ")
    value = re.sub(r"(\.\s*){2,}", ". ", value)
    value = re.sub(r"\s+([,.;:!?])", r"\1", value)
    value = re.sub(r"\s{2,}", " ", value).strip()
    if len(value) > SPEECH_MAX_CHARS:
        cut = value[:SPEECH_MAX_CHARS]
        value = cut[: cut.rfind(".") + 1] if "." in cut else cut
    return value


def _truncate_evidence(entry: Dict[str, Any]) -> Dict[str, Any]:
    text = json.dumps(entry, ensure_ascii=False, default=str)
    if len(text) <= MAX_EVIDENCE_CHARS:
        return entry
    return {"tool": entry.get("tool"), "gateway": entry.get("gateway"), "ok": entry.get("ok"), "note": "evidência truncada",
            "excerpt": text[:MAX_EVIDENCE_CHARS]}


# ---------------------------------------------------------------------------
# Planeamento
# ---------------------------------------------------------------------------
def _planner_catalog(limit: int = 34) -> List[Dict[str, str]]:
    """Lista curta de ferramentas para o planeador (cabe num prompt)."""
    promoted = [item for item in gateway.catalog() if item["gateway"] == "mcp" and item["id"] not in {"mcp.search", "mcp.call"}]
    web = [item for item in gateway.catalog() if item["gateway"] == "web" and item["id"] != "web.open"]
    hermes = [item for item in gateway.catalog() if item["gateway"] == "hermes"]
    agent = [item for item in gateway.catalog() if item["gateway"] == "agent"]
    items = [*hermes, *agent, *promoted[: limit - 8], *web]
    return [
        {"id": item["id"], "gateway": item["gateway"], "description": item["description"][:180]}
        for item in items
    ]


def _heuristic_plan(question: str) -> Dict[str, Any]:
    """Plano sem modelo: palavras-chave + Hermes como espinha dorsal.

    Os argumentos ficam vazios de propósito — quem os preenche é
    `_ensure_question_arg`, a partir do catálogo (uma só fonte de verdade).
    """
    chosen = [
        {"tool": tool_id, "args": {"question": question, "depth": "rapida"}}
        if tool_id == "hermes.ask"
        else {"tool": tool_id, "args": {}}
        for tool_id in gateway.pick_tools(question, limit=MAX_TOOLS_PER_PLAN)
    ]
    return {
        "tools": chosen,
        "actions": [],
        "reason": "Plano por palavras-chave (sem modelo de IA disponível).",
        "source": "heuristica",
    }


async def _llm_plan(question: str, backend: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    from api import ontology_ai  # noqa: PLC0415

    catalog = _planner_catalog()
    prompt = (
        "Ferramentas disponíveis (JSON):\n"
        + json.dumps(catalog, ensure_ascii=False)
        + "\n\nAções que podes propor (JSON):\n"
        + json.dumps(actions_catalogue.planner_catalogue(), ensure_ascii=False)
        + (f"\n\nConversa anterior (memória da sessão):\n{context}" if context else "")
        + f"\n\nPergunta do utilizador: {question}\n\nDevolve apenas o JSON do plano."
    )
    raw = await ontology_ai.ask_model(
        backend, system=SYSTEM_PLANNER, prompt=prompt, max_tokens=PLAN_MAX_TOKENS, temperature=0.0
    )
    parsed = ontology_ai.extract_json(raw)
    if not parsed:
        return None

    tools: List[Dict[str, Any]] = []
    known = gateway.TOOLS
    for row in (parsed.get("tools") or [])[:MAX_TOOLS_PER_PLAN]:
        if not isinstance(row, dict):
            continue
        tool_id = str(row.get("tool") or "").strip()
        if tool_id not in known:
            continue
        args = row.get("args") if isinstance(row.get("args"), dict) else {}
        tools.append({"tool": tool_id, "args": args})

    proposed: List[Dict[str, Any]] = []
    for row in (parsed.get("actions") or [])[:MAX_ACTIONS_PER_PLAN]:
        if not isinstance(row, dict):
            continue
        action_id = str(row.get("action") or row.get("id") or "").strip()
        if action_id in actions_catalogue.DESTINATIONS_BY_ID or action_id in actions_catalogue.CREATIONS_BY_ID:
            proposed.append(
                {
                    "action": action_id,
                    "params": row.get("params") if isinstance(row.get("params"), dict) else {},
                }
            )

    if not tools and not proposed:
        return None
    return {
        "tools": tools,
        "actions": proposed,
        "reason": str(parsed.get("reason") or ""),
        "source": "modelo",
    }


async def plan(question: str, backend: Optional[Dict[str, Any]], context: str = "") -> Dict[str, Any]:
    """Plano do Jarvis: modelo quando há, palavras-chave quando não há."""
    if backend and backend.get("kind") == "cloud":
        try:
            candidate = await _llm_plan(question, backend, context)
            if candidate:
                return candidate
        except Exception as exc:
            logger.info("Planeador do Jarvis falhou (%s); uso o plano por palavras-chave.", exc)
    return _heuristic_plan(question)


def _ensure_question_arg(call: Dict[str, Any], question: str) -> Dict[str, Any]:
    """Junta os argumentos do plano com os mínimos que o catálogo permite inferir.

    Os argumentos do planeador têm prioridade; o que faltar vem de
    `gateway.default_args`. Se mesmo assim faltar um parâmetro obrigatório, a
    chamada é marcada para ser salta (evita um 422 garantido).
    """
    tool_id = call["tool"]
    tool = gateway.TOOLS.get(tool_id)
    if tool is None:
        return {"tool": tool_id, "args": {}, "skip": "ferramenta desconhecida"}

    planned = {
        key: value
        for key, value in (call.get("args") or {}).items()
        if value not in (None, "", {}, [])
    }
    inferred = gateway.default_args(tool_id, question) or {}
    args: Dict[str, Any] = {**inferred, **planned}

    required = (tool.parameters or {}).get("required") or []
    missing = [name for name in required if args.get(name) in (None, "", {}, [])]
    if missing:
        return {"tool": tool_id, "args": args, "skip": f"faltam parâmetros: {', '.join(missing)}"}
    if not args:
        return {"tool": tool_id, "args": {}, "skip": "sem argumentos possíveis a partir da pergunta"}
    return {"tool": tool_id, "args": args}


# ---------------------------------------------------------------------------
# Execução
# ---------------------------------------------------------------------------
def _step(kind: str, label: str, **extra: Any) -> Dict[str, Any]:
    return {"kind": kind, "label": label, "at": round(time.perf_counter(), 3), **extra}


def _evidence_from(results: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Evidências para o modelo: só o payload útil, sem o envelope do gateway."""
    return [
        _truncate_evidence(
            {
                "tool": item.get("tool"),
                "gateway": item.get("gateway"),
                "ok": item.get("ok"),
                "error": item.get("error"),
                "data": _payload(item),
            }
        )
        for item in results
    ]


def _payload(item: Dict[str, Any]) -> Any:
    """O resultado de uma ferramenta sem o envelope do gateway MCP.

    As operações do MCP devolvem `{operation, label, method, path, data}`; o que
    interessa (contagens, registos) está em `data`, e é isso que se resume e se
    passa ao modelo.
    """
    data = item.get("data")
    if isinstance(data, dict) and "operation" in data and "data" in data and "path" in data:
        return data["data"]
    return data


def _sources_from(results: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Citações legíveis: contratos, empresas e páginas abertas."""
    sources: List[Dict[str, Any]] = []
    for item in results:
        if not item.get("ok"):
            continue
        data = item.get("data") or {}
        if item.get("gateway") == "hermes":
            for index, source in enumerate(data.get("sources") or [], start=1):
                if isinstance(source, dict):
                    sources.append(
                        {
                            "index": index,
                            "label": source.get("title") or source.get("label") or f"fonte {index}",
                            "url": source.get("url"),
                            "origin": "Hermes",
                        }
                    )
        elif item.get("gateway") == "agent":
            # O agente não devolve «fontes»: a citação é a delegação em si, com o
            # modelo que a executou. Distinguir da origem «MCP» importa — é o que
            # mostra ao utilizador *quem* fez o trabalho.
            data = data if isinstance(data, dict) else {}
            sources.append(
                {
                    "label": item.get("label") or item.get("tool"),
                    "origin": "Hermes Agent",
                    "note": (f"modelo {data.get('model')}" if data.get("model") else None),
                }
            )
        elif item.get("gateway") == "web":
            for row in data.get("results") or []:
                if isinstance(row, dict) and row.get("url"):
                    sources.append({"label": row.get("title") or row["url"], "url": row["url"], "origin": "Web"})
            for page in data.get("pages") or []:
                if isinstance(page, dict) and page.get("url"):
                    sources.append({"label": page.get("title") or page["url"], "url": page["url"], "origin": "Web"})
        else:
            sources.append({"label": item.get("label") or item.get("tool"), "origin": "MCP"})
    seen: set = set()
    unique: List[Dict[str, Any]] = []
    for source in sources:
        key = (source.get("url"), source.get("label"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(source)
    return unique[:12]


def _factual_answer(question: str, results: Sequence[Dict[str, Any]]) -> str:
    """Resposta sem modelo: só o que as ferramentas devolveram."""
    if not results:
        return (
            "Não tenho um modelo de IA configurado, por isso respondo em modo factual. "
            f"Não encontrei ferramentas adequadas para «{question}». "
            "Configure um fornecedor em Definições → Fornecedores de IA para uma resposta redigida."
        )
    lines: List[str] = []
    # Um agente (Hermes ou Hermes Agent) já redige: a resposta dele é a resposta, e
    # não um par chave=valor para o utilizador descodificar.
    delegado = False
    for item in results:
        label = item.get("label") or item.get("tool")
        if not item.get("ok"):
            lines.append(f"- {label}: não foi possível ({item.get('error')}).")
            continue
        data = item.get("data") or {}
        gateway = item.get("gateway")
        if gateway in {"hermes", "agent"}:
            answer = str(data.get("answer") or "").strip()
            if answer:
                lines.append(answer)
                delegado = True
                continue
        if gateway == "hermes":
            # O Hermes não redigiu (pergunta curta ou sem modelo): mostram-se as
            # evidências que recolheu, para a resposta não ficar vazia.
            titles = [
                str(source.get("title") or source.get("name") or "").strip()
                for source in (data.get("sources") or [])
                if isinstance(source, dict)
            ]
            titles = [title for title in titles if title][:6]
            lines.append(
                f"- Hermes recolheu {len(data.get('sources') or [])} evidências"
                + (f": {'; '.join(titles)}." if titles else ".")
            )
            continue
        if gateway == "agent":
            modelo = data.get("model") or "?"
            lines.append(f"- {label}: o agente não devolveu texto (modelo {modelo}).")
            continue
        lines.append(f"- {label}:")
        lines.append(_summarise_payload(_payload(item)))
    if delegado:
        return (
            "O agente autónomo respondeu diretamente (o Jarvis não tem modelo de IA "
            "configurado para redigir por cima):\n" + "\n".join(lines)
        )
    return (
        "Sem modelo de IA configurado, apresento o que as ferramentas devolveram "
        "(modo factual, sem interpretação):\n" + "\n".join(lines)
    )


#: Campos que identificam um registo, por ordem de utilidade numa leitura rápida.
_ITEM_LABELS: Tuple[Tuple[str, str], ...] = (
    ("objectoContrato", "objeto"),
    ("objecto", "objeto"),
    ("title", "título"),
    ("name", "nome"),
    ("nome", "nome"),
    ("label", "etiqueta"),
    ("adjudicante", "adjudicante"),
    ("adjudicatario", "adjudicatário"),
    ("precoContratual", "preço"),
    ("value", "valor"),
    ("total", "total"),
    ("date", "data"),
    ("dataPublicacao", "publicado"),
    ("url", "url"),
)


def _describe_item(item: Any) -> str:
    """Uma linha legível por registo (sem despejar o JSON todo)."""
    if not isinstance(item, dict):
        return str(item)[:120]
    parts: List[str] = []
    for key, label in _ITEM_LABELS:
        value = item.get(key)
        if value in (None, "", [], {}):
            continue
        text = str(value)
        parts.append(f"{label}={text[:80]}")
        if len(parts) >= 4:
            break
    if not parts:
        # Sem campos conhecidos: os primeiros valores simples servem de resumo.
        for key, value in list(item.items())[:4]:
            if isinstance(value, (str, int, float)) and str(value).strip():
                parts.append(f"{key}={str(value)[:60]}")
    return " · ".join(parts)


def _scalars(data: Dict[str, Any], limit: int = 8) -> Dict[str, Any]:
    """Os campos simples de um payload (o que se pode mostrar numa linha)."""
    return {
        key: value
        for key, value in data.items()
        if isinstance(value, (str, int, float, bool)) and str(value).strip()
    } | {}


def _summarise_payload(data: Any) -> str:
    """Resumo curto de um payload do MCP: contagens, escalares e primeiros registos."""
    if not isinstance(data, dict):
        return json.dumps(data, ensure_ascii=False, default=str)[:1200]

    header: List[str] = []
    for key in ("total", "count", "size", "items_count", "documents"):
        value = data.get(key)
        if isinstance(value, int):
            header.append(f"{key}={value}")
    summary = "; ".join(header)

    items = data.get("items") or data.get("results") or data.get("records") or data.get("data")
    if isinstance(items, list) and items:
        shown = "; ".join(_describe_item(item) for item in items[:4])
        summary = f"{summary} | {shown}" if summary else shown

    # Os escalares restantes (estado, versão, notas) são o que dá contexto quando
    # não há listas — ou o complemento delas quando há.
    scalars = _scalars(data, limit=6)
    for key in ("total", "count", "size", "items_count", "documents"):
        scalars.pop(key, None)
    extra = "; ".join(f"{key}={str(value)[:80]}" for key, value in list(scalars.items())[:6])
    if extra:
        summary = f"{summary} | {extra}" if summary else extra

    return (summary or json.dumps(data, ensure_ascii=False, default=str))[:1200]


def _speech_with_actions(answer: str, actions: Sequence[Dict[str, Any]]) -> str:
    """Versão falada da resposta, com o que o Jarvis se propõe fazer a seguir.

    Sem isto, um utilizador só de voz nunca saberia que há uma ação à espera de
    confirmação no ecrã.
    """
    speak = speech_text(answer)
    creations = [action for action in actions if action.get("kind") == "create"]
    destinations = [action for action in actions if action.get("kind") == "navigate"]
    parts: List[str] = []
    if creations:
        labels = " e ".join(action["label"].lower() for action in creations)
        parts.append(f"Se quiser, posso {labels} — diga confirmar.")
    if destinations:
        labels = " ou ".join(action["label"].lower() for action in destinations)
        parts.append(f"Também posso {labels}.")
    if parts:
        speak = f"{speak} {' '.join(parts)}".strip()
    return speak


def _suggestions(question: str, results: Sequence[Dict[str, Any]]) -> List[str]:
    used = {item.get("tool") for item in results}
    ideas: List[str] = []
    if "contratos_search" in used or "contratos_analytics" in used:
        ideas += ["Quem são os maiores adjudicatários destes contratos?", "Como evoluiu este valor nos últimos anos?"]
    if "empresa_detail" in used or "empresas_global_search" in used:
        ideas += ["Que contratos tem esta empresa com o Estado?", "Há processos de insolvência associados?"]
    if "market_history" in used or "market_info" in used:
        ideas += ["Como se comportou a ação no último ano?", "Que notícias explicam esta variação?"]
    if "web.search" in used or "web.research" in used:
        ideas += ["Compara estas fontes com os dados da plataforma."]
    ideas += [
        "Resume o que encontraste em três pontos.",
        "Que dados da plataforma sustentam esta resposta?",
    ]
    out: List[str] = []
    for idea in ideas:
        if idea not in out:
            out.append(idea)
    return out[:4]


async def _compose(
    question: str,
    results: Sequence[Dict[str, Any]],
    backend: Optional[Dict[str, Any]],
    skill_block: str,
    context: str = "",
) -> str:
    if backend and backend.get("kind") == "cloud":
        from api import ontology_ai  # noqa: PLC0415

        evidence = json.dumps(_evidence_from(results), ensure_ascii=False, default=str)
        prompt = (
            (skill_block + "\n\n" if skill_block else "")
            + (f"Conversa anterior (memória da sessão):\n{context}\n\n" if context else "")
            + "Evidências recolhidas pelos gateways (JSON):\n"
            + evidence
            + f"\n\nPergunta do utilizador: {question}\n\nResponde como o Jarvis, para ser lido em voz alta."
        )
        try:
            answer = await ontology_ai.ask_model(
                backend, system=SYSTEM_ANSWER, prompt=prompt, max_tokens=ANSWER_MAX_TOKENS, temperature=0.2
            )
            if answer and answer.strip():
                return answer.strip()
        except Exception as exc:
            logger.warning("Composição da resposta do Jarvis falhou: %s", exc)
    return _factual_answer(question, results)


# ---------------------------------------------------------------------------
# Ciclo principal
# ---------------------------------------------------------------------------
async def ask(
    question: str,
    *,
    session: Any = None,
    backend: Optional[str] = None,
    depth: str = "rapida",
    history: Optional[Sequence[Dict[str, Any]]] = None,
    scope: Optional[Dict[str, Any]] = None,
    country: str = "PRT",
    token: Optional[str] = None,
    app: Any = None,
) -> Dict[str, Any]:
    """Responde à pergunta do utilizador, passando pelos gateways."""
    from api import ontology_ai, skills_service  # noqa: PLC0415

    clean = clean_question(question)
    if not clean:
        raise ValueError("Diga ou escreva a pergunta que quer fazer ao Jarvis.")

    started = time.perf_counter()
    steps: List[Dict[str, Any]] = [_step("ouvir", f"Pergunta recebida: «{clean[:120]}»")]

    resolved = ontology_ai.available_backend(session, backend)
    steps.append(
        _step(
            "modelo",
            f"Modelo: {resolved.get('model') or resolved.get('backend') or 'local'}"
            + (f" ({resolved['provider']})" if resolved.get("provider") else "")
            + ("" if resolved.get("kind") == "cloud" else " — modo factual"),
        )
    )

    # 0) Skill: o método que o Jarvis segue (biblioteca partilhada com o Hermes).
    skill: Optional[Dict[str, Any]] = None
    skill_public: Optional[Dict[str, Any]] = None
    skill_id: Optional[str] = None
    skill_mode = ""
    skill_block = ""
    try:
        skill_result = await skills_service.for_request(clean, session=session, backend=backend)
        skill_block = skill_result.get("block") or ""
        skill = skill_result.get("raw")
        skill_public = skill_result.get("public")
        skill_id = skill_result.get("id")
        skill_mode = str(skill_result.get("mode") or "")
        if skill:
            steps.append(
                _step(
                    "skill",
                    f"Skill: {skill.get('title') or skill.get('id')} ({skill_mode or 'biblioteca'})",
                    skill_id=skill.get("id"),
                )
            )
    except Exception as exc:
        logger.info("Skill do Jarvis indisponível: %s", exc)

    # 1) Plano
    chosen = await plan(clean, resolved)
    calls = [_ensure_question_arg(call, clean) for call in chosen["tools"]]
    calls = [call for call in calls if not call.get("skip")]
    steps.append(
        _step(
            "plano",
            "Plano: " + (", ".join(call["tool"] for call in calls) if calls else "sem ferramentas"),
            reason=chosen.get("reason"),
            source=chosen.get("source"),
        )
    )

    # 2) Execução dos gateways (em sequência: o Hermes é pesado e as chamadas
    #    ao MCP partilham o mesmo cliente/backend).
    context = {
        "session": session,
        "backend": backend,
        "history": list(history or [])[:MAX_HISTORY],
        "scope": scope,
        "country": country,
        "token": token,
        "app": app,
    }
    results: List[Dict[str, Any]] = []
    for call in calls:
        tool_id = call["tool"]
        label = gateway.TOOLS[tool_id].label if tool_id in gateway.TOOLS else tool_id
        steps.append(_step("ferramenta", f"A usar {label} ({gateway.TOOLS[tool_id].gateway})…", tool=tool_id))
        result = await gateway.invoke(tool_id, call.get("args"), ctx=context)
        results.append(result)
        steps.append(
            _step(
                "resultado",
                (f"{label}: ok" if result.get("ok") else f"{label}: falhou ({result.get('error')})"),
                tool=tool_id,
                ok=bool(result.get("ok")),
            )
        )

    # 3) Resposta
    answer = await _compose(clean, results, resolved, skill_block)
    steps.append(_step("responder", "Resposta pronta."))

    # 4) Ações propostas (navegar ou criar em nome do utilizador). Nunca se
    #    executam aqui: quem decide é o utilizador, na interface.
    proposed = actions_catalogue.propose(
        clean,
        answer,
        tools_used=[call["tool"] for call in calls],
        extra=chosen.get("actions"),
    )
    for action in proposed:
        steps.append(_step("acao", f"Proposta: {action['label']}", tool=action["id"]))

    elapsed = round(time.perf_counter() - started, 2)
    speak = _speech_with_actions(answer, proposed)

    if skill_id:
        try:
            skills_service.finish(
                skill_id,
                question=clean,
                tools=[call["tool"] for call in calls],
                mode=skill_mode,
            )
        except Exception:  # pragma: no cover - melhor esforço
            pass

    return {
        "answered": True,
        "answer": answer,
        "speech": speak,
        "steps": steps,
        "plan": {"tools": [call["tool"] for call in calls], "reason": chosen.get("reason"), "source": chosen.get("source")},
        "tools_used": [
            {"tool": item.get("tool"), "gateway": item.get("gateway"), "label": item.get("label"), "ok": bool(item.get("ok")),
             "error": item.get("error")}
            for item in results
        ],
        "evidence": _evidence_from(results),
        "sources": _sources_from(results),
        "suggestions": _suggestions(clean, results),
        "actions": proposed,
        "skill": skill_public,
        "model": {
            "kind": resolved.get("kind"),
            "provider": resolved.get("provider"),
            "model": resolved.get("model"),
            "note": resolved.get("note"),
        },
        "elapsed_seconds": elapsed,
    }


async def stream(
    question: str,
    *,
    session: Any = None,
    backend: Optional[str] = None,
    depth: str = "rapida",
    history: Optional[Sequence[Dict[str, Any]]] = None,
    scope: Optional[Dict[str, Any]] = None,
    country: str = "PRT",
    token: Optional[str] = None,
    app: Any = None,
) -> AsyncIterator[str]:
    """Versão SSE: emite `passo`, `skill`, `plano`, `ferramenta`, `resposta` e `fim`.

    Emite os **mesmos passos** que `ask()` devolve em `steps` (para o rasto da
    interface ficar completo) e, além disso, eventos tipados que dão estrutura a
    quem os quiser consumir programaticamente.
    """
    from api import ontology_ai, skills_service  # noqa: PLC0415

    def frame(event: str, payload: Dict[str, Any]) -> str:
        return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"

    clean = clean_question(question)
    if not clean:
        yield frame("erro", {"detail": "Diga ou escreva a pergunta que quer fazer ao Jarvis."})
        return

    started = time.perf_counter()
    steps: List[Dict[str, Any]] = []

    def step(kind: str, label: str, **extra: Any) -> Dict[str, Any]:
        item = _step(kind, label, **extra)
        steps.append(item)
        return item

    yield frame("passo", step("ouvir", f"Pergunta recebida: «{clean[:120]}»"))

    resolved = ontology_ai.available_backend(session, backend)
    yield frame(
        "passo",
        step(
            "modelo",
            f"Modelo: {resolved.get('model') or resolved.get('backend') or 'local'}"
            + (f" ({resolved['provider']})" if resolved.get("provider") else "")
            + ("" if resolved.get("kind") == "cloud" else " — modo factual"),
        ),
    )

    skill_block = ""
    skill_public: Optional[Dict[str, Any]] = None
    skill_id: Optional[str] = None
    skill_mode = ""
    try:
        skill_result = await skills_service.for_request(clean, session=session, backend=backend)
        skill_block = skill_result.get("block") or ""
        skill_public = skill_result.get("public")
        skill_id = skill_result.get("id")
        skill_mode = str(skill_result.get("mode") or "")
        if skill_public:
            yield frame(
                "passo",
                step("skill", f"Skill: {skill_public.get('title') or skill_id} ({skill_mode or 'biblioteca'})"),
            )
            yield frame("skill", {"skill": skill_public})
    except Exception as exc:
        logger.info("Skill do Jarvis indisponível (stream): %s", exc)

    chosen = await plan(clean, resolved)
    calls = [_ensure_question_arg(call, clean) for call in chosen["tools"]]
    calls = [call for call in calls if not call.get("skip")]
    tools_label = ", ".join(call["tool"] for call in calls) if calls else "sem ferramentas"
    yield frame(
        "passo",
        step("plano", f"Plano: {tools_label}", reason=chosen.get("reason"), source=chosen.get("source")),
    )
    yield frame(
        "plano",
        {"tools": [call["tool"] for call in calls], "reason": chosen.get("reason"), "source": chosen.get("source")},
    )

    context = {
        "session": session,
        "backend": backend,
        "history": list(history or [])[:MAX_HISTORY],
        "scope": scope,
        "country": country,
        "token": token,
        "app": app,
    }
    results: List[Dict[str, Any]] = []
    for call in calls:
        tool_id = call["tool"]
        label = gateway.TOOLS[tool_id].label if tool_id in gateway.TOOLS else tool_id
        gateway_id = gateway.TOOLS[tool_id].gateway if tool_id in gateway.TOOLS else "?"
        yield frame("passo", step("ferramenta", f"A usar {label} ({gateway_id})…", tool=tool_id))
        yield frame("ferramenta", {"tool": tool_id, "label": label, "state": "a_correr"})
        result = await gateway.invoke(tool_id, call.get("args"), ctx=context)
        results.append(result)
        yield frame(
            "passo",
            step(
                "resultado",
                f"{label}: ok" if result.get("ok") else f"{label}: falhou ({result.get('error')})",
                tool=tool_id,
                ok=bool(result.get("ok")),
            ),
        )
        yield frame(
            "ferramenta",
            {"tool": tool_id, "label": label, "state": "ok" if result.get("ok") else "falhou", "error": result.get("error")},
        )

    answer = await _compose(clean, results, resolved, skill_block)
    yield frame("passo", step("responder", "Resposta pronta."))

    # Ações propostas: nunca se executam aqui — a interface mostra-as e o
    # utilizador confirma (por clique ou por voz).
    proposed = actions_catalogue.propose(
        clean,
        answer,
        tools_used=[call["tool"] for call in calls],
        extra=chosen.get("actions"),
    )
    for action in proposed:
        yield frame("passo", step("acao", f"Proposta: {action['label']}", tool=action["id"]))
        yield frame("acao", {"action": action})

    if skill_id:
        try:
            skills_service.finish(skill_id, question=clean, tools=[call["tool"] for call in calls], mode=skill_mode)
        except Exception:  # pragma: no cover
            pass

    yield frame(
        "resposta",
        {
            "answer": answer,
            "speech": _speech_with_actions(answer, proposed),
            "sources": _sources_from(results),
            "suggestions": _suggestions(clean, results),
            "actions": proposed,
            "skill": skill_public,
            "steps": steps,
            "tools_used": [
                {"tool": item.get("tool"), "gateway": item.get("gateway"), "label": item.get("label"), "ok": bool(item.get("ok")), "error": item.get("error")}
                for item in results
            ],
        },
    )
    yield frame("fim", {"elapsed_seconds": round(time.perf_counter() - started, 2)})


# ---------------------------------------------------------------------------
# Voz — STT
# ---------------------------------------------------------------------------
def stt_status() -> Dict[str, Any]:
    try:
        import faster_whisper  # type: ignore[import-not-found]  # noqa: F401

        available, engine = True, "faster-whisper"
    except Exception:
        available, engine = False, None
    return {
        "available": available,
        "engine": engine,
        "model": DEFAULT_STT_MODEL,
        "browser_fallback": True,
        "note": (
            "Transcrição no servidor disponível."
            if available
            else "Sem motor de transcrição no servidor — a interface usa o reconhecimento de voz do browser "
            "(Web Speech API), que funciona em Chrome/Edge."
        ),
    }


def wake_status() -> Dict[str, Any]:
    """Estado da palavra de ativação (vai no `/jarvis/voice`)."""
    stt = stt_status()
    return {
        "words": list(WAKE_WORDS),
        "model": WAKE_MODEL,
        "engine": stt["engine"],
        "available": bool(stt["available"]),
        "note": (
            f"Escuta contínua local: os trechos de áudio são transcritos com "
            f"`faster-whisper` ({WAKE_MODEL}) e só a palavra de ativação acorda o Jarvis."
            if stt["available"]
            else "A palavra de ativação precisa de `faster-whisper` no servidor."
        ),
    }


def _edit_distance_within(first: str, second: str, limit: int = 1) -> bool:
    """`first` e `second` distam no máximo `limit` edições? (Levenshtein, com saída cedo).

    Serve para aceitar as variações que um modelo pequeno produz ao ouvir a
    palavra de ativação — medido: o `tiny` alterna entre «Jarvis» e «Jervis»
    mesmo com o prompt de enviesamento.
    """
    if first == second:
        return True
    if abs(len(first) - len(second)) > limit:
        return False
    previous = list(range(len(second) + 1))
    for row, char_a in enumerate(first, start=1):
        current = [row]
        for column, char_b in enumerate(second, start=1):
            current.append(
                min(
                    previous[column] + 1,  # remover
                    current[column - 1] + 1,  # inserir
                    previous[column - 1] + (char_a != char_b),  # substituir
                )
            )
        if min(current) > limit:
            return False
        previous = current
    return previous[-1] <= limit


#: Comprimento mínimo para a tolerância fonética. Abaixo disto as palavras são
#: curtas de mais e aceitar uma edição começaria a casar com o que não é dito.
_FUZZY_MIN_LENGTH = 5


def _same_word(heard: str, expected: str) -> bool:
    """Compara uma palavra ouvida com uma da palavra de ativação."""
    if heard == expected:
        return True
    if len(heard) < _FUZZY_MIN_LENGTH or len(expected) < _FUZZY_MIN_LENGTH:
        return False
    return _edit_distance_within(heard, expected, 1)


def match_wake(text: str) -> Dict[str, Any]:
    """Procura a palavra de ativação no que foi transcrito.

    Devolve `active` (ouviu-a), `word` (qual) e `command` — o que veio **depois**
    dela na mesma frase, para o caso comum de se dizer tudo de uma vez:
    «Jarvis, quantos contratos tem a EDP?» já traz o pedido.
    """
    raw = str(text or "").strip()
    if not raw:
        return {"active": False, "word": None, "command": ""}

    words = raw.split()
    # Compara-se palavra a palavra para poder cortar o **texto original** (com
    # acentos): `_fold` encurta a string, por isso os índices não servem.
    folded = [_fold(word).strip(".,;:!?¿¡") for word in words]
    for wake in WAKE_WORDS:
        target = _fold(wake).split()
        span = len(target)
        for index in range(len(folded) - span + 1):
            window = folded[index : index + span]
            if all(_same_word(heard, wanted) for heard, wanted in zip(window, target)):
                command = " ".join(words[index + span :]).strip(" ,.;:!?—-\"")
                return {"active": True, "word": wake, "command": command}
    return {"active": False, "word": None, "command": ""}


def transcribe(
    data: bytes,
    *,
    filename: str = "audio.webm",
    language: str = "pt",
    model: Optional[str] = None,
    prompt: Optional[str] = None,
) -> Dict[str, Any]:
    """Transcreve áudio para texto (faster-whisper). Levanta `RuntimeError` sem motor.

    `model` permite usar um modelo mais pequeno nos trechos da escuta contínua
    (`transcribe_wake`) e o modelo completo quando já há uma pergunta. `prompt`
    enviesa o descodificador (é o que torna o `tiny` fiável nas palavras de
    ativação).
    """
    try:
        from faster_whisper import WhisperModel  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover - depende do ambiente
        raise RuntimeError(
            "Sem motor de transcrição no servidor. Instale `faster-whisper` ou use o microfone do browser."
        ) from exc

    if not data:
        raise RuntimeError("O áudio recebido está vazio.")

    suffix = Path(filename or "audio.webm").suffix or ".webm"
    handle, path = tempfile.mkstemp(suffix=suffix, prefix="jarvis-")
    os.close(handle)
    try:
        Path(path).write_bytes(data)
        chosen = (model or DEFAULT_STT_MODEL).strip() or DEFAULT_STT_MODEL
        whisper = _whisper_model(WhisperModel, chosen)
        segments, info = whisper.transcribe(
            path,
            language=language or "pt",
            vad_filter=True,
            initial_prompt=(prompt or None),
        )
        text = " ".join(segment.text.strip() for segment in segments).strip()
        return {
            "text": text,
            "language": getattr(info, "language", language),
            "duration_seconds": round(float(getattr(info, "duration", 0.0) or 0.0), 2),
            "engine": "faster-whisper",
            "model": chosen,
        }
    finally:
        try:
            os.unlink(path)
        except OSError:  # pragma: no cover
            pass


def transcribe_wake(data: bytes, *, filename: str = "audio.webm", language: str = "pt") -> Dict[str, Any]:
    """Transcreve um trecho curto e diz se ouviu a palavra de ativação.

    É o que o modo de escuta contínua chama a cada trecho: modelo pequeno,
    local, e nenhum áudio sai daqui — só volta texto (e, quando há palavra de
    ativação, o comando que veio atrás dela).
    """
    started = time.perf_counter()
    result = transcribe(
        data, filename=filename, language=language, model=WAKE_MODEL, prompt=WAKE_PROMPT
    )
    match = match_wake(result.get("text") or "")
    result.update(match)
    result["elapsed_ms"] = round((time.perf_counter() - started) * 1000)
    result["wake_words"] = list(WAKE_WORDS)
    return result


_MODEL_CACHE: Dict[str, Any] = {}


def _whisper_model(klass: Any, name: str) -> Any:
    """Carrega o modelo uma só vez (o carregamento é caro)."""
    if name not in _MODEL_CACHE:
        _MODEL_CACHE[name] = klass(name, device="cpu", compute_type="int8")
    return _MODEL_CACHE[name]


# ---------------------------------------------------------------------------
# Voz — TTS
# ---------------------------------------------------------------------------
VOICES: List[Dict[str, str]] = [
    {"id": "pt-PT-RaquelNeural", "label": "Raquel (pt-PT, feminina)", "locale": "pt-PT"},
    {"id": "pt-PT-DuarteNeural", "label": "Duarte (pt-PT, masculina)", "locale": "pt-PT"},
    {"id": "pt-BR-FranciscaNeural", "label": "Francisca (pt-BR, feminina)", "locale": "pt-BR"},
    {"id": "en-GB-RyanNeural", "label": "Ryan (en-GB, masculina)", "locale": "en-GB"},
]


def tts_status() -> Dict[str, Any]:
    try:
        import edge_tts  # type: ignore[import-not-found]  # noqa: F401

        available, engine = True, "edge-tts"
    except Exception:
        available, engine = False, None
    return {
        "available": available,
        "engine": engine,
        "voices": VOICES,
        "default_voice": DEFAULT_VOICE,
        "browser_fallback": True,
        "note": (
            "Síntese de voz no servidor disponível (edge-tts)."
            if available
            else "Sem síntese no servidor — a interface usa as vozes do sistema (Web Speech API) para falar."
        ),
    }


async def synthesize(text: str, *, voice: Optional[str] = None, rate: str = "+0%") -> Tuple[bytes, str]:
    """Sintetiza `text` e devolve `(áudio mp3, engine)`. Levanta `RuntimeError` sem motor."""
    try:
        import edge_tts  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover - depende do ambiente
        raise RuntimeError(
            "Sem síntese de voz no servidor. Instale `edge-tts` ou use a voz do sistema na interface."
        ) from exc

    clean = speech_text(text)
    if not clean:
        raise RuntimeError("Não há texto para sintetizar.")
    communicate = edge_tts.Communicate(clean, voice or DEFAULT_VOICE, rate=rate or "+0%")
    buffer = bytearray()
    async for chunk in communicate.stream():
        if chunk.get("type") == "audio" and chunk.get("data"):
            buffer.extend(chunk["data"])
    if not buffer:
        raise RuntimeError("A síntese não devolveu áudio.")
    return bytes(buffer), "edge-tts"


# ---------------------------------------------------------------------------
# Metamodelo
# ---------------------------------------------------------------------------
def meta(session: Any = None, backend: Optional[str] = None) -> Dict[str, Any]:
    """O que o Jarvis é e o que pode fazer (para a interface)."""
    from api import jarvis_agent  # noqa: PLC0415
    from api import ontology_ai  # noqa: PLC0415

    resolved = ontology_ai.available_backend(session, backend)
    agent_state = jarvis_agent.state()
    return {
        "about": {
            "name": NAME,
            "label": "Jarvis",
            "description": (
                "Assistente operacional do IQ OS: investiga nos dados da plataforma através do Hermes, "
                "delega trabalho autónomo no Hermes Agent (as skills dele e os 29 toolsets), "
                "executa operações do servidor MCP do sistema, vai à web e fala consigo em voz alta."
            ),
            "greeting": GREETING,
            "capabilities": [
                "Falar e ouvir (áudio → texto → resposta em voz)",
                "Investigação citada via gateway do Hermes",
                "Trabalho autónomo via Hermes Agent (skills + 29 toolsets: browser, terminal, ficheiros, código, visão, cron, …)",
                "Operações do MCP do sistema (205 operações curadas)",
                "Browser: pesquisa e leitura de páginas externas",
                "Skills partilhadas com o Hermes e o Chat IA",
            ],
        },
        "gateways": gateway.summary(),
        "agent": agent_state,
        "actions": actions_catalogue.catalogue(),
        "tools": gateway.catalog(),
        # `wake` tem de vir aqui também: é do `meta` que a página tira a disponibilidade
        # do botão da palavra de ativação (com só `stt`/`tts` o botão dizia
        # «indisponível» mesmo com o `faster-whisper` instalado).
        "voice": {"stt": stt_status(), "tts": tts_status(), "wake": wake_status()},
        "model": {
            "kind": resolved.get("kind"),
            "provider": resolved.get("provider"),
            "model": resolved.get("model"),
            "note": resolved.get("note"),
        },
        "limits": {
            "max_question_chars": MAX_QUESTION_CHARS,
            "max_tools_per_plan": MAX_TOOLS_PER_PLAN,
            "max_actions_per_plan": MAX_ACTIONS_PER_PLAN,
            "max_history": MAX_HISTORY,
        },
    }


def status() -> Dict[str, Any]:
    """Estado técnico (usado em `/jarvis/meta` e nos testes)."""
    return {
        "gateways": gateway.status(),
        "stt": stt_status(),
        "tts": tts_status(),
    }


__all__ = [
    "GREETING",
    "NAME",
    "ask",
    "clean_question",
    "meta",
    "plan",
    "speech_text",
    "status",
    "stream",
    "stt_status",
    "synthesize",
    "transcribe",
    "tts_status",
]