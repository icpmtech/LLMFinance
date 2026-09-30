"""Testes das **ações do Jarvis** (`api/jarvis_actions.py`).

O que importa garantir:

- uma **pergunta** não dispara navegação (só um pedido para ir a algum lado);
- um pedido para **guardar** não dispara navegação (o que se quer é o artefacto);
- as criações têm o corpo pronto (título e conteúdo) e passam pelo gateway MCP;
- nada é executado sem o utilizador confirmar.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from api import jarvis_actions as actions  # noqa: E402


# ---------------------------------------------------------------------------
# Navegação
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "question, expected",
    [
        ("abre os contratos públicos", "contratos"),
        ("mostra-me a página de insolvências", "insolvencias"),
        ("leva-me ao CRM", "crm"),
        ("quero ver as cotações da EDP", "mercados"),
        ("vai para os documentos", "documentos"),
        ("abre a ontologia", "ontologia"),
    ],
)
def test_navegacao_com_verbo(question, expected):
    destinos = [item.id for item in actions.detect_destinations(question)]
    assert expected in destinos


@pytest.mark.parametrize("question", ["contratos", "insolvências", "mercados", "crm"])
def test_navegacao_com_frase_curta(question):
    # Dizer só o nome do sítio é um pedido para ir lá.
    assert actions.detect_destinations(question), f"«{question}» devia sugerir um destino"


@pytest.mark.parametrize(
    "question",
    [
        "Quais são os maiores contratos públicos de energia em 2025?",
        "Que empresas portuguesas têm mais contratos com o Estado?",
        "Como evoluiu o desemprego em Portugal na última década?",
        "Notícias sobre o BCE esta semana",
    ],
)
def test_perguntas_nao_geram_navegacao(question):
    assert actions.detect_destinations(question) == []


def test_navegacao_sem_destino_explicito_vai_para_a_pesquisa_total():
    destinos = [item.id for item in actions.detect_destinations("abre a pesquisa sobre energia")]
    assert destinos == ["pesquisa_total"]


def test_dois_destinos_na_mesma_frase():
    destinos = [item.id for item in actions.detect_destinations("insolvências e citações")]
    assert set(destinos) == {"insolvencias", "citacoes"}


def test_aceita_query_so_onde_faz_sentido():
    assert actions.DESTINATIONS_BY_ID["pesquisa_total"].accepts_query is True
    assert actions.DESTINATIONS_BY_ID["contratos"].accepts_query is False


# ---------------------------------------------------------------------------
# Criações
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "question, expected",
    [
        ("guarda isto no office", "guardar_office"),
        ("grava um relatório no office", "guardar_office"),
        ("grava um dossiê 360 sobre energia", "guardar_dossie"),
        ("guarda este método como skill", "guardar_skill"),
    ],
)
def test_criacoes_detetadas(question, expected):
    criacoes = [item.id for item in actions.detect_creations(question, "resposta")]
    assert expected in criacoes


def test_criacao_sem_resposta_nao_e_proposta():
    assert actions.detect_creations("guarda isto no office", "") == []


def test_criacao_sem_artefacto_indicado_assume_documento():
    criacoes = [item.id for item in actions.detect_creations("guarda isto", "resposta")]
    assert criacoes == ["guardar_office"]


def test_pergunta_normal_nao_gera_criacao():
    assert actions.detect_creations("Quais são os maiores contratos?", "resposta") == []


# ---------------------------------------------------------------------------
# Propostas
# ---------------------------------------------------------------------------
def test_guardar_nao_propoe_navegacao():
    propostas = actions.propose("guarda isto no office", "conteúdo da resposta")
    tipos = {item["kind"] for item in propostas}
    assert tipos == {"create"}, "um pedido para guardar não deve também navegar"


def test_pergunta_normal_nao_propoe_nada():
    assert actions.propose("Quais são os maiores contratos de energia?", "resposta") == []


def test_navegacao_nao_exige_confirmacao_mas_a_criacao_exige():
    navegar = actions.propose("abre os contratos", "")
    guardar = actions.propose("guarda isto no office", "conteúdo")
    assert navegar[0]["requires_confirmation"] is False
    assert guardar[0]["requires_confirmation"] is True


def test_propostas_do_modelo_sao_validadas():
    propostas = actions.propose(
        "resume isto",
        "conteúdo",
        extra=[
            {"action": "ontologia"},
            {"action": "acao-que-nao-existe"},
            {"action": "guardar_office"},
        ],
    )
    ids = [item["id"] for item in propostas]
    assert ids == ["ontologia", "guardar_office"]


def test_propostas_nao_se_repetem_e_respeitam_o_limite():
    propostas = actions.propose(
        "abre os contratos, as insolvências, as citações e o CRM",
        "conteúdo",
    )
    ids = [item["id"] for item in propostas]
    assert len(ids) == len(set(ids))
    assert len(ids) <= actions.MAX_ACTIONS


# ---------------------------------------------------------------------------
# Construção da ação
# ---------------------------------------------------------------------------
def test_render_de_navegacao_traz_vista_e_caminho():
    acao = actions.render("contratos", "abre os contratos")
    assert acao["kind"] == "navigate"
    assert acao["view"] == "contracts-search"
    assert acao["path"] == "/contracts/search"
    assert acao["query"] is None


def test_render_de_navegacao_com_termo():
    acao = actions.render("pesquisa_total", "abre a pesquisa total", params={"query": "energia"})
    assert acao["query"] == "energia"


def test_render_de_criacao_traz_o_corpo_pronto():
    acao = actions.render("guardar_office", "guarda no office o relatório da EDP", "A EDP lidera.")
    assert acao["kind"] == "create"
    assert acao["operation"] == "office_save_document"
    corpo = acao["params"]
    assert corpo["title"] == "o relatório da EDP"
    assert "A EDP lidera." in corpo["markdown"]
    assert corpo["tags"] == ["jarvis"]


def test_render_de_dossie_usa_o_tema_sem_o_verbo():
    acao = actions.render("guardar_dossie", "grava um dossiê 360 sobre energia", "conteúdo")
    assert acao["params"]["term"] == "energia"
    assert acao["params"]["notes"] == "conteúdo"


def test_titulo_sem_conteudo_util_leva_data():
    acao = actions.render("guardar_office", "guarda isto no office", "conteúdo")
    assert acao["params"]["title"].startswith("Jarvis — ")


# ---------------------------------------------------------------------------
# Execução
# ---------------------------------------------------------------------------
def test_run_recusa_acoes_de_navegacao():
    with pytest.raises(ValueError) as exc:
        asyncio.run(actions.run("contratos", question="abre os contratos"))
    assert "não é executável" in str(exc.value)


def test_run_recusa_acao_desconhecida():
    with pytest.raises(ValueError):
        asyncio.run(actions.run("abrir_o_portal", question="x"))


def test_run_sem_resposta_e_sem_parametros_falha():
    with pytest.raises(ValueError) as exc:
        asyncio.run(actions.run("guardar_office", question="guarda isto"))
    assert "nada para criar" in str(exc.value).lower()


def test_run_executa_a_operacao_no_gateway(monkeypatch):
    from api import jarvis_gateway

    chamadas: list[tuple[str, dict]] = []

    async def fake_invoke(tool_id, args=None, *, ctx=None):
        chamadas.append((tool_id, dict(args or {})))
        return {"tool": tool_id, "gateway": "mcp", "label": "Guardar", "ok": True, "data": {"id": "doc-1"}}

    monkeypatch.setattr(jarvis_gateway, "invoke", fake_invoke)

    out = asyncio.run(actions.run("guardar_office", question="guarda no office o relatório", answer="Conteúdo."))
    assert out["ok"] is True
    assert out["operation"] == "office_save_document"
    assert out["result"] == {"id": "doc-1"}
    tool_id, envelope = chamadas[0]
    # Via `mcp.call`: as operações que escrevem não estão no catálogo curado de
    # ferramentas, para o modelo nunca as poder escolher sozinho.
    assert tool_id == "mcp.call"
    assert envelope["operation"] == "office_save_document"
    # O corpo vai no parâmetro do catálogo (`payload`); solto iria para o query
    # string e o endpoint responderia 422.
    assert "Conteúdo." in envelope["params"]["payload"]["markdown"]


def test_run_respeita_os_parametros_do_utilizador(monkeypatch):
    from api import jarvis_gateway

    capturado: dict = {}

    async def fake_invoke(tool_id, args=None, *, ctx=None):
        capturado.update(((args or {}).get("params") or {}).get("payload") or {})
        return {"tool": tool_id, "gateway": "mcp", "ok": True, "data": {}}

    monkeypatch.setattr(jarvis_gateway, "invoke", fake_invoke)
    asyncio.run(
        actions.run(
            "guardar_office",
            question="guarda isto",
            answer="Conteúdo.",
            params={"title": "Título escolhido", "folder_id": "pasta-7"},
        )
    )
    # O modelo pode escolher o título e a pasta: campos que o construtor do
    # corpo não produz (a pasta) têm de passar na mesma.
    assert capturado["title"] == "Título escolhido"
    assert capturado["folder_id"] == "pasta-7"


def test_o_corpo_vai_no_parametro_do_catalogo(monkeypatch):
    from api import jarvis_gateway

    visto: dict = {}

    async def fake_invoke(tool_id, args=None, *, ctx=None):
        visto.update(args or {})
        return {"tool": tool_id, "gateway": "mcp", "ok": True, "data": {}}

    monkeypatch.setattr(jarvis_gateway, "invoke", fake_invoke)
    for criacao in actions.CREATIONS:
        visto.clear()
        asyncio.run(
            actions.run(criacao.id, question="guarda isto", answer="Conteúdo.")
        )
        params = visto["params"]
        assert set(params) == {"payload"}, (criacao.id, sorted(params))
        assert isinstance(params["payload"], dict) and params["payload"], criacao.id


def test_run_ignora_campos_que_nao_sao_do_corpo(monkeypatch):
    from api import jarvis_gateway

    capturado: dict = {}

    async def fake_invoke(tool_id, args=None, *, ctx=None):
        capturado.update(((args or {}).get("params") or {}).get("payload") or {})
        return {"tool": tool_id, "gateway": "mcp", "ok": True, "data": {}}

    monkeypatch.setattr(jarvis_gateway, "invoke", fake_invoke)
    asyncio.run(
        actions.run(
            "guardar_office",
            question="guarda isto",
            answer="Conteúdo.",
            params={"title": "Aceito", "token_de_outro_utilizador": "x", "malicioso": 1},
        )
    )
    assert capturado["title"] == "Aceito"
    assert "token_de_outro_utilizador" not in capturado
    assert "malicioso" not in capturado


def test_escritas_nao_estao_no_catalogo_de_ferramentas_do_modelo():
    """Invariante de segurança: o modelo só propõe, nunca escolhe uma escrita.

    As operações usadas pelas criações têm de ficar de fora de `TOOLS`; se
    entrassem, o planeador poderia executá-las sem confirmação.
    """
    from api import jarvis_gateway

    pedidas = {creation.operation for creation in actions.CREATIONS}
    assert pedidas, "o catálogo de criações não pode estar vazio"
    assert not (pedidas & set(jarvis_gateway.TOOLS)), sorted(pedidas & set(jarvis_gateway.TOOLS))


def test_run_devolve_o_erro_do_gateway(monkeypatch):
    from api import jarvis_gateway

    async def fake_invoke(tool_id, args=None, *, ctx=None):
        return {"tool": tool_id, "gateway": "mcp", "ok": False, "error": "HTTP 500"}

    monkeypatch.setattr(jarvis_gateway, "invoke", fake_invoke)
    out = asyncio.run(actions.run("guardar_office", question="guarda isto", answer="Conteúdo."))
    assert out["ok"] is False
    assert out["error"] == "HTTP 500"


# ---------------------------------------------------------------------------
# Catálogo
# ---------------------------------------------------------------------------
def test_catalogo_tem_destinos_e_criacoes():
    catalogo = actions.catalogue()
    assert len(catalogo["destinations"]) > 20
    assert {item["id"] for item in catalogo["creations"]} == {"guardar_office", "guardar_dossie", "guardar_skill"}
    for item in catalogo["creations"]:
        assert item["requires_confirmation"] is True
        assert item["operation"].startswith(("office_", "search360_", "skills_"))


def test_destinos_apontam_para_vistas_reais():
    # As vistas têm de existir no encaminhamento da SPA (`App.tsx`/`AppNav.tsx`).
    conhecidas = {
        "contracts-search", "contracts-dashboard", "contracts-map", "entities-search", "empresas-iq",
        "pessoas-iq", "companies-global", "risco", "cire", "citacoes", "contribuintes", "gleif",
        "tickers", "forecast", "rag", "search360", "hermes", "researcher", "ontology", "visualizador",
        "sentimento", "office", "email", "rss", "crm-accounts", "scraper", "social", "shop", "browser",
        "world", "simulador", "padroes", "elastic", "pesquisa", "search", "settings", "admin",
    }
    usadas = {item.view for item in actions.DESTINATIONS}
    assert usadas <= conhecidas, f"vistas desconhecidas: {sorted(usadas - conhecidas)}"
    for item in actions.DESTINATIONS:
        assert item.path.startswith("/")
        assert item.keywords, f"{item.id} sem palavras-chave"


def test_planner_catalogue_lista_o_que_existe():
    itens = actions.planner_catalogue()
    ids = {item["action"] for item in itens}
    assert "contratos" in ids
    assert "guardar_office" in ids
    for item in itens:
        assert item["kind"] in {"navigate", "create"}
