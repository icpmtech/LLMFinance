"""Testes do gateway **Hermes Agent** do Jarvis (`api/jarvis_agent.py`).

O que se cobre aqui é o que é determinístico e não depende de o agente estar a
correr: o catálogo (ferramentas, argumentos por omissão e escolha por palavras),
a leitura da biblioteca de skills do container e o comportamento quando o agente
está desligado (tem de degradar, nunca rebentar o `/jarvis/meta`).
"""
from __future__ import annotations

import asyncio
import datetime
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from api import jarvis_agent as agent  # noqa: E402
from api import jarvis_gateway as gateway  # noqa: E402

#: Uma amostra do `hermes skills list` (com a moldura do terminal e um nome
#: truncado a meio, como o CLI faz quando a linha não cabe).
SKILLS_TABLE = """
                                 Installed Skills
 ─────┬───────────────────────┬──────────────────────┬─────────┬─────────
 │ Name                  │ Category            │ Source  │ Trust   │ Status
 ─────┼───────────────────────┼──────────────────────┼─────────┼─────────
 │ claude-code           │ autonomous-ai-agents │ builtin │ builtin │ enabled
 │ hermes-agent          │ autonomous-ai-agents │ builtin │ builtin │ enabled
 │ architecture-diagram  │ creative             │ builtin │ builtin │ enabled
 │ songwriting-and-ai-mu │ creative             │ builtin │ builtin │ enabled
 │ arxiv                 │ research             │ builtin │ builtin │ enabled
 ─────┴───────────────────────┴──────────────────────┴─────────┴─────────
"""


@pytest.fixture(autouse=True)
def cache_limpa():
    agent.invalidate()
    yield
    agent.invalidate()


# --------------------------------------------------------------------------- catálogo
def test_gateway_do_agente_esta_no_catalogo():
    ids = {item["id"] for item in gateway.GATEWAYS}
    assert "agent" in ids
    assert {tool for tool in gateway.TOOLS if tool.startswith("agent.")} == {
        "agent.ask",
        "agent.skills",
        "agent.capabilities",
    }


def test_ferramentas_do_agente_estao_no_gateway_certo():
    for item in gateway.catalog("agent"):
        assert item["gateway"] == "agent"
        assert item["description"].strip(), f"{item['id']} sem descrição"


def test_default_args_entregam_a_pergunta_ou_as_palavras():
    assert gateway.default_args("agent.ask", "delega isto") == {"task": "delega isto"}
    # Os filtros recebem as palavras distintivas (sem verbos nem perguntas).
    assert gateway.default_args("agent.skills", "quais são as tuas skills de pesquisa?") == {
        "query": "skills pesquisa"
    }
    foco = gateway.default_args("agent.capabilities", "que capacidades de browser existem?")
    assert foco is not None
    assert "browser" in foco["focus"], foco


def test_pick_tools_distingue_perguntar_do_delegar():
    assert "agent.skills" in gateway.pick_tools("quais são as tuas skills?", limit=3)
    escolhidas = gateway.pick_tools("delega no agente: investiga a dívida pública", limit=3)
    assert "agent.ask" in escolhidas


def test_contas_do_summary_incluem_o_agente():
    resumo = {entry["id"]: entry for entry in gateway.summary()}
    assert resumo["agent"]["tools"] == 3
    assert resumo["agent"]["label"] == "Hermes Agent"


# --------------------------------------------------------------------------- skills
def test_le_as_skills_do_container(monkeypatch):
    import api.hermes_agent_settings as settings

    capturado: dict[str, object] = {}

    def falso_exec(args, *, as_user=False, input_text=None, timeout=60.0):
        capturado["args"] = args
        capturado["as_user"] = as_user
        return 0, SKILLS_TABLE, ""

    monkeypatch.setattr(settings, "_exec", falso_exec)
    report = agent.skills()

    assert report["available"] is True
    assert report["total"] == 5
    assert [item["name"] for item in report["skills"]] == [
        "claude-code",
        "hermes-agent",
        "architecture-diagram",
        "songwriting-and-ai-mu",
        "arxiv",
    ]
    # O `COLUMNS` largo tem de ir dentro do container (por `sh -c`), senão o CLI
    # volta a truncar os nomes com «…».
    assert "COLUMNS=200" in " ".join(capturado["args"])  # type: ignore[arg-type]
    assert capturado["as_user"] is True


