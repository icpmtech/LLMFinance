"""Custo de vida por concelho: recolha, orçamento, índice e página.

Testa-se o que não depende da rede nem do Elasticsearch:

* os leitores das fontes (percentagens do IMI com vírgula, preços da DGEG,
  folhas de tarifas da ERSE) com ficheiros e respostas sintéticas;
* a escolha do concelho certo quando o nome se repete (Calheta e Lagoa);
* o orçamento mensal e o índice (100 = mediana nacional);
* os blocos da página — que os dados vão embutidos e que a tabela tem as
  colunas dos componentes que passaram a existir.
"""
from __future__ import annotations

import io

import pytest

from api import custo_vida_pagina as pagina
from api import custo_vida_service as servico
from collectors import custo_vida as recolha


# ---------------------------------------------------------------------------
# Leitores das fontes
# ---------------------------------------------------------------------------

def test_percent_aceita_virgula_e_branco() -> None:
    assert recolha._percent("0,324 %") == pytest.approx(0.324)
    assert recolha._percent("") is None
    assert recolha._percent(None) is None


def test_price_aceita_formato_do_portal_da_dgeg() -> None:
    assert recolha._price("1,879 €") == pytest.approx(1.879)
    assert recolha._price("") is None


def test_recolher_imi_guarda_branco_como_none() -> None:
    csv_sintetico = (
        "codigo,municipality,municipality_as_published,distrito,urban_percent,rural_percent,year\n"
        "1602,Caminha,CAMINHA,Viana do Castelo,\"0,324 %\",\"0,8 %\",2025\n"
        "0110,Aguiar da Beira,AGUIAR DA BEIRA,Guarda,,,2025\n"
    )

    class _Resposta:
        text = csv_sintetico

        def raise_for_status(self) -> None:
            return None

    class _Sessao:
        def get(self, *args, **kwargs):  # noqa: ANN002, ANN003
            return _Resposta()

    dados = recolha.recolher_imi(session=_Sessao())
    assert dados["concelhos"] == 2
    assert dados["ano"] == 2025
    assert dados["sem_taxa_unica"] == 1
    assert dados["por_concelho"]["caminha"]["urbana_pct"] == pytest.approx(0.324)
    assert dados["por_concelho"]["aguiar da beira"]["urbana_pct"] is None


def test_recolher_gasoleo_faz_mediana_por_concelho() -> None:
    postos = {
        "resultado": [
            {"Municipio": "Caminha", "Preco": "1,700 €", "DataAtualizacao": "2026-10-26 10:00"},
            {"Municipio": "Caminha", "Preco": "1,900 €", "DataAtualizacao": "2026-10-27 10:00"},
            {"Municipio": "Caminha", "Preco": "1,800 €", "DataAtualizacao": "2026-10-25 10:00"},
        ]
    }

    class _Resposta:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return postos

    class _Sessao:
        def get(self, *args, **kwargs):  # noqa: ANN002, ANN003
            return _Resposta()

    dados = recolha.recolher_gasoleo(session=_Sessao(), por_pagina=10)
    assert dados["concelhos"] == 1
    assert dados["leitura"] == "2026-10-27"
    assert dados["por_concelho"]["caminha"]["preco_l"] == pytest.approx(1.8)
    assert dados["por_concelho"]["caminha"]["postos"] == 3


def test_ler_eletricidade_do_ficheiro_da_erse(tmp_path) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    livro = openpyxl.Workbook()
    folha = livro.active
    folha.title = "TVCFtrans_CUR_Continente_BT"
    folha.append(["TARIFA TRANSITÓRIA DE VENDA A CLIENTES FINAIS"])
    folha.append([])
    folha.append(["TARIFA TRANSITÓRIA DE VENDA A CLIENTES FINAIS", "EM BTN (≤20,7 kVA e >2,3 kVA)", "PREÇOS"])
    folha.append(["Potência contratada", "EUR/dia"])
    folha.append(["Tarifa simples, bi-horária e tri-horária", 3.45, 0.1917])
    folha.append([])
    folha.append(["Energia ativa", "EUR/kWh"])
    folha.append(["Tarifa simples", 0.1711])
    folha.append(["Tarifa bi-horária", "Horas de vazio", 0.1143])
    caminho = tmp_path / "eletricidade.xlsx"
    livro.save(caminho)

    lido = recolha._ler_eletricidade(caminho)
    assert lido["termo_fixo_dia"] == pytest.approx(0.1917)
    # A linha das potências também começa por «Tarifa simples»: se o leitor não
    # separar as secções, apanha 0,1917 €/dia como se fosse €/kWh.
    assert lido["energia_kwh"] == pytest.approx(0.1711)


