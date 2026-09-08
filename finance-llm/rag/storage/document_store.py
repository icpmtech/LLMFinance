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
    updated_at: Optional[float] = None
    converter: Optional[str] = None
    extra: dict = None
    history: List[dict] = None

    def __post_init__(self):
        if self.created_at == 0.0:
            self.created_at = time.time()
        if self.extra is None:
            self.extra = {}
        if self.history is None:
            self.history = []

    @classmethod
    def from_dict(cls, raw: dict) -> "DocumentEntry":
        allowed = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in raw.items() if k in allowed}
        return cls(**filtered)


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
        return DocumentEntry.from_dict(raw) if raw else None

    def list(self) -> List[DocumentEntry]:
        return [DocumentEntry.from_dict(v) for v in self._docs.values()]

    def exists(self, file_hash: str) -> Optional[str]:
        for doc_id, meta in self._docs.items():
            if meta.get("hash") == file_hash:
                return doc_id
        return None

    def set_indexed(self, doc_id: str, indexed: bool = True):
        if doc_id in self._docs:
            self._docs[doc_id]["indexed"] = indexed
            self._docs[doc_id]["updated_at"] = time.time()
            self._save()

    def update(self, doc_id: str, title: str) -> Optional[DocumentEntry]:
        if doc_id not in self._docs:
            return None
        self._docs[doc_id]["title"] = title
        self._docs[doc_id]["updated_at"] = time.time()
        self._save()
        return DocumentEntry.from_dict(self._docs[doc_id])

    def add_history(self, doc_id: str, action: str, detail: str = ""):
        if doc_id not in self._docs:
            return
        history = self._docs[doc_id].setdefault("history", [])
        history.append(
            {"action": action, "detail": detail, "timestamp": time.time()}
        )
        self._docs[doc_id]["history"] = history
        self._save()

    def get_history(self, doc_id: str) -> List[dict]:
        if doc_id not in self._docs:
            return []
        return list(self._docs[doc_id].get("history", []))

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