def test_skills_filtra_por_nome_e_categoria(monkeypatch):
    import api.hermes_agent_settings as settings

    monkeypatch.setattr(settings, "_exec", lambda *a, **k: (0, SKILLS_TABLE, ""))
    por_categoria = agent.skills(query="research")
    assert [item["name"] for item in por_categoria["skills"]] == ["arxiv"]
    assert por_categoria["matched"] == 1
    assert por_categoria["total"] == 5

    por_nome = agent.skills(query="hermes")
    assert [item["name"] for item in por_nome["skills"]] == ["hermes-agent"]


def test_sem_docker_as_skills_degradam(monkeypatch):
    import api.hermes_agent_settings as settings

    def sem_docker(*args, **kwargs):
        raise RuntimeError("O comando `docker` não está disponível neste processo")

    monkeypatch.setattr(settings, "_exec", sem_docker)
    report = agent.skills()
    assert report["available"] is False
    assert report["total"] == 0
    assert report["skills"] == []


# --------------------------------------------------------------------------- capacidades
def test_capacidades_filtram_por_foco(monkeypatch):
    monkeypatch.setattr(
        agent,
        "_toolsets",
        lambda **kwargs: [
            {"id": "web", "label": "Web Search", "description": "web_search, web_extract"},
            {"id": "browser", "label": "Browser Automation", "description": "navigate, click"},
            {"id": "tts", "label": "Text-to-Speech", "description": "text_to_speech"},
        ],
    )
    report = agent.capabilities(focus="browser")
    assert report["total"] == 3
    assert [item["id"] for item in report["matched"]] == ["browser"]
    assert report["available"] is True


# --------------------------------------------------------------------------- agente desligado
def test_estado_com_o_agente_desligado_nao_levanta(monkeypatch):
    def falha(*args, **kwargs):
        raise ConnectionError("connection refused")

    monkeypatch.setattr(agent, "_get_json", falha)
    estado = agent.state()
    assert estado["available"] is False
    assert estado["id"] == "agent"
    assert "connection refused" in str(estado["error"])


def test_invoke_sem_task_devolve_erro_legivel():
    resultado = asyncio.run(gateway.invoke("agent.ask", {"task": "   "}))
    assert resultado["ok"] is False
    assert resultado["gateway"] == "agent"
    assert "task" in resultado["error"]


def test_invoke_delega_no_agente(monkeypatch):
    async def falso_ask(task, **kwargs):
        return {"answer": f"feito: {task}", "model": "hermes-agent", "usage": {}, "tool_calls": 2}

    monkeypatch.setattr(agent, "ask", falso_ask)
    resultado = asyncio.run(gateway.invoke("agent.ask", {"task": "organiza isto"}))
    assert resultado["ok"] is True
    assert resultado["data"]["answer"] == "feito: organiza isto"
    assert resultado["data"]["tool_calls"] == 2
    assert resultado["label"] == "Delegar no Hermes Agent"


def test_invoke_skills_usa_a_leitura_do_container(monkeypatch):
    monkeypatch.setattr(
        agent,
        "skills",
        lambda **kwargs: {"available": True, "total": 1, "skills": [{"name": "arxiv"}]},
    )
    resultado = asyncio.run(gateway.invoke("agent.skills", {"query": "research"}))
    assert resultado["ok"] is True
    assert resultado["data"]["total"] == 1


# ------------------------------------------------------ assistente (persona + histórico)
def test_assistant_system_traz_persona_data_e_os_dados_ao_lado(monkeypatch):
    monkeypatch.delenv("IQOS_API_BASE", raising=False)
    texto = agent.assistant_system("quantos contratos tem a EDP?")
    assert agent.PERSONA.split(".")[0] in texto
    assert "Hoje é" in texto
    assert str(datetime.date.today().year) in texto
    assert "http://backend:8000/search/unified" in texto
    assert "searxng" in texto
    assert "pesquisa-total" in texto and "websearch" in texto
    # O pedido vai citado para o agente não o perder no meio das regras.
    assert "quantos contratos tem a EDP?" in texto


