"""Serviço singleton de RAG para a API."""
from pathlib import Path
from typing import Optional

from rag.chat.rag_engine import RagEngine
from rag.models.bloomberg_gpt import BloombergGPTModel
from rag.storage.document_store import DocumentStore
from rag.storage.vector_store import VectorStore

# Cache global para evitar recarregar modelos a cada pedido.
_rag_engine: Optional[RagEngine] = None
_model: Optional[BloombergGPTModel] = None


def _log(msg: str):
    log_path = Path(__file__).resolve().parent.parent / "rag_service.log"
    with open(log_path, "a", encoding="utf-8") as fh:
        fh.write(msg + "\n")


def get_vector_store() -> VectorStore:
    return VectorStore()


def get_document_store() -> DocumentStore:
    return DocumentStore()


def get_bloomberg_model(model_path: Optional[str] = None) -> Optional[BloombergGPTModel]:
    global _model
    if _model is None:
        candidates = [
            model_path,
            "model/bloomberg-finance/final",
            "model/mistral-finance/final",
            "model/gpt2-finance/final",
        ]
        _log(f"Candidates: {candidates}")
        for candidate in candidates:
            if not candidate:
                continue
            if not Path(candidate).exists():
                _log(f"Candidate missing: {candidate}")
                continue
            try:
                _log(f"Attempting to load model from: {candidate}")
                _model = BloombergGPTModel(candidate, load_in_8bit=False)
                _log(
                    f"Successfully loaded model from {candidate} (type={_model.model.config.model_type})"
                )
                break
            except Exception as exc:
                _log(f"Failed to load model {candidate}: {type(exc).__name__}: {exc}")
                import traceback

                _log(traceback.format_exc())
                continue
        if _model is None:
            _log("No RAG generation model could be loaded.")
    return _model


def get_rag_engine() -> RagEngine:
    global _rag_engine
    if _rag_engine is None:
        _rag_engine = RagEngine(
            vector_store=get_vector_store(),
            document_store=get_document_store(),
            model=get_bloomberg_model(),
        )
    return _rag_engine


def reset_rag_engine():
    global _rag_engine, _model
    _rag_engine = None
    _model = None


def _format_entity(contract: dict, kind: str) -> str:
    parties = contract.get(kind) or []
    if not parties:
        return "n/a"
    if isinstance(parties, dict):
        parties = [parties]
    names = []
    for party in parties:
        if isinstance(party, str):
            names.append(party)
            continue
        for parsed in party.get("parsed", []):
            if parsed.get("nome"):
                names.append(parsed["nome"])
        raw = party.get("raw")
        if raw and not party.get("parsed"):
            if isinstance(raw, list):
                names.extend([r for r in raw if isinstance(r, str)])
            elif isinstance(raw, str):
                names.append(raw)
    return ", ".join(names) if names else "n/a"


def _format_price(contract: dict) -> Optional[float]:
    for key in ("precoContratual", "PrecoTotalEfetivo", "precoBaseProcedimento"):
        value = contract.get(key)
        if value is not None:
            try:
                return float(value)
            except (ValueError, TypeError):
                pass
    return None


def get_contracts_chat_answer(
    question: str,
    top_k: int = 5,
    max_new_tokens: int = 256,
    temperature: float = 0.1,
    model_name: Optional[str] = None,
) -> tuple[str, list]:
    """RAG simples para responder perguntas sobre contratos públicos.

    Recupera contratos relevantes do Elasticsearch, constrói um contexto e usa
    o modelo local carregado para gerar uma resposta em português.
    """
    from api.elasticsearch_client import search_contracts

    hits = search_contracts(q=question, size=top_k)
    sources = []
    context_lines = [
        "Responde em português com base nos seguintes contratos públicos portugueses."
    ]
    # Grounding ontológico: as entidades da pergunta são resolvidas para objetos
    # canónicos antes da recuperação, para o modelo não confundir homónimos.
    try:
        from api import ontology_service as ontology

        grounding = ontology.ai_context(question, limit=3, links_per_object=1, link_size=2, link_budget=2)
        if grounding["objects"]:
            context_lines.append("Entidades da ontologia (objetos canónicos da plataforma):")
            context_lines.extend("  " + line for line in grounding["grounding"].splitlines())
        ontology_context = grounding
    except Exception as exc:
        ontology_context = {"objects": [], "relations": [], "grounding": "", "notes": [f"Ontologia indisponível: {exc}"]}
    for item in hits.get("items", []):
        adjudicante = _format_entity(item, "adjudicantes")
        adjudicatario = _format_entity(item, "adjudicatarios")
        preco = _format_price(item)
        source = {
            "idcontrato": item.get("idcontrato"),
            "objectoContrato": item.get("objectoContrato"),
            "adjudicante": adjudicante,
            "adjudicatario": adjudicatario,
            "precoContratual": preco,
            "score": item.get("score"),
        }
        sources.append(source)
        context_lines.append(
            f"Contrato {item.get('idcontrato')}: {item.get('objectoContrato')} | "
            f"Adjudicante: {adjudicante} | Adjudicatário: {adjudicatario} | "
            f"Preço: {preco}€ | Local: {item.get('localExecucao')} | "
            f"Data: {item.get('dataCelebracaoContrato') or item.get('dataPublicacao')}"
        )

    context = "\n".join(context_lines)
    prompt = (
        f"{context}\n\nPergunta: {question}\n\n"
        "Resposta curta e factual baseada apenas nos contratos acima. "
        "Se não souberes, diz que não tens informação suficiente."
    )

    try:
        model = get_bloomberg_model(model_name)
        if model is None:
            answer = (
                "Não foi possível carregar o modelo de geração. "
                f"Recuperei {len(sources)} contratos relevantes, mas não consigo gerar a resposta."
            )
            return answer, sources

        if hasattr(model, "predict"):
            answer = model.predict(
                prompt,
                max_new_tokens=max_new_tokens,
                temperature=temperature,
                do_sample=temperature > 0,
            )
        else:
            answer = model.generate(
                prompt,
                max_new_tokens=max_new_tokens,
                temperature=temperature,
                do_sample=temperature > 0,
            )
        if not answer or not answer.strip():
            answer = "Não consegui gerar uma resposta com base nos contratos recuperados."
        answer = answer.strip()
        # Validação anti-alucinação: assinala entidades/valores não fundamentados.
        try:
            from api import ontology_service as ontology

            validation = ontology.validate_answer(answer, question=question, context=ontology_context)
            if not validation["supported"] or validation["score"] < 1.0:
                warnings = [
                    f"[aviso] {check['message']}" for check in validation["checks"] if check["status"] != "ok"
                ]
                if warnings:
                    answer = answer + "\n\nValidação da ontologia:\n" + "\n".join(warnings)
        except Exception:
            pass
        return answer, sources
    except Exception as exc:
        return (
            f"Erro ao gerar resposta: {exc}. Recuperei {len(sources)} contratos relevantes.",
            sources,
        )
