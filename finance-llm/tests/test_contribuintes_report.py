"""Testes dos relatórios de contribuintes (PDF, Excel e CSV com a marca do IQ OS).

São testes de unidade: constroem um contribuinte sintético (o mesmo formato do
índice `finance_contribuintes`) e verificam as secções, os três renderizadores e
a presença da marca. Não precisam de Elasticsearch nem da API.
"""
from __future__ import annotations

from io import BytesIO

import pytest

from api import contribuintes_report as report


@pytest.fixture()
def contribuinte() -> dict:
    """Contribuinte de exemplo, com evidência de várias fontes."""
    return {
        "nif": "500189412",
        "name": "JANSSEN - CILAG FARMACÊUTICA LDA",
        "names": ["JANSSEN - CILAG FARMACÊUTICA LDA", "JANSSEN CILAG FARMACEUTICA, LDA."],
        "type": "empresa",
        "type_label": "Empresa",
        "is_company": True,
        "nif_valid": True,
        "country": "Portugal",
        "sources": ["contratos", "societario", "cire"],
        "source_labels": ["Contratos públicos (PT)", "Publicações societárias (MJ)", "Insolvências (CIRE)"],
        "roles": ["adjudicante", "adjudicatario", "societario"],
        "contracts_count": 12,
        "contracts_as_adjudicante": 9,
        "contracts_as_adjudicatario": 3,
        "contracts_value": 1234567.89,
        "contratos_es_count": 2,
        "contratos_es_value": 99000.0,
        "societario_count": 93,
        "cire_count": 2,
        "cire_roles": ["insolvente", "credor"],
        "trademarks_count": 4,
        "firmas_count": 1,
        "people_roles_count": 7,
        "crm_account": True,
        "records_total": 107,
        "first_seen": "2006-02-21T00:00:00.000Z",
        "last_seen": "2026-09-22T00:00:00.000Z",
        "location": {"pais": "Portugal", "distrito": "Lisboa", "concelho": "Oeiras"},
        "run_id": "20260924T134242398805",
        "synced_at": "2026-09-24T13:57:17.558090+00:00",
        "src_contratos": {
            "label": "Contratos públicos (PT)",
            "count": 12,
            "value": 1234567.89,
            "first": "2006-02-21T00:00:00.000Z",
            "last": "2026-09-22T00:00:00.000Z",
            "roles": ["adjudicante", "adjudicatario"],
            "detail": {"localExecucao": ["Portugal, Lisboa, Oeiras"]},
            "parts": {"adjudicante": {"count": 9}, "adjudicatario": {"count": 3}},
        },
        "src_societario": {
            "label": "Publicações societárias (MJ)",
            "count": 93,
            "first": "2010-01-05T00:00:00.000Z",
            "last": "2026-09-01T00:00:00.000Z",
            "detail": {"natureza_juridica": "Sociedade por quotas"},
        },
    }


def test_logo_disponivel() -> None:
    """O logótipo do IQ OS existe no frontend (é o que vai para o PDF e o Excel)."""
    logo = report.logo_path()
    assert logo is not None, "logótipo não encontrado em chat-ui/public/"
    assert logo.suffix == ".png"
    assert logo.stat().st_size > 1000


def test_formatos_disponiveis() -> None:
    info = report.available()
    assert info["brand"] == "IQ OS"
    assert info["logo_available"] is True
    ids = {entry["id"]: entry for entry in info["formats"]}
    assert {"pdf", "xlsx", "csv"} <= set(ids)
    assert ids["pdf"]["embeds_logo"] is True
    assert ids["xlsx"]["embeds_logo"] is True
    # O CSV é texto: não pode conter a imagem, leva a marca no cabeçalho.
    assert ids["csv"]["embeds_logo"] is False


def test_seccoes_da_ficha(contribuinte: dict) -> None:
    sections = report.contribuinte_sections(contribuinte)
    titles = [section["title"] for section in sections]
    assert titles[0] == "Identificação"
    assert "Localização" in titles
    assert "Atividade agregada" in titles
    assert "Designações conhecidas" in titles
    assert any(title.startswith("Fonte: ") for title in titles)
    assert "Controlo" in titles

    identification = dict(sections[0]["rows"])
    assert identification["NIF / NIPC"] == "500189412"
    assert identification["Tipo de contribuinte"] == "Empresa"
    assert identification["Natureza"] == "Pessoa coletiva"

    activity = dict(next(section["rows"] for section in sections if section["title"] == "Atividade agregada"))
    assert activity["Contratos públicos (PT)"] == "12"
    assert activity["Valor contratual (PT)"].endswith("€")
    assert activity["Papéis no CIRE"] == "insolvente, credor"

    location = dict(next(section["rows"] for section in sections if section["title"] == "Localização"))
    assert location["Distrito"] == "Lisboa"
    assert location["Concelho"] == "Oeiras"

    contratos = next(section for section in sections if section["title"] == "Fonte: Contratos públicos (PT)")
    labels = dict(contratos["rows"])
    assert labels["Registos"] == "12"
    assert "Oeiras" in labels["Local execucao"]


