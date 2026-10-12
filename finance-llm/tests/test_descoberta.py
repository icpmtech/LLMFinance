"""Testes do painel de **Descoberta** (`api/descoberta_service.py`).

Cobrem o que não depende do Elasticsearch: os indicadores da recolha, o grafo de
informação (camadas, centro e arestas), a projeção sobre a ontologia (ligações
materializadas e lacunas) e a pergunta que o Hermes recebe.

A recolha em si é exercitada no ambiente (as fontes falam com o Elasticsearch e
com os serviços externos); aqui usamos uma recolha sintética, para os testes
serem determinísticos.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from api import descoberta_routes as rotas  # noqa: E402
from api import descoberta_service as service  # noqa: E402


def _contrato(indice: int, *, valor: float, cpv: str, adjudicante: str, adjudicante_nif: str) -> dict:
    return {
        "id": f"c{indice}",
        "ano": 2024,
        "objeto": f"Serviços {indice}",
        "valor": valor,
        "cpv": cpv,
        "cpv_desc": f"CPV {cpv}",
        "adjudicante": adjudicante,
        "adjudicante_nif": adjudicante_nif,
    }


def _recolha() -> dict:
    """Recolha sintética com todas as famílias de evidência que o grafo desenha."""
    recolha = {
        "nif": "500000000",
        "nome": "Empresa Teste, S.A.",
        "pais": "PT",
        "secoes": {
            "cadastro": {"cadastro": {"name": "Empresa Teste, S.A."}},
            "contratos": {
                "contratos": [
                    _contrato(1, valor=100.0, cpv="45000000", adjudicante="Município A", adjudicante_nif="501"),
                    _contrato(2, valor=900.0, cpv="72000000", adjudicante="Município B", adjudicante_nif="502"),
                    _contrato(3, valor=200.0, cpv="45000000", adjudicante="Município A", adjudicante_nif="501"),
                ],
                "resumo": {"valor_total": 1200.0, "valor_mediano": 200.0, "taxa_ajuste_direto": 0.33},
                "sinais": [{"padrao": "rede_pessoas", "detalhe": "2 pessoas com cargo"}],
                "contratos_total": 3,
            },
            "rede": {"cargos_sociais": [{"nif": "1", "nome": "Ana Silva", "cargos": [{"role_org": "Gerente"}]}]},
            "pessoas": {"pessoas": [{"nif": "1", "nome": "Ana Silva"}], "total": 1},
            "cire": {"insolvencias": [{"especie": "Insolvência", "processo": "p1", "tribunal": "T1"}], "total": 1},
            "marcas": {"items": [{"nord": "m1", "nome": "Marca Teste"}], "total": 1},
            "firmas": {"items": [{"nipc": "f1", "nome": "Firma Teste"}], "total": 1},
            "subvencoes": {"items": [{"id": "s1", "valor": 500.0, "entidade": "IAPMEI"}], "total": 1, "valor_total": 500.0},
            "devedores": {"items": [{"valor": 250.0}], "total": 1},
            "noticias": {"items": [{"id": "n1", "titulo": "Empresa Teste ganha obra", "fonte": "Jornal"}], "total": 1},
            "mercado": {"total": 0},
        },
        "fontes": [],
        "recolhidas": 9,
        "em_falta": [],
        "ms": 10,
    }
    recolha["kpis"] = service._kpis(recolha)
    return recolha


def test_normalizar_nif_aceita_formatos_comuns():
    assert service.normalizar_nif("500 000 000") == "500000000"
    assert service.normalizar_nif("PT500000000") == "500000000"
    assert service.normalizar_nif("") == ""


def test_kpis_resume_a_recolha():
    kpis = _recolha()["kpis"]
    assert kpis["contratos"] == 3
    assert kpis["valor_total"] == 1200.0
    assert kpis["adjudicantes"] == 2
    assert kpis["maior_adjudicante"]["nome"] == "Município B"
    assert kpis["concentracao_maior"] == 75.0
    assert kpis["insolvencias"] == 1
    assert kpis["marcas"] == 1
    assert kpis["firmas"] == 1
    assert kpis["subvencoes_valor"] == 500.0
    assert kpis["noticias"] == 1


def test_grafo_centra_a_empresa_e_liga_cada_camada():
    malha = service.grafo(_recolha())
    nos = {no["id"]: no for no in malha["nodes"]}

    centro = "empresa:500000000"
    assert centro in nos
    assert nos[centro]["label"] == "Empresa Teste, S.A."
    assert nos[centro]["total_value"] == 1200.0

    for identificador, dimension in (
        ("adjudicante:501", "adjudicante"),
        ("adjudicante:502", "adjudicante"),
        ("cpv:45000000", "cpv"),
        ("pessoa:1", "pessoa"),
        ("cire:p1", "cire"),
        ("marca:m1", "marca"),
        ("firma:f1", "firma"),
        ("subvencao:s1", "subvencao"),
        ("devedor:listas", "devedor"),
        ("noticia:n1", "noticia"),
    ):
        assert identificador in nos, f"falta o nó {identificador}"
        assert nos[identificador]["dimension"] == dimension

    ligados = {aresta["source"] for aresta in malha["edges"]} | {aresta["target"] for aresta in malha["edges"]}
    assert centro in ligados
    assert all(no["dimension"] == "empresa" or no["id"] in ligados for no in malha["nodes"])

    # As pessoas apontam para a empresa (quem gere), não o contrário.
    assert any(
        aresta["source"] == "pessoa:1" and aresta["target"] == centro and aresta["relation"] == "gere"
        for aresta in malha["edges"]
    )

    meta = malha["meta"]
    assert meta["dimension_a"] == "empresa"
    assert meta["nodes_total"] == len(malha["nodes"])
    assert meta["edges_total"] == len(malha["edges"])
    assert meta["camadas"]["cpv"] == 2
    assert meta["documents_scanned"] == 3


def test_grafo_sem_contratos_ainda_é_um_no():
    malha = service.grafo({"nif": "500000000", "nome": "Vazia", "secoes": {}, "kpis": {}})
    assert [no["id"] for no in malha["nodes"]] == ["empresa:500000000"]
    assert malha["edges"] == []


def test_ontologia_casa_as_ligacoes_declaradas_e_denuncia_lacunas():
    recolha = _recolha()
    projecao = service.ontologia(recolha, service.grafo(recolha))

    materializadas = {ligacao["id"] for ligacao in projecao["ligacoes"] if ligacao["declarado"]}
    assert {"empresa_contratada", "entidade_publica_adjudica", "contrato_cpv", "empresa_marcas", "empresa_firmas"} <= materializadas

    # O que a ontologia ainda não fala fica visível, em vez de ser escondido.
    assert "pessoa->empresa" in projecao["lacunas"]["ligacoes"]
    assert "empresa->processo_cire" in projecao["lacunas"]["ligacoes"]
    assert "empresa->subvencao" in projecao["lacunas"]["ligacoes"]

    tipos = {tipo["id"]: tipo for tipo in projecao["tipos"]}
    assert tipos["contrato"]["declarado"] is True
    assert tipos["empresa"]["instancias"] == 1

    cobertura = projecao["cobertura"]
    assert cobertura["tipos_instanciados"] == cobertura["tipos_declarados_usados"]
    assert cobertura["percent_tipos"] == 100.0
    assert 0 < cobertura["ligacoes_materializadas"] <= cobertura["ligacoes_declaradas"]


def test_pergunta_padrao_ancora_os_numeros_da_recolha():
    pergunta = service.pergunta_padrao(_recolha())
    assert "Empresa Teste, S.A." in pergunta
    assert "500000000" in pergunta
    assert "1200" in pergunta
    assert "Município B" in pergunta


def test_fontes_param_valida_os_identificadores():
    assert rotas._fontes_param("contratos, marcas") == ["contratos", "marcas"]
    assert rotas._fontes_param("") is None
    with pytest.raises(HTTPException) as erro:
        rotas._fontes_param("contratos,inexistente")
    assert erro.value.status_code == 422


def test_skill_desconhecida_e_recusada():
    with pytest.raises(ValueError):
        service._bloco_da_skill("skill-que-nao-existe")


def test_catalogo_de_fontes_e_coerente():
    assert len(service.FONTES) == len(service.FONTE_IDS)
    for fonte in service.FONTES:
        assert fonte["id"] in service.CARREGADORES
        assert fonte["id"] in service.SECAO_INDICE
        assert fonte["grupo"]
        assert fonte["descricao"]
    assert set(service.FONTES[0]) >= {"id", "label", "grupo", "descricao", "tipo"}
