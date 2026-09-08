"""Caminhos padrão do módulo RAG."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DOCS_DIR = ROOT / "data" / "documents"
UPLOADS_DIR = DOCS_DIR / "uploads"
MARKDOWN_DIR = DOCS_DIR / "markdown"
CHUNKS_DIR = DOCS_DIR / "chunks"
VECTORS_DIR = ROOT / "data" / "vectors"

for d in (UPLOADS_DIR, MARKDOWN_DIR, CHUNKS_DIR, VECTORS_DIR):
    d.mkdir(parents=True, exist_ok=True)
