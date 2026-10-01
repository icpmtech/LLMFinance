"""Peça do procedimento e leitura de valores do contrato.

O índice de contratos (`contratos`) guarda, quando existe, o endereço das
«peças do procedimento» (`linkPecasProc`) — normalmente um **ZIP** com o
convite e o caderno de encargos (`.docx` ou `.pdf`).

Este módulo:
- constrói as ligações oficiais (BASE.gov.pt, plataformas de contratação);
- descarrega e lê as peças (ZIP → DOCX/PDF → texto), com cache em memória;
- extrai factos verificáveis do texto (preço base, critério, caução, prazos,
  base legal, propriedade intelectual) para a ficha e para o relatório.

Não há dependências novas: o DOCX é lido com `zipfile` + `xml.etree` e o PDF
com `pymupdf` (já usado no projeto).
"""
from __future__ import annotations

import io
import logging
import re
import time
import zipfile
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

#: Anfitriões de onde é aceitável descarregar peças (evita SSRF a partir do índice).
ALLOWED_HOSTS = {
    "www.acingov.pt",
    "acingov.pt",
    "www.anogov.com",
    "anogov.com",
    "www.base.gov.pt",
    "base.gov.pt",
}

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

_MAX_PIECE_BYTES = 25 * 1024 * 1024  # 25 MB
_MAX_TEXT_CHARS = 40000  # por documento, para não inchar a UI/prompt
_CACHE_TTL = 3600.0
_cache: Dict[str, Tuple[float, dict]] = {}


# --------------------------------------------------------------------- ligações
def official_links(contract: Dict[str, Any]) -> List[Dict[str, str]]:
    """Ligações oficiais do contrato (BASE.gov.pt e plataforma de contratação)."""
    links: List[Dict[str, str]] = []
    idcontrato = str(contract.get("idcontrato") or "").strip()
    idprocedimento = str(contract.get("idprocedimento") or "").strip()

    if idcontrato:
        links.append(
            {
                "label": "Ficha do contrato no BASE.gov.pt",
                "url": f"https://www.base.gov.pt/Base4/pt/detalhe/?type=contratos&id={idcontrato}",
                "kind": "portal",
            }
        )
    if idprocedimento:
        links.append(
            {
                "label": "Procedimento no BASE.gov.pt",
                "url": f"https://www.base.gov.pt/Base4/pt/detalhe/?type=procedimentos&id={idprocedimento}",
                "kind": "portal",
            }
        )

    piece_url = str(contract.get("linkPecasProc") or "").strip()
    if piece_url:
        host = (urlparse(piece_url).hostname or "").lower()
        links.append(
            {
                "label": "Peças do procedimento (convite / caderno de encargos)",
                "url": piece_url,
                "kind": "pecas",
                "host": host,
            }
        )
    return links


def _piece_url(contract: Dict[str, Any]) -> Optional[str]:
    url = str(contract.get("linkPecasProc") or "").strip()
    if not url:
        return None
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return None
    if (parsed.hostname or "").lower() not in ALLOWED_HOSTS:
        logger.warning("Peça ignorada: anfitrião não autorizado (%s)", parsed.hostname)
        return None
    return url


# ----------------------------------------------------------------- leitura ficheiros
def _docx_text(blob: bytes) -> str:
    """Texto de um `.docx` (sem dependências externas)."""
    import xml.etree.ElementTree as ET

    with zipfile.ZipFile(io.BytesIO(blob)) as inner:
        xml = inner.read("word/document.xml")
    root = ET.fromstring(xml)
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    lines: List[str] = []
    for para in root.iter(f"{ns}p"):
        chunks = [t.text or "" for t in para.iter(f"{ns}t")]
        if chunks:
            lines.append("".join(chunks))
    return "\n".join(lines)


def _pdf_text(blob: bytes) -> str:
    """Texto de um PDF (pymupdf)."""
    import fitz  # pymupdf

    doc = fitz.open(stream=blob, filetype="pdf")
    try:
        return "\n".join(page.get_text() for page in doc)
    finally:
        doc.close()


