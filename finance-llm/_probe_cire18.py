"""Sonda 18 — que cabeçalho faz o portal devolver os resultados?"""
from __future__ import annotations

import re
from pathlib import Path

import httpx

URL = "https://www.citius.mj.pt/portal/consultas/ConsultasCire.aspx"
OUT = Path(__file__).parent / "_probe_cire_out"
BASE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.8",
}
P = "ctl00$ContentPlaceHolder1$"
SM = P + "ScriptManager1"
EXTRA = {
    "ajax": {"X-MicrosoftAjax": "Delta=true"},
    "xrw": {"X-Requested-With": "XMLHttpRequest"},
    "accept": {"Accept": "*/*"},
    "all": {"X-MicrosoftAjax": "Delta=true", "X-Requested-With": "XMLHttpRequest", "Accept": "*/*"},
}


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


def main() -> None:
    for tag, extra in EXTRA.items():
        with httpx.Client(headers={**BASE_HEADERS, **extra}, follow_redirects=True, timeout=120) as c:
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
                P + "txtCalendarDesde": "01/09/2026", P + "txtCalendarAte": "23/09/2026",
                P + "ddlTribunais": "", P + "ddlGrupoActos": "", P + "ddlActos": "",
                P + "rblDias": "todos", "__ASYNCPOST": "true",
            }
            r = c.post(URL, data=data, headers={"Referer": URL})
        res = parse_delta(r.text).get(P + "upResultados", "")
        txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", res))
        cnt = re.search(r"([\d\.]+)\s+documentos encontrados", txt)
        print(f"[{tag:6}] status={r.status_code} len={len(res):7} itens={res.count('resultadocdital') // 2:3} total={cnt.group(1) if cnt else '-'}")


if __name__ == "__main__":
    main()
