"""Cérebros do chat servidos pelo **gateway** do IQ OS.

O `/chat` deixou de falar diretamente com um fornecedor de IA: com um destes
*backends*, a pergunta é entregue ao **gateway** (`api/jarvis_gateway.py`), que a
encaminha para um dos cérebros do IQ OS:

| Backend | Ferramenta do gateway | O que é |
| --- | --- | --- |
| `hermes-agent` | `agent.ask` | O **Hermes Agent** autónomo: decide sozinho as skills e as ferramentas (browser, terminal, ficheiros, código, cron, …) e corre a tarefa até ao fim. É o cérebro predefinido do chat. |
| `hermes` | `hermes.ask` | O **Hermes**: investigação nas fontes da plataforma e na web aberta, com resposta citada `[n]`. |

Porque é que isto passa pelo gateway e não chama o agente diretamente: o gateway
é o **mesmo caminho** que o Jarvis usa. Fica um só sítio que sabe falar com o
Hermes e com o agente (URL, chave, persona, histórico) e um só rasto para
mostrar (`gateway`, `tool`, `model`, nº de ferramentas usadas), em vez de um
caminho paralelo que divergiria.

Notas de desenho:

* o agente é **lento por natureza** (um ciclo completo pode levar minutos), pelo
  que cada cérebro tem o seu `timeout` (`CHAT_AGENT_TIMEOUT` /
  `CHAT_HERMES_TIMEOUT`) — melhor devolver «excedeu o tempo» do que deixar o
  utilizador à espera sem fim;
* a **skill** da plataforma não é injetada aqui: o agente tem as skills dele e o
  Hermes tem o plano de investigação próprio. O `/chat` não gera skill para estes
  backends (evita uma chamada a um modelo que ninguém usaria);
* `invoke()` nunca levanta — devolve `ok: False` com o erro. Uma falha chega ao
  utilizador como resposta `⚠️ …`, igual ao que acontece com os fornecedores
  cloud.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

#: Cérebro predefinido do chat (o que o `/chat` usa quando nada foi escolhido).
DEFAULT_BACKEND = "hermes-agent"

#: Tecto de histórico enviado ao cérebro (o contexto dele já é grande).
MAX_HISTORY_TURNS = 12
MAX_HISTORY_CHARS = 4000


@dataclass(frozen=True)
class ChatBrain:
    """Um cérebro do chat servido pelo gateway."""

    id: str
    tool: str
    gateway: str
    label: str
    hint: str
    arg: str
    timeout_env: str
    default_timeout: float

    has_timeout: bool = True

    def timeout(self) -> float:
        """Tempo máximo de espera (segundos), configurável por ambiente."""
        raw = (os.getenv(self.timeout_env) or "").strip()
        if raw:
            try:
                return max(5.0, float(raw))
            except ValueError:
                logger.warning("%s=%r não é um número; uso %.0fs.", self.timeout_env, raw, self.default_timeout)
        return self.default_timeout

    def public(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "hint": self.hint,
            "gateway": self.gateway,
            "tool": self.tool,
            "timeout_seconds": self.timeout(),
        }


#: Ordem = ordem no selector do chat. O primeiro é o predefinido.
BRAINS: Tuple[ChatBrain, ...] = (
    ChatBrain(
        id="hermes-agent",
        tool="agent.ask",
        gateway="agent",
        label="Hermes Agent",
        hint=(
            "Agente autónomo do IQ OS: usa as skills e as ferramentas dele (browser, "
            "terminal, ficheiros, código) e pode levar minutos."
        ),
        arg="task",
        timeout_env="CHAT_AGENT_TIMEOUT",
        default_timeout=180.0,
    ),
    ChatBrain(
        id="hermes",
        tool="hermes.ask",
        gateway="hermes",
        label="Hermes (investigação citada)",
        hint="Investiga nas fontes da plataforma e na web e responde com citações [n].",
        arg="question",
        timeout_env="CHAT_HERMES_TIMEOUT",
        default_timeout=120.0,
    ),
)

BRAINS_BY_ID: Dict[str, ChatBrain] = {brain.id: brain for brain in BRAINS}


def resolve(backend: str) -> Optional[ChatBrain]:
    """Cérebro do gateway para este `backend` (ou `None` se for um modelo normal)."""
    return BRAINS_BY_ID.get((backend or "").strip().lower())


def is_gateway_backend(backend: str) -> bool:
    """O `backend` é servido pelo gateway? (usado pelo `/chat` para decidir o caminho)"""
    return resolve(backend) is not None


def ids() -> List[str]:
    return [brain.id for brain in BRAINS]


def catalogue(*, probe: bool = True) -> Dict[str, Any]:
    """Catálogo para a interface, com a disponibilidade de cada cérebro.

    Só o `hermes-agent` depende de um serviço à parte (o container `hermes-agent`,
    perfil `agents`); o `hermes` corre no próprio backend. Com `probe=False` não
    se toca na rede — útil em testes.
    """
    agent: Dict[str, Any] = {}
    if probe:
        try:
            from api import jarvis_agent  # noqa: PLC0415

            agent = jarvis_agent.state()
        except Exception as exc:  # noqa: BLE001 - o catálogo nunca falha
            logger.debug("Hermes Agent indisponível: %s", exc)
            agent = {}

    items: List[Dict[str, Any]] = []
    for brain in BRAINS:
        detail = brain.public()
        if brain.gateway == "agent":
            disponivel = bool(agent.get("available"))
            detail.update(
                {
                    "available": disponivel,
                    "model": agent.get("model"),
                    "skills": agent.get("skills") or 0,
                    "toolsets": agent.get("toolsets") or 0,
                    "url": agent.get("url"),
                    "error": agent.get("error"),
                    "note": (
                        f"{agent.get('skills') or 0} skills · {agent.get('toolsets') or 0} toolsets"
                        if disponivel
                        else "o container `hermes-agent` (perfil `agents`) não está a responder"
                    ),
                }
            )
        else:
            detail.update({"available": True, "note": "investigação com citações (no próprio backend)"})
        items.append(detail)

    return {
        "default": DEFAULT_BACKEND,
        "backends": items,
        "agent": agent,
    }


# ---------------------------------------------------------------------------
# Tradução entre a conversa do chat e o pedido ao gateway
# ---------------------------------------------------------------------------


def _question(messages: Sequence[Any]) -> str:
    """Última mensagem do utilizador."""
    for message in reversed(list(messages or [])):
        if str(getattr(message, "role", "") or "").lower() == "user":
            return str(getattr(message, "content", "") or "").strip()
    return ""


def _history(messages: Sequence[Any]) -> List[Dict[str, str]]:
    """Diálogo anterior (sem a pergunta atual), para uma pergunta de seguimento.

    Nem o agente nem o Hermes têm estado: sem isto, «e quanto é que isso valeu?»
    chega-lhes como pedido isolado.
    """
    turns: List[Dict[str, str]] = []
    for message in list(messages or [])[:-1]:
        role = str(getattr(message, "role", "") or "").lower()
        if role not in {"user", "assistant"}:
            continue
        content = str(getattr(message, "content", "") or "").strip()
        if not content:
            continue
        turns.append({"role": role, "content": content[:MAX_HISTORY_CHARS]})
    return turns[-MAX_HISTORY_TURNS:]


def _sources(entry: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Citações do gateway no formato do chat (`Source`).

    O Hermes devolve as citações `[n]` da resposta em **`evidence`** (`n`, título,
    URL, extrato); em `sources` vêm só os *ids* das fontes consultadas (`internal`,
    `documents`, …), que não são citações. Quando quem responde é o agente dinâmico
    «Hermes», `sources` já traz documentos (`doc_title`/`text`).

    O Hermes Agent não devolve citações: a «fonte» é a delegação em si, com o
    modelo que a executou, para o utilizador ver *quem* fez o trabalho.
    """
    gateway = str(entry.get("gateway") or "")
    data = entry.get("data") if isinstance(entry.get("data"), dict) else {}

    if gateway == "hermes":
        items: List[Dict[str, Any]] = []
        for evidence in data.get("evidence") or []:
            if not isinstance(evidence, dict):
                continue
            items.append(
                {
                    "name": str(
                        evidence.get("title") or evidence.get("source") or f"evidência {len(items) + 1}"
                    )[:300],
                    "url": evidence.get("url") or None,
                    "value": (evidence.get("snippet") or evidence.get("source") or None),
                }
            )
        if not items:
            for index, source in enumerate(data.get("sources") or [], start=1):
                if not isinstance(source, dict):
                    continue  # id de fonte consultada, não é citação
                items.append(
                    {
                        "name": str(
                            source.get("title") or source.get("doc_title") or source.get("label") or f"fonte {index}"
                        )[:300],
                        "url": source.get("url") or None,
                        "value": (source.get("snippet") or source.get("text") or None),
                    }
                )
        return items[:12]

    if gateway == "agent":
        modelo = data.get("model") or "?"
        usadas = data.get("tool_calls") or 0
        return [
            {
                "name": "Hermes Agent",
                "value": f"modelo {modelo} · {usadas} ferramenta(s) neste ciclo",
            }
        ]
    return []


