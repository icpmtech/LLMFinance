"""Testes do modelo de contratos (fine-tuning LoRA) e da sua API.

Correm sem treinar nem carregar o modelo: cobrem as peÃ§as onde um erro Ã© fÃ¡cil
de esconder â€” a divisÃ£o treino/held-out, a mÃ¡scara do prompt (a perda sÃ³ pode
contar a resposta), as mÃ©tricas de fidelidade e a ligaÃ§Ã£o rotaâ†’serviÃ§o.

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
# Prompt e mÃ¡scara
# ---------------------------------------------------------------------------


def test_render_prompt_tem_instrucao_e_dados() -> None:
    prompt = modelo.render_prompt("Descreve o contrato.", "Contrato 1 - limpeza")
    assert "### InstruÃ§Ã£o:" in prompt
    assert "Descreve o contrato." in prompt
    assert "Contrato 1 - limpeza" in prompt
    assert prompt.rstrip().endswith("### Resposta:")


def test_build_messages_leva_o_sistema() -> None:
    mensagens = modelo.build_messages("Descreve.", "dados")
    assert [m["role"] for m in mensagens] == ["system", "user"]
    assert mensagens[0]["content"] == modelo.SYSTEM_PROMPT
    assert "dados" in mensagens[1]["content"]


class _TokenizerFalso:
    """Tokenizer mÃ­nimo: um id por caractere, para o teste nÃ£o descer ao Qwen."""

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
# DivisÃ£o treino / held-out
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
# MÃ©tricas de fidelidade
# ---------------------------------------------------------------------------


def test_numeros_normalizados_ignoram_formatacao() -> None:
    assert avaliacao.numeric_tokens("20 806,20 â‚¬ e 1 379,64 â‚¬") == ["20806.20", "1379.64"]
    assert avaliacao.numeric_tokens("sem valores") == []


def test_numeros_em_formato_ingles_nao_viram_milhoes() -> None:
    # RegressÃ£o: Â«20806.2Â» era lido como 208 062 (o ponto tratado como milhares)
    # e a verificaÃ§Ã£o acusava um valor inventado que estava nos dados.
    assert avaliacao.numeric_tokens("PreÃ§o contratual: 20806.2") == ["20806.20"]
    assert avaliacao.numeric_tokens("1.234.567") == ["1234567.00"]
    assert avaliacao.numeric_fidelity("teve como valor de 20 806,20 â‚¬.", "PreÃ§o: 20806.2") == 1.0


def test_f1_premia_sobreposicao_e_pune_resposta_errada() -> None:
    assert avaliacao.token_f1("valor de 20 806,20 â‚¬", "valor de 20 806,20 â‚¬") == pytest.approx(1.0)
    assert avaliacao.token_f1("contrato de limpeza", "contrato de limpeza urbana") > 0.6
    assert avaliacao.token_f1("nada a ver", "contrato de limpeza") == 0.0
    assert avaliacao.token_f1("", "contrato") == 0.0


def test_fidelidade_numerica_detecta_valor_trocado() -> None:
    gabarito = "O valor contratual foi 20 806,20 â‚¬."
    assert avaliacao.numeric_fidelity("O valor foi 20 806,20 â‚¬.", gabarito) == 1.0
    assert avaliacao.numeric_fidelity("O valor foi 20,00 â‚¬.", gabarito) == 0.0
    assert avaliacao.numeric_fidelity("sem nÃºmeros", "tambÃ©m sem nÃºmeros") is None


def test_ancoragem_apanha_data_inventada() -> None:
    """O defeito real: contrato sem data, resposta com data.

    `numeric_fidelity` nÃ£o via isto â€” a data nÃ£o estava no gabarito, logo nÃ£o era
    medida. A ancoragem mede ao contrÃ¡rio: nÃºmeros escritos que nÃ£o estÃ£o no
    pedido.
    """
    pedido = "Contrato 900001 - reagentes\nPreÃ§o contratual: 15430.75"
    inventada = (
        "Este contrato, publicado a 2021-08-26 e com regime CCP (DL 18/2008), "
        "tem o valor de 15 430,75 â‚¬."
    )
    ancorada = "Este contrato tem o valor de 15 430,75 â‚¬."

    resultado = avaliacao.numeric_grounding(inventada, pedido)
    assert resultado is not None
    assert "2021.00" in resultado["inventados"]
    assert "18.00" in resultado["inventados"]
    assert "2008.00" in resultado["inventados"]
    assert resultado["taxa"] > 0

    assert avaliacao.numeric_grounding(ancorada, pedido)["inventados"] == []
    assert avaliacao.numeric_grounding(ancorada, pedido)["taxa"] == 0.0
    assert avaliacao.numeric_grounding("sem nÃºmeros", pedido) is None


# ---------------------------------------------------------------------------
# ServiÃ§o e Ã­ndice
# ---------------------------------------------------------------------------


def test_read_metrics_le_a_curva(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    ficheiro = tmp_path / "metrics.jsonl"
    ficheiro.write_text(
        "\n".join(
            [
                json.dumps({"step": 1, "perda": 1.5, "perplexidade": 4.48}),
                "linha invÃ¡lida",
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


def test_adaptadores_no_disco_sao_listados_e_resolvidos(tmp_path: Path) -> None:
    """O chat escolhe o adaptador por `id`; os de outro modelo base ficam de fora."""
    import json as _json

    def _criar(pasta: Path, base: str) -> None:
        pasta.mkdir(parents=True, exist_ok=True)
        (pasta / "adapter_config.json").write_text(_json.dumps({"base_model_name_or_path": base}), encoding="utf-8")
        (pasta / "adapter_model.safetensors").write_bytes(b"0" * 16)

    _criar(tmp_path / "qwen05-contratos", modelo.DEFAULT_BASE_MODEL)
    _criar(tmp_path / "soup-qwen05", modelo.DEFAULT_BASE_MODEL)
    _criar(tmp_path / "soup-mistral", "mistralai/Mistral-7B-Instruct-v0.3")
    (tmp_path / "vazia").mkdir()

    itens = {i["id"]: i for i in modelo.listar_adaptadores(tmp_path)}
    assert set(itens) == {"qwen05-contratos", "soup-qwen05", "soup-mistral"}
    assert itens["soup-qwen05"]["origem"] == "soup"
    assert itens["soup-qwen05"]["compativel"] is True
    assert itens["soup-mistral"]["compativel"] is False

    assert modelo.resolver_adaptador("soup-qwen05", tmp_path).name == "soup-qwen05"
    with pytest.raises(ValueError, match="mistral"):
        modelo.resolver_adaptador("soup-mistral", tmp_path)
    with pytest.raises(ValueError, match="desconhecido"):
        modelo.resolver_adaptador("nao-existe", tmp_path)


def test_index_eval_sem_elasticsearch_nao_rebenta(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "_client", lambda: None)
    assert service.index_eval({"base": {}, "treinado": {}}) is None
    assert service.index_run({"treino": {}}) is None
    assert service.list_evals() == []


def test_mapeamentos_do_indice_cobrem_as_metricas() -> None:
    campos = service.MAPPINGS[service.MODEL_EVALS_INDEX]["properties"]
    for esperado in ("base", "treinado", "delta", "f1_medio", "criado_em"):
        assert esperado in campos, f"o Ã­ndice de avaliaÃ§Ãµes perdeu o campo {esperado}"
    assert "metricas" in service.MAPPINGS[service.MODEL_RUNS_INDEX]["properties"]


# ---------------------------------------------------------------------------
# Matriz de pesos (lida do adaptador) e ligaÃ§Ãµes
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
    # â€–Aâ€– de ones(4,8) = âˆš32 ; â€–Bâ€– de 2Â·ones(8,4) = 2âˆš32 â†’ produto = 2Â·32 = 64
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
# Agente: skills, memÃ³ria, prompts, verificaÃ§Ã£o e auto-aprendizagem
# ---------------------------------------------------------------------------


def test_termos_uteis_tira_as_palavras_da_pergunta() -> None:
    assert agente.termos_uteis("Quantos contratos tem o Municipio de Chaves e qual o maior?") == "municipio chaves"


def test_escolher_skills_por_gatilho() -> None:
    assert "procurar_contratos" in agente.escolher_skills("mostra os contratos de limpeza")
    assert "subsidios" in agente.escolher_skills("que subsÃ­dios recebeu este beneficiÃ¡rio?")
    assert agente.escolher_skills("bom dia") == []


def test_escolher_skills_prioriza_pesquisa_agregada_para_ranking() -> None:
    pergunta = "Quais empresas adjudicatárias têm o maior valor total em contratos?"
    assert agente.escolher_skills(pergunta) == ["ranking_empresas"]


def test_escolher_skills_nao_confunde_valor_total_de_empresa_com_ranking() -> None:
    pergunta = "Qual é o valor total da empresa OLIVEIRA & PIRES - SANEAMENTO E LIMPEZAS?"
    assert agente.escolher_skills(pergunta) == ["ficha_entidade"]


def test_escolher_skills_conta_contratos_pela_ficha_da_empresa() -> None:
    assert agente.escolher_skills("Quantos contratos tem a Claranet?") == [
        "ficha_entidade",
        "procurar_contratos",
    ]


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


def test_limpar_nome_entidade_remove_a_pergunta_que_envolve_a_empresa() -> None:
    pergunta = (
        "Quem é a empresa OLIVEIRA & PIRES - SANEAMENTO E LIMPEZAS "
        "e quantos contratos tem como adjudicatária?"
    )
    assert agente.limpar_nome_entidade(pergunta) == "oliveira & pires - saneamento e limpezas"
    assert agente.limpar_nome_entidade(
        "Quantos contratos tem a empresa OLIVEIRA & PIRES - SANEAMENTO E LIMPEZAS?"
    ) == "oliveira & pires - saneamento e limpezas"


def test_skill_de_contratos_filtra_pelo_nome_da_empresa(monkeypatch: pytest.MonkeyPatch) -> None:
    capturado: Dict[str, object] = {}

    def _falsa_search_contracts(**kwargs):
        capturado.update(kwargs)
        return {"total": 2, "items": []}

    monkeypatch.setitem(
        __import__("sys").modules,
        "api.es.contratos",
        type("M", (), {"search_contracts": staticmethod(_falsa_search_contracts)}),
    )
    pergunta = (
        "Quem é a empresa OLIVEIRA & PIRES - SANEAMENTO E LIMPEZAS "
        "e quantos contratos tem como adjudicatária?"
    )
    agente.executar_skill("procurar_contratos", pergunta)
    assert capturado["entity"] == "oliveira & pires - saneamento e limpezas"
    assert capturado["q"] is None


def test_skill_de_contratos_pesquisa_por_nif(monkeypatch: pytest.MonkeyPatch) -> None:
    capturado: Dict[str, object] = {}

    def _falsa_search_contracts(**kwargs):
        capturado.update(kwargs)
        return {"total": 3, "items": []}

    monkeypatch.setitem(
        __import__("sys").modules,
        "api.es.contratos",
        type("M", (), {"search_contracts": staticmethod(_falsa_search_contracts)}),
    )
    agente.executar_skill("procurar_contratos", "Contratos da empresa com NIF 506782100")
    assert capturado["nif"] == "506782100"
    assert capturado["q"] is None


def test_skill_de_ficha_entidade_usa_lookup_exato_por_nif(monkeypatch: pytest.MonkeyPatch) -> None:
    capturado: Dict[str, str] = {}
    empresa = {
        "nif": "506782100",
        "name": "Município de Chaves",
        "contracts_total": 3,
        "total_value": 120.0,
        "adjudicante": {"contracts_count": 2, "total_value": 100.0},
        "adjudicatario": {"contracts_count": 1, "total_value": 20.0},
    }

    def _falso_lookup(nif: str):
        capturado["nif"] = nif
        return empresa

    monkeypatch.setitem(
        __import__("sys").modules,
        "api.es.entidades",
        type(
            "M",
            (),
            {
                "get_company_by_nif": staticmethod(_falso_lookup),
                "search_companies": staticmethod(lambda **_k: {"items": []}),
            },
        ),
    )
    resultado = agente._skill_entidade(nif="506782100")
    assert capturado["nif"] == "506782100"
    assert resultado["nome"] == "Município de Chaves"
    assert resultado["adjudicatario"]["contracts_count"] == 1


def test_skill_ranking_devolve_dados_agregados(monkeypatch: pytest.MonkeyPatch) -> None:
    resumo = {
        "unique_adjudicatarios": 42,
        "top_entities": [
            {
                "name": "Empresa A",
                "nif": "501234567",
                "adjudicatario": {
                    "contracts_count": 7,
                    "total_value": 900.0,
                    "first_year": 2022,
                    "last_year": 2025,
                },
            }
        ],
    }
    monkeypatch.setitem(
        __import__("sys").modules,
        "api.es.entidades",
        type("M", (), {"get_entity_role_summary": staticmethod(lambda **_k: resumo)}),
    )
    resultado = agente._skill_ranking_empresas(limite=1, ano=2025)
    assert resultado["ano_filtrado"] == 2025
    assert resultado["total_entidades"] == 42
    assert resultado["empresas"] == [
        {
            "nome": "Empresa A",
            "nif": "501234567",
            "contratos": 7,
            "valor_total": 900.0,
            "primeiro_ano": 2022,
            "ultimo_ano": 2025,
        }
    ]


def test_resumo_de_contrato_aceita_parte_em_dict() -> None:
    item = {
        "idcontrato": "1",
        "objectoContrato": "Limpeza",
        "precoContratual": 10.0,
        "adjudicantes": {"parsed": [{"nome": "MunicÃ­pio X"}]},
        "adjudicatarios": {"raw": ["501394192 - Empresa Y"]},
    }
    resumo = agente._resumo_contrato(item)
    assert resumo["adjudicante"] == "MunicÃ­pio X"
    assert resumo["adjudicatario"] == "Empresa Y"


def test_verificacao_apanha_numeros_inventados() -> None:
    resultado = agente.verificar_resposta("Custou 20 806,20 â‚¬ e 99 999,00 â‚¬.", "PreÃ§o contratual: 20806.2")
    assert resultado["suportados"] == ["20806.20"]
    assert resultado["inventados"] == ["99999.00"]
    assert resultado["confianca"] == 0.5
    assert "sem suporte" in resultado["motivo"]


def test_responder_substitui_numeros_nao_sustentados_pelos_dados_da_ficha(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    skills = [
        {
            "nome": "ficha_entidade",
            "resultado": {
                "encontrado": True,
                "nome": "OLIVEIRA & PIRES - SANEAMENTO E LIMPEZAS",
                "contratos": 47,
                "valor_total": 3577999.56,
            },
        }
    ]
    monkeypatch.setattr(service.contratos_lora, "resolver_adaptador", lambda _adaptador: tmp_path)
    monkeypatch.setattr(
        service.contratos_lora,
        "answer",
        lambda *_args, **_kwargs: {
            "resposta": "A empresa tem 47 contratos e o valor total é 99999999,00 €.",
            "modelo": "qwen",
            "adaptador": None,
            "prompt_tokens": 20,
            "tokens_gerados": 12,
            "tokens": [{"token": "99999999", "id": 1, "probabilidade": 0.9}],
            "confianca_media": 0.9,
        },
    )
    monkeypatch.setattr(agente, "resolver_prompt", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(
        agente,
        "construir_contexto",
        lambda **_kwargs: {
            "contexto": '[SKILL ficha_entidade] {"contratos": 47, "valor_total": 3577999.56}',
            "passos": [],
            "evidencias": [],
            "skills": skills,
            "memoria_ids": [],
        },
    )

    resposta = service.responder(instrucao="Quantos contratos e qual o valor total desta empresa?")

    assert resposta["resposta"] == (
        "OLIVEIRA & PIRES - SANEAMENTO E LIMPEZAS: tem 47 contratos públicos registados, "
        "com valor total adjudicado de 3 577 999,56 €."
    )
    assert resposta["verificacao"]["inventados"] == []
    assert resposta["tokens"] == []
    assert resposta["confianca_media"] is None
    assert any(passo["fase"] == "resposta_estruturada" for passo in resposta["passos"])


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
    fases = [p.fase for p in construido["passos"]]
    assert fases[0] == "pergunta" and "dados" in fases
    assert "DADOS DO PEDIDO" in construido["contexto"]
    assert construido["evidencias"] == []


def test_com_documento_o_corpus_nao_e_consultado(monkeypatch: pytest.MonkeyPatch) -> None:
    """Um 0,5 B colava evidÃªncias de outros contratos na descriÃ§Ã£o do documento."""

    def _explodir(*_a, **_k):  # pragma: no cover - sÃ³ falha se for chamado
        raise AssertionError("com documento no pedido nÃ£o se procura no corpus")

    monkeypatch.setattr(agente, "recuperar_rag", _explodir)
    monkeypatch.setattr(agente, "executar_skill", _explodir)
    monkeypatch.setattr(agente, "recuperar_memorias", lambda *a, **k: [])

    doc = "Contrato 772453 - limpeza de coletores\nAdjudicante: MunicÃ­pio de Condeixa-a-Nova"
    construido = agente.construir_contexto(pergunta="Descreve este contrato.", dados=doc)
    assert construido["evidencias"] == []
    assert construido["skills"] == []
    assert "[DADOS DO PEDIDO]" in construido["contexto"]
    assert "Corpus nÃ£o consultado" in " ".join(p.titulo for p in construido["passos"])

    # Sem documento (pergunta sobre o corpus) o RAG volta a correr.
    chamadas: list[str] = []
    monkeypatch.setattr(agente, "recuperar_rag", lambda consulta, k=3: chamadas.append(consulta) or [])
    monkeypatch.setattr(agente, "escolher_skills", lambda *_a, **_k: [])
    agente.construir_contexto(pergunta="que contratos existem sobre limpeza?", dados="")
    assert chamadas == ["que contratos existem sobre limpeza?"]


def test_pergunta_de_empresa_ignora_memoria_e_rag_de_outra_entidade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pergunta = (
        "Quem é a empresa OLIVEIRA & PIRES - SANEAMENTO E LIMPEZAS "
        "e quantos contratos tem como adjudicatária?"
    )
    memorias = [
        {
            "id": "chaves",
            "tipo": "memoria",
            "titulo": "Município de Chaves é o NIF 506782100",
            "instrucao": "",
            "dados": "",
            "resposta": "",
        },
        {
            "id": "oliveira",
            "tipo": "memoria",
            "titulo": "Empresa OLIVEIRA & PIRES - SANEAMENTO E LIMPEZAS",
            "instrucao": "",
            "dados": "",
            "resposta": "",
        },
    ]
    chunks = [
        {"fonte": "contratos", "titulo": "Entidade Filipa Dias Pires", "texto": "Contrato de terceiros."},
        {
            "fonte": "contratos",
            "titulo": "OLIVEIRA & PIRES - SANEAMENTO E LIMPEZAS",
            "texto": "Contrato da empresa pedida.",
        },
    ]
    monkeypatch.setattr(agente, "recuperar_memorias", lambda *_a, **_k: memorias)
    monkeypatch.setattr(agente, "recuperar_rag", lambda *_a, **_k: chunks)
    monkeypatch.setattr(agente, "escolher_skills", lambda *_a, **_k: [])

    construido = agente.construir_contexto(pergunta=pergunta)

    assert construido["memoria_ids"] == ["oliveira"]
    assert [item["texto"] for item in construido["evidencias"]] == ["Contrato da empresa pedida."]
    assert "Chaves" not in construido["contexto"]
    assert "Filipa" not in construido["contexto"]


def test_memoria_de_outro_municipio_nao_entra_na_descricao(monkeypatch: pytest.MonkeyPatch) -> None:
    """Uma memÃ³ria sobre Chaves colava-se a um contrato de Condeixa-a-Nova."""
    chaves = {"id": "m1", "tipo": "memoria", "titulo": "MunicÃ­pio de Chaves Ã© o NIF 506782100", "instrucao": "CÃ¢mara de Chaves", "dados": ""}
    condeixa = {"id": "m2", "tipo": "memoria", "titulo": "Condeixa-a-Nova Ã© o NIF 506131870", "instrucao": "CÃ¢mara de Condeixa", "dados": ""}
    monkeypatch.setattr(agente, "recuperar_memorias", lambda *a, **k: [chaves, condeixa])
    monkeypatch.setattr(agente, "recuperar_rag", lambda *a, **k: [])
    monkeypatch.setattr(agente, "escolher_skills", lambda *a, **k: [])

    doc = "Contrato 772453 - limpeza de coletores\nAdjudicante: MunicÃ­pio de Condeixa-a-Nova"
    construido = agente.construir_contexto(pergunta="Descreve este contrato.", dados=doc)
    assert construido["memoria_ids"] == ["m2"]
    assert "Chaves" not in construido["contexto"]
    assert any("ignoradas" in p.titulo for p in construido["passos"])


def test_ancoras_ignoram_vocabulario_generico() -> None:
    assert agente._ancoras("Adjudicante: MunicÃ­pio de Condeixa-a-Nova") == {"condeixa"}
    assert agente._ancoras("municÃ­pio de Chaves NIF 506782100") == {"chaves", "506782100"}


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


def test_prompt_consultar_responde_com_base_em_evidencias() -> None:
    texto = agente.resolver_prompt("consultar", None)
    assert "evidências" in texto
    assert "não encontraste dados" in texto
    assert "Não inventes" in texto


def test_prompt_consultar_empresas_prioriza_ficha_e_nao_contagem_textual() -> None:
    prompt = next(p for p in agente.PROMPTS_PREDEFINIDOS if p["id"] == "consultar_empresas")
    assert prompt["nome"] == "Consultar empresas"
    assert agente.resolver_prompt("consultar_empresas", None) == prompt["texto"]
    assert "ficha estruturada" in prompt["texto"]
    assert "contagem de contratos da empresa" in prompt["texto"]


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
    assert "mÃ­nimo" in resposta.json()["detail"]


def test_rotas_do_agente_estao_registadas() -> None:
    from api import main as api_main

    # `app.routes` desta versÃ£o do FastAPI embrulha os routers incluÃ­dos em
    # `_IncludedRouter` (sem `.path`); o contrato pÃºblico Ã© o esquema OpenAPI.
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
        "/llm/modelo/retreinar/historico",
        "/llm/modelo/retreinar/parar",
        "/llm/modelo/versoes",
        "/llm/modelo/versoes/reverter",
    ):
        assert esperado in caminhos, f"rota em falta: {esperado}"

    # O WebSocket nÃ£o entra no OpenAPI: procura-se na Ã¡rvore de rotas do router.
    from api import llm_contratos_routes as rotas

    websockets = {r.path for r in rotas.router.routes if r.__class__.__name__ == "APIWebSocketRoute"}
    assert "/llm/modelo/retreinar/ws" in websockets


def test_instantaneo_do_treino_nao_varre_o_disco(monkeypatch: pytest.MonkeyPatch) -> None:
    """O WebSocket pede um retrato a cada 400 ms: nÃ£o pode contar backups."""
    from api import llm_contratos_treino as treino

    def _explodir() -> int:  # pragma: no cover - sÃ³ falha se for chamado
        raise AssertionError("instantaneo() nÃ£o deve contar versÃµes guardadas")

    monkeypatch.setattr(treino, "_versoes_guardadas", _explodir)
    estado = treino.instantaneo()

    assert isinstance(estado["historico"], list)
    assert "fase" in estado and "atividade" in estado
    assert estado["agora_ts"] > 0


def test_ws_do_retreino_recusa_sem_token() -> None:
    """Sem token o canal fecha antes de aceitar (1008), nÃ£o fica a escutar."""
    from starlette.websockets import WebSocketDisconnect

    cliente, _ = _cliente()
    with pytest.raises(WebSocketDisconnect) as falha:
        with cliente.websocket_connect("/llm/modelo/retreinar/ws"):
            pass
    assert falha.value.code == 1008
    assert "SessÃ£o em falta" in (falha.value.reason or "")


def test_ws_do_retreino_entrega_o_estado_com_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Com sessÃ£o vÃ¡lida o canal aceita e envia logo o retrato do estado."""
    from api import llm_contratos_treino as treino
    from api import llm_contratos_routes as rotas

    monkeypatch.setattr(
        rotas,
        "session_from_token",
        lambda token: type("S", (), {"session_id": "s1", "token": token})(),
    )
    monkeypatch.setattr(
        treino,
        "instantaneo",
        lambda: {
            "a_correr": True,
            "passo": 3,
            "passos": 12,
            "perda": 0.31,
            "tokens": 2955,
            "fase": "a_treinar",
            "atividade": "A treinar",
            "historico": [{"passo": 1, "perda": 1.0}, {"passo": 3, "perda": 0.31}],
            "perda_antes": 1.2,
            "perda_depois": None,
            "erro": None,
            "paragem_pedida": False,
            "agora_ts": 1.0,
        },
    )

    cliente, _ = _cliente()
    with cliente.websocket_connect("/llm/modelo/retreinar/ws?token=abc") as ws:
        dados = ws.receive_json()

    assert dados["tipo"] == "estado"
    assert dados["passo"] == 3
    assert dados["fase"] == "a_treinar"
    assert len(dados["historico"]) == 2

