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
