"""Vector store local com sentence-transformers + FAISS."""
import json
from pathlib import Path
from typing import List, Optional, Sequence

try:
    import faiss  # type: ignore
except Exception:  # pragma: no cover
    faiss = None

try:
    from sentence_transformers import SentenceTransformer  # type: ignore
except Exception:  # pragma: no cover
    SentenceTransformer = None


class VectorStore:
    def __init__(
        self,
        index_dir: Optional[Path] = None,
        model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
        device: str = "cpu",
    ):
        from rag.paths import VECTORS_DIR

        if faiss is None:
            raise RuntimeError("faiss-cpu não está instalado.")
        if SentenceTransformer is None:
            raise RuntimeError("sentence-transformers não está instalado.")

        self.index_dir = Path(index_dir) if index_dir else VECTORS_DIR
        self.index_dir.mkdir(parents=True, exist_ok=True)
        self.model_name = model_name
        self.device = device
        self.model = SentenceTransformer(model_name, device=device)
        self.dim = self.model.get_sentence_embedding_dimension()

        self.index_path = self.index_dir / "faiss.index"
        self.chunks_path = self.index_dir / "chunks.jsonl"

        self._chunks: List[dict] = []
        self.index = self._load_or_create_index()
        self._load_chunks()

    def _load_or_create_index(self):
        if self.index_path.exists():
            return faiss.read_index(str(self.index_path))
        return faiss.IndexFlatIP(self.dim)

    def _load_chunks(self):
        if self.chunks_path.exists():
            self._chunks = [
                json.loads(line)
                for line in self.chunks_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]

    def _save(self):
        faiss.write_index(self.index, str(self.index_path))
        with self.chunks_path.open("w", encoding="utf-8") as f:
            for chunk in self._chunks:
                f.write(json.dumps(chunk, ensure_ascii=False) + "\n")

    def add(self, chunks: Sequence[dict]):
        if not chunks:
            return
        texts = [c["text"] for c in chunks]
        embeddings = self.model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
        self.index.add(embeddings)
        self._chunks.extend(chunks)
        self._save()

    def search(
        self,
        query: str,
        top_k: int = 5,
        min_score: float = 0.0,
    ) -> List[dict]:
        if not self._chunks:
            return []
        query_embedding = self.model.encode(
            [query], convert_to_numpy=True, normalize_embeddings=True
        )
        scores, indices = self.index.search(query_embedding, min(top_k, len(self._chunks)))
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0 or idx >= len(self._chunks):
                continue
            chunk = self._chunks[idx].copy()
            chunk["score"] = float(score)
            if score >= min_score:
                results.append(chunk)
        return results

    def list_doc_ids(self) -> List[str]:
        return sorted({c["doc_id"] for c in self._chunks})

    def delete_by_doc_id(self, doc_id: str):
        self._chunks = [c for c in self._chunks if c.get("doc_id") != doc_id]
        if not self._chunks:
            if self.index_path.exists():
                self.index_path.unlink()
            if self.chunks_path.exists():
                self.chunks_path.unlink()
            self.index = faiss.IndexFlatIP(self.dim)
        else:
            self.index = faiss.IndexFlatIP(self.dim)
            texts = [c["text"] for c in self._chunks]
            embeddings = self.model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
            self.index.add(embeddings)
        self._save()
