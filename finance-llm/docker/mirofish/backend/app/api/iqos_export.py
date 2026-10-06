"""Apagar simulações e exportar para Excel/PDF — extensão do IQ OS.

Acrescentado à imagem pelo `Dockerfile` (o `backend/app` original é substituído
pelo do upstream, por isso este módulo é copiado e o blueprint registado por
`iqos_admin_patch.py`).

Rotas (prefixo `/api/iqos`):

- ``DELETE /simulations/<simulation_id>``          apaga a simulação (e, por
  omissão, o relatório associado); ``?project=1`` apaga também o projeto
- ``GET    /export/simulations.xlsx``              Excel com todas as simulações
- ``GET    /export/simulations.csv``               CSV equivalente (sem libs)
- ``GET    /export/simulations/<id>.xlsx``         Excel detalhado de uma
- ``GET    /export/simulations/<id>.pdf``          ficha da simulação em PDF
- ``GET    /export/reports/<report_id>.pdf``       relatório completo em PDF

Onde vivem os dados (verificado no container): ``Config.UPLOAD_FOLDER`` =
``/app/backend/uploads``, com ``projects/``, ``simulations/`` e ``reports/``.

Porquê apagar por ficheiros e não por uma função da biblioteca: o
`SimulationManager` não tem `delete`; cada simulação é uma pasta e o relatório
outra, com o `simulation_id` dentro do `meta.json` a fazer a ligação.
"""
from __future__ import annotations

import csv
import io
import json
import os
import shutil
import unicodedata
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request, send_file

from ..config import Config
from ..utils.logger import get_logger

logger = get_logger("mirofish.iqos")

iqos_bp = Blueprint("iqos", __name__)

UPLOAD_FOLDER = os.path.abspath(Config.UPLOAD_FOLDER)
SIM_DIR = os.path.join(UPLOAD_FOLDER, "simulations")
REPORT_DIR = os.path.join(UPLOAD_FOLDER, "reports")
PROJECT_DIR = os.path.join(UPLOAD_FOLDER, "projects")

# Estados em que apagar seria perder trabalho a meio: o pedido é recusado.
BUSY_STATES = {"starting", "running", "paused", "stopping"}

# Segurança: só se apaga dentro destas pastas e com nomes com este aspeto.
SAFE_PREFIXES = {"simulations": "sim_", "reports": "report_", "projects": "proj_"}

# --------------------------------------------------------------------------
# Assinatura da plataforma nos PDF
#
# O cabeçalho e o rodapé são desenhados em **todas** as páginas (métodos
# `header`/`footer` do `FPDF`), para que uma página solta — impressa ou
# fotografada — continue a dizer de onde veio: a marca, o documento a que
# pertence, quando foi emitido e em que página está.
# --------------------------------------------------------------------------
BRAND = "IQ OS"
BRAND_SECTION = "Simulações"
BRAND_LINE = "IQ OS - Plataforma de Inteligência Financeira"
BRAND_ORANGE = (255, 69, 0)
BRAND_MUTED = (120, 120, 120)
BRAND_RULE = (222, 222, 222)


# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------
def _load_json(path: str):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return None


def _safe_id(value: str, kind: str) -> str:
    """Valida o id (prefixo certo, apenas caracteres seguros) antes de tocar no disco."""
    text = str(value or "").strip()
    prefix = SAFE_PREFIXES[kind]
    if not text.startswith(prefix):
        raise ValueError(f"Identificador inválido para {kind}: {text!r}")
    if not all(ch.isalnum() or ch in "_-" for ch in text):
        raise ValueError(f"Identificador com caracteres inválidos: {text!r}")
    return text


def _folder(kind: str, identifier: str) -> str:
    base = {"simulations": SIM_DIR, "reports": REPORT_DIR, "projects": PROJECT_DIR}[kind]
    return os.path.join(base, _safe_id(identifier, kind))


def _remove_folder(path: str) -> bool:
    if os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)
        return not os.path.exists(path)
    return False


def _history_rows(limit: int = 500) -> list:
    """Lista enriquecida de simulações — reutiliza o endpoint `/history`."""
    from .simulation import get_simulation_history

    response = get_simulation_history()
    payload = response.get_json() if hasattr(response, "get_json") else response
    rows = (payload or {}).get("data") or []
    return rows[:limit]


