"""Sonda 13 — replicar EXATAMENTE o postback assíncrono do browser (incluindo ScriptManager1)."""
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
    "X-MicrosoftAjax": "Delta=true",
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "*/*",
}
P = "ctl00$ContentPlaceHolder1$"
SM = P + "ScriptManager1"


def hidden(html: str, name: str) -> str:
    m = re.search(r'id="' + name.replace("$", r"\$") + r'"[^>]*value="([^"]*)"', html)
    return m.group(1) if m else ""


def payload(html: str, manager: str, target: str, **over) -> dict:
    data = {
        SM: manager,
        "__EVENTTARGET": target,
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
        "__ASYNCPOST": "true",
    }
    data.update(over)
    return data


def refresh_ids(delta: str) -> str:
    m = re.search(r"\|panelsToRefreshIDs\|[^|]*\|([^|]*)\|", delta)
    return m.group(1) if m else "?"


def main() -> None:
    with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=120) as c:
        html = c.get(URL).text
        variants = {
            "sfm_target_vazio": (f"{P}UpdatePanel1|{P}btnSearch", "", {}),
            "sfm_target_btn": (f"{P}UpdatePanel1|{P}btnSearch", P + "btnSearch", {}),
            "sfm_target_btn_datas": (f"{P}UpdatePanel1|{P}btnSearch", P + "btnSearch",
                                     {P + "txtCalendarDesde": "01/09/2026", P + "txtCalendarAte": "23/09/2026"}),
            "sfm_upResultados": (f"{P}upResultados|{P}btnSearch", "", {}),
        }
        for tag, (mgr, tgt, over) in variants.items():
            r = c.post(URL, data=payload(html, mgr, tgt, **over), headers={"Referer": URL})
            txt = r.text
            (OUT / f"v_{tag}.txt").write_text(txt, encoding="utf-8")
            n_tab = len(re.findall(r"<table", txt))
            print(f"[{tag}] len={len(txt)} tables={n_tab} refresh={refresh_ids(txt)[:120]}")


if __name__ == "__main__":
    main()
