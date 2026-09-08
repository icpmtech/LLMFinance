"""Index JSON com os documentos ingeridos."""
import json
import shutil
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional


@dataclass
class DocumentEntry:
    doc_id: str
    title: str
    filename: str
    pages: int
    size_bytes: int
    hash: str
    md_path: str
    chunk_file: str
    indexed: bool = False
    created_at: float = 0.0
    extra: dict = None

    def __post_init__(self):
        if self.created_at == 0.0:
            self.created_at = time.time()
        if self.extra is None:
            self.extra = {}


class DocumentStore:
    def __init__(self, index_path: Optional[Path] = None, uploads_dir: Optional[Path] = None):
        from rag.paths import UPLOADS_DIR

        self.index_path = Path(index_path) if index_path else UPLOADS_DIR.parent / "index.json"
        self.uploads_dir = Path(uploads_dir) if uploads_dir else UPLOADS_DIR
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        self._docs: dict[str, dict] = {}
        self._load()

    def _load(self):
        if self.index_path.exists():
            try:
                self._docs = json.loads(self.index_path.read_text(encoding="utf-8"))
            except Exception:
                self._docs = {}

    def _save(self):
        self.index_path.write_text(
            json.dumps(self._docs, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def add(self, entry: DocumentEntry) -> DocumentEntry:
        self._docs[entry.doc_id] = asdict(entry)
        self._save()
        return entry

    def get(self, doc_id: str) -> Optional[DocumentEntry]:
        raw = self._docs.get(doc_id)
        return DocumentEntry(**raw) if raw else None

    def list(self) -> List[DocumentEntry]:
        return [DocumentEntry(**v) for v in self._docs.values()]

    def exists(self, file_hash: str) -> Optional[str]:
        for doc_id, meta in self._docs.items():
            if meta.get("hash") == file_hash:
                return doc_id
        return None

    def set_indexed(self, doc_id: str, indexed: bool = True):
        if doc_id in self._docs:
            self._docs[doc_id]["indexed"] = indexed
            self._save()

    def delete(self, doc_id: str) -> bool:
        entry = self._docs.pop(doc_id, None)
        if entry:
            self._save()
            md_path = Path(entry.get("md_path", ""))
            if md_path.exists():
                md_path.unlink()
            chunk_file = Path(entry.get("chunk_file", ""))
            if chunk_file.exists():
                chunk_file.unlink()
            pdf_path = self.uploads_dir / entry.get("filename", "")
            if pdf_path.exists():
                pdf_path.unlink()
            return True
        return False