def _tool_call(brain: ChatBrain, args: Dict[str, Any], entry: Dict[str, Any]) -> Dict[str, Any]:
    """Rasto do que aconteceu, no formato `ToolCall` do chat."""
    data = entry.get("data") if isinstance(entry.get("data"), dict) else {}
    if entry.get("ok"):
        detalhe = (
            f"gateway {entry.get('gateway')} · {brain.tool}"
            + (f" · modelo {data.get('model')}" if data.get("model") else "")
            + (f" · {data.get('tool_calls')} ferramenta(s)" if data.get("tool_calls") else "")
        )
    else:
        detalhe = f"falhou: {entry.get('error') or 'erro desconhecido'}"
    return {"tool": brain.tool, "input": dict(args), "output": detalhe[:500]}


def _failure(brain: ChatBrain, error: Any) -> str:
    return (
        f"⚠️ Não foi possível responder pelo **{brain.label}**: {error}\n\n"
        "Verifique se o container do agente está a correr (perfil `agents`) e se o "
        "fornecedor de IA está configurado em Definições → Fornecedores de IA."
    )


async def _invoke(brain: ChatBrain, question: str, history: List[Dict[str, str]], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Chama o gateway, com o teto de tempo do cérebro. Nunca levanta."""
    from api import jarvis_gateway  # noqa: PLC0415

    args = {brain.arg: question}
    try:
        return await asyncio.wait_for(
            jarvis_gateway.invoke(brain.tool, args, ctx={**ctx, "history": history}),
            timeout=brain.timeout(),
        )
    except asyncio.TimeoutError:
        logger.info("Chat: %s excedeu %ss.", brain.tool, brain.timeout())
        return {
            "tool": brain.tool,
            "gateway": brain.gateway,
            "label": brain.label,
            "ok": False,
            "error": (
                f"excedeu {brain.timeout():.0f}s (o agente corre um ciclo autónomo completo; "
                "simplifique o pedido ou aumente o limite com "
                f"`{brain.timeout_env}`)"
            ),
        }


async def ask(
    messages: Sequence[Any],
    backend: str,
    *,
    user_id: Optional[str] = None,
    user_email: Optional[str] = None,
    session: Any = None,
) -> Dict[str, Any]:
    """Responde pelo gateway, no formato do chat (`message`/`sources`/`tools`/`model`)."""
    from api.models import ChatMessage  # noqa: PLC0415

    brain = resolve(backend)
    if brain is None:
        raise ValueError(f"`{backend}` não é um cérebro do gateway.")

    question = _question(messages)
    if not question:
        return {
            "message": ChatMessage(role="assistant", content="Escreva a pergunta que quer colocar."),
            "sources": [],
            "tools": [],
            "model": f"gateway:{brain.gateway}",
        }

    history = _history(messages)
    ctx: Dict[str, Any] = {"user_id": user_id, "session": session, "country": "PRT"}
    entry = await _invoke(brain, question, history, ctx)

    if entry.get("ok"):
        answer = str((entry.get("data") or {}).get("answer") or "").strip()
        if not answer:
            # Sem resposta mas sem erro: dizer quem calou, em vez de um genérico.
            answer = (
                f"⚠️ O **{brain.label}** concluiu sem devolver texto "
                f"(gateway `{entry.get('gateway')}` / `{brain.tool}`)."
            )
    else:
        answer = _failure(brain, entry.get("error") or "erro desconhecido")

    _log(brain, entry, answer, user_id=user_id, user_email=user_email)
    return {
        "message": ChatMessage(role="assistant", content=answer),
        "sources": _sources(entry),
        "tools": [_tool_call(brain, {brain.arg: question}, entry)],
        "model": f"gateway:{brain.gateway}",
    }


def ask_sync(
    messages: Sequence[Any],
    backend: str,
    *,
    user_id: Optional[str] = None,
    user_email: Optional[str] = None,
    session: Any = None,
) -> Dict[str, Any]:
    """Igual a `ask()`, para quem já está fora de um ciclo de eventos.

    O `/chat` corre o agente num thread (`asyncio.to_thread`), pelo que não há
    ciclo a decorrer — mesma solução que o caminho cloud usa.
    """
    return asyncio.run(ask(messages, backend, user_id=user_id, user_email=user_email, session=session))


def _log(
    brain: ChatBrain,
    entry: Dict[str, Any],
    answer: str,
    *,
    user_id: Optional[str],
    user_email: Optional[str],
) -> None:
    try:
        from api import events_service as events  # noqa: PLC0415

        events.log_event(
            "info" if entry.get("ok") else "error",
            "providers",
            f"Chat via gateway {brain.gateway}/{brain.tool} ({len(answer)} caracteres)",
            user_id=user_id,
            user_email=user_email,
            data={
                "backend": brain.id,
                "gateway": brain.gateway,
                "tool": brain.tool,
                "ok": bool(entry.get("ok")),
                "error": entry.get("error"),
            },
        )
    except Exception as exc:  # noqa: BLE001 - a telemetria não pode estragar a resposta
        logger.debug("evento do chat/gateway ignorado: %s", exc)


# ---------------------------------------------------------------------------
# Streaming (mesmo contrato SSE do resto do chat)
# ---------------------------------------------------------------------------


def sse(event: str, payload: Dict[str, Any]) -> str:
    """Uma linha SSE (o formato que `streamChat.ts` já sabe ler)."""
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def stream(
    messages: Sequence[Any],
    backend: str,
    *,
    user_id: Optional[str] = None,
    user_email: Optional[str] = None,
    session: Any = None,
) -> AsyncIterator[str]:
    """Resposta pelo gateway em SSE.

    Não há *tokens* a meio: o cérebro devolve a resposta completa. Emite-se o
    estado (para o ecrã não ficar mudo), a resposta como um único bloco e o
    `done` com as fontes e o rasto — **os mesmos passos** que os outros caminhos.
    """
    from api.models import ChatMessage  # noqa: PLC0415

    brain = resolve(backend)
    if brain is None:
        yield sse("error", {"message": f"`{backend}` não é um cérebro do gateway."})
        return

    yield sse("meta", {"model": f"gateway:{brain.gateway}", "backend": brain.id, "brain": brain.label})
    yield sse(
        "status",
        {"status": "busy", "detail": f"A entregar a tarefa ao {brain.label}… (pode levar minutos)"},
    )

    resultado = await ask(messages, backend, user_id=user_id, user_email=user_email, session=session)
    texto = str(resultado["message"].content or "")

    for pedaco in _chunks(texto):
        yield f"data: {json.dumps({'token': pedaco}, ensure_ascii=False)}\n\n"
        await asyncio.sleep(0)

    yield sse(
        "done",
        {
            "sources": resultado["sources"],
            "tools": resultado["tools"],
            "skill": None,
            "model": resultado["model"],
        },
    )


def _chunks(text: str) -> List[str]:
    """Divide a resposta em blocos, **por linhas**.

    Cortar a meio arriscava partir uma cerca de código markdown a meio (o chat
    desenha à medida que os pedaços chegam); por linhas o markdown mantém-se
    coerente em cada pedaço.
    """
    if not text:
        return [""]
    linhas = text.splitlines(keepends=True)
    blocos: List[str] = []
    atual = ""
    for linha in linhas:
        if len(atual) + len(linha) > 600 and atual:
            blocos.append(atual)
            atual = ""
        atual += linha
    if atual:
        blocos.append(atual)
    return blocos or [text]
