"""Motor de RAG: retrieval + geração com contexto."""
from pathlib import Path
from typing import List, Optional

from rag.models.bloomberg_gpt import BloombergGPTModel
from rag.storage.document_store import DocumentStore
from rag.storage.vector_store import VectorStore


DEFAULT_RAG_PROMPT = """Com base exclusivamente no contexto abaixo, responda de forma curta e precisa à pergunta. Responde em português. Se a informação não existir no contexto, diz "Não encontrei essa informação nos documentos carregados."

Contexto:
{context}

Pergunta: {question}
Resposta:"""

class RagEngine:
    def __init__(
        self,
        vector_store: VectorStore,
        document_store: DocumentStore,
        model: Optional[BloombergGPTModel] = None,
        top_k: int = 5,
        prompt_template: Optional[str] = None,
    ):
        self.vector_store = vector_store
        self.document_store = document_store
        self.model = model
        self.top_k = top_k
        self.prompt_template = prompt_template or DEFAULT_RAG_PROMPT

    def retrieve(
        self,
        question: str,
        top_k: Optional[int] = None,
        min_score: float = 0.0,
        doc_id: Optional[str] = None,
    ) -> List[dict]:
        return self.vector_store.search(
            question,
            top_k=top_k or self.top_k,
            min_score=min_score,
            doc_id=doc_id,
        )

    def build_prompt(self, question: str, context_chunks: List[dict]) -> str:
        context = "\n\n---\n\n".join(
            f"[{i + 1}] {chunk.get('doc_title', 'Documento')} (página {chunk.get('page', '?')})\n{chunk['text']}"
            for i, chunk in enumerate(context_chunks)
        )
        return self.prompt_template.format(context=context, question=question)

    def answer(
        self,
        question: str,
        top_k: Optional[int] = None,
        max_new_tokens: int = 64,
        temperature: float = 0.1,
        return_sources: bool = True,
        doc_id: Optional[str] = None,
    ) -> dict:
        import time

        t0 = time.time()
        chunks = self.retrieve(question, top_k=top_k, doc_id=doc_id)
        prompt = self.build_prompt(question, chunks)

        if not chunks:
            return {
                "answer": "Não encontrei documentos relevantes para a pergunta.",
                "sources": [],
                "prompt": prompt,
                "model_used": None,
            }

        if self.model is None:
            return {
                "answer": self._fallback_answer(question, chunks),
                "sources": chunks,
                "prompt": prompt,
                "model_used": None,
            }

        # Modelos pequenos/não afinados em CPU são lentos; limita geração.
        answer_text = self.model.predict(
            prompt,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
            top_p=0.85,
            top_k=30,
            repetition_penalty=1.15,
            do_sample=True,
        )

        # Modelos pequenos/não afinados produzem frequentemente token salad.
        # Fallback baseado em extração do contexto garante utilidade.
        if not answer_text or len(answer_text.strip()) < 10 or self._looks_like_gibberish(answer_text):
            answer_text = self._fallback_answer(question, chunks)

        result = {
            "answer": answer_text,
            "prompt": prompt,
            "model_used": self.model.model_path,
            "sources": chunks,
            "elapsed_seconds": round(time.time() - t0, 2),
        }
        return result

    @staticmethod
    def _looks_like_gibberish(text: str) -> bool:
        import re
        if not text or not text.strip():
            return True

        # Divide em tokens alfanuméricos (ignora pontuação).
        words = re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9]+", text)
        if not words:
            return True

        from collections import Counter
        counts = Counter(w.lower() for w in words)

        # Deteta repetição excessiva: as 3 palavras mais frequentes > 40% do texto.
        if len(words) >= 10:
            top3_total = sum(c for _, c in counts.most_common(3))
            if top3_total / len(words) > 0.40:
                return True

        # Tokens que são claramente "token salad" (ex: "603SS43", "5-04-234366" sem letras suficientes).
        # Um token "sadio" deve conter uma palavra com pelo menos 3 letras OU ser uma stopword comum PT/EN.
        stopwords = {
            "de", "da", "do", "em", "os", "as", "um", "uma", "que", "com", "por", "para", "se",
            "não", "nos", "nas", "pelo", "pela", "sobre", "sob", "entre", "durante", "apesar",
            "the", "a", "an", "and", "or", "of", "to", "in", "on", "at", "for", "with", "from",
            "day", "price", "trend", "resale", "purch", "reached", "options", "subscription", "customers",
        }
        healthy = 0
        for w in words:
            lower = w.lower()
            if lower in stopwords:
                healthy += 1
            elif re.search(r"[A-Za-zÀ-ÖØ-öø-ÿ]{3,}", w):
                healthy += 1
        if len(words) >= 10 and healthy / len(words) < 0.25:
            return True

        # Se mais de 40% dos tokens forem predominantemente dígitos/hífen, é token salad.
        numeric_like = sum(1 for w in words if re.fullmatch(r"[0-9\-]{2,}|[0-9]+", w))
        if len(words) >= 10 and numeric_like / len(words) > 0.40:
            return True

        return False

    @staticmethod
    def _fallback_answer(question: str, chunks: List[dict]) -> str:
        if not chunks:
            return "Não encontrei informação suficiente nos documentos carregados."
        import re
        # Procura por chunks que contenham keywords da pergunta.
        keywords = [w for w in re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9]+", question.lower()) if len(w) > 3]
        scored = []
        for c in chunks:
            txt = c.get("text", "").lower()
            score = sum(1 for k in keywords if k in txt)
            scored.append((score, c))
        scored.sort(reverse=True, key=lambda x: x[0])
        best = scored[0][1]
        best_text = best.get("text", "").strip()
        # Remove cabeçalhos markdown e metadados.
        best_text = re.sub(r"^#+\s*", "", best_text, flags=re.MULTILINE)
        best_text = re.sub(r"\*\*[^*]+\*\*\s*[:\-]?\s*", "", best_text)
        best_text = re.sub(r"\n{3,}", "\n\n", best_text).strip()
        if not best_text:
            return "Não encontrei informação suficiente nos documentos carregados."
        # Tenta extrair uma frase com keyword.
        sentences = re.split(r"(?<=[.!?])\s+", best_text)
        relevant = [s for s in sentences if any(k in s.lower() for k in keywords)]
        snippet = relevant[0] if relevant else best_text
        return f"Com base no documento carregado:\n\n{snippet}"

    def stream_answer(
        self,
        question: str,
        top_k: Optional[int] = None,
        max_new_tokens: int = 256,
        temperature: float = 0.5,
        doc_id: Optional[str] = None,
    ):
        """Gera resposta em streaming; primeiro yield são as sources."""
        chunks = self.retrieve(question, top_k=top_k, doc_id=doc_id)
        prompt = self.build_prompt(question, chunks)

        yield {"type": "sources", "sources": chunks}

        if self.model is None:
            yield {"type": "token", "token": "[Modelo não carregado]"}
            return

        for token in self.model.predict_streaming(
            prompt,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
            top_p=0.9,
            top_k=50,
        ):
            yield {"type": "token", "token": token}

    def list_documents(self) -> List[dict]:
        return [
            {
                "doc_id": e.doc_id,
                "title": e.title,
                "filename": e.filename,
                "pages": e.pages,
                "indexed": e.indexed,
            }
            for e in self.document_store.list()
        ]
