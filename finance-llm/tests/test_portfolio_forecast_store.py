from copy import deepcopy
import base64
import json
import os
import uuid
from unittest.mock import Mock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import portfolio_forecast_store as store, portfolio_routes as routes
from api.auth_routes import optional_session
from types import SimpleNamespace


def forecast(partial=False):
    return {
        "ticker": "AAA", "interval": "1h", "currency": "USD", "order": [1, 0, 1],
        "market": {"partial_bar": partial, "source": "test"},
        "series": [
            {"date": "2026-01-01T10:00:00+00:00", "value": 100},
            {"date": "2026-01-01T11:00:00+00:00", "value": 101},
        ],
        "forecast": [{"date": "2026-01-01T12:00:00+00:00", "price": 102, "lower": 99, "upper": 105}],
        "backtest": [{"date": "2026-01-01T11:00:00+00:00", "price": 100.5, "baseline": 100, "actual": 101}] if not partial else [],
    }


CONFIG = {"interval": "1h", "prepost": True, "train_window": 60}


def test_price_and_direction_outcomes_are_independent():
    # Correct price within 1%, but predicted down and observed up.
    result = store.evaluate(99.6, 100.4, 100)
    assert result["price_hit"] is True
    assert result["direction_hit"] is False
    # Correct direction, but a large price error.
    result = store.evaluate(110, 102, 100)
    assert result["direction_hit"] is True
    assert result["price_hit"] is False
    assert store.evaluate(100, 100, 100)["direction_hit"] is True


def test_records_are_immutable_deduplicated_and_keep_historical_evaluation_separate():
    client = Mock()
    client.search.return_value = {"hits": {"hits": []}}
    writes = []
    with (
        patch.object(store, "_client", return_value=client),
        patch.object(store, "_now", return_value="2026-01-01T11:05:00+00:00"),
        patch.object(store, "_write", side_effect=lambda _, docs: writes.extend(deepcopy(docs))),
        patch.object(store, "read_history", return_value={"total": 1}),
    ):
        store.record_forecast("owner-a", "portfolio:p1", forecast(), CONFIG)
        store.record_forecast("owner-a", "portfolio:p1", forecast(), CONFIG)
    creates = [op for op in writes if op["_op_type"] == "create"]
    assert creates[0]["_id"] == creates[2]["_id"]
    assert creates[0]["_source"]["status"] == "pending"
    assert creates[0]["_source"]["predicted"] == 102
    assert creates[0]["_source"]["config"]["selected_order"] == [1, 0, 1]
    assert creates[0]["_source"]["config"]["original_point"]["lower"] == 99
    assert creates[1]["_source"]["kind"] == "backtest"
    assert creates[1]["_source"]["status"] == "evaluated"
    for op in creates:
        assert op["_source"]["owner_id"] == "owner-a"
        assert op["_source"]["scope_id"] == "portfolio:p1"


def test_completed_bar_evaluates_original_prediction_not_new_forecast():
    client = Mock()
    original = {
        "target_key": "2026-01-01T11:00:00+00:00", "predicted": 103, "reference_price": 100,
    }
    client.search.side_effect = [
        {"hits": {"hits": [{"_id": "original", "_source": original, "sort": ["2026-01-01", "original"]}]}},
        {"hits": {"hits": []}},
    ]
    client.mget.return_value = {"docs": [{"_source": {"status": "completed", "actual": 101}}]}
    writes = []
    with (
        patch.object(store, "_client", return_value=client),
        patch.object(store, "_now", return_value="2026-01-01T11:05:00+00:00"),
        patch.object(store, "_write", side_effect=lambda _, docs: writes.extend(deepcopy(docs))),
        patch.object(store, "read_history", return_value={}),
    ):
        store.record_forecast("owner-a", "default", forecast(), CONFIG)
    update = next(op for op in writes if op["_id"] == "original")
    evaluation = update["script"]["params"]["evaluation"]
    assert evaluation["absolute_error"] == 2
    assert evaluation["price_hit"] is False
    assert "predicted" not in evaluation
    assert client.search.call_args_list[1].kwargs["body"]["search_after"] == ["2026-01-01", "original"]


