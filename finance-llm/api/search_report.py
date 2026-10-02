"""Relatório (PDF/Excel) de uma pesquisa de contratos.

Constrói o **mesmo** documento para os dois formatos: uma lista de secções
`{title, columns, rows}` entregue ao motor de relatórios já usado nos outros
módulos (`contribuintes_report.render_pdf` / `render_xlsx`), que traz o logótipo
do IQ OS e uma folha por secção.

O conteúdo é o da análise (`search_analysis.contracts_analysis`) — totais por
país, série por ano, CPV, procedimento, maiores adjudicatários — seguido da
listagem dos contratos filtrados, com os valores tal como publicados e as
empresas e pessoas associadas por NIF.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from api.contribuintes_report import render_pdf, render_xlsx
from api.elasticsearch_client import search_contracts, search_contratos_es

logger = logging.getLogger(__name__)

MAX_ROWS_EXCEL = 2000
MAX_ROWS_PDF = 300


def _money(value: Any) -> str:
    """Valor em euros no formato português (1 234 567,89)."""
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return ""
    text = f"{number:,.2f}"
    return text.replace(",", " ").replace(".", ",")


def _party_names(entries: Any) -> str:
    """Nomes das partes de um contrato português (`adjudicantes`/`adjudicatarios`)."""
    names: List[str] = []
    if isinstance(entries, dict):
        for part in entries.get("parsed") or []:
            if isinstance(part, dict) and part.get("nome"):
                names.append(str(part["nome"]))
        if not names:
            raw = entries.get("raw")
            names = [str(raw)] if isinstance(raw, str) else [str(item) for item in (raw or []) if item]
    return " · ".join(names[:3])


def _pt_rows(query: str, limit: int) -> List[List[str]]:
    """Contratos portugueses que casam com a pesquisa, prontos a imprimir."""
    try:
        result = search_contracts(q=query or None, size=min(limit, MAX_ROWS_EXCEL), sort_by=None)
    except Exception as exc:
        logger.info("Contratos PT para o relatório falharam: %s", exc)
        return []
    rows: List[List[str]] = []
    for row in result.get("items") or []:
        rows.append(
            [
                str(row.get("idcontrato") or ""),
                str(row.get("dataPublicacao") or row.get("dataCelebracaoContrato") or "")[:10],
                str(row.get("objectoContrato") or row.get("descContrato") or "")[:220],
                _party_names(row.get("adjudicantes")),
                _party_names(row.get("adjudicatarios")),
                _money(row.get("precoContratual") or row.get("PrecoTotalEfetivo")),
                "PT",
            ]
        )
    return rows


def _es_rows(query: str, limit: int) -> List[List[str]]:
    """Contratos de Espanha (PLACSP) que casam com a pesquisa."""
    try:
        result = search_contratos_es(q=query or None, size=min(limit, MAX_ROWS_EXCEL), with_facets=False)
    except Exception as exc:
        logger.info("Contratos ES para o relatório falharam: %s", exc)
        return []
    rows: List[List[str]] = []
    for row in result.get("items") or []:
        valor = row.get("valor_adjudicado")
        if not isinstance(valor, (int, float)):
            valor = row.get("valor_base")
        rows.append(
            [
                str(row.get("doc_id") or ""),
                str(row.get("fecha_publicacion") or "")[:10],
                str(row.get("objeto") or row.get("descripcion") or "")[:220],
                str(row.get("organo_nombre") or ""),
                str(row.get("adjudicatario_nombre") or ""),
                _money(valor),
                "ES",
            ]
        )
    return rows


def build_sections(
    query: str,
    analysis: Dict[str, Any],
    *,
    limit: int = 500,
    include_contracts: bool = True,
) -> List[Dict[str, Any]]:
    """Secções do relatório (o mesmo conteúdo nos dois formatos)."""
    totals = analysis.get("totals") or {}
    sections: List[Dict[str, Any]] = [
        {
            "title": "Resumo",
            "columns": ["Indicador", "Valor"],
            "rows": [
                ["Pesquisa", analysis.get("query") or query],
                ["Contratos encontrados", f"{int(totals.get('contracts') or 0):,}".replace(",", " ")],
                ["Valor total", f"{_money(totals.get('value'))} €"],
                ["Portugal (contratos · valor)", f"{totals.get('contracts_pt')} · {_money(totals.get('value_pt'))} €"],
                ["Espanha (contratos · valor)", f"{totals.get('contracts_es')} · {_money(totals.get('value_es'))} €"],
                ["Valor médio por contrato", f"{_money(totals.get('avg_value'))} €"],
                ["Maior contrato", f"{_money(totals.get('max_value'))} €"],
                ["Adjudicantes distintos (PT)", str(totals.get("distinct_adjudicantes") or 0)],
                ["Adjudicatários distintos (PT)", str(totals.get("distinct_adjudicatarios") or 0)],
                ["Emitido em", str(analysis.get("generated_at") or "")],
            ],
        }
    ]

    by_year = analysis.get("by_year") or []
    if by_year:
        sections.append(
            {
                "title": "Por ano",
                "columns": ["Ano", "Contratos", "Valor"],
                "rows": [[str(item.get("key")), str(item.get("count")), f"{_money(item.get('total_value'))} €"] for item in by_year],
            }
        )

    by_cpv = analysis.get("by_cpv") or []
    if by_cpv:
        sections.append(
            {
                "title": "Por CPV",
                "columns": ["CPV", "Descrição", "Contratos", "Valor"],
                "rows": [
                    [
                        str(item.get("key")),
                        str(item.get("description") or "")[:120],
                        str(item.get("count")),
                        f"{_money(item.get('total_value'))} €",
                    ]
                    for item in by_cpv
                ],
            }
        )

    procedures = analysis.get("procedure_types") or []
    if procedures:
        sections.append(
            {
                "title": "Por procedimento",
                "columns": ["Procedimento", "Contratos", "Valor"],
                "rows": [
                    [str(item.get("key")), str(item.get("count")), f"{_money(item.get('total_value'))} €"]
                    for item in procedures
                ],
            }
        )

    adjudicatarios = analysis.get("top_adjudicatarios") or []
    if adjudicatarios:
        sections.append(
            {
                "title": "Maiores adjudicatários",
                "columns": ["NIF / Nome", "Contratos", "Valor"],
                "rows": [
                    [
                        str(item.get("key")),
                        str(item.get("description") or item.get("key") or "")[:140],
                        str(item.get("count")),
                        f"{_money(item.get('total_value'))} €",
                    ]
                    for item in adjudicatarios
                ],
            }
        )

    links = analysis.get("linked") or {}
    companies = links.get("companies") or []
    if companies:
        sections.append(
            {
                "title": "Empresas associadas",
                "columns": ["NIF", "Empresa", "Contratos (ficha)", "Valor (ficha)", "Neste conjunto", "Papel"],
                "rows": [
                    [
                        str(item.get("nif")),
                        str(item.get("name") or "")[:140],
                        str(item.get("contracts_total") or ""),
                        f"{_money(item.get('total_value'))} €",
                        f"{item.get('contracts_in_search')} · {_money(item.get('value_in_search'))} €",
                        "adjudicatário" if item.get("adjudicatario") else ("adjudicante" if item.get("adjudicante") else ""),
                    ]
                    for item in companies
                ],
            }
        )
    people = links.get("people") or []
    if people:
        sections.append(
            {
                "title": "Pessoas associadas",
                "columns": ["NIF", "Nome", "Cargo", "Empresa", "Fonte"],
                "rows": [
                    [
                        str(item.get("nif")),
                        str(item.get("name") or "")[:140],
                        str(item.get("role") or ""),
                        str(item.get("company_name") or "")[:140],
                        str(item.get("source") or ""),
                    ]
                    for item in people
                ],
            }
        )

    if include_contracts:
        rows = _pt_rows(query, limit) + _es_rows(query, limit)
        rows.sort(key=lambda row: row[1], reverse=True)
        if rows:
            sections.append(
                {
                    "title": "Contratos filtrados",
                    "columns": ["ID", "Data", "Objeto", "Adjudicante", "Adjudicatário", "Valor", "País"],
                    "rows": rows,
                }
            )
        else:
            sections.append(
                {
                    "title": "Contratos filtrados",
                    "columns": ["Nota"],
                    "rows": [["Não foi possível listar contratos para esta pesquisa (índices indisponíveis ou sem resultados)."]],
                }
            )
    return sections


def report_pdf(query: str, analysis: Dict[str, Any], *, limit: int = MAX_ROWS_PDF) -> bytes:
    """Relatório em PDF com os contratos filtrados e os valores."""
    sections = build_sections(query, analysis, limit=min(limit, MAX_ROWS_PDF))
    return render_pdf(
        title="Contratos e custos",
        subtitle=f"Pesquisa: {query} · {analysis.get('generated_at') or ''}",
        sections=sections,
    )


def report_xlsx(query: str, analysis: Dict[str, Any], *, limit: int = MAX_ROWS_EXCEL) -> bytes:
    """Relatório em Excel (uma folha por secção, com os contratos filtrados)."""
    sections = build_sections(query, analysis, limit=min(limit, MAX_ROWS_EXCEL))
    return render_xlsx(
        title="Contratos e custos",
        subtitle=f"Pesquisa: {query} · {analysis.get('generated_at') or ''}",
        sections=sections,
    )
