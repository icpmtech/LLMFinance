"""Parser do delta ASP.NET (UpdatePanel) devolvido pelo CIRE — mostra a estrutura completa."""
from __future__ import annotations

import re
import sys
from pathlib import Path

OUT = Path(__file__).parent / "_probe_cire_out"


def parse(delta: str) -> list[tuple[str, str, str]]:
    """Devolve [(type, id, content)] segundo o formato length|type|id|content|."""
    parts: list[tuple[str, str, str]] = []
    i = 0
    n = len(delta)
    while i < n:
        j = delta.find("|", i)
        if j < 0:
            break
        try:
            length = int(delta[i:j])
        except ValueError:
            break
        k = delta.find("|", j + 1)
        kind = delta[j + 1:k]
        m = delta.find("|", k + 1)
        ident = delta[k + 1:m]
        start = m + 1
        content = delta[start:start + length]
        parts.append((kind, ident, content))
        i = start + length
        if i < n and delta[i] == "|":
            i += 1
    return parts


def main() -> None:
    name = sys.argv[1] if len(sys.argv) > 1 else "s8_nomeLDA.txt"
    delta = (OUT / name).read_text(encoding="utf-8")
    parts = parse(delta)
    lines = [f"ficheiro: {name}  len={len(delta)}  partes={len(parts)}"]
    for kind, ident, content in parts:
        lines.append(f"\n### {kind} | {ident} | {len(content)} chars")
        plain = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", content)).strip()
        lines.append("   texto: " + plain[:400])
    (OUT / "delta_report.txt").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines)[:4000])


if __name__ == "__main__":
    main()
