"""Retriever híbrido para documentos RAG: combina busca vetorial (FAISS),
keyword search (BM25) e fusion por RRF.

Se `rank_bm25` não estiver instalado, usa um fallback baseado em frequência
de termos (TF) simples. O objetivo é recuperar termos exatos (SKUs, IDs,
nomes próprios) que a busca vetorial pode perder.
"""
from __future__ import annotations

import re
import threading
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

try:
    import faiss  # type: ignore
except Exception:  # pragma: no cover
    faiss = None

try:
    from rank_bm25 import BM25Okapi  # type: ignore
except Exception:  # pragma: no cover
    BM25Okapi = None

try:
    from sentence_transformers import SentenceTransformer  # type: ignore
except Exception:  # pragma: no cover
    SentenceTransformer = None

from rag.storage.vector_store import _get_embedding_model


DEFAULT_RRF_K = 60
STOPWORDS_PT = {
    "de", "da", "do", "em", "os", "as", "um", "uma", "que", "com", "por", "para", "se",
    "não", "nos", "nas", "pelo", "pela", "sobre", "sob", "entre", "durante", "apesar",
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "at", "for", "with", "from",
}


def _tokenize(text: str) -> List[str]:
    """Tokeniza para keyword search (minúsculas, alfanuméricos, sem stopwords curtas)."""
    tokens = re.findall(r"[a-zà-öø-ÿ0-9]+", text.lower())
    return [t for t in tokens if t not in STOPWORDS_PT and len(t) > 2]


@dataclass
class HybridResult:
    chunk: Dict[str, Any]
    vector_rank: Optional[int]
    keyword_rank: Optional[int]
    rrf_score: float
    keyword_score: Optional[float]


