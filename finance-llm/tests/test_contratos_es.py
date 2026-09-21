"""Testes do pipeline de contratos públicos de Espanha (PLACSP).

Correr com:

    c:\\LLMFinance\\.venv\\Scripts\\python.exe -m pytest tests/test_contratos_es.py -q

Cobrem três coisas que já partiram ou que são fáceis de partir:
1. os rótulos oficiais das listas de códigos CODICE em `data/contratos-espanha/codigos`;
2. a normalização de uma entrada Atom do PLACSP (documento plano para o Elasticsearch);
3. o filtro de valor e a construção da query de pesquisa no cliente Elasticsearch.
"""
from __future__ import annotations

import hashlib
from xml.etree import ElementTree as ET

import pytest

from api import elasticsearch_client as es_client
from collectors import contratos_es as pipeline

# --------------------------------------------------------------- listas de códigos
def test_rotulos_de_tipo_de_contrato() -> None:
    """`ContractCode-2.08.gc` tem de dar os rótulos em espanhol (não os ingleses)."""
    tipos = pipeline.label_map("ContractCode-2.08")
    assert tipos["1"] == "Suministros"
    assert tipos["2"] == "Servicios"
    assert tipos["3"] == "Obras"
    assert tipos["8"] == "Privado"


def test_rotulos_de_estado_e_resultado() -> None:
    """O estado vem do feed (`SyndicationContractFolderStatusCode`); o resultado da lista CODICE."""
    assert pipeline.ESTADO_LABELS["RES"] == "Resuelta"
    assert pipeline.ESTADO_LABELS["PUB"] == "En plazo"
    resultados = pipeline.label_map("TenderResultCode-2.09")
    assert resultados["8"] == "Adjudicado"
    assert pipeline.label_map("SyndicationTenderingProcessCode-2.07")["6"] == "Contrato menor"


def test_descricao_cpv_da_lista_oficial() -> None:
    """A lista CPV2008 (3,3 MB) tem de carregar e descrever códigos reais."""
    cpv = pipeline.label_map("CPV2008-2.04")
    assert cpv["48952000"] == "Sistemas de megafonía."


