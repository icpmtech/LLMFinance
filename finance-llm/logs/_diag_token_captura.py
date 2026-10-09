"""Diagnóstico: porque é que a captura caiu no ecrã de login.

Compara o que o browser tem (token no localStorage), o que o servidor responde a
`/auth/me` e o URL final depois de tentar abrir uma página autenticada.

Uso::

    python logs/_diag_token_captura.py
"""
from __future__ import annotations

import json
import subprocess
import sys

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:4180"
CODIGO_TOKEN = (
    "from api import auth_service;"
    "us = auth_service.list_users(1) or [];"
    "s = auth_service.create_session(us[0]) if us else {};"
    "print('EMAIL=' + str(us[0].get('email') if us else ''));"
    "print('TOKEN=' + str(s.get('token', '')))"
)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    saida = subprocess.run(
        ["docker", "exec", "finance-llm-backend", "python", "-c", CODIGO_TOKEN],
        capture_output=True, text=True, timeout=120,
    )
    token, email = "", ""
    for linha in (saida.stdout or "").splitlines():
        if linha.startswith("TOKEN="):
            token = linha.split("=", 1)[1].strip()
        if linha.startswith("EMAIL="):
            email = linha.split("=", 1)[1].strip()
    print(f"utilizador da sessão: {email!r} | token com {len(token)} caracteres")
    if saida.stderr.strip():
        print("stderr:", saida.stderr.strip()[:300])
    if not token:
        return 1

    with sync_playwright() as p:
        browser = p.chromium.launch()
        contexto = browser.new_context(viewport={"width": 1600, "height": 950})
        contexto.add_init_script(
            f"try {{ window.localStorage.setItem('finance-llm-token', {json.dumps(token)}); }} catch (e) {{}}"
        )
        pagina = contexto.new_page()
        registos: list[str] = []
        pagina.on("response", lambda r: registos.append(f"{r.status} {r.url[:90]}") if "/auth/" in r.url else None)
        pagina.on("console", lambda m: registos.append(f"console[{m.type}] {m.text[:120]}") if m.type == "error" else None)

        pagina.goto(f"{BASE}/empresas-iq", wait_until="load", timeout=60000)
        pagina.wait_for_timeout(6000)

        estado = pagina.evaluate(
            """async () => {
              const t = window.localStorage.getItem('finance-llm-token') || '';
              let me = null;
              try {
                const r = await fetch('/api/auth/me', { headers: { Authorization: 'Bearer ' + t } });
                me = { status: r.status, corpo: (await r.text()).slice(0, 120) };
              } catch (e) { me = { erro: String(e) }; }
              return {
                url: window.location.href,
                tokenGuardado: t.length,
                temLogin: !!document.querySelector("input[type=password]"),
                me,
              };
            }"""
        )
        print("estado:", json.dumps(estado, ensure_ascii=False, indent=1))
        print("eventos /auth/:", *registos[-8:], sep="\n  ")
        contexto.close()
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
