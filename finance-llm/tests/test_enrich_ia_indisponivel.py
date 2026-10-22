"""O enriquecimento não pode rebentar quando o fornecedor de IA falha.

Um `402 Insufficient Balance` do fornecedor saía como `500 Internal Server Error`
com o rasto todo no log: a rota `/entities/{nif}/enrich` só sabe mapear
`result["error"]`, e a exceção subia de dentro da extração estruturada.
"""
from __future__ import annotations

import asyncio

from api import entity_enrichment_service as service


def _backend_cloud() -> dict:
    return {
        "kind": "cloud",
        "provider": "deepseek",
        "model": "deepseek-chat",
        "api_key": "chave-de-teste",
        "spec": {},
    }


def test_fornecedor_sem_saldo_devolve_nota_em_vez_de_rebentar(monkeypatch) -> None:
    monkeypatch.setattr(service, "available_backend", lambda *a, **k: _backend_cloud())

    async def _falha(*args, **kwargs):
        raise RuntimeError("Erro de DeepSeek (402). Insufficient Balance")

    monkeypatch.setattr(service, "ask_model", _falha)

    facts = asyncio.run(
        service._ask_structured_fields("Empresa X", [], "500000000", session=None, page_texts=[])
    )

    assert facts["nif"] == "500000000"
    assert facts["status"] == "unknown"
    assert facts["notes"], "a nota tem de explicar que a extração por IA falhou"
    assert "indisponível" in facts["notes"][0].lower()


def test_resposta_sem_json_continua_a_devolver_os_campos_vazios(monkeypatch) -> None:
    monkeypatch.setattr(service, "available_backend", lambda *a, **k: _backend_cloud())

    async def _texto(*args, **kwargs):
        return "não consegui extrair nada"

    monkeypatch.setattr(service, "ask_model", _texto)

    facts = asyncio.run(
        service._ask_structured_fields("Empresa Y", [], "500000001", session=None, page_texts=[])
    )

    assert facts["nif"] == "500000001"
    assert facts["notes"] == []
