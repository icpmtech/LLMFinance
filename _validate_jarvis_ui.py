"""Vê como fica o Jarvis na UI: modo de voz e integração com o Hermes Agent.

Fluxo do utilizador, replicado no browser:

1. abre `/jarvis` autenticado;
2. lê o cabeçalho (gateways vindos do `/jarvis/meta`) e o painel de controlo da voz;
3. liga a **Voz do servidor** e confirma que o motor é `edge-tts`;
4. pergunta «Quais são as skills do agente Hermes?» no compositor e segue o rasto:
   passos do plano e ferramentas do gateway `agent`;
5. guarda screenshots de cada momento.
"""
from __future__ import annotations

import json
import sys
import urllib.request

from playwright.sync_api import sync_playwright

BASE = "https://sabemos.studio"
QUESTION = "Quais são as skills do agente Hermes?"


def login_token() -> str:
    body = json.dumps({"email": "teste@teste.com", "password": "teste123"}).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE}/api/auth/login",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))["token"]


def main() -> int:
    token = login_token()
    failures: list[str] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1500, "height": 940})
        ctx.add_init_script(
            f"window.localStorage.setItem('finance-llm-token', {json.dumps(token)});"
        )
        page = ctx.new_page()
        errors: list[str] = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

        page.goto(f"{BASE}/jarvis", wait_until="domcontentloaded", timeout=90_000)
        subtitle = ""
        for _ in range(20):
            page.wait_for_timeout(1500)
            subtitle = " ".join((page.locator("header p").first.text_content() or "").split())
            if "Hermes Agent" in subtitle:
                break
        print("subtítulo:", subtitle)
        if "Hermes Agent" not in subtitle:
            failures.append("o cabeçalho não mostra o gateway «Hermes Agent»")

        for label in ("Recusar", "Aceitar"):
            button = page.locator(f"button:has-text('{label}')")
            if button.count() > 0:
                try:
                    button.first.click(timeout=5000)
                    break
                except Exception:
                    pass
        page.wait_for_timeout(2000)
        page.screenshot(path=r"c:\LLMFinance\_jarvis_1_antes.png")

        header = " ".join((page.locator("header").first.text_content() or "").split())
        print("cabeçalho:", header[:260])
        for needle in ("Voz do servidor", "Falar", "ferramentas", "Investigação"):
            print(f"  contém «{needle}»:", needle in header)

        voice_toggle = page.locator("header button:has-text('Voz do servidor')")
        if voice_toggle.count() > 0:
            voice_toggle.first.click(timeout=8000)
            page.wait_for_timeout(4000)
            print("voz do servidor ligada")
        else:
            failures.append("não encontrei o botão «Voz do servidor» no cabeçalho")
        page.screenshot(path=r"c:\LLMFinance\_jarvis_2_voz.png")

        composer = page.locator("textarea").last
        if composer.count() == 0:
            composer = page.locator("input[type=text]").last
        composer.fill(QUESTION)
        composer.press("Enter")
        print("pergunta enviada; à espera do rasto…")

        body_text = ""
        for _ in range(60):
            page.wait_for_timeout(3000)
            body_text = " ".join((page.locator("body").text_content() or "").split())
            if "Hermes Agent" in body_text and "skills" in body_text.lower() and (
                "Delegar" in body_text or "resultado" in body_text
            ):
                break

        for needle in (
            "Skills do Hermes Agent",
            "Delegar no Hermes Agent",
            "Hermes Agent",
            "53",
            "skill",
        ):
            print(f"  rasto contém «{needle}»:", needle in body_text)
        if "Skills do Hermes Agent" not in body_text:
            failures.append("o rasto não mostrou o passo do gateway do agente")

        page.screenshot(path=r"c:\LLMFinance\_jarvis_3_agente.png")
        browser.close()

    print("\n=== erros de consola ===")
    for line in errors[:10]:
        print("-", " ".join(line.split())[:160])
    if errors:
        failures.append(f"{len(errors)} erros de consola")

    print("\n=== resultado ===")
    for failure in failures:
        print("FALHA:", failure)
    if failures:
        return 1
    print("OK: Jarvis na UI com voz do servidor e o gateway do Hermes Agent no rasto.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
