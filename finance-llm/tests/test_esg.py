"""Testes do motor **ESG** — puros, sem Elasticsearch.

O que aqui se protege (é o que dá sentido ao número que a UI mostra):

- a normalização de indicadores nos dois sentidos (maior/menor é melhor);
- a **renormalização** pelos componentes com dados, a cobertura e a confiança;
- o **encolhimento** dos indicadores declarados quando há poucos;
- as features de contratos (compras ecológicas, CPV verde/carbónico/social,
  concentração, ajuste direto, concorrência);
- o cartão do modelo (pesos fecham em 1,0 por pilar), as faixas e a dimensão;
- a precedência da verificação externa nos indicadores;
- o benchmark (percentil/medianas) e a repartição do valor na carteira.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api import esg_service as esg  # noqa: E402
from api import esg_sources as tax  # noqa: E402
from api import esg_taxonomy as tax_eu  # noqa: E402


# ---------------------------------------------------------------------------
# Curvas, faixas e cartão
# ---------------------------------------------------------------------------
def test_normalize_nos_dois_sentidos() -> None:
    assert esg._normalize(0.0, 0.0, 0.25) == 0.0
    assert esg._normalize(0.25, 0.0, 0.25) == 100.0
    assert esg._normalize(1.0, 0.0, 0.25) == 100.0  # satura
    assert esg._normalize(-5.0, 0.0, 0.25) == 0.0
    # Menor é melhor: 180 dias → 0 pontos, 0 dias → 100.
    assert esg._normalize(180.0, 180.0, 0.0) == 0.0
    assert esg._normalize(0.0, 180.0, 0.0) == 100.0
    assert esg._normalize(90.0, 180.0, 0.0) == pytest.approx(50.0)
    assert esg._normalize(None, 0.0, 1.0) is None


def test_niveis_e_dimensoes() -> None:
    assert tax.nivel_de(None)["id"] == "sem_dados"
    assert tax.nivel_de(10)["id"] == "fraco"
    assert tax.nivel_de(35)["id"] == "inicial"
    assert tax.nivel_de(50)["id"] == "intermedio"
    assert tax.nivel_de(65)["id"] == "avancado"
    assert tax.nivel_de(90)["id"] == "lider"
    assert tax.nivel_de(500)["id"] == "lider"
    assert tax.dimensao_de(None)["id"] == "sem_dados"
    assert tax.dimensao_de(100_000)["id"] == "micro"
    assert tax.dimensao_de(1_000_000)["id"] == "pequena"
    assert tax.dimensao_de(5_000_000)["id"] == "media"
    assert tax.dimensao_de(50_000_000)["id"] == "grande"


def test_setor_de_cae() -> None:
    assert tax.setor_de_cae("42910")[0] == "F"
    assert tax.setor_de_cae("42.910")[0] == "F"
    assert tax.setor_de_cae("62010")[0] == "J"
    assert tax.setor_de_cae("86100")[0] == "Q"
    assert tax.setor_de_cae("") == ("", "")


def test_cartao_pesos_fecham_em_um_por_pilar() -> None:
    cartao = tax.cartao_modelo()
    assert cartao["versao"] == tax.MODELO_VERSAO
    assert cartao["aviso"]
    assert sum(pilar["peso"] for pilar in cartao["pilares"]) == pytest.approx(1.0)
    for pilar in cartao["pilares"]:
        assert pilar["componentes"]
        assert sum(item["peso"] for item in pilar["componentes"]) == pytest.approx(1.0), pilar["id"]
    ids = [item["codigo"] for item in cartao["indicadores"]]
    assert len(ids) == len(set(ids))
    for item in cartao["indicadores"]:
        assert item["pilar"] in {"e", "s", "g"}


# ---------------------------------------------------------------------------
# Pontuação
# ---------------------------------------------------------------------------
def test_avaliar_sem_dados_nao_inventa_score() -> None:
    payload = esg.avaliar({})
    assert payload["score"] is None
    assert payload["nivel"] is None
    assert payload["cobertura"] == 0.0
    assert payload["confianca"] == "sem dados"
    assert payload["componentes"] and all(not item["disponivel"] for item in payload["componentes"])
    assert payload["avisos"]


def test_avaliar_renormaliza_pelos_componentes_com_dados() -> None:
    features = {
        "contratos": 40,
        "valor_total": 1_000_000.0,
        "taxa_ecologicos": 0.60,
        "share_verde": 0.50,
        "share_marrom": 0.10,
        "exposicao_verde": 0.40,
        "share_servicos_ambientais": 0.30,
        "share_social": 0.20,
        "mediana_concorrentes": 4.0,
        "adjudicantes_distintos": 8,
        "dias_publicacao_mediana": 20.0,
        "taxa_ajuste_direto": 0.10,
        "concentracao_comprador": 0.40,
        "insolvencias": 0,
        "devedor": 0,
    }
    payload = esg.avaliar(features)
    assert payload["score"] is not None
    assert 0 < payload["cobertura"] < 1  # faltam os indicadores declarados
    assert payload["confianca"] in {"baixa", "média"}
    assert payload["pilares"]["e"] is not None
    assert payload["pilares"]["s"] is not None
    assert payload["pilares"]["g"] is not None
    compras = next(item for item in payload["componentes"] if item["id"] == "compras_ecologicas")
    assert compras["pontos"] == 100.0
    assert compras["evidencia"]
    assert next(item for item in payload["componentes"] if item["id"] == "indicadores_ambientais")["disponivel"] is False


def test_indicadores_declarados_encolhem_com_poucos_dados() -> None:
    poucos = esg.indicadores_score({"e_iso14001": 1, "e_energia_renovavel_pct": 100})
    muitos = esg.indicadores_score(
        {
            "e_iso14001": 1,
            "e_energia_renovavel_pct": 100,
            "e_emissoes_scope1": 0,
            "e_emissoes_scope2": 0,
            "e_residuos_valorizacao_pct": 100,
        }
    )
    assert poucos["e"]["score"] is not None and muitos["e"]["score"] is not None
    # Com dois indicadores perfeitos, o encolhimento puxa para 50; com cinco,
    # a evidência já sustenta um valor muito mais alto.
    assert poucos["e"]["score"] < muitos["e"]["score"]
    assert poucos["e"]["n"] == 2 and muitos["e"]["n"] == 5
    # Indicador de contexto (nº de trabalhadores) não pontua nem entra na média.
    contexto = esg.indicadores_score({"s_trabalhadores": 100})["s"]
    assert contexto["n"] == 0 and contexto["detalhes"] == []


def test_features_de_contratos() -> None:
    rows = [
        {"ano": 2025, "valor": 1000.0, "adjudicante_nif": "1", "adjudicante_nome": "A", "ajuste_direto": 0, "ecologico": True, "n_concorrentes": 5, "dias_publicacao": 10, "cpv": "90500000"},
        {"ano": 2025, "valor": 500.0, "adjudicante_nif": "2", "adjudicante_nome": "B", "ajuste_direto": 1, "ecologico": False, "n_concorrentes": 1, "dias_publicacao": 120, "cpv": "09100000"},
    ]
    features = esg.features_de_contratos(rows, insolvencias=1, devedor=True)
    assert features["contratos"] == 2
    assert features["valor_total"] == 1500.0
    assert features["taxa_ecologicos"] == pytest.approx(2 / 3, abs=1e-4)
    assert features["share_verde"] == pytest.approx(2 / 3, abs=1e-4)
    assert features["share_marrom"] == pytest.approx(1 / 3, abs=1e-4)
    assert features["exposicao_verde"] == pytest.approx(1 / 3, abs=1e-4)
    assert features["share_servicos_ambientais"] == pytest.approx(2 / 3, abs=1e-4)
    assert features["concentracao_comprador"] == pytest.approx(2 / 3, abs=1e-4)
    assert features["taxa_ajuste_direto"] == pytest.approx(1 / 3, abs=1e-4)
    assert features["mediana_concorrentes"] == 3.0
    assert features["insolvencias"] == 1 and features["devedor"] == 1
    assert features["cpv_top"][0]["divisao"] == "90"
    assert features["por_ano"] == [{"ano": 2025, "contratos": 2, "valor": 1500.0}]


def test_indicadores_externos_tem_precedencia() -> None:
    docs = [
        {"ano": 2025, "fonte": "relatorio", "verificacao": "declarada", "atualizado_em": "2025-06-01", "indicadores": [{"codigo": "e_iso14001", "valor": 0}]},
        {"ano": 2025, "fonte": "auditoria", "verificacao": "externa", "atualizado_em": "2025-05-01", "indicadores": [{"codigo": "e_iso14001", "valor": 1}]},
    ]
    valores, detalhes, fontes = esg._valores_indicadores(docs, 2025)
    assert valores["e_iso14001"] == 1
    assert detalhes[0]["verificacao"] == "externa"
    assert "auditoria" in fontes and "relatorio" in fontes


# ---------------------------------------------------------------------------
# Benchmark e carteira (com cliente falso)
# ---------------------------------------------------------------------------
class _Indices:
    def exists(self, *, index: str) -> bool:  # noqa: A002 - API do Elasticsearch
        return True


class _ClienteFalso:
    """Devolve sempre os mesmos hits: chega para benchmark e carteira."""

    def __init__(self, hits: list[dict] | None = None) -> None:
        self.indices = _Indices()
        self.hits = hits or []

    def search(self, *, index: str, body: dict, request_timeout: int = 30) -> dict:  # noqa: A002
        return {"hits": {"total": {"value": len(self.hits)}, "hits": self.hits}}


def test_benchmark_percentil_e_quartis() -> None:
    hits = [
        {"_source": {"nif": f"n{i}", "score": score, "pilares": {"e": score, "s": score, "g": score}, "historico": [{"ano": 2025, "score": score}]}}
        for i, score in enumerate([40, 50, 60, 80, 90])
    ]
    cliente = _ClienteFalso(hits)
    payload = esg._benchmark(cliente, nif="alvo", setor="F", dimensao="grande", score=70, pilares={"e": 70}, anos=[2025])
    assert payload["disponivel"] is True
    assert payload["n_pares"] == 5
    assert payload["percentil"] == pytest.approx(60.0)
    assert payload["mediana"] == 60.0
    assert payload["p25"] == 50.0 and payload["p75"] == 80.0
    assert payload["historico_pares"][2025] == 60.0


def test_benchmark_sem_amostra_nao_inventa() -> None:
    cliente = _ClienteFalso([{"_source": {"nif": "n1", "score": 60}}])
    payload = esg._benchmark(cliente, nif="alvo", setor="F", dimensao="grande", score=70, pilares={}, anos=[2025])
    assert payload["disponivel"] is False
    assert payload["n_pares"] == 1


def test_carteira_reparte_valor_e_nao_inventa_score() -> None:
    rows = [
        {
            "valor": 100.0,
            "cpv": "90500000",
            "ecologico": True,
            "ajuste_direto": False,
            "adjudicatarios": [
                {"nif": "111111111", "nome": "Fornecedor A"},
                {"nif": "222222222", "nome": "Fornecedor B"},
            ],
        }
    ]
    cliente = _ClienteFalso([])
    payload = esg._fornecedores_de_rows(cliente, rows, nif="comprador", nome="Comprador", calcular_em_falta=False)
    assert payload["resumo"]["n_fornecedores"] == 2
    assert payload["resumo"]["valor_total"] == 100.0
    assert payload["resumo"]["n_sem_score"] == 2
    valores = sorted(item["valor"] for item in payload["fornecedores"])
    assert valores == [50.0, 50.0]
    assert payload["distribuicao"]["niveis"][0]["id"] == "sem_score"
    assert payload["alertas"]


def test_mapa_agrega_por_regiao_e_nao_inventa_localizacao() -> None:
    """O mapa só marca distritos conhecidos; «Portugal Continental» não é região."""
    docs = [
        {
            "nif": "1",
            "name": "A",
            "pais": "PT",
            "score": 60.0,
            "nivel": "intermedio",
            "nivel_label": "Intermédio",
            "cor": "#fbbf24",
            "cobertura": 0.5,
            "valor": 100.0,
            "location": {"distrito": "Lisboa", "concelho": "Oeiras"},
        },
        {
            "nif": "2",
            "name": "B",
            "pais": "PT",
            "score": 80.0,
            "nivel": "avancado",
            "nivel_label": "Avançado",
            "cor": "#2dd4bf",
            "cobertura": 1.0,
            "valor": 50.0,
            "location": {"distrito": "Lisboa"},
        },
        {"nif": "3", "name": "C", "pais": "PT", "score": 40.0, "location": {}},
        {"nif": "4", "name": "D", "pais": "PT", "score": 30.0, "location": {"distrito": "Portugal Continental"}},
    ]

    payload = esg._agregar_mapa(docs)

    assert payload["com_localizacao"] == 2
    assert payload["sem_localizacao"] == 2
    assert len(payload["regioes"]) == 1
    regiao = payload["regioes"][0]
    assert regiao["distrito"] == "Lisboa"
    assert regiao["n"] == 2
    assert regiao["score_medio"] == 70.0
    assert regiao["valor"] == 150.0
    assert regiao["empresas"] == ["1", "2"]
    assert [item["id"] for item in regiao["niveis"]] == ["avancado", "intermedio"]
    assert payload["empresas"][0]["concelho"] == "Oeiras"


# ---------------------------------------------------------------------------
# Taxonomia Europeia
# ---------------------------------------------------------------------------
def test_taxonomia_panorama_tem_os_seis_objetivos_e_151_atividades() -> None:
    panorama = esg.taxonomia_panorama()
    assert len(panorama["objetivos"]) == 6
    assert panorama["total_atividades"] == 151
    assert {item["id"] for item in panorama["objetivos"]} == {41, 42, 43, 44, 45, 46}
    assert panorama["salvaguardas"]
    assert panorama["normas_relato"]
    assert len(panorama["ods"]) == 17
    assert len(panorama["passos"]) == 5


def test_atividades_por_nace_prefere_o_prefixo_mais_especifico() -> None:
    atividades = tax_eu.atividades_por_nace("42910")
    assert atividades
    assert all(item["especificidade"] >= 4 for item in atividades)
    assert any("F42.9" in (item.get("nace_match") or "") for item in atividades)


def test_taxonomia_de_empresa_elege_mas_nao_declara_alinhamento() -> None:
    payload = esg.taxonomia_de_empresa(
        cae="42910",
        setor="F",
        valores={"e_emissoes_scope1": 10, "e_agua_m3": 100, "g_codigo_etica": 1},
    )
    assert payload["nace"] == "F42910"
    assert payload["elegivel"] is True
    assert payload["alinhamento"] == "elegivel_nao_verificado"
    assert payload["objetivos"]
    assert payload["dnsh"]
    assert next(item for item in payload["dnsh"] if item["objetivo"] == 41)["status"] == "com indicador"
    assert next(item for item in payload["dnsh"] if item["objetivo"] == 43)["status"] == "com indicador"
    assert any(item["status"] != "sem evid?ncia" for item in payload["salvaguardas"])
    assert any(item["id"] == 16 for item in payload["ods"])
    assert payload["avisos"]


def test_taxonomia_sem_cae_nao_inventa_elegibilidade() -> None:
    payload = esg.taxonomia_de_empresa(cae="", setor="", valores={})
    assert payload["elegivel"] is False
    assert payload["alinhamento"] == "sem_dados"
    assert payload["atividades"] == []


def test_pesquisa_de_atividades_por_objetivo() -> None:
    payload = esg.taxonomia_atividades(objetivo=44, size=100)
    assert payload["total"] > 0
    assert all(any(item["id"] == 44 for item in atividade["objetivos"]) for atividade in payload["itens"])
