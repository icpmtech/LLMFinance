"""Testes do módulo MiroFish (`api/mirofish_service.py`).

Cobrem o que é determinístico — a composição das sementes a partir dos dados do
sistema, o tratamento do envelope de resposta do MiroFish e o registo dos
trabalhos — sem tocar em rede nem no Elasticsearch (esse acesso é substituído).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from api import mirofish_service as miro  # noqa: E402
from api import padroes_service  # noqa: E402


# ---------------------------------------------------------------------------
# Envelope de resposta do MiroFish
# ---------------------------------------------------------------------------
class _FakeResponse:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def test_payload_devolve_data():
    assert miro._payload(_FakeResponse(200, {"success": True, "data": {"project_id": "p1"}}), "teste") == {"project_id": "p1"}


def test_payload_falha_por_success_false():
    with pytest.raises(miro.MiroFishError) as exc:
        miro._payload(_FakeResponse(200, {"success": False, "error": "sem chave de LLM"}), "ontologia")
    assert "sem chave de LLM" in str(exc.value)


def test_payload_falha_por_http_error():
    with pytest.raises(miro.MiroFishError) as exc:
        miro._payload(_FakeResponse(502, {"detail": "bad gateway"}), "grafo")
    assert "502" in str(exc.value)


def test_payload_aceita_corpo_sem_envelope():
    assert miro._payload(_FakeResponse(200, [1, 2]), "lista") == {"value": [1, 2]}


# ---------------------------------------------------------------------------
# Semente: ficha de empresa
# ---------------------------------------------------------------------------
DOSSIE = {
    "nif": "512345678",
    "nome": "Empresa Exemplo, S.A.",
    "pais": "PT",
    "contratos_total": 3,
    "contratos": [
        {
            "ano": 2025,
            "objeto": "Aquisição de serviços de manutenção",
            "valor": 120000.0,
            "procedimento": "Ajuste Direto Regime Geral",
            "n_concorrentes": 1,
            "adjudicante": "Município de Exemplo",
        },
        {
            "ano": 2024,
            "objeto": "Empreitada de reabilitação",
            "valor": 900000.0,
            "procedimento": "Concurso Público",
            "n_concorrentes": 4,
            "adjudicante": "Câmara Municipal de Exemplo",
        },
    ],
    "resumo": {
        "valor_total": 1020000.0,
        "valor_mediano": 510000.0,
        "desvio_mediano": 1.12,
        "taxa_ajuste_direto": 0.5,
        "adjudicantes_distintos": 2,
        "taxa_aditivo": 0.0,
        "anos": [2024, 2025],
    },
    "sinais": [{"padrao": "concentracao_fornecedor", "detalhe": "82% do valor vem de um adjudicante"}],
    "cargos_sociais": [
        {
            "nome": "Maria Silva",
            "cargos": [{"role": "Gerente", "role_org": "Empresa Exemplo, S.A.", "data": "2021-03-02"}],
        }
    ],
    "insolvencias": [
        {"data": "2023-05-10", "especie": "Insolvência", "ato": "Sentença de declaração", "tribunal": "Tribunal de Exemplo", "processo": "123/23.0T8EXP"}
    ],
    "insolvencias_total": 1,
    "pessoas_total": 3,
}


def test_markdown_empresa_tem_contratos_sinais_e_insolvencias():
    markdown = miro._markdown_empresa(DOSSIE)
    assert "Empresa Exemplo, S.A." in markdown
    assert "512345678" in markdown
    assert "Aquisição de serviços de manutenção" in markdown
    assert "concentracao_fornecedor" in markdown
    assert "Maria Silva" in markdown
    assert "Gerente (Empresa Exemplo, S.A.) desde 2021-03-02" in markdown
    assert "Tribunal de Exemplo" in markdown
    # valores em euros, no formato português
    assert "1 020 000,00 €" in markdown
    assert "50,0 %" in markdown


def test_markdown_empresa_ordena_contratos_por_valor():
    markdown = miro._markdown_empresa(DOSSIE)
    maior = markdown.index("Empreitada de reabilitação")
    menor = markdown.index("Aquisição de serviços de manutenção")
    assert maior < menor


def test_markdown_empresa_sem_dossie_levanta():
    with pytest.raises(miro.MiroFishError):
        miro._markdown_empresa({"error": "Elasticsearch indisponível"})


# ---------------------------------------------------------------------------
# Semente: panorama do sistema
# ---------------------------------------------------------------------------
def test_markdown_sistema_com_panorama():
    markdown = miro._markdown_sistema(
        {
            "volumes": {"Contratos (Portal BASE)": 2250969, "Insolvências (CIRE)": 163941},
            "contratos_ano": [{"key_as_string": "2025", "doc_count": 246992, "valor": {"value": 23670498334.05}}],
            "maiores_contratos": [
                {
                    "ano": 2025,
                    "objeto": "Concessão da Linha Ferroviária",
                    "valor": 1661362811.55,
                    "data": "2025-09-17",
                    "adjudicante": "Infraestruturas de Portugal",
                }
            ],
            "insolvencias": [{"data": "2026-01-05", "insolvente": "Empresa Z", "especie": "Insolvência", "tribunal": "Tribunal Y"}],
            "citacoes_comarca": [{"key": "Lisboa", "doc_count": 4210}],
            "destaques": ["Lisboa: 4210 publicações"],
        }
    )
    assert "Contratos (Portal BASE)" in markdown
    assert "2 250 969" in markdown
    assert "Infraestruturas de Portugal" in markdown
    assert "Empresa Z" in markdown
    assert "Lisboa" in markdown


def test_markdown_sistema_sem_dados_nao_rebenta():
    markdown = miro._markdown_sistema({})
    assert "Panorama do sistema IQ OS" in markdown
    assert "_(sem registos)_" in markdown


# ---------------------------------------------------------------------------
# build_seed
# ---------------------------------------------------------------------------
def test_build_seed_fonte_desconhecida():
    with pytest.raises(miro.MiroFishError) as exc:
        miro.build_seed("inexistente", {})
    assert "fonte desconhecida" in str(exc.value)


def test_build_seed_empresa_sem_nif():
    with pytest.raises(miro.MiroFishError) as exc:
        miro.build_seed("empresa", {})
    assert "NIF" in str(exc.value)


def test_build_seed_empresa_composta(monkeypatch):
    monkeypatch.setattr(padroes_service, "entity_dossier", lambda nif, pais="PT", es=None: DOSSIE)
    seed = miro.build_seed("empresa", {"nif": "512345678", "pais": "PT"})
    assert seed["source"] == "empresa"
    assert seed["filename"] == "empresa-exemplo-s-a.md"
    assert seed["chars"] == len(seed["markdown"])
    assert seed["words"] > 100
    assert seed["stats"]["nif"] == "512345678"
    assert seed["stats"]["contratos"] == 2
    # o pedido sugerido vem da fonte, para o formulário nunca ir vazio
    assert seed["suggested_requirement"]


def test_build_seed_sistema_sem_elasticsearch(monkeypatch):
    monkeypatch.setattr(miro, "_es", lambda: None)
    seed = miro.build_seed("sistema", {"size": 5})
    assert seed["title"] == "Panorama do sistema IQ OS"
    assert seed["stats"]["volumes"]["Contratos (Portal BASE)"] is None


def test_build_seed_noticias_sem_artigos(monkeypatch):
    from api import rss_store

    monkeypatch.setattr(rss_store, "all_articles", lambda: [])
    with pytest.raises(miro.MiroFishError) as exc:
        miro.build_seed("noticias", {})
    assert "RSS" in str(exc.value)


# ---------------------------------------------------------------------------
# Trabalhos
# ---------------------------------------------------------------------------
def test_job_regista_progresso_e_log():
    job = miro._job_new("simulation", {"source": "sistema"}, title="Panorama")
    miro._job_log(job["id"], "a compor a semente", step="seed", progress=10)
    miro._job_log(job["id"], "ontologia gerada", progress=30)
    miro._job_update(job["id"], status="done", progress=100)

    saved = miro.get_job(job["id"])
    assert saved is not None
    assert saved["status"] == "done"
    assert saved["progress"] == 100
    assert saved["step"] == "seed"
    assert [entry["message"] for entry in saved["log"]] == ["a compor a semente", "ontologia gerada"]
    assert saved["log"][0]["at"]


def test_list_jobs_ordena_e_limita():
    # Os trabalhos vivem em memória e outras threads (o arranque de uma
    # simulação) podem criar trabalhos a qualquer momento, por isso a asserção
    # compara os novos com os que já existiam — nunca assume que a lista está
    # vazia nem que os novos são os primeiros de todos.
    antigos = [job["id"] for job in miro.list_jobs(limit=1000)]
    ids = [miro._job_new("simulation", {}, title=f"t{i}")["id"] for i in range(3)]

    jobs = miro.list_jobs(limit=2)
    assert len(jobs) == 2

    ordenados = [job["id"] for job in miro.list_jobs(limit=1000)]
    posicao = {job_id: index for index, job_id in enumerate(ordenados)}
    for job_id in ids:
        assert job_id in posicao, "um trabalho criado agora desapareceu da lista"
        for antigo in antigos:
            assert posicao[job_id] < posicao[antigo], "os trabalhos recentes têm de vir à frente dos antigos"

    # A ordem é a de criação (mais recente primeiro), mesmo quando o relógio do
    # sistema não distingue dois trabalhos criados no mesmo instante.
    assert posicao[ids[0]] > posicao[ids[1]] > posicao[ids[2]]

    # `limit` corta a lista sem alterar a ordem.
    assert [job["id"] for job in jobs] == ordenados[:2]


def test_job_desconhecido_devolve_none():
    assert miro.get_job("nao-existe") is None


# ---------------------------------------------------------------------------
# Diagnóstico de chaves em falta
# ---------------------------------------------------------------------------
def test_explain_error_mapeia_401_do_llm():
    explicado = miro.explain_error("geração da ontologia: HTTP 502 — LLM provider request failed (HTTP 401)")
    assert explicado["key"] == "MIROFISH_LLM_API_KEY"
    assert "MIROFISH_LLM_API_KEY" in explicado["hint"]
    assert "finance-llm/.env" in explicado["hint"]
    assert "chave em falta" in explicado["message"]


def test_explain_error_mapeia_zep():
    explicado = miro.explain_error("Zep 401 Unauthorized: invalid api key")
    assert explicado["key"] == "MIROFISH_ZEP_API_KEY"
    assert "ZEP_API_KEY" in explicado["hint"]


def test_explain_error_sem_mapeamento_devolve_original():
    explicado = miro.explain_error("tempo limite excedido")
    assert explicado["message"] == "tempo limite excedido"
    assert explicado["key"] is None
    assert explicado["hint"] is None


def test_diagnose_lista_chaves_comandos_e_ultimo_erro(monkeypatch):
    monkeypatch.setenv("MIROFISH_URL", "http://mirofish:5001")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(miro, "health", lambda: {"available": False, "base_url": "http://mirofish:5001", "detail": "ConnectError"})
    job = miro._job_new("simulation", {}, title="Panorama")
    miro._job_update(job["id"], status="failed", error="O LLM do MiroFish recusou o pedido (HTTP 401)", hint="Defina MIROFISH_LLM_API_KEY.")

    info = miro.diagnose()
    assert info["service"]["available"] is False
    assert [key["name"] for key in info["keys"]] == ["MIROFISH_LLM_API_KEY", "MIROFISH_ZEP_API_KEY"]
    assert info["host_env"]["OPENAI_API_KEY"] is False
    assert "docker compose --profile mirofish up -d" in info["commands"]["start"]
    assert info["commands"]["logs"].endswith("logs mirofish")
    assert info["last_error"]["error"].startswith("O LLM do MiroFish")


def test_diagnose_ve_a_alternativa_openai(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://exemplo/v1")
    monkeypatch.setattr(miro, "health", lambda: {"available": True, "base_url": "http://127.0.0.1:5001"})
    info = miro.diagnose()
    assert info["host_env"]["OPENAI_API_KEY"] is True
    assert info["host_env"]["OPENAI_BASE_URL"] == "https://exemplo/v1"


# ---------------------------------------------------------------------------
# Catálogo de fontes
# ---------------------------------------------------------------------------
def test_catalogo_de_fontes_bem_formado():
    assert [source["id"] for source in miro.SOURCES] == ["empresa", "tema", "noticias", "documento", "sistema"]
    for source in miro.SOURCES:
        assert source["label"] and source["hint"] and source["requirement"]
        assert isinstance(source["params"], list)
        for param in source["params"]:
            assert param["name"] and param["label"] and param["type"]


def test_base_url_por_omissao(monkeypatch):
    monkeypatch.delenv("MIROFISH_URL", raising=False)
    assert miro.base_url() == "http://127.0.0.1:5001"
    monkeypatch.setenv("MIROFISH_URL", "http://mirofish:5001/")
    assert miro.base_url() == "http://mirofish:5001"


# ---------------------------------------------------------------------------
# Simulador IQ OS: leitura e apresentação dos resultados
# ---------------------------------------------------------------------------
class _FakeClient:
    """Cliente httpx mínimo: responde por caminho e guarda os pedidos feitos."""

    def __init__(self, routes: dict):
        self.routes = routes
        self.calls: list = []

    def _resolve(self, path: str, params=None, body=None):
        self.calls.append({"path": path, "params": params, "body": body})
        for prefix in sorted(self.routes, key=len, reverse=True):
            if path == prefix or path.startswith(prefix + "/") or path.startswith(prefix + "?"):
                payload = self.routes[prefix]
                if isinstance(payload, Exception):
                    raise payload
                return payload
        return _FakeResponse(404, {"success": False, "error": "não encontrado"})

    def get(self, path, params=None):
        return self._resolve(path, params=params)

    def post(self, path, json=None):
        return self._resolve(path, body=json)


def _ok(data):
    return _FakeResponse(200, {"success": True, "data": data})


SIM = "sim_teste1"


def _overview_client() -> _FakeClient:
    return _FakeClient(
        {
            f"/api/simulation/{SIM}": _ok(
                {
                    "simulation_id": SIM,
                    "project_id": "proj_1",
                    "graph_id": "graph_1",
                    "status": "running",
                    "profiles_count": 2,
                    "entities_count": 3,
                    "entity_types": ["Court", "Person"],
                    "config_reasoning": "Previsão sobre insolvências.",
                }
            ),
            f"/api/simulation/{SIM}/run-status": _ok(
                {
                    "runner_status": "running",
                    "current_round": 4,
                    "total_rounds": 10,
                    "progress_percent": 40.0,
                    "total_actions_count": 3,
                    "twitter_actions_count": 2,
                    "reddit_actions_count": 1,
                    "total_simulation_hours": 72,
                    "twitter_running": True,
                    "reddit_completed": False,
                    "started_at": "2026-09-29T10:00:00",
                }
            ),
            f"/api/simulation/{SIM}/timeline": _ok(
                {
                    "rounds_count": 1,
                    "timeline": [
                        {"round_num": 0, "total_actions": 3, "twitter_actions": 2, "reddit_actions": 1, "active_agents_count": 2, "action_types": {"CREATE_POST": 3}}
                    ],
                }
            ),
            f"/api/simulation/{SIM}/agent-stats": _ok(
                {
                    "agents_count": 1,
                    "stats": [
                        {"agent_id": 7, "agent_name": "Tribunal de Aveiro", "total_actions": 3, "twitter_actions": 2, "reddit_actions": 1, "action_types": {"CREATE_POST": 3}}
                    ],
                }
            ),
            f"/api/simulation/{SIM}/actions": _ok(
                {
                    "count": 2,
                    "actions": [
                        {
                            "agent_id": 7,
                            "agent_name": "Tribunal de Aveiro",
                            "action_type": "CREATE_POST",
                            "platform": "twitter",
                            "round_num": 0,
                            "timestamp": "2026-09-29T10:01:00",
                            "success": True,
                            "action_args": {"content": "Primeira publicação"},
                        },
                        {
                            "agent_id": 3,
                            "agent_name": "Diviminho Lda.",
                            "action_type": "CREATE_COMMENT",
                            "platform": "reddit",
                            "round_num": 0,
                            "timestamp": "2026-09-29T10:02:00",
                            "success": True,
                            "action_args": {"content": "Comentário mais recente"},
                        },
                    ],
                }
            ),
            f"/api/simulation/{SIM}/config": _ok(
                {
                    "agent_configs": [
                        {"agent_id": 7, "entity_name": "Tribunal de Aveiro", "entity_type": "Court", "influence_weight": 2.8, "activity_level": 0.5, "active_hours": [9, 10], "stance": "neutral", "sentiment_bias": 0.0},
                        {"agent_id": 3, "entity_name": "Diviminho Lda.", "entity_type": "InsolventEntity", "influence_weight": 1.0, "activity_level": 0.7},
                    ],
                    "generation_reasoning": "Configuração temporal europeia.",
                }
            ),
            f"/api/simulation/{SIM}/profiles": _ok(
                {
                    "count": 2,
                    "profiles": [
                        {"name": "Tribunal de Aveiro", "age": 30, "mbti": "ISTJ", "bio": "Tribunal da comarca de Aveiro."},
                        {"name": "Diviminho Lda.", "age": 44, "mbti": "ENTJ", "bio": "Empresa insolvente do setor têxtil."},
                    ],
                }
            ),
            f"/api/report/check/{SIM}": _ok({"has_report": False, "interview_unlocked": False, "report_id": None, "report_status": None}),
            "/api/graph/project/proj_1": _ok(
                {
                    "project_id": "proj_1",
                    "name": "Panorama do sistema IQ OS",
                    "analysis_summary": "Panorama de contratação pública.",
                    "ontology": {
                        "entity_types": [{"name": "Court"}, {"name": "Person"}],
                        "edge_types": [{"name": "REPORTS_ON"}],
                    },
                }
            ),
        }
    )


def test_run_state_label_traduz_estados():
    assert miro.run_state_label("running")["label"] == "em curso"
    assert miro.run_state_label("running")["tone"] == "busy"
    assert miro.run_state_label("completed")["label"] == "concluída"
    assert miro.run_state_label("stopped")["tone"] == "warn"
    assert miro.run_state_label(None)["key"] == "idle"
    assert miro.run_state_label("novo_estado")["label"] == "novo estado"


def test_action_label_traduz_tipos():
    assert miro.action_label("CREATE_POST") == "publicou"
    assert miro.action_label("create_comment") == "comentou"
    assert miro.action_label("OUTRA_COISA") == "outra coisa"


def test_acao_normalizada_tem_verbo_plataforma_e_conteudo():
    action = miro._action_item(
        {
            "agent_id": 7,
            "agent_name": "Tribunal de Aveiro",
            "action_type": "CREATE_POST",
            "platform": "twitter",
            "round_num": 2,
            "timestamp": "2026-09-29T10:01:00",
            "success": True,
            "action_args": {"content": "Texto publicado"},
        },
        index=0,
    )
    assert action["action"] == "publicou"
    assert action["content"] == "Texto publicado"
    assert action["platform"] == "twitter"
    assert action["round"] == 2
    assert action["agent_name"] == "Tribunal de Aveiro"


def test_merge_cast_junta_configuracao_persona_e_acoes():
    cast = miro._merge_cast(
        [{"agent_id": 7, "entity_name": "Tribunal de Aveiro", "entity_type": "Court", "influence_weight": 2.8}],
        [{"name": "Tribunal de Aveiro", "age": 30, "bio": "Tribunal da comarca de Aveiro."}],
        [{"agent_id": 7, "total_actions": 5, "twitter_actions": 3, "reddit_actions": 2}],
    )
    assert len(cast) == 1
    agente = cast[0]
    assert agente["entity_type"] == "Court"
    assert agente["influence"] == 2.8
    assert agente["age"] == 30
    assert agente["bio"] == "Tribunal da comarca de Aveiro."
    assert agente["actions_total"] == 5


def test_merge_cast_sem_configuracao_devolve_vazio():
    assert miro._merge_cast([], [{"name": "x"}], []) == []


def test_state_counts_conta_por_tipo():
    counts = miro._state_counts([{"entity_type": "Court"}, {"entity_type": "Court"}, {"entity_type": "Person"}])
    assert counts[0] == {"type": "Court", "count": 2}
    assert {"type": "Person", "count": 1} in counts


def test_run_overview_agrega_execucao_elenco_e_grafo():
    overview = miro.run_overview(SIM, client=_overview_client(), actions=5)
    assert overview["state"]["label"] == "em curso"
    assert overview["active"] is True
    assert overview["metrics"]["rounds_total"] == 10
    assert overview["metrics"]["agents_total"] == 2
    assert overview["platforms"]["twitter"]["running"] is True
    assert overview["rounds"][0]["total"] == 3
    assert [action["agent_name"] for action in overview["actions"]] == ["Diviminho Lda.", "Tribunal de Aveiro"]
    assert overview["state_counts"] == [{"type": "Court", "count": 1}, {"type": "InsolventEntity", "count": 1}]
    assert overview["simulation"]["title"] == "Panorama do sistema IQ OS"
    assert overview["simulation"]["ontology"]["edge_types"] == ["REPORTS_ON"]
    assert overview["report"]["has_report"] is False
    assert overview["report_hint"] is not None


def test_run_overview_tolera_leituras_em_falta():
    client = _FakeClient({f"/api/simulation/{SIM}": _ok({"simulation_id": SIM, "status": "completed", "project_id": ""})})
    overview = miro.run_overview(SIM, client=client)
    assert overview["state"]["key"] == "completed"
    assert overview["rounds"] == []
    assert overview["cast"] == []
    assert overview["report_hint"] is None


def test_run_feed_ordena_por_data_descendente():
    feed = miro.run_feed(SIM, client=_overview_client(), limit=10)
    assert feed["actions"][0]["content"] == "Comentário mais recente"
    assert feed["count"] == 2


def test_run_cast_devolve_elenco_ordenado_por_acoes():
    cast = miro.run_cast(SIM, client=_overview_client())
    assert cast["count"] == 2
    assert cast["agents"][0]["name"] == "Tribunal de Aveiro"
    assert cast["by_type"][0]["type"] == "Court"


def test_runs_usa_estado_ao_vivo_da_simulacao():
    client = _FakeClient(
        {
            "/api/simulation/list": _ok(
                [
                    {"simulation_id": SIM, "project_id": "proj_1", "status": "created", "created_at": "2026-09-29T09:00:00", "profiles_count": 2},
                ]
            ),
            f"/api/simulation/{SIM}/run-status": _ok({"runner_status": "running", "current_round": 3, "total_rounds": 10, "progress_percent": 30.0, "total_actions_count": 4}),
            f"/api/report/check/{SIM}": _ok({"has_report": True, "report_id": "rep_1", "report_status": "completed"}),
        }
    )
    catalog = miro.runs(client=client, limit=5, enrich=2)
    assert catalog["count"] == 1
    run = catalog["runs"][0]
    assert run["state"]["key"] == "running"
    assert run["live"]["round_current"] == 3
    assert run["report"]["has_report"] is True
    assert run["report"]["status"]["label"] == "concluída"


def test_runs_sem_enriquecimento_nao_pede_estado():
    client = _FakeClient({"/api/simulation/list": _ok([{"simulation_id": SIM, "status": "created"}])})
    catalog = miro.runs(client=client, enrich=0)
    assert catalog["runs"][0]["live"] is None
    assert all(not call["path"].endswith("run-status") for call in client.calls)


def test_report_summary_conta_palavras_e_seccoes():
    summary = miro._report_summary(
        {
            "report_id": "rep_1",
            "simulation_id": SIM,
            "status": "completed",
            "markdown_content": "# Relatório\n\nDuas palavras.",
            "outline": {"title": "Risco empresarial", "summary": "Resumo", "sections": [{"title": "Sumário", "content": "texto"}]},
        }
    )
    assert summary["title"] == "Risco empresarial"
    assert summary["words"] == 4
    assert summary["sections"][0]["title"] == "Sumário"
    assert summary["status"]["label"] == "concluída"


def test_report_summary_sem_relatorio_devolve_none():
    assert miro._report_summary(None) is None
    assert miro._report_summary({}) is None


def test_run_report_traduz_recusa_de_simulacao_a_correr():
    client = _FakeClient(
        {
            f"/api/report/check/{SIM}": _ok({"has_report": False, "report_id": None}),
            "/api/report/generate": _FakeResponse(409, {"success": False, "error": "Simulation is still active; wait for a terminal run status"}),
        }
    )
    with pytest.raises(miro.MiroFishError) as exc:
        miro.run_report(SIM, generate=True, client=client)
    assert "ainda está a correr" in str(exc.value)


def test_run_report_devolve_relatorio_existente():
    client = _FakeClient(
        {
            f"/api/report/check/{SIM}": _ok({"has_report": True, "report_id": "rep_9", "report_status": "completed"}),
            "/api/report/rep_9": _ok({"report_id": "rep_9", "simulation_id": SIM, "status": "completed", "markdown_content": "# Título", "outline": {"title": "T", "sections": []}}),
        }
    )
    view = miro.run_report(SIM, client=client)
    assert view["has_report"] is True
    assert view["report_id"] == "rep_9"
    assert view["report"]["markdown"] == "# Título"


def test_report_by_simulation_404_devolve_none():
    client = _FakeClient({f"/api/report/by-simulation/{SIM}": _FakeResponse(404, {"success": False, "error": "sem relatório"})})
    assert miro.report_by_simulation(client, SIM) is None


def test_ask_agents_exige_pergunta():
    with pytest.raises(miro.MiroFishError):
        miro.ask_agents(SIM, "  ", client=_overview_client())


def test_ask_agents_entrevista_um_agente():
    client = _FakeClient({"/api/simulation/interview": _ok({"agent_id": 7, "result": {"response": "Acho que o risco aumenta."}})})
    result = miro.ask_agents(SIM, "O que esperas?", agent_id=7, client=client)
    assert result["mode"] == "agente"
    assert client.calls[0]["body"]["agent_id"] == 7


def test_ask_agents_entrevista_todos_sem_agent_id():
    client = _FakeClient({"/api/simulation/interview/all": _ok({"interviews_count": 2})})
    result = miro.ask_agents(SIM, "O que esperas?", client=client)
    assert result["mode"] == "todos"
    assert client.calls[0]["path"] == "/api/simulation/interview/all"


def test_ask_report_devolve_resposta_e_fontes():
    client = _FakeClient({"/api/report/chat": _ok({"response": "Os têxteis.", "tool_calls": [], "sources": ["insolvências"]})})
    answer = miro.ask_report(SIM, "Que setores?", client=client)
    assert answer["answer"] == "Os têxteis."
    assert answer["sources"] == ["insolvências"]


def test_stop_run_devolve_estado():
    client = _FakeClient({"/api/simulation/stop": _ok({"simulation_id": SIM, "runner_status": "stopped"})})
    result = miro.stop_run(SIM, client=client)
    assert result["state"]["label"] == "interrompida"


def test_job_for_simulation_encontra_o_trabalho():
    job = miro.start_simulation_job({"source": "sistema", "title": "Panorama"}, session=None)
    miro._job_update(job["id"], result={"simulation_id": "sim_encontrada", "seed": {"title": "Panorama"}})
    try:
        found = miro.job_for_simulation("sim_encontrada")
        assert found is not None
        assert found["id"] == job["id"]
        assert found["title"] == "Panorama"
        assert found["seed"] == {"title": "Panorama"}
        assert miro.job_for_simulation("sim_outra") is None
    finally:
        with miro._JOBS_LOCK:
            miro._JOBS.pop(job["id"], None)


# ---------------------------------------------------------------------------
# Grafo de conhecimento (Zep)
# ---------------------------------------------------------------------------
def _graph_client(*, nodes: list | None = None, edges: list | None = None, graph_id: str = "graph_1") -> _FakeClient:
    return _FakeClient(
        {
            f"/api/simulation/{SIM}": _ok({"simulation_id": SIM, "project_id": "proj_1", "graph_id": graph_id}),
            f"/api/graph/data/{graph_id}": _ok(
                {
                    "graph_id": graph_id,
                    "node_count": len(nodes or []),
                    "edge_count": len(edges or []),
                    "nodes": nodes or [],
                    "edges": edges or [],
                }
            ),
        }
    )


def test_run_graph_normaliza_nos_tipos_e_factos():
    client = _graph_client(
        nodes=[
            {"uuid": "n1", "name": "Câmara de Exemplo", "labels": ["PublicContractingEntity"], "summary": "Adjudica obras.", "created_at": "2026-09-29T10:00:00Z"},
            {"uuid": "n2", "name": "Empresa X", "labels": ["PrivateCompany"], "summary": "Concorre."},
            {"uuid": "n3", "name": "2015 data", "labels": [], "summary": "Sem etiqueta."},
        ],
        edges=[
            {
                "uuid": "e1",
                "source_node_uuid": "n1",
                "target_node_uuid": "n2",
                "source_node_name": "Câmara de Exemplo",
                "target_node_name": "Empresa X",
                "fact": "A Câmara adjudicou 3 contratos à Empresa X.",
                "fact_type": "AWARDS_CONTRACT_TO",
                "valid_at": "2026-09-29T10:00:00Z",
                "episodes": ["ep1"],
            },
            {"uuid": "e2", "source_node_uuid": "n1", "target_node_uuid": "n3", "fact": "antigo", "fact_type": "OLD", "expired_at": "2026-01-01"},
        ],
    )
    graph = miro.run_graph(SIM, client=client)
    assert graph["graph_id"] == "graph_1"
    assert graph["node_count"] == 3
    # O facto expirado não conta para o grafo.
    assert graph["edge_count"] == 1
    assert [row["type"] for row in graph["types"]] == ["PublicContractingEntity", "PrivateCompany", "Sem tipo"]
    tipos = {row["type"]: row["count"] for row in graph["types"]}
    assert tipos["Sem tipo"] == 1
    assert [row["type"] for row in graph["relations"]] == ["AWARDS_CONTRACT_TO"]
    camara = next(node for node in graph["nodes"] if node["id"] == "n1")
    assert camara["type"] == "PublicContractingEntity"
    assert camara["degree"] == 1
    assert graph["edges"][0]["fact"] == "A Câmara adjudicou 3 contratos à Empresa X."
    assert graph["omitted"] == {"nodes": 0, "edges": 0, "reason": graph["omitted"]["reason"]}


def test_run_graph_limita_aos_nos_mais_ligados():
    nodes = [{"uuid": f"n{index}", "name": f"Nó {index}", "labels": ["Person"]} for index in range(6)]
    edges = [
        {"uuid": f"e{index}", "source_node_uuid": "n0", "target_node_uuid": f"n{index}", "fact": "f", "fact_type": "RELATES_TO"}
        for index in range(1, 6)
    ]
    graph = miro.run_graph(SIM, client=_graph_client(nodes=nodes, edges=edges), max_nodes=2, max_edges=10)
    assert len(graph["nodes"]) == 2
    assert graph["nodes"][0]["id"] == "n0"  # o mais ligado
    assert graph["omitted"]["nodes"] == 4
    assert all(edge["source"] in {"n0"} for edge in graph["edges"])


def test_run_graph_sem_grafo_levantar_erro():
    client = _FakeClient(
        {
            f"/api/simulation/{SIM}": _ok({"simulation_id": SIM, "project_id": "proj_1"}),
            "/api/graph/project/proj_1": _ok({"project_id": "proj_1"}),
        }
    )
    with pytest.raises(miro.MiroFishError) as exc:
        miro.run_graph(SIM, client=client)
    assert "grafo" in str(exc.value)


def test_run_graph_usa_o_grafo_do_projeto_quando_a_simulacao_nao_o_tem():
    client = _FakeClient(
        {
            f"/api/simulation/{SIM}": _ok({"simulation_id": SIM, "project_id": "proj_1"}),
            "/api/graph/project/proj_1": _ok({"project_id": "proj_1", "graph_id": "graph_2"}),
            "/api/graph/data/graph_2": _ok({"nodes": [{"uuid": "n1", "name": "A", "labels": ["Person"]}], "edges": []}),
        }
    )
    graph = miro.run_graph(SIM, client=client)
    assert graph["graph_id"] == "graph_2"
    assert graph["nodes"][0]["name"] == "A"


def test_job_for_simulation_encontra_o_trabalho():
    job = miro.start_simulation_job({"source": "sistema", "title": "Panorama"}, session=None)
    miro._job_update(job["id"], result={"simulation_id": "sim_encontrada", "seed": {"title": "Panorama"}})
    try:
        found = miro.job_for_simulation("sim_encontrada")
        assert found is not None
        assert found["id"] == job["id"]
        assert found["title"] == "Panorama"
        assert found["seed"] == {"title": "Panorama"}
        assert miro.job_for_simulation("sim_outra") is None
    finally:
        with miro._JOBS_LOCK:
            miro._JOBS.pop(job["id"], None)

