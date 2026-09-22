"""CRAG-style context grader e query reformulation sem dependências externas.

Implementa um ciclo simples de Corrective RAG:
1. Recupera contexto.
2. Avalia se o contexto responde à pergunta (score 0..1).
3. Se score < threshold, reformula a query e tenta novamente (máx. tentativas).
4. Se mesmo assim não for suficiente, dá fallback "não sei".

A classificação é feita por um LLM leve/local via Ollama ou pelo modelo local
configurado no RagEngine. Para evitar dependências pesadas, a chamada ao LLM
é injetada como função (`grade_fn`) no método `run`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence


DEFAULT_THRESHOLD = 0.6


def _tokenize(text: str) -> List[str]:
    return re.findall(r"[a-zà-öø-ÿ0-9]+", text.lower())


def _overlap_score(query: str, context: str) -> float:
    """Heurística de cobertura lexical: termos da query presentes no contexto."""
    q_tokens = set(_tokenize(query))
    c_tokens = set(_tokenize(context))
    if not q_tokens:
        return 0.0
    return len(q_tokens & c_tokens) / len(q_tokens)


@dataclass
class CragResult:
    query: str
    original_query: str
    context: List[Dict[str, Any]]
    iterations: int
    grade: float
    reformulated: bool
    fallback: bool
    reasoning: str
    sources: List[Dict[str, Any]] = field(default_factory=list)


class CragGrader:
    """Avalia e reformula queries quando o contexto recuperado é fraco."""

    def __init__(
        self,
        retrieve_fn: Callable[[str, int, bool], List[Dict[str, Any]]],
        threshold: float = DEFAULT_THRESHOLD,
        max_iterations: int = 2,
    ):
        """Args:
            retrieve_fn: função(query, top_k, use_hybrid) -> lista de chunks.
            threshold: grade mínimo para considerar contexto suficiente.
            max_iterations: número máximo de tentativas incluindo a original.
        """
        self.retrieve_fn = retrieve_fn
        self.threshold = threshold
        self.max_iterations = max_iterations

    def _grade(self, query: str, context_chunks: Sequence[Dict[str, Any]], grade_fn: Optional[Callable[[str, Sequence[Dict[str, Any]]], float]] = None) -> tuple[float, str]:
        context_text = "\n\n".join(
            c.get("text", "") for c in context_chunks[:5]
        )
        if grade_fn is not None:
            try:
                grade = grade_fn(query, context_chunks)
                return float(grade), "llm"
            except Exception:
                pass

        # Fallback léxico simples + comprimento mínimo.
        lexical = _overlap_score(query, context_text)
        length_score = min(1.0, len(context_text) / 800.0)
        grade = 0.7 * lexical + 0.3 * length_score
        return grade, "lexical"

    def _reformulate(self, query: str, context: Sequence[Dict[str, Any]]) -> str:
        """Reformula a query expandindo com sinónimos/termos do contexto recuperado."""
        # Heurística: junta os 5 termos mais frequentes do contexto que não estão na query.
        context_text = " ".join(c.get("text", "") for c in context)
        q_tokens = set(_tokenize(query))
        c_tokens = _tokenize(context_text)
        top_terms = [
            term
            for term, _ in __import__("collections").Counter(t for t in c_tokens if t not in q_tokens and len(t) > 3).most_common(5)
        ]
        if not top_terms:
            return query
        return f"{query} ({' '.join(top_terms)})"

    def run(
        self,
        query: str,
        top_k: int = 5,
        use_hybrid: bool = True,
        use_rerank: bool = False,
        grade_fn: Optional[Callable[[str, Sequence[Dict[str, Any]]], float]] = None,
    ) -> CragResult:
        """Executa o loop CRAG."""
        original_query = query
        current = query
        best_context: List[Dict[str, Any]] = []
        best_grade = 0.0
        last_reason = ""

        for iteration in range(1, self.max_iterations + 1):
            chunks = self.retrieve_fn(current, top_k * 2, use_hybrid)
            if use_rerank and len(chunks) > top_k:
                # O rerank será aplicado mais tarde pelo RagEngine; aqui apenas truncamos.
                chunks = chunks[: top_k * 2]

            grade, reason = self._grade(current, chunks, grade_fn=grade_fn)
            last_reason = reason

            if grade >= self.threshold:
                return CragResult(
                    query=current,
                    original_query=original_query,
                    context=chunks[:top_k],
                    iterations=iteration,
                    grade=grade,
                    reformulated=current != original_query,
                    fallback=False,
                    reasoning=reason,
                    sources=[
                        {
                            "doc_id": c.get("doc_id"),
                            "chunk_id": c.get("chunk_id"),
                            "section": c.get("section"),
                            "page": c.get("page"),
                            "score": c.get("score"),
                        }
                        for c in chunks[:top_k]
                    ],
                )

            if grade > best_grade:
                best_grade = grade
                best_context = chunks

            if iteration < self.max_iterations:
                current = self._reformulate(current, chunks)

        # Não atingiu threshold: devolve o melhor contexto encontrado mas sinaliza fallback.
        return CragResult(
            query=current,
            original_query=original_query,
            context=best_context[:top_k],
            iterations=self.max_iterations,
            grade=best_grade,
            reformulated=current != original_query,
            fallback=True,
            reasoning=f"{last_reason} (below threshold {self.threshold})",
            sources=[
                {
                    "doc_id": c.get("doc_id"),
                    "chunk_id": c.get("chunk_id"),
                    "section": c.get("section"),
                    "page": c.get("page"),
                    "score": c.get("score"),
                }
                for c in best_context[:top_k]
            ],
        )
