"""Testes do módulo «Publicidade da Composição da Massa Insolvente».

Cobrem o que não se pode partir sem se notar na página:

- o parser do portal (``fieldset#DetailViewer`` → anúncio, ativos e estado do
  paginador), incluindo valores em euros e datas ``dd/mm/aaaa HH:MM:SS``;
- a deteção do *delta* do ASP.NET Ajax na paginação (o portal só devolve o
  painel nesse formato);
- a divisão do intervalo em janelas e os ficheiros de recolha do serviço.

Não se fazem pedidos reais ao CITIUS: o HTML é sintético, com a mesma forma do
que o portal devolve.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collectors import citius_massa  # noqa: E402
from api import massa_insolvente_service as service  # noqa: E402


ANUNCIO = """
<fieldset id="DetailViewer" class="resultadopubvenda">
  <legend style="font-weight: bold;">Anúncio da composição da massa insolvente</legend>
  <strong>Processo: </strong>4680/26.9T8VNF - Insolvência pessoa singular (Apresentação)<br />
  <strong>Tribunal: </strong>Tribunal Judicial da Comarca de Braga - Juízo de Comércio de
  Vila Nova de Famalicão - Juiz 1<br />
  <span id="ctl00_ContentPlaceHolder1_dlVenda_ctl00_InsolventeDataList">
    <span><strong>Insolvente: </strong>João Paulo Ferreira Carvalho</span><br />
    <span><strong>Insolvente: </strong>Vera Cristina Gonçalves Dias</span>
  </span>
  <br />
  <strong>Área de negócio: </strong>Comércio, manutenção e reparação, de veículos automóveis<br />
  <strong>Valor da avaliação: </strong>30 000,01 €<br />
  <strong>Data da última atualização: </strong>20/10/2026 11:18:21<br />
  <h2>Descrição da massa insolvente: </h2>
  <div class="collapsiblecontent" style="max-height: 100%;">
    VERBA N.º 1
    Saldo da conta DO n.º 40323612565, titulada pela insolvente mulher.
    VERBA N.º 2
    Veículo automóvel marca Citroën, matrícula 74-DU-75.
  </div>
  <div class="collapsible" onclick="collapse(this)">Composição:</div>
  <div class="collapsiblecontent" style="max-height: 100%;">
    <span id="ctl00_ContentPlaceHolder1_dlVenda_ctl00_AtivosDataList">
      <span>
        <strong>Ativo: </strong>Veículo<br />
        Veículo automóvel marca Citroën, matrícula 74-DU-75.<br />
        <strong>Quantidade: </strong>1<br />
        <strong>Localização: </strong>Barcelos [Braga]<br />
      </span><br />
      <span>
        <strong>Ativo: </strong>Imóvel<br />
        Prédio urbano sito na Travessa de Paradela, n.º 19.<br />
        <strong>Quantidade: </strong>1<br />
        <strong>Localização: </strong>Braga [Braga]<br />
      </span>
    </span>
  </div>
</fieldset>
"""

PAGINA = """
<div id="ctl00_ContentPlaceHolder1_pnlResults">
  <div class="divisaopaginas">
    <div id="ctl00_ContentPlaceHolder1_Pager1_panel">
      <span id="ctl00_ContentPlaceHolder1_Pager1_lblPageNumber"
            title="Página&#32;actual:&#32;1" class="select">1</span>
      <a id="ctl00_ContentPlaceHolder1_Pager1_lnkNext"
         href="javascript:__doPostBack('ctl00$ContentPlaceHolder1$Pager1$lnkNext','')">2</a>
    </div>
  </div>
  <center><span id="ctl00_ContentPlaceHolder1_lblRecordCount">Número de Registos: 11</span></center>
  {anuncios}