# --------------------------------------------------------------- normalização
ATOM_ENTRY = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:cbc="urn:dgpe:names:draft:codice:schema:xsd:CommonBasicComponents-2"
      xmlns:cac="urn:dgpe:names:draft:codice:schema:xsd:CommonAggregateComponents-2"
      xmlns:cbc-place-ext="urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonBasicComponents-2"
      xmlns:cac-place-ext="urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonAggregateComponents-2">
  <entry>
    <id>https://contrataciondelestado.es/sindicacion/licitacionesPerfilContratante/1</id>
    <link href="https://contrataciondelestado.es/wps/poc?uri=deeplink:detalle_licitacion&amp;idEvl=abc"/>
    <title>Suministro de energía eléctrica</title>
    <updated>2023-02-01T10:00:00.000+01:00</updated>
    <cac-place-ext:ContractFolderStatus>
      <cbc:ContractFolderID>2023/EXP-1</cbc:ContractFolderID>
      <cbc-place-ext:ContractFolderStatusCode languageID="es" listURI="x">RES</cbc-place-ext:ContractFolderStatusCode>
      <cac-place-ext:LocatedContractingParty>
        <cbc:ContractingPartyTypeCode listURI="x">1</cbc:ContractingPartyTypeCode>
        <cac:Party>
          <cbc:WebsiteURI>https://example.es</cbc:WebsiteURI>
          <cac:PartyIdentification><cbc:ID schemeName="DIR3">EA0003016</cbc:ID></cac:PartyIdentification>
          <cac:PartyName><cbc:Name>Ayuntamiento de Getafe</cbc:Name></cac:PartyName>
          <cac:PostalAddress>
            <cbc:CityName>Getafe</cbc:CityName>
            <cbc:PostalZone>28901</cbc:PostalZone>
            <cac:Country><cbc:IdentificationCode>ES</cbc:IdentificationCode><cbc:Name>España</cbc:Name></cac:Country>
          </cac:PostalAddress>
          <cac:Contact><cbc:ElectronicMail>contratacion@example.es</cbc:ElectronicMail></cac:Contact>
        </cac:Party>
      </cac-place-ext:LocatedContractingParty>
      <cac:ProcurementProject>
        <cbc:Name>Suministro de energía eléctrica</cbc:Name>
        <cbc:TypeCode listURI="x">1</cbc:TypeCode>
        <cbc:SubTypeCode listURI="x">2</cbc:SubTypeCode>
        <cac:BudgetAmount>
          <cbc:EstimatedOverallContractAmount currencyID="EUR">59722.28</cbc:EstimatedOverallContractAmount>
          <cbc:TotalAmount currencyID="EUR">72263.96</cbc:TotalAmount>
          <cbc:TaxExclusiveAmount currencyID="EUR">59722.28</cbc:TaxExclusiveAmount>
        </cac:BudgetAmount>
        <cac:RequiredCommodityClassification>
          <cbc:ItemClassificationCode listURI="x">65310000</cbc:ItemClassificationCode>
        </cac:RequiredCommodityClassification>
        <cac:RealizedLocation>
          <cbc:CountrySubentity>Getafe</cbc:CountrySubentity>
          <cbc:CountrySubentityCode listURI="x">ES300</cbc:CountrySubentityCode>
        </cac:RealizedLocation>
        <cac:PlannedPeriod><cbc:DurationMeasure unitCode="MON">12</cbc:DurationMeasure></cac:PlannedPeriod>
      </cac:ProcurementProject>
      <cac:ProcurementProjectLot><cbc:ID>1</cbc:ID></cac:ProcurementProjectLot>
      <cac:ProcurementProjectLot><cbc:ID>2</cbc:ID></cac:ProcurementProjectLot>
      <cac:TenderResult>
        <cbc:ResultCode listURI="x">8</cbc:ResultCode>
        <cbc:Description>Por ser la oferta económicamente más ventajosa</cbc:Description>
        <cbc:ReceivedTenderQuantity>3</cbc:ReceivedTenderQuantity>
        <cbc:AwardDate>2023-01-20</cbc:AwardDate>
        <cac:WinningParty>
          <cac:PartyIdentification><cbc:ID schemeName="NIF">A95075586</cbc:ID></cac:PartyIdentification>
          <cac:PartyName><cbc:Name>IBERDROLA GENERACIÓN, S.A.</cbc:Name></cac:PartyName>
        </cac:WinningParty>
        <cac:AwardedTenderedProject>
          <cac:LegalMonetaryTotal>
            <cbc:TaxExclusiveAmount currencyID="EUR">45466.12</cbc:TaxExclusiveAmount>
            <cbc:PayableAmount currencyID="EUR">55014.01</cbc:PayableAmount>
          </cac:LegalMonetaryTotal>
        </cac:AwardedTenderedProject>
      </cac:TenderResult>
      <cac:TenderingTerms>
        <cac:Language><cbc:ID>es</cbc:ID></cac:Language>
      </cac:TenderingTerms>
      <cac:TenderingProcess>
        <cbc:ProcedureCode listURI="x">1</cbc:ProcedureCode>
        <cbc:TenderSubmissionDeadlinePeriod>
          <cbc:EndDate>2023-01-10</cbc:EndDate>
          <cbc:EndTime>14:00:00</cbc:EndTime>
        </cbc:TenderSubmissionDeadlinePeriod>
      </cac:TenderingProcess>
      <cac:ValidNoticeInfo>
        <cbc:NoticeTypeCode listURI="x">DOC_CAN_ADJ</cbc:NoticeTypeCode>
        <cac:AdditionalPublicationStatus>
          <cac:AdditionalPublicationDocumentReference><cbc:IssueDate>2023-01-25</cbc:IssueDate></cac:AdditionalPublicationDocumentReference>
        </cac:AdditionalPublicationStatus>
      </cac:ValidNoticeInfo>
    </cac-place-ext:ContractFolderStatus>
  </entry>
