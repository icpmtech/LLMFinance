"""Regressão: a rota `/elastic/search/prices/{ticker}` tem de devolver o resultado.

O que aconteceu: a rota estava declarada como **síncrona** (`def`) e fazia
`return search_ticker_prices(...)`, que é `async` — devolvia a **corrotina** e o
FastAPI rebentava só na validação da resposta:

    ResponseValidationError: Input should be a valid dictionary or object to
    extract fields from   (input: <coroutine object …>)
    RuntimeWarning: coroutine 'search_ticker_prices' was never awaited

O erro aponta para a serialização e não para a chamada, pelo que o teste aqui
verifica as duas pontas: a forma da resposta **e** o facto de o handler ser
`async` (é o que obriga ao `await`).
"""
from __future__ import annotations

import inspect
import sys
from typing import Any, Dict

import pytest

sys.path.insert(0, "c:/LLMFinance/finance-llm")

from fastapi.testclient import TestClient  # noqa: E402

from api import main as api_main  # noqa: E402


def test_handler_de_precos_e_async() -> None:
    """Sem `async def` não há `await` e a rota devolve a corrotina."""
    for rota in api_main.app.routes:
        if getattr(rota, "path", "") == "/elastic/search/prices/{ticker}":
            assert inspect.iscoroutinefunction(rota.endpoint), (
                "o handler de preços tem de ser `async def` — é o que o obriga a aguardar "
                "`search_ticker_prices()` antes de devolver"
            )
            return
    pytest.fail("rota /elastic/search/prices/{ticker} não encontrada")


def test_rota_de_precos_devolve_o_resultado(monkeypatch: pytest.MonkeyPatch) -> None:
    """A rota devolve o dicionário do serviço, não a corrotina."""
    chamadas: Dict[str, Any] = {}

    def _search_prices(ticker: str, start: Any = None, end: Any = None, size: int = 1000, es: Any = None) -> Dict[str, Any]:
        chamadas.update({"ticker": ticker, "start": start, "end": end, "size": size})
        return {
            "ticker": ticker,
            "total": 2,
            "points": [
                {"date": "2026-10-01", "close": 10.5},
                {"date": "2026-10-02", "close": 10.8},
            ],
        }

    monkeypatch.setattr("api.elasticsearch_client.search_prices", _search_prices)

    cliente = TestClient(api_main.app, base_url="http://prova")
    resposta = cliente.get("/elastic/search/prices/spcx?size=50&start_date=2026-01-01")

    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["ticker"] == "SPCX"
    assert corpo["total"] == 2
    assert len(corpo["points"]) == 2
    # O ticker é normalizado a maiúsculas e os filtros chegam ao serviço.
    assert chamadas["ticker"] == "SPCX"
    assert chamadas["size"] == 50
    assert chamadas["start"] == "2026-01-01"
