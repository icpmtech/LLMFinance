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

from api import elasticsearch_client as es_client  # noqa: E402
from api import main as api_main  # noqa: E402


class _ClienteFalso:
    """Cliente ES mínimo: devolve os documentos que lhe derem e guarda a consulta."""

    def __init__(self, documentos: list) -> None:
        self.documentos = documentos
        self.consultas: list = []

    def search(self, index: str, body: dict) -> dict:
        self.consultas.append(body)
        return {
            "hits": {
                "total": {"value": len(self.documentos)},
                "hits": [{"_source": doc} for doc in self.documentos],
            }
        }


def test_pesquisa_de_precos_exclui_documentos_sem_data() -> None:
    """O índice tem documentos «stub» (tudo a `null`, sem `date`).

    Foi um deles que fez a rota rebentar: o modelo exige `date` e a validação
    falhava com `points.0.date Input should be a valid string (input_value=None)`.
    """
    cliente = _ClienteFalso(
        [
            {"ticker": "SPCX", "date": "2026-10-01", "close": 10.5},
            {"ticker": "SPCX", "date": None, "close": None, "period": "1y"},
        ]
    )

    resultado = es_client.search_prices("SPCX", es=cliente)

    assert [ponto["date"] for ponto in resultado["points"]] == ["2026-10-01"]
    # E os stubs nem chegam a vir do índice: a consulta filtra-os.
    filtros = cliente.consultas[0]["query"]["bool"]["must"]
    assert {"exists": {"field": "date"}} in filtros


def test_escrita_de_precos_nao_indexa_linha_sem_data(monkeypatch: pytest.MonkeyPatch) -> None:
    """Uma linha sem `date` gerava `_id="TICKER-None"` — o stub que nos caiu em cima."""
    escritos: Dict[str, Any] = {}

    def _bulk(cliente: Any, acoes: list, **_kwargs: Any) -> tuple:
        escritos["acoes"] = acoes
        return len(acoes), []

    monkeypatch.setattr("api.elasticsearch_client.ensure_indices", lambda *_: None)
    monkeypatch.setattr("api.elasticsearch_client.bulk", _bulk)

    resultado = es_client.index_price_points(
        "SPCX",
        [
            {"date": "2026-10-01", "close": 10.5},
            {"date": None, "close": None},
        ],
        # O cliente não chega a ser usado: `ensure_indices` e `bulk` estão trocados.
        es=object(),
    )

    assert resultado["indexed_count"] == 1
    assert len(escritos["acoes"]) == 1
    assert escritos["acoes"][0]["date"] == "2026-10-01"


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
                {"ticker": ticker, "date": "2026-10-01", "close": 10.5},
                {"ticker": ticker, "date": "2026-10-02", "close": 10.8},
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
