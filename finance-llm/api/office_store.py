"""Office IQ OS — documentos em Markdown (notas, dossiês, relatórios, páginas).

É o sítio onde o trabalho fica escrito: o **dossiê 360** guardado transforma-se
aqui num documento editável, e qualquer nota/relatório escrito na plataforma vive
no mesmo catálogo, com pastas, etiquetas, pesquisa e exportação.

Os documentos são guardados em Markdown (`data/office/office.json`), com escrita
atómica: o ficheiro é a fonte de verdade e pode ser versionado. Cada documento
tem `kind` (`nota`, `dossier`, `relatorio`, `ata`, `pagina`), pasta opcional,
etiquetas, ligação à origem (por exemplo o dossiê que o gerou), autor e contagem
de palavras.
"""
from __future__ import annotations

import copy
import html
import json
import logging
import re
import threading
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
OFFICE_DIR = ROOT / "data" / "office"
OFFICE_PATH = OFFICE_DIR / "office.json"
OFFICE_VERSION = 1

KINDS = ["nota", "dossier", "relatorio", "ata", "pagina"]
KIND_LABELS = {
    "nota": "Nota",
    "dossier": "Dossiê",
    "relatorio": "Relatório",
    "ata": "Ata",
    "pagina": "Página",
}

_lock = threading.Lock()
_cache: Optional[Dict[str, Any]] = None

# Esqueletos para começar um documento novo (o utilizador pode apagar tudo).
TEMPLATES: Dict[str, str] = {
    "nota": "# {title}\n\n",
    "relatorio": (
        "# {title}\n\n"
        "**Data:** {date}  \n**Autor:** {author}\n\n"
        "## Sumário executivo\n\n_(duas a três frases com a conclusão principal)_\n\n"
        "## Contexto\n\n## Análise\n\n## Dados\n\n| Indicador | Valor | Fonte |\n| --- | --- | --- |\n|  |  |  |\n\n"
        "## Riscos e limitações\n\n## Próximos passos\n\n"
    ),
    "ata": (
        "# {title}\n\n"
        "**Data:** {date}  \n**Participantes:** \n\n"
        "## Ordem de trabalhos\n\n1. \n\n## Decisões\n\n- \n\n## Ações\n\n| Ação | Responsável | Prazo |\n| --- | --- | --- |\n|  |  |  |\n"
    ),
    "pagina": "# {title}\n\n",
    "dossier": "# {title}\n\n_(documento gerado a partir de um dossiê 360)_\n\n",
}


# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug(value: str, fallback: str = "documento") -> str:
    text = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_").lower()
    return re.sub(r"_+", "_", text)[:64] or fallback


def _word_count(markdown: str) -> int:
    text = re.sub(r"[#*`>_\-\[\]()!]", " ", markdown or "")
    return len([word for word in re.split(r"\s+", text) if word.strip()])