</div>
""".replace("{anuncios}", ANUNCIO)


def test_parse_items_extrai_anuncio_e_ativos() -> None:
    itens = citius_massa.parse_items(PAGINA)
    assert len(itens) == 1
    anuncio = itens[0]

    assert anuncio.processo == "4680/26.9T8VNF - Insolvência pessoa singular (Apresentação)"
    assert anuncio.processo_numero == "4680/26.9T8VNF"
    assert anuncio.especie == "Insolvência pessoa singular (Apresentação)"
    assert anuncio.tipo == "Insolvência"
    assert anuncio.tribunal_comarca == "Braga"
    assert anuncio.juizo == "Juízo de Comércio de Vila Nova de Famalicão - Juiz 1"
    assert anuncio.insolventes == ["João Paulo Ferreira Carvalho", "Vera Cristina Gonçalves Dias"]
    assert anuncio.insolvente == "João Paulo Ferreira Carvalho; Vera Cristina Gonçalves Dias"
    assert anuncio.valor_avaliacao == pytest.approx(30000.01)
    assert anuncio.data_atualizacao == "2026-10-20T11:18:21"
    assert anuncio.descricao and "VERBA N.º 1" in anuncio.descricao

    assert [ativo.tipo for ativo in anuncio.ativos] == ["Veículo", "Imóvel"]
    assert anuncio.ativos[0].localizacao == "Barcelos [Braga]"
    assert anuncio.ativos[0].quantidade == "1"
    assert "Citroën" in (anuncio.ativos[0].descricao or "")
    assert anuncio.ativo_tipos == ["Imóvel", "Veículo"]
    assert anuncio.localizacoes == ["Barcelos [Braga]", "Braga [Braga]"]


def test_to_dict_remove_valores_vazios_e_mantem_o_texto() -> None:
    anuncio = citius_massa.parse_items(PAGINA)[0]
    doc = anuncio.to_dict()

    assert doc["pub_id"] == anuncio.pub_id
    assert doc["source"] == "citius_massa_insolvente"
    assert doc["valor_avaliacao"] == pytest.approx(30000.01)
    assert len(doc["ativos"]) == 2
    assert "Citroën" in doc["texto"]
    assert all(valor not in (None, "", [], {}) for valor in doc.values())


def test_pub_id_e_estavel_entre_leituras() -> None:
    primeiro = citius_massa.parse_items(PAGINA)[0].pub_id
    segundo = citius_massa.parse_items(PAGINA)[0].pub_id
    assert primeiro == segundo
    assert len(primeiro) == 40


def test_estado_do_paginador() -> None:
    assert citius_massa.result_count(PAGINA) == 11
    assert citius_massa.current_page(PAGINA) == 1
    assert citius_massa.has_next_page(PAGINA)
    assert not citius_massa.has_next_page("<div>sem paginador</div>")
    assert citius_massa.result_count("") == 0
    assert citius_massa.current_page("") == 1


def test_result_panel_le_html_completo_e_delta() -> None:
    completo = f'<html><body><div id="ctl00_ContentPlaceHolder1_pnlUpdResults">CONTEUDO</div></body></html>'
    assert "CONTEUDO" in citius_massa.result_panel(completo)

    delta = (
        "1|#||4|11|updatePanel|ctl00_ContentPlaceHolder1_pnlUpdResults|"
        "<div>DELTA</div>|"
    )
    assert "DELTA" in citius_massa.result_panel(delta)


def test_normalize_date_e_iso_date_aceitam_formatos_do_portal() -> None:
    assert citius_massa._iso_date("20/10/2026 11:18:21") == "2026-10-20T11:18:21"
    assert citius_massa._iso_date("20/10/2026") == "2026-10-20"
    assert citius_massa._iso_date("") is None
    assert citius_massa._br_date("2026-10-20") == "20/10/2026"
    assert citius_massa._br_date(None) is None


def test_parse_valor_aceita_formato_portugues() -> None:
    assert citius_massa._parse_valor("30 000,01 €") == pytest.approx(30000.01)
    assert citius_massa._parse_valor("2 000,00 €") == pytest.approx(2000.0)
    assert citius_massa._parse_valor("1.234,56 €") == pytest.approx(1234.56)
    assert citius_massa._parse_valor("") is None


def test_especie_tipo_classifica_processos() -> None:
    assert citius_massa._especie_tipo("Insolvência pessoa coletiva (Requerida)") == "Insolvência"
    assert citius_massa._especie_tipo("PER - Processo Especial de Revitalização") == "PER"
    assert citius_massa._especie_tipo("PEAP") == "PEAP"
    assert citius_massa._especie_tipo("PEVE") == "PEVE"
    assert citius_massa._especie_tipo("") is None


def test_patch_state_atualiza_viewstate() -> None:
    html = '<input type="hidden" name="__VIEWSTATE" id="__VIEWSTATE" value="ANTIGO" />'
    atualizado = citius_massa._patch_state(html, "__VIEWSTATE", "NOVO")
    assert 'value="NOVO"' in atualizado
    assert "ANTIGO" not in atualizado


def test_search_valida_as_datas_antes_de_pedir() -> None:
    with pytest.raises(ValueError):
        citius_massa.MassaInsolventeClient(min_interval=0.0).search(desde="2026-10-01")
    with pytest.raises(ValueError):
        citius_massa.MassaInsolventeClient(min_interval=0.0).search(
            desde="2026-10-20", ate="2026-10-01"
        )
    with pytest.raises(ValueError):
        citius_massa.MassaInsolventeClient(min_interval=0.0).search(dias="99")


def test_windows_do_servico_divide_o_intervalo() -> None:
    janelas = service._windows("2026-09-01", "2026-09-30", 10)
    assert janelas[0] == ("2026-09-21", "2026-09-30")
    assert janelas[-1][0] == "2026-09-01"
    assert all(a <= b for a, b in janelas)
    assert service._windows(None, None, 10) == [(None, None)]
    assert service._windows("2026-09-30", "2026-09-01", 10) == [("2026-09-30", "2026-09-01")]


def test_meta_aponta_para_o_indice_e_o_portal() -> None:
    meta = service.meta()
    assert meta["index"] == "finance_massa_insolvente"
    assert meta["source_url"].endswith("PublicidadeMassaInsolvente.aspx")
    assert meta["page_size"] == 10
    assert meta["dias"] == [{"value": "15", "label": "Últimos 15 dias"}]
