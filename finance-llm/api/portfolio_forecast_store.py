"""Immutable forecast snapshots and completed-bar evaluation, isolated by account."""
from __future__ import annotations

import hashlib
import json
import base64
from datetime import datetime, timezone
from typing import Any

import pandas as pd
from elasticsearch import BadRequestError
from elasticsearch.helpers import bulk

from api.es.core import get_es_client

INDEX = "finance_portfolio_forecast_points"
VERSION = 1
PRICE_TOLERANCE_PCT = 1.0
DIRECTION_FLAT_PCT = 0.2


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def _client():
    client = get_es_client()
    if client is None:
        raise RuntimeError("Elasticsearch indisponivel; simulacao nao guardada.")
    if not client.indices.exists(index=INDEX):
        keywords = ("owner_id", "scope_id", "ticker", "interval", "kind", "status", "run_id", "target_key", "sort_id")
        numbers = ("predicted", "reference_price", "actual", "absolute_error", "error_pct", "actual_return_pct", "predicted_return_pct")
        mapping = {
            "dynamic": "strict",
            "properties": {
                **{key: {"type": "keyword"} for key in keywords},
                **{key: {"type": "double"} for key in numbers},
                **{key: {"type": "date"} for key in ("recorded_at", "reference_date", "target_date", "evaluated_at")},
                **{key: {"type": "boolean"} for key in ("prepost", "direction_hit", "price_hit")},
                "config": {"type": "object", "enabled": False},
                "signal": {"type": "object", "enabled": False},
                "source": {"type": "keyword"},
                "currency": {"type": "keyword"},
                "version": {"type": "integer"},
            },
        }
        try:
            client.indices.create(index=INDEX, mappings=mapping)
        except BadRequestError as exc:
            if exc.error != "resource_already_exists_exception":
                raise
    return client


def _filters(owner_id: str, scope_id: str, ticker: str, interval: str, prepost: bool) -> list:
    return [{"term": {key: value}} for key, value in {
        "owner_id": owner_id, "scope_id": scope_id, "ticker": ticker,
        "interval": interval, "prepost": prepost if interval in {"1m", "1h"} else False,
    }.items()]


def _key(date: str, interval: str) -> str:
    stamp = pd.Timestamp(date)
    if interval in {"1m", "1h"}:
        stamp = stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")
        return stamp.isoformat()
    return str(stamp.date())


def evaluate(predicted: float, actual: float, reference: float) -> dict:
    predicted_return = (predicted / reference - 1) * 100
    actual_return = (actual / reference - 1) * 100

    def direction(value: float) -> int:
        return 0 if abs(value) <= DIRECTION_FLAT_PCT else (1 if value > 0 else -1)

    error = abs(actual - predicted)
    error_pct = error / actual * 100
    return {
        "actual": actual, "absolute_error": error, "error_pct": error_pct,
        "actual_return_pct": actual_return, "predicted_return_pct": predicted_return,
        "price_hit": error_pct <= PRICE_TOLERANCE_PCT,
        "direction_hit": direction(predicted_return) == direction(actual_return),
        "status": "evaluated", "evaluated_at": _now(),
    }


def _write(client, operations: list) -> None:
    if not operations:
        return
    # Conflicting creates are intentional deduplication; all other failures are surfaced.
    _, errors = bulk(client, operations, raise_on_error=False)
    failures = [item for item in errors if not (
        "create" in item and item["create"].get("status") == 409
    )]
    if failures:
        raise RuntimeError(f"Elasticsearch: {len(failures)} pontos nao guardados.")
    client.indices.refresh(index=INDEX)