@pytest.mark.parametrize(
    ("format", "magic"),
    [("pdf", b"%PDF"), ("xlsx", b"PK"), ("csv", "\ufeff".encode("utf-8"))],
)
def test_relatorio_da_ficha(contribuinte: dict, format: str, magic: bytes) -> None:
    filename, content, media_type = report.contribuinte_report(contribuinte, format=format)
    assert content.startswith(magic), f"assinatura inválida em {format}"
    assert filename.startswith("iq-os-contribuinte-500189412_")
    assert filename.endswith(f".{format}")
    assert media_type
    assert "500189412" in filename


def test_csv_com_marca_e_valores(contribuinte: dict) -> None:
    _, content, _ = report.contribuinte_report(contribuinte, format="csv")
    text = content.decode("utf-8-sig")
    lines = text.splitlines()
    assert lines[0].startswith("# IQ OS")
    assert "Plataforma de Inteligência Financeira" in lines[0]
    assert "## Identificação" in lines
    assert "JANSSEN - CILAG FARMACÊUTICA LDA" in text
    assert "## Localização" in lines


def test_excel_com_logotipo(contribuinte: dict) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    _, content, media_type = report.contribuinte_report(contribuinte, format="xlsx")
    assert "spreadsheetml" in media_type
    workbook = openpyxl.load_workbook(BytesIO(content))
    assert "Relatório" in workbook.sheetnames
    sheet = workbook["Relatório"]
    assert sheet["A1"].value == "IQ OS"
    assert sheet["A3"].value.startswith("Ficha de contribuinte")
    # O logótipo é embutido como imagem (depende do Pillow, já usado pelo openpyxl).
    assert len(sheet._images) == 1


def test_pdf_com_paginas_e_marca(contribuinte: dict) -> None:
    pytest.importorskip("reportlab")
    _, content, media_type = report.contribuinte_report(contribuinte, format="pdf")
    assert media_type == "application/pdf"
    assert content.startswith(b"%PDF")
    pages = content.count(b"/Type /Page") - content.count(b"/Type /Pages")
    assert pages >= 1
    assert b"IQ OS" in content


def test_relatorio_de_lista(contribuinte: dict) -> None:
    items = [contribuinte, {**contribuinte, "nif": "600012662", "name": "MUNICÍPIO DE OEIRAS", "type": "entidade_publica"}]
    for format, magic in (("csv", "\ufeff".encode("utf-8")), ("xlsx", b"PK"), ("pdf", b"%PDF")):
        filename, content, media_type = report.list_report(items, total=112608, format=format, filters_label="tipo: empresa")
        assert content.startswith(magic), f"assinatura inválida em {format}"
        assert filename.startswith("iq-os-contribuintes_")
        assert media_type

    sections = report.list_sections(items, total=112608, filters_label="tipo: empresa")
    summary = dict(sections[0]["rows"])
    assert summary["Contribuintes no resultado"] == "112 608"
    assert summary["Contribuintes exportados"] == "2"
    assert summary["Filtros aplicados"] == "tipo: empresa"
    assert "Distribuição por tipo" in [section["title"] for section in sections]

    table = next(section for section in sections if section["title"] == "Contribuintes")
    assert table["columns"][0] == "NIF"
    assert len(table["rows"]) == 2
    first = dict(zip(table["columns"], table["rows"][0]))
    assert first["NIF"] == "500189412"
    assert "Oeiras" in first["Localização"]


def test_formato_desconhecido() -> None:
    with pytest.raises(ValueError):
        report.contribuinte_report({"nif": "1"}, format="docx")


def test_slugify_nomes_de_ficheiro() -> None:
    assert report.slugify("JANSSEN - CILAG FARMACÊUTICA LDA") == "janssen-cilag-farmaceutica-lda"
    assert report.slugify("") == "contribuintes"
    assert report.slugify("500189412") == "500189412"
