"""Qual é a base da API de cada bundle? (backend serve `chat-ui/dist`, o nginx do
frontend serve `_frontend_dist` — se uma tiver `/api` e a outra não, não podem ser
o mesmo build.)

    python _check_api_base.py
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "finance-llm"
ALVOS = [
    ("backend (chat-ui/dist)", ROOT / "chat-ui" / "dist"),
    ("frontend (_frontend_dist)", ROOT / "_frontend_dist"),
]


def bundle(dist: Path) -> Path | None:
    """O JS principal do dist (o que é referido no index.html)."""
    index = dist / "index.html"
    if not index.exists():
        return None
    m = re.search(r'src="(/assets/index-[^"]+\.js)"', index.read_text(encoding="utf-8"))
    return dist / m.group(1).lstrip("/") if m else None


def main() -> int:
    for nome, dist in ALVOS:
        js = bundle(dist)
        print(f"\n{nome}: {dist}")
        if js is None or not js.exists():
            print("   sem bundle")
            continue
        print(f"   bundle: {js.name} ({js.stat().st_size / 1024:.0f} kB)")
        text = js.read_text(encoding="utf-8", errors="replace")
        # A base da API é uma constante: `const X="/api"` (ou "").
        for m in re.finditer(r'(?:const|var|let)\s+([A-Za-z_$][\w$]*)\s*=\s*(""|"/api")', text):
            print(f"   {m.group(0)}")
        print("   '\"/api/ pode ocorrer':", text.count('"/api/'))
        idx = text.find("jarvis/ask/stream")
        if idx >= 0:
            print("   chamada:", repr(text[max(0, idx - 70) : idx + 16]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
