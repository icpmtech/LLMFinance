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
from api import llm_contratos_service as service  # noqa: E402
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
        "chat",
        lambda instrucao, dados, max_tokens, temperatura: {
            "resposta": "Contrato de limpeza.",
            "modelo": "Qwen/Qwen2.5-0.5B-Instruct",
            "adaptador": None,
            "prompt_tokens": 12,
            "tokens_gerados": 5,
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
    assert resposta.json()["resposta"] == "Contrato de limpeza."
