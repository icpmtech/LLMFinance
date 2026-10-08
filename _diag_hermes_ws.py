"""Diagnóstico: WebSocket/gateway do dashboard do Hermes sob /hermes-agent/.

Abre o dashboard (login por SSO), captura o WebSocket que o dashboard usa para o
gateway e os erros de consola, para localizar o «Lost connection to the Hermes
dashboard server».
"""
from __future__ import annotations

import json
import sys
import urllib.request

from playwright.sync_api import sync_playwright

BASE = "https://sabemos.studio"
URL = f"{BASE}/iframe/iqos-hermes-agent?v=1791462000001"


def login_token() -> str:
    body = json.dumps({"email": "teste@teste.com", "password": "teste123"}).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE}/api/auth/login",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))["token"]


def main() -> int:
    token = login_token()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        ctx.add_init_script(
            f"window.localStorage.setItem('finance-llm-token', {json.dumps(token)});"
        )
        page = ctx.new_page()

        sockets: list[dict] = []

        def on_ws(ws):
            entry = {"url": ws.url, "closed": False, "sent": 0, "recv": 0, "error": None}
            sockets.append(entry)
            ws.on("framesent", lambda _: entry.update(sent=entry["sent"] + 1))
            ws.on("framereceived", lambda _: entry.update(recv=entry["recv"] + 1))
            ws.on("close", lambda _: entry.update(closed=True))
            ws.on("socketerror", lambda e: entry.update(error=str(e)))

        page.on("websocket", on_ws)
        page.on("console", lambda m: print("console", m.type, " ".join(m.text.split())[:220]))
        page.on("pageerror", lambda e: print("pageerror", " ".join(str(e).split())[:220]))
        page.on(
            "requestfailed",
            lambda r: print("requestfailed", r.method, r.url, r.failure),
        )

        page.goto(URL, wait_until="domcontentloaded", timeout=90_000)
        for _ in range(45):
            if any("/hermes-agent/" in (f.url or "") for f in page.frames):
                break
            page.wait_for_timeout(1000)
        page.wait_for_timeout(15_000)

        frames = [f for f in page.frames if "/hermes-agent/" in (f.url or "")]
        frame = frames[0] if frames else None
        print("frame:", frame.url if frame else None)
        if frame:
            body = frame.locator("body").text_content() or ""
            print("corpo:", " ".join(body.split())[:300])
            info = frame.evaluate(
                """() => ({
                     base: window.__HERMES_BASE_PATH__ ?? null,
                     href: location.href,
                     gateway: window.__HERMES_GATEWAY_URL__ ?? null,
                 })"""
            )
            print("info do frame:", info)

        print("\n=== websockets ===")
        for s in sockets:
            print(s)
        if not sockets:
            print("(nenhum WebSocket aberto)")

        page.screenshot(path=r"c:\LLMFinance\_hermes_ws.png")
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
