"""Que campos é que o `/jarvis/ask` devolve (e o que traz o plano)."""
from __future__ import annotations

import json
import os
import sys
import urllib.request

BASE = os.getenv("JARVIS_BASE", "http://127.0.0.1:8002")
QUESTION = os.getenv("JARVIS_Q", "Quais são as skills do agente Hermes?")


def main() -> int:
    body = json.dumps({"question": QUESTION}).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE}/jarvis/ask", data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=600) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    print("chaves:", sorted(data.keys()))
    for key in ("plan", "steps", "tools_used", "sources"):
        value = data.get(key)
        print(f"\n{key}:")
        print(json.dumps(value, ensure_ascii=False, default=str)[:700])
    print("\nanswer:", json.dumps(data.get("answer"), ensure_ascii=False, default=str)[:600])
    return 0


if __name__ == "__main__":
    sys.exit(main())