def _reports_for(simulation_id: str) -> list:
    """Relatórios que apontam para esta simulação (lidos de `meta.json`)."""
    found = []
    if not os.path.isdir(REPORT_DIR):
        return found
    for name in sorted(os.listdir(REPORT_DIR)):
        meta = _load_json(os.path.join(REPORT_DIR, name, "meta.json"))
        if meta and str(meta.get("simulation_id")) == simulation_id:
            found.append(name)
    return found


def _report_folder(report_id: str) -> str:
    return _folder("reports", report_id)


def _text(value) -> str:
    """Texto de uma célula: listas/dicts em JSON curto, sem partir o Excel."""
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        return ", ".join(str(v) for v in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)[:32000]
    return str(value)


def _slug(value: str, fallback: str = "exportacao") -> str:
    """Nome de ficheiro seguro (sem acentos nem caracteres estranhos)."""
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    keep = [ch if (ch.isalnum() or ch in "-_") else "-" for ch in text]
    slug = "".join(keep).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return (slug or fallback)[:60]


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")


def _xlsx_available() -> bool:
    try:
        import openpyxl  # noqa: F401

        return True
    except Exception:
        return False


def _pdf_available() -> bool:
    try:
        import fpdf  # noqa: F401

        return True
    except Exception:
        return False


# --------------------------------------------------------------------------
# Excel
# --------------------------------------------------------------------------
SIM_COLUMNS = [
    ("simulation_id", "ID"),
    ("project_id", "Projeto"),
    ("report_id", "Relatório"),
    ("simulation_requirement", "Requisito"),
    ("status", "Estado"),
    ("runner_status", "Estado do runner"),
    ("current_round", "Ronda atual"),
    ("total_rounds", "Total de rondas"),
    ("total_simulation_hours", "Horas simuladas"),
    ("entities_count", "Entidades"),
    ("profiles_count", "Personas"),
    ("entity_types", "Tipos de entidade"),
    ("created_at", "Criada em"),
    ("updated_at", "Atualizada em"),
    ("error", "Erro"),
]


