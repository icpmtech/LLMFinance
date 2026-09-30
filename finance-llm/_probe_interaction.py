"""Sonda: que ações o MiroFish oferece (InteractionView) e os seus payloads."""

from __future__ import annotations

import pathlib
import subprocess


def sh(cmd: str) -> str:
    out = subprocess.run(
        ["docker", "exec", "finance-llm-mirofish", "sh", "-c", cmd],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return out.stdout or out.stderr


parts = {
    "interaction_view": sh("grep -nE 'api/|@click|placeholder|label=|title=|:disabled|emit|function ' /app/frontend/src/views/InteractionView.vue | head -80"),
    "simulation_api_tail": sh("sed -n '120,400p' /app/frontend/src/api/simulation.js"),
    "api_routes_payloads": sh("grep -nE \"route\\('/(env-status|close-env|start|stop|interview|interview/batch|interview/all|<simulation_id>/(posts|comments|profiles|config|run-status))|data.get\" /app/backend/app/api/simulation.py | head -60"),
}
text = "\n\n".join(f"########## {k}\n{v}" for k, v in parts.items())
pathlib.Path("logs/_mirofish_interaction_probe.txt").write_text(text, encoding="utf-8")
print("ok", len(text))
