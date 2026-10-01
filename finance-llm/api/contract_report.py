"""Relatório PDF de um contrato: valores, peça do procedimento, empresas e análise IA.

Reutiliza `api.contribuintes_report.render_pdf` (logótipo, tabelas e rodapé da
marca IQ OS), pelo que o relatório sai com o mesmo aspeto dos restantes.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from api.contribuintes_report import render_pdf

BRAND = "IQ OS"


# ------------------------------------------------------------------ formatação
def money(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    return f"{number:,.2f} €".replace(",", " ").replace(".", ",")


def _plain(text: str) -> str:
    """Markdown simples → texto corrido (o PDF não interpreta markdown)."""
    out = re.sub(r"^#{1,6}\s*", "", text or "", flags=re.MULTILINE)
    out = re.sub(r"\*\*(.+?)\*\*", r"\1", out)
    out = re.sub(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)", r"\1", out)
    out = re.sub(r"^\s*[-*+]\s+", "• ", out, flags=re.MULTILINE)
    out = re.sub(r"`([^`]*)`", r"\1", out)
    return out.strip()


def _blocks(text: str) -> List[List[str]]:
    """Divide a análise em parágrafos, agrupando linhas soltas."""
    parts: List[str] = []
    buffer: List[str] = []
    for line in (text or "").splitlines():
        stripped = line.strip()
        if not stripped:
            if buffer:
                parts.append(" ".join(buffer))
                buffer = []
            continue
        buffer.append(stripped)
    if buffer:
        parts.append(" ".join(buffer))
    return [[_plain(part)] for part in parts if _plain(part)]


def _company_rows(companies: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    sections: List[Dict[str, Any]] = []
    for company in companies:
        detail = company.get("detail") or {}
        analytics = company.get("analytics") or {}
        name = detail.get("name") or company.get("nome") or company.get("nif") or "—"
        role = company.get("role") or "entidade"

        rows: List[List[str]] = [["NIF", str(detail.get("nif") or company.get("nif") or "—")]]
        rows.append(["Papel no contrato", str(role).capitalize()])
        rows.append(["Contratos (total)", str(detail.get("contracts_total", 0))])
        rows.append(["Valor total", money(detail.get("total_value"))])

        for key, label in (("adjudicante", "Como adjudicante"), ("adjudicatario", "Como adjudicatária")):
            summary = detail.get(key) or {}
            if summary:
                rows.append(
                    [
                        label,
                        f"{summary.get('contracts_count', 0)} contratos · "
                        f"{money(summary.get('total_value'))} · média {money(summary.get('avg_value'))}"
                        + (
                            f" · {summary.get('first_year')}–{summary.get('last_year')}"
                            if summary.get("first_year")
                            else ""
                        ),
                    ]
                )

        if analytics:
            rows.append(
                [
                    "Analítica",
                    f"{analytics.get('total_contracts', 0)} contratos · "
                    f"{money(analytics.get('total_value'))} · média {money(analytics.get('avg_value'))} · "
                    f"máx. {money(analytics.get('max_value'))}",
                ]
            )
            top_partners = (analytics.get("top_partners") or [])[:3]
            for partner in top_partners:
                rows.append(
                    [
                        f"Parceiro · {partner.get('key', '—')}",
                        f"{partner.get('count', 0)} contratos · {money(partner.get('total_value'))}",
                    ]
                )
            by_year = sorted((analytics.get("by_year") or []), key=lambda r: r.get("key", ""))[-4:]
            if by_year:
                rows.append(
                    [
                        "Por ano",
                        " · ".join(
                            f"{row.get('key')}: {row.get('count')} ({money(row.get('total_value'))})"
                            for row in by_year
                        ),
                    ]
                )

        if detail.get("trademarks_total"):
            marks = [m.get("nome") or m.get("name") or "—" for m in (detail.get("trademarks") or [])[:4]]
            rows.append(["Marcas INPI", f"{detail['trademarks_total']} · " + "; ".join(marks)])

        sections.append({"title": f"Empresa — {name}", "columns": None, "rows": rows})
    return sections


# ---------------------------------------------------------------------- relatório
def build_report_pdf(
    *,
    contract: Dict[str, Any],
    document: Optional[Dict[str, Any]],
    analysis: Optional[Dict[str, Any]],
    companies: Sequence[Dict[str, Any]],
    question: Optional[str] = None,
) -> bytes:
    """Constrói o PDF do dossiê do contrato."""
    contract = contract or {}
    document = document or {}
    analysis = analysis or {}

    objecto = contract.get("objectoContrato") or contract.get("descContrato") or "Contrato"
    subtitle = (
        f"Contrato {contract.get('idcontrato', '—')} · {contract.get('tipoprocedimento', '—')} · "
        f"{money(contract.get('precoContratual'))}"
    )

    sections: List[Dict[str, Any]] = []

    # 1. Identificação
    adjudicantes = ", ".join(
        f"{a.get('nome')} ({a.get('nif')})" for a in (contract.get("adjudicantes") or {}).get("parsed", [])
    ) or "—"
    adjudicatarios = ", ".join(
        f"{a.get('nome')} ({a.get('nif')})" for a in (contract.get("adjudicatarios") or {}).get("parsed", [])
    ) or "—"
    identificacao = [
        ["Objeto", str(contract.get("objectoContrato") or "—")],
        ["Entidade adjudicante", adjudicantes],
        ["Entidade adjudicatária", adjudicatarios],
        ["Tipo de contrato", ", ".join(contract.get("tipoContrato") or []) or "—"],
        ["Procedimento", str(contract.get("tipoprocedimento") or "—")],
        ["Prazo de execução", f"{int(contract['prazoExecucao'])} dias" if contract.get("prazoExecucao") else "—"],
        ["CPV", ", ".join(f"{c.get('code')} {c.get('description')}" for c in (contract.get("cpv") or [])) or "—"],
        ["Local de execução", ", ".join(contract.get("localExecucao") or []) or "—"],
        ["NUTs", ", ".join(contract.get("NUTs") or []) or "—"],
    ]
    sections.append({"title": "1. Identificação do contrato", "columns": None, "rows": identificacao})

    # 2. Valores
    values = [(v["label"], str(v.get("value", "—"))) for v in (document.get("values") or [])]
    if values:
        sections.append({"title": "2. Valores publicados (índice BASE)", "columns": None, "rows": values})

    # 3. Peça do procedimento
    highlights = document.get("highlights") or []
    if highlights:
        sections.append(
            {
                "title": "3. Factos lidos da peça do procedimento",
                "columns": ["Facto", "Valor", "Documento"],
                "rows": [[h.get("label", "—"), h.get("value", "—"), h.get("document", "—")] for h in highlights],
            }
        )
    pieces = document.get("pieces") or []
    if pieces:
        sections.append(
            {
                "title": "4. Documentos da peça",
                "columns": ["Ficheiro", "Tipo", "Caracteres"],
                "rows": [[p.get("name", "—"), p.get("kind", "—"), str(len(p.get("text") or ""))] for p in pieces],
            }
        )

    # 5. Empresas
    sections.extend(_company_rows(companies))

    # 6. Análise IA
    answer = analysis.get("answer") or analysis.get("error")
    if answer:
        rows = _blocks(answer)
        if question:
            rows.insert(0, [f"Pedido: {_plain(question)}"])
        sections.append(
            {
                "title": "6. Análise IA",
                "columns": [f"Modelo: {analysis.get('backend_used', '—')}"],
                "rows": rows,
            }
        )

    # 7. Fontes web
    sources = analysis.get("sources") or []
    if sources:
        sections.append(
            {
                "title": "7. Fontes web consultadas",
                "columns": ["Título", "Ligação"],
                "rows": [[s.get("title") or s.get("href", "—"), s.get("href", "—")] for s in sources],
            }
        )

    # 8. Ligações oficiais
    links = document.get("links") or []
    if links:
        sections.append(
            {
                "title": "8. Ligações oficiais",
                "columns": ["Ligação", "URL"],
                "rows": [[link.get("label", "—"), link.get("url", "—")] for link in links],
            }
        )

    return render_pdf(
        title=f"Dossiê do contrato — {_plain(objecto)[:110]}",
        subtitle=subtitle + f" · {datetime.now().strftime('%d/%m/%Y')}",
        sections=[s for s in sections if isinstance(s, dict)],
    )
