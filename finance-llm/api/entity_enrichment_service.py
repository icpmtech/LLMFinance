from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from bs4 import BeautifulSoup

from api.elasticsearch_client import WORLD_RELATIONS_INDEX, get_es_client
from api.ontology_ai import ask_model, available_backend
from api.tools import web_search

logger = logging.getLogger(__name__)


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _entity_query(nif: str, name: Optional[str], query: Optional[str]) -> str:
    if query and query.strip():
        return query.strip()
    return f"{name or nif} empresa Portugal".strip()


def _extract_top_sources(results: List[Dict[str, Any]], limit: int = 6) -> List[Dict[str, Any]]:
    cleaned: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for item in results or []:
        url = str(item.get("href") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        cleaned.append({
            "title": _safe_text(item.get("title") or item.get("name") or ""),
            "url": url,
            "snippet": _safe_text(item.get("body") or item.get("snippet") or ""),
            "source": str(item.get("source") or "web").strip(),
        })
        if len(cleaned) >= limit:
            break
    return cleaned


def _fetch_page_text(url: str, timeout: int = 12) -> str:
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"}
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    text = resp.text or ""
    soup = BeautifulSoup(text, "html.parser")
    body = soup.get_text(" ", strip=True)
    return _safe_text(body)[:8000]


def _local_ollama_model(timeout: int = 3) -> Optional[str]:
    """Modelo local instalado no Ollama (ignora os que correm na cloud).

    Serve de último recurso quando o utilizador não escolheu nenhum fornecedor:
    sem isto a extração estruturada ficava sempre vazia.
    """
    try:
        resp = requests.get("http://127.0.0.1:11434/api/tags", timeout=timeout)
        resp.raise_for_status()
        models = [str(m.get("name") or "") for m in (resp.json().get("models") or [])]
    except Exception:
        return None
    local = [name for name in models if name and not name.endswith(":cloud")]
    return local[0] if local else None


async def _ask_structured_fields(
    name: str,
    sources: List[Dict[str, Any]],
    nif: str,
    session: Any = None,
    page_texts: Optional[List[str]] = None,
) -> Dict[str, Any]:
    backend = available_backend(session)
    if backend.get("kind") != "cloud":
        # Sem fornecedor escolhido nas Configurações: tenta o Ollama local, se existir.
        model = _local_ollama_model()
        if model:
            local_backend = available_backend(session, backend=f"ollama:{model}")
            if local_backend.get("kind") == "cloud":
                backend = local_backend
    if backend.get("kind") != "cloud":
        note = (
            "Sem fornecedor de IA configurado: escolha um modelo cloud nas Configurações "
            "(ou arranque o Ollama local) para a extração estruturada."
            if backend.get("kind") == "local"
            else "Fornecedor de IA indisponível (sem chave de API)."
        )
        return {
            "entity_name": name,
            "nif": nif,
            "country": "Portugal",
            "status": "unknown",
            "description": "",
            "cae": None,
            "cae_description": None,
            "contacts": [],
            "addresses": [],
            "brands": [],
            "parent_company": None,
            "related_entities": [],
            "notes": [note],
        }

    # O texto das páginas raspadas é a fonte mais rica (CAE, contactos, endereço);
    # sem isto o modelo só via os snippets do motor de busca.
    page_excerpt = "\n\n".join((page_texts or [])[:3])[:6000]
    prompt = f"""
    A partir das fontes abaixo, extrai um JSON válido com estes campos:

    Identificação
    - entity_name (string)
    - legal_name (string ou null: firma registada, se for diferente do nome comercial)
    - legal_form (string ou null: "Lda", "S.A.", "Unipessoal Lda", "Sociedade por quotas", …)
    - country (string)
    - status (string: active, unknown, inactive)
    - description (string: 2 a 4 frases sobre o que a empresa faz)
    - founded_year (número ou null: ano de constituição)
    - nif (string)

    Dados económicos (só quando aparecem explicitamente)
    - share_capital (string ou null: capital social, como está escrito, ex.: "50 000 EUR")
    - employees_band (string ou null: escalão, ex.: "10-49", "50-249")
    - revenue_band (string ou null: volume de negócios/resultado, ex.: "1,2 M EUR (2023)")
    - size_class (string ou null: micro, pequena, média, grande)

    Atividade
    - cae (string ou null: código CAE/CIRS, só o número, ex.: "21200")
    - cae_description (string ou null: descrição da atividade económica do CAE)
    - cae_secondary (lista de strings: outros CAE, com descrição se houver)
    - activities (lista de strings: áreas de atividade em linguagem simples)
    - products_services (lista de strings: produtos e serviços)
    - certifications (lista de strings: certificações, alvarás, licenças, registos)

    Contactos e localização
    - contacts (lista de strings: como aparecem na fonte)
    - emails (lista de strings: endereços de email, sem duplicados)
    - phones (lista de strings: telefones, com indicativo quando houver)
    - website (string ou null: site oficial da própria empresa)
    - socials (objeto: {{"linkedin": string|null, "facebook": string|null, "instagram": string|null, "youtube": string|null, "x": string|null}})
    - addresses (lista de strings: moradas como aparecem na fonte)
    - address (objeto ou null: {{"street": string|null, "postal_code": string|null, "city": string|null, "region": string|null, "country": string|null}})

    Relações e notas
    - brands (lista de strings: marcas/firmas conhecidas)
    - parent_company (string ou null)
    - related_entities (lista de objetos com {{"name": string, "kind": string, "evidence": string}})
    - public_flags (lista de strings: factos públicos relevantes — insolvência, PER, dívidas, processos — só se a fonte o disser)
    - notes (lista de strings)

    Atenção: não inventes dados. Se não houver informação explícita, usa [] ou null.
    O CAE aparece em sites como Racius/eInforma sob «CAE» ou «Atividade principal».
    O capital social aparece em fichas registais sob «Capital Social». Preenche `size_class`
    (micro/pequena/média/grande) só quando o número de trabalhadores ou o volume constarem.
    Preenche `website` apenas com o domínio da própria empresa (não com diretórios).

    Empresa: {name}
    NIF: {nif}
    Fontes:
    {json.dumps(sources, ensure_ascii=False, indent=2)[:12000]}

    Texto das páginas oficiais:
    {page_excerpt}
    """
    raw = await ask_model(
        backend,
        system="És um analista de empresas. Devolves apenas JSON válido em português de Portugal.",
        prompt=prompt,
        max_tokens=2600,
        temperature=0.1,
    )
    text = str(raw or "").strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        candidate = text[start : end + 1]
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {
        "entity_name": name,
        "nif": nif,
        "country": "Portugal",
        "status": "unknown",
        "description": "",
        "cae": None,
        "cae_description": None,
        "contacts": [],
        "addresses": [],
        "brands": [],
        "parent_company": None,
        "related_entities": [],
        "notes": [],
    }


def _save_entity_doc(nif: str, name: str, payload: Dict[str, Any], summary: Dict[str, Any]) -> bool:
    from api.elasticsearch_client import ENTITIES_INDEX, ensure_indices

    doc = {
        "nif": nif,
        "name": name,
        "enrichment_web": payload,
        "enrichment_last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "enrichment_summary": summary,
    }
    client = get_es_client(request_timeout=30)
    if client is None:
        return False
    try:
        ensure_indices(client)
    except Exception:
        pass
    # O cadastro de entidades usa IDs no formato "finance_entities:<nif>".
    doc_id = f"{ENTITIES_INDEX}:{nif}"
    try:
        client.update(index=ENTITIES_INDEX, id=doc_id, body={"doc": doc, "doc_as_upsert": True}, refresh=True)
        return True
    except Exception:
        try:
            client.index(index=ENTITIES_INDEX, id=doc_id, document=doc, refresh=True)
            return True
        except Exception:
            return False


def _canonical_kind(kind: Any) -> str:
    """Normaliza o tipo de relação para um vocabulário fixo da ontologia.

    O LLM devolve rótulos livres («Divisão/Subsidiária», «empresa-mãe»); sem isto
    a mesma relação aparecia com dois nomes e duplicava o grafo.
    """
    raw = _safe_text(kind).lower()
    if not raw:
        return "related"
    slug = re.sub(r"[^a-z0-9]+", "_", raw.replace("ã", "a").replace("ç", "c").replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o").replace("ú", "u")).strip("_")
    aliases = {
        "parent": "parent_company",
        "parent_company": "parent_company",
        "empresa_mae": "parent_company",
        "grupo": "parent_company",
        "grupo_empresa_mae": "parent_company",
        "holding": "parent_company",
        "mother_company": "parent_company",
        "subsidiary": "subsidiary",
        "subsidiaria": "subsidiary",
        "divisao_subsidiaria": "subsidiary",
        "divisao": "subsidiary",
        "filial": "subsidiary",
        "division": "subsidiary",
        "supplier": "supplier",
        "fornecedor": "supplier",
        "customer": "customer",
        "cliente": "customer",
        "shareholder": "shareholder",
        "socio": "shareholder",
        "acionista": "shareholder",
        "partner": "partner",
        "parceiro": "partner",
        "joint_venture": "partner",
        "person": "person",
        "pessoa": "person",
        "gerente": "person",
        "administrador": "person",
    }
    return aliases.get(slug, slug or "related")


def _save_relations(nif: str, name: str, links: List[Dict[str, Any]]) -> int:
    from api.elasticsearch_client import ensure_indices

    client = get_es_client(request_timeout=30)
    if client is None or not links:
        return 0
    try:
        ensure_indices(client)
    except Exception:
        pass
    saved = 0
    for link in links:
        source_name = str(link.get("source_name") or name)
        source_ref = str(link.get("source_ref") or nif)
        target_ref = str(link.get("target_ref") or "")
        target_name = str(link.get("target_name") or link.get("target") or "")
        if not target_ref or source_ref == target_ref:
            continue
        relation_id = f"{link.get('kind','related')}:{source_ref}>{target_ref}"
        evidence = [str(link.get("evidence") or "")]
        # A mesma aresta pode voltar noutra recolha: junta as provas em vez de as trocar.
        try:
            previous = client.get(index=WORLD_RELATIONS_INDEX, id=relation_id)["_source"]
            for item in previous.get("evidence") or []:
                if item and item not in evidence:
                    evidence.append(str(item))
        except Exception:
            pass
        doc = {
            "relation_id": relation_id,
            "kind": str(link.get("kind") or "related"),
            "source_ref": source_ref,
            "source_name": source_name,
            "source_type": str(link.get("source_type") or "empresa"),
            "target_ref": target_ref,
            "target_name": target_name,
            "target_type": str(link.get("target_type") or "entidade"),
            "evidence": evidence,
            "country": str(link.get("country") or "Portugal"),
            "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        try:
            client.index(index=WORLD_RELATIONS_INDEX, id=relation_id, document=doc, refresh=True)
            saved += 1
        except Exception:
            continue
    return saved


def _entity_report_blocks(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Secções do relatório: `{title, columns?, rows}` (o mesmo modelo dos outros relatórios)."""
    blocks: List[Dict[str, Any]] = []

    cae = str(payload.get("cae") or "").strip()
    cae_desc = str(payload.get("cae_description") or "").strip()
    identificacao = [
        ["Estado", payload.get("status") or "N/D"],
        ["CAE", (f"{cae} — {cae_desc}" if cae and cae_desc else cae or "N/D")],
        ["País", payload.get("country") or "Portugal"],
        ["Grupo / empresa-mãe", payload.get("parent_company") or "N/D"],
    ]
    if payload.get("contracts_total"):
        identificacao.append(["Contratos indexados", f"{int(payload['contracts_total']):,}".replace(",", " ")])
    if payload.get("contracts_total_value"):
        identificacao.append(["Valor contratado", _fmt_money(payload.get("contracts_total_value"))])
    if payload.get("enriched_at"):
        identificacao.append(["Enriquecido em", str(payload.get("enriched_at"))])
    blocks.append({"title": "Identificação", "rows": identificacao})

    description = str(payload.get("description") or "").strip()
    if description:
        blocks.append({"title": "Atividade", "rows": [["Descrição", description]]})

    cpv_rows = payload.get("cpv_rows") or []
    if cpv_rows:
        total = payload.get("contracts_total_value")
        rows = []
        for row in cpv_rows[:12]:
            share = ""
            value = row.get("total_value")
            if isinstance(value, (int, float)) and isinstance(total, (int, float)) and total:
                share = f" ({value / total * 100:.1f}%)"
            rows.append([
                str(row.get("key") or "—"),
                str(row.get("description") or "—"),
                _fmt_money(value) + share,
                str(row.get("count") if row.get("count") is not None else ""),
            ])
        blocks.append({
            "title": "CPV mais contratados",
            "columns": ["Código", "Descrição", "Valor", "Nº"],
            "rows": rows,
        })

    for title, key, columns in (
        ("Endereços", "addresses", ["Endereço"]),
        ("Contactos", "contacts", ["Contacto"]),
        ("Marcas", "brands", ["Marca"]),
    ):
        values = payload.get(key) or []
        if values:
            blocks.append({"title": title, "columns": columns, "rows": [[str(v)] for v in values[:20]]})

    related = payload.get("related_entities") or []
    if related:
        rows = []
        for item in related[:20]:
            if not isinstance(item, dict):
                rows.append([str(item), "", ""])
                continue
            rows.append([
                str(item.get("name") or "—"),
                str(item.get("kind") or "—"),
                str(item.get("evidence") or ""),
            ])
        blocks.append({
            "title": "Entidades relacionadas (extração IA)",
            "columns": ["Nome", "Tipo", "Evidência"],
            "rows": rows,
        })

    relations = payload.get("relations") or []
    if relations:
        rows = []
        for rel in relations[:25]:
            rows.append([
                "→" if rel.get("direction") == "out" else "←",
                str(rel.get("other_name") or rel.get("other_ref") or "—"),
                str(rel.get("kind") or "relacionada"),
                " / ".join(str(e) for e in (rel.get("evidence") or []) if e),
            ])
        blocks.append({
            "title": "Relações (ontologia)",
            "columns": ["Sentido", "Entidade", "Tipo", "Evidência"],
            "rows": rows,
        })

    sources = payload.get("sources") or []
    if sources:
        rows = [[str(s.get("title") or s.get("url") or "—"), str(s.get("url") or "")] for s in sources[:15]]
        blocks.append({"title": "Fontes", "columns": ["Título", "URL"], "rows": rows})

    return blocks


def _fmt_money(value: Any) -> str:
    if isinstance(value, (int, float)):
        return f"{value:,.2f} €".replace(",", " ").replace(".", ",")
    return "N/D"


def _generate_pdf_report(
    nif: str,
    name: str,
    payload: Dict[str, Any],
    *,
    titulo: str = "Relatório da entidade",
    notas: Optional[List[str]] = None,
    prefixo: str = "entity",
    blocos: Optional[List[Dict[str, Any]]] = None,
) -> Optional[str]:
    """Relatório da entidade com o logótipo/dados do IQ OS no cabeçalho e rodapé em todas as páginas.

    Usa o mesmo modelo de secções dos restantes relatórios da plataforma
    (`contribuintes_report`), para que a marca seja consistente. É o mesmo
    gerador para o relatório da entidade e para o relatório de processos: muda
    o título, as secções (`blocos`) e as notas legais.
    """
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.pdfgen import canvas
        from reportlab.platypus import (
            Image as PdfImage,
            KeepTogether,
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )
    except Exception:
        return None

    from api.contribuintes_report import BRAND, BRAND_TAGLINE, logo_path

    out_dir = Path(__file__).resolve().parents[1] / "data" / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    file_name = f"{prefixo}_{nif}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}.pdf"
    path = out_dir / file_name

    brand_color = colors.HexColor("#0F766E")
    dark = colors.HexColor("#0F172A")
    muted = colors.HexColor("#64748B")
    zebra = colors.HexColor("#F1F5F9")

    base = getSampleStyleSheet()
    title_style = ParagraphStyle("ent-title", parent=base["Title"], fontSize=16, leading=19, textColor=dark, alignment=0)
    brand_style = ParagraphStyle("ent-brand", parent=base["Normal"], fontSize=10, leading=12, textColor=brand_color, fontName="Helvetica-Bold")
    sub_style = ParagraphStyle("ent-sub", parent=base["Normal"], fontSize=9, leading=12, textColor=muted)
    section_style = ParagraphStyle("ent-section", parent=base["Normal"], fontSize=11, leading=14, textColor=dark, fontName="Helvetica-Bold", spaceBefore=8, spaceAfter=4)
    cell_style = ParagraphStyle("ent-cell", parent=base["Normal"], fontSize=8, leading=10, textColor=dark)
    cell_muted = ParagraphStyle("ent-cell-muted", parent=cell_style, textColor=muted, fontName="Helvetica-Bold")

    def paragraph(value: Any, style: Any = cell_style) -> Any:
        text = str(value if value is not None else "")
        escape = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return Paragraph(escape or "—", style)

    # --- Cabeçalho da primeira página: logótipo + dados da plataforma ---
    story: List[Any] = []
    logo = logo_path()
    if logo:
        try:
            story.append(PdfImage(str(logo), width=13 * mm, height=13 * mm))
            story.append(Spacer(1, 4))
        except Exception as exc:  # pragma: no cover - depende do Pillow
            logger.debug("Logótipo não embutido no relatório da entidade: %s", exc)
    story.append(Paragraph(f"{BRAND} · {BRAND_TAGLINE}", brand_style))
    story.append(Spacer(1, 2))
    story.append(Paragraph(titulo, title_style))
    story.append(Paragraph(name, ParagraphStyle("ent-name", parent=base["Normal"], fontSize=13, leading=16, textColor=dark, fontName="Helvetica-Bold")))
    story.append(Paragraph(f"NIF {nif}", sub_style))
    generated = datetime.now(timezone.utc).strftime("%d/%m/%Y às %H:%M UTC")
    story.append(Spacer(1, 4))
    story.append(Paragraph(f"Gerado pelo {BRAND} em {generated}", sub_style))
    story.append(Spacer(1, 10))

    table_style = TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), brand_color),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8.5),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CBD5E1")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, zebra]),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ])

    for block in (blocos if blocos is not None else _entity_report_blocks(payload)):
        rows = block.get("rows") or []
        if not rows:
            continue
        story.append(Paragraph(str(block["title"]), section_style))
        columns = block.get("columns")
        if columns:
            data = [[paragraph(col, ParagraphStyle("h", parent=cell_style, textColor=colors.white, fontName="Helvetica-Bold")) for col in columns]]
            data.extend([[paragraph(cell) for cell in row] for row in rows])
            table = Table(data, colWidths=[None] * len(columns), repeatRows=1)
        else:
            data = [[paragraph("Campo", cell_muted), paragraph("Valor", cell_muted)]]
            data.extend([[paragraph(label, cell_muted), paragraph(value)] for label, value in (r[:2] for r in rows)])
            table = Table(data, colWidths=[45 * mm, None], repeatRows=1)
        table.setStyle(table_style)
        story.append(KeepTogether(table) if len(data) <= 14 else table)
        story.append(Spacer(1, 8))

    if notas:
        story.append(Paragraph("Notas legais", section_style))
        for numero, nota in enumerate(notas, start=1):
            story.append(Paragraph(f"{numero}. {nota}", sub_style))
            story.append(Spacer(1, 2))
        story.append(Spacer(1, 6))

    story.append(Paragraph(f"Fim do relatório — {BRAND} · {BRAND_TAGLINE}.", sub_style))

    class _NumberedCanvas(canvas.Canvas):
        """Marca do IQ OS em todas as páginas (cabeçalho de continuidade + rodapé)."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self._states: List[Dict[str, Any]] = []

        def showPage(self) -> None:  # noqa: N802 (API do reportlab)
            self._states.append(dict(self.__dict__))
            self._startPage()

        def save(self) -> None:
            total = len(self._states)
            for state in self._states:
                self.__dict__.update(state)
                self._marca(total)
                super().showPage()
            super().save()

        def _logo(self, x: float, y: float, lado: float) -> float:
            """Desenha o logótipo (se existir) e devolve o x a seguir a ele."""
            if not logo:
                return x
            try:
                self.drawImage(str(logo), x, y, width=lado, height=lado, mask="auto")
                return x + lado + 3
            except Exception:  # pragma: no cover - depende do Pillow
                return x

        def _marca(self, total: int) -> None:
            """Logótipo + dados da plataforma no cabeçalho de cada página e no rodapé."""
            self.saveState()
            largura, altura = A4
            numero = self.getPageNumber()
            linha = colors.HexColor("#E2E8F0")

            # A 1.ª página leva o cabeçalho completo na própria story; nas seguintes
            # repete-se uma versão compacta, para o leitor não perder a identidade.
            if numero > 1:
                x = self._logo(18, altura - 40, 9 * mm)
                self.setFont("Helvetica-Bold", 8.5)
                self.setFillColor(brand_color)
                self.drawString(x, altura - 32, f"{BRAND} · {BRAND_TAGLINE}")
                self.setFont("Helvetica", 7.5)
                self.setFillColor(muted)
                self.drawString(x, altura - 41, f"{titulo} — {name} · NIF {nif}")
                self.setStrokeColor(linha)
                self.setLineWidth(0.5)
                self.line(18, altura - 48, largura - 18, altura - 48)

            # Rodapé (todas as páginas): marca + entidade + numeração.
            self.setStrokeColor(linha)
            self.setLineWidth(0.5)
            self.line(18, 32, largura - 18, 32)
            x_rodape = self._logo(18, 14, 7 * mm)
            self.setFont("Helvetica", 7.5)
            self.setFillColor(muted)
            self.drawString(x_rodape, 21, f"{BRAND} — {BRAND_TAGLINE}")
            self.drawCentredString(largura / 2, 21, f"Entidade {name} · NIF {nif}")
            self.drawRightString(largura - 18, 21, f"Página {numero} de {total}")
            self.restoreState()

    document = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        leftMargin=18,
        rightMargin=18,
        topMargin=54,
        bottomMargin=46,
        title=f"{titulo} — {name} · {BRAND}",
        author=BRAND,
        subject=f"{BRAND} — {BRAND_TAGLINE}",
    )
    document.build(story, canvasmaker=_NumberedCanvas)
    return str(path)


def build_entity_report_pdf(nif: str) -> Optional[str]:
    """Gera o PDF da entidade com o que está guardado (enriquecimento + CPV dos contratos).

    É este o relatório que a ficha descarrega: junta o enriquecimento web, a ontologia
    e os CPV mais contratados, para o dossiê não sair pela metade.
    """
    from api.elasticsearch_client import (
        ENTITIES_INDEX,
        ensure_indices,
        get_company_analytics,
        get_entity_relations,
    )

    client = get_es_client(request_timeout=30)
    payload: Dict[str, Any] = {}
    name = nif
    if client is not None:
        try:
            ensure_indices(client)
            doc = client.get(index=ENTITIES_INDEX, id=f"{ENTITIES_INDEX}:{nif}")["_source"]
            payload = dict(doc.get("enrichment_web") or {})
            name = str(doc.get("name") or payload.get("entity_name") or nif)
        except Exception as exc:
            logger.warning("Relatório de %s: sem enriquecimento guardado (%s)", nif, exc)

    try:
        analytics = get_company_analytics(nif=nif)
        cpv_rows = analytics.get("by_cpv") or []
        if cpv_rows:
            payload["cpv_rows"] = cpv_rows
        if analytics.get("total_contracts"):
            payload["contracts_total"] = analytics.get("total_contracts")
            payload["contracts_total_value"] = analytics.get("total_value")
    except Exception as exc:
        logger.warning("Relatório de %s: falha ao ler CPV (%s)", nif, exc)

    relations = get_entity_relations(nif)
    if relations.get("items"):
        payload["relations"] = relations["items"]

    return _generate_pdf_report(nif, name, payload)


# ---------------------------------------------------------------------------
# Relatório de processos e dados da empresa (modelo «Relatório de Processos»)
# ---------------------------------------------------------------------------

#: Notas legais do relatório de processos (texto simples: o `Paragraph` do
#: reportlab só entende um subconjunto de HTML, por isso só há `<b>`).
NOTAS_LEGAIS_PROCESSOS: List[str] = [
    "<b>Natureza e utilização da informação.</b> Este relatório é produzido pelo IQ OS a partir de "
    "fontes públicas — contratos do Portal BASE, publicações de atos societários do Ministério da "
    "Justiça, publicações do CIRE (insolvências e revitalizações), citações e notificações editais, "
    "listas públicas de devedores das Finanças e da Segurança Social — e de conteúdo recolhido de "
    "terceiros. Apesar dos critérios de recolha e validação, o IQ OS não garante a exatidão, a "
    "completude ou a atualização permanente da informação, podendo existir divergências, omissões ou "
    "alterações posteriores à data de emissão. O relatório tem natureza informativa e de apoio à "
    "avaliação de risco, não constituindo aconselhamento jurídico, fiscal, contabilístico ou "
    "financeiro.",
    "<b>Processos judiciais.</b> A identificação das partes nos processos publicados depende da "
    "informação disponibilizada pelos tribunais. Nem todas as publicações incluem o NIF/NIPC das "
    "partes, pelo que podem surgir processos com nomes iguais ou semelhantes ao da entidade em "
    "análise, ou faltar processos em que ela seja parte. É responsabilidade do utilizador confirmar "
    "junto do tribunal competente qualquer processo aqui listado.",
    "<b>Insolvências e PER.</b> A presença na lista pública de execuções ou a publicação de uma "
    "insolvência não é, por si só, impedimento a que a situação seja regularizada: os processos podem "
    "ser extintos, o pagamento pode ocorrer a qualquer momento e a entidade pode sair da lista.",
    "<b>Diligência do utilizador.</b> As decisões tomadas com base neste relatório são da exclusiva "
    "responsabilidade do utilizador, que deve complementar a informação com diligências próprias e "
    "com os seus instrumentos de análise de risco.",
]


def _primeiro(dados: Dict[str, Any], *chaves: str) -> Any:
    """Primeiro valor preenchido entre várias grafias possíveis do mesmo campo."""
    for chave in chaves:
        valor = dados.get(chave)
        if valor not in (None, "", [], {}):
            return valor
    return None


def _texto(valor: Any) -> str:
    if isinstance(valor, (list, tuple)):
        return ", ".join(str(v) for v in valor if v not in (None, ""))
    if isinstance(valor, dict):
        return str(_primeiro(valor, "nome", "name", "raw", "value") or "")
    return str(valor if valor is not None else "").strip()


def _iso(valor: Any) -> str:
    """Data em ISO curto (AAAA-MM-DD) a partir de texto ou lista."""
    texto = _texto(valor)
    return texto[:10] if len(texto) >= 10 else texto


def _nomes(parte: Any) -> List[str]:
    """Nomes de uma parte do contrato (adjudicante/adjudicatário), em qualquer formato."""
    if not parte:
        return []
    if isinstance(parte, dict):
        nomes = [str(p.get("nome")) for p in (parte.get("parsed") or []) if isinstance(p, dict) and p.get("nome")]
        if nomes:
            return nomes
        return [str(x) for x in (parte.get("raw") or [])]
    if isinstance(parte, list):
        saida: List[str] = []
        for item in parte:
            saida.extend(_nomes(item))
        return saida
    return [str(parte)]


def _banda_idade(anos: Optional[int]) -> Optional[str]:
    """Banda de idade da entidade (como nos relatórios de risco)."""
    if anos is None:
        return None
    if anos < 5:
        return "Recém-constituída — menos de 5 anos"
    if anos <= 10:
        return "Jovem — de 5 a 10 anos"
    if anos <= 20:
        return "Madura — de 10 a 20 anos"
    return "Antiga — mais de 20 anos"


def _anos_desde(valor: Any) -> Optional[int]:
    texto = _iso(valor)
    try:
        ano = int(str(texto)[:4])
    except (TypeError, ValueError):
        return None
    if ano < 1800 or ano > datetime.now(timezone.utc).year:
        return None
    return datetime.now(timezone.utc).year - ano


def _processos_dados(nif: str) -> Dict[str, Any]:
    """Junta o que os módulos do IQ OS sabem sobre a entidade, para o relatório.

    Cada fonte é independente: uma falha (índice em baixo, módulo sem dados)
    não impede o relatório — a secção correspondente desaparece ou sai vazia.
    """
    from api.elasticsearch_client import ENTITIES_INDEX, get_company_analytics

    nif = str(nif or "").strip()
    dados: Dict[str, Any] = {"nif": nif, "name": nif, "erros": []}

    client = get_es_client(request_timeout=30)
    if client is not None:
        try:
            doc = dict(client.get(index=ENTITIES_INDEX, id=f"{ENTITIES_INDEX}:{nif}")["_source"])
            enriquecimento = dict(doc.get("enrichment_web") or {})
            bruto = str(doc.get("name") or enriquecimento.get("entity_name") or nif)
            # O cadastro traz por vezes um prefixo de ordenação («1 - EMPRESA …»).
            dados["name"] = re.sub(r"^\s*\d+\s*[-–—]\s*", "", bruto).strip() or bruto
            dados["cadastro"] = doc
            dados["enriquecimento"] = enriquecimento
            for campo, chaves in {
                "cae": ("cae", "cae_principal"),
                "cae_description": ("cae_description", "cae_descricao"),
                "status": ("status", "situacao", "state"),
                "description": ("description", "descricao", "objecto_social", "objeto_social"),
                "capital_social": ("capital_social", "capitalSocial", "share_capital"),
                "morada": ("address", "morada", "sede"),
                "concelho": ("municipality", "concelho"),
                "distrito": ("district", "distrito"),
                "nuts": ("nuts", "nuts_iii", "regiao"),
                "constituicao": (
                    "founded_at",
                    "incorporation_date",
                    "data_constituicao",
                    "constituicao",
                    "start_date",
                ),
                "natureza_juridica": ("natureza_juridica", "legal_form"),
            }.items():
                valor = _primeiro({**enriquecimento, **doc}, *chaves)
                if valor not in (None, "", [], {}):
                    dados[campo] = valor
        except Exception as exc:  # noqa: BLE001 - o relatório sai sem o cadastro
            dados["erros"].append(f"cadastro: {exc}")
            logger.warning("Relatório de processos de %s: sem cadastro (%s)", nif, exc)

    try:
        analytics = get_company_analytics(nif=nif) or {}
        dados["contracts_total"] = analytics.get("total_contracts")
        dados["contracts_value"] = analytics.get("total_value")
        dados["by_cpv"] = analytics.get("by_cpv") or []
        dados["by_year"] = analytics.get("by_year") or []
    except Exception as exc:  # noqa: BLE001
        dados["erros"].append(f"contratos: {exc}")

    try:
        from api.elasticsearch_client import get_company_contracts

        contratos = get_company_contracts(nif=nif, role="all", size=15)
        dados["contratos"] = contratos.get("items") or []
        dados["contratos_total"] = contratos.get("total")
    except Exception as exc:  # noqa: BLE001
        dados["erros"].append(f"contratos recentes: {exc}")

    try:
        from api.societario_service import company_publicacoes

        publicacoes = company_publicacoes(nif, size=200)
        dados["societario"] = publicacoes.get("items") or []
        dados["societario_total"] = publicacoes.get("total")
    except Exception as exc:  # noqa: BLE001
        dados["erros"].append(f"societário: {exc}")

    try:
        from api.elasticsearch_client import search_cire

        cire = search_cire(nif=nif, size=200)
        dados["cire"] = cire
    except Exception as exc:  # noqa: BLE001
        dados["erros"].append(f"CIRE: {exc}")

    try:
        from api.elasticsearch_client import search_citacoes

        citacoes = search_citacoes(nif=nif, size=100, with_texto=False)
        dados["citacoes"] = citacoes
    except Exception as exc:  # noqa: BLE001
        dados["erros"].append(f"citações: {exc}")

    try:
        from api import devedores_service

        dados["devedores"] = devedores_service.por_nif(nif)
    except Exception as exc:  # noqa: BLE001
        dados["erros"].append(f"devedores: {exc}")

    return dados


def _papeis_no_cire(dados: Dict[str, Any]) -> Dict[str, int]:
    """Quantas publicações do CIRE por papel da entidade (Insolvente, Credor, …)."""
    nif = str(dados.get("nif") or "")
    contagem: Dict[str, int] = {}
    for item in (dados.get("cire") or {}).get("items") or []:
        for parte in item.get("intervenientes") or []:
            if str(parte.get("nif") or "").strip() != nif:
                continue
            papel = str(parte.get("papel") or "Interveniente")
            contagem[papel] = contagem.get(papel, 0) + 1
    return contagem


def _papeis_nas_citacoes(dados: Dict[str, Any]) -> Dict[str, int]:
    """Papéis da entidade nos éditos (Executado, Réu, Exequente, Credor, …)."""
    nif = str(dados.get("nif") or "")
    nome = str(dados.get("name") or "").strip().lower()
    contagem: Dict[str, int] = {}
    for item in (dados.get("citacoes") or {}).get("items") or []:
        papeis = item.get("papeis") or item.get("intervenientes") or []
        for parte in papeis if isinstance(papeis, list) else []:
            if not isinstance(parte, dict):
                continue
            parte_nif = str(parte.get("nif") or "").strip()
            parte_nome = str(parte.get("nome") or "").strip().lower()
            if parte_nif and parte_nif == nif:
                pass
            elif nome and parte_nome and (nome in parte_nome or parte_nome in nome):
                pass
            else:
                continue
            papel = str(parte.get("papel") or parte.get("tipo") or "Interveniente")
            contagem[papel] = contagem.get(papel, 0) + 1
    if not contagem:
        for item in (dados.get("citacoes") or {}).get("items") or []:
            papel = str(item.get("papel") or "").strip()
            if papel:
                contagem[papel] = contagem.get(papel, 0) + 1
    return contagem


def _processos_blocks(dados: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Secções do relatório de processos (mesmo modelo de blocos dos outros)."""
    blocos: List[Dict[str, Any]] = []
    cadastro = dados.get("cadastro") or {}
    enrich = dados.get("enriquecimento") or {}

    # Sem nenhuma fonte a responder o relatório sairia vazio sem explicação: diz-se.
    if dados.get("erros") and not any(
        [
            dados.get("contracts_total"),
            (dados.get("cire") or {}).get("total"),
            (dados.get("citacoes") or {}).get("total"),
            dados.get("cadastro"),
        ]
    ):
        blocos.append(
            {
                "title": "Aviso",
                "rows": [
                    [
                        "Fontes de dados",
                        "As fontes do IQ OS não responderam a este pedido, por isso o relatório pode estar "
                        "incompleto. Volte a gerar o relatório dentro de alguns minutos.",
                    ]
                ],
            }
        )

    # --- Resumo / identificação -------------------------------------------
    anos = _anos_desde(dados.get("constituicao"))
    situacao = _texto(dados.get("status"))
    if situacao.lower() in ("unknown", "desconhecido", "desconhecida", "n/d", "nd"):
        situacao = ""
    resumo = [
        ["Denominação", dados.get("name") or "—"],
        ["NIF/NIPC", dados.get("nif") or "—"],
        ["Situação", situacao or "—"],
        ["Natureza jurídica", _texto(dados.get("natureza_juridica")) or "—"],
        ["Morada", _texto(dados.get("morada")) or _texto(_primeiro(enrich, "address", "morada")) or "—"],
        ["Concelho", _texto(dados.get("concelho")) or "—"],
        ["Distrito", _texto(dados.get("distrito")) or "—"],
        ["NUTS III", _texto(dados.get("nuts")) or "—"],
        ["Capital social", _fmt_money(dados.get("capital_social")) if dados.get("capital_social") else "—"],
        ["Data de constituição", _iso(dados.get("constituicao")) or "—"],
        ["Idade", _banda_idade(anos) or "—"],
    ]
    cae = _texto(dados.get("cae"))
    if cae:
        descricao_cae = _texto(dados.get("cae_description"))
        resumo.append(["CAE", f"{cae} — {descricao_cae}" if descricao_cae else cae])
    blocos.append({"title": "Resumo da entidade", "rows": resumo})

    # --- Indicadores (page 1 do modelo) -----------------------------------
    papeis_cire = _papeis_no_cire(dados)
    papeis_cit = _papeis_nas_citacoes(dados)
    devedores = dados.get("devedores") or {}
    cire_total = int((dados.get("cire") or {}).get("total") or 0)
    cit_total = int((dados.get("citacoes") or {}).get("total") or 0)
    contratos = int(dados.get("contracts_total") or 0)

    def _papeis_texto(papeis: Dict[str, int], amostra: bool = False) -> str:
        if not papeis:
            return "—"
        texto = " · ".join(
            f"{papel}: {quantidade}"
            for papel, quantidade in sorted(papeis.items(), key=lambda par: -par[1])[:4]
        )
        # A contagem vem da amostra lida (não do índice inteiro), por isso é dita assim.
        return f"{texto} (na amostra lida)" if amostra else texto

    escaloes = devedores.get("escaloes") or []
    fontes_divida = ", ".join(str(e) for e in (devedores.get("entidades") or [])) or "—"
    indicadores = [
        [
            "Contratos públicos",
            (
                f"{contratos:,}".replace(",", " ") + f" contratos · {_fmt_money(dados.get('contracts_value'))}"
                if contratos
                else "Sem contratos indexados"
            ),
        ],
        ["Insolvências / PER", f"{cire_total} publicações · {_papeis_texto(papeis_cire, amostra=True)}" if cire_total else "Nada encontrado"],
        ["Processos judiciais (éditos)", f"{cit_total} publicações · {_papeis_texto(papeis_cit)}" if cit_total else "Nada encontrado"],
        [
            "Situação fiscal e contributiva",
            (
                f"Com registo em listas de devedores ({fontes_divida}) · escalões: {', '.join(str(e) for e in escaloes[:3])}"
                if devedores.get("devedor")
                else "Sem registo nas listas públicas de devedores (Finanças e Segurança Social)"
            ),
        ],
        [
            "Adjudicatário / adjudicante",
            " · ".join(
                filter(
                    None,
                    [
                        f"adjudicatário desde {cadastro.get('adjudicatario', {}).get('first_year')}"
                        if (cadastro.get("adjudicatario") or {}).get("first_year")
                        else "",
                        f"adjudicante desde {cadastro.get('adjudicante', {}).get('first_year')}"
                        if (cadastro.get("adjudicante") or {}).get("first_year")
                        else "",
                    ],
                )
            )
            or "—",
        ],
        ["Atos societários (MJ)", f"{int(dados.get('societario_total') or 0)} publicações recolhidas" if dados.get("societario_total") else "Nada encontrado"],
    ]
    blocos.append({"title": "Indicadores", "rows": indicadores})

    # --- Atividade --------------------------------------------------------
    descricao = _texto(dados.get("description"))
    if descricao:
        blocos.append({"title": "Objeto social / atividade", "rows": [["Descrição", descricao]]})

    # --- Insolvências / PER ----------------------------------------------
    itens_cire = sorted(
        (dados.get("cire") or {}).get("items") or [],
        key=lambda item: str(item.get("data_publicacao") or ""),
        reverse=True,
    )
    if itens_cire:
        nif = str(dados.get("nif") or "")
        vistos: set[str] = set()
        linhas = []
        for item in itens_cire:
            # Várias publicações do mesmo processo (atos diferentes): fica só a última.
            chave = str(item.get("processo") or item.get("pub_id") or "")
            if chave in vistos:
                continue
            vistos.add(chave)
            papel = "—"
            for parte in item.get("intervenientes") or []:
                if str(parte.get("nif") or "").strip() == nif:
                    papel = str(parte.get("papel") or "—")
                    break
            linhas.append(
                [
                    _iso(item.get("data_publicacao")) or "—",
                    _texto(item.get("tribunal")) or "—",
                    _texto(item.get("processo")) or "—",
                    _texto(_primeiro(item, "tipo", "especie")) or "—",
                    papel,
                ]
            )
            if len(linhas) >= 15:
                break
        blocos.append(
            {
                "title": f"Insolvências / PER — processos mais recentes (de {cire_total} publicações)",
                "columns": ["Data", "Tribunal", "Processo", "Tipo", "Papel da entidade"],
                "rows": linhas,
            }
        )

    # --- Processos judiciais (éditos) -------------------------------------
    itens_cit = sorted(
        (dados.get("citacoes") or {}).get("items") or [],
        key=lambda item: str(_primeiro(item, "data_publicacao", "data") or ""),
        reverse=True,
    )
    if itens_cit:
        linhas = []
        for item in itens_cit[:15]:
            linhas.append(
                [
                    _iso(_primeiro(item, "data_publicacao", "data")) or "—",
                    _texto(_primeiro(item, "tribunal", "tribunal_sede")) or "—",
                    _texto(_primeiro(item, "tipo", "ato", "especie")) or "—",
                    _texto(_primeiro(item, "processo", "processo_numero", "referencia")) or "—",
                    _fmt_money(_primeiro(item, "documento_valor", "valor")) if _primeiro(item, "documento_valor", "valor") else "—",
                ]
            )
        blocos.append(
            {
                "title": f"Processos judiciais — éditos (últimos, de {cit_total} publicações)",
                "columns": ["Data", "Tribunal", "Tipo / ato", "Processo", "Valor"],
                "rows": linhas,
            }
        )

    # --- Situação fiscal e contributiva -----------------------------------
    registos_divida = devedores.get("items") or []
    if registos_divida:
        blocos.append(
            {
                "title": "Listas públicas de devedores",
                "columns": ["Fonte", "Entidade", "Escalão", "Valor mínimo"],
                "rows": [
                    [
                        _texto(_primeiro(registo, "fonte", "lista")) or "—",
                        _texto(_primeiro(registo, "entidade", "nome")) or "—",
                        _texto(registo.get("escalao")) or "—",
                        _fmt_money(registo.get("valor_min")) if registo.get("valor_min") else "—",
                    ]
                    for registo in registos_divida[:15]
                ],
            }
        )

    # --- Atos societários e publicações oficiais --------------------------
    publicacoes = dados.get("societario") or []
    if publicacoes:
        ordenadas = sorted(publicacoes, key=lambda p: str(p.get("data_publicacao") or ""), reverse=True)
        blocos.append(
            {
                "title": "Atos societários e publicações oficiais",
                "columns": ["Data", "Tipo de ato", "Entidade / firma"],
                "rows": [
                    [
                        _iso(p.get("data_publicacao")) or "—",
                        _texto(_primeiro(p, "tipo_label", "acto")) or "—",
                        _texto(_primeiro(p, "firma", "entidade")) or "—",
                    ]
                    for p in ordenadas[:20]
                ],
            }
        )

    # --- Contratos públicos ganhos / celebrados ---------------------------
    contratos_recentes = dados.get("contratos") or []
    if contratos_recentes:
        linhas = []
        for contrato in contratos_recentes[:15]:
            adj = _nomes(contrato.get("adjudicantes"))
            linhas.append(
                [
                    _iso(_primeiro(contrato, "dataCelebracaoContrato", "dataPublicacao", "Ano")) or "—",
                    (adj[0] if adj else "—"),
                    (_texto(contrato.get("objectoContrato")) or "—")[:120],
                    _fmt_money(_primeiro(contrato, "precoContratual", "PrecoTotalEfetivo")),
                ]
            )
        blocos.append(
            {
                "title": "Contratos públicos (últimos)",
                "columns": ["Data", "Entidade adjudicante", "Objeto", "Valor"],
                "rows": linhas,
            }
        )

    # --- CPV mais contratados --------------------------------------------
    by_cpv = dados.get("by_cpv") or []
    if by_cpv:
        total_valor = dados.get("contracts_value")
        linhas = []
        for linha in sorted(by_cpv, key=lambda r: r.get("total_value") or 0, reverse=True)[:12]:
            valor = linha.get("total_value")
            parte = ""
            if isinstance(valor, (int, float)) and isinstance(total_valor, (int, float)) and total_valor:
                parte = f" ({valor / total_valor * 100:.1f}%)"
            linhas.append(
                [
                    _texto(linha.get("key")) or "—",
                    _texto(linha.get("description")) or "—",
                    _fmt_money(valor) + parte,
                    str(linha.get("count") if linha.get("count") is not None else ""),
                ]
            )
        blocos.append({"title": "CPV mais contratados", "columns": ["Código", "Descrição", "Valor", "Nº"], "rows": linhas})

    return blocos


def build_entity_processos_pdf(nif: str) -> Optional[str]:
    """Gera o «Relatório de processos e dados da empresa» de uma entidade.

    Modelo inspirado nos relatórios de risco de crédito: resumo e indicadores na
    primeira página, insolvências/PER, processos judiciais, situação fiscal,
    atos societários e contratos nas seguintes, e as notas legais no fim.
    """
    try:
        dados = _processos_dados(nif)
    except Exception as exc:  # noqa: BLE001 - o relatório nunca pode rebentar a rota
        logger.exception("Relatório de processos de %s falhou a recolher dados", nif)
        return None

    blocos = _processos_blocks(dados)
    return _generate_pdf_report(
        str(dados.get("nif") or nif),
        str(dados.get("name") or nif),
        {},
        titulo="Relatório de processos e dados da empresa",
        notas=NOTAS_LEGAIS_PROCESSOS,
        prefixo="processos",
        blocos=blocos,
    )


#: Nível de risco atribuído ao dossiê, a partir dos sinais públicos.
_RISCO_GRAUS = ("baixo", "moderado", "elevado")


def _risco_da_empresa(dados: Dict[str, Any]) -> Dict[str, Any]:
    """Lê os sinais públicos e devolve o grau de risco e o porquê.

    Os sinais vêm do que o IQ OS já recolhe: **CIRE** (insolvências e
    revitalizações), citações/notificações por editais, listas públicas de
    devedores das Finanças e da Segurança Social, e a presença nos contratos.
    O grau é uma leitura simples e explicável — não substitui a análise de
    crédito, mas diz o que pesou.
    """
    sinais: List[str] = []
    pontos = 0

    cire = dados.get("cire") or {}
    insolvencias = int(cire.get("insolvencias") or cire.get("total_insolvencias") or 0)
    per = int(cire.get("per") or cire.get("revitalizacoes") or cire.get("total_per") or 0)
    total_cire = int(cire.get("total") or 0)
    if insolvencias or (total_cire and not insolvencias and not per):
        pontos += 3
        sinais.append(f"processo de insolvência publicado no CIRE ({insolvencias or total_cire})")
    if per:
        pontos += 2
        sinais.append(f"processo especial de revitalização ({per})")

    citacoes = dados.get("citacoes") or {}
    total_citacoes = int(citacoes.get("total") or 0)
    if total_citacoes:
        pontos += 1 if total_citacoes < 5 else 2
        sinais.append(f"{total_citacoes} citação(ões)/notificação(ões) por editais")

    devedores = dados.get("devedores") or {}
    listas = devedores.get("listas") if isinstance(devedores, dict) else None
    if devedores and (listas or devedores.get("total")):
        pontos += 3
        nomes = []
        if isinstance(listas, list):
            nomes = [str(item.get("lista") or item) for item in listas][:3]
        sinais.append(
            "consta em listas públicas de devedores"
            + (f" ({', '.join(nomes)})" if nomes else "")
        )

    fiscal = dados.get("fiscal")
    if isinstance(fiscal, dict) and fiscal.get("situacao") and "regular" not in str(fiscal.get("situacao")).lower():
        pontos += 1
        sinais.append(f"situação fiscal: {fiscal.get('situacao')}")

    if not dados.get("contracts_total"):
        pontos += 1
        sinais.append("sem contratos públicos indexados")

    if pontos >= 5:
        grau = "elevado"
    elif pontos >= 2:
        grau = "moderado"
    else:
        grau = "baixo"
    return {
        "grau": grau,
        "pontos": pontos,
        "sinais": sinais or ["sem sinais públicos relevantes nas fontes consultadas"],
    }


def _dossie_marca_blocks(nif: str, nome: str) -> List[Dict[str, Any]]:
    """Bloco com o site oficial e o logótipo identificados para a empresa."""
    try:
        from api import empresas_perfil

        perfil = empresas_perfil.obter(nif, nome) or {}
    except Exception as exc:  # noqa: BLE001
        logger.info("Dossiê de %s: sem perfil (%s)", nif, exc)
        return []
    if not perfil:
        return []
    linhas = [
        ["Site oficial", perfil.get("site") or "não identificado"],
        ["Domínio", perfil.get("dominio") or "—"],
        ["Confiança", f"{round(float(perfil.get('confianca') or 0) * 100)}%"],
        ["Origem", perfil.get("origem") or "—"],
        ["Logótipo", "obtido" if perfil.get("logo_url") else "não encontrado"],
        ["Atualizado", str(perfil.get("atualizado") or "—")[:19].replace("T", " ")],
    ]
    if perfil.get("motivo"):
        linhas.append(["Como foi escolhido", str(perfil.get("motivo"))[:160]])
    return [{"title": "Identidade digital (site e logótipo)", "columns": ["Item", "Valor"], "rows": linhas}]


def _dossie_risco_blocks(dados: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Bloco de risco: grau, sinais que o sustentam e o que o faria mudar."""
    risco = _risco_da_empresa(dados)
    linhas = [
        ["Grau de risco", str(risco["grau"]).upper()],
        ["Sinais encontrados", str(len(risco["sinais"]))],
    ]
    blocos: List[Dict[str, Any]] = [
        {"title": "Leitura de risco", "columns": ["Indicador", "Valor"], "rows": linhas},
        {"title": "Sinais considerados", "columns": ["Sinal"], "rows": [[s] for s in risco["sinais"]]},
    ]
    return blocos


def build_entity_dossie_pdf(nif: str) -> Optional[str]:
    """**Dossiê da empresa**: tudo o que o IQ OS sabe, num só PDF.

    Junta, por esta ordem: identificação e marca (site/logótipo), ficha do
    enriquecimento por IA (descrição, contactos, morada, dimensão, atividade e
    certificações), **leitura de risco** (com o CIRE, citações, devedores e
    situação fiscal), processos e insolvências em detalhe, atos societários,
    contratos e CPV, relações e fontes.

    É o relatório «tudo sobre a empresa» da ficha — distingue-se do relatório de
    processos (que é focado no risco) por trazer também a identidade e a
    atividade recolhidas por web + IA.
    """
    from api.elasticsearch_client import ENTITIES_INDEX, ensure_indices

    try:
        dados = _processos_dados(nif)
    except Exception:  # noqa: BLE001
        logger.exception("Dossiê de %s falhou a recolher os processos", nif)
        dados = {"nif": nif, "erros": ["processos"]}

    nome = str(dados.get("name") or nif)

    # Enriquecimento web/IA guardado na ficha da entidade.
    payload: Dict[str, Any] = {}
    client = get_es_client(request_timeout=30)
    if client is not None:
        try:
            ensure_indices(client)
            doc = client.get(index=ENTITIES_INDEX, id=f"{ENTITIES_INDEX}:{nif}")["_source"]
            payload = dict(doc.get("enrichment_web") or {})
            nome = str(doc.get("name") or payload.get("entity_name") or nome)
        except Exception as exc:  # noqa: BLE001 - o dossiê sai sem o enriquecimento
            logger.info("Dossiê de %s: sem enriquecimento guardado (%s)", nif, exc)

    try:
        from api.elasticsearch_client import get_entity_relations

        relacoes = get_entity_relations(nif)
        if relacoes.get("items"):
            payload["relations"] = relacoes["items"]
    except Exception as exc:  # noqa: BLE001
        logger.info("Dossiê de %s: sem relações (%s)", nif, exc)

    blocos: List[Dict[str, Any]] = []
    blocos += _dossie_marca_blocks(nif, nome)
    blocos += _entity_report_blocks(payload) if payload else []
    blocos += _dossie_risco_blocks(dados)
    blocos += _processos_blocks(dados)

    notas = list(NOTAS_LEGAIS_PROCESSOS)
    notas.insert(
        0,
        "<b>Dossiê da empresa.</b> Reúne a ficha recolhida por pesquisa web e IA, a identidade "
        "digital (site e logótipo) e a leitura de risco a partir de fontes públicas. Os campos "
        "marcados como «não identificado» não foram encontrados nas fontes consultadas — não "
        "significam que a informação não exista.",
    )
    return _generate_pdf_report(
        str(dados.get("nif") or nif),
        nome,
        payload,
        titulo=f"Dossiê da empresa — {nome}",
        notas=notas,
        prefixo="dossie",
        blocos=blocos,
    )


async def enrich_entity(nif: str, payload: Optional[Dict[str, Any]] = None, session: Any = None) -> Dict[str, Any]:
    """Enriquece uma entidade com web, scraping e IA, guardando resultado no Elasticsearch.

    `session` (opcional) identifica o utilizador para resolver o fornecedor de IA
    configurado; sem ela a extração estruturada cai no caminho sem LLM.
    """
    data = dict(payload or {})
    entity_name = str(data.get("entity_name") or "").strip()
    query = str(data.get("query") or "").strip()
    max_results = max(1, min(12, int(data.get("max_results") or 6)))
    max_pages = max(1, min(8, int(data.get("max_pages") or 3)))
    use_web = bool(data.get("use_web", True))
    use_scraper = bool(data.get("use_scraper", True))
    save_relations = bool(data.get("save_relations", True))
    generate_pdf = bool(data.get("generate_pdf", False))

    # Neste ponto a ficha da entidade existe no cadastro. Se o código do chamador só tiver o NIF,
    # tentamos recuperar o nome no Elasticsearch para produzir uma pesquisa útil.
    base_name = entity_name or ""
    if not base_name:
        from api.elasticsearch_client import get_entity_by_nif

        entity = get_entity_by_nif(nif)
        base_name = str((entity or {}).get("name") or "")

    search_query = _entity_query(nif, base_name, query)
    summary: Dict[str, Any] = {"query": search_query, "source_count": 0, "links": []}
    search_results: List[Dict[str, Any]] = []

    if use_web:
        try:
            web_results = web_search(search_query, max_results=max_results)
            search_results = _extract_top_sources(web_results, limit=max_results)
            summary["links"] = search_results
            summary["source_count"] = len(search_results)
        except Exception as exc:
            logger.warning("Falha ao pesquisar web para %s: %s", nif, exc)

    page_texts: List[str] = []
    if use_scraper and search_results:
        for item in search_results[:max_pages]:
            url = str(item.get("url") or "").strip()
            if not url:
                continue
            try:
                page_texts.append(_fetch_page_text(url))
            except Exception as exc:
                logger.warning("Falha ao raspar %s: %s", url, exc)

    facts = await _ask_structured_fields(base_name or nif, search_results, nif, session=session, page_texts=page_texts)
    facts.setdefault("entity_name", base_name or nif)
    facts.setdefault("nif", nif)
    facts.setdefault("country", "Portugal")
    facts.setdefault("status", "unknown")
    facts.setdefault("description", "")
    facts.setdefault("cae", None)
    facts.setdefault("cae_description", None)
    facts.setdefault("contacts", [])
    facts.setdefault("addresses", [])
    facts.setdefault("brands", [])
    facts.setdefault("parent_company", None)
    facts.setdefault("related_entities", [])
    facts.setdefault("notes", [])
    # Campos novos: quando o modelo os traz, completam-se uns aos outros (a lista
    # simples de contactos passa a incluir emails e telefones).
    emails = [str(x).strip() for x in (facts.get("emails") or []) if str(x).strip()]
    phones = [str(x).strip() for x in (facts.get("phones") or []) if str(x).strip()]
    contactos = [str(x).strip() for x in (facts.get("contacts") or []) if str(x).strip()]
    for extra in [*emails, *phones]:
        if extra not in contactos:
            contactos.append(extra)
    facts["contacts"] = contactos
    for campo, vazio in (
        ("emails", []),
        ("phones", []),
        ("cae_secondary", []),
        ("activities", []),
        ("products_services", []),
        ("certifications", []),
        ("public_flags", []),
        ("legal_form", None),
        ("founded_year", None),
        ("share_capital", None),
        ("employees_band", None),
        ("revenue_band", None),
        ("size_class", None),
        ("address", None),
        ("socials", {}),
        ("website", None),
    ):
        facts.setdefault(campo, vazio)
    if not str(facts.get("website") or "").strip():
        facts["website"] = None

    combined = {
        "entity_name": facts.get("entity_name") or base_name or nif,
        "nif": nif,
        "country": facts.get("country") or "Portugal",
        "status": facts.get("status") or "unknown",
        "legal_name": facts.get("legal_name"),
        "legal_form": facts.get("legal_form"),
        "founded_year": facts.get("founded_year"),
        "description": facts.get("description") or "",
        "cae": facts.get("cae") or None,
        "cae_description": facts.get("cae_description") or None,
        "cae_secondary": facts.get("cae_secondary") or [],
        "share_capital": facts.get("share_capital"),
        "employees_band": facts.get("employees_band"),
        "revenue_band": facts.get("revenue_band"),
        "size_class": facts.get("size_class"),
        "activities": facts.get("activities") or [],
        "products_services": facts.get("products_services") or [],
        "certifications": facts.get("certifications") or [],
        "contacts": facts.get("contacts") or [],
        "emails": facts.get("emails") or [],
        "phones": facts.get("phones") or [],
        "website": facts.get("website"),
        "socials": facts.get("socials") or {},
        "addresses": facts.get("addresses") or [],
        "address": facts.get("address"),
        "brands": facts.get("brands") or [],
        "parent_company": facts.get("parent_company"),
        "related_entities": facts.get("related_entities") or [],
        "public_flags": facts.get("public_flags") or [],
        "notes": facts.get("notes") or [],
        "sources": search_results,
        "page_text_chars": sum(len(text) for text in page_texts),
        "pages_scraped": len(page_texts),
        "enriched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if page_texts:
        combined["page_text_preview"] = " ".join(page_texts[:3])[:2000]

    summary.update({
        "country": combined.get("country"),
        "status": combined.get("status"),
        "cae": combined.get("cae"),
        "cae_description": combined.get("cae_description"),
        "parent_company": combined.get("parent_company"),
        "contact_count": len(combined.get("contacts") or []),
        "address_count": len(combined.get("addresses") or []),
        "brand_count": len(combined.get("brands") or []),
        "email_count": len(combined.get("emails") or []),
        "phone_count": len(combined.get("phones") or []),
        "activity_count": len(combined.get("activities") or []),
        "certification_count": len(combined.get("certifications") or []),
        "related_count": len(combined.get("related_entities") or []),
    })
    combined["summary"] = summary

    # Marca da empresa: site oficial e logótipo (`api.empresas_perfil`). Corre
    # **antes** de gravar, para o documento de enriquecimento levar também o
    # site, o domínio e o endereço do logótipo. O perfil fica no índice
    # `empresas_perfil` do Elasticsearch (mais a cache local) e é o que a ficha
    # da empresa mostra sem ir à rede.
    perfil: Optional[Dict[str, Any]] = None
    try:
        from api import empresas_perfil

        pais = "pt"
        origem_pais = str(combined.get("country") or "").lower()
        if origem_pais.startswith("es") or "espanha" in origem_pais:
            pais = "es"
        elif origem_pais.startswith("fr") or "fran" in origem_pais:
            pais = "fr"
        perfil = empresas_perfil.resolver(
            base_name or nif,
            nif,
            pais,
            usar_ia=True,
            forcar=True,
            user_id=getattr(getattr(session, "user", None), "id", None),
        )
        if perfil:
            combined["site"] = perfil.get("site")
            combined["dominio"] = perfil.get("dominio")
            combined["logo_url"] = perfil.get("logo_url")
            if perfil.get("site"):
                summary["site"] = perfil.get("site")
    except Exception as exc:  # noqa: BLE001 - a marca é um extra, nunca falha a ficha
        logger.warning("Falha ao obter o site/logótipo de %s: %s", nif, exc)

    saved = _save_entity_doc(nif, base_name or nif, combined, summary)

    relations: List[Dict[str, Any]] = []
    if save_relations:
        for rel in facts.get("related_entities") or []:
            target_name = str(rel.get("name") or "").strip()
            target_ref = str(rel.get("nif") or rel.get("ref") or target_name).strip()
            if not target_ref:
                continue
            relations.append({
                "kind": _canonical_kind(rel.get("kind") or "related"),
                "source_ref": nif,
                "source_name": base_name or nif,
                "source_type": "empresa",
                "target_ref": target_ref,
                "target_name": target_name,
                "target_type": "entidade",
                "evidence": str(rel.get("evidence") or ""),
                "country": combined.get("country") or "Portugal",
            })
        if combined.get("parent_company"):
            relations.append({
                "kind": "parent_company",
                "source_ref": nif,
                "source_name": base_name or nif,
                "source_type": "empresa",
                "target_ref": str(combined["parent_company"]).strip(),
                "target_name": str(combined["parent_company"]).strip(),
                "target_type": "empresa",
                "evidence": "Parent company mentioned in online sources",
                "country": combined.get("country") or "Portugal",
            })

    relation_count = _save_relations(nif, base_name or nif, relations) if save_relations else 0

    report = None
    if generate_pdf:
        pdf_path = _generate_pdf_report(nif, base_name or nif, combined)
        if pdf_path:
            report = {
                "generated": True,
                "path": pdf_path,
                "title": f"Relatório da entidade {base_name or nif}",
                "size_bytes": Path(pdf_path).stat().st_size if Path(pdf_path).exists() else None,
            }

    fields_added: Dict[str, Any] = {
        "country": combined.get("country"),
        "status": combined.get("status"),
        "description": combined.get("description"),
        "cae": combined.get("cae"),
        "cae_description": combined.get("cae_description"),
        "contacts_count": len(combined.get("contacts") or []),
        "addresses_count": len(combined.get("addresses") or []),
        "brands_count": len(combined.get("brands") or []),
        "parent_company": combined.get("parent_company"),
        "related_entities_count": len(combined.get("related_entities") or []),
        "sources_count": len(search_results),
        "pages_scraped": len(page_texts),
        "site": (perfil or {}).get("site"),
        "logo": bool((perfil or {}).get("logo_url")),
    }
    return {
        "nif": nif,
        "name": base_name or nif,
        "query": search_query,
        "status": "ok",
        "saved": saved,
        "enriched_at": combined.get("enriched_at"),
        "fields_added": fields_added,
        "source_count": len(search_results),
        "relation_count": relation_count,
        "summary": summary,
        "report": report,
        "message": f"Entidade {nif} enriquecida — {len(search_results)} fontes, {relation_count} relações."
                    + (" Relatório PDF gerado." if report else ""),
        "error": None,
    }