def record_forecast(owner_id: str, scope_id: str, result: dict, config: dict) -> dict:
    client = _client()
    interval = result.get("interval", config["interval"])
    ticker = result["ticker"]
    market = result.get("market") or {}
    prepost = bool(config.get("prepost")) if interval in {"1m", "1h"} else False
    base = {
        "owner_id": owner_id, "scope_id": scope_id, "ticker": ticker,
        "interval": interval, "prepost": prepost, "version": VERSION,
    }
    recorded_at = _now()
    history = [point for point in result["series"] if isinstance(point.get("value"), (float, int))]
    if not history:
        raise ValueError("Sem serie real para guardar a simulacao.")
    completed = history[:-1] if market.get("partial_bar") else history
    actuals = {_key(point["date"], interval): float(point["value"]) for point in completed}
    run_id = _hash({
        **base, "config": config, "forecast": result["forecast"], "backtest": result.get("backtest"),
        "trading": result.get("trading"), "last": history[-1], "selected_order": result.get("order"),
    })
    saved_config = {
        **config, "selected_order": result.get("order"), "recommended_model": result.get("recommended_model"),
        "rmse": result.get("rmse"), "mape": result.get("mape"), "market": market,
    }
    operations = []
    for point in history:
        key = _key(point["date"], interval)
        doc_id = _hash([base, "real", key])
        doc = {
            **base, "kind": "real", "target_date": key, "target_key": key, "sort_id": doc_id,
            "actual": point["value"], "recorded_at": recorded_at,
            "status": "completed" if key in actuals else "partial",
            "source": market.get("source"), "currency": result.get("currency"),
        }
        operations.append({
            "_op_type": "update", "_index": INDEX, "_id": doc_id,
            "scripted_upsert": True,
            "script": {
                "lang": "painless",
                "source": "if (ctx.op == 'create' || ctx._source.status != 'completed') { ctx._source = params.doc; } else { ctx.op = 'noop'; }",
                "params": {"doc": doc},
            },
            "upsert": {},
        })
    signals = {
        _key(point["date"], interval): point for point in (result.get("trading") or {}).get("signals", [])
    }
    reference = history[-1]
    for kind, points in (("forecast", result["forecast"]), ("backtest", result.get("backtest", []))):
        for point in points:
            key = _key(point["date"], interval)
            if kind == "forecast":
                reference_date, reference_price = _key(reference["date"], interval), reference["value"]
            else:
                position = next(i for i, item in enumerate(completed) if _key(item["date"], interval) == key)
                previous = completed[position - 1]
                reference_date, reference_price = _key(previous["date"], interval), point["baseline"]
            doc_id = _hash([run_id, kind, key])
            target_time = pd.Timestamp(key)
            target_time = target_time.tz_localize("UTC") if target_time.tzinfo is None else target_time
            doc = {
                **base, "kind": kind, "run_id": run_id, "config": {**saved_config, "original_point": point},
                "sort_id": doc_id, "target_date": key, "target_key": key, "recorded_at": recorded_at,
                "reference_date": reference_date, "reference_price": reference_price,
                "predicted": point["price"], "currency": result.get("currency"),
                "status": "pending" if target_time > pd.Timestamp(recorded_at)
                else "not_eligible",
                "signal": signals.get(reference_date),
            }
            if kind == "backtest":
                doc.update(evaluate(point["price"], point["actual"], reference_price))
            operations.append({"_op_type": "create", "_index": INDEX, "_id": doc_id, "_source": doc})
    for signal_date, signal in signals.items():
        target = signal.get("execution_date")
        if target is None:
            target = next((point["date"] for point in history if _key(point["date"], interval) > signal_date),
                          result["forecast"][0]["date"])
        target = _key(target, interval)
        doc_id = _hash([run_id, "signal", signal_date])
        target_time = pd.Timestamp(target)
        target_time = target_time.tz_localize("UTC") if target_time.tzinfo is None else target_time
        doc = {
            **base, "kind": "signal", "run_id": run_id, "config": saved_config,
            "sort_id": doc_id, "recorded_at": recorded_at, "target_date": target, "target_key": target,
            "reference_date": signal_date, "reference_price": signal["price"],
            "predicted": signal["prediction"], "signal": signal, "currency": result.get("currency"),
            "status": "pending" if target_time > pd.Timestamp(recorded_at) else "not_eligible",
        }
        # Historical signals stay retrospective; only the last unexecuted signal is live-eligible.
        if signal.get("execution_date"):
            doc["status"] = "not_eligible"
        operations.append({"_op_type": "create", "_index": INDEX, "_id": doc_id, "_source": doc})
    _write(client, operations)
    filters = _filters(owner_id, scope_id, ticker, interval, prepost)
    # Walk all pending snapshots, not just the first page. Never match approximate timestamps by position.
    after = None
    while actuals:
        body = {
            "size": 500,
            "query": {"bool": {"filter": filters + [
                {"terms": {"kind": ["forecast", "signal"]}}, {"term": {"status": "pending"}},
                {"range": {"target_date": {"lte": max(actuals)}}},
            ]}},
            "sort": [{"target_date": "asc"}, {"sort_id": "asc"}],
        }
        if after is not None:
            body["search_after"] = after
        hits = client.search(index=INDEX, body=body)["hits"]["hits"]
        if not hits:
            break
        real_ids = [_hash([base, "real", hit["_source"]["target_key"]]) for hit in hits]
        observations = client.mget(index=INDEX, ids=real_ids)["docs"]
        updates = []
        for hit, observation in zip(hits, observations):
            doc = hit["_source"]
            observed = observation.get("_source") or {}
            if observed.get("status") == "completed":
                actual = observed["actual"]
                evaluation = evaluate(doc["predicted"], actual, doc["reference_price"])
                updates.append({
                    "_op_type": "update", "_index": INDEX, "_id": hit["_id"],
                    "script": {
                        "lang": "painless",
                        "source": "if (ctx._source.status == 'pending') { ctx._source.putAll(params.evaluation); } else { ctx.op = 'noop'; }",
                        "params": {"evaluation": evaluation},
                    },
                })
        _write(client, updates)
        after = hits[-1]["sort"]
    return read_history(owner_id, scope_id, ticker, interval, prepost, client=client)