def _style_sheet(sheet) -> None:
    from openpyxl.styles import Alignment, Font, PatternFill

    header_fill = PatternFill("solid", start_color="FF4500")
    header_font = Font(color="FFFFFF", bold=True)
    for cell in sheet[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(vertical="center")
    sheet.freeze_panes = "A2"
    # Largura a partir do conteúdo (limitada, senão o Excel abre com colunas enormes).
    for column in sheet.columns:
        longest = max((len(str(cell.value)) for cell in column if cell.value is not None), default=0)
        letter = column[0].column_letter
        sheet.column_dimensions[letter].width = min(max(12, longest + 2), 60)


def _sheet_from_rows(workbook, title: str, columns, rows):
    sheet = workbook.create_sheet(title=title[:31])
    sheet.append([label for _, label in columns])
    for row in rows:
        sheet.append([_text(row.get(key)) for key, _ in columns])
    _style_sheet(sheet)
    return sheet


def _simulation_workbook(rows) -> bytes:
    from openpyxl import Workbook

    workbook = Workbook()
    workbook.remove(workbook.active)

    _sheet_from_rows(workbook, "Simulações", SIM_COLUMNS, rows)

    # Resumo: contagens por estado e totais — é o que se olha primeiro.
    by_status: dict = {}
    for row in rows:
        key = str(row.get("runner_status") or row.get("status") or "desconhecido")
        by_status[key] = by_status.get(key, 0) + 1
    summary = [{"estado": key, "simulações": count} for key, count in sorted(by_status.items())]
    summary.append({"estado": "TOTAL", "simulações": len(rows)})
    summary.append({"estado": "entidades (soma)", "simulações": sum(int(r.get("entities_count") or 0) for r in rows)})
    summary.append({"estado": "personas (soma)", "simulações": sum(int(r.get("profiles_count") or 0) for r in rows)})
    _sheet_from_rows(workbook, "Resumo", [("estado", "Estado"), ("simulações", "Simulações")], summary)

    stream = io.BytesIO()
    workbook.save(stream)
    return stream.getvalue()


PROFILE_COLUMNS = [
    ("username", "Utilizador"),
    ("name", "Nome"),
    ("profession", "Profissão"),
    ("country", "País"),
    ("age", "Idade"),
    ("gender", "Género"),
    ("mbti", "MBTI"),
    ("karma", "Karma"),
    ("interested_topics", "Interesses"),
    ("bio", "Bio"),
    ("persona", "Persona"),
]

RUN_COLUMNS = [
    ("runner_status", "Estado do runner"),
    ("current_round", "Ronda atual"),
    ("total_rounds", "Total de rondas"),
    ("simulated_hours", "Horas simuladas"),
    ("progress_percent", "Progresso (%)"),
    ("total_actions_count", "Ações"),
    ("twitter_actions_count", "Ações (X)"),
    ("reddit_actions_count", "Ações (Reddit)"),
    ("started_at", "Início"),
    ("updated_at", "Atualização"),
]


def _simulation_detail_workbook(simulation_id: str) -> bytes:
    from openpyxl import Workbook

    folder = _folder("simulations", simulation_id)
    state = _load_json(os.path.join(folder, "state.json")) or {}
    run_state = _load_json(os.path.join(folder, "run_state.json")) or {}
    config = _load_json(os.path.join(folder, "simulation_config.json")) or {}
    profiles = _load_json(os.path.join(folder, "reddit_profiles.json")) or []
    if not profiles:
        # Algumas corridas só geram perfis para o X (CSV).
        csv_path = os.path.join(folder, "twitter_profiles.csv")
        if os.path.exists(csv_path):
            try:
                with open(csv_path, encoding="utf-8", newline="") as handle:
                    profiles = list(csv.DictReader(handle))
            except Exception:
                profiles = []

    workbook = Workbook()
    workbook.remove(workbook.active)

    # Ficha
    ficha = [
        ("simulation_id", simulation_id),
        ("project_id", state.get("project_id")),
        ("graph_id", state.get("graph_id")),
        ("status", state.get("status")),
        ("runner_status", run_state.get("runner_status")),
        ("current_round", run_state.get("current_round")),
        ("total_rounds", run_state.get("total_rounds")),
        ("simulated_hours", run_state.get("simulated_hours")),
        ("entities_count", state.get("entities_count")),
        ("profiles_count", state.get("profiles_count")),
        ("entity_types", state.get("entity_types")),
        ("enable_twitter", state.get("enable_twitter")),
        ("enable_reddit", state.get("enable_reddit")),
        ("created_at", state.get("created_at")),
        ("updated_at", state.get("updated_at")),
        ("erro", state.get("error")),
        ("requisito", config.get("simulation_requirement") or state.get("simulation_requirement")),
    ]
    _sheet_from_rows(workbook, "Simulação", [("campo", "Campo"), ("valor", "Valor")],
                     [{"campo": key, "valor": value} for key, value in ficha])

    if profiles:
        _sheet_from_rows(workbook, "Personas", PROFILE_COLUMNS, profiles)
    if run_state:
        _sheet_from_rows(workbook, "Execução", RUN_COLUMNS, [run_state])

    # Relatório: uma linha por secção/parágrafo, para dar para ler e filtrar.
    reports = _reports_for(simulation_id)
    if reports:
        markdown = ""
        path = os.path.join(REPORT_DIR, reports[-1], "full_report.md")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as handle:
                markdown = handle.read()
        lines = [{"linha": index + 1, "texto": line}
                 for index, line in enumerate(markdown.splitlines()) if line.strip()]
        _sheet_from_rows(workbook, "Relatório", [("linha", "Linha"), ("texto", "Texto")], lines)

    stream = io.BytesIO()
    workbook.save(stream)
    return stream.getvalue()


def _simulations_csv(rows) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow([label for _, label in SIM_COLUMNS])
    for row in rows:
        writer.writerow([_text(row.get(key)) for key, _ in SIM_COLUMNS])
    # BOM para o Excel reconhecer UTF-8 (acentos corretos ao abrir com duplo clique).
    return "\ufeff".encode("utf-8") + buffer.getvalue().encode("utf-8")


# --------------------------------------------------------------------------
# PDF
# --------------------------------------------------------------------------
def _pdf_safe(text: str) -> str:
    """Texto pronto para as fontes base do PDF (latin-1).

    As fontes de base do fpdf são latin-1, que não tem travessões longos, aspas
    curvas, reticências **nem o símbolo do euro** — sem estas substituições, um
    relatório com valores em euros saía cheio de «?». O que sobrar é substituído,
    nunca provoca exceção.
    """
    replacements = {
        "\u2014": "-",  # travessão
        "\u2013": "-",  # meia-risca
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2026": "...",
        "\u2022": "-",
        "\u00a0": " ",  # espaço não separável
        "\u20ac": "EUR",  # o euro não existe em latin-1
        "\u2192": "->",
        "\u2190": "<-",
        "\u2705": "[x]",
        "\u274c": "[ ]",
    }
    flattened = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    for source, target in replacements.items():
        flattened = flattened.replace(source, target)
    # Colapsa espaços e quebras: o `multi_cell` faz a sua própria divisão de linha.
    flattened = " ".join(flattened.split())
    return flattened.encode("latin-1", "replace").decode("latin-1")


class _Report:
    """PDF simples com cabeçalho, título, parágrafos e blocos de texto.

    Nota sobre o `multi_cell`: no fpdf2 ≥ 2.7 a posição por omissão é
    `new_x=RIGHT, new_y=TOP` (compatibilidade com o fpdf v1), o que deixa o
    cursor à direita e faz o **bloco seguinte** rebentar com «Not enough
    horizontal space to render a single character». Daí o `_write` fixar sempre
    `LMARGIN`/`NEXT`.

    Nota sobre `header`/`footer`: são chamados pelo próprio `FPDF` (no
    `add_page` e no fim de cada página, incluindo as criadas pela quebra
    automática). O `FPDF` repõe `y` depois do `header`, por isso desenhar ali
    não desloca o conteúdo; no `footer` a posição tem de ser fixada à mão,
    porque o cursor vem de onde o texto parou.

    Como a `_Report` **contém** um `FPDF` (não herda dele), os métodos têm de
    ser ligados ao objeto em `self.pdf.header` / `self.pdf.footer`: definir
    `header`/`footer` na `_Report` sem essa ligação não é chamado por ninguém e
    o PDF saía sem assinatura — a primeira versão fez isso e o teste ao texto
    do PDF foi o que o mostrou.
    """

    def __init__(self, title: str, subtitle: str = "", kind: str = "Documento", doc_id: str = "",
                 total_pages: int | None = None):
        from fpdf import FPDF

        self.title = title
        self.kind = kind
        self.doc_id = doc_id
        self.total_pages = total_pages
        self.emitted_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        self.pdf = FPDF(orientation="P", unit="mm", format="A4")
        # A margem da quebra automática é maior do que a do texto, para o
        # rodapé não ficar por cima da última linha de uma página cheia.
        self.pdf.set_auto_page_break(auto=True, margin=24)
        self.pdf.set_margins(18, 18, 18)
        # Antes do `add_page`: é aí que o `FPDF` chama `header`.
        self.pdf.header = self._brand_header
        self.pdf.footer = self._brand_footer
        self.pdf.add_page()
        self._write(title, size=16, style="B", line_height=9)
        if subtitle:
            self.pdf.set_text_color(*BRAND_MUTED)
            self._write(subtitle, size=9, line_height=5)
            self.pdf.set_text_color(0, 0, 0)
        self.pdf.ln(2)

    # -- assinatura da plataforma em todas as páginas ----------------------
    def _brand_header(self) -> None:
        pdf = self.pdf
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_text_color(*BRAND_ORANGE)
        pdf.cell(17, 6, BRAND, new_x="RIGHT", new_y="TOP")
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*BRAND_MUTED)
        pdf.cell(pdf.epw - 17, 6, _pdf_safe(f"{BRAND_SECTION} · {self.kind}"), align="L",
                 new_x="LMARGIN", new_y="NEXT")
        pdf.set_draw_color(*BRAND_ORANGE)
        pdf.set_line_width(0.4)
        pdf.line(pdf.l_margin, pdf.get_y() + 0.5, pdf.w - pdf.r_margin, pdf.get_y() + 0.5)
        pdf.set_draw_color(0, 0, 0)
        pdf.set_line_width(0.2)
        pdf.set_text_color(0, 0, 0)
        pdf.ln(4)

    def _brand_footer(self) -> None:
        pdf = self.pdf
        pdf.set_y(-19)
        pdf.set_draw_color(*BRAND_RULE)
        pdf.set_line_width(0.3)
        pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
        pdf.ln(1.5)

        pdf.set_font("Helvetica", "B", 7.5)
        pdf.set_text_color(*BRAND_MUTED)
        pdf.cell(pdf.epw - 30, 4, _pdf_safe(BRAND_LINE), new_x="RIGHT", new_y="TOP")
        actual = pdf.page_no()
        count = f"página {actual} de {self.total_pages}" if self.total_pages else f"página {actual}"
        pdf.cell(30, 4, _pdf_safe(count), align="R", new_x="LMARGIN", new_y="NEXT")

        reference = f"{self.kind} {self.doc_id}".strip()
        pdf.set_font("Helvetica", "", 7.5)
        pdf.cell(0, 4, _pdf_safe(f"{reference} · emitido a {self.emitted_at}"), align="L",
                 new_x="LMARGIN", new_y="NEXT")

        pdf.set_draw_color(0, 0, 0)
        pdf.set_line_width(0.2)
        pdf.set_text_color(0, 0, 0)

    def _write(self, text: str, size: float = 10, style: str = "", line_height: float = 5.2) -> None:
        self.pdf.set_font("Helvetica", style, size)
        self.pdf.multi_cell(0, line_height, _pdf_safe(text), new_x="LMARGIN", new_y="NEXT")

    def heading(self, text: str, size: int = 12) -> None:
        self.pdf.ln(3)
        self.pdf.set_font("Helvetica", "B", size)
        self.pdf.set_fill_color(255, 69, 0)
        self.pdf.set_text_color(255, 255, 255)
        self.pdf.cell(0, 7, _pdf_safe(f" {text}"), new_x="LMARGIN", new_y="NEXT", fill=True)
        self.pdf.set_text_color(0, 0, 0)
        self.pdf.ln(1)

    def paragraph(self, text: str, size: float = 10, style: str = "") -> None:
        self._write(text, size=size, style=style)

    def bullet(self, text: str) -> None:
        self._write(f"  - {text}", size=10)

    def output(self) -> bytes:
        data = self.pdf.output()
        return bytes(data)


