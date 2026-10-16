"""Testes dos templates de contratação pública (Find a Tender e Contracts Finder).

Os dois portais britânicos partilham a família de páginas do Gov.uk, mas não a
ficha de cada aviso: o Find a Tender usa `dt`/`dd` e o Contracts Finder guarda o
valor no texto do contentor, ao lado do rótulo. Os testes fixam as duas decisões
que essa diferença obrigou a tomar:

* os campos procuram-se **pelo rótulo** (`xpath`), porque os avisos de
  adjudicação publicam menos linhas do que os de concurso — um seletor por
  posição lia o adjudicatário no lugar do prazo;
* o `valor` fica em **texto**, porque o `cast: "float"` do motor trata a vírgula
  como separador decimal e leria «£8,944,853.06» como 8,9.

O `resumo` é o `div.wrap-text` que não é o sub-cabeçalho — o comprador também usa
`wrap-text` e chegava primeiro.
"""
from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from api import scraper_service as scraper  # noqa: E402
from api import scraper_templates as templates  # noqa: E402

FIND_A_TENDER = """
<div class="search-result">
  <div class="search-result-header" title="Supply of Supplementary Drive Detectors">
    <h2>
      <a class="govuk-link search-result-rwh" href="https://www.find-tender.service.gov.uk/Notice/097962-2026?origin=SearchResults&amp;p=1">
        Supply of Supplementary Drive Detectors, Clamplocks and Spares
      </a>
    </h2>
  </div>
  <div class="search-result-sub-header wrap-text">London Underground Limited</div>
  <div class="search-result-spacer"></div>
  <div class="wrap-text">Direct award for the supply of detectors, Clamplocks and spares.</div>
  <div class="search-result-spacer"></div>
  <dl>
    <div class="search-result-entry">
      <dt><strong>Notice type</strong></dt>
      <dd>UK5: Transparency notice</dd>
    </div>
    <div class="search-result-entry">
      <dt><strong>Total value including VAT</strong></dt>
      <dd>£8,944,853.06</dd>
    </div>
    <div class="search-result-entry">
      <dt><strong>Contract location</strong></dt>
      <dd>UK - United Kingdom</dd>
    </div>
    <div class="search-result-entry">
      <dt><strong>Submission deadline</strong></dt>
      <dd>30 October 2026,  4:00pm</dd>
    </div>
    <div class="search-result-entry">
      <dt><strong>Publication date</strong></dt>
      <dd>16 October 2026,  1:01pm</dd>
    </div>
  </dl>
</div>
<div class="search-result">
  <div class="search-result-header" title="Temporary Accommodation at Paragon House">
    <h2>
      <a class="govuk-link search-result-rwh" href="https://www.find-tender.service.gov.uk/Notice/097963-2026?origin=SearchResults&amp;p=1">
        Temporary Accommodation at Paragon House
      </a>
    </h2>
  </div>
  <div class="search-result-sub-header wrap-text">Chelmsford City Council</div>
  <div class="search-result-spacer"></div>
  <div class="wrap-text">Direct Award under PA23 to provide nightly let accommodation.</div>
  <div class="search-result-spacer"></div>
  <dl>
    <div class="search-result-entry">
      <dt><strong>Notice type</strong></dt>
      <dd>UK6: Contract award notice</dd>
    </div>
    <div class="search-result-entry">
      <dt><strong>Contract location</strong></dt>
      <dd>UKH3 - Essex</dd>
    </div>
    <div class="search-result-entry">
      <dt><strong>Publication date</strong></dt>
      <dd>16 October 2026,  1:33pm</dd>
    </div>
  </dl>
</div>
"""

CONTRACTS_FINDER = """
<div class="search-result">
  <div class="search-result-header" title="Arboricultural services - Tree works operations">
    <h2 id="c608b122-b81f-4d6f-91d2-db6ba6bb1517">
      <a class="govuk-link search-result-rwh" href="https://www.contractsfinder.service.gov.uk/notice/c608b122-b81f-4d6f-91d2-db6ba6bb1517?origin=SearchResults&amp;p=1">
        Arboricultural services - Tree works operations
      </a>
    </h2>
  </div>
  <div class="search-result-sub-header wrap-text">London Borough Of Islington</div>
  <div class="search-result-spacer"></div>
  <div class="wrap-text">13686 DTH 2026-27 Final Set. Tree and stump removal.</div>
  <div class="search-result-spacer"></div>
  <div class="search-result-entry"><strong>Procurement stage</strong>Opportunity</div>
  <div class="search-result-entry"><strong>Notice status</strong>Open</div>
  <div class="search-result-entry"><strong>Closing</strong>23 October 2026, 12pm</div>
  <div class="search-result-entry"><strong>Contract location</strong>United Kingdom</div>
  <div class="search-result-entry"><strong>Contract value</strong>£42,000</div>
  <div class="search-result-entry"><strong>Publication date</strong>16 October 2026</div>
</div>
"""


