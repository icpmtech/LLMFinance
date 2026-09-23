"""Sonda 24 — ver o que MostraPdf.aspx?q=<token> devolve e localizar o PDF."""
from __future__ import annotations

import re
from pathlib import Path

from collectors.citius_cire import BASE, PAGE, CireClient

OUT = Path(__file__).parent / "_probe_cire_out"


def main() -> None:
    with CireClient(min_interval=1.0) as client:
        page = client.search(desde="2026-09-23", ate="2026-09-23")
        pub = next((p for p in page.items if p.doc_token), None)
        tok = pub.doc_token if pub else ""
        r = client.session.get(BASE + "Viewer/MostraPdf.aspx?q=" + tok, headers={"Referer": PAGE}, timeout=45)
        (OUT / "mostrapdf.html").write_text(r.text, encoding="utf-8")
        print("status", r.status_code, r.headers.get("content-type"), len(r.text))
        print("texto:", re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", r.text))[:600])
        print("srcs:", re.findall(r'(?:src|href|location)\s*=\s*["\']([^"\']+)', r.text)[:20])
        print("scripts:", re.findall(r"<script[^>]*>(.*?)</script>", r.text, re.S)[:3])


if __name__ == "__main__":
    main()
