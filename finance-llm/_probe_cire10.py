"""Sonda 10 — conduzir o CIRE com um browser real (Playwright) e capturar o POST de pesquisa
e o HTML resultante do painel upResultados."""
from __future__ import annotations

import re
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "https://www.citius.mj.pt/portal/consultas/ConsultasCire.aspx"
OUT = Path(__file__).parent / "_probe_cire_out"
OUT.mkdir(exist_ok=True)
P = "ctl00_ContentPlaceHolder1_"


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s)).strip()


def main() -> None:
    captured: list[tuple[str, str, str]] = []
    with sync_playwright() as pw:
        for launcher in ("chromium", "chrome", "msedge"):
            try:
                browser = getattr(pw, launcher).launch(headless=True)
                print("launcher ok:", launcher)
                break
            except Exception as e:  # noqa: BLE001
                print("launcher falhou:", launcher, str(e)[:120])
        else:
            raise SystemExit("sem browser")

        ctx = browser.new_context(locale="pt-PT")
        page = ctx.new_page()

        def on_response(resp):
            if "ConsultasCire" in resp.url and resp.request.method == "POST":
                try:
                    body = resp.text()
                except Exception:  # noqa: BLE001
                    body = ""
                captured.append(("RESP", str(resp.status), body))
                (OUT / f"browser_resp_{len(captured)}.txt").write_text(body, encoding="utf-8")

        page.on("response", on_response)

        def on_request(req):
            if "ConsultasCire" in req.url and req.method == "POST":
                captured.append(("REQ", "", req.post_data or ""))

        page.on("request", on_request)

        page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(1500)
        # preencher datas
        page.fill(f"#{P}txtCalendarDesde", "01/09/2026")
        page.fill(f"#{P}txtCalendarAte", "23/09/2026")
        page.click(f"#{P}btnSearch")
        page.wait_for_timeout(6000)
        up = page.inner_html(f"#{P}upResultados")
        (OUT / "browser_upResultados.html").write_text(up, encoding="utf-8")
        print("\n=== upResultados (texto) ===")
        print(norm(up)[:1500])
        print("\n=== body text (fim) ===")
        body = page.inner_text("body")
        print(norm(body)[-2000:])
        print("\n=== pedidos capturados ===")
        for kind, status, payload in captured:
            print(f"[{kind}] {status} len={len(payload)}")
            if kind == "REQ":
                fields = dict(re.findall(r"(?:^|&)([^=]+)=([^&]*)", payload.replace("\r\n", "&")))
                for k, v in fields.items():
                    if k.startswith("__") or "PlaceHolder1" in k:
                        print(f"    {k} = {v[:80]!r}")
        browser.close()


if __name__ == "__main__":
    main()
