"""Dump de segmentos do HTML do CIRE para inspeção."""
from __future__ import annotations

import re
from pathlib import Path

OUT = Path(__file__).parent / "_probe_cire_out"


def seg(html: str, needle: str, before: int = 200, after: int = 2000) -> str:
    i = html.find(needle)
    if i < 0:
        return f"<<{needle} NÃO ENCONTRADO>>"
    s = html[max(0, i - before): i + after]
    return re.sub(r"[ \t]+", " ", s)


def main() -> None:
    page = (OUT / "page.html").read_text(encoding="utf-8")
    post = (OUT / "post_full.html").read_text(encoding="utf-8")
    parts = []
    parts.append("===== PAGE: upResultados =====")
    parts.append(seg(page, 'id="ctl00_ContentPlaceHolder1_upResultados"'))
    parts.append("\n===== PAGE: btnSearch =====")
    parts.append(seg(page, 'ctl00_ContentPlaceHolder1_btnSearch', 600, 900))
    parts.append("\n===== PAGE: gv (grid) =====")
    parts.append(seg(page, "gv", 200, 600) if "gv" in page else "sem 'gv'")
    parts.append("\n===== PAGE: scripts do botão / validate =====")
    for m in re.finditer(r"<script[^>]*>(.*?)</script>", page, re.S):
        s = m.group(1)
        if "buscar" in s.lower() or "btnSearch" in s or "IsValid" in s:
            parts.append(re.sub(r"\s+", " ", s)[:1500])
    parts.append("\n===== POST: upResultados =====")
    parts.append(seg(post, 'id="ctl00_ContentPlaceHolder1_upResultados"'))
    (OUT / "segments.txt").write_text("\n".join(parts), encoding="utf-8")
    print("ok, ver _probe_cire_out/segments.txt")


if __name__ == "__main__":
    main()
