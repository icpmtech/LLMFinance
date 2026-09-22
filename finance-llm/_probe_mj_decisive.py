"""Teste decisivo: o captcha é mesmo exigido pelo servidor? Há serviço alternativo?"""
from __future__ import annotations

import re
import time
from html import unescape

import requests

PAGE = "https://publicacoes.mj.pt/Pesquisa.aspx"
PFX = "ctl00$ContentPlaceHolderMain$"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
      "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.8", "Origin": "https://publicacoes.mj.pt", "Referer": PAGE}


def state(html: str) -> dict:
    st = {}
    for m in re.finditer(r"<input([^>]*)>", html, re.I):
        n = re.search(r'name=["\']([^"\']+)["\']', m.group(1), re.I)
        if not n:
            continue
        v = re.search(r'value=["\']([^"\']*)["\']', m.group(1), re.I)
        st[n.group(1)] = unescape(v.group(1)) if v else ""
    return st


def submit(s: requests.Session, st: dict, challenge_state: str, recaptcha: str | None, wait: float) -> str:
    time.sleep(wait)
    p = {
        "__EVENTTARGET": "", "__EVENTARGUMENT": "", "__LASTFOCUS": "",
        "__VIEWSTATE": st.get("__VIEWSTATE", ""),
        "__VIEWSTATEGENERATOR": st.get("__VIEWSTATEGENERATOR", ""),
        "__EVENTVALIDATION": st.get("__EVENTVALIDATION", ""),
        f"{PFX}txtDadosPubNif": "500273170",
        f"{PFX}txtDadosPubEntidade": "",
        f"{PFX}comboDadosPubDistrito": "null",
        f"{PFX}comboDadosPubConcelho": "null",
        f"{PFX}txtDataInit": "", f"{PFX}txtDataFim": "",
        f"{PFX}rblTipoPub": "0",
        f"{PFX}NoBot1$NoBot1_NoBotExtender_ClientState": challenge_state,
        f"{PFX}btSearch": "Pesquisar",
    }
    if recaptcha is not None:
        p["g-recaptcha-response"] = recaptcha
    r = s.post(PAGE, data=p, timeout=90)
    h = r.content.decode("utf-8", errors="replace")
    m = re.search(r'id="ctl00_ContentPlaceHolderMain_lbNoResult"[^>]*>(.*?)<', h, re.S)
    grid = re.findall(r"<table[^>]*id=[\"']([^\"']+)[\"']", h, re.I)
    return f"HTTP {r.status_code} | lbNoResult={re.sub(r'<[^>]+>','',m.group(1)).strip() if m else '-'!r} | tabelas={grid}"


def main() -> None:
    s = requests.Session()
    s.headers.update(UA)
    html = s.get(PAGE, timeout=60).content.decode("utf-8", errors="replace")
    st = state(html)
    ch = re.search(r'"ChallengeScript":"([^"]+)"', html)
    script = ch.group(1).replace("\\u0027", "'") if ch else ""
    val = str(eval(script.split("eval('")[1].split("')")[0]))  # noqa: S307 - desafio do site
    print("desafio NoBot:", script, "->", val)

    print("A) sem captcha, NoBot correto, espera 5s:", submit(s, st, val, None, 5))
    st2 = state(s.get(PAGE, timeout=60).content.decode("utf-8", errors="replace"))
    print("B) com captcha inválido:            ", submit(s, st2, val, "invalid-token", 5))

    print("\n=== endpoints de serviço candidatos ===")
    for u in ("Services/Publicacoes.asmx", "PublicacoesService.asmx", "api/publicacoes",
              "Services/PesquisaService.asmx", "Pesquisa.asmx", "Default.aspx"):
        try:
            r = s.get(f"https://publicacoes.mj.pt/{u}", timeout=25)
            print(f"  {r.status_code} {len(r.content):>6} {u}")
        except Exception as e:
            print("  ERR", u, e)


if __name__ == "__main__":
    main()
