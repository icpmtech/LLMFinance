"""Benchmark interno das funções da área de administração.

Corrido dentro do container backend (PYTHONPATH=/app) para medir o tempo das
funções sem HTTP, auth ou rede de frontend.  Usa um pedido de admin fictício
com os campos mínimos exigidos pelas dependências FastAPI.
"""
from __future__ import annotations

import statistics
import time
from dataclasses import dataclass
from typing import Any, Callable

import sys
sys.path.insert(0, "/app")

from api import auth_service as auth  # noqa: E402
from api import events_service as events  # noqa: E402
from api.admin_routes import _elastic_info, admin_overview  # noqa: E402


@dataclass
class FakeSession:
    user: Any


def fake_admin_session():
    me = auth.get_user_by_email("mouro.martins@gmail.com")
    if not me:
        me = auth.list_users(limit=1)[0]
    return FakeSession(user=me)


def measure(label: str, fn: Callable[[], Any], runs: int = 3) -> dict:
    times = []
    for _ in range(runs):
        t0 = time.perf_counter()
        try:
            fn()
        except Exception as exc:
            return {"label": label, "error": str(exc)}
        times.append(time.perf_counter() - t0)
    return {
        "label": label,
        "runs": runs,
        "min_ms": min(times) * 1000,
        "max_ms": max(times) * 1000,
        "mean_ms": statistics.mean(times) * 1000,
        "median_ms": statistics.median(times) * 1000,
    }


def main() -> None:
    session = fake_admin_session()
    # aquecer caches
    try:
        admin_overview(session)
    except Exception as exc:
        print("warmup error:", exc)

    tasks = [
        ("admin_overview", lambda: admin_overview(session)),
        ("_elastic_info", _elastic_info),
        ("auth.stats", auth.stats),
        ("auth.user_role_status_counts", auth.user_role_status_counts),
        ("auth.list_users(200)", lambda: auth.list_users(limit=200)),
        ("events.event_stats(24h)", lambda: events.event_stats(hours=24)),
        ("events.list_log_files", events.list_log_files),
    ]

    results = []
    for label, fn in tasks:
        results.append(measure(label, fn, runs=3))

    print(f"{'function':30} {'min':>8} {'max':>8} {'mean':>8} {'median':>8}")
    for r in results:
        if "error" in r:
            print(f"{r['label']:30} ERRO: {r['error']}")
        else:
            print(
                f"{r['label']:30} {r['min_ms']:8.1f} {r['max_ms']:8.1f} "
                f"{r['mean_ms']:8.1f} {r['median_ms']:8.1f}"
            )


if __name__ == "__main__":
    main()