def test_today_pt_escreve_a_data_em_portugues():
    hoje = datetime.date.today()
    texto = agent._today_pt()
    assert agent._WEEKDAYS[hoje.weekday()] in texto
    assert agent._MONTHS[hoje.month - 1] in texto
    assert str(hoje.year) in texto


def test_assistant_system_respeita_o_endereco_configurado(monkeypatch):
    monkeypatch.setenv("IQOS_API_BASE", "http://iqos.local:9000")
    monkeypatch.setenv("IQOS_SEARXNG_URL", "http://busca.local:8081")
    texto = agent.assistant_system()
    assert "http://iqos.local:9000/search/unified" in texto
    assert "http://busca.local:8081/search" in texto


class _RespostaFalsa:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _cliente_falso(capturado):
    class ClienteFalso:
        def __init__(self, *args, **kwargs):
            capturado["timeout"] = kwargs.get("timeout")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, json=None):
            capturado["url"] = url
            capturado["payload"] = json
            return _RespostaFalsa(
                {
                    "model": "hermes-agent",
                    "choices": [{"message": {"content": "a resposta"}}],
                    "usage": {"total_tokens": 10},
                }
            )

    return ClienteFalso


def test_ask_envia_persona_e_historico(monkeypatch):
    capturado: dict = {}
    monkeypatch.setattr(agent.httpx, "AsyncClient", _cliente_falso(capturado))
    resultado = asyncio.run(
        agent.ask(
            "e quanto é que isso valeu?",
            history=[
                {"role": "user", "content": "quem ganhou o contrato da Câmara de Lisboa?"},
                {"role": "assistant", "content": "A empresa X."},
                {"role": "system", "content": "isto não é um turno da conversa"},
                {"role": "user", "content": "   "},
            ],
        )
    )
    assert resultado["answer"] == "a resposta"
    assert resultado["model"] == "hermes-agent"
    assert resultado["task"] == "e quanto é que isso valeu?"
    mensagens = capturado["payload"]["messages"]
    assert mensagens[0]["role"] == "system"
    assert "IQ OS" in mensagens[0]["content"]
    # Só turnos de conversa (user/assistant) e sem mensagens vazias.
    assert [m["role"] for m in mensagens[1:]] == ["user", "assistant", "user"]
    assert mensagens[-1]["content"] == "e quanto é que isso valeu?"


def test_ask_sem_historico_manda_so_o_pedido(monkeypatch):
    capturado: dict = {}
    monkeypatch.setattr(agent.httpx, "AsyncClient", _cliente_falso(capturado))
    asyncio.run(agent.ask("olá"))
    mensagens = capturado["payload"]["messages"]
    assert [m["role"] for m in mensagens] == ["system", "user"]


def test_ask_aceita_persona_propria(monkeypatch):
    capturado: dict = {}
    monkeypatch.setattr(agent.httpx, "AsyncClient", _cliente_falso(capturado))
    asyncio.run(agent.ask("olá", system="Persona de teste."))
    assert capturado["payload"]["messages"][0]["content"] == "Persona de teste."


def test_delegar_no_agente_leva_persona_e_conversa(monkeypatch):
    capturado: dict = {}

    async def falso_ask(task, **kwargs):
        capturado["task"] = task
        capturado.update(kwargs)
        return {"answer": "feito", "model": "hermes-agent", "usage": {}, "tool_calls": 0}

    monkeypatch.setattr(agent, "ask", falso_ask)
    historico = [{"role": "user", "content": "fala-me da EDP"}]
    resultado = asyncio.run(
        gateway.invoke("agent.ask", {"task": "e as dívidas dela?"}, ctx={"history": historico})
    )
    assert resultado["ok"] is True
    assert capturado["task"] == "e as dívidas dela?"
    assert capturado["history"] == historico
    assert "Hoje é" in capturado["system"] and "e as dívidas dela?" in capturado["system"]
