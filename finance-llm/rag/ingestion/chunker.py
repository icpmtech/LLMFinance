"""Divide Markdown em chunks com overlap e referências de origem."""
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    doc_title: str
    page: Optional[int]
    text: str
    source_md_path: str
    start_pos: int = 0
    end_pos: int = 0
    metadata: dict = field(default_factory=dict)


def _split_into_sections(markdown: str) -> List[tuple]:
    """Separa Markdown por cabeçalhos e devolve lista de (título, corpo, página)."""
    lines = markdown.splitlines()
    sections: List[tuple] = []
    current_title = ""
    current_body: List[str] = []
    current_page: Optional[int] = None

    page_re = re.compile(r"^##\s+P[áa]gina\s+(\d+)", re.IGNORECASE)

    for line in lines:
        page_match = page_re.match(line.strip())
        if page_match:
            if current_body:
                sections.append((current_title, "\n".join(current_body).strip(), current_page))
                current_body = []
            current_page = int(page_match.group(1))
            current_title = f"Página {current_page}"
            continue

        if line.startswith("#"):
            if current_body:
                sections.append((current_title, "\n".join(current_body).strip(), current_page))
                current_body = []
            current_title = line.lstrip("#").strip()
            continue

        current_body.append(line)

    if current_body:
        sections.append((current_title, "\n".join(current_body).strip(), current_page))

    return [(t, b, p) for t, b, p in sections if b.strip()]


def _split_text(text: str, max_chars: int) -> List[str]:
    """Quebra texto respeitando parágrafos e frases."""
    if len(text) <= max_chars:
        return [text]

    parts: List[str] = []
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    current = ""
    for para in paragraphs:
        if len(current) + len(para) + 2 <= max_chars:
            current = f"{current}\n\n{para}".strip() if current else para
        else:
            if current:
                parts.append(current)
            if len(para) > max_chars:
                sentences = re.split(r"(?<=[.!?])\s+", para)
                current = ""
                for sentence in sentences:
                    if len(current) + len(sentence) + 1 <= max_chars:
                        current = f"{current} {sentence}".strip() if current else sentence
                    else:
                        if current:
                            parts.append(current)
                        current = sentence
            else:
                current = para
    if current:
        parts.append(current)
    return parts


def chunk_markdown(
    md_path: Path,
    doc_id: str,
    doc_title: str,
    max_chars: int = 800,
    overlap_chars: int = 120,
) -> List[Chunk]:
    """Cria chunks a partir de um ficheiro Markdown.

    Args:
        md_path: caminho do ficheiro Markdown.
        doc_id: identificador do documento.
        doc_title: título do documento.
        max_chars: tamanho máximo aproximado de cada chunk.
        overlap_chars: caracteres de overlap entre chunks consecutivos.

    Returns:
        Lista de `Chunk` com referência de página e posição.
    """
    md_path = Path(md_path)
    raw = md_path.read_text(encoding="utf-8")
    sections = _split_into_sections(raw)
    chunks: List[Chunk] = []
    position = 0

    for section_title, body, page in sections:
        parts = _split_text(body, max_chars)
        for i, part in enumerate(parts):
            prefix = f"# {section_title}\n\n" if section_title and not part.startswith("#") else ""
            text = prefix + part
            overlap = ""
            if i > 0 and overlap_chars > 0:
                overlap = part[:overlap_chars]
                text = overlap + "\n\n" + text if overlap else text

            chunk_id = f"{doc_id}_{len(chunks):06d}"
            end_pos = position + len(text)
            chunks.append(
                Chunk(
                    chunk_id=chunk_id,
                    doc_id=doc_id,
                    doc_title=doc_title,
                    page=page,
                    text=text.strip(),
                    source_md_path=str(md_path),
                    start_pos=position,
                    end_pos=end_pos,
                    metadata={"section": section_title, "chunk_index": i, "page": page},
                )
            )
            position = end_pos - len(overlap)

    return chunks


def save_chunks(chunks: List[Chunk], output_path: Path) -> Path:
    """Guarda chunks num ficheiro JSONL."""
    import json

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        for chunk in chunks:
            f.write(
                json.dumps(
                    {
                        "chunk_id": chunk.chunk_id,
                        "doc_id": chunk.doc_id,
                        "doc_title": chunk.doc_title,
                        "page": chunk.page,
                        "text": chunk.text,
                        "source_md_path": chunk.source_md_path,
                        "start_pos": chunk.start_pos,
                        "end_pos": chunk.end_pos,
                        "metadata": chunk.metadata,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    return output_path