class HybridRetriever:
    """Combina FAISS, BM25 (ou fallback TF) e RRF.

    Atualmente trabalha com os chunks já carregados pelo VectorStore. O
    construtor aceita `chunks` (lista de dicts) e um modelo sentence-transformers.
    """

    def __init__(
        self,
        chunks: Sequence[Dict[str, Any]],
        model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
        device: str = "cpu",
        rrf_k: int = DEFAULT_RRF_K,
    ):
        self.chunks = list(chunks)
        self.model_name = model_name
        self.device = device
        self.rrf_k = rrf_k
        self._model: Optional[SentenceTransformer] = None
        self._index: Optional[faiss.IndexFlatIP] = None
        self._tokenized_corpus: List[List[str]] = []
        self._bm25: Optional[Any] = None
        self._lock = threading.Lock()
        self._build()

    @property
    def model(self) -> "SentenceTransformer":
        if self._model is None:
            self._model = _get_embedding_model(self.model_name, self.device)
        return self._model

    def _build(self) -> None:
        if faiss is None:
            raise RuntimeError("faiss-cpu não está instalado.")
        if not self.chunks:
            self._index = faiss.IndexFlatIP(self.model.get_sentence_embedding_dimension())
            self._tokenized_corpus = []
            return

        texts = [c.get("text", "") for c in self.chunks]
        embeddings = self.model.encode(
            texts, convert_to_numpy=True, normalize_embeddings=True, show_progress_bar=False
        )
        self._index = faiss.IndexFlatIP(embeddings.shape[1])
        self._index.add(embeddings)

        self._tokenized_corpus = [_tokenize(t) for t in texts]
        if BM25Okapi is not None and self._tokenized_corpus:
            self._bm25 = BM25Okapi(self._tokenized_corpus)

    def refresh(self, chunks: Sequence[Dict[str, Any]]) -> None:
        with self._lock:
            self.chunks = list(chunks)
            self._index = None
            self._bm25 = None
            self._tokenized_corpus = []
            self._build()

    def _keyword_scores(self, query: str) -> List[float]:
        """Devolve scores de keyword para cada chunk (BM25 se disponível, senão TF simples)."""
        tokens = _tokenize(query)
        if not tokens:
            return [0.0] * len(self.chunks)

        if self._bm25 is not None:
            return self._bm25.get_scores(tokens)

        # Fallback TF: soma da frequência dos termos da query no documento.
        query_counts = Counter(tokens)
        scores: List[float] = []
        for doc_tokens in self._tokenized_corpus:
            doc_counts = Counter(doc_tokens)
            score = sum(doc_counts[t] * w for t, w in query_counts.items())
            scores.append(score)
        return scores

    def search(
        self,
        query: str,
        top_k: int = 10,
        vector_k: Optional[int] = None,
        keyword_k: Optional[int] = None,
        doc_id: Optional[str] = None,
    ) -> List[HybridResult]:
        """Executa busca híbrida e devolve resultados fundidos por RRF.

        Args:
            query: pergunta do utilizador.
            top_k: número final de resultados após RRF.
            vector_k: tamanho do candidato pool vetorial (default: 2*top_k).
            keyword_k: tamanho do candidato pool keyword (default: 2*top_k).
            doc_id: restringir a um documento específico.
        """
        if not self.chunks:
            return []

        chunks = self.chunks
        indices = list(range(len(chunks)))
        if doc_id is not None:
            indices = [i for i, c in enumerate(chunks) if c.get("doc_id") == doc_id]
            if not indices:
                return []
            chunks = [chunks[i] for i in indices]

        vector_k = vector_k or max(top_k * 2, 10)
        keyword_k = keyword_k or max(top_k * 2, 10)

        # Vetorial
        query_embedding = self.model.encode(
            [query], convert_to_numpy=True, normalize_embeddings=True, show_progress_bar=False
        )
        vector_rank: Dict[int, int] = {}
        if doc_id is None:
            scores, positions = self._index.search(query_embedding, min(vector_k, len(chunks)))
            for rank, pos in enumerate(positions[0]):
                if 0 <= pos < len(self.chunks) and pos in indices:
                    local_pos = indices.index(pos)
                    vector_rank[local_pos] = rank + 1
        else:
            sub_embeddings = self.model.encode(
                [c.get("text", "") for c in chunks],
                convert_to_numpy=True,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
            sub_index = faiss.IndexFlatIP(sub_embeddings.shape[1])
            sub_index.add(sub_embeddings)
            scores, positions = sub_index.search(query_embedding, min(vector_k, len(chunks)))
            for rank, pos in enumerate(positions[0]):
                if 0 <= pos < len(chunks):
                    vector_rank[pos] = rank + 1

        # Keyword
        keyword_scores = self._keyword_scores(query)
        if doc_id is None:
            filtered_scores = [keyword_scores[i] for i in indices]
        else:
            filtered_scores = keyword_scores

        ranked_keyword = sorted(
            range(len(filtered_scores)),
            key=lambda i: filtered_scores[i],
            reverse=True,
        )
        keyword_rank: Dict[int, int] = {}
        for rank, local_pos in enumerate(ranked_keyword[:keyword_k]):
            keyword_rank[local_pos] = rank + 1

        # RRF fusion
        rrf: Dict[int, float] = {}
        for local_pos in set(vector_rank.keys()) | set(keyword_rank.keys()):
            score = 0.0
            if local_pos in vector_rank:
                score += 1.0 / (self.rrf_k + vector_rank[local_pos])
            if local_pos in keyword_rank:
                score += 1.0 / (self.rrf_k + keyword_rank[local_pos])
            rrf[local_pos] = score

        sorted_positions = sorted(rrf.keys(), key=lambda p: rrf[p], reverse=True)
        results: List[HybridResult] = []
        for rank, pos in enumerate(sorted_positions[:top_k], start=1):
            chunk = chunks[pos].copy()
            chunk["score"] = rrf[pos]
            chunk["rank"] = rank
            results.append(
                HybridResult(
                    chunk=chunk,
                    vector_rank=vector_rank.get(pos),
                    keyword_rank=keyword_rank.get(pos),
                    rrf_score=rrf[pos],
                    keyword_score=filtered_scores[pos] if pos < len(filtered_scores) else None,
                )
            )
        return results
