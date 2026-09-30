"""Testes do **Jarvis** (`api/jarvis_gateway.py` e `api/jarvis_service.py`).

Cobrem o que é determinístico e não depende de rede nem de Elasticsearch:

- o catálogo dos gateways (Hermes, MCP do sistema e browser) e os argumentos
  por omissão, que garantem que o plano sem modelo nunca gera um 422;
- a escolha de ferramentas por palavras-chave (o plano de recurso);
- a limpeza do texto para leitura em voz alta;
- o ciclo `ask` completo, com os gateways substituídos por dublês;
- o comportamento da voz quando não há motor no servidor (cai para o browser).
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from api import jarvis_gateway as gateway  # noqa: E402
from api import jarvis_service as service  # noqa: E402


# ---------------------------------------------------------------------------
# Catálogo dos gateways
# ---------------------------------------------------------------------------
def test_catalogo_tem_os_tres_gateways():
    ids = {item["id"] for item in gateway.GATEWAYS}
    assert ids == {"hermes", "mcp", "web"}


def test_catalogo_publica_ferramentas_dos_tres_gateways():
    catalog = gateway.catalog()
    assert catalog, "o catálogo não pode estar vazio"
    por_gateway = {item["gateway"] for item in catalog}
    assert por_gateway == {"hermes", "mcp", "web"}
    for item in catalog:
        assert item["id"], "todas as ferramentas precisam de identificador"
        assert item["label"], f"{item['id']} sem etiqueta"
        assert item["description"], f"{item['id']} sem descrição"


def test_catalogo_filtra_por_gateway():
    web = gateway.catalog("web")
    assert {item["id"] for item in web} == {"web.search", "web.open", "web.research"}
    assert all(item["gateway"] == "web" for item in web)


def test_summary_conta_ferramentas_por_gateway():
    resumo = gateway.summary()
    assert {entry["id"] for entry in resumo} == {"hermes", "mcp", "web"}
    assert all(entry["tools"] > 0 for entry in resumo), "nenhum gateway pode ficar sem ferramentas"


def test_status_inclui_o_estado_da_web():
    status = service.status()
    assert status["gateways"]["tools"] == len(gateway.TOOLS)
    assert status["gateways"]["web"]["available"] is True


# ---------------------------------------------------------------------------
# Argumentos por omissão (a rede de segurança do plano sem modelo)
# ---------------------------------------------------------------------------
def test_default_args_para_ferramentas_de_texto():
    assert gateway.default_args("hermes.ask", "quem é a EDP?") == {"question": "quem é a EDP?"}
    assert gateway.default_args("web.search", "notícias de hoje") == {"query": "notícias de hoje"}
    assert gateway.default_args("search_unified", "insolvências") == {"q": "insolvências"}


def test_default_args_para_corpos_json_conhecidos():
    assert gateway.default_args("contratos_search", "energia 2025") == {
        "payload": {"q": "energia 2025", "year": 2025}
    }
    assert gateway.default_args("rag_chat", "o que dizem os documentos?") == {
        "payload": {"question": "o que dizem os documentos?"}
    }
    assert gateway.default_args("sentiment_analyze_text", "gosto muito disto") == {
        "payload": {"text": "gosto muito disto"}
    }


def test_contratos_search_respeita_maiores_e_o_ano():
    # «maiores» tem de ordenar por valor: por omissão a API ordena por data.
    corpo = gateway.default_args("contratos_search", "Quais são os maiores contratos públicos de energia em 2025?")
    assert corpo["payload"]["sort_by"] == "precoContratual"
    assert corpo["payload"]["sort_order"] == "desc"
    assert corpo["payload"]["year"] == 2025
    # Sem «maiores» nem ano, não se inventa ordenação nem filtro.
    simples = gateway.default_args("contratos_search", "contratos de medicamentos")
    assert "sort_by" not in simples["payload"]
    assert "year" not in simples["payload"]


def test_default_args_nao_adivinha_parametros_especificos():
    # Uma ação/empresa exige um ticker/NIF que não se pode inventar.
    assert gateway.default_args("market_history", "como está a EDP?") is None
    assert gateway.default_args("contrato_detail", "o contrato 123") is None
    assert gateway.default_args("visualizador_query", "vendas por mês") is None
    assert gateway.default_args("ferramenta.inexistente", "x") is None


def test_default_args_extrai_url_da_pergunta():
    args = gateway.default_args("web.open", "vê isto https://www.base.gov.pt/Base4/pt/noticias/2025/ por favor")
    assert args == {"url": "https://www.base.gov.pt/Base4/pt/noticias/2025/"}
    assert gateway.default_args("web.open", "abre uma página qualquer") is None


# ---------------------------------------------------------------------------
# Termos de pesquisa (as pesquisas recebem termos, não perguntas)
# ---------------------------------------------------------------------------
def test_search_terms_deixa_so_as_palavras_distintivas():
    termos = gateway.search_terms("Quais são os maiores contratos públicos de energia em 2025?")
    # As palavras mantêm os acentos (quem normaliza é o analisador do
    # Elasticsearch); o que sai são as palavras vazias e as da pergunta.
    assert termos == "maiores contratos públicos energia 2025"
    assert "os" not in termos.split()
    assert "são" not in termos.split()
    assert "quais" not in termos.split()


def test_search_terms_preserva_nif_e_ticker():
    assert "500697256" in gateway.search_terms("Quais os contratos da empresa com NIF 500697256?")
    assert "EDP.LS" in gateway.search_terms("Como está a ação EDP.LS hoje?")


def test_search_terms_mantem_anos_e_descarta_outros_numeros():
    termos = gateway.search_terms("contratos de 2024 e código 12345")
    assert "2024" in termos.split()
    assert "12345" not in termos.split()


def test_search_terms_sem_palavras_uteis_devolve_o_texto():
    assert gateway.search_terms("de a o e") == "de a o e"

def test_pesquisas_do_mcp_recebem_termos_mas_a_ia_recebe_a_pergunta():
    pergunta = "Quais são os maiores contratos públicos de energia em 2025?"
    # Pesquisa: palavras distintivas (mais a ordenação por valor e o ano).
    corpo = gateway.default_args("contratos_search", pergunta)
    assert corpo["payload"]["q"] == "maiores contratos públicos energia 2025"
    assert corpo["payload"]["sort_by"] == "precoContratual"
    assert gateway.default_args("search_unified", pergunta) == {"q": "maiores contratos públicos energia 2025"}
    # IA: a pergunta inteira (reduzi-la a palavras-chave destruiria o pedido).
    assert gateway.default_args("rag_chat", pergunta) == {"payload": {"question": pergunta}}
    assert gateway.default_args("ontology_ai_answer", pergunta) == {"payload": {"question": pergunta}}
    assert gateway.default_args("sentiment_analyze_text", "gosto muito disto") == {
        "payload": {"text": "gosto muito disto"}
    }
    # Hermes e web: a pergunta inteira.
    assert gateway.default_args("hermes.ask", pergunta) == {"question": pergunta}


# ---------------------------------------------------------------------------
# Plano sem modelo
# ---------------------------------------------------------------------------
def test_pick_tools_encontra_contratos():
    escolhidas = gateway.pick_tools("Quais são os maiores contratos públicos de energia em 2025?")
    assert "contratos_search" in escolhidas
    assert "hermes.ask" in escolhidas


def test_pick_tools_prefere_abrir_a_pagina_quando_ha_url():
    escolhidas = gateway.pick_tools("resume isto https://example.com/artigo para mim")
    assert escolhidas[0] == "web.open"


def test_pick_tools_nunca_escolhe_ferramenta_sem_argumentos_possiveis():
    for tool_id in gateway.pick_tools("contratos empresas mercado notícias insolvências documentos"):
        assert gateway.default_args(tool_id, "x") is not None, f"{tool_id} não tem argumentos possíveis"


def test_pick_tools_cai_no_hermes_quando_nao_ha_pistas():
    assert gateway.pick_tools("boa tarde") == ["hermes.ask"]


def test_pick_tools_nao_acrescenta_hermes_a_consultas_curtas():
    # «EDP» é uma consulta curta: não vale a pena pagar o plano do Hermes.
    escolhidas = gateway.pick_tools("contratos EDP")
    assert "hermes.ask" not in escolhidas


def test_plano_heuristico_preenche_os_argumentos():
    plano = asyncio.run(service.plan("Quais os maiores contratos de energia?", None))
    assert plano["source"] == "heuristica"
    assert plano["tools"], "o plano tem de trazer pelo menos uma ferramenta"
    for call in plano["tools"]:
        resolvido = service._ensure_question_arg(call, "Quais os maiores contratos de energia?")
        assert "skip" not in resolvido, f"{call['tool']} ficou sem argumentos"


def test_ensure_question_arg_marca_em_falta_o_que_nao_se_pode_inferir():
    resolvido = service._ensure_question_arg({"tool": "market_history", "args": {}}, "EDP")
    assert resolvido.get("skip")


def test_ensure_question_arg_respeita_o_plano():
    resolvido = service._ensure_question_arg(
        {"tool": "market_history", "args": {"ticker": "EDP.LS"}}, "como está a EDP?"
    )
    assert resolvido["args"]["ticker"] == "EDP.LS"
    assert "skip" not in resolvido


# ---------------------------------------------------------------------------
# Texto para voz
# ---------------------------------------------------------------------------
def test_speech_text_limpa_markdown():
    texto = "## Resposta\n\n**Os maiores contratos** são da EDP [1].\n\n- primeiro\n- segundo\n\nVeja `codigo`."
    falado = service.speech_text(texto)
    assert "**" not in falado
    assert "#" not in falado
    assert "`" not in falado
    assert "(fonte 1)" in falado
    assert falado.startswith("Resposta.")


def test_speech_text_remove_tabelas_e_reguas():
    falado = service.speech_text("| a | b |\n|---|---|\n| 1 | 2 |\n\n---\n\nfim")
    assert "|" not in falado
    assert "---" not in falado
    assert "fim" in falado


def test_speech_text_corta_texto_longo():
    falado = service.speech_text("Frase completa. " * 200)
    assert len(falado) <= service.SPEECH_MAX_CHARS


def test_speech_text_vazio():
    assert service.speech_text("") == ""


# ---------------------------------------------------------------------------
# Ciclo ask — gateways substituídos por dublês
# ---------------------------------------------------------------------------
@pytest.fixture()
def duble_gateways(monkeypatch):
    """Substitui `gateway.invoke` e o planeador por dublês previsíveis."""
    chamadas: list[tuple[str, dict]] = []

    async def fake_invoke(tool_id, args=None, *, ctx=None):
        chamadas.append((tool_id, dict(args or {})))
        if tool_id == "hermes.ask":
            return {
                "tool": tool_id,
                "gateway": "hermes",
                "label": "Investigar (Hermes)",
                "ok": True,
                "data": {
                    "answer": "A EDP lidera a contratação de energia [1].",
                    "sources": [{"title": "Base.gov.pt", "url": "https://www.base.gov.pt/"}],
                    "subquestions": [],
                },
            }
        if tool_id == "web.search":
            return {
                "tool": tool_id,
                "gateway": "web",
                "label": "Pesquisar na web",
                "ok": True,
                "data": {
                    "query": args.get("query"),
                    "results": [{"title": "Notícia", "url": "https://example.com/n", "snippet": "…"}],
                },
            }
        return {
            "tool": tool_id,
            "gateway": "mcp",
            "label": gateway.TOOLS[tool_id].label if tool_id in gateway.TOOLS else tool_id,
            "ok": True,
            "data": {"total": 42},
        }

    monkeypatch.setattr(service.gateway, "invoke", fake_invoke)

    async def fake_plan(question, backend):
        return {
            "tools": [
                {"tool": "contratos_search", "args": {}},
                {"tool": "hermes.ask", "args": {"question": question}},
            ],
            "reason": "plano de teste",
            "source": "teste",
        }

    monkeypatch.setattr(service, "plan", fake_plan)

    async def fake_skills(question, *, session=None, backend=None, **kwargs):
        return {
            "id": "skill-teste",
            "raw": {"id": "skill-teste", "title": "Investigar contratos de energia"},
            "public": {"id": "skill-teste", "title": "Investigar contratos de energia", "steps": ["recolher", "citar"]},
            "block": "Método de teste.",
            "mode": "biblioteca",
        }

    monkeypatch.setattr("api.skills_service.for_request", fake_skills)
    monkeypatch.setattr("api.skills_service.finish", lambda *a, **k: None)
    return chamadas


def test_ask_corre_os_gateways_e_devolve_passos(duble_gateways):
    resultado = asyncio.run(service.ask("Quais os maiores contratos de energia?"))

    assert resultado["answered"] is True
    assert "EDP" in resultado["answer"]
    assert [item["tool"] for item in resultado["tools_used"]] == ["contratos_search", "hermes.ask"]
    tipos = [step["kind"] for step in resultado["steps"]]
    for esperado in ("ouvir", "modelo", "skill", "plano", "ferramenta", "resultado", "responder"):
        assert esperado in tipos, f"falta o passo {esperado}"


def test_ask_devolve_citacoes_e_sugestoes(duble_gateways):
    resultado = asyncio.run(service.ask("Quais os maiores contratos de energia?"))
    urls = {source.get("url") for source in resultado["sources"]}
    assert "https://www.base.gov.pt/" in urls
    assert any(source["origin"] == "Hermes" for source in resultado["sources"])
    assert resultado["suggestions"], "o Jarvis deve sugerir a pergunta seguinte"
    assert resultado["speech"], "a resposta tem de ter uma versão falada"


def test_ask_guarda_a_skill(duble_gateways):
    resultado = asyncio.run(service.ask("Quais os maiores contratos de energia?"))
    assert resultado["skill"]["id"] == "skill-teste"
    assert resultado["skill"]["title"] == "Investigar contratos de energia"


def test_ask_sem_pergunta_falha():
    with pytest.raises(ValueError):
        asyncio.run(service.ask("   "))


def test_ask_em_modo_factual_sem_gateways(monkeypatch):
    async def fake_invoke(tool_id, args=None, *, ctx=None):
        return {"tool": tool_id, "gateway": "hermes", "label": "Investigar (Hermes)", "ok": True, "data": {"answer": None, "sources": [{"title": "Base.gov.pt"}]}}

    async def fake_plan(question, backend):
        return {"tools": [{"tool": "hermes.ask", "args": {"question": question}}], "reason": "t", "source": "t"}

    async def fake_skills(question, **kwargs):
        return {"id": None, "raw": None, "public": None, "block": "", "mode": None}

    monkeypatch.setattr(service.gateway, "invoke", fake_invoke)
    monkeypatch.setattr(service, "plan", fake_plan)
    monkeypatch.setattr("api.skills_service.for_request", fake_skills)

    resultado = asyncio.run(service.ask("pergunta sem modelo"))
    assert "modo factual" in resultado["answer"]
    # Sem resposta redigida, mostra pelo menos as evidências recolhidas.
    assert "Base.gov.pt" in resultado["answer"]


def test_ask_sem_ferramentas_explica_o_modo_factual(monkeypatch):
    async def fake_plan(question, backend):
        return {"tools": [], "reason": "nada serve", "source": "t"}

    async def fake_skills(question, **kwargs):
        return {"id": None, "raw": None, "public": None, "block": "", "mode": None}

    monkeypatch.setattr(service, "plan", fake_plan)
    monkeypatch.setattr("api.skills_service.for_request", fake_skills)

    resultado = asyncio.run(service.ask("pergunta estranha"))
    assert "modo factual" in resultado["answer"]
    assert resultado["tools_used"] == []


def test_ask_marca_as_ferramentas_que_falham(monkeypatch):
    async def fake_invoke(tool_id, args=None, *, ctx=None):
        return {"tool": tool_id, "gateway": "mcp", "label": "Pesquisar", "ok": False, "error": "HTTP 500"}

    async def fake_plan(question, backend):
        return {"tools": [{"tool": "contratos_search", "args": {}}], "reason": "t", "source": "t"}

    async def fake_skills(question, **kwargs):
        return {"id": None, "raw": None, "public": None, "block": "", "mode": None}

    monkeypatch.setattr(service.gateway, "invoke", fake_invoke)
    monkeypatch.setattr(service, "plan", fake_plan)
    monkeypatch.setattr("api.skills_service.for_request", fake_skills)

    resultado = asyncio.run(service.ask("contratos"))
    assert resultado["tools_used"][0]["ok"] is False
    assert "HTTP 500" in resultado["answer"]


# ---------------------------------------------------------------------------
# Resumo factual (sem modelo)
# ---------------------------------------------------------------------------
def test_summarise_payload_resume_listas_em_vez_de_despejar_json():
    payload = {
        "total": 2237233,
        "items": [
            {"idcontrato": "1", "objectoContrato": "Aquisição de medicamentos", "precoContratual": 1200},
            {"idcontrato": "2", "objectoContrato": "Serviços de banca", "precoContratual": 900},
        ],
    }
    resumo = service._summarise_payload(payload)
    assert "total=2237233" in resumo
    assert "Aquisição de medicamentos" in resumo
    assert "{" not in resumo, "o modo factual não deve despejar JSON cru"


def test_summarise_payload_sem_listas_mostra_os_escalares():
    resumo = service._summarise_payload({"status": "healthy", "features": ["chat", "rag"], "count": 3})
    assert "healthy" in resumo
    assert "count=3" in resumo or "count" in resumo


def test_summarise_payload_aceita_valores_nao_dicionario():
    assert service._summarise_payload([1, 2, 3]).startswith("[1, 2, 3]")


def test_factual_answer_mostra_o_erro_das_ferramentas_que_falham():
    texto = service._factual_answer(
        "pergunta", [{"tool": "t", "label": "Pesquisar", "gateway": "mcp", "ok": False, "error": "HTTP 500"}]
    )
    assert "HTTP 500" in texto


def test_factual_answer_desembrulha_o_envelope_do_mcp():
    resultados = [
        {
            "tool": "contratos_search",
            "gateway": "mcp",
            "label": "Pesquisar contratos públicos",
            "ok": True,
            "data": {
                "operation": "contratos_search",
                "label": "Pesquisar contratos públicos",
                "method": "POST",
                "path": "/contracts/search",
                "data": {
                    "total": 2237233,
                    "items": [{"objectoContrato": "Aquisição de medicamentos", "precoContratual": 1200}],
                },
            },
        }
    ]
    texto = service._factual_answer("contratos", resultados)
    assert "total=2237233" in texto
    assert "Aquisição de medicamentos" in texto
    assert "/contracts/search" not in texto, "o envelope do gateway não interessa à resposta"


def test_evidencia_para_o_modelo_nao_leva_o_envelope_do_mcp():
    evidencias = service._evidence_from(
        [
            {
                "tool": "contratos_search",
                "gateway": "mcp",
                "ok": True,
                "data": {"operation": "contratos_search", "path": "/contracts/search", "data": {"total": 7}},
            }
        ]
    )
    assert evidencias[0]["data"] == {"total": 7}


# ---------------------------------------------------------------------------
# Streaming
# ---------------------------------------------------------------------------
def test_stream_emite_os_eventos_esperados(duble_gateways):
    async def collect() -> list[str]:
        frames: list[str] = []
        async for frame in service.stream("Quais os maiores contratos de energia?"):
            frames.append(frame)
        return frames

    frames = asyncio.run(collect())
    texto = "".join(frames)
    for evento in ("event: passo", "event: plano", "event: skill", "event: ferramenta", "event: resposta", "event: fim"):
        assert evento in texto, f"o stream não emitiu {evento}"
    assert "EDP" in texto
    assert texto.rstrip().endswith("}") and "\n\n" in texto


def test_stream_emite_o_mesmo_rasto_de_passos_que_o_ask(duble_gateways):
    """O rasto do stream tem de ser completo — é o que a interface desenha."""

    async def collect() -> list[dict]:
        passos: list[dict] = []
        async for frame in service.stream("Quais os maiores contratos de energia?"):
            for block in frame.split("\n\n"):
                if block.startswith("event: passo"):
                    data = block.split("data: ", 1)[1]
                    passos.append(json.loads(data))
        return passos

    passos = asyncio.run(collect())
    tipos = [passo["kind"] for passo in passos]
    for esperado in ("ouvir", "modelo", "skill", "plano", "ferramenta", "resultado", "responder"):
        assert esperado in tipos, f"o stream não emitiu o passo {esperado}"
    # Duas ferramentas no plano de teste: cada uma dá um passo de execução e um
    # de resultado.
    assert tipos.count("ferramenta") == 2
    assert tipos.count("resultado") == 2


def test_stream_inclui_o_rasto_no_evento_resposta(duble_gateways):
    async def collect() -> dict:
        resposta: dict = {}
        async for frame in service.stream("Quais os maiores contratos de energia?"):
            for block in frame.split("\n\n"):
                if block.startswith("event: resposta"):
                    resposta = json.loads(block.split("data: ", 1)[1])
        return resposta

    resposta = asyncio.run(collect())
    assert resposta["answer"]
    assert resposta["steps"], "o evento `resposta` tem de trazer o rasto completo"
    assert [item["tool"] for item in resposta["tools_used"]] == ["contratos_search", "hermes.ask"]


def test_stream_sem_pergunta_emite_erro():
    async def collect() -> str:
        return "".join([frame async for frame in service.stream("")])

    assert "event: erro" in asyncio.run(collect())


# ---------------------------------------------------------------------------
# Voz
# ---------------------------------------------------------------------------
def test_stt_sem_motor_aponta_para_o_browser():
    estado = service.stt_status()
    assert set(estado) >= {"available", "engine", "browser_fallback", "note"}
    if not estado["available"]:
        assert "browser" in estado["note"].lower()


def test_transcribe_sem_audio_falha():
    # Sem motor instalado falha com RuntimeError; com motor, falha pelo áudio vazio.
    with pytest.raises(RuntimeError):
        service.transcribe(b"")


def test_tts_catalogo_de_vozes():
    estado = service.tts_status()
    assert estado["voices"], "tem de haver vozes listadas"
    ids = {voice["id"] for voice in estado["voices"]}
    assert service.DEFAULT_VOICE in ids
    for voice in estado["voices"]:
        assert voice["label"] and voice["locale"]


def test_synthesize_sem_motor_falha_mas_nao_rebenta():
    try:
        asyncio.run(service.synthesize("olá"))
    except RuntimeError as exc:
        assert "edge-tts" in str(exc) or "síntese" in str(exc).lower()
    else:  # pragma: no cover - só quando o edge-tts está instalado
        pytest.skip("edge-tts instalado no ambiente")


# ---------------------------------------------------------------------------
# Metamodelo
# ---------------------------------------------------------------------------
def test_meta_descreve_capacidades_gateways_e_voz():
    meta = service.meta()
    assert meta["about"]["name"] == "Jarvis"
    assert meta["about"]["capabilities"]
    assert {entry["id"] for entry in meta["gateways"]} == {"hermes", "mcp", "web"}
    assert meta["tools"] == gateway.catalog()
    assert "stt" in meta["voice"] and "tts" in meta["voice"]
    assert meta["limits"]["max_tools_per_plan"] == service.MAX_TOOLS_PER_PLAN


def test_meta_sem_modelo_nao_mente_sobre_o_estado():
    meta = service.meta()
    assert meta["model"]["kind"] in {"cloud", "local", "unavailable"}
    if meta["model"]["kind"] != "cloud":
        assert not meta["model"]["model"]
