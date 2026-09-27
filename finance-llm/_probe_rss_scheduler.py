"""Sonda: confirmar que o agendador do leitor dispara o job (cron de 1 minuto).

Não recolhe nada a sério: substitui `refresh_all` por um contador e repõe a
agenda original no fim.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api import rss_scheduler  # noqa: E402
from api import rss_service as service  # noqa: E402
from api import rss_store as store  # noqa: E402

original = store.settings()
print("agenda original:", original["cron"], original["timezone"])

calls: list = []


def fake_refresh_all(**kwargs):
    calls.append(kwargs)
    return {"feeds": 0, "added": 0, "errors": 0, "items": []}


service.refresh_all = fake_refresh_all  # type: ignore[assignment]

print("a guardar cron de teste (*/1 * * * *) …")
store.save_settings({"cron": "*/1 * * * *", "auto_fetch": True, "timezone": "Europe/Lisbon"})
state = rss_scheduler.start()
print("estado:", {k: state.get(k) for k in ("running", "scheduled", "cron", "next_run_at", "error")})

if not state.get("running"):
    print("RESULTADO: agendador não arrancou.")
else:
    deadline = time.time() + 80
    while time.time() < deadline and not calls:
        time.sleep(2)
    print("chamadas ao refresh_all:", len(calls), calls[:1])
    print("RESULTADO:", "DISPAROU" if calls else "NÃO DISPAROU em 80 s")

print("a repor a agenda original …", store.save_settings({"cron": original["cron"], "timezone": original["timezone"]})["cron"])
rss_scheduler.shutdown()
