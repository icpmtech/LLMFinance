"""Testes do motor de decisão da descoberta (`api/descoberta_decisao.py`).

Tudo é cálculo puro sobre uma recolha sintética, para os testes serem
determinísticos e não dependerem do Elasticsearch. Os números da recolha são
escolhidos para disparar (ou não) cada regra de atenção de forma explícita.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from api import descoberta_decisao as motor  # noqa: E402


def _contrato(
    indice: int,
    *,
    ano: int,
    valor: float,
    cpv: str,
    adjudicante: str,
    nif: str,
    procedimento: str,
    ajuste_direto: int = 0,
    n_concorrentes: int | None = 2,
    ratio_base: float | None = 1.0,
    ratio_efetivo: float | None = 1.0,
    dias_decisao: int | None = -10,
    dias_assinatura: int | None = 5,
    dias_publicacao: int | None = 3,
) -> dict:
    return {
        "id": f"c{indice}",
        "ano": ano,
        "objeto": f"Contrato {indice}",
        "valor": valor,
        "preco_base": valor / ratio_base if ratio_base else None,
        "ratio_base": ratio_base,
        "ratio_efetivo": ratio_efetivo,
        "procedimento": procedimento,
        "ajuste_direto": ajuste_direto,
        "n_concorrentes": n_concorrentes,
        "cpv": cpv,
        "cpv_desc": f"CPV {cpv}",
        "adjudicante": adjudicante,
        "adjudicante_nif": nif,
        "dias_decisao": dias_decisao,
        "dias_assinatura": dias_assinatura,
        "dias_publicacao": dias_publicacao,
    }


def _recolha() -> dict:
    """Quatro contratos: um comprador com 60% do valor, 75% por ajuste direto."""
    contratos = [
        _contrato(1, ano=2023, valor=10_000, cpv="45000000", adjudicante="Município A", nif="501",
                  procedimento="Concurso público", n_concorrentes=3, ratio_base=1.0),
        _contrato(2, ano=2023, valor=50_000, cpv="45000000", adjudicante="Município A", nif="501",
                  procedimento="Ajuste direto", ajuste_direto=1, n_concorrentes=0, ratio_base=1.2,
                  dias_decisao=-200),
        _contrato(3, ano=2024, valor=400_000, cpv="72000000", adjudicante="Município A", nif="501",
                  procedimento="Ajuste direto", ajuste_direto=1, n_concorrentes=0, ratio_base=1.2,
                  dias_decisao=-400),
        _contrato(4, ano=2024, valor=700_000, cpv="72000000", adjudicante="Município B", nif="502",
                  procedimento="Ajuste direto", ajuste_direto=1, n_concorrentes=0, ratio_base=1.2,
                  dias_decisao=-400),
    ]
    risco = {
        "score": 65.0,
        "nivel": "elevado",
        "nivel_label": "Elevado",
        "cor": "#fbbf24",
        "confianca": "alta",
        "cobertura": 0.9,
        "metodo_label": "Triagem",
        "componentes": [
            {"id": "insolvencia", "label": "Processos de insolvência", "peso": 0.2, "peso_efetivo": 0.22,
             "pontos": 80.0, "contributo": 0.176, "disponivel": True, "unidade": "processos",
             "evidencia": ["1 processo"]},
            {"id": "ajuste_direto", "label": "Peso do ajuste direto", "peso": 0.13, "peso_efetivo": 0.14,
             "pontos": 40.0, "contributo": 0.056, "disponivel": True, "unidade": "%", "evidencia": ["75%"]},
        ],
        "fatores": [{"label": "Processos de insolvência", "pontos": 80.0, "contributo": 0.176}],
    }
    kpis = {
        "contratos": 4,
        "valor_total": 1_160_000.0,
        "adjudicantes": 2,
        "insolvencias": 1,
        "marcas": 0,
        "firmas": 0,
        "pessoas": 0,
        "subvencoes_valor": 0.0,
        "noticias": 0,
        "sinais": [
            {"padrao": "insolvencia", "detalhe": "1 processo(s) no CIRE"},
            {"padrao": "rede_pessoas", "detalhe": "3 pessoa(s) com cargo"},
        ],
    }
    return {
        "nif": "500000000",
        "nome": "Empresa Teste, S.A.",
        "pais": "PT",
        "secoes": {"contratos": {"contratos": contratos}, "risco": {"risco": risco}},
        "fontes": [],
        "recolhidas": 2,
        "em_falta": [],
        "ms": 12,
        "kpis": kpis,
    }


def test_evolucao_por_ano():
    linhas = motor.evolucao(_recolha()["secoes"]["contratos"]["contratos"])
    assert [linha["ano"] for linha in linhas] == [2023, 2024]
    assert linhas[0]["contratos"] == 2
    assert linhas[0]["valor"] == 60_000.0
    assert linhas[1]["valor"] == 1_100_000.0
    assert linhas[0]["adjudicantes"] == 1
    assert linhas[0]["novos_adjudicantes"] == 1
    assert linhas[1]["novos_adjudicantes"] == 1


def test_concentracao_calcula_quotas_hhi_e_pareto():
    dados = motor.concentracao(_recolha()["secoes"]["contratos"]["contratos"])
    assert dados["adjudicantes"] == 2
    assert dados["top"][0]["nome"] == "Município B"
    assert dados["top1"] == 60.34
    assert dados["top3"] == 100.0
    assert dados["hhi"] == 5213.8
    assert dados["curva"][-1]["quota_acumulada"] == 100.0
    assert dados["curva"][0]["ordem"] == 1


def test_escaloes_distribui_pelos_cortes():
    itens = motor.escaloes(_recolha()["secoes"]["contratos"]["contratos"])
    assert [item["contratos"] for item in itens] == [1, 1, 1, 1, 0]
    assert itens[0]["escalao"] == "≤ 20 mil €"
    assert itens[3]["valor"] == 700_000.0


def test_procedimentos_e_ajuste_direto():
    dados = motor.procedimentos(_recolha()["secoes"]["contratos"]["contratos"])
    assert dados["taxa_ajuste_direto"] == 0.75
    assert dados["itens"][0]["procedimento"] == "Ajuste direto"
    assert all(item["ajuste_direto"] for item in dados["itens"] if item["procedimento"] == "Ajuste direto")


def test_precos_conta_contratos_e_valor_por_faixa():
    dados = motor.precos(_recolha()["secoes"]["contratos"]["contratos"])
    assert dados["mediana"] == 1.2
    assert dados["com_ratio"] == 4
    faixa_alinhada = next(item for item in dados["itens"] if item["faixa"] == "0,95–1,05 (alinhado)")
    faixa_acima = next(item for item in dados["itens"] if item["faixa"].startswith("> 1,15"))
    assert faixa_alinhada["contratos"] == 1
    assert faixa_alinhada["valor"] == 10_000.0
    assert faixa_acima["contratos"] == 3
    assert faixa_acima["valor"] == 1_150_000.0
    assert dados["taxa_aditivo"] == 0.0


def test_concorrencia_e_prazos():
    contratos = _recolha()["secoes"]["contratos"]["contratos"]
    concorrencia = motor.concorrencia(contratos)
    assert concorrencia["mediana"] == 0.0
    assert concorrencia["com_dados"] == 4
    sem_registo = next(item for item in concorrencia["itens"] if item["faixa"].startswith("0"))
    assert sem_registo["contratos"] == 3

    prazos = motor.prazos(contratos)
    assert prazos["mediana_decisao_publicacao"] == 300.0
    assert prazos["itens"][0]["fase"] == "Decisão → publicação"
    assert prazos["itens"][2]["dias"] == 3


def test_risco_entra_invertido_no_perfil():
    dados = motor.decisao(_recolha())
    perfil = {item["id"]: item for item in dados["perfil"]}
    assert perfil["risco"]["valor"] == 35.0
    assert "65" in perfil["risco"]["detalhe"]
    assert all(0 <= (item["valor"] or 0) <= 100 for item in dados["perfil"])


def test_pontos_de_atencao_disparam_e_nao_se_repetem():
    dados = motor.decisao(_recolha())
    titulos = [item["titulo"] for item in dados["atencao"]]

    assert any("insolvente" in titulo for titulo in titulos)
    assert any("num só comprador" in titulo for titulo in titulos)
    assert any("ajuste direto" in titulo for titulo in titulos)
    assert any("Elevado" in titulo for titulo in titulos)
    assert any("Acima do preço base" in titulo or "acima do preço base" in titulo for titulo in titulos)
    assert "rede_pessoas" in titulos

    # O sinal «insolvencia» do motor de padrões não se repete: já há regra própria.
    assert "insolvencia" not in titulos

    severidades = [item["severidade"] for item in dados["atencao"]]
    assert severidades == sorted(severidades, key=lambda valor: motor.SEVERIDADE[valor])
    assert severidades[0] == "alerta"
    assert all(item["verificar"] for item in dados["atencao"])


def test_decisao_resume_tudo_e_escreve_a_leitura():
    dados = motor.decisao(_recolha())
    assert dados["nif"] == "500000000"
    assert dados["resumo"]["contratos"] == 4
    assert dados["resumo"]["valor_total"] == 1_160_000.0
    assert dados["resumo"]["adjudicantes"] == 2
    assert dados["resumo"]["hhi"] == 5213.8
    assert dados["resumo"]["taxa_ajuste_direto"] == 0.75
    assert dados["risco"]["nivel_label"] == "Elevado"
    assert len(dados["risco"]["componentes"]) == 2
    assert dados["cpv"][0]["cpv"] == "72000000"
    assert "4 contratos lidos" in dados["leitura"]
    assert "por ajuste direto" in dados["leitura"]
    assert "ponto(s) de atenção graves" in dados["leitura"]


def test_decisao_sem_contratos_nao_rebenta():
    dados = motor.decisao({"nif": "1", "nome": "Vazia", "secoes": {}, "kpis": {}})
    assert dados["resumo"]["contratos"] == 0
    assert dados["evolucao"] == []
    assert dados["concentracao"]["top"] == []
    assert dados["concentracao"]["hhi"] is None
    assert any(item["severidade"] == "info" for item in dados["atencao"])
    assert "Sem contratos lidos" in dados["leitura"]
    assert all(item["valor"] is None or 0 <= item["valor"] <= 100 for item in dados["perfil"])


def test_mencoes_no_cire_sem_insolvencia_nao_e_alerta():
    """Regressão: aparecer em milhares de processos como credor não é ser insolvente.

    O caso real que motivou a regra: a EDP tem milhares de menções no CIRE (cobra
    dívidas) e zero processos em que seja a insolvente. O painel tem de dar nota,
    não alerta.
    """
    recolha = _recolha()
    recolha["kpis"]["insolvencias"] = 0
    recolha["kpis"]["mencoes_cire"] = 8953
    dados = motor.decisao(recolha)

    assert dados["resumo"]["insolvencias"] == 0
    assert dados["resumo"]["mencoes_cire"] == 8953
    assert not any(item["severidade"] == "alerta" and "insolvente" in item["titulo"] for item in dados["atencao"])
    nota = next((item for item in dados["atencao"] if "credora" in item["titulo"]), None)
    assert nota is not None
    assert nota["severidade"] == "info"
    assert "8953" in nota["titulo"]


def test_empresa_nao_encontrada_e_alerta():
    recolha = _recolha()
    recolha["encontrada"] = False
    recolha["kpis"]["contratos"] = 0
    recolha["kpis"]["insolvencias"] = 0
    recolha["kpis"]["mencoes_cire"] = 0
    recolha["secoes"]["contratos"] = {"contratos": []}
    dados = motor.decisao(recolha)

    assert dados["encontrada"] is False
    assert any(
        item["severidade"] == "alerta" and "não encontrada" in item["titulo"] for item in dados["atencao"]
    )
