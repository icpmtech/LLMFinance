"""Sonda 17 — comparar pesquisas com sessões novas e ver o texto do painel (diagnóstico de vazio)."""
from __future__ import annotations

import re
from pathlib import Path

import httpx

URL = "https://www.citius.mj.pt/portal/consultas/ConsultasCire.aspx"
OUT = Path(__file__).parent / "_probe_cire_out"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.8",
}
P = "ctl00$ContentPlaceHolder1$"
SM = P + "ScriptManager1"


def hidden(html: str, name: str) -> str:
    m = re.search(r'id="' + name.replace("$", r"\$") + r'"[^>]*value="([^"]*)"', html)
    return m.group(1) if m else ""


def parse_delta(delta: str) -> dict[str, str]:
    out, i, n = {}, 0, len(delta)
    while i < n:
        j = delta.find("|", i)
        if j < 0:
            break
        try:
            length = int(delta[i:j])
        except ValueError:
            break
        k = delta.find("|", j + 1)
        kind = delta[j + 1:k]
        m = delta.find("|", k + 1)
        ident = delta[k + 1:m]
        start = m + 1
        if kind == "updatePanel":
            out[ident] = delta[start:start + length]
        i = start + length
        if i < n and delta[i] == "|":
            i += 1
    return out


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s)).strip()


def search(c: httpx.Client, desde: str, ate: str, rbl: str = "todos") -> str:
    html = c.get(URL).text
    data = {
        SM: f"{P}UpdatePanel1|{P}btnSearch",
        "__EVENTTARGET": P + "btnSearch",
        "__EVENTARGUMENT": "",
        "__LASTFOCUS": "",
        "__VIEWSTATE": hidden(html, "__VIEWSTATE"),
        "__VIEWSTATEGENERATOR": hidden(html, "__VIEWSTATEGENERATOR"),
        "__VIEWSTATEENCRYPTED": hidden(html, "__VIEWSTATEENCRYPTED"),
        "__EVENTVALIDATION": hidden(html, "__EVENTVALIDATION"),
        P + "txtPesquisa": "", P + "rblTipo": "nif", P + "txtNumeroProcesso": "",
        P + "txtCalendarDesde": desde, P + "txtCalendarAte": ate,
        P + "ddlTribunais": "", P + "ddlGrupoActos": "", P + "ddlActos": "",
        P + "rblDias": rbl, "__ASYNCPOST": "true",
    }
    r = c.post(URL, data=data, headers={**HEADERS, "Referer": URL, "X-MicrosoftAjax": "Delta=true"})
    return parse_delta(r.text).get(P + "upResultados", "")


def main() -> None:
    for tag, desde, ate in [("A_01_23", "01/09/2026", "23/09/2026"), ("B_14_23", "14/09/2026", "23/09/2026")]:
        with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=120) as c:
            res = search(c, desde, ate)
        (OUT / f"d_{tag}.html").write_text(res, encoding="utf-8")
        txt = norm(res)
        cnt = re.search(r"([\d\.]+)\s+documentos encontrados", txt)
        print(f"[{tag}] len={len(res)} divs={res.count('resultadocdital') // 2} total={cnt.group(1) if cnt else '?'}")
        print("   ", txt[:260])
    # últimos 15/30 dias via rblDias
    for tag, rbl in [("C_dias15", "15"), ("D_dias30", "30")]:
        with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=120) as c:
            res = search(c, "", "", rbl)
        (OUT / f"d_{tag}.html").write_text(res, encoding="utf-8")
        txt = norm(res)
        cnt = re.search(r"([\d\.]+)\s+documentos encontrados", txt)
        print(f"[{tag}] len={len(res)} total={cnt.group(1) if cnt else '?'}")


if __name__ == "__main__":
    main()
