"""Observed minute bars, poll samples and a server-configured external quote adapter."""
from __future__ import annotations

import math
import os
from datetime import datetime, timezone
from urllib.parse import urlparse

import pandas as pd
import requests

from api import portfolio_forecast_store as store
from forecasting.market_series import load_market_series, serialize_date
from forecasting.trading_signals import intraday_signal, technical_indicators


def _external_quote(ticker: str) -> dict:
    endpoint = os.getenv("PORTFOLIO_REALTIME_URL", "")
    if not endpoint:
        raise ValueError("Feed externo indisponivel: configure PORTFOLIO_REALTIME_URL no servidor.")
    parsed = urlparse(endpoint)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("PORTFOLIO_REALTIME_URL requer HTTPS sem credenciais no URL.")
    token = os.getenv("PORTFOLIO_REALTIME_TOKEN")
    response = requests.get(
        endpoint, params={"symbol": ticker},
        headers={"Authorization": f"Bearer {token}"} if token else {},
        timeout=10, allow_redirects=False,
    )
    if response.status_code != 200:
        raise RuntimeError(f"Fornecedor externo respondeu HTTP {response.status_code}.")
    payload = response.json()
    price = float(payload["price"])
    timestamp = pd.Timestamp(payload["timestamp"])
    if timestamp.tzinfo is None:
        raise ValueError("Timestamp do fornecedor deve incluir fuso horario.")
    age = (pd.Timestamp.now(tz="UTC") - timestamp.tz_convert("UTC")).total_seconds()
    if not math.isfinite(price) or price <= 0 or age < -60:
        raise ValueError("Preco ou timestamp invalido no feed externo.")
    return {
        "value": price, "source_date": timestamp.tz_convert("UTC").isoformat(),
        "currency": payload.get("currency"), "source": "Feed externo configurado",
        "age_seconds": max(0, int(age)),
    }


def intraday_points(owner_id: str, scope_id: str, ticker: str, mode: str, prepost: bool) -> dict:
    fetched = datetime.now(timezone.utc).isoformat()
    if mode == "provider":
        try:
            quote = _external_quote(ticker)
        except (KeyError, TypeError, ValueError, requests.RequestException) as exc:
            raise RuntimeError("Feed externo indisponivel ou resposta invalida; verifique a configuracao do fornecedor.") from exc
        bars = []
        market = {"source": quote["source"], "currency": quote["currency"]}
        client = store._client()
        previous = client.search(index=store.INDEX, body={
            "size": 100, "query": {"bool": {"filter": store._filters(owner_id, scope_id, ticker, "1m", prepost)
                + [{"term": {"kind": "provider"}}, {"range": {"target_date": {"lt": quote["source_date"]}}}]}},
            "sort": [{"target_date": "desc"}],
        })
        prices = pd.Series(
            [hit["_source"]["actual"] for hit in reversed(previous["hits"]["hits"])] + [quote["value"]],
            index=pd.DatetimeIndex(
                [hit["_source"]["target_key"] for hit in reversed(previous["hits"]["hits"])] + [quote["source_date"]]
            ),
        )
    else:
        observed = load_market_series(ticker, "1m", prepost)
        market = observed.metadata
        prices = observed.prices
        client = store._client()
        completed = set(observed.completed.index)
        bars = [{
            "date": serialize_date(date, "1m"), "value": float(value), "completed": date in completed,
            "source_date": serialize_date(date, "1m"),
        } for date, value in observed.prices.tail(390).items()]
        quote = {
            "value": bars[-1]["value"], "source_date": bars[-1]["date"],
            "currency": market.get("currency"), "source": market["source"],
            "age_seconds": market["delay_seconds"],
        }
    if not math.isfinite(quote["value"]) or quote["value"] <= 0:
        raise ValueError("Fonte devolveu preco invalido.")
    indicators = technical_indicators(prices)
    technical = {serialize_date(date, "1m"): values.to_dict() for date, values in indicators.iterrows()}
    base = {
        "owner_id": owner_id, "scope_id": scope_id, "ticker": ticker, "interval": "1m",
        "prepost": prepost, "version": store.VERSION,
    }
    operations = []
    kind = {"bars": "minute", "samples": "sample", "provider": "provider"}[mode]
    points = bars if mode == "bars" else [{
        "date": quote["source_date"] if mode == "provider" else fetched,
        "value": quote["value"], "source_date": quote["source_date"], "completed": False,
    }]
    for point in points:
        values = technical.get(point["source_date"], {})
        signal = intraday_signal(
            values, provisional=not point["completed"],
            stale=(mode != "bars" or point["date"] == bars[-1]["date"]) and quote["age_seconds"] > 180,
        )
        doc_id = store._hash([base, kind, point["date"]])
        doc = {
            **base, "kind": kind, "target_date": point["date"], "target_key": point["date"],
            "sort_id": doc_id, "recorded_at": fetched, "actual": point["value"],
            "reference_date": point["source_date"], "source": quote["source"],
            "currency": quote["currency"], "status": "completed" if point["completed"] else "partial",
            "signal": signal,
        }
        if mode == "bars":
            operations.append({
                "_op_type": "update", "_index": store.INDEX, "_id": doc_id, "scripted_upsert": True,
                "script": {
                    "lang": "painless",
                    "source": "if (ctx.op == 'create' || ctx._source.status != 'completed') { ctx._source = params.doc; } else if (ctx._source.signal == null) { ctx._source.signal = params.doc.signal; } else { ctx.op = 'noop'; }",
                    "params": {"doc": doc},
                }, "upsert": {},
            })
        else:
            operations.append({"_op_type": "create", "_index": store.INDEX, "_id": doc_id, "_source": doc})
    store._write(client, operations)
    result = client.search(index=store.INDEX, body={
        "size": 390, "query": {"bool": {"filter": store._filters(owner_id, scope_id, ticker, "1m", prepost)
                                                    + [{"term": {"kind": kind}}]}},
        "sort": [{"target_date": "desc"}],
    })
    return {
        "mode": mode, "fetched_at": fetched, "source_date": quote["source_date"],
        "source": quote["source"], "currency": quote["currency"], "age_seconds": quote["age_seconds"],
        "poll_seconds": 15, "index": store.INDEX,
        "points": [{
            "date": hit["_source"]["target_key"], "value": hit["_source"]["actual"],
            "source_date": hit["_source"]["reference_date"], "completed": hit["_source"]["status"] == "completed",
            "signal": hit["_source"].get("signal"),
        } for hit in reversed(result["hits"]["hits"])],
        "notice": "Consulta de 15 em 15 s, nao tick-a-tick. "
                  + ("Amostras da consulta: o mesmo preco da fonte pode repetir-se." if mode == "samples"
                     else "Latencia e cobertura dependem do fornecedor; timestamps originais preservados."),
    }