def read_history(
    owner_id: str, scope_id: str, ticker: str, interval: str, prepost: bool,
    offset: int = 0, limit: int = 100, kind: str = "forecast", cursor: str | None = None, client=None,
) -> dict:
    client = client if client is not None else _client()
    filters = _filters(owner_id, scope_id, ticker, interval, prepost)
    body = {
        "size": limit, "track_total_hits": True,
        "query": {"bool": {"filter": filters + [{"term": {"kind": kind}}]}},
        "sort": [{"recorded_at": "desc"}, {"target_date": "asc"}, {"sort_id": "asc"}],
        "aggs": {
            "evaluated": {"filter": {"term": {"status": "evaluated"}}, "aggs": {
                "direction_hits": {"filter": {"term": {"direction_hit": True}}},
                "price_hits": {"filter": {"term": {"price_hit": True}}},
            }},
            "pending": {"filter": {"term": {"status": "pending"}}},
            "not_eligible": {"filter": {"term": {"status": "not_eligible"}}},
        },
    }
    if cursor:
        try:
            after = json.loads(base64.urlsafe_b64decode(cursor).decode())
            if not isinstance(after, list) or len(after) != 3 or any(not isinstance(value, (str, int)) for value in after):
                raise ValueError("Invalid cursor shape.")
        except (ValueError, UnicodeDecodeError) as exc:
            raise ValueError("Cursor de paginacao invalido.") from exc
        body["search_after"] = after
    elif offset:
        raise ValueError("Cursor necessario para paginas seguintes.")
    response = client.search(index=INDEX, body=body)
    real = client.search(index=INDEX, body={
        "size": 500, "query": {"bool": {"filter": filters + [{"term": {"kind": "real"}}]}},
        "sort": [{"target_date": "desc"}],
    })
    aggregations = response["aggregations"]
    evaluated = aggregations["evaluated"]
    total = response["hits"]["total"]["value"]
    hits = response["hits"]["hits"]
    has_more = offset + len(hits) < total
    return {
        "index": INDEX, "kind": kind, "total": total, "offset": offset,
        "next_offset": offset + len(hits) if has_more else None,
        "next_cursor": base64.urlsafe_b64encode(json.dumps(hits[-1]["sort"]).encode()).decode() if has_more and hits else None,
        "items": [{"id": hit["_id"], **{key: value for key, value in hit["_source"].items() if key != "owner_id"}}
                  for hit in response["hits"]["hits"]],
        "real_series": [{"date": hit["_source"]["target_key"], "value": hit["_source"]["actual"],
                         "completed": hit["_source"]["status"] == "completed"}
                        for hit in reversed(real["hits"]["hits"])],
        "evaluated": evaluated["doc_count"],
        "direction_hits": evaluated["direction_hits"]["doc_count"],
        "price_hits": evaluated["price_hits"]["doc_count"],
        "pending": aggregations["pending"]["doc_count"],
        "not_eligible": aggregations["not_eligible"]["doc_count"],
        "price_tolerance_pct": PRICE_TOLERANCE_PCT, "direction_flat_pct": DIRECTION_FLAT_PCT,
    }
