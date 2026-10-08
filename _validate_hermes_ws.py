"""Valida o WebSocket do gateway do Hermes sob o subcaminho público.

Compara o dashboard **público** (`https://sabemos.studio/hermes-agent/`, via
Caddy → túnel → nginx → container) com o **local** (`http://127.0.0.1:8892/`,
proxy de incorporação), para separar o que é do proxy do que é da própria app:

* WebSockets abertos (`/api/ws`, `/api/events`, `/api/pty`), frames e fechos;
* banner «Lost connection to the Hermes dashboard server» / «Reconnect now»;
* respostas 404 e erros de consola.

Corre numa página do dashboard (Sessions) e na do Chat, com uma janela de
estabilidade de 60 s para apanhar quedas de ligação.
"""
from __future__ import annotations

import json
import sys
import urllib.request

from playwright.sync_api import sync_playwright

PUBLIC = "https://sabemos.studio"
SSO_URL = f"{PUBLIC}/hermes-agent/"
LOCAL_URL = "http://127.0.0.1:8892/"
STABILITY_SECONDS = 60


def login_token() -> str:
    body = json.dumps({"email": "teste@teste.com", "password": "teste123"}).encode("utf-8")
    req = urllib.request.Request(
        f"{PUBLIC}/api/auth/login",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=25) as resp:
        return json.loads(resp.read().decode("utf-8"))["token"]


class Probe:
    """Observa uma página: sockets, 404s, consola e o banner de desconexão."""

    def __init__(self, page, label: str) -> None:
        self.page = page
        self.label = label
        self.sockets: dict[str, dict] = {}
        self.not_found: list[str] = []
        self.console: list[tuple[str, str]] = []
        page.on("websocket", self._on_ws)
        page.on(
            "response",
            lambda r: self.not_found.append(r.url.split("?")[0])
            if r.status in (404, 500, 502)
            else None,
        )
        page.on("console", self._on_console)

    # -- eventos ------------------------------------------------------------
    def _on_ws(self, ws) -> None:
        entry = {"open": True, "closed": False, "sent": 0, "recv": 0, "error": None}
        key = ws.url.split("?")[0]
        self.sockets[key] = entry
        ws.on("framesent", lambda _: entry.__setitem__("sent", entry["sent"] + 1))
        ws.on("framereceived", lambda _: entry.__setitem__("recv", entry["recv"] + 1))
        ws.on("close", lambda _: entry.update(closed=True))
        ws.on(
            "socketerror",
            lambda e: entry.__setitem__("error", str(e).splitlines()[0][:90]),
        )

    def _on_console(self, message) -> None:
        if message.type in ("error", "warning") and "getImageData" not in message.text:
            self.console.append((message.type, " ".join(message.text.split())[:200]))

    # -- leitura ------------------------------------------------------------
    def banner(self) -> tuple[bool, bool]:
        body = self.page.locator("body").text_content() or ""
        return "Lost connection" in body, "Reconnect now" in body

    def report(self) -> bool:
        lost, reconnect = self.banner()
        print(f"\n--- {self.label} ---")
        print("banner «Lost connection»:", lost, "| «Reconnect now»:", reconnect)
        for url, state in self.sockets.items():
            print(f"  {url} -> {state}")
        if not self.sockets:
            print("  (nenhum WebSocket aberto)")
        bad = [u for u in self.not_found if "analytics" not in u]
        if bad:
            print("  404/5xx:", sorted(set(bad)))
        for kind, text in self.console:
            if "GL Driver" not in text and "sandbox" not in text:
                print(f"  consola [{kind}] {text}")
        return not lost and not reconnect


def main() -> int:
    token = login_token()
    problems: list[str] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)

        # ---- público (SSO por localStorage) ------------------------------
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        ctx.add_init_script(
            f"window.localStorage.setItem('finance-llm-token', {json.dumps(token)});"
        )
        page = ctx.new_page()
        probe = Probe(page, "público: dashboard + chat")
        page.goto(SSO_URL, wait_until="domcontentloaded", timeout=90_000)
        for _ in range(45):
            if "/login" not in page.url:
                break
            page.wait_for_timeout(1000)
        print("url:", page.url)
        page.wait_for_timeout(5000)
        try:
            page.get_by_role("link", name="Chat", exact=True).first.click(timeout=15_000)
            print("clique em «Chat» ->", page.url)
        except Exception as error:  # noqa: BLE001
            problems.append(f"não abriu o Chat: {error}")
        page.wait_for_timeout(10_000)

        # janela de estabilidade
        for _ in range(STABILITY_SECONDS // 5):
            page.wait_for_timeout(5000)
            if probe.banner()[0]:
                break
        if not probe.report():
            problems.append("público: banner de desconexão presente")
        page.screenshot(path=r"c:\LLMFinance\_hermes_ws_public.png")
        ctx.close()

        # ---- local (proxy de incorporação :8892) ------------------------
        ctx2 = browser.new_context(viewport={"width": 1440, "height": 900})
        page2 = ctx2.new_page()
        probe2 = Probe(page2, "local: :8892/chat")
        try:
            page2.goto(f"{LOCAL_URL}chat?profile=default", wait_until="domcontentloaded", timeout=60_000)
            for _ in range(30):
                if "password" not in (page2.locator("body").text_content() or "").lower():
                    break
                page2.wait_for_timeout(1000)
            page2.wait_for_timeout(15_000)
            probe2.report()
        except Exception as error:  # noqa: BLE001
            print("local indisponível:", error)
        ctx2.close()
        browser.close()

    print("\n=== resultado ===")
    if problems:
        for p in problems:
            print("FALHA:", p)
        return 1
    print("OK: WebSocket do gateway estável no domínio público (sem aviso de desconexão).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