def _render(build) -> bytes:
    """Gera o PDF em duas passagens, para o rodapé poder dizer «página X de Y».

    O `fpdf2` tem o alias `{nb}` para isto, mas nesta versão (2.8.9) o alias
    dentro do rodapé sai vazio — reproduzido num documento mínimo: o rodapé
    imprimia «página 1 de ». Duas passagens custam milissegundos e não dependem
    de comportamento da biblioteca: a primeira descobre o total, a segunda
    escreve-o no rodapé.

    `build(total_pages)` tem de devolver o `_Report` completo.
    """
    total = build(None).pdf.page_no()
    return build(total).output()


def _strip_markdown(line: str) -> str:
    """Markdown → texto legível (o PDF não interpreta markdown)."""
    text = line.rstrip()
    for token in ("**", "__", "`", "##"):
        text = text.replace(token, "")
    if text.lstrip().startswith(("- ", "* ")):
        text = "  - " + text.lstrip()[2:]
    return text


def _report_document(meta: dict, markdown: str, report_id: str, total_pages) -> _Report:
    doc = _Report(
        meta.get("simulation_requirement") or f"Relatório {report_id}",
        f"ID: {report_id} · simulação: {meta.get('simulation_id') or '—'} · "
        f"criado: {meta.get('created_at') or '—'} · estado: {meta.get('status') or '—'}",
        kind="Relatório de simulação",
        doc_id=f"{report_id} / {meta.get('simulation_id') or '—'}",
        total_pages=total_pages,
    )
    for raw in markdown.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            level = len(line) - len(line.lstrip("#"))
            doc.heading(_strip_markdown(line.lstrip("#").strip()), size=max(10, 14 - level))
        elif line.startswith(("- ", "* ")):
            doc.bullet(_strip_markdown(line[2:]))
        else:
            doc.paragraph(_strip_markdown(line))
    return doc


