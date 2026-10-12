"""Testes da comparação de **várias empresas** (`api/descoberta_conjunto.py`).

Sem Elasticsearch: a recolha e a análise do módulo de padrões são substituídas
por versões sintéticas, para se testar o que é nosso — o alinhamento das
métricas, o melhor/pior de cada linha, o radar de séries, a agregação dos pontos
de atenção, a síntese e a validação dos pedidos.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from api import descoberta_conjunto as cj  # noqa: E402


def _contrato(indice: int, *, ano: int, valor: float, cpv: str, adjudicante: str, adjudicante_nif: str) -> dict:
    return {
        "id": f"c{indice}",
        "ano": ano,
        "objeto": f"Serviços {indice}",
        "valor": valor,
        "cpv": cpv,
        "cpv_desc": f"CPV {cpv}",
        "adjudicante": adjudicante,
        "adjudicante_nif": adjudicante_nif,
        "procedimento": "Ajuste direto",
        "n_concorrentes": 0,
    }


def _recolha(nif: str, nome: str, contratos: list[dict], *, risco: float | None = 30.0) -> dict:
    valor_total = sum(float(contrato.get("valor") or 0.0) for contrato in contratos)
    adjudicantes = {str(contrato.get("adjudicante_nif")) for contrato in contratos}
    return {
        "nif": nif,
        "nome": nome,
        "pais": "PT",
        "encontrada": True,
        "avisos": [],
        "fontes": [{"id": "contratos", "estado": "ok"}],
        "em_falta": [],
        "ms": 1200,
        "secoes": {
            "contratos": {
                "contratos": contratos,
                "resumo": {
                    "valor_total": valor_total,
                    "valor_mediano": valor_total / max(len(contratos), 1),
                    "taxa_ajuste_direto": 1.0,
                },
                "contratos_total": len(contratos),
                "sinais": [],
            },
            "risco": {
                "risco": {
                    "score": risco,
                    "nivel": "moderado",
                    "nivel_label": "Moderado",
                    "cor": "#a3e635",
                    "cobertura": 0.8,
                    "confianca": "média",
                    "metodo": "triagem",
                    "metodo_label": "Triagem (contratos da empresa)",
                    "componentes": [
                        {
                            "id": "ajuste_direto",
                            "label": "Peso do ajuste direto",
                            "pontos": 100,
                            "peso": 0.13,
                            "peso_efetivo": 0.16,
                            "contributo": 16.0,
                            "disponivel": True,
                            "unidade": "taxa",
                            "evidencia": ["100.0% dos contratos por ajuste direto"],
                        }
                    ],
                    "fatores": [],
                }
            },
        },
        "kpis": {
            "contratos": len(contratos),
            "valor_total": valor_total,
            "adjudicantes": len(adjudicantes),
            "risco": "Moderado",
            "risco_pontos": risco,
            "insolvencias": 0,
            "mencoes_cire": 0,
            "pessoas": 0,
            "marcas": 0,
            "firmas": 0,
            "subvencoes_valor": 0.0,
            "noticias": 0,
            "sinais": [],
        },
    }


def _base_conjunto() -> dict:
    return {
        "pais": "PT",
        "pais_label": "Portugal",
        "empresas": [{"nif": "111", "nome": "Alfa, S.A."}, {"nif": "222", "nome": "Beta, Lda."}],
        "totais": {"empresas": 2, "contratos": 4, "valor_total": 2000.0},
        "cruzamentos": {
            "adjudicantes": [
                {"nif": "501", "nome": "Município A", "empresas": ["111", "222"], "contratos": 3, "valor": 900.0}
            ],
            "pessoas": [],
            "processos": [
                {"processo": "p1", "especie": "Insolvência", "empresas": ["111", "222"], "data": "2024-01-01"}
            ],
            "cpvs": [
                {"cpv": "45000000", "descricao": "Obras", "empresas": ["111", "222"], "contratos": 4, "valor": 1500.0}
            ],
        },
        "grafo": {"nodes": [{"id": "empresa:111"}, {"id": "empresa:222"}], "edges": [], "meta": {"mode": "relations"}},
        "avisos": [],
    }


@pytest.fixture()
def conjunto(monkeypatch):
    """`conjunto()` com a recolha e os padrões substituídos por dados sintéticos."""

    recolhas = {
        "111": _recolha(
            "111",
            "Alfa, S.A.",
            [
                _contrato(1, ano=2023, valor=900.0, cpv="45000000", adjudicante="Município A", adjudicante_nif="501"),
                _contrato(2, ano=2024, valor=100.0, cpv="45000000", adjudicante="Município B", adjudicante_nif="502"),
            ],
            risco=40.0,
        ),
        "222": _recolha(
            "222",
            "Beta, Lda.",
            [
                _contrato(3, ano=2024, valor=500.0, cpv="45000000", adjudicante="Município A", adjudicante_nif="501"),
                _contrato(4, ano=2024, valor=500.0, cpv="72000000", adjudicante="Município A", adjudicante_nif="501"),
            ],
            risco=10.0,
        ),
    }

    def fake_padroes(*, nifs=None, nomes=None, pais="PT", max_empresas=6, **kwargs):
        return _base_conjunto()

    def fake_recolher(nif, pais="PT", nome=None, apenas=None):
        return recolhas.get(str(nif), {"error": f"NIF desconhecido: {nif}"})

    monkeypatch.setattr(cj.padroes, "analise_empresas", fake_padroes)
    monkeypatch.setattr(cj.service, "recolher", fake_recolher)
    return cj.conjunto(nifs=["111", "222"], pais="PT", max_empresas=4)


def test_conjunto_junta_as_empresas_e_os_cruzamentos(conjunto):
    assert [empresa["nif"] for empresa in conjunto["empresas"]] == ["111", "222"]
    assert conjunto["empresas"][0]["nome"] == "Alfa, S.A."
    assert conjunto["cruzamentos"]["resumo"] == {"adjudicantes": 1, "pessoas": 0, "processos": 1, "cpvs": 1}
    # Os nomes das empresas que partilham cada item vêm resolvidos para a UI.
    assert conjunto["cruzamentos"]["adjudicantes"][0]["empresas_nome"] == ["Alfa, S.A.", "Beta, Lda."]
    assert conjunto["grafo"]["meta"]["mode"] == "relations"
    assert conjunto["totais"]["valor_total"] == 2000.0


def test_comparacao_marca_o_melhor_e_o_pior(conjunto):
    por_id = {linha["id"]: linha for linha in conjunto["comparacao"]}
    escala = por_id["valor_total"]
    assert escala["melhor"]["nome"] == "Alfa, S.A."  # 1000 € > 1000 €? não: 1000 vs 1000 empata
    assert escala["melhor"]["valor"] == pytest.approx(1000.0)
    risco = por_id["risco"]
    assert risco["melhor"]["nome"] == "Beta, Lda."
    assert risco["pior"]["nome"] == "Alfa, S.A."
    assert risco["maior_melhor"] is False


def test_comparacao_por_alvo_do_preco(conjunto):
    por_id = {linha["id"]: linha for linha in conjunto["comparacao"]}
    precio = por_id["preco"]
    # Sem preço base nos contratos sintéticos não há rácio: a linha diz que faltam dados.
    assert precio["alvo"] == 1.0
    assert precio["amplitude"] is None
    assert precio["sem_dados"] == ["Alfa, S.A.", "Beta, Lda."]
    assert all(item["melhor"] is False for item in precio["valores"])


def test_perfil_comparado_alinha_as_dimensoes(conjunto):
    dimensoes = conjunto["perfil"]["dimensoes"]
    ids = [dimensao["id"] for dimensao in dimensoes]
    assert ids[:5] == ["escala", "diversificacao", "concorrencia", "transparencia", "celeridade"]
    assert "risco" in ids
    for serie in conjunto["perfil"]["series"]:
        assert set(serie["valores"]) == set(ids)
        assert serie["detalhes"]


def test_atencao_agregada_por_gravidade(conjunto):
    atencao = conjunto["atencao"]
    assert atencao
    # A primeira linha é sempre a mais grave (alertas antes de avisos e de notas).
    ordem = [cj.SEVERIDADE_ORDEM.get(item["severidade"], 3) for item in atencao]
    assert ordem == sorted(ordem)
    assert {item["nif"] for item in atencao} <= {"111", "222"}
    assert all(item["titulo"] for item in atencao)


def test_leitura_resume_o_conjunto(conjunto):
    leitura = conjunto["leitura"]
    assert "2 empresas comparadas" in leitura
    assert "maior escala: Alfa, S.A." in leitura
    assert "partilham 1 comprador(es)" in leitura
    assert not leitura.endswith("..")


def test_conjunto_avisa_quando_uma_empresa_falha(monkeypatch):
    def fake_padroes(*, nifs=None, nomes=None, pais="PT", max_empresas=6, **kwargs):
        return _base_conjunto()

    def fake_recolher(nif, pais="PT", nome=None, apenas=None):
        if str(nif) == "222":
            return {"error": "Elasticsearch indisponível"}
        return _recolha("111", "Alfa, S.A.", [_contrato(1, ano=2024, valor=10.0, cpv="45000000", adjudicante="A", adjudicante_nif="501")])

    monkeypatch.setattr(cj.padroes, "analise_empresas", fake_padroes)
    monkeypatch.setattr(cj.service, "recolher", fake_recolher)
    resultado = cj.conjunto(nifs=["111", "222"], pais="PT")
    falhada = [empresa for empresa in resultado["empresas"] if empresa["nif"] == "222"][0]
    assert falhada["erro"] == "Elasticsearch indisponível"
    assert falhada["contratos"] is None
    assert any("Beta" in aviso for aviso in resultado["avisos"])


def test_conjunto_valida_o_pedido(monkeypatch):
    with pytest.raises(ValueError, match="pelo menos 2"):
        cj.conjunto(nifs=["111"], pais="PT")
    with pytest.raises(ValueError, match="País não suportado"):
        cj.conjunto(nifs=["111", "222"], pais="XX")

    def fake_padroes(*, nifs=None, nomes=None, pais="PT", max_empresas=6, **kwargs):
        return {"error": "sem empresas para comparar"}

    monkeypatch.setattr(cj.padroes, "analise_empresas", fake_padroes)
    with pytest.raises(ValueError, match="sem empresas"):
        cj.conjunto(nifs=["111", "222"], pais="PT")


def test_conjunto_corta_o_pedido_ao_limite(monkeypatch):
    pedido: dict = {}

    def fake_padroes(*, nifs=None, nomes=None, pais="PT", max_empresas=6, **kwargs):
        pedido["nifs"] = list(nifs or [])
        pedido["max_empresas"] = max_empresas
        return _base_conjunto()

    monkeypatch.setattr(cj.padroes, "analise_empresas", fake_padroes)
    monkeypatch.setattr(cj.service, "recolher", lambda nif, pais="PT", nome=None, apenas=None: _recolha(str(nif), str(nif), []))
    resultado = cj.conjunto(nifs=["111", "222", "333", "444"], pais="PT", max_empresas=99)
    assert pedido["max_empresas"] == cj.MAX_EMPRESAS
    assert resultado["pedido"]["max_empresas"] == cj.MAX_EMPRESAS


def test_texto_das_metricas_usa_a_unidade_certa():
    euros = next(metrica for metrica in cj.METRICAS if metrica["id"] == "valor_total")
    taxa = next(metrica for metrica in cj.METRICAS if metrica["id"] == "ajuste_direto")
    quota = next(metrica for metrica in cj.METRICAS if metrica["id"] == "top1")
    assert cj._texto_metrica(euros, 1_500_000) == "1.5 M€"
    assert cj._texto_metrica(euros, 2_500) == "2 mil €"
    assert cj._texto_metrica(taxa, 0.42) == "42 %"
    assert cj._texto_metrica(quota, 65.48) == "65,5 %"
    assert cj._texto_metrica(quota, None) == "sem dados"


def test_pedidos_sem_repetições_e_pela_ordem():
    assert cj._pedidos(["111", " 111 ", "", None, "222"], ["222", "333"]) == ["111", "222", "333"]
    assert cj._pedidos(None, None) == []