def test_partial_real_bar_never_scores_a_prediction():
    client = Mock()
    client.search.side_effect = [
        {"hits": {"hits": [{"_id": "pending", "_source": {
            "target_key": "2026-01-01T11:00:00+00:00", "predicted": 102, "reference_price": 100,
        }, "sort": ["2026-01-01", "pending"]}]}},
        {"hits": {"hits": []}},
    ]
    client.mget.return_value = {"docs": [{"_source": {"status": "partial", "actual": 101}}]}
    writes = []
    with (
        patch.object(store, "_client", return_value=client),
        patch.object(store, "_write", side_effect=lambda _, docs: writes.extend(docs)),
        patch.object(store, "read_history", return_value={}),
    ):
        store.record_forecast("owner-a", "default", forecast(True), CONFIG)
    assert not any(op["_id"] == "pending" for op in writes)
    real = [op for op in writes if op["_op_type"] == "update"]
    assert real[-1]["script"]["params"]["doc"]["status"] == "partial"


def test_scopes_and_sessions_have_distinct_ids_and_all_reads_filter_owner():
    client = Mock()
    client.search.return_value = {"hits": {"hits": []}}
    ids = []
    with (
        patch.object(store, "_client", return_value=client),
        patch.object(store, "_write", side_effect=lambda _, docs: ids.append(docs[0]["_id"])),
        patch.object(store, "read_history", return_value={}),
    ):
        for owner, scope, prepost in [
            ("a", "p1", True), ("b", "p1", True), ("a", "p2", True), ("a", "p1", False),
        ]:
            store.record_forecast(owner, scope, forecast(), {**CONFIG, "prepost": prepost})
    assert len(set(ids)) == 4
    for call in client.search.call_args_list:
        filters = call.kwargs["body"]["query"]["bool"]["filter"]
        assert any("owner_id" in item.get("term", {}) for item in filters)
        assert any("scope_id" in item.get("term", {}) for item in filters)


def test_bulk_only_ignores_duplicate_creates_not_update_conflicts():
    with patch.object(store, "bulk", return_value=(0, [{"create": {"status": 409}}])):
        store._write(Mock(), [{}])
    with patch.object(store, "bulk", return_value=(0, [{"update": {"status": 409}}])):
        with pytest.raises(RuntimeError, match="nao guardados"):
            store._write(Mock(), [{}])


def test_missing_elasticsearch_is_an_explicit_failure():
    with patch.object(store, "get_es_client", return_value=None):
        with pytest.raises(RuntimeError, match="nao guardada"):
            store._client()


def test_history_cursor_reads_past_ten_thousand_without_es_from_limit():
    client = Mock()
    client.search.side_effect = [
        {
            "hits": {"total": {"value": 20000}, "hits": [
                {"_id": "point", "_source": {"kind": "forecast", "owner_id": "owner-a"}, "sort": [1, 2, "point"]},
            ]},
            "aggregations": {
                "evaluated": {"doc_count": 0, "direction_hits": {"doc_count": 0}, "price_hits": {"doc_count": 0}},
                "pending": {"doc_count": 20000}, "not_eligible": {"doc_count": 0},
            },
        },
        {"hits": {"hits": []}},
    ]
    cursor = base64.urlsafe_b64encode(json.dumps([0, 1, "previous"]).encode()).decode()
    result = store.read_history("owner-a", "default", "AAA", "1h", True, 10000, 1, cursor=cursor, client=client)
    body = client.search.call_args_list[0].kwargs["body"]
    assert "from" not in body
    assert body["search_after"] == [0, 1, "previous"]
    assert result["next_offset"] == 10001
    assert result["next_cursor"]
    assert "owner_id" not in result["items"][0]
    with pytest.raises(ValueError, match="invalido"):
        store.read_history("owner-a", "default", "AAA", "1h", True, cursor="bad cursor", client=client)


def api_client(session):
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[optional_session] = lambda: session
    return TestClient(app)


def test_history_requires_auth_and_rejects_foreign_portfolio():
    assert api_client(None).get("/portfolio/forecast/history?ticker=AAA").status_code == 401
    session = SimpleNamespace(user=SimpleNamespace(id="owner-a"))
    with patch.object(routes.portfolio_store, "get_portfolio", return_value=None):
        response = api_client(session).get("/portfolio/forecast/history?ticker=AAA&portfolio_id=foreign")
    assert response.status_code == 404