# ---------------------------------------------------- guarda numÃ©rica (chat)
class _TokFalso:
    """Tokenizer mÃ­nimo: sÃ³ os dÃ­gitos 0-9, em ids 10-19."""

    def get_vocab(self) -> dict:
        return {str(d): 10 + d for d in range(10)}


def test_guarda_numerica_so_deixa_escrever_numeros_do_documento() -> None:
    import torch

    guarda = modelo.GuardaNumerica(_TokFalso(), "Preco contratual: 20806.2")
    assert guarda.permitidos == {"20806", "208062"}

    def bloqueados(ids: list) -> set:
        scores = torch.zeros(1, 20)
        saida = guarda(torch.tensor([ids]), scores)
        return {d for d in range(10) if saida[0, 10 + d].item() == float("-inf")}

    # Â«2Â» em curso: sÃ³ o Â«0Â» continua para 20806 (o Â«19/07/2019Â» inventado morre aqui)
    assert bloqueados([10 + 2]) == set(range(10)) - {0}
    # Â«2080Â» em curso: sÃ³ o Â«6Â» fecha o nÃºmero
    assert bloqueados([10 + 2, 10 + 0, 10 + 8, 10 + 0]) == set(range(10)) - {6}


def test_guarda_numerica_sem_numero_em_curso_nao_bloqueia() -> None:
    import torch

    guarda = modelo.GuardaNumerica(_TokFalso(), "sem numeros aqui 7")
    scores = torch.zeros(1, 20)
    saida = guarda(torch.tensor([[999]]), scores)  # token que nao e digito
    assert not torch.isinf(saida).any()
