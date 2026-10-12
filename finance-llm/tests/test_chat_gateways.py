"""Chat servido pelo **gateway** (Hermes Agent / Hermes).

O `/chat` passou a ter o mesmo cérebro do Jarvis: com o backend `hermes-agent` (o
predefinido) ou `hermes`, a pergunta é entregue ao gateway
(`api/jarvis_gateway.py`) em vez de ir direta a um fornecedor de IA.

O que se testa aqui é o que **não** depende da rede: a tradução entre a conversa
do chat e o pedido ao gateway, a forma da resposta (`message`/`sources`/`tools`),
o teto de tempo de cada cérebro, o rasto quando falha e o encaminhamento nas
rotas (`/chat`, `/chat/stream`, `/chat/backends`). O gateway é sempre substituído
por um duplo — nenhum teste fala com o container do agente.
"""
from __future__ import annotations

import asyncio
import json
import sys
from typing import Any, Dict, List

import pytest

sys.path.insert(0, "c:/LLMFinance/finance-llm")

from fastapi.testclient import TestClient  # noqa: E402

from api import chat_gateways as gateways  # noqa: E402
from api import jarvis_gateway as gateway  # noqa: E402
from api import main as api_main  # noqa: E402
from api.auth_routes import CurrentSession, UserResponse, require_session  # noqa: E402
from api.models import ChatMessage  # noqa: E402


def _conversa(*pares: tuple[str, str]) -> List[ChatMessage]:
    return [ChatMessage(role=role, content=texto) for role, texto in pares]


def _run(corrotina: Any) -> Any:
    """Corre uma corrotina num teste síncrono.

    O projeto não usa `pytest-asyncio` (não está instalado): a convenção é
    `asyncio.run(...)` dentro de testes normais — ver os restantes ficheiros de
    `tests/`.
    """
    return asyncio.run(corrotina)


async def _coletar(gerador: Any) -> List[str]:
    """Consome um gerador assíncrono (o SSE do chat)."""
    return [pedaco async for pedaco in gerador]


# ------------------------------------------------------------------ catálogo


def test_ids_e_resolucao() -> None:
    assert gateways.ids() == ["hermes-agent", "hermes"]
    assert gateways.DEFAULT_BACKEND == "hermes-agent"
    assert gateways.is_gateway_backend("hermes-agent") is True
    assert gateways.is_gateway_backend("HERMES") is True
    assert gateways.is_gateway_backend("deepseek:deepseek-chat") is False
    assert gateways.is_gateway_backend("gpt2") is False
    assert gateways.resolve("hermes").tool == "hermes.ask"
    assert gateways.resolve("hermes-agent").tool == "agent.ask"
    assert gateways.resolve("não-existe") is None


def test_catalogo_sem_sondar_a_rede() -> None:
    catalogo = gateways.catalogue(probe=False)
    assert catalogo["default"] == "hermes-agent"
    por_id = {item["id"]: item for item in catalogo["backends"]}
    assert set(por_id) == {"hermes-agent", "hermes"}
    # Sem sonda, o agente não é dado como disponível (não se inventa estado).
    assert por_id["hermes-agent"]["available"] is False
    assert por_id["hermes"]["available"] is True
    assert por_id["hermes"]["gateway"] == "hermes"
    assert por_id["hermes-agent"]["timeout_seconds"] > 0


def test_catalogo_usa_o_estado_do_agente(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "api.jarvis_agent.state",
        lambda **_kwargs: {"available": True, "model": "deepseek-chat", "skills": 42, "toolsets": 29, "url": "http://x"},
    )
    catalogo = gateways.catalogue()
    agente = next(item for item in catalogo["backends"] if item["id"] == "hermes-agent")
    assert agente["available"] is True
    assert agente["model"] == "deepseek-chat"
    assert agente["skills"] == 42 and agente["toolsets"] == 29
    assert "42 skills" in agente["note"]


