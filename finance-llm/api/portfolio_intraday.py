"""Observed minute bars, poll samples and a server-configured external quote adapter."""
from __future__ import annotations

import math
import os
import base64
import json
import binascii
from datetime import datetime, timezone
from urllib.parse import urlparse

import pandas as pd
import requests

from api import portfolio_forecast_store as store
from forecasting.market_series import load_market_series, serialize_date
from forecasting.trading_signals import intraday_signal, technical_indicators


def _point(hit: dict) -> dict:
    doc = hit["_source"]
    return {
        "date": doc["target_key"], "value": doc["actual"], "source_date": doc["reference_date"],
        "completed": doc["status"] == "completed", "signal": doc.get("signal"),
    }


def intraday_history(
    owner_id: str, scope_id: str, ticker: str, mode: str, prepost: bool,
    start: str | None = None, end: str | None = None, cursor: str | None = None,
    limit: int = 390,
) -> dict:
    if not 1 <= limit <= 390:
        raise ValueError("Limite de pontos deve estar entre 1 e 390.")
    after = None
    bounds = {}
    for key, value in (("gte", start), ("lte", end)):
        if value:
            stamp = pd.Timestamp(value)
            if pd.isna(stamp):
                raise ValueError("Data invalida.")
            stamp = stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")
            bounds[key] = stamp.isoformat()
    if "gte" in bounds and "lte" in bounds and bounds["gte"] > bounds["lte"]:
        raise ValueError("Inicio deve ser anterior ao fim.")
    if cursor:
        try:
            after = json.loads(base64.urlsafe_b64decode(cursor).decode())
            if not isinstance(after, list) or len(after) != 2 or any(not isinstance(item, (str, int)) for item in after):
                raise ValueError("Invalid cursor.")
        except (ValueError, UnicodeDecodeError, binascii.Error) as exc:
            raise ValueError("Cursor intradiario invalido.") from exc
    kind = {"bars": "minute", "samples": "sample", "provider": "provider"}[mode]
    filters = store._filters(owner_id, scope_id, ticker, "1m", prepost) + [{"term": {"kind": kind}}]
    if bounds:
        filters.append({"range": {"target_date": bounds}})
    body = {
        "size": limit + 1, "track_total_hits": True, "query": {"bool": {"filter": filters}},
        "sort": [{"target_date": "desc"}, {"sort_id": "desc"}],
    }
    if after is not None:
        body["search_after"] = after
    client = store._client()
    result = client.search(index=store.INDEX, body=body)
    hits = result["hits"]["hits"]
    has_more = len(hits) > limit
    hits = hits[:limit]
    latest = hits[0]["_source"] if hits else {}
    return {
        "mode": mode, "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source_date": latest.get("reference_date"), "source": latest.get("source", "Elasticsearch"),
        "currency": latest.get("currency"), "age_seconds": None, "poll_seconds": 15, "index": store.INDEX,
        "points": [_point(hit) for hit in reversed(hits)],
        "total": result["hits"]["total"]["value"],
        "next_cursor": base64.urlsafe_b64encode(json.dumps(hits[-1]["sort"]).encode()).decode() if has_more else None,
        "notice": "Historico persistido: leitura do Elasticsearch, sem consultar o fornecedor nem recalcular sinais.",
    }


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
        "points": [_point(hit) for hit in reversed(result["hits"]["hits"])],
        "notice": "Consulta de 15 em 15 s, nao tick-a-tick. "
                  + ("Amostras da consulta: o mesmo preco da fonte pode repetir-se." if mode == "samples"
                     else "Latencia e cobertura dependem do fornecedor; timestamps originais preservados."),
    }
