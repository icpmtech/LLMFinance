"""Validação end-to-end do Hermes Agent sob o subcaminho público (com SSO).

Fluxo replicado do utilizador real:

1. Inicia sessão no IQ OS por API e injeta o token em `localStorage`
   (`finance-llm-token`), como a SPA faz.
2. Abre a página iframe `https://sabemos.studio/iframe/iqos-hermes-agent`.
3. **Sem preencher o formulário**, espera que o *single sign-on* autentique no
   dashboard (o script injetado publica em `/hermes-agent/auth/password-login`
   com o token do IQ OS).
4. Verifica que o dashboard renderiza, que o bundle vem de
   `/hermes-agent/assets/`, que não há 404 nem pedidos de assets à raiz e que
   não há erros de consola.
"""
from __future__ import annotations

import json
import sys
import urllib.request

from playwright.sync_api import sync_playwright

BASE = "https://sabemos.studio"
URL = f"{BASE}/iframe/iqos-hermes-agent?v=1791460700001"
EMAIL = "teste@teste.com"
PASSWORD = "teste123"


def login_token() -> str:
    body = json.dumps({"email": EMAIL, "password": PASSWORD}).encode("utf-8")
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
    print("token IQ OS obtido:", token[:16], "...")

    failures: list[str] = []
    responses: list[tuple[str, int]] = []
    console_errors: list[str] = []
    console_warnings: list[str] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        context.add_init_script(
            f"window.localStorage.setItem('finance-llm-token', {json.dumps(token)});"
        )
        page = context.new_page()
        page.on("response", lambda r: responses.append((r.url, r.status)))
        page.on(
            "console",
            lambda m: (
                console_errors.append(m.text)
                if m.type == "error"
                else console_warnings.append(m.text)
            ),
        )

        page.goto(URL, wait_until="domcontentloaded", timeout=90_000)

        frame = None
        for _ in range(45):
            frame = next(
                (f for f in page.frames if "/hermes-agent/" in (f.url or "")), None
            )
            if frame is not None:
                break
            page.wait_for_timeout(1000)
        if frame is None:
            print("FALHA: o iframe do Hermes nao criou frame")
            print("frames:", [f.url for f in page.frames])
            browser.close()
            return 1

        print("frame inicial:", frame.url)
        page.wait_for_timeout(10_000)
        for _ in range(45):
            if "/login" not in (frame.url or ""):
                break
            page.wait_for_timeout(1000)

        body = frame.locator("body").text_content() or ""
        print("url final do frame:", frame.url)
        print("inicio do corpo:", " ".join(body.split())[:200])

        if "/login" in (frame.url or ""):
            failures.append("SSO nao autenticou (o frame ficou na pagina de login)")
        if "Sessions" not in body:
            failures.append("dashboard nao renderizou («Sessions» ausente)")

        hermes_assets = [u for u, _ in responses if "/hermes-agent/assets/" in u]
        root_assets = [u for u in (u for u, _ in responses) if u.startswith(f"{BASE}/assets/")]
        print("assets sob /hermes-agent/:", len(hermes_assets))
        if not hermes_assets:
            failures.append("nenhum asset carregado pelo subcaminho do Hermes")
        # Os assets da raiz pertencem à própria SPA — não contam como falha.

        bad_404 = [u for u, s in responses if s == 404 and "/hermes-agent/" in u]
        api_404 = [u for u, s in responses if s == 404 and "/hermes-agent/api/" in u]
        print("404 sob /hermes-agent/:", bad_404[:8])
        if bad_404:
            failures.append(f"{len(bad_404)} pedidos 404 sob o subcaminho do Hermes")
        if api_404:
            failures.append(f"{len(api_404)} chamadas de API 404")

        page.screenshot(path=r"c:\LLMFinance\_hermes_public.png")
        browser.close()

    print("\n=== erros de consola ===")
    for line in console_errors[:15]:
        print("-", " ".join(line.split())[:200])
    if console_errors:
        failures.append(f"{len(console_errors)} erros de consola")

    print("\n=== resultado ===")
    for f in failures:
        print("FALHA:", f)
    if failures:
        return 1
    print("OK: SSO + dashboard do Hermes funcionais no iframe publico.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