def _read_archive(blob: bytes) -> List[Dict[str, str]]:
    """Extrai o texto dos documentos de um arquivo (ZIP) ou de um ficheiro só.

    O mesmo documento costuma aparecer em pastas diferentes do ZIP — é
    deduplicado pelo texto.
    """
    documents: List[Dict[str, str]] = []
    seen_texts: set[str] = set()

    def push(name: str, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        key = str(hash(text[:2000]))
        if key in seen_texts:
            return
        seen_texts.add(key)
        documents.append(
            {
                "name": name.rsplit("/", 1)[-1],
                "kind": (name.rsplit(".", 1)[-1] or "").lower(),
                "text": text[:_MAX_TEXT_CHARS],
            }
        )

    if blob[:2] != b"PK":
        # Ficheiro único (PDF, DOCX ou texto)
        push("documento", _read_single(blob, "documento"))
        return documents

    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        for info in zf.infolist():
            if info.is_dir() or info.file_size == 0:
                continue
            try:
                payload = zf.read(info.filename)
            except Exception as exc:  # pragma: no cover - zip corrompido
                logger.debug("Peça: entrada ilegível %s (%s)", info.filename, exc)
                continue
            push(info.filename, _read_single(payload, info.filename))
    return documents


def _read_single(payload: bytes, name: str) -> str:
    lower = name.lower()
    try:
        if payload[:2] == b"PK" and lower.endswith(".docx"):
            return _docx_text(payload)
        if payload[:4] == b"%PDF" or lower.endswith(".pdf"):
            return _pdf_text(payload)
    except Exception as exc:
        logger.debug("Peça: não foi possível ler %s (%s)", name, exc)
    return ""


def _download(url: str, timeout: float) -> bytes:
    response = requests.get(
        url,
        headers={"User-Agent": UA, "Accept": "*/*", "Accept-Language": "pt-PT,pt;q=0.9"},
        timeout=timeout,
        stream=True,
    )
    response.raise_for_status()
    chunks: List[bytes] = []
    size = 0
    for chunk in response.iter_content(65536):
        size += len(chunk)
        if size > _MAX_PIECE_BYTES:
            raise ValueError("Peça demasiado grande")
        chunks.append(chunk)
    return b"".join(chunks)


# ------------------------------------------------------------------ valores
_DASH = "\u2013\u2014-"

#: (etiqueta, padrão, grupo) — extrações deterministas do texto da peça.
PATTERNS: List[Tuple[str, str]] = [
    ("Nº do procedimento", r"(?:Ajuste\s+direto|Concurso\s+p[úu]blico)\s*n[.ºo]*\s*([\w./\u2013-]+)"),
    ("Preço base", rf"Pre[çc]o\s+Base\s*[\n\r\s]*([\d][\d\s.,\u00a0]*\s*(?:€|euros))"),
    ("IVA", r"(acresc(?:ido|erá)[^.\n]{0,80}IVA[^.\n]{0,60})"),
    ("Critério de adjudicação", r"(proposta\s+economicamente\s+mais\s+vantajosa[^.\n]{0,120})"),
    ("Modalidade do critério", r"modalidade\s+(monofator|multifator|multicrit[ée]rio)"),
    ("Base legal", r"(al[íi]nea\s+[a-z]\)\s*do\s+n[.ºo]*\s*1\s*do\s+artigo\s*24[.ºo]*[^.\n]{0,80})"),
    ("Caução", r"Cau[çc][ãa]o[^\n]{0,40}\n[^\n]{0,120}"),
    ("Prazo de apresentação de propostas", r"at[ée]\s+[àa]s\s*([\dhH:]{4,}\s+do\s+[^.\n]{0,70})"),
    ("Validade da proposta", r"proposta\s+durante\s+um\s+per[íi]odo\s+de\s+(\d+\s+dias)"),
    ("Prazo de habilitação", r"no\s+prazo\s+de\s+(\d+\s+dias)\s+a\s+contar\s+da\s+notifica[çc][ãa]o"),
    ("Plataforma eletrónica", r"(https?://(?:www\.)?(?:acingov|anogov)\.\w+[^\s,;)]*)"),
    ("Marca registada (INPI)", r"marca\s*n[.ºo]*\s*(\d+)"),
    ("Patentes nacionais", r"Patentes?\s+Nacionais?\s+N[.ºo]*\s*([^.\n]{5,200})"),
    ("Sede da adjudicatária", r"sede\s+na\s+([^\n,]{5,120}),\s*com\s+n[úu]mero\s+de\s+identifica[çc][ãa]o"),
    ("Contactos da adjudicante", r"((?:\+351|\(\+351\))\s*[\d\s]{9,12})[^\n]{0,120}"),
    ("Manutenção preventiva", r"([^\n]{0,60}manuten[çc][ãa]o\s+preventiva[^\n]{0,160})"),
]


def _clean(value: str) -> str:
    text = re.sub(r"\s+", " ", value or "").strip(" .;:-\u2013\u2014")
    return text[:300]


def extract_values(text: str) -> List[Dict[str, str]]:
    """Factos verificáveis encontrados no texto da peça (com o excerto original)."""
    if not text:
        return []
    found: List[Dict[str, str]] = []
    seen: set[str] = set()
    for label, pattern in PATTERNS:
        if label in seen:
            continue
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            continue
        # Usa o grupo 1 quando existe; caso contrário o texto todo do match.
        raw = match.group(1) if match.groups() else match.group(0)
        value = _clean(raw)
        if not value or len(value) < 2:
            continue
        seen.add(label)
        found.append({"label": label, "value": value, "source": "peça do procedimento"})
    return found


# --------------------------------------------------------------------- entrada
def _contract_values(contract: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Valores lidos do índice (o que o portal publicou sobre este contrato)."""
    def money(value: Any) -> Optional[str]:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return f"{number:,.2f} €".replace(",", " ").replace(".", ",")

    rows: List[Dict[str, Any]] = []

    def add(label: str, value: Any, *, money_value: bool = False) -> None:
        if value in (None, "", 0, 0.0, []):
            return
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        shown = money(value) if money_value else value
        if shown is None:
            return
        rows.append({"label": label, "value": shown, "source": "índice BASE"})

    add("Preço contratual", contract.get("precoContratual"), money_value=True)
    add("Preço base do procedimento", contract.get("precoBaseProcedimento"), money_value=True)
    add("Preço total efetivo", contract.get("PrecoTotalEfetivo"), money_value=True)
    add("Tipo de contrato", _first(contract.get("tipoContrato")))
    add("Procedimento", contract.get("tipoprocedimento"))
    add("Critério de adjudicação", contract.get("TipoCriterioAdjudicacao"))
    add("Regime", contract.get("regime"))
    add("Fundamentação", contract.get("fundamentacao"))
    add("Fundamento do ajuste direto", contract.get("fundamentAjusteDireto"))
    add("Prazo de execução (dias)", contract.get("prazoExecucao"))
    add("Data de publicação", contract.get("dataPublicacao"))
    add("Data de celebração", contract.get("dataCelebracaoContrato"))
    add("Data da decisão de adjudicação", contract.get("dataDecisaoAdjudicacao"))
    add("Data de fecho", contract.get("dataFechoContrato"))
    add("Concorrentes", contract.get("concorrentes"))
    add("PME (NIF)", contract.get("adjudicatarioPMEs"))
    add("Procedimento centralizado", contract.get("ProcedimentoCentralizado"))
    add("Contratação ecológica", contract.get("ContratEcologico"))
    add("Critérios materiais", contract.get("CritMateriais"))
    add("Lotes", contract.get("Lotes"))
    add("NUTs", _first(contract.get("NUTs")))
    add("Observações", contract.get("Observacoes"))
    return rows


def _first(value: Any) -> Any:
    if isinstance(value, list):
        return value[0] if value else None
    return value


def contract_document(idcontrato: str, contract: Optional[Dict[str, Any]] = None, *, fetch: bool = True) -> Dict[str, Any]:
    """Ligações oficiais, peça do procedimento (lida) e valores do contrato."""
    from api.elasticsearch_client import get_contract_by_id

    if contract is None:
        contract = get_contract_by_id(idcontrato)
    if contract.get("error"):
        return {"error": contract["error"], "status_code": contract.get("status_code", 502)}

    result: Dict[str, Any] = {
        "contract_id": str(contract.get("idcontrato") or idcontrato),
        "links": official_links(contract),
        "values": _contract_values(contract),
        "pieces": [],
        "highlights": [],
        "error": None,
    }

    url = _piece_url(contract)
    if not url:
        result["note"] = (
            "Este contrato não tem peças publicadas no índice."
            if not contract.get("linkPecasProc")
            else "A ligação das peças aponta para um domínio não reconhecido."
        )
        return result
    if not fetch:
        result["note"] = "Peça disponível mas não lida (modo rápido)."
        return result

    cached = _cache.get(url)
    if cached and (time.time() - cached[0]) < _CACHE_TTL:
        result.update(cached[1])
        return result

    try:
        blob = _download(url, timeout=25)
        documents = _read_archive(blob)
    except Exception as exc:
        logger.info("Peça do contrato %s não lida: %s", idcontrato, exc)
        result["error"] = f"Não foi possível ler a peça: {exc}"
        return result

    highlights: List[Dict[str, str]] = []
    seen_facts: set[str] = set()
    for document in documents:
        for item in extract_values(document["text"]):
            key = f"{item['label']}|{item['value']}"
            if key in seen_facts:
                continue
            seen_facts.add(key)
            item["document"] = document["name"]
            highlights.append(item)

    payload = {"pieces": documents, "highlights": highlights}
    _cache[url] = (time.time(), payload)
    result.update(payload)
    return result