def _report_pdf(report_id: str) -> bytes:
    folder = _report_folder(report_id)
    meta = _load_json(os.path.join(folder, "meta.json")) or {}
    markdown_path = os.path.join(folder, "full_report.md")
    if not os.path.exists(markdown_path):
        raise FileNotFoundError("Relatório sem `full_report.md`.")

    with open(markdown_path, encoding="utf-8") as handle:
        markdown = handle.read()

    # O texto é lido e validado uma só vez; as duas passagens só recompõem o PDF.
    return _render(lambda total: _report_document(meta, markdown, report_id, total))


def _simulation_document(simulation_id: str, total_pages) -> _Report:
    folder = _folder("simulations", simulation_id)
    state = _load_json(os.path.join(folder, "state.json")) or {}
    run_state = _load_json(os.path.join(folder, "run_state.json")) or {}
    config = _load_json(os.path.join(folder, "simulation_config.json")) or {}
    profiles = _load_json(os.path.join(folder, "reddit_profiles.json")) or []

    doc = _Report(
        f"Simulação {simulation_id}",
        f"Projeto: {state.get('project_id') or '—'} · criada em {state.get('created_at') or '—'}",
        kind="Ficha de simulação",
        doc_id=simulation_id,
        total_pages=total_pages,
    )
    doc.heading("Requisito")
    doc.paragraph(config.get("simulation_requirement") or "Sem requisito registado.")

    doc.heading("Estado")
    for label, value in (
        ("Estado", state.get("status")),
        ("Runner", run_state.get("runner_status")),
        ("Rondas", f"{run_state.get('current_round') or 0} de {run_state.get('total_rounds') or 0}"),
        ("Horas simuladas", run_state.get("simulated_hours")),
        ("Progresso", f"{run_state.get('progress_percent') or 0}%"),
        ("Entidades", state.get("entities_count")),
        ("Personas", state.get("profiles_count")),
        ("Ações registadas", run_state.get("total_actions_count")),
    ):
        doc.bullet(f"{label}: {value if value not in (None, '') else '—'}")

    types = state.get("entity_types") or []
    if types:
        doc.heading("Tipos de entidade")
        doc.paragraph(", ".join(str(t) for t in types))

    if profiles:
        doc.heading(f"Personas ({len(profiles)})")
        # Numa ficha não cabem 40 bios completas: nome, papel e uma linha de bio.
        for profile in profiles:
            name = profile.get("name") or profile.get("username") or "—"
            role = profile.get("profession") or profile.get("country") or ""
            doc.bullet(f"{name} — {role}".strip(" —"))
            bio = (profile.get("bio") or "").strip()
            if bio:
                doc.paragraph(bio[:220], size=8.5, style="I")

    reports = _reports_for(simulation_id)
    if reports:
        doc.heading("Relatórios")
        for report in reports:
            doc.bullet(report)
    return doc


