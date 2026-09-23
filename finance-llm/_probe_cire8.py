"""Sonda 8 — vários cenários de pesquisa no CIRE para descobrir o critério que devolve resultados."""
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


def hidden(html: str, name: str) -> str:
    m = re.search(r'id="' + name.replace("$", r"\$") + r'"[^>]*value="([^"]*)"', html)
    return m.group(1) if m else ""


def base(html: str) -> dict:
    return {
        "__EVENTTARGET": P + "btnSearch",
        "__EVENTARGUMENT": "",
        "__LASTFOCUS": "",
        "__VIEWSTATE": hidden(html, "__VIEWSTATE"),
        "__VIEWSTATEGENERATOR": hidden(html, "__VIEWSTATEGENERATOR"),
        "__VIEWSTATEENCRYPTED": hidden(html, "__VIEWSTATEENCRYPTED"),
        "__EVENTVALIDATION": hidden(html, "__EVENTVALIDATION"),
        "__ASYNCPOST": "true",
        P + "txtPesquisa": "",
        P + "rblTipo": "nif",
        P + "txtNumeroProcesso": "",
        P + "txtCalendarDesde": "",
        P + "txtCalendarAte": "",
        P + "ddlTribunais": "",
        P + "ddlGrupoActos": "",
        P + "ddlActos": "",
        P + "rblDias": "todos",
        P + "btnSearch": "Pesquisar",
    }


def run(c: httpx.Client, tag: str, **over) -> str:
    html = c.get(URL).text
    data = base(html)
    data.update(over)
    r = c.post(URL, data=data, headers={**HEADERS, "Referer": URL, "X-MicrosoftAjax": "Delta=true"})
    txt = r.text
    (OUT / f"s8_{tag}.txt").write_text(txt, encoding="utf-8")
    n_tab = len(re.findall(r"<table", txt))
    msg = re.search(r'id="ctl00_ContentPlaceHolder1_lblMsg"[^>]*>(.*?)</', txt, re.S)
    msg_t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", msg.group(1))).strip() if msg else ""
    panels = re.findall(r"\|updatePanel\|([^|]+)\|", txt)
    print(f"[{tag}] len={len(txt)} tables={n_tab} panels={panels} lblMsg={msg_t[:120]!r} erro={'erro.htm' in r.url.path or 'erro' in str(r.url)}")
    return txt


def main() -> None:
    with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=120) as c:
        run(c, "dias30", **{P + "rblDias": "30"})
        run(c, "dias15", **{P + "rblDias": "15"})
        run(c, "nomeLDA", **{P + "rblTipo": "nome", P + "txtPesquisa": "LDA"})
        run(c, "datas_longas", **{P + "txtCalendarDesde": "01/01/2026", P + "txtCalendarAte": "30/06/2026"})
        run(c, "datas_certas30", **{P + "txtCalendarDesde": "24/08/2026", P + "txtCalendarAte": "23/09/2026"})
        run(c, "grupo20", **{P + "ddlGrupoActos": "20", P + "rblDias": "30"})
        run(c, "nif_pt", **{P + "rblTipo": "nif", P + "txtPesquisa": "500189412"})


if __name__ == "__main__":
    main()
