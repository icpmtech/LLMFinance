"""Verificação rápida das leituras do Simulador IQ OS contra o MiroFish a correr."""

from __future__ import annotations

import json

from api import mirofish_service as service

SIM = "sim_74e8c2c2682d"


def dump(label: str, payload: object, max_len: int = 1400) -> None:
    text = json.dumps(payload, ensure_ascii=False, default=str)
    print(f"\n=== {label} ===")
    print(text[:max_len] + (" …" if len(text) > max_len else ""))


catalog = service.runs(limit=5, enrich=3)
print("runs:", catalog["count"])
for item in catalog["runs"]:
    dump(
        "run",
        {
            "id": item["simulation_id"],
            "title": item["title"],
            "state": item["state"],
            "live": item["live"],
            "report": item["report"],
            "job": item["job"],
        },
        700,
    )

overview = service.run_overview(SIM, actions=3)
dump(
    "overview",
    {
        "state": overview["state"],
        "metrics": overview["metrics"],
        "platforms": overview["platforms"],
        "rounds": overview["rounds"][:2],
        "actions": [a["content"][:60] for a in overview["actions"]],
        "cast": len(overview["cast"]),
        "state_counts": overview["state_counts"],
        "report": overview["report"],
        "hint": overview["report_hint"],
        "entity_types": overview["simulation"]["entity_types"][:6],
        "ontology_edges": overview["simulation"]["ontology"]["edge_types"][:6],
        "job": (overview["job"] or {}).get("id"),
        "seed": (overview["job"] or {}).get("seed"),
    },
    2600,
)

cast = service.run_cast(SIM)
dump("cast", {"count": cast["count"], "by_type": cast["by_type"], "first": cast["agents"][:1]}, 1400)

feed = service.run_feed(SIM, limit=2)
dump("feed", feed, 900)

status = service.run_report(SIM)
dump("report-status", status, 600)
