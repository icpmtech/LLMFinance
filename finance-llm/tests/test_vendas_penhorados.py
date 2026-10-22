"""Testes unitários do coletor de vendas de bens penhorados.

Testam a normalização, parsing e transformação sem tocar na rede.
"""
from __future__ import annotations

import json

import pytest

from collectors.vendas_penhorados import (
    VendaPenhorada,
    _iso_from_ddmmyyyy,
    _pairs,
    _pt_number,
    _split_processo,
    parse_details,
    parse_items,
)


def test_iso_from_ddmmyyyy():
    assert _iso_from_ddmmyyyy("22/10/2026") == "2026-10-22"
    assert _iso_from_ddmmyyyy("22/10/2026 13:45:00", with_time=True) == "2026-10-22T13:45:00"
    assert _iso_from_ddmmyyyy(None) is None
    assert _iso_from_ddmmyyyy("não é data") == "não é data"


def test_pt_number_converte_formato_portugues():
    assert _pt_number("220 000,00 €") == 220000.0
    assert _pt_number("1.234,56") == 1234.56
    assert _pt_number("1000") == 1000.0
    assert _pt_number("") is None
    assert _pt_number(None) is None


def test_split_processo():
    assert _split_processo("7150/24.6T8PRT, Juízo de Execução do Porto - Juiz 5") == (
        "7150/24.6T8PRT",
        "Juízo de Execução do Porto - Juiz 5",
    )
    assert _split_processo(None) == (None, None)


def test_pairs_extrait_pares_strong():
    html = "<strong>Tribunal: </strong>Porto<br /> <strong>Valor Base: </strong>220 000,00 €<br />"
    assert _pairs(html) == {"Tribunal": "Porto", "Valor Base": "220 000,00 €"}


def test_parse_details_completo():
    html = """
    <h1>Detalhes do bem</h1>
    <div>
        <strong>Tribunal:&#160;</strong>Porto - Tribunal Judicial da Comarca do Porto<br />
        <strong>Processo:&#160;</strong>7150/24.6T8PRT - Juízo de Execução do Porto - Juiz 5<br />
        <strong>Espécie:&#160;</strong>Execução Sumária (Of. Justiça)<br />
        <strong>Tipo de Bem:&#160;</strong>Imóvel<br />
        <strong>Valor Base:&#160;</strong>220 000,00 €<br />
        <strong>Descrição do Bem:&#160;</strong>Prédio urbano sito em Grijó.<br />
        <strong>Data da Venda:&#160;</strong>22/10/2026 13:45:00<br />
    </div>
    <h2>Intervenientes</h2>
    <div>
        <strong>Interveniente:&#160;</strong>Executado<br />
        <strong>Nome:&#160;</strong>António Silva<br />
        <strong>Morada:&#160;</strong>Rua A, 1<br />
        <strong>Telefone:&#160;</strong>912345678<br />
    </div>
    """
    dados = parse_details(html)
    assert dados["tribunal"] == "Porto - Tribunal Judicial da Comarca do Porto"
    assert dados["processo_numero"] == "7150/24.6T8PRT"
    assert dados["juizo"] == "Juízo de Execução do Porto - Juiz 5"
    assert dados["tipo_bem"] == "Imóvel"
    assert dados["valor_base"] == 220000.0
    assert dados["data_venda"] == "2026-10-22T13:45:00"
    assert len(dados["intervenientes"]) == 1
    assert dados["intervenientes"][0]["papel"] == "Executado"
    assert dados["intervenientes"][0]["nome"] == "António Silva"


def test_parse_items_cria_venda_id():
    panel = '''
    <div class="resultadopubvenda">
        <strong>Tipo de Bem:</strong> Imóvel<br />
        <strong>Estado:</strong> Em venda<br />
        <strong>Valor Base: </strong> 220 000,00 €<br />
        <strong>Modalidade: </strong> Venda por negociação<br />
        <strong>Descrição do Bem: </strong> Prédio.<br />
        <strong>Processo: </strong> 7150/24.6T8PRT, Juízo de Execução - Juiz 5<br />
        <strong>Espécie: </strong> Execução Sumária<br />
        <strong>Data da Venda: </strong>22/10/2026 13:45:00<br />
        <a onclick="javascript:Viewer.Abrir(this, 12345, 'ConsultasVenda.aspx/GetHtmlDetails', 'btnFechar','viewer')">ver mais</a>
    </div>
    '''
    items = parse_items(panel, tribunal="Porto - Tribunal Judicial da Comarca do Porto")
    assert len(items) == 1
    item = items[0]
    assert item.venda_id == "citius:12345"
    assert item.fonte == "citius"
    assert item.valor_base == 220000.0
    assert item.data_venda == "2026-10-22T13:45:00"


def test_venda_penhorada_to_dict_remove_vazios():
    item = VendaPenhorada(venda_id="x", fonte="citius", valor_base=None, descricao="desc")
    doc = item.to_dict()
    assert "valor_base" not in doc
    assert doc["descricao"] == "desc"


def test_venda_penhorada_pub_id_estavel():
    item = VendaPenhorada(venda_id="", fonte="citius", referencia="r1", processo="p1", data_venda="2026-10-22", titulo="t1")
    assert item.pub_id == item.pub_id
    assert len(item.pub_id) == 40  # sha1 hex
