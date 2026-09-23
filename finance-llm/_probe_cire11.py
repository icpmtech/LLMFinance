"""Sonda 11 — diagnosticar o carregamento da página CIRE num browser real."""
from __future__ import annotations

import re
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "https://www.citius.mj.pt/portal/consultas/ConsultasCire.aspx"
OUT = Path(__file__).parent / "_probe_cire_out"
P = "ctl00_ContentPlaceHolder1_"


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s)).strip()


def main() -> None:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(locale="pt-PT")
        page = ctx.new_page()
        page.goto(URL, wait_until="load", timeout=90000)
        page.wait_for_timeout(3000)
        print("url:", page.url)
        print("title:", page.title())
        html = page.content()
        (OUT / "browser_page.html").write_text(html, encoding="utf-8")
        print("len html:", len(html))
        print("tem txtCalendarDesde:", f"{P}txtCalendarDesde" in html)
        print("tem aspnetForm:", "aspnetForm" in html)
        print("IDs PlaceHolder1:", sorted(set(re.findall(r'id="(ctl00_ContentPlaceHolder1_[A-Za-z0-9_]+)"', html)))[:25])
        print("\n--- texto (3000) ---")
        print(norm(page.inner_text("body"))[:3000])
        browser.close()


if __name__ == "__main__":
    main()
