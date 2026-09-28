"""Testes da **pesquisa e análise de uma empresa** — puros, sem Elasticsearch.

O que aqui se protege é o que é fácil de partir sem se dar por isso:

- a agregação do portefólio (por ano/CPV/procedimento/adjudicante) e a
  concentração, que é o indicador que o utilizador lê primeiro;
- a régua robusta por CPV (`_z_valor`): sem MAD não há σ e o contrato passa a
  ser «normal» em vez de virar o mais anómalo de todos (era o bug clássico);
- a deteção de NIF vs nome (um NIF pesquisado como nome devolve zero);
- o nome curto para notícias («Cimontubo - Tubagens, Lda» → «cimontubo»);
- as degradações sem Elasticsearch e os erros de parâmetro.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api import padroes_service as padroes  # noqa: E402


def _linha(**extra):
    """Contrato mínimo, na forma que `_row_from_hit` devolve."""
    base = {
        "id": "x",
        "ano": 2024,
        "valor": 50_000.0,
        "base": 50_000.0,
        "efetivo": 50_000.0,
        "ratio_base": 1.0,
        "ratio_efetivo": 1.0,
        "ajuste_direto": False,
        "cpv": "45231300-8",
        "cpv_grupo": "45",
        "cpv_desc": "Construção de condutas",
        "procedimento": "Concurso público",
        "adjudicante_nif": "500000001",
        "adjudicante_nome": "Município A",
        "adjudicatarios": [{"nif": "503439800", "nome": "ACME, Lda"}],
    }
    base.update(extra)
    return base


# ---------------------------------------------------------------------------
# Agregação do portefólio
# ---------------------------------------------------------------------------
def test_agregar_anos_cpv_e_procedimentos() -> None:
    rows = [
        _linha(ano=2023, valor=10_000.0),
        _linha(ano=2023, valor=90_000.0, ajuste_direto=True, procedimento="Ajuste direto"),
        _linha(ano=2024, valor=1_500_000.0, cpv_grupo="31", cpv_desc="Equipamento elétrico"),
    ]
    saida = padroes._agregar(rows)

    assert saida["valor_total"] == pytest.approx(1_600_000.0)
    assert saida["valor_mediano"] == pytest.approx(90_000.0)
    assert [item["ano"] for item in saida["por_ano"]] == [2023, 2024]
    assert saida["por_ano"][0]["contratos"] == 2
    assert saida["por_ano"][0]["valor"] == pytest.approx(100_000.0)

    assert saida["escaloes"] == {"<10k": 0, "10k-100k": 2, "100k-1M": 0, ">1M": 1}
    primeiro = saida["por_cpv"][0]
    assert primeiro["cpv"] == "31"  # ordenado pelo valor, não pela contagem
    cpv45 = next(item for item in saida["por_cpv"] if item["cpv"] == "45")
    assert cpv45["contratos"] == 2
    assert cpv45["taxa_ajuste_direto"] == pytest.approx(0.5)
    assert cpv45["desvio_mediano"] == pytest.approx(1.0)

    procedimentos = {item["procedimento"]: item for item in saida["por_procedimento"]}
    assert procedimentos["Ajuste direto"]["contratos"] == 1


def test_agregar_aditivos_e_concentracao() -> None:
    rows = [
        _linha(ratio_efetivo=1.30),  # aditivo de 30%
        _linha(ratio_efetivo=1.10),
        _linha(ratio_efetivo=None),
        _linha(valor=100_000.0, adjudicante_nif="500000002", adjudicante_nome="Município B"),
    ]
    saida = padroes._agregar(rows)
    grupo = saida["por_cpv"][0]
    assert grupo["aditivos"] == 1
    assert grupo["taxa_aditivo"] == pytest.approx(0.25)
    # A concentração é a parte do valor do maior adjudicante: 150k de 250k.
    assert saida["concentracao_adjudicante"] == pytest.approx(0.6)
    assert [item["nome"] for item in saida["adjudicantes"]] == ["Município A", "Município B"]


def test_agregar_sem_contratos_nao_rebenta() -> None:
    saida = padroes._agregar([])
    assert saida["valor_total"] == 0.0
    assert saida["valor_mediano"] is None
    assert saida["concentracao_adjudicante"] is None
    assert saida["por_ano"] == []


def test_agregar_usa_adjudicante_nif_quando_falta_o_nome() -> None:
    saida = padroes._agregar([_linha(adjudicante_nome=None), _linha(adjudicante_nome="Município A")])
    assert len(saida["adjudicantes"]) == 1
    assert saida["adjudicantes"][0]["nif"] == "500000001"


# ---------------------------------------------------------------------------
# Régua robusta por CPV
# ---------------------------------------------------------------------------
def test_z_valor_sem_regua_e_zero() -> None:
    assert padroes._z_valor(10_000.0, None) == 0.0
    assert padroes._z_valor(None, {"mediana_log_valor": 4.0, "mad_log_valor": 0.5}) == 0.0
    assert padroes._z_valor(0.0, {"mediana_log_valor": 4.0, "mad_log_valor": 0.5}) == 0.0


def test_z_valor_mad_zero_nao_divide_por_zero() -> None:
    # Com MAD = 0 a escala é 0: devolver 0 é a resposta segura (não há dispersão
    # medida neste CPV) — devolver infinito punha o contrato no topo da lista.
    assert padroes._z_valor(1_000_000.0, {"mediana_log_valor": 3.0, "mad_log_valor": 0.0}) == 0.0


def test_z_valor_usa_escala_robusta() -> None:
    regua = {"mediana_log_valor": 4.0, "mad_log_valor": 0.5}  # escala = 0.7413
    assert padroes._z_valor(10_000.0, regua) == pytest.approx(0.0, abs=1e-6)
    assert padroes._z_valor(100_000.0, regua) == pytest.approx(1 / (1.4826 * 0.5), rel=1e-6)
    # Simétrico: muito abaixo da mediana dá o mesmo σ de muito acima.
    assert padroes._z_valor(100.0, regua) == padroes._z_valor(1_000_000.0, regua)


# ---------------------------------------------------------------------------
# NIF vs nome
# ---------------------------------------------------------------------------
def test_nif_puro_reconhece_nif_portugues() -> None:
    assert padroes._nif_puro("503439800", padroes.PT) == "503439800"
    assert padroes._nif_puro("503 439 800", padroes.PT) == "503439800"
    assert padroes._nif_puro("50343980", padroes.PT) == "50343980"
    # Nome de empresa não é NIF (mesmo com dígitos dentro).
    assert padroes._nif_puro("PSG 508170710", padroes.PT) is None
    assert padroes._nif_puro("cimontubo", padroes.PT) is None
    assert padroes._nif_puro("12345", padroes.PT) is None
    assert padroes._nif_puro("", padroes.PT) is None


def test_nif_puro_reconhece_cif_espanhol_em_maiusculas() -> None:
    assert padroes._nif_puro("a28791069", padroes.ES) == "A28791069"
    assert padroes._nif_puro("A28791069", padroes.ES) == "A28791069"
    assert padroes._nif_puro("kone ascensores", padroes.ES) is None


def test_nome_curto_para_noticias() -> None:
    assert padroes._nome_curto("Cimontubo - Tubagens E Soldadura, Lda") == "cimontubo tubagens"
    assert padroes._nome_curto("PSG-Segurança Privada, S.A.") == "psg seguranca"
    assert padroes._nome_curto("Lda, S.A.") is None
    assert padroes._nome_curto("") is None
    # «Portugal» e os sufixos societários não ajudam a encontrar a empresa.
    assert padroes._nome_curto("Kone Portugal, Lda") == "kone"


# ---------------------------------------------------------------------------
# Resolução e análise sem Elasticsearch
# ---------------------------------------------------------------------------
def test_empresa_query_pt_e_nested() -> None:
    assert padroes._empresa_query(padroes.PT, "503439800") == {
        "nested": {"path": "adjudicatarios.parsed", "query": {"term": {"adjudicatarios.parsed.nif": "503439800"}}}
    }


def test_empresa_query_es_ignora_maiusculas() -> None:
    # No PLACSP o mesmo NIF aparece como `A28791069` e `a28791069`.
    condicao = padroes._empresa_query(padroes.ES, "A28791069")
    assert condicao["wildcard"]["adjudicatario_nif"]["case_insensitive"] is True


def test_resolver_empresa_sem_es(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(padroes, "get_es_client", lambda *args, **kwargs: None)
    assert padroes.resolver_empresa("cimontubo")["error"] == "Elasticsearch indisponível"


def test_resolver_empresa_pais_desconhecido() -> None:
    resposta = padroes.resolver_empresa("cimontubo", pais="XX")
    assert "país desconhecido" in resposta["error"]
    assert resposta["paises"] == ["PT", "ES"]


def test_analise_empresa_pais_desconhecido() -> None:
    resposta = padroes.analise_empresa(nome="cimontubo", pais="FR")
    assert "país desconhecido" in resposta["error"]


def test_analise_empresa_sem_es(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(padroes, "get_es_client", lambda *args, **kwargs: None)
    assert padroes.analise_empresa(nif="503439800")["error"] == "Elasticsearch indisponível"


def test_analise_empresa_pesquisa_vazia_nao_consulta(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeClient:
        pass

    monkeypatch.setattr(padroes, "get_es_client", lambda *args, **kwargs: _FakeClient())
    # Sem `nif` nem `nome` útil, a resolução falha antes de tocar nos índices.
    assert padroes.analise_empresa(nome="", pais="PT")["error"] == "pesquisa vazia"


def test_top_hit_name_le_nome_aninhado() -> None:
    agregado = {"hits": {"hits": [{"_source": {"adjudicatarios": {"parsed": {"nome": "ACME, Lda"}}}}]}}
    assert padroes._top_hit_name(agregado) == "ACME, Lda"
    assert padroes._top_hit_name({"hits": {"hits": [{"_source": {"outro": "x"}}]}}) is None
    assert padroes._top_hit_name(None) is None


def test_clear_cache_inclui_analises_de_empresa() -> None:
    padroes._emp_cache_put(("PT", "503439800", None, None, 400, 250), {"nome": "ACME"})
    assert padroes._emp_cache_get(("PT", "503439800", None, None, 400, 250)) == {"nome": "ACME"}
    padroes.clear_cache()
    assert padroes._emp_cache_get(("PT", "503439800", None, None, 400, 250)) is None


# ---------------------------------------------------------------------------
# Rotas
# ---------------------------------------------------------------------------
def test_rotas_de_empresa_registadas() -> None:
    from api import padroes_routes  # noqa: PLC0415

    caminhos = {route.path for route in padroes_routes.router.routes}
    assert {"/padroes/empresas/sugestoes", "/padroes/empresas/analise"} <= caminhos
