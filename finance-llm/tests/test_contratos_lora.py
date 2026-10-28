"""Testes do modelo de contratos (fine-tuning LoRA) e da sua API.

Correm sem treinar nem carregar o modelo: cobrem as peças onde um erro é fácil
de esconder — a divisão treino/held-out, a máscara do prompt (a perda só pode
contar a resposta), as métricas de fidelidade e a ligação rota→serviço.

    pytest tests/test_contratos_lora.py -q
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api import llm_contratos_routes as routes  # noqa: E402
from api import llm_contratos_agente as agente  # noqa: E402
from api import llm_contratos_service as service  # noqa: E402
from api import llm_contratos_treino as treino  # noqa: E402
from inference import contratos_eval as avaliacao  # noqa: E402
from inference import contratos_lora as modelo  # noqa: E402


# ---------------------------------------------------------------------------
# Prompt e máscara
# ---------------------------------------------------------------------------


def test_render_prompt_tem_instrucao_e_dados() -> None:
    prompt = modelo.render_prompt("Descreve o contrato.", "Contrato 1 - limpeza")
    assert "### Instrução:" in prompt
    assert "Descreve o contrato." in prompt
    assert "Contrato 1 - limpeza" in prompt
    assert prompt.rstrip().endswith("### Resposta:")


def test_build_messages_leva_o_sistema() -> None:
    mensagens = modelo.build_messages("Descreve.", "dados")
    assert [m["role"] for m in mensagens] == ["system", "user"]
    assert mensagens[0]["content"] == modelo.SYSTEM_PROMPT
    assert "dados" in mensagens[1]["content"]


class _TokenizerFalso:
    """Tokenizer mínimo: um id por caractere, para o teste não descer ao Qwen."""

    chat_template = "{{ messages }}"
    eos_token_id = 0
    pad_token = "<pad>"

    def __call__(self, texto, add_special_tokens: bool = True, **kwargs):  # noqa: ARG002
        return {"input_ids": [1] * len(texto)}

    def apply_chat_template(self, messages, tokenize: bool = False, add_generation_prompt: bool = True):
        del tokenize, add_generation_prompt
        return "".join(m["content"] for m in messages)


def test_encode_example_mascara_o_prompt() -> None:
    exemplo = __import__("training.train_lora_contratos", fromlist=["encode_example"]).encode_example(
        _TokenizerFalso(), {"instruction": "Descreve.", "input": "Contrato 1", "output": "Resumo"}, 512
    )
    assert exemplo is not None
    vistos = [i for i, label in enumerate(exemplo["labels"]) if label != -100]
    assert vistos, "a resposta tem de produzir tokens de perda"
    assert exemplo["labels"][: vistos[0]] == [-100] * vistos[0]
    assert exemplo["input_ids"][vistos[0] :] == exemplo["labels"][vistos[0] :]
    assert len(exemplo["input_ids"]) == len(exemplo["labels"])


def test_encode_example_sem_espaco_devolve_none() -> None:
    exemplo = __import__("training.train_lora_contratos", fromlist=["encode_example"]).encode_example(
        _TokenizerFalso(), {"instruction": "x" * 500, "input": "y" * 500, "output": "z"}, 40
    )
    assert exemplo is None


# ---------------------------------------------------------------------------
# Divisão treino / held-out
# ---------------------------------------------------------------------------


def test_split_indices_e_estavel_e_sem_sobreposicao() -> None:
    treino, held = modelo.split_indices(100, 20, seed=42)
    assert len(treino) == 80 and len(held) == 20
    assert not set(treino) & set(held)
    assert sorted(treino + held) == list(range(100))
    assert (treino, held) == modelo.split_indices(100, 20, seed=42)


def test_split_pequeno_ja_mistura_as_fontes() -> None:
    # Ficheiro ordenado por fonte, como o exporter grava: 245 / 300 / 262.
    fontes = ["contratos"] * 245 + ["empresas"] * 300 + ["subvencoes"] * 262
    treino, held = modelo.split_indices(len(fontes), 60, seed=42)
    assert {fontes[i] for i in treino[:40]} == {"contratos", "empresas", "subvencoes"}
    assert {fontes[i] for i in held} == {"contratos", "empresas", "subvencoes"}


def test_held_out_pairs_nao_cruza_com_o_treino(tmp_path: Path) -> None:
    rows = [
        {"instruction": "i", "input": f"dado {i}", "output": "o", "metadata": {"fonte": "contratos"}}
        for i in range(50)
    ]
    pares = avaliacao.held_out_pairs(rows, holdout=10, seed=42)
    treino, _ = modelo.split_indices(len(rows), 10, seed=42)
    assert len(pares) == 10
    assert not {r["input"] for r in pares} & {rows[i]["input"] for i in treino}


# ---------------------------------------------------------------------------
# Métricas de fidelidade
# ---------------------------------------------------------------------------


def test_numeros_normalizados_ignoram_formatacao() -> None:
    assert avaliacao.numeric_tokens("20 806,20 € e 1 379,64 €") == ["20806.20", "1379.64"]
    assert avaliacao.numeric_tokens("sem valores") == []


def test_numeros_em_formato_ingles_nao_viram_milhoes() -> None:
    # Regressão: «20806.2» era lido como 208 062 (o ponto tratado como milhares)
    # e a verificação acusava um valor inventado que estava nos dados.
    assert avaliacao.numeric_tokens("Preço contratual: 20806.2") == ["20806.20"]
    assert avaliacao.numeric_tokens("1.234.567") == ["1234567.00"]
    assert avaliacao.numeric_fidelity("teve como valor de 20 806,20 €.", "Preço: 20806.2") == 1.0


def test_f1_premia_sobreposicao_e_pune_resposta_errada() -> None:
    assert avaliacao.token_f1("valor de 20 806,20 €", "valor de 20 806,20 €") == pytest.approx(1.0)
    assert avaliacao.token_f1("contrato de limpeza", "contrato de limpeza urbana") > 0.6
    assert avaliacao.token_f1("nada a ver", "contrato de limpeza") == 0.0
    assert avaliacao.token_f1("", "contrato") == 0.0


def test_fidelidade_numerica_detecta_valor_trocado() -> None:
    gabarito = "O valor contratual foi 20 806,20 €."
    assert avaliacao.numeric_fidelity("O valor foi 20 806,20 €.", gabarito) == 1.0
    assert avaliacao.numeric_fidelity("O valor foi 20,00 €.", gabarito) == 0.0
    assert avaliacao.numeric_fidelity("sem números", "também sem números") is None


# ---------------------------------------------------------------------------
# Serviço e índice
# ---------------------------------------------------------------------------


def test_read_metrics_le_a_curva(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    ficheiro = tmp_path / "metrics.jsonl"
    ficheiro.write_text(
        "\n".join(
            [
                json.dumps({"step": 1, "perda": 1.5, "perplexidade": 4.48}),
                "linha inválida",
                json.dumps({"step": 2, "perda": 0.8, "perplexidade": 2.22}),
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(service, "METRICS_FILE", ficheiro)
    pontos = service.read_metrics()
    assert [p["step"] for p in pontos] == [1, 2]
    assert service.read_metrics(limit=1)[0]["step"] == 2


def test_model_state_sem_adaptador(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(modelo, "DEFAULT_ADAPTER_DIR", tmp_path / "inexistente")
    monkeypatch.setattr(service, "METRICS_FILE", tmp_path / "metrics.jsonl")
    estado = service.model_state()
    assert estado["adaptador_disponivel"] is False
    assert estado["metricas"]["pontos"] == 0
    assert estado["fonte_dados"]["indices"] == ["contratos", "finance_entities", "finance_subvencoes"]


def test_index_eval_sem_elasticsearch_nao_rebenta(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "_client", lambda: None)
    assert service.index_eval({"base": {}, "treinado": {}}) is None
    assert service.index_run({"treino": {}}) is None
    assert service.list_evals() == []


def test_mapeamentos_do_indice_cobrem_as_metricas() -> None:
    campos = service.MAPPINGS[service.MODEL_EVALS_INDEX]["properties"]
    for esperado in ("base", "treinado", "delta", "f1_medio", "criado_em"):
        assert esperado in campos, f"o índice de avaliações perdeu o campo {esperado}"
    assert "metricas" in service.MAPPINGS[service.MODEL_RUNS_INDEX]["properties"]


# ---------------------------------------------------------------------------
# Matriz de pesos (lida do adaptador) e ligações
# ---------------------------------------------------------------------------


def test_normas_do_adaptador_agrega_por_camada_e_projeccao(tmp_path: Path) -> None:
    import torch
    from safetensors.torch import save_file

    pesos = {
        "base_model.model.model.layers.0.self_attn.q_proj.lora_A.weight": torch.ones(4, 8),
        "base_model.model.model.layers.0.self_attn.q_proj.lora_B.weight": torch.ones(8, 4) * 2,
        "base_model.model.model.layers.1.mlp.down_proj.lora_A.weight": torch.ones(4, 8) * 3,
        "base_model.model.model.layers.1.mlp.down_proj.lora_B.weight": torch.ones(8, 4) * 4,
    }
    ficheiro = tmp_path / "adapter_model.safetensors"
    save_file(pesos, str(ficheiro))

    dados = service._normas_do_adaptador(ficheiro)
    assert dados["camadas"] == [0, 1]
    assert dados["modulos"] == ["q", "k", "v", "o", "gate", "up", "down"]
    # ‖A‖ de ones(4,8) = √32 ; ‖B‖ de 2·ones(8,4) = 2√32 → produto = 2·32 = 64
    assert dados["detalhe"]["0:q"]["produto"] == pytest.approx(64.0, rel=1e-3)
    assert dados["detalhe"]["1:down"]["produto"] == pytest.approx(12 * 32, rel=1e-3)
    assert dados["detalhe"]["0:k"]["produto"] == 0.0


def test_ligacoes_conta_pares_por_fonte(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    final = tmp_path / "data" / "final"
    final.mkdir(parents=True)
    dataset = final / "iqos_contratos_empresas_qwen.jsonl"
    linhas = [
        {"instruction": "i", "input": "d", "output": "o", "metadata": {"fonte": "contratos"}},
        {"instruction": "i", "input": "d", "output": "o", "metadata": {"fonte": "contratos"}},
        {"instruction": "i", "input": "d", "output": "o", "metadata": {"fonte": "empresas"}},
    ]
    dataset.write_text("\n".join(json.dumps(l, ensure_ascii=False) for l in linhas), encoding="utf-8")
    monkeypatch.setattr(service, "ROOT", tmp_path)
    monkeypatch.setattr(service.contratos_lora, "read_run_metadata", lambda *a, **k: {"dados": {"pares_treino": 2}})

    dados = service.ligacoes()
    assert [(f["id"], f["pares"]) for f in dados["fontes"]] == [("contratos", 2), ("empresas", 1)]
    assert dados["fontes"][0]["indice"] == "finance_contracts"
    assert dados["fontes"][0]["fracao"] == pytest.approx(2 / 3, rel=1e-3)
    assert dados["dataset"]["pares"] == 3


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


def _cliente():
    from fastapi.testclient import TestClient

    from api import main as api_main

    return TestClient(api_main.app), api_main


def test_rota_estado_do_modelo_e_publica() -> None:
    cliente, _ = _cliente()
    resposta = cliente.get("/llm/modelo")
    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert "adaptador_disponivel" in corpo
    assert "metricas" in corpo


def test_chat_exige_sessao() -> None:
    cliente, _ = _cliente()
    resposta = cliente.post("/llm/modelo/chat", json={"instrucao": "Descreve.", "dados": "Contrato 1"})
    assert resposta.status_code == 401


def test_chat_com_sessao_devolve_resposta(monkeypatch: pytest.MonkeyPatch) -> None:
    cliente, api_main = _cliente()
    from api.auth_routes import CurrentSession, require_session

    api_main.app.dependency_overrides[require_session] = lambda: CurrentSession.model_construct(
        user=None, session_id="s1", token="t"
    )
    monkeypatch.setattr(
        routes.service,
        "responder",
        lambda **kwargs: {
            "resposta": "Contrato de limpeza.",
            "modelo": "Qwen/Qwen2.5-0.5B-Instruct",
            "adaptador": None,
            "prompt_tokens": 12,
            "tokens_gerados": 5,
            "tokens": [{"token": "Contrato", "id": 1, "probabilidade": 0.99}],
            "confianca_media": 0.99,
            "verificacao": {"suportados": [], "inventados": [], "confianca": 1.0, "motivo": "ok"},
            "passos": [{"fase": "geracao", "titulo": "Resposta gerada", "detalhe": "", "dados": {}}],
            "evidencias": [],
            "skills": ["contagem"],
            "prompt_sistema": "sistema",
            "duracao_s": 1.2,
        },
    )
    try:
        resposta = cliente.post(
            "/llm/modelo/chat",
            json={"instrucao": "Descreve.", "dados": "Contrato 1 - limpeza", "max_tokens": 32},
        )
    finally:
        api_main.app.dependency_overrides.clear()
    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["resposta"] == "Contrato de limpeza."
    assert corpo["skills"] == ["contagem"]
    assert corpo["passos"][0]["fase"] == "geracao"


# ---------------------------------------------------------------------------
# Agente: skills, memória, prompts, verificação e auto-aprendizagem
# ---------------------------------------------------------------------------


def test_termos_uteis_tira_as_palavras_da_pergunta() -> None:
    assert agente.termos_uteis("Quantos contratos tem o Municipio de Chaves e qual o maior?") == "municipio chaves"


def test_escolher_skills_por_gatilho() -> None:
    assert "procurar_contratos" in agente.escolher_skills("mostra os contratos de limpeza")
    assert "subsidios" in agente.escolher_skills("que subsídios recebeu este beneficiário?")
    assert agente.escolher_skills("bom dia") == []


def test_skill_de_contagem_pesquisa_com_termos_uteis(monkeypatch: pytest.MonkeyPatch) -> None:
    capturado: Dict[str, object] = {}

    def _falsa_search_contracts(**kwargs):
        capturado.update(kwargs)
        return {"total": 42, "items": []}

    monkeypatch.setitem(
        __import__("sys").modules,
        "api.es.contratos",
        type("M", (), {"search_contracts": staticmethod(_falsa_search_contracts)}),
    )
    resultado = agente.executar_skill("contagem", "Quantos contratos tem o Municipio de Chaves?")
    assert resultado["total"] == 42
    assert capturado["q"] == "municipio chaves"
    assert capturado["strict"] is True


def test_resumo_de_contrato_aceita_parte_em_dict() -> None:
    item = {
        "idcontrato": "1",
        "objectoContrato": "Limpeza",
        "precoContratual": 10.0,
        "adjudicantes": {"parsed": [{"nome": "Município X"}]},
        "adjudicatarios": {"raw": ["501394192 - Empresa Y"]},
    }
    resumo = agente._resumo_contrato(item)
    assert resumo["adjudicante"] == "Município X"
    assert resumo["adjudicatario"] == "Empresa Y"


def test_verificacao_apanha_numeros_inventados() -> None:
    resultado = agente.verificar_resposta("Custou 20 806,20 € e 99 999,00 €.", "Preço contratual: 20806.2")
    assert resultado["suportados"] == ["20806.20"]
    assert resultado["inventados"] == ["99999.00"]
    assert resultado["confianca"] == 0.5
    assert "sem suporte" in resultado["motivo"]


def test_guardar_memoria_exige_titulo(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError):
        agente.guardar_memoria(titulo="   ")
    with pytest.raises(ValueError):
        agente.guardar_memoria(tipo="skill", titulo="skill sem nada")


def test_construir_contexto_sem_elasticsearch_nao_parte(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(agente, "recuperar_memorias", lambda *a, **k: [])
    monkeypatch.setattr(agente, "recuperar_rag", lambda *a, **k: [])
    monkeypatch.setattr(agente, "escolher_skills", lambda *a, **k: [])
    construido = agente.construir_contexto(pergunta="descreve isto", dados="Contrato 1")
    assert [p.fase for p in construido["passos"]] == ["pergunta", "dados"]
    assert "DADOS DO PEDIDO" in construido["contexto"]
    assert construido["evidencias"] == []


def test_pares_de_feedback_viram_treino(monkeypatch: pytest.MonkeyPatch) -> None:
    docs = [
        {"id": "a", "instrucao": "Descreve.", "dados": "d1", "correcao": "resposta certa", "nota": -1},
        {"id": "b", "instrucao": "Descreve.", "dados": "d2", "correcao": "", "nota": 1},
        {"id": "c", "instrucao": "Descreve.", "dados": "d3", "correcao": "outra", "nota": -1, "utilizado": True},
    ]
    monkeypatch.setattr(agente, "_search", lambda *a, **k: docs)
    monkeypatch.setattr(agente, "listar_memorias", lambda *a, **k: [])
    pares = agente.pares_de_feedback()
    assert len(pares) == 1
    assert pares[0]["output"] == "resposta certa"
    assert pares[0]["metadata"]["feedback_id"] == "a"


def test_prompt_predefinido_e_resolvido() -> None:
    texto = agente.resolver_prompt("auditar", None)
    assert texto and "Auditor" in texto
    assert agente.resolver_prompt(None, "  sistema escrito  ") == "sistema escrito"


def test_retreino_recusa_sem_pares(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(agente, "pares_de_feedback", lambda *a, **k: [])
    monkeypatch.setattr(agente, "estatisticas_feedback", lambda: {"total": 0, "uteis": 0, "corrigidos": 0, "por_utilizar": 0, "nota_media": None})
    cliente, api_main = _cliente()
    from api.auth_routes import CurrentSession, require_session

    api_main.app.dependency_overrides[require_session] = lambda: CurrentSession.model_construct(
        user=None, session_id="s1", token="t"
    )
    try:
        resposta = cliente.post("/llm/modelo/retreinar", json={"passos": 4})
    finally:
        api_main.app.dependency_overrides.clear()
    assert resposta.status_code == 409
    assert "mínimo" in resposta.json()["detail"]


def test_rotas_do_agente_estao_registadas() -> None:
    from api import main as api_main

    # `app.routes` desta versão do FastAPI embrulha os routers incluídos em
    # `_IncludedRouter` (sem `.path`); o contrato público é o esquema OpenAPI.
    caminhos = set(api_main.app.openapi()["paths"])
    for esperado in (
        "/llm/modelo/matriz",
        "/llm/modelo/matriz/{camada}/{modulo}",
        "/llm/modelo/ligacoes",
        "/llm/modelo/memoria",
        "/llm/modelo/skills",
        "/llm/modelo/prompts",
        "/llm/modelo/rag",
        "/llm/modelo/feedback",
        "/llm/modelo/retreinar",
    ):
        assert esperado in caminhos, f"rota em falta: {esperado}"
