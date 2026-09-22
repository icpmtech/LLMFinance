"""Testa um POST de pesquisa por NIF no publicacoes.mj.pt."""
from __future__ import annotations

import re
import sys
import time
from html import unescape

import requests

PAGE = "https://publicacoes.mj.pt/Pesquisa.aspx"
PFX = "ctl00$ContentPlaceHolderMain$"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-PT,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Origin": "https://publicacoes.mj.pt",
    "Referer": PAGE,
}


def form_state(html: str) -> dict:
    state = {}
    for m in re.finditer(r"<input([^>]*)>", html, re.I):
        attrs = m.group(1)
        n = re.search(r'name=["\']([^"\']+)["\']', attrs, re.I)
        if not n:
            continue
        v = re.search(r'value=["\']([^"\']*)["\']', attrs, re.I)
        state[n.group(1)] = unescape(v.group(1)) if v else ""
    for m in re.finditer(r"<select[^>]*name=[\"']([^\"']+)[\"'][^>]*>(.*?)</select>", html, re.I | re.S):
        sel = re.search(r'<option[^>]*value=["\']([^"\']*)["\'][^>]*selected', m.group(2), re.I)
        state[m.group(1)] = unescape(sel.group(1)) if sel else "null"
    return state


def main() -> int:
    nif = sys.argv[1] if len(sys.argv) > 1 else "500273170"
    s = requests.Session()
    s.headers.update(HEADERS)
    r = s.get(PAGE, timeout=60)
    html = r.content.decode("utf-8", errors="replace")
    st = form_state(html)

    print("cookies:", s.cookies.get_dict())
    noBot = re.search(r"NoBotBehavior.*?\}\s*\)", html, re.S)
    print("NoBotBehavior snippet:", (noBot.group(0)[:300] if noBot else "n/a"))

    time.sleep(3)
    payload = {
        "__EVENTTARGET": "",
        "__EVENTARGUMENT": "",
        "__LASTFOCUS": "",
        "__VIEWSTATE": st.get("__VIEWSTATE", ""),
        "__VIEWSTATEGENERATOR": st.get("__VIEWSTATEGENERATOR", ""),
        "__EVENTVALIDATION": st.get("__EVENTVALIDATION", ""),
        f"{PFX}txtDadosPubNif": nif,
        f"{PFX}txtDadosPubEntidade": "",
        f"{PFX}comboDadosPubDistrito": "null",
        f"{PFX}comboDadosPubConcelho": "null",
        f"{PFX}txtDataInit": "",
        f"{PFX}txtDataFim": "",
        f"{PFX}rblTipoPub": "0",
        f"{PFX}NoBot1$NoBot1_NoBotExtender_ClientState": "",
        f"{PFX}btSearch": "Pesquisar",
    }
    r2 = s.post(PAGE, data=payload, timeout=90)
    out = r2.content.decode("utf-8", errors="replace")
    open("_probe_mj_results.html", "w", encoding="utf-8").write(out)
    print("HTTP", r2.status_code, "bytes", len(out))

    # sinais de bloqueio / captcha
    for kw in ("reCAPTCHA", "captcha", "Captcha", "NoBot", "robô", "rob", "Valide"):
        if kw in out:
            print("  contém:", kw)
    # mensagens de validação
    for m in re.finditer(r'(id="[^"]*(?:Validator|lblMensagem|lblErro|lblResultado)[^"]*"[^>]*>)(.*?)(?=<)', out, re.S):
        print("  msg:", re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m.group(2)))[:200])

    # tabela de resultados
    tables = re.findall(r"<table[^>]*id=[\"']([^\"']+)[\"']", out, re.I)
    print("tabelas:", tables[:30])
    print("__VIEWSTATE presente:", "__VIEWSTATE" in out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
