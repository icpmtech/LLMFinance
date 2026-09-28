"""Testes do motor de **risco por empresa** — puros, sem Elasticsearch.

O que aqui se protege (é o que dá sentido ao número que a UI mostra):

- a curva dos componentes (limiar de saturação, limites 0–100);
- a **renormalização** pelos componentes com dados e a `cobertura`/`confiança`;
- as **faixas** do nível de risco e o cartão do modelo (pesos fecham em 1,0);
- as features da triagem (aditivos, ajuste direto, concentração, concorrência,
  prazos) e as da análise completa (réguas de CPV, insolvências);
- o **modelo de anomalia** (IsolationForest) com uma população sintética;
- o **parecer factual** (o recuo quando não há modelo de IA), sem inventar dados.
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api import padroes_service as padroes  # noqa: E402
from api import risco_ia as ia  # noqa: E402
from api import risco_service as risco  # noqa: E402


# ---------------------------------------------------------------------------
# Curva, faixas e cartão do modelo
# ---------------------------------------------------------------------------
def test_linear_satura_e_respeita_limites() -> None:
    assert risco._linear(None, 0.0, 0.25) is None
    assert risco._linear(0.0, 0.0, 0.25) == 0.0
    assert risco._linear(0.25, 0.0, 0.25) == 100.0
    assert risco._linear(1.0, 0.0, 0.25) == 100.0  # satura
    assert risco._linear(-5.0, 0.0, 0.25) == 0.0  # não desce abaixo de zero
    # Componente com piso (concentração: 50 % → 0 pontos, 90 % → 100).
    assert risco._linear(0.5, 0.5, 0.9) == 0.0
    assert risco._linear(0.7, 0.5, 0.9) == pytest.approx(50.0)


def test_niveis_por_faixa() -> None:
    assert risco.nivel_de(0)["id"] == "baixo"
    assert risco.nivel_de(19.9)["id"] == "baixo"
    assert risco.nivel_de(20)["id"] == "moderado"
    assert risco.nivel_de(45)["id"] == "elevado"
    assert risco.nivel_de(70)["id"] == "muito_elevado"
    assert risco.nivel_de(100)["id"] == "critico"
    assert risco.nivel_de(500)["id"] == "critico"  # saturado, não rebenta


def test_cartao_modelo_pesos_fecham_em_um() -> None:
    cartao = risco.cartao_modelo()
    assert cartao["versao"] == risco.MODELO_VERSAO
    assert cartao["aviso"]
    total = sum(item["peso"] for item in cartao["componentes"])
    assert total == pytest.approx(1.0)
    ids = [item["id"] for item in cartao["componentes"]]
    assert len(ids) == len(set(ids))
    for item in cartao["componentes"]:
        assert item["limiar_saturacao"] > item["limiar_zero"]


# ---------------------------------------------------------------------------
# Pontuação
# ---------------------------------------------------------------------------
def test_avaliar_sem_dados_nao_inventa_score() -> None:
    payload = risco.avaliar({}, metodo="triagem")
    assert payload["score"] is None
    assert payload["nivel"] is None
    assert payload["cobertura"] == 0.0
    assert payload["confianca"] == "sem dados"
    assert payload["componentes"]  # os componentes aparecem, todos indisponíveis
    assert all(not item["disponivel"] for item in payload["componentes"])
    assert payload["avisos"]


def test_avaliar_renormaliza_pelos_componentes_com_dados() -> None:
    """Sem z_cpv (triagem) e sem ML, a cobertura baixa mas o score existe."""
    features = {
        "insolvencias": 1,
        "taxa_aditivos": 0.3,
        "taxa_ajuste_direto": 0.9,
        "concentracao_comprador": 0.95,
        "taxa_sem_concorrentes": 0.5,
        "dias_assinatura_mediana": 200.0,
        "contratos": 40,
    }
    payload = risco.avaliar(features, metodo="triagem")
    assert payload["cobertura"] == pytest.approx(0.80)  # sem valor_atipico nem anomalia_ml
    assert payload["confianca"] == "média"
    assert payload["score"] is not None and payload["score"] > 50
    valor = next(item for item in payload["componentes"] if item["id"] == "valor_atipico")
    assert valor["disponivel"] is False and valor["peso_efetivo"] == 0.0
    assert payload["componentes"][0]["id"] == "insolvencia"  # ordem estável do cartão


def test_avaliar_empresa_critica_soma_evidencias() -> None:
    features = {
        "insolvencias": 3,
        "taxa_aditivos": 0.5,
        "taxa_ajuste_direto": 1.0,
        "concentracao_comprador": 0.98,
        "taxa_sem_concorrentes": 0.9,
        "taxa_baixa_concorrencia": 0.9,
        "dias_assinatura_mediana": 400.0,
        "dias_publicacao_mediana": 300.0,
        "z_cpv_mediano": 8.0,
        "adjudicantes_distintos": 2,
        "contratos": 120,
        "valor_total": 9_000_000.0,
    }
    ml = {
        "disponivel": True,
        "algoritmo": "IsolationForest (não supervisionado)",
        "n_referencia": 900,
        "percentil": 0.995,
    }
    payload = risco.avaliar(features, ml=ml, metodo="detalhado")
    assert payload["cobertura"] == pytest.approx(1.0)
    assert payload["confianca"] == "alta"
    assert payload["score"] == pytest.approx(100.0, abs=0.01)
    assert payload["nivel"] == "critico"
    assert payload["nivel_label"] == "Crítico"
    assert payload["fatores"] and payload["fatores"][0]["contributo"] > 0
    insolvencia = next(item for item in payload["componentes"] if item["id"] == "insolvencia")
    assert insolvencia["pontos"] == 100.0
    assert "3 processo(s) no CIRE" in insolvencia["evidencia"][0]


def test_avaliar_empresa_calma_fica_baixa() -> None:
    features = {
        "insolvencias": 0,
        "taxa_aditivos": 0.0,
        "taxa_ajuste_direto": 0.3,
        "concentracao_comprador": 0.3,
        "taxa_sem_concorrentes": 0.0,
        "taxa_baixa_concorrencia": 0.0,
        "dias_assinatura_mediana": 10.0,
        "dias_publicacao_mediana": 5.0,
        "z_cpv_mediano": 0.4,
        "adjudicantes_distintos": 30,
        "contratos": 60,
        "valor_total": 500_000.0,
    }
    ml = {"disponivel": True, "algoritmo": "IsolationForest", "n_referencia": 900, "percentil": 0.2}
    payload = risco.avaliar(features, ml=ml, metodo="detalhado")
    assert payload["nivel"] == "baixo"
    assert payload["score"] < 20
    assert payload["fatores"] == []  # nada contribui para o risco


def test_anomalia_ml_ordena_empresa_fora_do_padrao() -> None:
    if padroes._sklearn() is None:  # pragma: no cover - ambiente sem sklearn
        pytest.skip("scikit-learn indisponível")
    rng = random.Random(11)
    referencia = [
        {
            "contratos": rng.randint(20, 80),
            "valor_total": rng.uniform(1e5, 2e6),
            "valor_mediano": rng.uniform(1e3, 5e4),
            "adjudicantes_distintos": rng.randint(5, 40),
            "concentracao_comprador": rng.uniform(0.05, 0.35),
            "taxa_ajuste_direto": rng.uniform(0.1, 0.5),
            "taxa_aditivos": rng.uniform(0.0, 0.05),
        }
        for _ in range(400)
    ]
    típico = dict(referencia[0])
    fora = {
        "contratos": 900,
        "valor_total": 4e8,
        "valor_mediano": 5e6,
        "adjudicantes_distintos": 2,
        "concentracao_comprador": 0.99,
        "taxa_ajuste_direto": 0.95,
        "taxa_aditivos": 0.6,
    }
    anomalia_típica = risco.anomalia_ml(típico, referencia)
    anomalia_fora = risco.anomalia_ml(fora, referencia)
    assert anomalia_típica and anomalia_típica["disponivel"]
    assert anomalia_fora and anomalia_fora["disponivel"]
    assert anomalia_fora["percentil"] > anomalia_típica["percentil"]
    assert anomalia_fora["percentil"] > 0.9
    assert anomalia_fora["n_referencia"] == 400


def test_anomalia_ml_sem_referencia_suficiente_explica_se() -> None:
    resultado = risco.anomalia_ml({"contratos": 10}, [{"contratos": 5}] * 3)
    assert resultado and resultado["disponivel"] is False
    assert "referência" in resultado["motivo"]


def test_anomalia_ml_features_em_falta_nao_estragam() -> None:
    """Empresa sem valor registado: imputa pela mediana, não rebenta nem inventa."""
    if padroes._sklearn() is None:  # pragma: no cover
        pytest.skip("scikit-learn indisponível")
    referência = [
        {"contratos": 10 + i, "valor_total": 1e5 * (i + 1), "valor_mediano": 1000.0, "adjudicantes_distintos": i % 7, "concentracao_comprador": 0.2, "taxa_ajuste_direto": 0.5, "taxa_aditivos": 0.0}
        for i in range(120)
    ]
    resultado = risco.anomalia_ml({"contratos": None, "valor_total": None}, referência)
    assert resultado and resultado["disponivel"] is True
    assert 0.0 <= resultado["percentil"] <= 1.0


# ---------------------------------------------------------------------------
# Features
# ---------------------------------------------------------------------------
def _contrato(**kwargs) -> dict:
    base = {
        "valor": 10_000.0,
        "ajuste_direto": 0,
        "ratio_efetivo": None,
        "adjudicante_nif": "500000000",
        "adjudicante_nome": "Câmara X",
        "n_concorrentes": 3,
        "dias_assinatura": 10,
        "dias_publicacao": 5,
        "ano": 2024,
    }
    return {**base, **kwargs}


def test_features_de_triagem_conta_o_que_interessa() -> None:
    contratos = [
        _contrato(valor=100_000.0, ajuste_direto=1, ratio_efetivo=1.5, n_concorrentes=0),
        _contrato(valor=100_000.0, ajuste_direto=1, ratio_efetivo=1.2, adjudicante_nif="500000001", adjudicante_nome="Instituto Y", n_concorrentes=1),
        _contrato(valor=200_000.0, adjudicante_nif="500000001", adjudicante_nome="Instituto Y", n_concorrentes=2),
        _contrato(valor=10_000.0, adjudicante_nif=None, adjudicante_nome=None, n_concorrentes=None),
    ]
    features = risco.features_de_triagem(contratos, insolvencias=2)
    assert features["contratos"] == 4
    assert features["valor_total"] == pytest.approx(410_000.0)
    assert features["taxa_ajuste_direto"] == pytest.approx(0.5)
    assert features["taxa_aditivos"] == pytest.approx(0.5)  # 2 de 4 acima de 115 %
    assert features["concentracao_comprador"] == pytest.approx(0.75)  # 300k do maior comprador em 400k com comprador
    assert features["adjudicantes_distintos"] == 2
    # A linha sem `n_concorrentes` fica de fora da taxa (não conta como «sem concorrentes»).
    assert features["taxa_sem_concorrentes"] == pytest.approx(1 / 3, abs=1e-4)
    assert features["taxa_baixa_concorrencia"] == pytest.approx(2 / 3, abs=1e-4)  # ≤1 concorrente e ≥25 000 €
    assert features["insolvencias"] == 2
    assert features["anos"] == [2024]
    assert features["z_cpv_mediano"] is None  # só existe no dossiê


def test_features_sem_insolvencias_fica_none() -> None:
    """Sem consulta ao CIRE o componente fica indisponível — não vale zero."""
    features = risco.features_de_triagem([_contrato()])
    assert features["insolvencias"] is None
    payload = risco.avaliar(features, metodo="triagem")
    insolvencia = next(item for item in payload["componentes"] if item["id"] == "insolvencia")
    assert insolvencia["disponivel"] is False


def test_features_de_analise_usa_resumo_e_reguas() -> None:
    analise = {
        "contratos": [
            {"z_cpv": 1.0, "valor": 1000.0, "ratio_efetivo": None, "ajuste_direto": 0},
            {"z_cpv": 5.0, "valor": 2000.0, "ratio_efetivo": 1.4, "ajuste_direto": 1},
        ],
        "resumo": {
            "taxa_ajuste_direto": 0.5,
            "taxa_aditivo": 0.5,
            "concentracao_adjudicante": 0.8,
            "valor_total": 3000.0,
            "valor_mediano": 1500.0,
            "adjudicantes_distintos": 2,
            "insolvente": True,
        },
        "relacoes": {"insolvencias": [{"processo": "1"}, {"processo": "2"}]},
        "sinais": [{"padrao": "aditivo_valor", "severidade": "alerta"}],
    }
    features = risco.features_de_analise(analise)
    assert features["z_cpv_mediano"] == pytest.approx(3.0)
    assert features["taxa_ajuste_direto"] == pytest.approx(0.5)
    assert features["taxa_aditivos"] == pytest.approx(0.5)
    assert features["concentracao_comprador"] == pytest.approx(0.8)
    assert features["insolvencias"] == 2
    assert features["severidade"] == "alerta"
    assert features["valor_total"] == pytest.approx(3000.0)


def test_tokens_do_pedido_ignora_ligacoes_curtas() -> None:
    assert risco.tokens_do_pedido("Residências Montepio, Serviços de Saúde") == [
        "residencias",
        "montepio",
        "servicos",
        "saude",
    ]
    assert risco.tokens_do_pedido("A do Sá") == []
    assert risco.tokens_do_pedido("") == []


def test_tokens_significativos_tiram_formas_societarias() -> None:
    """«CLARANET, S.A.» tem de procurar `claranet` — `s.a` casava com todo o mercado."""
    assert risco.tokens_significativos("CLARANET, S.A.") == ["claranet"]
    assert risco.tokens_significativos("CLARANET PORTUGAL, S.A.") == ["claranet", "portugal"]
    assert risco.tokens_significativos("Águas do Norte, SA") == ["aguas", "norte"]
    assert risco.tokens_significativos("Mota-Engil, Lda") == ["mota", "engil"]
    assert risco.tokens_significativos("EMPRESA UNIPESSOAL, LDA") == []


def test_nif_pesquisa_reconhece_nif_e_recusa_nomes() -> None:
    assert risco._nif_pesquisa("503412031") == "503412031"
    assert risco._nif_pesquisa("503 412 031") == "503412031"
    assert risco._nif_pesquisa("A61129086") == "A61129086"
    assert risco._nif_pesquisa("claranet") is None
    assert risco._nif_pesquisa("S.A.") is None


def test_ordem_candidato_prefere_a_empresa_pedida() -> None:
    """«águas do norte» tem de dar a *Águas do Norte, SA*, não a do Alentejo."""
    frase, tokens = "aguas do norte", ["aguas", "norte"]
    norte = {"name": "Águas do Norte, SA", "contracts_count": 16484, "_score": 18.0}
    alentejano = {"name": "Águas do Norte Alentejano, SA", "contracts_count": 1, "_score": 21.0}
    interior = {"name": "Águas do Interior - Norte, EIM, SA", "contracts_count": 15, "_score": 19.0}
    ordem = sorted([alentejano, interior, norte], key=lambda doc: risco.ordem_candidato(doc, frase=frase, tokens=tokens))
    assert [doc["name"] for doc in ordem] == ["Águas do Norte, SA", "Águas do Norte Alentejano, SA", "Águas do Interior - Norte, EIM, SA"]


def test_ordem_candidato_promove_quem_tem_contratos() -> None:
    """Entre homónimos, primeiro a que tem contratos registados."""
    frase, tokens = "claranet", ["claranet"]
    portugal = {"name": "CLARANET PORTUGAL, S.A.", "contracts_count": 1038, "_score": 35.0}
    sau = {"name": "CLARANET SAU", "contracts_count": 0, "_score": 45.0}
    ordem = sorted([sau, portugal], key=lambda doc: risco.ordem_candidato(doc, frase=frase, tokens=tokens))
    assert ordem[0]["name"] == "CLARANET PORTUGAL, S.A."


def test_ordem_candidato_da_precedencia_a_frase_do_pedido() -> None:
    frase, tokens = "mota engil", ["mota", "engil"]
    com_frase = {"name": "MOTA-ENGIL RENEWING, S.A.", "contracts_count": 14, "_score": 12.0}
    sem_frase = {"name": "ENGIL MOTA SERVIÇOS, LDA", "contracts_count": 900, "_score": 30.0}
    ordem = sorted([sem_frase, com_frase], key=lambda doc: risco.ordem_candidato(doc, frase=frase, tokens=tokens))
    assert ordem[0]["name"] == "MOTA-ENGIL RENEWING, S.A."


def test_consulta_cadastro_e_estrita_por_omissao() -> None:
    """A consulta estrita exige todas as palavras; o recuo (`ou`) é explícito."""
    estrita = risco.consulta_cadastro("CLARANET, S.A.")
    assert estrita is not None
    should = estrita["bool"]["should"]
    frase = [clause.get("match_phrase") for clause in should if "match_phrase" in clause]
    assert frase and frase[0]["name"]["query"] == "claranet"
    assert all(
        "operator" not in clause.get("multi_match", {}) or clause["multi_match"]["operator"] == "and"
        for clause in should
        if "multi_match" in clause
    )
    assert not any(clause.get("multi_match", {}).get("operator") == "or" for clause in should)

    recuo = risco.consulta_cadastro("CLARANET, S.A.", estrito=False)
    assert recuo is not None
    assert any(clause.get("multi_match", {}).get("operator") == "or" for clause in recuo["bool"]["should"])

    # Um NIF entra por `term`, não por texto.
    por_nif = risco.consulta_cadastro("503412031")
    assert por_nif is not None
    assert any("terms" in clause for clause in por_nif["bool"]["should"])

    # Só formas societárias não dão consulta nenhuma (evita devolver o país inteiro).
    assert risco.consulta_cadastro("S.A.") is None
    assert risco.consulta_cadastro("lda unipessoal") is None


def test_pesquisa_sem_texto_nao_bate_no_elasticsearch() -> None:
    payload = risco.pesquisa("   ", es=None)
    assert payload.get("itens") == []
    assert payload.get("total") == 0
    if "error" not in payload:
        assert payload["cartao_modelo"]["versao"] == risco.MODELO_VERSAO


def test_risco_empresa_com_pais_desconhecido_devolve_erro() -> None:
    payload = risco.risco_empresa(nif="500000000", pais="FR", use_cache=False)
    assert "error" in payload


def test_pais_aceita_codigo_ou_nome() -> None:
    """O cadastro guarda o nome do país; as rotas recebem o código — os dois valem."""
    assert risco.pais_codigo("PT") == "PT"
    assert risco.pais_codigo("pt") == "PT"
    assert risco.pais_codigo("Portugal") == "PT"
    assert risco.pais_codigo("Espanha") == "ES"
    assert risco.pais_codigo("España") == "ES"
    assert risco.pais_codigo("ES") == "ES"
    assert risco.pais_codigo(None) == "PT"
    assert risco.pais_codigo("FR") == "FR"  # passa tal como está: quem valida é a rota


# ---------------------------------------------------------------------------
# Parecer (IA com recuo factual)
# ---------------------------------------------------------------------------
def test_factual_markdown_tem_numeros_e_aviso() -> None:
    payload = risco.avaliar(
        {"insolvencias": 1, "taxa_aditivos": 0.3, "contratos": 20},
        metodo="triagem",
        avisos=["Triagem sobre 20 de 300 contratos."],
    )
    analise = {
        "nif": "500000000",
        "nome": "Empresa Exemplo, Lda.",
        "pais_label": "Portugal (Portal BASE)",
        "contratos_analisados": 20,
        "contratos_total": 300,
        "resumo": {"valor_total": 1_234_567.89, "taxa_ajuste_direto": 0.42, "taxa_aditivo": 0.3, "adjudicantes_distintos": 4, "concentracao_adjudicante": 0.7},
        "sinais": [{"padrao": "aditivo_valor", "label": "Valor efetivo acima do contratual", "severidade": "alerta", "contratos": 6}],
    }
    texto = ia.factual_markdown(payload, analise)
    assert "Empresa Exemplo, Lda." in texto
    assert payload["nivel_label"] in texto
    assert "1 234 567,89 €" in texto
    assert "Valor efetivo acima do contratual" in texto
    assert "Triagem sobre 20 de 300 contratos." in texto
    assert "prioridade" in texto.lower() or "não uma acusação" in texto.lower()


def test_factual_markdown_aguenta_risco_vazio() -> None:
    texto = ia.factual_markdown({}, None)
    assert "sem dados" in texto


def test_factos_nao_inventa_quem_nao_esta() -> None:
    payload = risco.avaliar({"contratos": 12, "insolvencias": 0}, metodo="triagem")
    fac = ia.factos(payload, {"nif": "1", "nome": "X", "resumo": {"valor_total": 10.0}})
    assert fac["risco"]["score"] == payload["score"]
    assert len(fac["componentes"]) == len(risco.COMPONENTES)
    assert all("evidencia" in item for item in fac["componentes"])
    assert fac["empresa"]["nome"] == "X"
