"""Grandes Litigantes — Portaria 200/2011 e artigo 13.º do RCP.

Testam-se os componentes que não dependem da rede nem do Elasticsearch:
- normalização de faixas (`faixa_de`);
- deteção do total e paginação no HTML;
- extração de linhas da grelha do portal;
- construção do identificador e serialização JSON.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from collectors import citius_200_acoes as scraper


class TestFaixaDe:
    def test_faixa_entre_201_e_500(self) -> None:
        f = scraper.faixa_de("Entre 201 e 500")
        assert f["faixa"] == "201-500"
        assert f["label"] == "Entre 201 e 500"
        assert f["acoes_min"] == 201
        assert f["numero"] == 201

    def test_faixa_501_ou_superior(self) -> None:
        f = scraper.faixa_de("501 ou superior")
        assert f["faixa"] == "501+"
        assert f["label"] == "501 ou superior"
        assert f["acoes_min"] == 501
        assert f["numero"] == 501

    def test_faixa_maiusculas_e_acentos(self) -> None:
        f = scraper.faixa_de("  ENTRE 201 E 500 ")
        assert f["faixa"] == "201-500"

    def test_faixa_texto_vazio_cai_no_default(self) -> None:
        f = scraper.faixa_de("")
        assert f["faixa"] == "201-500"
        assert f["numero"] is None

    def test_faixa_texto_com_numero_soltos(self) -> None:
        f = scraper.faixa_de("Há 900 processos")
        assert f["faixa"] == "501+"
        assert f["numero"] == 900


class TestParsingHtml:
    HTML_AMOSTRA = """
    <form id="aspnetForm">
        <input type="hidden" name="__VIEWSTATE" id="__VIEWSTATE" value="VS" />
        <input type="hidden" name="__VIEWSTATEGENERATOR" id="__VIEWSTATEGENERATOR" value="GEN" />
        <input type="hidden" name="__EVENTVALIDATION" id="__EVENTVALIDATION" value="EV" />
        <input type="text" name="ctl00$ContentPlaceHolder1$txtPesquisa" value="Banco" />
    </form>
    <div id="ctl00_ContentPlaceHolder1_Pager1_lblPageNumber">1</div>
    <div>82 entidades encontradas</div>
    <a id="ctl00_ContentPlaceHolder1_Pager1_lnkNext" href="javascript:__doPostBack">Seguinte</a>
    <table id="ctl00_ContentPlaceHolder1_grdView">
        <tr>
            <th>NIPC</th><th>Denominação</th><th>Acções, procedimentos ou execuções</th><th>Ano</th>
        </tr>
        <tr>
            <td class="cellGridDistrib">501525882</td>
            <td class="cellGridDistrib">Banco Comercial Português, S.A.</td>
            <td class="cellGridDistrib">Entre 201 e 500</td>
            <td class="cellGridDistrib">2025</td>
        </tr>
        <tr>
            <td class="cellGridDistrib">504658985</td>
            <td class="cellGridDistrib">NOS&nbsp;Comunicações, S.A.</td>
            <td class="cellGridDistrib">501 ou superior</td>
            <td class="cellGridDistrib">2025</td>
        </tr>
    </table>
    """

    def test_form_state_extra_viewstate(self) -> None:
        estado = scraper.form_state(self.HTML_AMOSTRA)
        assert estado["__VIEWSTATE"] == "VS"
        assert estado["__VIEWSTATEGENERATOR"] == "GEN"
        assert estado["__EVENTVALIDATION"] == "EV"
        assert "__EVENTTARGET" in estado
        assert "__VIEWSTATEENCRYPTED" in estado

    def test_text_value_preserva_termo(self) -> None:
        assert scraper.text_value(self.HTML_AMOSTRA, scraper.FIELD_TERMO) == "Banco"

    def test_parse_total(self) -> None:
        assert scraper.parse_total(self.HTML_AMOSTRA) == 82

    def test_page_number(self) -> None:
        assert scraper.page_number(self.HTML_AMOSTRA) == 1

    def test_has_next_page(self) -> None:
        assert scraper.has_next_page(self.HTML_AMOSTRA) is True

    def test_parse_rows(self) -> None:
        rows = scraper.parse_rows(self.HTML_AMOSTRA)
        assert len(rows) == 2
        assert rows[0]["nipc"] == "501525882"
        assert rows[0]["denominacao"] == "Banco Comercial Português, S.A."
        assert rows[0]["faixa"] == "201-500"
        assert rows[0]["ano"] == 2025
        assert rows[1]["nipc"] == "504658985"
        assert rows[1]["denominacao"] == "NOS Comunicações, S.A."
        assert rows[1]["faixa"] == "501+"
        assert rows[1]["faixa_label"] == "501 ou superior"

    def test_parse_rows_sem_linhas_validas_devolve_vazio(self) -> None:
        assert scraper.parse_rows("<html></body></html>") == []

    def test_parse_rows_ignora_linha_vazia(self) -> None:
        html = """
        <table>
            <tr>
                <td class="cellGridDistrib"></td>
                <td class="cellGridDistrib"></td>
                <td class="cellGridDistrib"></td>
                <td class="cellGridDistrib"></td>
            </tr>
            <tr>
                <td class="cellGridDistrib">123456789</td>
                <td class="cellGridDistrib">X, Lda.</td>
                <td class="cellGridDistrib">Entre 201 e 500</td>
                <td class="cellGridDistrib">2024</td>
            </tr>
        </table>
        """
        rows = scraper.parse_rows(html)
        assert len(rows) == 1
        assert rows[0]["ano"] == 2024

    def test_blocked_detecta_waf(self) -> None:
        assert scraper._blocked("<html>Access denied</html>") is True
        assert scraper._blocked("<html>Request rejected</html>") is True
        assert scraper._blocked(self.HTML_AMOSTRA) is False


class TestUtilidades:
    def test_clean_remove_tags_e_entidades(self) -> None:
        assert scraper._clean(" <p>A &amp; B  </p>  ") == "A & B"

    def test_fold_remove_acentos(self) -> None:
        assert scraper.fold("Áção ÚNICA") == "acao unica"

    def test_faixa_de_nao_mutua_dict(self) -> None:
        f1 = scraper.faixa_de("Entre 201 e 500")
        f2 = scraper.faixa_de("501 ou superior")
        assert f1["numero"] == 201
        assert f2["numero"] == 501
        assert scraper.FAIXAS["201-500"]["acoes_min"] == 201


class TestSerializacao:
    def test_registo_e_serializavel_em_json(self) -> None:
        rows = scraper.parse_rows(TestParsingHtml.HTML_AMOSTRA)
        payload = json.dumps(rows, ensure_ascii=False, default=str)
        loaded = json.loads(payload)
        assert loaded[0]["nipc"] == "501525882"
        assert loaded[0]["ano"] == 2025


@pytest.fixture
def html_sem_paginador():
    return """
    <div id="ctl00_ContentPlaceHolder1_Pager1_lblPageNumber">3</div>
    <div>60 entidades encontradas</div>
    <table id="ctl00_ContentPlaceHolder1_grdView">
        <tr>
            <td class="cellGridDistrib">987654321</td>
            <td class="cellGridDistrib">Y, S.A.</td>
            <td class="cellGridDistrib">501 ou superior</td>
            <td class="cellGridDistrib">2023</td>
        </tr>
    </table>
    """


class TestPaginacaoFinal:
    def test_ultima_pagina_sem_lnk_next(self, html_sem_paginador: str) -> None:
        assert scraper.has_next_page(html_sem_paginador) is False
        assert scraper.parse_total(html_sem_paginador) == 60
        assert scraper.page_number(html_sem_paginador) == 3
