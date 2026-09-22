"""Reranker cross-encoder leve para RAG.

Utiliza `sentence-transformers` com um modelo cross-encoder (por defeito
`cross-encoder/ms-marco-MiniLM-L-6-v2`). Se o modelo não estiver disponível
(local/offline) ou falhar, devolve os resultados originais como fallback.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

try:
    from sentence_transformers import CrossEncoder  # type: ignore
except Exception:  # pragma: no cover
    CrossEncoder = None

DEFAULT_RERANK_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"


@dataclass
class RerankedResult:
    chunk: Dict[str, Any]
    rerank_score: float
    previous_index: int


class CrossEncoderReranker:
    def __init__(self, model_name: str = DEFAULT_RERANK_MODEL, device: str = "cpu", max_length: int = 512):
        self.model_name = model_name
        self.device = device
        self.max_length = max_length
        self._model: Optional["CrossEncoder"] = None
        self._lock = threading.Lock()
        self._available: Optional[bool] = None

    @property
    def available(self) -> bool:
        if self._available is None:
            self._available = CrossEncoder is not None
        return self._available

    def _load(self) -> bool:
        if not self.available or self._model is not None:
            return self._model is not None
        with self._lock:
            if self._model is not None:
                return True
            try:
                self._model = CrossEncoder(
                    self.model_name, max_length=self.max_length, device=self.device
                )
                return True
            except Exception:
                self._available = False
                return False

    def rerank(
        self,
        query: str,
        results: List[Any],
        top_k: int = 5,
    ) -> List[RerankedResult]:
        """Reranka uma lista de resultados (HybridResult ou dicts).

        Args:
            query: pergunta original.
            results: lista de resultados com atributo `.chunk` ou dicts.
            top_k: número de resultados a devolver.

        Returns:
            Lista ordenada por score descendente. Se o reranker não estiver
            disponível, devolve os resultados originais truncados.
        """
        if not results:
            return []

        chunks: List[Dict[str, Any]] = []
        for r in results:
            if hasattr(r, "chunk"):
                chunks.append(r.chunk)
            elif isinstance(r, dict):
                chunks.append(r)
            else:
                chunks.append({"text": str(r)})

        if not self._load():
            return [
                RerankedResult(chunk=c, rerank_score=float(i), previous_index=i)
                for i, c in enumerate(chunks[:top_k])
            ]

        pairs: List[List[str]] = []
        for c in chunks:
            text = c.get("text", "")[: self.max_length]
            pairs.append([query[: self.max_length], text])

        try:
            scores = self._model.predict(pairs, show_progress_bar=False)
        except Exception:
            return [
                RerankedResult(chunk=c, rerank_score=float(i), previous_index=i)
                for i, c in enumerate(chunks[:top_k])
            ]

        scored = sorted(
            enumerate(scores),
            key=lambda x: x[1],
            reverse=True,
        )
        return [
            RerankedResult(
                chunk=chunks[original_idx],
                rerank_score=float(score),
                previous_index=original_idx,
            )
            for original_idx, score in scored[:top_k]
        ]

    def rerank_dicts(
        self,
        query: str,
        chunks: List[Dict[str, Any]],
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """Reranka dicts de chunks em-place e devolve-os com `rerank_score` + `rank`."""
        if not chunks:
            return []
        results = self.rerank(query, chunks, top_k=top_k)
        out: List[Dict[str, Any]] = []
        for rank, r in enumerate(results, start=1):
            chunk = r.chunk.copy()
            chunk["rerank_score"] = r.rerank_score
            chunk["rank"] = rank
            out.append(chunk)
        return out