def test_catalogo_nunca_falha_se_o_agente_rebentar(monkeypatch: pytest.MonkeyPatch) -> None:
    def _explode(**_kwargs: Any) -> Any:
        raise RuntimeError("sem container")

    monkeypatch.setattr("api.jarvis_agent.state", _explode)
    catalogo = gateways.catalogue()
    agente = next(item for item in catalogo["backends"] if item["id"] == "hermes-agent")
    assert agente["available"] is False
    assert catalogo["backends"]  # o catálogo continua a existir


# ------------------------------------------------- conversa → pedido ao gateway


def test_pergunta_e_a_ultima_do_utilizador() -> None:
    conversa = _conversa(
        ("user", "primeira"),
        ("assistant", "resposta"),
        ("user", "e quanto é que isso valeu?"),
    )
    assert gateways._question(conversa) == "e quanto é que isso valeu?"


def test_historico_leva_o_dialogo_anterior_sem_a_pergunta_atual() -> None:
    """O agente é sem estado: sem histórico, um seguimento chega órfão."""
    conversa = _conversa(
        ("user", "contratos da Câmara de Lisboa"),
        ("assistant", "são 1234"),
        ("user", "e quanto valem?"),
    )
    historico = gateways._history(conversa)
    assert historico == [
        {"role": "user", "content": "contratos da Câmara de Lisboa"},
        {"role": "assistant", "content": "são 1234"},
    ]


def test_historico_ignora_system_e_vazios() -> None:
    conversa = _conversa(("system", "instruções"), ("user", ""), ("user", "olá"))
    assert gateways._history(conversa) == []


# ------------------------------------------------------------------- resposta


def test_pergunta_vai_para_o_agente_com_o_historico(monkeypatch: pytest.MonkeyPatch) -> None:
    visto: Dict[str, Any] = {}

    async def _invoke(tool_id: str, args: Dict[str, Any], *, ctx: Dict[str, Any] | None = None) -> Dict[str, Any]:
        visto.update({"tool_id": tool_id, "args": args, "ctx": ctx or {}})
        return {
            "tool": "agent.ask",
            "gateway": "agent",
            "label": "Hermes Agent",
            "ok": True,
            "data": {"answer": "42", "model": "deepseek-chat", "tool_calls": 3},
        }

    monkeypatch.setattr("api.jarvis_gateway.invoke", _invoke)
    resultado = _run(
        gateways.ask(
            _conversa(("user", "quanto valem?"), ("assistant", "…"), ("user", "e agora?")),
            "hermes-agent",
            user_id="u1",
        )
    )

    assert visto["tool_id"] == "agent.ask"
    assert visto["args"] == {"task": "e agora?"}
    assert visto["ctx"]["history"] == [{"role": "user", "content": "quanto valem?"}, {"role": "assistant", "content": "…"}]
    assert resultado["message"].content == "42"
    assert resultado["model"] == "gateway:agent"
    # O agente não dá citações: a «fonte» é a delegação, com o modelo que a correu.
    assert resultado["sources"][0]["name"] == "Hermes Agent"
    assert "deepseek-chat" in resultado["sources"][0]["value"]
    assert resultado["tools"][0]["tool"] == "agent.ask"
    assert "3 ferramenta(s)" in resultado["tools"][0]["output"]


def test_hermes_devolve_citacoes_como_fontes(monkeypatch: pytest.MonkeyPatch) -> None:
    """As citações `[n]` vêm em `evidence`; `sources` são só ids de fontes consultadas."""

    async def _invoke(tool_id: str, args: Dict[str, Any], *, ctx: Dict[str, Any] | None = None) -> Dict[str, Any]:
        assert tool_id == "hermes.ask"
        assert args == {"question": "insolvências da Cofely"}
        return {
            "tool": "hermes.ask",
            "gateway": "hermes",
            "label": "Investigar (Hermes)",
            "ok": True,
            "data": {
                "answer": "A empresa entrou em insolvência [1].",
                "sources": ["internal", "documents"],
                "evidence": [
                    {
                        "n": 1,
                        "title": "Publicação CIRE 123",
                        "source": "Plataforma IQ OS · factos",
                        "url": "https://cire/j/123",
                        "snippet": "PER em 2024",
                    },
                    {"n": 2, "title": "Notícia X", "url": None, "snippet": None},
                    "lixo",
                ],
            },
        }

    monkeypatch.setattr("api.jarvis_gateway.invoke", _invoke)
    resultado = _run(gateways.ask(_conversa(("user", "insolvências da Cofely")), "hermes"))

    fontes = resultado["sources"]
    assert fontes[0] == {"name": "Publicação CIRE 123", "url": "https://cire/j/123", "value": "PER em 2024"}
    assert fontes[1]["name"] == "Notícia X"
    assert len(fontes) == 2  # a string solta na lista não vira fonte
    assert resultado["model"] == "gateway:hermes"


