"""Converte PDFs para Markdown estruturado usando PyMuPDF ou markitdown."""
import hashlib
import logging
import re
from pathlib import Path
from typing import Optional

try:
    import fitz  # PyMuPDF
except Exception:  # pragma: no cover
    fitz = None

try:
    from markitdown import MarkItDown
except Exception:  # pragma: no cover
    MarkItDown = None

logger = logging.getLogger(__name__)


def _fallback_extract_text(pdf_path: Path) -> str:
    """Extrai texto básico se PyMuPDF falhar ou não estiver instalado."""
    try:
        from PyPDF2 import PdfReader  # type: ignore
        reader = PdfReader(str(pdf_path))
        parts = []
        for i, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            parts.append(f"## Página {i}\n\n{text.strip()}")
        return "\n\n".join(parts)
    except Exception as exc:
        return f"Erro ao extrair texto: {exc}"


def _clean_text(text: str) -> str:
    """Normaliza espaços e quebras de página."""
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _count_pdf_pages(pdf_path: Path) -> int:
    """Devolve o número de páginas do PDF, se possível."""
    if fitz is not None:
        try:
            return len(fitz.open(str(pdf_path)))
        except Exception as exc:
            logger.warning("Não foi possível contar páginas com PyMuPDF: %s", exc)
    return 0


def convert_pdf_to_markdown_pymupdf(
    pdf_path: Path,
    output_dir: Path,
    title: Optional[str] = None,
    extra_metadata: Optional[dict] = None,
) -> dict:
    """Converte um PDF para Markdown usando PyMuPDF (com cabeçalhos por página)."""
    if fitz is None:
        raise RuntimeError("PyMuPDF (fitz) não está instalado.")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    content_bytes = Path(pdf_path).read_bytes()
    file_hash = hashlib.sha256(content_bytes).hexdigest()
    doc_id = file_hash[:16]

    md_filename = f"{doc_id}.md"
    md_path = output_dir / md_filename

    doc = fitz.open(str(pdf_path))
    pages = []
    for page_num in range(len(doc)):
        page = doc.load_page(page_num)
        text = page.get_text("text") or ""
        text = _clean_text(text)
        if text:
            pages.append(f"## Página {page_num + 1}\n\n{text}")

    if not pages:
        pages.append(_fallback_extract_text(pdf_path))

    full_text = "\n\n".join(pages)
    metadata = {
        "id": doc_id,
        "title": title or pdf_path.stem.replace("_", " ").replace("-", " ").title(),
        "filename": pdf_path.name,
        "pages": len(doc),
        "size_bytes": len(content_bytes),
        "hash": file_hash,
        "md_path": str(md_path),
        "extra": extra_metadata or {},
    }

    header = f"# {metadata['title']}\n\n"
    header += f"- **Ficheiro**: {pdf_path.name}\n"
    header += f"- **Páginas**: {metadata['pages']}\n"
    header += f"- **Hash**: {file_hash}\n\n"

    md_path.write_text(header + full_text, encoding="utf-8")
    return metadata


def convert_pdf_to_markdown_markitdown(
    pdf_path: Path,
    output_dir: Path,
    title: Optional[str] = None,
    extra_metadata: Optional[dict] = None,
) -> dict:
    """Converte um PDF para Markdown usando a biblioteca markitdown da Microsoft."""
    if MarkItDown is None:
        raise RuntimeError("markitdown não está instalado. Instala com: pip install 'markitdown[pdf]'")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    content_bytes = Path(pdf_path).read_bytes()
    file_hash = hashlib.sha256(content_bytes).hexdigest()
    doc_id = file_hash[:16]

    md_filename = f"{doc_id}.md"
    md_path = output_dir / md_filename

    md = MarkItDown()
    result = md.convert(pdf_path)
    full_text = _clean_text(result.text_content or result.markdown or "")

    if not full_text:
        full_text = _fallback_extract_text(pdf_path)

    pages = _count_pdf_pages(pdf_path)
    metadata = {
        "id": doc_id,
        "title": title or (result.title if result.title else pdf_path.stem.replace("_", " ").replace("-", " ").title()),
        "filename": pdf_path.name,
        "pages": pages,
        "size_bytes": len(content_bytes),
        "hash": file_hash,
        "md_path": str(md_path),
        "extra": extra_metadata or {},
    }

    header = f"# {metadata['title']}\n\n"
    header += f"- **Ficheiro**: {pdf_path.name}\n"
    header += f"- **Páginas**: {metadata['pages']}\n"
    header += f"- **Hash**: {file_hash}\n"
    header += f"- **Conversor**: markitdown\n\n"

    md_path.write_text(header + full_text, encoding="utf-8")
    return metadata


def convert_pdf_to_markdown(
    pdf_path: Path,
    output_dir: Path,
    title: Optional[str] = None,
    extra_metadata: Optional[dict] = None,
    use_markitdown: bool = False,
) -> dict:
    """Converte um PDF para Markdown e devolve metadados.

    Args:
        pdf_path: caminho do PDF.
        output_dir: pasta onde guardar o .md resultante.
        title: título opcional; se omitido, usa o nome do ficheiro.
        extra_metadata: dicionário com metadados adicionais.
        use_markitdown: se True, usa a API da biblioteca markitdown da Microsoft; senão PyMuPDF.

    Returns:
        dict com id, título, caminho do markdown, número de páginas, hash e metadados.
    """
    if use_markitdown:
        try:
            return convert_pdf_to_markdown_markitdown(pdf_path, output_dir, title=title, extra_metadata=extra_metadata)
        except Exception as exc:
            logger.warning("markitdown falhou (%s); a recair para PyMuPDF.", exc)
    return convert_pdf_to_markdown_pymupdf(pdf_path, output_dir, title=title, extra_metadata=extra_metadata)