def test_ler_gas_do_ficheiro_da_erse(tmp_path) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    livro = openpyxl.Workbook()
    folha = livro.active
    folha.title = "TarifaTransitoria"
    folha.append(["Escalão", "m³/ano", "EUR/dia", "EUR/kWh"])
    folha.append(["Escalão 1", "0 - 220", 0.0839, 0.0638])
    caminho = tmp_path / "gas.xlsx"
    livro.save(caminho)

    lido = recolha._ler_gas(caminho)
    assert lido["termo_fixo_dia"] == pytest.approx(0.0839)
    assert lido["energia_kwh"] == pytest.approx(0.0638)


# ---------------------------------------------------------------------------
# Identificação do concelho
# ---------------------------------------------------------------------------

def test_escolher_desambigua_calheta_e_lagoa_pela_regiao() -> None:
    candidatos = [
        {"concelho": "Calheta (Açores)", "distrito": "Angra do Heroísmo", "urbana_pct": 0.3},
        {"concelho": "Calheta (Madeira)", "distrito": "Funchal", "urbana_pct": 0.3},
    ]
    assert servico._escolher(candidatos, "", "Calheta (R.A.A.)")["concelho"] == "Calheta (Açores)"
    assert servico._escolher(candidatos, "Região Autónoma da Madeira", "Calheta (R.A.M.)")["concelho"] == \
        "Calheta (Madeira)"

    lagoas = [
        {"concelho": "Lagoa (Algarve)", "distrito": "Faro", "urbana_pct": 0.36},
        {"concelho": "Lagoa (Açores)", "distrito": "Ponta Delgada", "urbana_pct": 0.3},
    ]
    assert servico._escolher(lagoas, "Faro", "Lagoa")["concelho"] == "Lagoa (Algarve)"
    assert servico._escolher(lagoas, "", "Lagoa (R.A.A.)")["concelho"] == "Lagoa (Açores)"


def test_escolher_nao_da_o_preco_da_madeira_aos_acores() -> None:
    """A DGEG escreve «Calheta» sem região: o distrito do posto decide."""
    candidatos = [{"concelho": "Calheta", "distrito": "Madeira", "preco_l": 2.31}]
    assert servico._escolher(candidatos, "Região Autónoma da Madeira", "Calheta (R.A.M.)") is not None
    assert servico._escolher(candidatos, "Região Autónoma dos Açores", "Calheta (R.A.A.)") is None


def test_chave_nome_tolera_grafias() -> None:
    assert servico._chave_nome("Vila da Praia da Vitória") == servico._chave_nome("Praia da Vitória")
    assert servico._chave_nome("Bragança") == servico._chave_nome("Braganca")


# ---------------------------------------------------------------------------
# Orçamento e índice
# ---------------------------------------------------------------------------

def _componentes() -> dict:
    return {
        "recolhido_em": "2026-10-28T00:00:00+00:00",
        "imi": {
            "fonte": "AT",
            "url": "https://exemplo/imi.csv",
            "licenca": "CC BY 4.0",
            "ano": 2025,
            "sem_taxa_unica": 8,
            "por_concelho": {
                "caminha": {"concelho": "Caminha", "distrito": "Viana do Castelo", "urbana_pct": 0.3},
            },
        },
        "gasoleo": {
            "fonte": "DGEG",
            "url": "https://exemplo/dgeg",
            "leitura": "2026-10-28",
            "por_concelho": {"caminha": {"concelho": "Caminha", "preco_l": 2.0, "postos": 4}},
        },
        "erse": {
            "eletricidade": {"termo_fixo_dia": 0.1917, "energia_kwh": 0.1711},
            "gas": {"termo_fixo_dia": 0.0839, "energia_kwh": 0.0638},
        },
    }


