"""Testes do módulo de inteligência de mercado (CPV × CAE × contratos) — puros.

Cobrem os indicadores (P_i, D_i, evolução), a tabela CPV↔CAE, os cenários do
World Model, a simulação de concorrência (Monte Carlo) e a leitura das
agregações com cliente Elasticsearch falso. Não há `pytest-asyncio`: tudo síncrono.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api import lorenz_service as lz  # noqa: E402
from api import mercado_service as mk  # noqa: E402


# --------------------------------------------------------------------------- #
# Cliente Elasticsearch falso (filas por tipo de pedido)
# --------------------------------------------------------------------------- #
class _ClienteFalso:
    def __init__(self, buscas=None, mrespostas=None, total=0):
        self._buscas = list(buscas or [])
        self._mrespostas = list(mrespostas or [])
        self._total = total
        self.pedidos: list = []
        self.mpedidos: list = []
        self.indices = self

    def get_mapping(self, index=None):  # noqa: A002
        return {"contratos": {"mappings": {"properties": {}}}}

    def exists(self, index=None):  # noqa: A002
        return True

    def create(self, **kwargs):
        return {"acknowledged": True}

    def search(self, **kwargs):
        self.pedidos.append(kwargs.get("body"))
        if not self._buscas:
            return {"hits": {"total": {"value": 0}, "hits": []}, "aggregations": {}}
        resposta = self._buscas.pop(0)
        if isinstance(resposta, Exception):
            raise resposta
        return resposta

    def msearch(self, body=None):
        self.mpedidos.append(body)
        if not self._mrespostas:
            return {"responses": []}
        resposta = self._mrespostas.pop(0)
        if isinstance(resposta, Exception):
            raise resposta
        return resposta

    def count(self, **kwargs):
        return {"count": self._total}

    def index(self, **kwargs):
        self.pedidos.append(kwargs)
        return {"result": "created"}

    def get(self, **kwargs):
        return {"_source": {"run_id": kwargs.get("id")}}


def _escopo() -> dict:
    return mk.lz.escopo(area="saude", ano_de=2023, ano_ate=2025)


def _resposta_empresa(valor: float, entidades: list, cpvs: list, anos: list, contratos: int = 10, nome: str = "Empresa") -> dict:
    """Resposta de `metricas_empresas` com a forma real do Elasticsearch."""
    return {
        "hits": {"total": {"value": contratos}},
        "aggregations": {
            "eu": {"nested": {}, "proprio": {"doc_count": contratos, "nome": {"hits": {"hits": [{"_source": {"nif": "x", "nome": nome}}]}}}},
            "valor": {"value": valor},
            "valor_efetivo": {"value": valor * 0.9},
            "percentis": {"values": {"50.0": valor / max(contratos, 1), "90.0": valor / 3}},
            "entidades": {
                "distintas": {"value": len(entidades)},
                "por_nif": {
                    "buckets": [
                        {
                            "key": nif,
                            "doc_count": 3,
                            "nome": {"hits": {"hits": [{"_source": {"nif": nif, "nome": nome}}]}},
                            "documento": {"valor": {"value": valor_entidade}},
                        }
                        for nif, nome, valor_entidade in entidades
                    ]
                },
            },
            "cpvs": {
                "por_codigo": {
                    "buckets": [
                        {"key": codigo, "doc_count": 4, "documento": {"valor": {"value": valor_cpv}}}
                        for codigo, valor_cpv in cpvs
                    ]
                }
            },
            "anos": {
                "buckets": [
                    {"key": ano, "doc_count": 3, "valor": {"value": valor_ano}} for ano, valor_ano in anos
                ]
            },
            "procedimentos": {"buckets": [{"key": "Ajuste Direto Regime Geral", "doc_count": 5}, {"key": "Concurso público", "doc_count": 5}]},
        },
    }


def _resposta_entidades(nifs: list) -> dict:
    """Resposta da consulta a `finance_entities` (CAE)."""
    return {
        "hits": {
            "total": {"value": len(nifs)},
            "hits": [
                {
                    "_id": nif,
                    "_source": {"nif": nif, "name": nome, "cae_principal": cae, "caes_secundarios": secundarios, "concelho": "Lisboa"},
                }
                for nif, nome, cae, secundarios in nifs
            ],
        }
    }


# --------------------------------------------------------------------------- #
# 1. Compatibilidade CPV ↔ CAE
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "cae,cpv,grau",
    [
        ("21200", "33600000-6", "alta"),      # fabricação de farmacêuticos
        ("46460", "33600000-6", "alta"),      # comércio por grosso de farmacêuticos
        ("32500", "33141000-0", "alta"),      # dispositivos médicos
        ("62010", "72000000-5", "alta"),      # TI
        ("41200", "45200000-9", "alta"),      # construção de edifícios
        ("86101", "85110000-3", "alta"),      # atividades de saúde
        ("47730", "33600000-6", "média"),     # farmácias (retalho)
        ("47110", "33600000-6", "baixa"),     # retalho genérico
        ("41200", "33600000-6", "desconhecida"),  # sem regra para o par
        ("99999", "99999999-9", "desconhecida"),
    ],
)
def test_compatibilidade_graus(cae, cpv, grau):
    assert mk.compatibilidade(cae, cpv)["grau"] == grau


def test_compatibilidade_sem_cae_nao_inventa_atividade():
    resultado = mk.compatibilidade(None, "33600000-6")
    assert resultado["grau"] == "desconhecida"
    assert resultado["score"] == 0.0
    assert "sem CAE" in resultado["motivo"]


def test_compatibilidade_usa_a_regra_mais_especifica():
    # 46460 casa a regra de 4 dígitos (4646) e a de 2 dígitos (46): fica a melhor
    resultado = mk.compatibilidade("46460", "33600000-6")
    assert resultado["regra"]["cae"] == "4646"
    assert resultado["grau"] == "alta"


def test_compatibilidade_empresa_escolhe_o_melhor_cae():
    resultado = mk.compatibilidade_empresa(["41200", "46460"], "33600000-6")
    assert resultado["grau"] == "alta"
    assert resultado["cae"] == "46460"


def test_compatibilidade_empresa_sem_caes():
    resultado = mk.compatibilidade_empresa([], "33600000-6")
    assert resultado["grau"] == "desconhecida"
    assert resultado["cae"] is None


def test_guardar_tabela_limpa_regras_invalidas(tmp_path, monkeypatch):
    monkeypatch.setattr(mk, "CONFIG_PATH", tmp_path / "cae_cpv.json")
    monkeypatch.setattr(mk, "_config_cache", {"mtime": None, "dados": None})
    resultado = mk.guardar_tabela(
        [
            {"cae": "9999", "cpv": "336", "grau": "alta", "nota": "teste"},
            {"cae": "abc", "cpv": "336", "grau": "alta"},       # CAE inválido
            {"cae": "8888", "cpv": "336", "grau": "altíssimo"},  # grau inválido
        ]
    )
    assert resultado["ok"] is True
    assert [regra["cae"] for regra in resultado["cae_cpv"]] == ["9999"]
    assert mk.compatibilidade("999912", "33600000-6")["grau"] == "alta"
    # tabela vazia volta às predefinições
    reposto = mk.guardar_tabela([{"cae": "x", "cpv": "y", "grau": "nada"}])
    assert len(reposto["cae_cpv"]) == len(mk.CAE_CPV_DEFAULT)


# --------------------------------------------------------------------------- #
# 2. Indicadores
# --------------------------------------------------------------------------- #
def test_indice_posicionamento():
    assert mk.indice_posicionamento(12e6, 23e6) == pytest.approx(12 / 23)
    assert mk.indice_posicionamento(5.0, 0.0) == 0.0          # mercado sem valor
    assert mk.indice_posicionamento(100.0, 50.0) == 1.0       # nunca acima de 1


def test_indice_dependencia_exemplo_do_modelo():
    # Carteira da «Empresa A» do exemplo: maior entidade com 70 % do valor
    resultado = mk.indice_dependencia([8.4e6, 2.4e6, 1.2e6])
    assert resultado["maior_quota"] == pytest.approx(0.7)
    assert resultado["n_entidades"] == 3
    assert resultado["hhi"] == pytest.approx(0.7**2 + 0.2**2 + 0.1**2)
    assert 0 < resultado["hhi_normalizado"] < 1


def test_indice_dependencia_casos_limite():
    um = mk.indice_dependencia([100.0])
    assert um["hhi"] == 1.0 and um["hhi_normalizado"] == 1.0
    vazio = mk.indice_dependencia([])
    assert vazio["hhi"] == 0.0 and vazio["n_entidades"] == 0


def test_evolucao_anual_cagr_e_variacao():
    resultado = mk.evolucao_anual([(2023, 100.0), (2024, 115.0), (2025, 132.25)])
    assert resultado["variacao"] == pytest.approx(0.3225)
    assert resultado["cagr"] == pytest.approx(0.15)
    assert resultado["n_anos"] == 3
    assert resultado["declive"] > 0


def test_evolucao_anual_serie_curta_e_queda():
    curta = mk.evolucao_anual([(2025, 100.0)])
    assert curta["variacao"] is None and curta["cagr"] is None
    queda = mk.evolucao_anual([(2023, 100.0), (2024, 90.0), (2025, 80.0)])
    assert queda["variacao"] < 0 and queda["cagr"] < 0 and queda["declive"] < 0


# --------------------------------------------------------------------------- #
# 3. Simulação de concorrência (Monte Carlo)
# --------------------------------------------------------------------------- #
def test_monte_carlo_proporcional_e_reprodutivel():
    forcas = {"A": 3.0, "B": 1.0}
    resultado = mk._cotas_monte_carlo(forcas, concursos=20000, semente=7)
    assert resultado["A"]["quota"] == pytest.approx(0.75, abs=0.02)
    assert resultado["B"]["quota"] == pytest.approx(0.25, abs=0.02)
    assert sum(item["quota"] for item in resultado.values()) == pytest.approx(1.0, abs=1e-9)
    # mesma semente ⇒ mesmo resultado
    repetido = mk._cotas_monte_carlo(forcas, concursos=20000, semente=7)
    assert repetido["A"]["vitorias"] == resultado["A"]["vitorias"]


def test_monte_carlo_sem_forca():
    assert mk._cotas_monte_carlo({}, concursos=100, semente=1) == {}
    assert mk._cotas_monte_carlo({"A": 0.0}, concursos=100, semente=1) == {}


def test_cenario_perda_maior_comprador_calcula_residual():
    metrica = {
        "nif": "1",
        "valor": 1_000_000.0,
        "entidades": [
            {"nif": "E1", "nome": "Maior", "valor": 700_000.0, "quota": 0.7, "contratos": 5},
            {"nif": "E2", "nome": "Segundo", "valor": 300_000.0, "quota": 0.3, "contratos": 2},
        ],
    }
    resultado = mk.cenario_perda_maior_comprador(metrica)
    assert resultado["disponivel"] is True
    assert resultado["medicao"]["valor_perdido"] == pytest.approx(700_000.0)
    assert resultado["medicao"]["quota_do_valor"] == pytest.approx(0.7)
    assert resultado["medicao"]["valor_residual"] == pytest.approx(300_000.0)
    assert resultado["medicao"]["variacao_valor"] == pytest.approx(-0.7)
    assert resultado["medicao"]["dependencia_depois"]["hhi"] == pytest.approx(1.0)  # fica um só comprador


def test_cenario_perda_sem_compradores():
    resultado = mk.cenario_perda_maior_comprador({"nif": "1", "valor": 0.0, "entidades": []})
    assert resultado["disponivel"] is False


# --------------------------------------------------------------------------- #
# 4. Cenários com cliente falso
# --------------------------------------------------------------------------- #
def _resposta_topo_empresas(empresas: list) -> dict:
    """Resposta de `_topo_por_papel` (topo de adjudicatárias do escopo)."""
    return {
        "hits": {"total": {"value": len(empresas)}},
        "aggregations": {
            "partes": {
                "por_nif": {
                    "buckets": [
                        {
                            "key": nif,
                            "doc_count": 5,
                            "nome": {"hits": {"hits": [{"_source": {"nif": nif, "nome": nome}}]}},
                            "documento": {"valor": {"value": valor}},
                        }
                        for nif, nome, valor in empresas
                    ]
                }
            }
        },
    }


def test_cenario_novo_concorrente_reduz_quotas(monkeypatch):
    escopo = _escopo()
    cliente = _ClienteFalso(
        buscas=[
            _resposta_topo_empresas([("1", "Alfa", 1_000_000.0), ("2", "Beta", 500_000.0)]),
            _resposta_entidades([("1", "Alfa", "46460", []), ("2", "Beta", "21200", [])]),
        ],
        mrespostas=[
            {
                "responses": [
                    _resposta_empresa(1_000_000.0, [("E1", "Hospital", 1_000_000.0)], [("33600000-6", 1_000_000.0)], [(2024, 1_000_000.0)], nome="Alfa"),
                    _resposta_empresa(500_000.0, [("E1", "Hospital", 500_000.0)], [("33600000-6", 500_000.0)], [(2024, 500_000.0)], nome="Beta"),
                ]
            }
        ],
    )
    monkeypatch.setattr(lz, "get_es_client", lambda *a, **k: cliente)
    monkeypatch.setattr(mk, "parametros", lambda: {**mk.PARAMETROS_DEFAULT, "concursos_simulados": 4000})

    resultado = mk.cenario_novo_concorrente(escopo, forca_relativa=1.0)
    assert resultado["disponivel"] is True
    medicao = resultado["medicao"]
    assert medicao["quota_estimada_do_entrante"] > 0
    assert medicao["forca_mediana_do_mercado"] > 0
    assert medicao["hhi_antes"] > medicao["hhi_simulado"]  # a entrada reparte o mercado
    assert all(linha["variacao"] <= 0 for linha in medicao["empresas"])
    assert medicao["empresas"][0]["nome"] == "Alfa"  # nome próprio da empresa (não do comprador)


def test_cenario_contratos_a_expirar_calcula_em_python(monkeypatch):
    escopo = _escopo()
    hoje = mk.datetime.now(mk.timezone.utc).date()

    def _iso(dias: int) -> str:
        return (hoje + mk.timedelta(days=dias)).isoformat()

    # Três contratos: um com fim explícito na janela, um estimado (celebração + prazo),
    # e um fora da janela pelo prazo.
    resposta = {
        "hits": {
            "total": {"value": 3},
            "hits": [
                {
                    "_id": "c1",
                    "_source": {
                        "idcontrato": "c1",
                        "objectoContrato": "Medicamentos",
                        "precoContratual": 700_000.0,
                        "dataCelebracaoContrato": "2024-01-15",
                        "dataFechoContrato": _iso(30),
                        "prazoExecucao": 365,
                        "adjudicantes": {"parsed": [{"nif": "E1", "nome": "Hospital"}]},
                        "adjudicatarios": {"parsed": [{"nif": "1", "nome": "Alfa"}]},
                    },
                },
                {
                    "_id": "c2",
                    "_source": {
                        "idcontrato": "c2",
                        "objectoContrato": "Equipamento",
                        "precoContratual": 300_000.0,
                        "dataCelebracaoContrato": _iso(-200),
                        "prazoExecucao": 365,
                        "adjudicantes": {"parsed": [{"nif": "E2", "nome": "ULS Sul"}]},
                        "adjudicatarios": {"parsed": [{"nif": "2", "nome": "Beta"}]},
                    },
                },
                {
                    "_id": "c3",
                    "_source": {
                        "idcontrato": "c3",
                        "objectoContrato": "Serviços",
                        "precoContratual": 100_000.0,
                        "dataCelebracaoContrato": _iso(-3000),
                        "prazoExecucao": 365,
                        "adjudicantes": {"parsed": [{"nif": "E1", "nome": "Hospital"}]},
                        "adjudicatarios": {"parsed": [{"nif": "1", "nome": "Alfa"}]},
                    },
                },
                {
                    "_id": "c4",
                    "_source": {
                        "idcontrato": "c4",
                        "objectoContrato": "Sem prazo plausível",
                        "precoContratual": 50_000.0,
                        "dataCelebracaoContrato": _iso(-10),
                        "prazoExecucao": 9_000_000,
                        "adjudicatarios": {"parsed": [{"nif": "2", "nome": "Beta"}]},
                    },
                },
            ],
        },
        "aggregations": {"valor": {"value": 1_150_000.0}},
    }
    cliente = _ClienteFalso(buscas=[resposta, resposta])
    monkeypatch.setattr(lz, "get_es_client", lambda *a, **k: cliente)
    resultado = mk.cenario_contratos_a_expirar(escopo, horizonte_dias=180, es=cliente)
    assert resultado["disponivel"] is True
    medicao = resultado["medicao"]
    estrito, estimado = medicao["estrito"], medicao["estimado"]

    # estrito: só o contrato com data de fecho explícita dentro da janela
    assert estrito["campo"] == "dataFechoContrato"
    assert estrito["contratos"] == 1
    assert estrito["valor"] == pytest.approx(700_000.0)
    assert estrito["empresas"][0]["nome"] == "Alfa"
    assert estrito["entidades"][0]["nome"] == "Hospital"
    assert estrito["evidencia"][0]["idcontrato"] == "c1"

    # estimado: só o contrato sem fim explícito cujo fim cai na janela (c2)
    assert estimado["campo"] == "dataCelebracaoContrato+prazoExecucao"
    assert estimado["contratos"] == 1
    assert estimado["valor"] == pytest.approx(300_000.0)
    assert estimado["evidencia"][0]["fim_calculado"] == _iso(165)
    assert estimado["amostra"]["prazos_ignorados"] == 1  # c4 (prazo absurdo)
    assert estimado["amostra"]["cobertura_valor"] == pytest.approx(1_150_000.0 / 1_150_000.0)
    assert medicao["valor_exposto"] == pytest.approx(1_000_000.0)
    assert medicao["janela"]["de"] == hoje.isoformat()
    assert any("dataFechoContrato" in filtro.get("range", {}) for filtro in cliente.pedidos[0]["query"]["bool"]["filter"])
    assert any("dataCelebracaoContrato" in filtro.get("range", {}) for filtro in cliente.pedidos[1]["query"]["bool"]["filter"])


def test_dias_para_data_tolera_datas_invalidas():
    assert mk._dias_para_data("2026-01-01", 10) == "2026-01-11"
    assert mk._dias_para_data("2026-01-01", 0) is None
    assert mk._dias_para_data("data má", 10) is None
    assert mk._dias_para_data(None, 10) is None


def test_cenario_precos_aritmetica(monkeypatch):
    escopo = _escopo()
    cliente = _ClienteFalso(
        buscas=[
            _resposta_topo_empresas([("1", "Alfa", 1_000_000.0)]),
            _resposta_entidades([("1", "Alfa", "46460", [])]),
        ],
        mrespostas=[
            {
                "responses": [
                    _resposta_empresa(1_000_000.0, [("E1", "Hospital", 1_000_000.0)], [("33600000-6", 1_000_000.0)], [(2024, 1_000_000.0)], nome="Alfa")
                ]
            }
        ],
    )
    monkeypatch.setattr(lz, "get_es_client", lambda *a, **k: cliente)
    resultado = mk.cenario_precos(escopo, variacao=0.10)
    medicao = resultado["medicao"]
    assert medicao["valor_simulado"] == pytest.approx(1_100_000.0)
    assert medicao["delta_valor"] == pytest.approx(100_000.0)
    assert medicao["por_empresa"][0]["delta_valor"] == pytest.approx(100_000.0)


def test_cenario_diversificacao_baixa_a_concentracao(monkeypatch):
    escopo = _escopo()
    cliente = _ClienteFalso(
        buscas=[_resposta_entidades([("1", "Alfa", "46460", [])])],
        mrespostas=[
            {
                "responses": [
                    _resposta_empresa(1_000_000.0,
                        [("E1", "Maior", 900_000.0), ("E2", "Segundo", 100_000.0)],
                        [("33600000-6", 1_000_000.0)],
                        [(2024, 1_000_000.0)],
                        nome="Alfa",
                    )
                ]
            }
        ],
    )
    monkeypatch.setattr(lz, "get_es_client", lambda *a, **k: cliente)
    resultado = mk.cenario_diversificacao(escopo, nif="1")
    assert resultado["disponivel"] is True
    antes = resultado["medicao"]["dependencia_antes"]["hhi"]
    depois = resultado["medicao"]["dependencia_simulada"]["hhi"]
    assert antes > depois


def test_cenario_entidade_sem_fornecedor(monkeypatch):
    escopo = _escopo()
    classes = {
        "hits": {"total": {"value": 10}},
        "aggregations": {"cpvs": {"por_codigo": {"buckets": [{"key": "33600000-6", "doc_count": 10, "documento": {"valor": {"value": 1_000_000.0}}}]}}},
    }
    topo = {
        "hits": {"total": {"value": 3}},
        "aggregations": {
            "partes": {
                "por_nif": {
                    "buckets": [
                        {"key": "E1", "doc_count": 9, "nome": {"hits": {"hits": [{"_source": {"nif": "E1", "nome": "Hospital"}}]}}, "documento": {"valor": {"value": 1_000_000.0}}}
                    ]
                }
            }
        },
    }
    detalhe = {
        "hits": {"total": {"value": 9}},
        "aggregations": {
            "valor": {"value": 1_000_000.0},
            "contrapartes": {
                "por_nif": {
                    "buckets": [
                        {"key": "F1", "doc_count": 6, "nome": {"hits": {"hits": [{"_source": {"nif": "F1", "nome": "Dominante"}}]}}, "documento": {"valor": {"value": 700_000.0}}},
                        {"key": "F2", "doc_count": 3, "nome": {"hits": {"hits": [{"_source": {"nif": "F2", "nome": "Alternativa"}}]}}, "documento": {"valor": {"value": 300_000.0}}},
                    ]
                }
            },
            "cpvs": {"por_codigo": {"buckets": [{"key": "33600000-6", "doc_count": 9, "documento": {"valor": {"value": 1_000_000.0}}}]}},
            "procedimentos": {"buckets": [{"key": "Ajuste Direto", "doc_count": 9}]},
        },
    }
    classe = {
        "hits": {"total": {"value": 10}},
        "aggregations": {
            "valor": {"value": 1_000_000.0},
            "compradores": {"n": {"value": 1}},
            "fornecedores": {
                "por_nif": {
                    "buckets": [
                        {"key": "F1", "doc_count": 6, "nome": {"hits": {"hits": [{"_source": {"nif": "F1", "nome": "Dominante"}}]}}, "documento": {"valor": {"value": 700_000.0}}},
                        {"key": "F2", "doc_count": 4, "nome": {"hits": {"hits": [{"_source": {"nif": "F2", "nome": "Alternativa"}}]}}, "documento": {"valor": {"value": 300_000.0}}},
                    ]
                }
            },
        },
    }
    cliente = _ClienteFalso(buscas=[topo, classes], mrespostas=[{"responses": [detalhe]}, {"responses": [classe]}])
    monkeypatch.setattr(lz, "get_es_client", lambda *a, **k: cliente)
    resultado = mk.cenario_entidade_sem_fornecedor(escopo, entidade_nif="E1", fornecedor_nif="F1")
    assert resultado["disponivel"] is True
    medicao = resultado["medicao"]
    assert medicao["exposicao"] == pytest.approx(0.7)
    assert medicao["alternativas_no_escopo"][0]["nome"] == "Alternativa"
    assert medicao["cobertura_alternativa_3"] == pytest.approx(0.3)
    assert medicao["dificuldade_substituicao"] == pytest.approx(0.7)


# --------------------------------------------------------------------------- #
# 5. Mercados e benchmark
# --------------------------------------------------------------------------- #
def _resposta_cpv_classes() -> dict:
    return {
        "hits": {"total": {"value": 100}},
        "aggregations": {
            "cpvs": {
                "por_codigo": {
                    "buckets": [
                        {"key": "33600000-6", "doc_count": 60, "documento": {"valor": {"value": 6_000_000.0}}},
                        {"key": "33141000-0", "doc_count": 40, "documento": {"valor": {"value": 4_000_000.0}}},
                    ]
                }
            }
        },
    }


def test_mercados_junta_cae_e_mede_cobertura(monkeypatch):
    escopo = _escopo()
    principal = _resposta_cpv_classes()
    classe_336 = {
        "hits": {"total": {"value": 60}},
        "aggregations": {
            "valor": {"value": 6_000_000.0},
            "compradores": {"n": {"value": 5}},
            "fornecedores": {
                "por_nif": {
                    "buckets": [
                        {"key": "1", "doc_count": 30, "nome": {"hits": {"hits": [{"_source": {"nif": "1", "nome": "Alfa"}}]}}, "documento": {"valor": {"value": 4_000_000.0}}},
                        {"key": "2", "doc_count": 20, "nome": {"hits": {"hits": [{"_source": {"nif": "2", "nome": "Beta"}}]}}, "documento": {"valor": {"value": 2_000_000.0}}},
                    ]
                }
            },
        },
    }
    classe_331 = {
        "hits": {"total": {"value": 40}},
        "aggregations": {
            "valor": {"value": 4_000_000.0},
            "compradores": {"n": {"value": 4}},
            "fornecedores": {
                "por_nif": {
                    "buckets": [
                        {"key": "3", "doc_count": 25, "nome": {"hits": {"hits": [{"_source": {"nif": "3", "nome": "Gama"}}]}}, "documento": {"valor": {"value": 4_000_000.0}}},
                    ]
                }
            },
        },
    }
    cliente = _ClienteFalso(
        buscas=[principal, _resposta_entidades([("1", "Alfa", "46460", []), ("2", "Beta", "41200", [])])],
        mrespostas=[{"responses": [classe_336, classe_331]}],
    )
    monkeypatch.setattr(lz, "get_es_client", lambda *a, **k: cliente)
    dados = mk.mercados(escopo, top=2)
    assert len(dados["mercados"]) == 2
    mercado_336 = next(item for item in dados["mercados"] if item["cpv_classe"] == "3360")
    assert mercado_336["empresas_analisadas"] == 2
    assert mercado_336["empresas_com_cae"] == 2
    # Alfa (46460) é compatível; Beta (41200) não tem regra para 336
    assert mercado_336["empresas_compativeis"] == 1
    assert mercado_336["cobertura_cae"] == 1.0
    assert mercado_336["cobertura_valor_compativel"] == pytest.approx(4_000_000.0 / 6_000_000.0)
    assert mercado_336["caes_dominantes"][0]["cae"] == "46460"
    assert mercado_336["qualidade"]["grau"] == "limitada"  # poucas empresas


def test_mercados_sem_empresas_com_cae(monkeypatch):
    escopo = _escopo()
    classe = {
        "hits": {"total": {"value": 10}},
        "aggregations": {
            "valor": {"value": 1_000_000.0},
            "fornecedores": {"por_nif": {"buckets": [{"key": "9", "doc_count": 10, "nome": {"hits": {"hits": [{"_source": {"nif": "9", "nome": "Sem CAE"}}]}}, "documento": {"valor": {"value": 1_000_000.0}}}]}},
        },
    }
    cliente = _ClienteFalso(buscas=[_resposta_cpv_classes(), _resposta_entidades([])], mrespostas=[{"responses": [classe]}])
    monkeypatch.setattr(lz, "get_es_client", lambda *a, **k: cliente)
    dados = mk.mercados(escopo, top=1)
    mercado = dados["mercados"][0]
    assert mercado["cobertura_cae"] == 0.0
    assert mercado["empresas"][0]["compatibilidade"] == "desconhecida"
    assert mercado["empresas"][0]["caes"] == []


def test_benchmark_calcula_quota_dependencia_e_alertas(monkeypatch):
    escopo = _escopo()
    cliente = _ClienteFalso(
        buscas=[_resposta_entidades([("1", "Alfa S.A.", "46460", ["21200"]), ("2", "Beta Lda.", None, [])])],
        mrespostas=[
            {
                "responses": [
                    # Alfa: 1 M€, dependente (900 k num só comprador), 2 anos, crescimento
                    _resposta_empresa(1_000_000.0, [("E1", "Hospital", 900_000.0), ("E2", "ULS Norte", 100_000.0)], [("33600000-6", 1_000_000.0)], [(2024, 400_000.0), (2025, 600_000.0)], nome="Alfa S.A."),
                    # Beta: 500 k€, dispersa, queda de atividade
                    _resposta_empresa(500_000.0, [("E1", "Hospital Central", 250_000.0), ("E3", "ULS Sul", 250_000.0)], [("33600000-6", 500_000.0)], [(2024, 400_000.0), (2025, 100_000.0)], nome="Beta Lda."),
                ]
            }
        ],
    )
    monkeypatch.setattr(lz, "get_es_client", lambda *a, **k: cliente)
    dados = mk.benchmark(escopo, nifs=["1", "2"], cpv="336", es=cliente)
    assert [empresa["nif"] for empresa in dados["empresas"]] == ["1", "2"]
    alfa, beta = dados["empresas"]

    assert alfa["nome"] == "Alfa S.A."
    assert dados["mercado"]["valor"] == pytest.approx(1_500_000.0)
    assert alfa["quota"] == pytest.approx(2 / 3)
    assert beta["quota"] == pytest.approx(1 / 3)
    assert alfa["dependencia"]["maior_quota"] == pytest.approx(0.9)
    assert alfa["cae_principal"] == "46460"
    assert alfa["compatibilidade"] == "alta"
    assert alfa["posicao"] == 1
    assert any(alerta["tipo"] == "dependencia_de_comprador" for alerta in alfa["alertas"])
    assert any(alerta["tipo"] == "cae_desconhecido" for alerta in beta["alertas"])
    assert any(alerta["tipo"] == "queda_de_atividade" for alerta in beta["alertas"])
    assert alfa["evolucao"]["variacao"] == pytest.approx(0.5)
    assert sum(empresa["quota"] for empresa in dados["empresas"]) <= 1.0
    assert dados["avisos"]  # cobertura de CAE parcial e/ou mercado pequeno
    assert dados["mercado"]["cobertura_cae"] == pytest.approx(0.5)


def test_benchmark_sem_empresas(monkeypatch):
    escopo = _escopo()
    cliente = _ClienteFalso(buscas=[{"hits": {"total": {"value": 0}}, "aggregations": {"partes": {"por_nif": {"buckets": []}}}}])
    monkeypatch.setattr(lz, "get_es_client", lambda *a, **k: cliente)
    dados = mk.benchmark(escopo, es=cliente)
    assert dados["erro"] and dados["empresas"] == []


def test_label_cae_tolera_catalogo_ausente(monkeypatch):
    """Sem o catálogo CAE (não entra na imagem: chega por volume), a medição continua."""

    def _explodir(codigo):
        raise FileNotFoundError("CAE-Rev.4.md não encontrado em data/docs")

    monkeypatch.setattr(mk, "label_for_cae", _explodir)
    assert mk._label_cae("46460") is None
    assert mk._label_cae(None) is None
    assert mk._label_cae("") is None

    cliente = _ClienteFalso(buscas=[_resposta_entidades([("1", "Alfa S.A.", "46460", [])])])
    monkeypatch.setattr(lz, "get_es_client", lambda *a, **k: cliente)
    registos = mk.cae_por_nif(["1"], es=cliente)
    assert registos["1"]["cae_principal"] == "46460"
    assert registos["1"]["cae_principal_label"] is None


def test_dependencias_reciprocas(monkeypatch):
    escopo = _escopo()
    detalhe = {
        "hits": {"total": {"value": 9}},
        "aggregations": {
            "valor": {"value": 1_000_000.0},
            "contrapartes": {
                "por_nif": {
                    "buckets": [
                        {"key": "F1", "doc_count": 7, "nome": {"hits": {"hits": [{"_source": {"nif": "F1", "nome": "Dominante"}}]}}, "documento": {"valor": {"value": 800_000.0}}},
                        {"key": "F2", "doc_count": 2, "nome": {"hits": {"hits": [{"_source": {"nif": "F2", "nome": "Outro"}}]}}, "documento": {"valor": {"value": 200_000.0}}},
                    ]
                }
            },
            "cpvs": {"por_codigo": {"buckets": [{"key": "33600000-6", "doc_count": 9, "documento": {"valor": {"value": 1_000_000.0}}}]}},
            "procedimentos": {"buckets": [{"key": "Ajuste Direto", "doc_count": 9}]},
        },
    }
    # O `topo` identifica o **comprador** (Hospital, E1) — é ele que entra nas entidades.
    topo = {
        "hits": {"total": {"value": 2}},
        "aggregations": {
            "partes": {
                "por_nif": {
                    "buckets": [
                        {"key": "E1", "doc_count": 9, "nome": {"hits": {"hits": [{"_source": {"nif": "E1", "nome": "Hospital"}}]}}, "documento": {"valor": {"value": 1_000_000.0}}}
                    ]
                }
            }
        },
    }
    cliente = _ClienteFalso(
        # `dependencias()` não lê o registo: só as métricas e o cruzamento (topo + detalhe).
        buscas=[topo],
        mrespostas=[
            {"responses": [_resposta_empresa(1_000_000.0, [("E1", "Hospital", 1_000_000.0)], [("33600000-6", 1_000_000.0)], [(2025, 1_000_000.0)], nome="Alfa")]},
            {"responses": [detalhe]},
        ],
    )
    monkeypatch.setattr(lz, "get_es_client", lambda *a, **k: cliente)
    dados = mk.dependencias(escopo, nifs=["1"], es=cliente)
    assert dados["empresas"][0]["nif"] == "1"
    assert dados["empresas"][0]["dependencia"]["maior_quota"] == pytest.approx(1.0)
    entidade = dados["entidades"][0]
    assert entidade["nome"] == "Hospital"
    assert entidade["dependencia"]["maior_quota"] == pytest.approx(0.8)
    assert entidade["maior_fornecedor"]["nome"] == "Dominante"
    assert entidade["critico"] is True
    assert dados["totais"]["entidades_criticas"] == 1


# --------------------------------------------------------------------------- #
# 6. Grafo temporal, sensibilidade e meta
# --------------------------------------------------------------------------- #
def test_grafo_temporal_tem_os_cinco_tipos_de_no(monkeypatch):
    escopo = _escopo()
    contratos = {
        "hits": {
            "total": {"value": 2},
            "hits": [
                {
                    "_id": "c1",
                    "_source": {
                        "idcontrato": "c1",
                        "objectoContrato": "Medicamentos",
                        "precoContratual": 700_000.0,
                        "Ano": 2025,
                        "dataCelebracaoContrato": "2025-06-01",
                        "dataFechoContrato": "2026-06-01",
                        "cpv": [{"code": "33600000-6"}],
                        "adjudicantes": {"parsed": [{"nif": "E1", "nome": "Hospital"}]},
                        "adjudicatarios": {"parsed": [{"nif": "1", "nome": "Alfa"}]},
                    },
                }
            ],
        }
    }
    cliente = _ClienteFalso(
        buscas=[_resposta_entidades([("1", "Alfa", "46460", [])]), contratos],
        mrespostas=[
            {
                "responses": [
                    _resposta_empresa(1_000_000.0, [("E1", "Hospital", 700_000.0), ("E2", "ULS", 300_000.0)], [("33600000-6", 1_000_000.0)], [(2025, 1_000_000.0)], nome="Alfa")
                ]
            }
        ],
    )
    monkeypatch.setattr(lz, "get_es_client", lambda *a, **k: cliente)
    grafo = mk.grafo_temporal(escopo, nifs=["1"], contratos=1, es=cliente)
    dimensoes = {no["dimension"] for no in grafo["nodes"]}
    assert dimensoes == {"empresa", "contrato", "entidade", "cpv", "cae"}
    tipos_relacao = {aresta.get("relacao") for aresta in grafo["edges"]}
    assert {"atividade registada", "vende neste mercado", "contrata com", "adjudicado a", "comprado por"} <= tipos_relacao
    assert grafo["meta"]["tipos"] == ["empresa", "contrato", "entidade", "cpv", "cae"]
    # o nó de contrato traz as datas (o grafo é temporal)
    contrato = next(no for no in grafo["nodes"] if no["dimension"] == "contrato")
    assert contrato["data"] == "2025-06-01" and contrato["fim"] == "2026-06-01"


def test_sensibilidade_usa_a_matematica_do_lorenz(monkeypatch):
    escopo = _escopo()
    buckets = []
    for indice in range(4):
        buckets.append(
            {
                "key": 2022 + indice,
                "doc_count": 100 + indice,
                "valor": {"value": 1_000_000.0 * (indice + 1)},
                "valor_efetivo": {"value": 0.0},
                "percentis": {"values": {"50.0": 5_000.0, "95.0": 50_000.0, "99.0": 95_000.0 + indice}},
                "compradores": {"n": {"value": 10}},
                "fornecedores": {"n": {"value": 30 + indice}},
                "top_fornecedores": {"por_nif": {"buckets": [{"key": "F1", "doc_count": 5, "documento": {"valor": {"value": 300_000.0 * (indice + 1)}}}]}},
                "procedimentos": {"buckets": [{"key": "Ajuste Direto", "doc_count": 40}, {"key": "Concurso público", "doc_count": 60}]},
            }
        )
    cliente = _ClienteFalso(buscas=[{"hits": {"total": {"value": 400}}, "aggregations": {"periodos": {"buckets": buckets}}}])
    monkeypatch.setattr(lz, "get_es_client", lambda *a, **k: cliente)
    monkeypatch.setattr(lz, "parametros", lambda: {**lz.PARAMETROS_DEFAULT, "passos_lorenz": 400})
    dados = mk.sensibilidade(escopo, es=cliente)
    assert dados["disponivel"] is True
    assert dados["parametros"]["disponivel"] is True
    assert dados["parametros"]["sigma"] >= 6.0
    assert dados["mapa"]["disponivel"] is True
    assert "lambda_empirico" in dados["divergencia"]
    assert dados["lorenz"]["lyapunov"]["intervalos"] > 0
    assert len(dados["periodos"]) == 4  # cardinalidade fixa (4 buckets = 4 períodos)


def test_sensibilidade_serie_curta(monkeypatch):
    escopo = _escopo()
    cliente = _ClienteFalso(
        buscas=[
            {
                "hits": {"total": {"value": 100}},
                "aggregations": {
                    "periodos": {
                        "buckets": [
                            {"key": 2024, "doc_count": 10, "valor": {"value": 1.0}, "percentis": {"values": {}}, "compradores": {"n": {"value": 1}}, "fornecedores": {"n": {"value": 1}}, "top_fornecedores": {"por_nif": {"buckets": []}}, "procedimentos": {"buckets": []}}
                        ]
                    }
                },
            }
        ]
    )
    monkeypatch.setattr(lz, "get_es_client", lambda *a, **k: cliente)
    dados = mk.sensibilidade(escopo, es=cliente)
    assert dados["disponivel"] is False
    assert "curta" in dados["motivo"]


def test_meta_lista_camadas_indicadores_e_eventos():
    dados = mk.meta()
    assert [camada["camada"] for camada in dados["arquitetura"]] == ["ingestao", "grafo", "indicadores", "dinamica", "evidencia"]
    assert {item["id"] for item in dados["indicadores"]} >= {"posicionamento", "dependencia_empresa", "dependencia_entidade", "evolucao", "sensibilidade"}
    assert len(dados["eventos"]) == 6
    assert len(dados["tabela_cae_cpv"]) >= 30
    assert dados["indices"]["execucoes"] == "finance_mercado_runs"
    assert any("CAE" in limite for limite in dados["limites"])


def test_guardar_execucao_sem_elastico(monkeypatch):
    monkeypatch.setattr(lz, "get_es_client", lambda *a, **k: None)
    assert mk.guardar_execucao(_escopo(), {})["erro"]
    assert mk.listar_execucoes() == []
    assert mk.obter_execucao("x") is None