def _simulation_pdf(simulation_id: str) -> bytes:
    return _render(lambda total: _simulation_document(simulation_id, total))


# --------------------------------------------------------------------------
# Rotas
# --------------------------------------------------------------------------
@iqos_bp.delete("/simulations/<simulation_id>")
def delete_simulation(simulation_id: str):
    """Apaga uma simulação e, por omissão, o relatório e o projeto associados.

    Recusa (409) se a simulação estiver a correr: apagar a pasta a meio deixa o
    runner a escrever para caminhos que já não existem.
    """
    try:
        simulation_id = _safe_id(simulation_id, "simulations")
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400

    with_project = request.args.get("project", "0") in ("1", "true", "yes")
    with_reports = request.args.get("reports", "1") not in ("0", "false", "no")
    force = request.args.get("force", "0") in ("1", "true", "yes")

    folder = _folder("simulations", simulation_id)
    if not os.path.isdir(folder):
        return jsonify({"success": False, "error": f"Simulação {simulation_id} não encontrada."}), 404

    state = _load_json(os.path.join(folder, "run_state.json")) or {}
    runner_status = str(state.get("runner_status") or "idle").lower()
    if runner_status in BUSY_STATES and not force:
        return jsonify({
            "success": False,
            "error": (
                f"A simulação está {runner_status}. Pare-a primeiro "
                "(ou use force=1 para parar e apagar)."
            ),
            "runner_status": runner_status,
        }), 409

    stopped = False
    if runner_status in BUSY_STATES and force:
        try:
            from ..services.simulation_runner import SimulationRunner

            SimulationRunner.stop_simulation(simulation_id)
            stopped = True
        except Exception as exc:  # o apagar continua: o objetivo é remover a pasta
            logger.warning("Não foi possível parar %s antes de apagar: %s", simulation_id, exc)

    config = _load_json(os.path.join(folder, "simulation_config.json")) or {}
    project_id = None
    if with_project:
        project_id = state.get("project_id")
        if not project_id:
            # O project_id pode só existir no state.json da simulação.
            project_id = (_load_json(os.path.join(folder, "state.json")) or {}).get("project_id")

    deleted_reports = []
    if with_reports:
        for report in _reports_for(simulation_id):
            if _remove_folder(os.path.join(REPORT_DIR, report)):
                deleted_reports.append(report)

    removed = _remove_folder(folder)
    deleted_project = None
    if with_project and project_id:
        try:
            candidate = _safe_id(str(project_id), "projects")
            if _remove_folder(_folder("projects", candidate)):
                deleted_project = candidate
        except ValueError:
            logger.warning("project_id inválido %r ao apagar %s", project_id, simulation_id)

    if not removed:
        return jsonify({"success": False, "error": "Não foi possível remover a pasta da simulação."}), 500

    logger.info("Simulação %s apagada (relatórios=%s, projeto=%s)", simulation_id, deleted_reports, deleted_project)
    return jsonify({
        "success": True,
        "message": f"Simulação {simulation_id} apagada.",
        "deleted": {
            "simulation_id": simulation_id,
            "reports": deleted_reports,
            "project_id": deleted_project,
            "stopped_runner": stopped,
            "had_config": bool(config),
        },
    })