</feed>
"""


@pytest.fixture(scope="module")
def doc() -> dict:
    root = ET.fromstring(ATOM_ENTRY)
    entry = next(c for c in root if c.tag.split("}")[-1] == "entry")
    result = pipeline.normalize_entry(entry, "licitaciones", 2023)
    assert result is not None
    return result


def test_campos_principais(doc: dict) -> None:
    assert doc["id_expediente"] == "2023/EXP-1"
    assert doc["organo_nombre"] == "Ayuntamiento de Getafe"
    assert doc["organo_id"] == "EA0003016"
    assert doc["organo_ciudad"] == "Getafe"
    assert doc["tipo_contrato_label"] == "Suministros"
    assert doc["estado_label"] == "Resuelta"
    assert doc["adjudicatario_nombre"] == "IBERDROLA GENERACIÓN, S.A."
    assert doc["adjudicatario_nif"] == "A95075586"
    assert doc["resultado_label"] == "Adjudicado"
    assert doc["procedimiento_label"] == "Abierto"
    assert doc["idioma"] == "es"
    assert doc["num_lotes"] == 2
    assert doc["localidad"] == "Getafe"
    assert doc["nuts"] == "ES300"
    assert doc["pais"] == "ES"


def test_valores_e_datas(doc: dict) -> None:
    assert doc["valor_base"] == pytest.approx(59722.28)
    assert doc["valor_presupuesto"] == pytest.approx(72263.96)
    assert doc["valor_adjudicado"] == pytest.approx(45466.12)
    assert doc["valor_adjudicado_con_iva"] == pytest.approx(55014.01)
    assert doc["moneda"] == "EUR"
    assert doc["num_ofertas"] == 3
    assert doc["duracion_valor"] == pytest.approx(12)
    assert doc["duracion_unidad"] == "MON"
    assert doc["fecha_publicacion"].startswith("2023-01-25")
    assert doc["ano"] == 2023


def test_cpv_com_descricao(doc: dict) -> None:
    assert doc["cpv"][0]["code"] == "65310000"
    # Rótulo vindo da lista oficial CPV2008 (`Distribución de electricidad.`).
    assert "electricidad" in doc["cpv"][0]["nombre"]


def test_doc_id_e_estavel_e_por_expediente() -> None:
    """O `_id` tem de ser função de fonte+órgão+expediente, para a reindexação atualizar."""
    esperado = hashlib.sha1(b"licitaciones|EA0003016|2023/EXP-1").hexdigest()
    assert pipeline._doc_id("licitaciones", "EA0003016", "2023/EXP-1") == esperado
    assert pipeline._doc_id("menores", "EA0003016", "2023/EXP-1") != esperado


def test_search_text_junta_partes_uteis(doc: dict) -> None:
    assert "IBERDROLA" in doc["search_text"]
    assert "65310000" in doc["search_text"]


def test_documento_serializavel_em_json() -> None:
    """A entrada não pode deixar nós XML no documento (bug apanhado na importação de 2023)."""
    import json

    root = ET.fromstring(ATOM_ENTRY)
    entry = next(c for c in root if c.tag.split("}")[-1] == "entry")
    json.dumps(pipeline.normalize_entry(entry, "licitaciones", 2023), ensure_ascii=False)


@pytest.mark.parametrize(
    "raw, esperado",
    [
        ("2023-01-25", "2023-01-25T00:00:00"),
        ("2023-01-11T09:41:37.139+01:00", "2023-01-11T09:41:37.139000+01:00"),
        ("25/01/2023", "2023-01-25T00:00:00"),
        ("", None),
        ("sem data", None),
    ],
)
def test_normalizacao_de_datas(raw: str, esperado: str | None) -> None:
    assert pipeline._date(raw) == esperado


def test_ano_ignora_gralhas_da_fonte() -> None:
    """`IssueDate=0018-03-02` (gralha real no feed) não pode dar uma faceta «ano 18»."""
    assert pipeline._year_of("0018-03-02", "2018-06-19", fallback=2018) == 2018
    assert pipeline._year_of("0018-03-02", fallback=2018) == 2018
    assert pipeline._year_of("", None, fallback=2018) == 2018
    assert pipeline._year_of("1850-01-01", fallback=None) is None
    assert pipeline._year_of("2999-01-01", fallback=2015) == 2015
    assert pipeline._year_of("2023-01-25") == 2023


# --------------------------------------------------------------- query no Elasticsearch
def test_filtro_de_valor_usa_valor_adjudicado_com_fallback() -> None:
    """Quem filtra por valor espera o valor adjudicado; sem ele, vale o valor base."""
    filtro = es_client._contratos_es_value_range(1000, None)
    assert filtro is not None
    should = filtro["bool"]["should"]
    assert should[0] == {"range": {"valor_adjudicado": {"gte": 1000}}}
    assert should[1]["bool"]["must"][1] == {"range": {"valor_base": {"gte": 1000}}}


def test_sem_filtro_de_valor_nao_gera_clausula() -> None:
    assert es_client._contratos_es_value_range(None, None) is None


def test_query_com_filtros_aceita_codigo_ou_rotulo() -> None:
    query = es_client._build_contratos_es_query(tipo="2", estado="RES", procedimiento="6", ano=2023)
    filtros = query["bool"]["filter"]
    assert {"term": {"tipo_contrato": "2"}} in filtros
    assert {"term": {"estado": "RES"}} in filtros
    assert {"term": {"procedimiento": "6"}} in filtros
    assert {"term": {"ano": 2023}} in filtros

    por_rotulo = es_client._build_contratos_es_query(tipo="Servicios", estado="Resuelta")
    assert {"term": {"tipo_contrato_label": "Servicios"}} in por_rotulo["bool"]["filter"]
    assert {"term": {"estado_label": "Resuelta"}} in por_rotulo["bool"]["filter"]


def test_query_de_texto_pesquisa_campos_relevantes() -> None:
    query = es_client._build_contratos_es_query(q="energía eléctrica")
    multi = query["bool"]["must"][0]["bool"]["should"][0]["multi_match"]
    campos = multi["fields"]
    assert any(c.startswith("objeto") for c in campos)
    assert any(c.startswith("adjudicatario_nombre") for c in campos)


def test_filtro_cpv_exato_versus_prefixo() -> None:
    exato = es_client._build_contratos_es_query(cpv_code="65310000")["bool"]["filter"][-1]
    prefixo = es_client._build_contratos_es_query(cpv_code="6531")["bool"]["filter"][-1]
    assert exato["nested"]["query"] == {"term": {"cpv.code": "65310000"}}
    assert prefixo["nested"]["query"] == {"prefix": {"cpv.code": "6531"}}


def test_ordenacao_por_data_ou_valor() -> None:
    assert es_client._contratos_es_sort("valor_adjudicado", "asc")[0]["valor_adjudicado"]["order"] == "asc"
    assert es_client._contratos_es_sort("fecha_publicacion", None)[0]["fecha_publicacion"]["order"] == "desc"
    assert es_client._contratos_es_sort("relevancia", None)[0] == "_score"