def test_history_uses_session_owner_and_validates_pagination_and_kind():
    session = SimpleNamespace(user=SimpleNamespace(id="owner-a"))
    with patch.object(store, "read_history", return_value={"total": 1}) as read:
        client = api_client(session)
        assert client.get("/portfolio/forecast/history?ticker=AAA&interval=1h&offset=100&kind=backtest").status_code == 200
        assert read.call_args.args == ("owner-a", "default", "AAA", "1h", True, 100, 100, "backtest", None)
        assert client.get("/portfolio/forecast/history?ticker=AAA&offset=-1").status_code == 422
        assert client.get("/portfolio/forecast/history?ticker=AAA&kind=anything").status_code == 422


def test_forecast_save_failure_keeps_prices_but_surfaces_explicit_error():
    session = SimpleNamespace(user=SimpleNamespace(id="owner-a"))
    with (
        patch.object(routes.portfolio_service, "portfolio_forecast", return_value={"forecasts": [forecast()]}),
        patch.object(store, "record_forecast", side_effect=RuntimeError("ES offline")),
    ):
        response = api_client(session).post("/portfolio/forecast", json={"tickers": ["AAA"]})
    assert response.status_code == 200
    point = response.json()["forecasts"][0]
    assert point["forecast"][0]["price"] == 102
    assert "ES offline" in point["persistence"]["error"]


@pytest.mark.skipif(os.getenv("FORECAST_STORE_INTEGRATION") != "1", reason="Requires local Elasticsearch")
def test_real_elasticsearch_durability_partial_bars_and_immutable_evaluation():
    owner = f"forecast-store-test-{uuid.uuid4().hex}"
    client = store._client()
    initial = forecast()
    initial["series"] = initial["series"][:1]
    initial["forecast"] = [{"date": "2026-01-01T11:00:00+00:00", "price": 102}]
    initial["backtest"] = []
    try:
        with patch.object(store, "_now", return_value="2026-01-01T10:05:00+00:00"):
            first = store.record_forecast(owner, "test", initial, CONFIG)
        assert first["pending"] == 1
        point_id = first["items"][0]["id"]
        second = forecast(True)
        with patch.object(store, "_now", return_value="2026-01-01T11:05:00+00:00"):
            partial = store.record_forecast(owner, "test", second, CONFIG)
        assert partial["evaluated"] == 0
        second["market"]["partial_bar"] = False
        with patch.object(store, "_now", return_value="2026-01-01T12:05:00+00:00"):
            finished = store.record_forecast(owner, "test", second, CONFIG)
        point = next(row for row in finished["items"] if row["id"] == point_id)
        assert point["predicted"] == 102
        assert point["actual"] == 101
        assert point["direction_hit"] is True
        assert point["price_hit"] is True
        assert point["recorded_at"] == "2026-01-01T10:05:00+00:00"
        # A later revision must not rewrite either the original prediction or its first evaluation.
        second["series"][-1]["value"] = 110
        with patch.object(store, "_now", return_value="2026-01-01T13:05:00+00:00"):
            store.record_forecast(owner, "test", second, CONFIG)
            store.record_forecast(owner, "test", initial, CONFIG)
        loaded = store.read_history(owner, "test", "AAA", "1h", True, limit=1)
        assert loaded["next_cursor"]
        next_page = store.read_history(
            owner, "test", "AAA", "1h", True,
            offset=loaded["next_offset"], limit=1, cursor=loaded["next_cursor"],
        )
        assert next_page["items"][0]["id"] != loaded["items"][0]["id"]
        stored = client.get(index=store.INDEX, id=point_id)["_source"]
        assert stored["actual"] == 101
        assert stored["predicted"] == 102
        assert stored["recorded_at"] == "2026-01-01T10:05:00+00:00"
        assert store.read_history(owner, "other-scope", "AAA", "1h", True)["total"] == 0
        assert store.read_history(owner + "-foreign", "test", "AAA", "1h", True)["total"] == 0
        assert store.read_history(owner, "test", "AAA", "1h", False)["total"] == 0
    finally:
        client.delete_by_query(index=store.INDEX, query={"term": {"owner_id": owner}}, refresh=True)