@iqos_bp.get("/export/simulations.xlsx")
def export_simulations_xlsx():
    """Excel com uma linha por simulação, mais uma folha de resumo."""
    if not _xlsx_available():
        return jsonify({
            "success": False,
            "error": "Exportação Excel indisponível neste ambiente (openpyxl em falta). Use o CSV.",
        }), 501
    rows = _history_rows()
    payload = _simulation_workbook(rows)
    return send_file(
        io.BytesIO(payload),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=f"iqos-simulacoes-{_stamp()}.xlsx",
    )


@iqos_bp.get("/export/simulations.csv")
def export_simulations_csv():
    """CSV (com BOM) — o caminho que funciona mesmo sem openpyxl."""
    rows = _history_rows()
    return send_file(
        io.BytesIO(_simulations_csv(rows)),
        mimetype="text/csv",
        as_attachment=True,
        download_name=f"iqos-simulacoes-{_stamp()}.csv",
    )


@iqos_bp.get("/export/simulations/<simulation_id>.xlsx")
def export_simulation_xlsx(simulation_id: str):
    """Excel detalhado: ficha, personas, execução e relatório."""
    if not _xlsx_available():
        return jsonify({
            "success": False,
            "error": "Exportação Excel indisponível neste ambiente (openpyxl em falta).",
        }), 501
    try:
        folder = _folder("simulations", simulation_id)
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    if not os.path.isdir(folder):
        return jsonify({"success": False, "error": f"Simulação {simulation_id} não encontrada."}), 404

    payload = _simulation_detail_workbook(simulation_id)
    return send_file(
        io.BytesIO(payload),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=f"iqos-{_slug(simulation_id)}-{_stamp()}.xlsx",
    )


@iqos_bp.get("/export/simulations/<simulation_id>.pdf")
def export_simulation_pdf(simulation_id: str):
    """Ficha da simulação em PDF (requisito, estado, tipos de entidade e personas)."""
    if not _pdf_available():
        return jsonify({
            "success": False,
            "error": "Geração de PDF indisponível neste ambiente (fpdf2 em falta).",
        }), 501
    try:
        folder = _folder("simulations", simulation_id)
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    if not os.path.isdir(folder):
        return jsonify({"success": False, "error": f"Simulação {simulation_id} não encontrada."}), 404

    payload = _simulation_pdf(simulation_id)
    return send_file(
        io.BytesIO(payload),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"iqos-{_slug(simulation_id)}-{_stamp()}.pdf",
    )


@iqos_bp.get("/export/reports/<report_id>.pdf")
def export_report_pdf(report_id: str):
    """Relatório completo em PDF (a partir do `full_report.md`)."""
    if not _pdf_available():
        return jsonify({
            "success": False,
            "error": "Geração de PDF indisponível neste ambiente (fpdf2 em falta).",
        }), 501
    try:
        folder = _report_folder(report_id)
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    if not os.path.isdir(folder):
        return jsonify({"success": False, "error": f"Relatório {report_id} não encontrado."}), 404

    try:
        payload = _report_pdf(report_id)
    except FileNotFoundError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404

    return send_file(
        io.BytesIO(payload),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"iqos-{_slug(report_id)}-{_stamp()}.pdf",
    )
