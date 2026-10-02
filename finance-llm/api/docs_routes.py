"""Página **Documentos** (`/docs/*`): ficheiros de `data/docs` e o seu markdown.

A pasta `finance-llm/data/docs` guarda os documentos de referência da
plataforma (manuais, classificações, tabelas oficiais). Esta página

- lista os ficheiros da pasta (`GET /docs/documents`);
- serve cada ficheiro (pré-visualização/descarga, `GET /docs/document/{nome}`);
- devolve a **versão markdown** de um documento (`GET /docs/markdown/{nome}`).

Sempre que exista um `.md` irmão do ficheiro (ex.: `CAE-Rev.4.pdf` →
`CAE-Rev.4.md`, gerado por `_gen_docs_markdown.py`), é esse que a página mostra.
Ficheiros de texto (`.txt`, `.csv`, `.json`, `.md`) são convertidos a pedido.

Rotas abertas (leitura), como o resto dos catálogos públicos da plataforma.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = ROOT / "data" / "docs"

router = APIRouter(prefix="/docs", tags=["documentos"])

# Extensões de texto que a página sabe transformar em markdown.
TEXTO = {".md", ".markdown", ".txt", ".csv", ".json", ".log", ".tsv"}
TIPO_POR_SUFIXO = {
    ".pdf": "PDF",
    ".md": "Markdown",
    ".markdown": "Markdown",
    ".txt": "Texto",
    ".csv": "CSV",
    ".tsv": "TSV",
    ".json": "JSON",
    ".xlsx": "Excel",
    ".xls": "Excel",
    ".docx": "Word",
    ".doc": "Word",
    ".png": "Imagem",
    ".jpg": "Imagem",
    ".jpeg": "Imagem",
    ".zip": "Arquivo",
}


def _titulo(nome: str) -> str:
    """Nome legível: `CAE-Rev.4.pdf` → `CAE Rev.4`."""
    base = Path(nome).stem
    base = re.sub(r"[_\-]+", " ", base).strip()
    return base or nome


def _iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def _seguro(nome: str) -> Path:
    """Resolve um nome de ficheiro **dentro** de `data/docs` (sem travessias)."""
    limpo = (nome or "").strip().lstrip("/\\")
    if not limpo or ".." in Path(limpo).parts:
        raise HTTPException(status_code=400, detail="Nome de documento inválido.")
    caminho = (DOCS_DIR / limpo).resolve()
    try:
        caminho.relative_to(DOCS_DIR.resolve())
    except ValueError as exc:  # pragma: no cover - proteção contra path traversal
        raise HTTPException(status_code=400, detail="Nome de documento inválido.") from exc
    if not caminho.is_file():
        raise HTTPException(status_code=404, detail=f"Documento «{nome}» não encontrado.")
    return caminho


def _markdown_irmao(caminho: Path) -> Optional[Path]:
    """`CAE-Rev.4.pdf` → `CAE-Rev.4.md`, se existir."""
    candidato = caminho.with_suffix(".md")
    return candidato if candidato.is_file() else None


def _markdown_para(caminho: Path) -> Optional[str]:
    """Markdown do documento: `.md` irmão, o próprio `.md` ou conversão de texto."""
    if caminho.suffix.lower() in {".md", ".markdown"}:
        return caminho.read_text(encoding="utf-8", errors="replace")
    irmao = _markdown_irmao(caminho)
    if irmao is not None:
        return irmao.read_text(encoding="utf-8", errors="replace")
    sufixo = caminho.suffix.lower()
    if sufixo in TEXTO:
        bruto = caminho.read_text(encoding="utf-8", errors="replace")
        if sufixo == ".json":
            try:
                dados = json.loads(bruto)
                bruto = json.dumps(dados, ensure_ascii=False, indent=2)
            except json.JSONDecodeError:
                pass
        if sufixo in {".csv", ".tsv"}:
            return f"# {_titulo(caminho.name)}\n\n```{sufixo.lstrip('.')}\n{bruto}\n```\n"
        return f"# {_titulo(caminho.name)}\n\n```text\n{bruto}\n```\n"
    return None


def _tem_markdown(caminho: Path) -> bool:
    """Se o documento tem (ou gera a pedido) uma versão markdown."""
    sufixo = caminho.suffix.lower()
    if sufixo in {".md", ".markdown"} or sufixo in TEXTO:
        return True
    return _markdown_irmao(caminho) is not None


def _documento(caminho: Path, irmaos_md: set[str] | None = None) -> Dict[str, Any]:
    estatistica = caminho.stat()
    sufixo = caminho.suffix.lower()
    irmao = _markdown_irmao(caminho)
    gerado = bool(
        irmaos_md
        and sufixo in {".md", ".markdown"}
        and caminho.name in irmaos_md
    )
    return {
        "name": caminho.name,
        "title": _titulo(caminho.name),
        "kind": TIPO_POR_SUFIXO.get(sufixo, sufixo.lstrip(".").upper() or "Ficheiro"),
        "extension": sufixo.lstrip("."),
        "size": estatistica.st_size,
        "modified": _iso(estatistica.st_mtime),
        "has_markdown": _tem_markdown(caminho),
        "markdown_name": irmao.name if irmao else caminho.name,
        # `.md` que é a versão markdown de outro documento da pasta (ex.:
        # `CAE-Rev.4.md` a partir de `CAE-Rev.4.pdf`) — a página assinala-o.
        "generated": gerado,
        "url": f"/data/docs/{quote(caminho.name)}",
    }


@router.get("/documents")
def listar_documentos() -> Dict[str, Any]:
    """Ficheiros de `data/docs`, mais recentes primeiro."""
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    ficheiros = [
        caminho for caminho in sorted(DOCS_DIR.iterdir()) if caminho.is_file() and not caminho.name.startswith(".")
    ]
    # Versões markdown de outros documentos (ex.: `CAE-Rev.4.md` do `.pdf`).
    irmaos_md: set[str] = set()
    for caminho in ficheiros:
        irmao = _markdown_irmao(caminho)
        if irmao is not None and irmao.suffix.lower() == ".md":
            irmaos_md.add(irmao.name)

    itens: List[Dict[str, Any]] = []
    for caminho in ficheiros:
        try:
            itens.append(_documento(caminho, irmaos_md))
        except OSError as exc:  # pragma: no cover - ficheiro removido a meio
            logger.warning("Documento ignorado (%s): %s", caminho.name, exc)
    itens.sort(key=lambda item: item["modified"], reverse=True)
    return {
        "folder": str(DOCS_DIR),
        "total": len(itens),
        "items": itens,
    }


@router.get("/document/{nome:path}")
def servir_documento(nome: str, download: bool = False):
    """Serve o ficheiro original (pré-visualizar no browser ou descarregar)."""
    caminho = _seguro(nome)
    disposicao = "attachment" if download else "inline"
    return FileResponse(
        caminho,
        filename=caminho.name,
        content_disposition_type=disposicao,
        headers={"Cache-Control": "no-store, must-revalidate"},
    )


@router.get("/markdown/{nome:path}")
def ler_markdown(nome: str) -> Dict[str, Any]:
    """Markdown do documento (`.md` irmão ou conversão de texto)."""
    caminho = _seguro(nome)
    markdown = _markdown_para(caminho)
    if markdown is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"«{caminho.name}» não tem versão markdown. "
                f"Crie `{caminho.with_suffix('.md').name}` na pasta data/docs "
                "(ou use um ficheiro de texto) para o ver aqui."
            ),
        )
    return {
        "name": caminho.name,
        "title": _titulo(caminho.name),
        "kind": TIPO_POR_SUFIXO.get(caminho.suffix.lower(), caminho.suffix.lstrip(".").upper()),
        "source": str(caminho),
        "chars": len(markdown),
        "lines": markdown.count("\n") + 1,
        "markdown": markdown,
    }