def _excerpt(markdown: str, limit: int = 220) -> str:
    text = re.sub(r"```.*?```", " ", markdown or "", flags=re.S)
    text = re.sub(r"[#*`>_|]", " ", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _empty_store() -> Dict[str, Any]:
    return {"version": OFFICE_VERSION, "documents": [], "folders": [], "updated_at": _now()}


def _read_store() -> Dict[str, Any]:
    if not OFFICE_PATH.exists():
        return _empty_store()
    try:
        raw = json.loads(OFFICE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Ficheiro do Office ilegível (%s); a recomeçar.", exc)
        return _empty_store()
    if not isinstance(raw, dict):
        return _empty_store()
    store = _empty_store()
    for key in ("documents", "folders"):
        value = raw.get(key)
        if isinstance(value, list):
            store[key] = [item for item in value if isinstance(item, dict)]
    return store


def _write_store(store: Dict[str, Any]) -> None:
    global _cache
    store["version"] = OFFICE_VERSION
    store["updated_at"] = _now()
    OFFICE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = OFFICE_PATH.with_suffix(".json.tmp")
    payload = json.dumps(store, ensure_ascii=False, indent=2, default=str)
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(OFFICE_PATH)
    _cache = store


def _store() -> Dict[str, Any]:
    global _cache
    with _lock:
        if _cache is None:
            _cache = _read_store()
        return copy.deepcopy(_cache)


def _summary(document: Dict[str, Any], folders: Dict[str, str]) -> Dict[str, Any]:
    return {
        "id": document.get("id"),
        "title": document.get("title"),
        "kind": document.get("kind") or "nota",
        "kind_label": KIND_LABELS.get(str(document.get("kind") or "nota"), "Nota"),
        "folder_id": document.get("folder_id"),
        "folder": folders.get(str(document.get("folder_id") or "")),
        "tags": document.get("tags") or [],
        "author": document.get("author"),
        "pinned": bool(document.get("pinned")),
        "words": document.get("words") or 0,
        "excerpt": _excerpt(str(document.get("markdown") or "")),
        "source": document.get("source"),
        "created_at": document.get("created_at"),
        "updated_at": document.get("updated_at"),
    }


# --------------------------------------------------------------------------
# Pastas
# --------------------------------------------------------------------------
def list_folders() -> List[Dict[str, Any]]:
    store = _store()
    counts: Dict[str, int] = {}
    for document in store["documents"]:
        key = str(document.get("folder_id") or "")
        if key:
            counts[key] = counts.get(key, 0) + 1
    folders = []
    for folder in store["folders"]:
        folders.append({**folder, "documents": counts.get(str(folder.get("id")), 0)})
    folders.sort(key=lambda item: str(item.get("name") or "").lower())
    return folders


def save_folder(payload: Dict[str, Any]) -> Dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ValueError("A pasta precisa de um nome.")
    with _lock:
        store = _read_store()
        folder_id = str(payload.get("id") or "").strip() or _slug(name, "pasta")
        entry = {
            "id": folder_id,
            "name": name,
            "color": str(payload.get("color") or "148,163,184"),
            "description": payload.get("description"),
            "created_at": _now(),
            "updated_at": _now(),
        }
        for index, folder in enumerate(store["folders"]):
            if folder.get("id") == folder_id:
                entry["created_at"] = folder.get("created_at") or entry["created_at"]
                store["folders"][index] = {**folder, **entry}
                break
        else:
            store["folders"].append(entry)
        _write_store(store)
        return next(item for item in store["folders"] if item["id"] == folder_id)


def delete_folder(folder_id: str) -> Dict[str, Any]:
    with _lock:
        store = _read_store()
        before = len(store["folders"])
        store["folders"] = [folder for folder in store["folders"] if folder.get("id") != folder_id]
        moved = 0
        for document in store["documents"]:
            if document.get("folder_id") == folder_id:
                document["folder_id"] = None
                moved += 1
        _write_store(store)
        return {"removed": len(store["folders"]) != before, "id": folder_id, "documents_kept": moved}


# --------------------------------------------------------------------------
# Documentos
# --------------------------------------------------------------------------
def list_documents(
    *,
    folder_id: Optional[str] = None,
    query: Optional[str] = None,
    kind: Optional[str] = None,
    tag: Optional[str] = None,
    limit: int = 200,
    with_content: bool = False,
) -> Dict[str, Any]:
    store = _store()
    folders = {str(folder.get("id")): str(folder.get("name")) for folder in store["folders"]}
    documents = store["documents"]
    if folder_id:
        documents = [item for item in documents if str(item.get("folder_id") or "") == folder_id]
    if kind:
        documents = [item for item in documents if str(item.get("kind") or "nota") == kind]
    if tag:
        documents = [item for item in documents if tag in (item.get("tags") or [])]
    if query:
        needle = query.strip().lower()
        documents = [
            item
            for item in documents
            if needle in str(item.get("title") or "").lower()
            or needle in str(item.get("markdown") or "").lower()
            or any(needle in str(value).lower() for value in (item.get("tags") or []))
        ]
    documents = sorted(documents, key=lambda item: str(item.get("updated_at") or ""), reverse=True)
    documents.sort(key=lambda item: 0 if item.get("pinned") else 1)
    items = []
    for document in documents[:limit]:
        summary = _summary(document, folders)
        if with_content:
            summary["markdown"] = document.get("markdown")
        items.append(summary)
    return {
        "total": len(documents),
        "items": items,
        "folders": list_folders(),
        "kinds": [{"id": kind_id, "label": KIND_LABELS[kind_id]} for kind_id in KINDS],
        "stats": stats(),
    }


def get_document(document_id: str) -> Dict[str, Any]:
    for document in _store()["documents"]:
        if document.get("id") == document_id:
            return document
    raise KeyError(f"Documento {document_id} não encontrado.")


def _unique_id(document_id: str, taken: set) -> str:
    """Devolve um id livre (acrescenta sufixo numérico quando já existe)."""
    if document_id not in taken:
        return document_id
    index = 2
    while f"{document_id}_{index}" in taken:
        index += 1
    return f"{document_id}_{index}"


def save_document(payload: Dict[str, Any], *, author: Optional[str] = None, force_new: bool = False) -> Dict[str, Any]:
    """Cria ou atualiza um documento (id derivado do título quando é novo).

    Uma alteração parcial (ex.: mudar só o título) **não** toca no Markdown: para
    isso é preciso enviar `markdown` (ou `content`).

    Com ``force_new=True`` é sempre criado um documento novo, mesmo que o título
    (ou o id indicado) já exista — o id recebe um sufixo numérico.
    """
    title = str(payload.get("title") or "").strip()
    kind = str(payload.get("kind") or "nota").strip() or "nota"
    if kind not in KINDS:
        kind = "nota"
    template = str(payload.get("template") or "").strip()
    provided = payload.get("markdown")
    if provided is None and template:
        provided = TEMPLATES.get(template, TEMPLATES["nota"]).format(
            title=title or "Sem título",
            date=datetime.now().strftime("%d/%m/%Y"),
            author=author or "",
        )
    has_markdown = provided is not None or "content" in payload
    markdown = str(provided if provided is not None else (payload.get("content") or ""))
    document_id = str(payload.get("id") or "").strip() or _slug(title or payload.get("name") or "documento", "documento")
    with _lock:
        store = _read_store()
        now = _now()
        if force_new:
            document_id = _unique_id(document_id, {str(item.get("id")) for item in store["documents"]})
        body: Dict[str, Any] = {
            "id": document_id,
            "title": title or "Sem título",
            "kind": kind,
            "updated_at": now,
        }
        if has_markdown:
            body["markdown"] = markdown
            body["words"] = _word_count(markdown)
        for optional in ("folder_id", "tags", "pinned", "private"):
            if optional in payload:
                body[optional] = payload[optional]
        if isinstance(payload.get("tags"), list):
            body["tags"] = [str(tag) for tag in payload["tags"] if str(tag).strip()]
        if "source" in payload:
            body["source"] = payload["source"]
        for index, document in enumerate(store["documents"]):
            if document.get("id") != document_id:
                continue
            merged = {**document, **body}
            # Uma alteração parcial sem título não deve apagar o título existente.
            if not title and document.get("title"):
                merged["title"] = document["title"]
            merged["created_at"] = document.get("created_at") or now
            merged["markdown"] = str(body.get("markdown", document.get("markdown") or ""))
            merged["words"] = _word_count(merged["markdown"])
            merged["pinned"] = bool(body.get("pinned", document.get("pinned")))
            store["documents"][index] = merged
            _write_store(store)
            return copy.deepcopy(merged)
        body["created_at"] = now
        body["author"] = payload.get("author") or author
        body["markdown"] = markdown if has_markdown else ""
        body["words"] = _word_count(body["markdown"])
        body["tags"] = body.get("tags") or []
        body["pinned"] = bool(body.get("pinned"))
        store["documents"].append(body)
        _write_store(store)
        return copy.deepcopy(body)


def delete_document(document_id: str) -> Dict[str, Any]:
    with _lock:
        store = _read_store()
        before = len(store["documents"])
        store["documents"] = [item for item in store["documents"] if item.get("id") != document_id]
        _write_store(store)
        return {"removed": len(store["documents"]) != before, "id": document_id}


def duplicate_document(document_id: str, *, title: Optional[str] = None) -> Dict[str, Any]:
    original = get_document(document_id)
    return save_document(
        {
            "title": title or f"{original.get('title')} (cópia)",
            "kind": original.get("kind") or "nota",
            "markdown": original.get("markdown") or "",
            "folder_id": original.get("folder_id"),
            "tags": original.get("tags") or [],
            "author": original.get("author"),
        },
        author=original.get("author"),
        force_new=True,
    )


# --------------------------------------------------------------------------
# Integração com o dossiê 360
# --------------------------------------------------------------------------
def document_from_dossier(
    dossier: Dict[str, Any],
    markdown: str,
    *,
    author: Optional[str] = None,
    folder_id: Optional[str] = None,
    create_new: bool = False,
) -> Dict[str, Any]:
    """Cria (ou atualiza) o documento de um dossiê guardado da Pesquisa 360."""
    source = {
        "type": "dossier360",
        "id": dossier.get("id"),
        "ontology": dossier.get("ontology_id"),
        "term": dossier.get("term"),
        "generated_at": (dossier.get("snapshot") or {}).get("generated_at"),
    }
    existing = None
    if not create_new:
        for document in _store()["documents"]:
            current = document.get("source") or {}
            if current.get("type") == "dossier360" and current.get("id") == dossier.get("id"):
                existing = document
                break
    return save_document(
        {
            "id": None if create_new else (existing.get("id") if existing else None),
            "title": dossier.get("title") or f"{dossier.get('term')} — dossiê 360",
            "kind": "dossier",
            "markdown": markdown,
            "folder_id": folder_id if folder_id is not None else (existing or {}).get("folder_id"),
            "tags": dossier.get("tags") or [],
            "source": source,
            "author": (existing or {}).get("author") or author,
        },
        author=author,
        force_new=create_new,
    )


# --------------------------------------------------------------------------
# Exportação e estatísticas
# --------------------------------------------------------------------------
def to_html(markdown: str) -> str:
    """Converte Markdown simples em HTML (para exportar ou imprimir)."""
    lines = (markdown or "").splitlines()
    out: List[str] = []
    in_list = False
    in_code = False
    in_table = False

    def close_blocks() -> None:
        nonlocal in_list, in_table
        if in_list:
            out.append("</ul>")
            in_list = False
        if in_table:
            out.append("</tbody></table>")
            in_table = False

    for raw in lines:
        line = raw.rstrip()
        if line.startswith("```"):
            close_blocks()
            out.append("</pre>" if in_code else "<pre>")
            in_code = not in_code
            continue
        if in_code:
            out.append(html.escape(raw))
            continue
        if not line.strip():
            close_blocks()
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading:
            close_blocks()
            level = len(heading.group(1))
            out.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
            continue
        if re.match(r"^\s*[-*+]\s+", line):
            if not in_list:
                close_blocks()
                out.append("<ul>")
                in_list = True
            bullet = re.sub(r"^\s*[-*+]\s+", "", line)
            out.append(f"<li>{_inline(bullet)}</li>")
            continue
        if re.match(r"^\s*\d+[.)]\s+", line):
            if not in_list:
                close_blocks()
                out.append("<ul>")
                in_list = True
            numbered = re.sub(r"^\s*\d+[.)]\s+", "", line)
            out.append(f"<li>{_inline(numbered)}</li>")
            continue
        if line.strip().startswith("|") and line.count("|") >= 2:
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", cell or "") for cell in cells):
                continue
            if not in_table:
                close_blocks()
                out.append("<table><tbody>")
                in_table = True
            out.append("<tr>" + "".join(f"<td>{_inline(cell)}</td>" for cell in cells) + "</tr>")
            continue
        if line.strip() in ("---", "***", "___"):
            close_blocks()
            out.append("<hr />")
            continue
        if line.startswith(">"):
            close_blocks()
            out.append(f"<blockquote>{_inline(line.lstrip('> '))}</blockquote>")
            continue
        close_blocks()
        out.append(f"<p>{_inline(line)}</p>")
    close_blocks()
    if in_code:
        out.append("</pre>")
    return "\n".join(out)


def _inline(text: str) -> str:
    value = html.escape(text)
    value = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", value)
    value = re.sub(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)", r"<em>\1</em>", value)
    value = re.sub(r"`(.+?)`", r"<code>\1</code>", value)
    value = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', value)
    return value


def export_document(document: Dict[str, Any], fmt: str = "md") -> Tuple[str, str, str]:
    """`(conteúdo, media_type, nome do ficheiro)`."""
    title = str(document.get("title") or "documento")
    if fmt == "html":
        body = to_html(str(document.get("markdown") or ""))
        page = (
            "<!doctype html><html lang=\"pt\"><head><meta charset=\"utf-8\" />"
            f"<title>{html.escape(title)}</title>"
            "<style>body{max-width:820px;margin:40px auto;padding:0 20px;font:16px/1.7 system-ui,Segoe UI,sans-serif;color:#0f172a}"
            "h1,h2,h3{line-height:1.25}table{border-collapse:collapse;width:100%}td,th{border:1px solid #cbd5e1;padding:6px 8px}"
            "code,pre{background:#f1f5f9;border-radius:6px;padding:2px 4px}blockquote{border-left:3px solid #94a3b8;margin-left:0;padding-left:12px;color:#475569}"
            "</style></head><body>"
            f"<article>{body}</article></body></html>"
        )
        return page, "text/html; charset=utf-8", f"{_slug(title)}.html"
    header = (
        f"---\ntitle: {title}\nkind: {document.get('kind')}\nauthor: {document.get('author') or ''}\n"
        f"updated_at: {document.get('updated_at') or ''}\ntags: {', '.join(document.get('tags') or [])}\n---\n\n"
    )
    return header + str(document.get("markdown") or ""), "text/markdown; charset=utf-8", f"{_slug(title)}.md"


def stats() -> Dict[str, Any]:
    store = _store()
    documents = store["documents"]
    by_kind: Dict[str, int] = {}
    for document in documents:
        key = str(document.get("kind") or "nota")
        by_kind[key] = by_kind.get(key, 0) + 1
    recent = sorted(documents, key=lambda item: str(item.get("updated_at") or ""), reverse=True)[:5]
    folders = {str(folder.get("id")): str(folder.get("name")) for folder in store["folders"]}
    return {
        "documents": len(documents),
        "folders": len(store["folders"]),
        "words": sum(int(document.get("words") or 0) for document in documents),
        "by_kind": [{"value": key, "label": KIND_LABELS.get(key, key), "count": value} for key, value in sorted(by_kind.items(), key=lambda pair: -pair[1])],
        "recent": [_summary(item, folders) for item in recent],
        "updated_at": store.get("updated_at"),
    }
