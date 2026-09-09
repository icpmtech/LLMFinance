"""Análise rápida de RAG: retrieval + respostas."""
import time
from api.rag_service import get_rag_engine

eng = get_rag_engine()
DOC_ID = "13062b000c9a8ff0"
questions = [
    "O que é o MDM?",
    "resumo do documento",
]

for q in questions:
    print(f"\n=== {q} ===")
    t0 = time.time()
    chunks = eng.retrieve(q, top_k=5, doc_id=DOC_ID)
    print(f"retrieve: {len(chunks)} chunks em {round(time.time()-t0,2)}s")
    for i, c in enumerate(chunks, 1):
        print(f"  {i}) score={round(c.get('score',0),3):6.3f} page={c.get('page','?'):>3} doc={c.get('doc_id','?')[:8]} text={c.get('text','')[:90].replace(chr(10),' ')}")

    t1 = time.time()
    res = eng.answer(q, top_k=5, max_new_tokens=64, temperature=0.1, doc_id=DOC_ID)
    print(f"answer: {round(time.time()-t1,2)}s | model_used={res.get('model_used')}")
    print(f"ANSWER: {res['answer'][:250].replace(chr(10),' ')}")
    print(f"fallback? {res['answer'].startswith('Com base no documento carregado:')}")
    print(f"prompt_len: {len(res.get('prompt',''))}")
