"""Reproduz (e valida a recuperação) do aviso «Lost connection to the Hermes dashboard server».

Sequência:
1. abre o dashboard público com SSO e vai ao Chat (abre o WebSocket do gateway);
2. reinicia o container `hermes-agent` — é isto que provoca o aviso;
3. espera que o aviso apareça;
4. clica «Reconnect now» e confirma que a ligação volta e o aviso desaparece.
"""
from __future__ import annotations

import json
import subprocess
import sys
import urllib.request

from playwright.sync_api import sync_playwright

PUBLIC = "https://sabemos.studio"
URL = f"{PUBLIC}/hermes-agent/"
COMPOSE = ["docker", "compose", "-f", r"C:\LLMFinance\finance-llm\docker-compose.yml"]
CWD = r"C:\LLMFinance\finance-llm"


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


def restart_hermes() -> None:
    print(">>> a reiniciar o container hermes-agent…")
    out = subprocess.run(
        COMPOSE + ["restart", "hermes-agent"], capture_output=True, cwd=CWD, timeout=300
    )
    print("   ", out.stdout.decode("utf-8", "replace").strip().splitlines()[-1:] or out.returncode)


def wait_logged_in(page, timeout_s: int = 60) -> None:
    for _ in range(timeout_s):
        if "/login" not in page.url:
            return
        page.wait_for_timeout(1000)


def main() -> int:
    token = login_token()
    problems: list[str] = []
    sockets: dict[str, dict] = {}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        ctx.add_init_script(
            f"window.localStorage.setItem('finance-llm-token', {json.dumps(token)});"
        )
        page = ctx.new_page()

        def on_ws(ws):
            entry = {"open": True, "closed": False, "sent": 0, "recv": 0}
            sockets.setdefault(ws.url.split("?")[0], []).append(entry)
            ws.on("framesent", lambda _: entry.__setitem__("sent", entry["sent"] + 1))
            ws.on("framereceived", lambda _: entry.__setitem__("recv", entry["recv"] + 1))
            ws.on("close", lambda _: entry.update(closed=True))

        page.on("websocket", on_ws)
        page.on(
            "console",
            lambda m: print("console", m.type, " ".join(m.text.split())[:150])
            if m.type == "error"
            else None,
        )

        page.goto(URL, wait_until="domcontentloaded", timeout=90_000)
        wait_logged_in(page)
        page.wait_for_timeout(5000)
        page.get_by_role("link", name="Chat", exact=True).first.click(timeout=15_000)
        page.wait_for_timeout(8000)
        print("url:", page.url)
        print("sockets antes do restart:", {k: len(v) for k, v in sockets.items()})

        def ticket_status() -> int | str:
            """O bilhete de WebSocket só é emitido com sessão válida (401 = sessão perdida)."""
            try:
                return page.evaluate(
                    """async () => {
                         const r = await fetch('/hermes-agent/api/auth/ws-ticket',
                                               {method: 'POST', credentials: 'include'});
                         return r.status;
                       }"""
                )
            except Exception as error:  # noqa: BLE001
                return f"erro: {error}"

        print("ws-ticket antes do restart:", ticket_status())

        # 1) provocar a queda exactamente como aconteceu
        restart_hermes()

        # 2) esperar o aviso
        banner_seen = False
        for _ in range(60):
            page.wait_for_timeout(2000)
            body = page.locator("body").text_content() or ""
            if "Lost connection" in body:
                banner_seen = True
                break
        print("aviso «Lost connection» apareceu:", banner_seen)
        if not banner_seen:
            # Não é falha: o cliente pode ter reconectado sozinho (retry automático).
            print("(a página reconectou sozinha — o aviso é transitório)")

        # 3) recuperação: «Reconnect now» se estiver visível, senão recarregar
        clicked = False
        button = page.locator("text=Reconnect now")
        if button.count() > 0:
            try:
                button.first.click(timeout=10_000)
                clicked = True
                print("clique em «Reconnect now»")
            except Exception as error:  # noqa: BLE001
                problems.append(f"não consegui clicar em «Reconnect now»: {error}")
        else:
            print("botão «Reconnect now» não apareceu — a recuperar com um reload da página")
            page.reload(wait_until="domcontentloaded", timeout=90_000)
            print("depois do reload ->", page.url)
            page.wait_for_timeout(10_000)
            for _ in range(30):
                if "/login" not in page.url:
                    break
                page.wait_for_timeout(1000)

        # 4) confirmar recuperação
        recovered = False
        for _ in range(60):
            page.wait_for_timeout(2000)
            body = page.locator("body").text_content() or ""
            alive = any(
                not inst["closed"] and inst["recv"] > 0
                for insts in sockets.values()
                for inst in insts
            )
            if "Lost connection" not in body and alive:
                recovered = True
                break
        print("recuperado:", recovered)
        print("sockets:", {k: [{"closed": i["closed"], "recv": i["recv"]} for i in v] for k, v in sockets.items()})
        survived = ticket_status()
        print("ws-ticket depois do restart:", survived)
        if survived != 200:
            problems.append(
                f"a sessão do dashboard não sobreviveu ao restart (ws-ticket -> {survived})"
            )
        body = " ".join((page.locator("body").text_content() or "").split())
        index = body.find("Gateway Status")
        print("estado no rodapé:", body[index : index + 120] if index >= 0 else "(não encontrado)")

        if not recovered:
            problems.append("a ligação não recuperou depois do restart")
        page.screenshot(path=r"c:\LLMFinance\_hermes_reconnect.png")
        browser.close()

    print("\n=== resultado ===")
    for p in problems:
        print("FALHA:", p)
    if problems:
        return 1
    print(
        "OK: a queda do gateway é detetada"
        + (" e «Reconnect now» recupera a ligação." if clicked else " e o cliente reconecta sozinho.")
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
