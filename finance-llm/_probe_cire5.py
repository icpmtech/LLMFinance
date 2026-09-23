"""Sonda 5 — postback assíncrono (UpdatePanel) no CIRE e extração da grelha de resultados."""
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


def form(html: str, **over) -> dict:
    data = {
        "__EVENTTARGET": "",
        "__EVENTARGUMENT": "",
        "__LASTFOCUS": "",
        "__VIEWSTATE": hidden(html, "__VIEWSTATE"),
        "__VIEWSTATEGENERATOR": hidden(html, "__VIEWSTATEGENERATOR"),
        "__VIEWSTATEENCRYPTED": hidden(html, "__VIEWSTATEENCRYPTED"),
        "__EVENTVALIDATION": hidden(html, "__EVENTVALIDATION"),
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
    data.update(over)
    return data


def post_async(c: httpx.Client, html: str, **over) -> str:
    data = form(html, **over)
    data["__ASYNCPOST"] = "true"
    h = {**HEADERS, "Referer": URL, "X-MicrosoftAjax": "Delta=true", "Cache-Control": "no-cache"}
    r = c.post(URL, data=data, headers=h)
    return r.text


def show(txt: str, tag: str) -> None:
    (OUT / f"async_{tag}.txt").write_text(txt, encoding="utf-8")
    print(f"--- {tag}: len={len(txt)}")
    parts = txt.split("|")
    print("   cabeça:", parts[:8])
    for i, part in enumerate(parts):
        low = part.lower()
        if "resultados" in low or "gv" in low or "lblmsg" in low:
            print(f"   [{i}] {part[:60]!r} -> {parts[i+1][:120]!r}" if i + 1 < len(parts) else f"   [{i}] {part!r}")
    # procurar tabela
    for m in re.finditer(r'<table[^>]*id="([^"]+)"', txt):
        print("   table:", m.group(1))
    msg = re.search(r'id="ctl00_ContentPlaceHolder1_lblMsg"[^>]*>(.*?)</', txt, re.S)
    if msg:
        print("   lblMsg:", re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", msg.group(1))).strip()[:200])
    # texto
    plain = re.sub(r"<[^>]+>", " ", txt)
    plain = re.sub(r"\s+", " ", plain).strip()
    print("   texto:", plain.encode("cp1252", "replace").decode()[:400])


def main() -> None:
    with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=90) as c:
        html = c.get(URL).text
        # A) intervalo de datas
        show(post_async(c, html, **{P + "txtCalendarDesde": "01/09/2026", P + "txtCalendarAte": "23/09/2026",
                                    "__EVENTTARGET": P + "btnSearch", P + "btnSearch": "Pesquisar"}), "datas")
        # B) últimos N dias
        html2 = c.get(URL).text
        show(post_async(c, html2, **{P + "rblDias": "30", "__EVENTTARGET": P + "btnSearch"}), "dias30")


if __name__ == "__main__":
    main()
