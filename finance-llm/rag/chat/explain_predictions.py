"""Ferramentas para explicar e analisar previsões financeiras do RAG."""
from typing import List, Optional


def explain_prediction(
    question: str,
    answer: str,
    sources: List[dict],
    model_name: Optional[str] = None,
) -> dict:
    """Constrói uma explicação legível sobre como a resposta foi obtida."""
    unique_docs = sorted({s.get("doc_title", s.get("doc_id", "?")) for s in sources})
    pages = sorted({s.get("page") for s in sources if s.get("page") is not None})
    top_scores = [round(s.get("score", 0.0), 4) for s in sources]

    return {
        "question": question,
        "answer_preview": answer[:500],
        "model_used": model_name,
        "documents_used": unique_docs,
        "pages_used": pages,
        "retrieval_scores": top_scores,
        "analysis": (
            f"A resposta foi gerada com base em {len(sources)} passagens recuperadas "
            f"de {len(unique_docs)} documento(s). "
            f"Scores médio/mediana dos chunks: {(_avg(top_scores) if top_scores else 0):.4f} / "
            f"{(_median(top_scores) if top_scores else 0):.4f}."
        ),
    }


def analyze_rag_predictions(
    samples: List[dict],
    vector_store,
    model=None,
) -> dict:
    """Avalia um conjunto de perguntas/respostas esperadas."""
    correct = 0
    details = []
    for sample in samples:
        question = sample["question"]
        expected = sample.get("expected_answer", "")
        retrieved = vector_store.search(question, top_k=5)
        if model:
            generated = model.predict(question, max_new_tokens=128)
        else:
            generated = "[sem modelo]"
        is_match = _soft_match(generated, expected)
        if is_match:
            correct += 1
        details.append(
            {
                "question": question,
                "expected": expected,
                "generated": generated,
                "retrieved_count": len(retrieved),
                "match": is_match,
            }
        )

    total = len(samples) or 1
    return {
        "accuracy": correct / total,
        "correct": correct,
        "total": len(samples),
        "details": details,
    }


def _avg(values: List[float]) -> float:
    return sum(values) / len(values)


def _median(values: List[float]) -> float:
    s = sorted(values)
    n = len(s)
    if n == 0:
        return 0.0
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2


def _soft_match(generated: str, expected: str) -> bool:
    gen = generated.lower()
    exp = expected.lower()
    if exp in gen or gen in exp:
        return True
    gen_words = set(gen.split())
    exp_words = set(exp.split())
    if not exp_words:
        return False
    return len(gen_words & exp_words) / len(exp_words) >= 0.5