def test_construir_calcula_orcamento_e_indice() -> None:
    resultado = servico.construir(_componentes())
    docs = {doc["nome"]: doc for doc in resultado["docs"]}
    assert len(docs) == 308

    caminha = docs["Caminha"]
    eletricidade = servico.KWH_ANO / 12 * 0.1711 + 0.1917 * servico.DIAS_MES
    gas = servico.GAS_M3_ANO * servico.KWH_POR_M3_GAS / 12 * 0.0638 + 0.0839 * servico.DIAS_MES
    imi_mes = servico.VPT_REFERENCIA * 0.3 / 100 / 12
    esperado = caminha["renda_m2"] * servico.TIPOLOGIAS["T2"] + 2.0 * servico.LITROS_MES + eletricidade + gas + imi_mes
    assert caminha["custo"]["T2"] == pytest.approx(esperado, abs=0.05)
    assert caminha["imi_pct"] == pytest.approx(0.3)
    assert caminha["eletricidade_mensal"] == pytest.approx(round(eletricidade, 2))
    assert "imi" in caminha["cobertura"]

    # 100 é a mediana nacional, por construção.
    assert resultado["meta"]["custo_mediano"] is not None
    indices = [doc["indice"] for doc in resultado["docs"] if doc["indice"] is not None]
    assert min(indices) < 100 < max(indices)
    assert docs[resultado["meta"]["concelho_mais_caro"]]["indice"] == max(indices)


def test_concelhos_sem_renda_ficam_sem_custo_e_sem_indice() -> None:
    resultado = servico.construir(_componentes())
    sem_renda = [doc for doc in resultado["docs"] if doc["renda_m2"] is None]
    assert sem_renda, "a base tem concelhos com renda suprimida pelo INE"
    for doc in sem_renda:
        assert doc["custo"]["T2"] is None
        assert doc["indice"] is None
        assert doc["indice_posicao"] is None


def test_concelho_sem_posto_na_recolha_fica_sem_gasoleo() -> None:
    """A recolha da DGEG manda: sem posto com preço, não se reaproveita a base."""
    componentes = _componentes()
    componentes["gasoleo"]["por_concelho"] = {}  # recolha feita, mas sem postos
    resultado = servico.construir(componentes)
    caminha = next(doc for doc in resultado["docs"] if doc["nome"] == "Caminha")
    assert caminha["gasoleo_l"] is None
    assert "gasoleo" not in caminha["cobertura"]


def test_imi_em_branco_nao_e_zero() -> None:
    componentes = _componentes()
    componentes["imi"]["por_concelho"]["caminha"]["urbana_pct"] = None
    resultado = servico.construir(componentes)
    caminha = next(doc for doc in resultado["docs"] if doc["nome"] == "Caminha")
    assert caminha["imi_pct"] is None
    assert caminha["imi_anual"] is None
    assert "imi" not in caminha["cobertura"]


# ---------------------------------------------------------------------------
# Página
# ---------------------------------------------------------------------------

def test_blocos_trazem_os_componentes_novos() -> None:
    resultado = servico.construir(_componentes())
    blocos = pagina.blocos(resultado["docs"], resultado["meta"])
    assert [bloco["id"] for bloco in blocos] == ["cv_01_mapa", "cv_02_metodologia", "cv_03_fontes"]

    mapa = blocos[0]["data"]["markdown"]
    assert "const CV = [" in mapa
    for coluna in ("Eletricidade", "Gás", "IMI/ano", "Índice"):
        assert coluna in mapa
    # Os dados vão embutidos: a página não pode depender de um fetch para ter números.
    assert "fetch(" not in mapa

    metodologia = blocos[1]["data"]["markdown"]
    assert "Índice de custo de vida" in metodologia
    assert "O que fica de fora" in metodologia
    assert "Água, saneamento e resíduos" in metodologia

    fontes = blocos[2]["data"]
    assert fontes["tone"] == "nota"
    assert "DGEG" in fontes["text"] and "ERSE" in fontes["text"]


def test_bloco_mapa_e_json_valido() -> None:
    import json
    import re

    resultado = servico.construir(_componentes())
    mapa = pagina.blocos(resultado["docs"], resultado["meta"])[0]["data"]["markdown"]
    bruto = re.search(r"const CV = (\[.*?\]);", mapa, re.S)
    assert bruto is not None
    linhas = json.loads(bruto.group(1))
    assert len(linhas) == 308
    assert set(linhas[0]) == {"n", "d", "nu", "p", "r", "g", "i", "ia", "e", "z", "x", "k", "dp", "lat", "lon"}