def _pagina(html: str):
    from scrapling.parser import Adaptor

    return Adaptor(html, url="https://www.find-tender.service.gov.uk/Search/Results")


# ------------------------------------------------------------------ catálogo
def test_os_dois_templates_estao_na_categoria_de_contratacao_publica():
    categoria = "Contratação pública (UE e Reino Unido)"
    assert categoria in templates.CATEGORIES
    for template_id in ("find-a-tender", "contracts-finder"):
        resumo = templates.get_template(template_id)
        assert resumo is not None, template_id
        assert resumo["category"] == categoria
        assert resumo["requires"] == "http"
        assert resumo["requires_browser"] is False


def test_paginacao_por_parametro_de_url():
    for template_id in ("find-a-tender", "contracts-finder"):
        pagination = templates.build_source(template_id)["pagination"]
        assert pagination["mode"] == "query"
        assert pagination["param"] == "page"
        assert pagination["start"] == 1


# -------------------------------------------------------------- Find a Tender
def test_find_a_tender_le_os_campos_pelo_rotulo():
    source = templates.build_source("find-a-tender")
    items = scraper._extract_items(_pagina(FIND_A_TENDER), source)
    assert len(items) == 2

    primeiro = items[0]
    assert primeiro["title"] == "Supply of Supplementary Drive Detectors, Clamplocks and Spares"
    assert primeiro["url"] == "https://www.find-tender.service.gov.uk/Notice/097962-2026?origin=SearchResults&p=1"
    dados = primeiro["data"]
    assert dados["comprador"] == "London Underground Limited"
    assert dados["tipo_aviso"] == "UK5: Transparency notice"
    assert dados["local"] == "UK - United Kingdom"
    assert dados["prazo"] == "30 October 2026,  4:00pm"
    # A data é normalizada para `AAAA-MM-DD` (mesmo com a hora à frente).
    assert dados["publicado"] == "2026-10-16"


def test_find_a_tender_resumo_e_a_descricao_e_nao_o_comprador():
    source = templates.build_source("find-a-tender")
    items = scraper._extract_items(_pagina(FIND_A_TENDER), source)
    assert items[0]["data"]["resumo"].startswith("Direct award for the supply of detectors")
    assert items[0]["data"]["comprador"] == "London Underground Limited"


def test_find_a_tender_valor_fica_em_texto_para_nao_ler_8_9():
    source = templates.build_source("find-a-tender")
    items = scraper._extract_items(_pagina(FIND_A_TENDER), source)
    assert items[0]["data"]["valor"] == "£8,944,853.06"


def test_find_a_tender_aviso_de_adjudicacao_nao_inventa_o_prazo():
    """O aviso de adjudicação não publica prazo nem valor: os campos ficam vazios."""
    source = templates.build_source("find-a-tender")
    items = scraper._extract_items(_pagina(FIND_A_TENDER), source)
    adjudicacao = items[1]["data"]
    assert adjudicacao["tipo_aviso"] == "UK6: Contract award notice"
    assert adjudicacao["local"] == "UKH3 - Essex"
    assert "prazo" not in adjudicacao
    assert "valor" not in adjudicacao


# ------------------------------------------------------------ Contracts Finder
def test_contracts_finder_le_os_campos_do_contentor():
    source = templates.build_source("contracts-finder")
    itens = scraper._extract_items(_pagina(CONTRACTS_FINDER), source)
    assert len(itens) == 1
    dados = itens[0]["data"]
    assert itens[0]["title"] == "Arboricultural services - Tree works operations"
    assert dados["comprador"] == "London Borough Of Islington"
    assert dados["resumo"].startswith("13686 DTH 2026-27 Final Set.")
    assert dados["fase"] == "Opportunity"
    assert dados["estado"] == "Open"
    assert dados["encerra"] == "2026-10-23"
    assert dados["local"] == "United Kingdom"
    assert dados["valor"] == "£42,000"
    assert dados["publicado"] == "2026-10-16"


def test_contracts_finder_identidade_do_item_e_a_ligacao():
    source = templates.build_source("contracts-finder")
    assert source["id_fields"] == ["url"]
    item = scraper._extract_items(_pagina(CONTRACTS_FINDER), source)[0]
    assert item["item_id"].split(":")[0].startswith("contracts-finder")
    # Repetir a recolha atualiza o mesmo item, não cria outro.
    repetido = scraper._extract_items(_pagina(CONTRACTS_FINDER), source)[0]
    assert repetido["item_id"] == item["item_id"]