def test_hermes_sem_evidencias_cai_para_as_fontes_do_agente_dinamico(monkeypatch: pytest.MonkeyPatch) -> None:
    """O ramo do agente dinâmico devolve documentos em `sources`, não evidências."""

    async def _invoke(tool_id: str, args: Dict[str, Any], *, ctx: Dict[str, Any] | None = None) -> Dict[str, Any]:
        return {
            "tool": tool_id,
            "gateway": "hermes",
            "ok": True,
            "data": {"answer": "ok", "sources": [{"doc_title": "Relatório anual", "text": "…"}]},
        }

    monkeypatch.setattr("api.jarvis_gateway.invoke", _invoke)
    resultado = _run(gateways.ask(_conversa(("user", "olá")), "hermes"))

    assert resultado["sources"][0]["name"] == "Relatório anual"
    assert resultado["sources"][0]["value"] == "…"


def test_gateway_de_hermes_le_a_resposta_de_text(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regressão: `hermes_service.ask()` põe a resposta em `text`, não em `answer`.

    Ler só `answer` dava resposta vazia em todas as investigações (no chat **e** no Jarvis).
    """

    async def _ask(question: str, **kwargs: Any) -> Dict[str, Any]:
        return {
            "text": "A resposta está no texto.",
            "sources": ["internal"],
            "evidence": [{"n": 1, "title": "Fonte", "url": "/x", "snippet": "s"}],
        }

    monkeypatch.setattr("api.hermes_service.ask", _ask)
    resposta = _run(gateway.invoke("hermes.ask", {"question": "olá"}))

    assert resposta["ok"] is True
    assert resposta["data"]["answer"] == "A resposta está no texto."
    assert resposta["data"]["evidence"][0]["n"] == 1


def test_falha_do_gateway_chega_como_resposta_e_nao_como_erro(monkeypatch: pytest.MonkeyPatch) -> None:
    """`invoke()` nunca levanta: devolve `ok: False`. O chat mostra ⚠️, não 500."""

    async def _invoke(tool_id: str, args: Dict[str, Any], *, ctx: Dict[str, Any] | None = None) -> Dict[str, Any]:
        return {"tool": tool_id, "gateway": "agent", "ok": False, "error": "connection refused"}

    monkeypatch.setattr("api.jarvis_gateway.invoke", _invoke)
    resultado = _run(gateways.ask(_conversa(("user", "olá")), "hermes-agent"))

    assert resultado["message"].content.startswith("⚠️")
    assert "connection refused" in resultado["message"].content
    assert "falhou" in resultado["tools"][0]["output"]


def test_teto_de_tempo_do_cerebro(monkeypatch: pytest.MonkeyPatch) -> None:
    """Uma delegação sem fim não pode prender o pedido: o cérebro tem teto."""
    monkeypatch.setenv("CHAT_AGENT_TIMEOUT", "0.2")

    async def _lento(tool_id: str, args: Dict[str, Any], *, ctx: Dict[str, Any] | None = None) -> Dict[str, Any]:
        await asyncio.sleep(5)
        return {"ok": True, "data": {"answer": "tarde demais"}}

    monkeypatch.setattr("api.jarvis_gateway.invoke", _lento)
    resultado = _run(gateways.ask(_conversa(("user", "faz isto")), "hermes-agent"))

    assert "⚠️" in resultado["message"].content
    assert "excedeu" in resultado["message"].content
    assert "CHAT_AGENT_TIMEOUT" in resultado["message"].content


def test_teto_de_tempo_configuravel_e_tolerante() -> None:
    cerebro = gateways.resolve("hermes-agent")
    assert cerebro is not None
    import os

    antigo = os.environ.get("CHAT_AGENT_TIMEOUT")
    try:
        os.environ["CHAT_AGENT_TIMEOUT"] = "45"
        assert cerebro.timeout() == 45.0
        os.environ["CHAT_AGENT_TIMEOUT"] = "nem por isso"
        assert cerebro.timeout() == cerebro.default_timeout
        os.environ["CHAT_AGENT_TIMEOUT"] = "0"
        assert cerebro.timeout() >= 5.0  # um teto absurdo não é aceite
    finally:
        if antigo is None:
            os.environ.pop("CHAT_AGENT_TIMEOUT", None)
        else:
            os.environ["CHAT_AGENT_TIMEOUT"] = antigo


def test_pergunta_vazia_nao_chama_o_gateway(monkeypatch: pytest.MonkeyPatch) -> None:
    chamadas: List[str] = []

    async def _invoke(tool_id: str, args: Dict[str, Any], *, ctx: Dict[str, Any] | None = None) -> Dict[str, Any]:
        chamadas.append(tool_id)
        return {"ok": True, "data": {"answer": "nunca"}}

    monkeypatch.setattr("api.jarvis_gateway.invoke", _invoke)
    resultado = _run(gateways.ask([], "hermes-agent"))
    assert chamadas == []
    assert "Escreva a pergunta" in resultado["message"].content


# ------------------------------------------------------------------- streaming


def test_stream_emite_os_mesmos_passos_que_os_outros_caminhos(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _invoke(tool_id: str, args: Dict[str, Any], *, ctx: Dict[str, Any] | None = None) -> Dict[str, Any]:
        return {
            "tool": "agent.ask",
            "gateway": "agent",
            "ok": True,
            "data": {"answer": "linha um\nlinha dois", "model": "m", "tool_calls": 1},
        }

    monkeypatch.setattr("api.jarvis_gateway.invoke", _invoke)
    pedacos = _run(_coletar(gateways.stream(_conversa(("user", "olá")), "hermes-agent")))

    texto = "".join(pedacos)
    assert "event: meta" in texto
    assert "event: status" in texto
    assert "event: done" in texto
    assert '"token"' in texto

    # A resposta reconstruída bate certo (o chat escreve à medida que chega).
    tokens = []
    for linha in texto.splitlines():
        if linha.startswith("data: ") and '"token"' in linha:
            tokens.append(json.loads(linha[6:])["token"])
    assert "".join(tokens) == "linha um\nlinha dois"


def test_stream_de_backend_desconhecido_avisa() -> None:
    pedacos = _run(_coletar(gateways.stream(_conversa(("user", "olá")), "gpt2")))
    assert len(pedacos) == 1
    assert "event: error" in pedacos[0]


# ------------------------------------------------------- encaminhamento no chat


def test_run_chat_encaminha_para_o_gateway(monkeypatch: pytest.MonkeyPatch) -> None:
    from api import agent

    visto: Dict[str, Any] = {}

    def _ask(messages: Any, backend: str, **kwargs: Any) -> Dict[str, Any]:
        visto.update({"backend": backend, "kwargs": kwargs})
        return {
            "message": ChatMessage(role="assistant", content="pelo agente"),
            "sources": [],
            "tools": [],
            "model": "gateway:agent",
        }

    monkeypatch.setattr("api.chat_gateways.ask_sync", _ask)
    resultado = agent.run_chat(_conversa(("user", "olá")), "hermes-agent", user_id="u1")

    assert visto["backend"] == "hermes-agent"
    assert visto["kwargs"]["user_id"] == "u1"
    assert "skill_block" not in visto["kwargs"]  # o agente usa as skills dele
    assert resultado["message"].content == "pelo agente"


def test_run_chat_nao_mexe_nos_outros_backends() -> None:
    """`gpt2` continua a ser o modelo local (o caminho antigo intacto)."""
    from api import agent

    resultado = agent.run_chat(_conversa(("user", "olá")), "gpt2")
    assert resultado["model"] == "finance-llm-gpt2"


# ------------------------------------------------------------------ as rotas


def _sessao(email: str = "prova@exemplo.pt") -> CurrentSession:
    nome = email.split("@")[0]
    return CurrentSession(
        user=UserResponse(
            id=f"u-{email}",
            email=email,
            name=nome,
            role="member",
            initials=(nome[:2] or "??").upper(),
            status="active",
            locale="pt-PT",
            timezone="Europe/Lisbon",
        ),
        session_id="s-prova",
        token="t-prova",
    )


def test_rota_chat_backends(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "api.jarvis_agent.state",
        lambda **_kwargs: {"available": True, "model": "deepseek-chat", "skills": 7, "toolsets": 29},
    )
    cliente = TestClient(api_main.app, base_url="http://prova")
    resposta = cliente.get("/chat/backends")
    assert resposta.status_code == 200
    dados = resposta.json()
    assert dados["default"] == "hermes-agent"
    assert {item["id"] for item in dados["backends"]} == {"hermes-agent", "hermes"}
    # Sem sonda: não se toca na rede (útil para clientes que só querem a lista).
    resposta = cliente.get("/chat/backends?probe=false")
    assert resposta.status_code == 200
    assert resposta.json()["backends"][0]["available"] is False


def test_rota_chat_responde_pelo_agente(monkeypatch: pytest.MonkeyPatch) -> None:
    """`POST /chat?backend=hermes-agent` devolve a resposta do agente, com o rasto."""
    chamadas: List[str] = []

    async def _invoke(tool_id: str, args: Dict[str, Any], *, ctx: Dict[str, Any] | None = None) -> Dict[str, Any]:
        chamadas.append(tool_id)
        return {
            "tool": "agent.ask",
            "gateway": "agent",
            "label": "Hermes Agent",
            "ok": True,
            "data": {"answer": "Respondido pelo agente.", "model": "deepseek-chat", "tool_calls": 2},
        }

    monkeypatch.setattr("api.jarvis_gateway.invoke", _invoke)
    api_main.app.dependency_overrides[require_session] = _sessao
    try:
        cliente = TestClient(api_main.app, base_url="http://prova")
        resposta = cliente.post(
            "/chat?backend=hermes-agent",
            json={"messages": [{"role": "user", "content": "quem sou eu?"}], "model": "finance-llm", "backend": "hermes-agent"},
        )
    finally:
        api_main.app.dependency_overrides.pop(require_session, None)

    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["message"]["content"] == "Respondido pelo agente."
    assert corpo["tools"][0]["tool"] == "agent.ask"
    assert corpo["sources"][0]["name"] == "Hermes Agent"
    # A skill da plataforma não é gerada para estes backends (não havia skill a usar).
    assert corpo["skill"] is None
    assert chamadas == ["agent.ask"]


def test_rota_chat_stream_pelo_agente(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _invoke(tool_id: str, args: Dict[str, Any], *, ctx: Dict[str, Any] | None = None) -> Dict[str, Any]:
        return {"tool": "agent.ask", "gateway": "agent", "ok": True, "data": {"answer": "feito", "model": "m"}}

    monkeypatch.setattr("api.jarvis_gateway.invoke", _invoke)
    api_main.app.dependency_overrides[require_session] = _sessao
    try:
        cliente = TestClient(api_main.app, base_url="http://prova")
        with cliente.stream(
            "POST",
            "/chat/stream?backend=hermes-agent",
            json={"messages": [{"role": "user", "content": "olá"}], "backend": "hermes-agent"},
        ) as resposta:
            assert resposta.status_code == 200
            corpo = "".join(resposta.iter_text())
    finally:
        api_main.app.dependency_overrides.pop(require_session, None)

    assert "event: status" in corpo
    assert "event: done" in corpo
    assert '"token"' in corpo
