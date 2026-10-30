"""Motor Soup (`api/llm_contratos_soup.py`): configs, validação e orquestração.

O CLI real não corre nos testes (precisa de `soup-cli[train]` e de um modelo):
usa-se um duplo em Python apontado por `SOUP_BIN`, que imprime linhas no mesmo
formato do Soup (`step N/M`, `loss=…`) e sai com o código pedido. É assim que se
verifica o que interessa — que o subprocesso é lançado, que as linhas são
traduzidas em passo/perda e que o estado termina em `concluido` ou `erro`.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from api import llm_contratos_soup as soup  # noqa: E402

DUPLO = """
import sys, time
config = sys.argv[-1]
print("Loading config from " + config)
print("Data OK: 12 train samples")
for passo, perda in ((1, 0.91), (2, 0.55), (3, 0.42), (4, 0.38)):
    print(f"  step {passo}/4 loss={perda}")
    time.sleep(0.05)
print("Treino concluido")
sys.exit(int(__import__("os").environ.get("SOUP_DUPLO_CODIGO", "0")))
"""


@pytest.fixture()
def duplo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Instala o duplo e aponta o `SOUP_BIN` para ele."""
    script = tmp_path / "soup_duplo.py"
    script.write_text(DUPLO, encoding="utf-8")
    monkeypatch.setenv("SOUP_BIN", f'"{sys.executable}" "{script}"')
    soup._versao_cache.update({"binario": None, "versao": None})
    return script


def _esperar(limite: float = 30.0) -> dict:
    """Espera o subprocesso terminar (o leitor fecha o estado por si)."""
    fim = time.time() + limite
    while time.time() < fim:
        estado = soup.instantaneo()
        if not estado["a_correr"]:
            return estado
        time.sleep(0.05)
    raise AssertionError("o duplo do Soup não terminou a tempo")


def test_lista_configs_com_modelo_base_e_dataset() -> None:
    configs = soup.configs()
    nomes = {c["nome"] for c in configs}
    assert "soup-qwen05-empresas-contratos" in nomes, nomes
    qwen = next(c for c in configs if c["nome"] == "soup-qwen05-empresas-contratos")
    assert qwen["base"] == "Qwen/Qwen2.5-0.5B-Instruct"
    assert qwen["dataset"].endswith(".jsonl")
    assert qwen["dataset_existe"] is True
    assert (qwen["pares"] or 0) > 0


def test_sem_binario_o_estado_diz_que_nao_esta_disponivel(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SOUP_BIN", raising=False)
    monkeypatch.setattr(soup.shutil, "which", lambda _nome: None)
    estado = soup.instantaneo()
    assert estado["disponivel"] is False
    assert soup.iniciar("soup-qwen05-empresas-contratos")["ok"] is False


def test_config_desconhecido_e_recusado(duplo: Path) -> None:
    resultado = soup.iniciar("nao-existe")
    assert resultado["ok"] is False
    assert "config desconhecido" in resultado["erro"]


def test_iniciar_le_passo_e_perda_do_subprocesso(duplo: Path) -> None:
    resultado = soup.iniciar("soup-qwen05-empresas-contratos")
    assert resultado["ok"] is True, resultado
    assert resultado["estado"] == "iniciado"

    estado = _esperar()
    assert estado["fase"] == "concluido", estado
    assert estado["codigo_saida"] == 0
    assert estado["passo"] == 4 and estado["passos"] == 4
    assert estado["perda"] == pytest.approx(0.38)
    assert [p["passo"] for p in estado["pontos"]] == [1, 2, 3, 4]
    assert any("Data OK" in linha for linha in estado["log"])
    assert estado["config"] == "soup-qwen05-empresas-contratos.yaml"


def test_saida_com_erro_fica_registada(duplo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOUP_DUPLO_CODIGO", "2")
    assert soup.iniciar("soup-qwen05-empresas-contratos")["ok"] is True
    estado = _esperar()
    assert estado["fase"] == "erro"
    assert estado["codigo_saida"] == 2
    assert estado["erro"]


def test_rotas_do_soup_estao_registadas() -> None:
    """A página de retreino depende destas três rotas (e do motor no WS)."""
    from api import llm_contratos_routes as rotas

    caminhos = {getattr(r, "path", "") for r in rotas.router.routes}
    for esperado in ("/llm/modelo/soup", "/llm/modelo/soup/validar", "/llm/modelo/soup/treinar", "/llm/modelo/soup/parar"):
        assert esperado in caminhos, f"rota em falta: {esperado}"


def test_curva_do_rewind_jsonl(tmp_path: Path) -> None:
    """A curva vem do `rewind.jsonl` (média das linhas de cada passo)."""
    saida = tmp_path / "out"
    saida.mkdir()
    (saida / "rewind.jsonl").write_text(
        "\n".join(
            [
                '{"kind": "batch", "step": 1, "row_loss": [1.0, 0.5]}',
                '{"kind": "batch", "step": 1, "row_loss": [0.3]}',
                '{"kind": "batch", "step": 2, "row_loss": [0.2]}',
                '{"kind": "outro", "step": 2, "row_loss": [9.9]}',
            ]
        ),
        encoding="utf-8",
    )
    pontos = soup._pontos_rewind(str(saida))
    assert pontos == [{"passo": 1, "perda": 0.6}, {"passo": 2, "perda": 0.2}]


def test_instantaneo_usa_o_rewind_quando_a_saida_existe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    saida = tmp_path / "out"
    saida.mkdir()
    (saida / "rewind.jsonl").write_text(
        '{"kind": "batch", "step": 7, "row_loss": [0.4, 0.6]}\n', encoding="utf-8"
    )
    monkeypatch.setitem(soup._estado, "saida", str(saida))
    monkeypatch.setitem(soup._estado, "pontos", [])
    monkeypatch.setitem(soup._estado, "passo", 0)
    monkeypatch.setitem(soup._estado, "perda", None)

    estado = soup.instantaneo()
    assert estado["pontos"] == [{"passo": 7, "perda": 0.5}]
    assert estado["passo"] == 7
    assert estado["perda"] == pytest.approx(0.5)


def test_linhas_de_truncagem_nao_contam_como_passos() -> None:
    """`Truncating eval dataset: 10/10` dava um total de passos errado."""
    assert soup._interpretar("Truncating eval dataset: 100%|████| 10/10 [00:00<00:00, 4538 ex/s]") is None
    assert soup._interpretar("  step 3/47 loss=1.25") == {"passo": 3, "passos": 47, "perda": 1.25}


def test_parar_sem_corrida_nao_e_erro_fatal() -> None:
    resultado = soup.parar()
    assert resultado["ok"] is False
    assert "não há treino" in resultado["motivo"]
