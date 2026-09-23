"""Sonda 21 — listar as chaves do delta e extrair o painel de resultados (ids com `_`)."""
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
_TYPES = (
    "updatePanel|hiddenField|script|arrayDeclaration|asyncPostBackControlIDs|postBackControlIDs|"
    "updatePanelIDs|childUpdatePanelIDs|panelsToRefreshIDs|asyncPostBackTimeout|formAction|pageTitle|"
    "pageRedirect|focus"
)
_REC = re.compile(r"(\d+)\|(" + _TYPES + r")\|([^|]*)\|")


def parse_delta(delta: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for m in _REC.finditer(delta):
        length = int(m.group(1))
        content = delta[m.end(): m.end() + length]
        out[f"{m.group(2)}:{m.group(3)}"] = content
    return out


def hidden(html: str, name: str) -> str:
    m = re.search(r'id="' + name.replace("$", r"\$") + r'"[^>]*value="([^"]*)"', html)
    return m.group(1) if m else ""


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s.replace("\xa0", " "))).strip()


def main() -> None:
    with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=120) as c:
        html = c.get(URL).text
        data = {
            SM: f"{P}UpdatePanel1|{P}btnSearch",
            "__EVENTTARGET": P + "btnSearch", "__EVENTARGUMENT": "", "__LASTFOCUS": "",
            "__VIEWSTATE": hidden(html, "__VIEWSTATE"),
            "__VIEWSTATEGENERATOR": hidden(html, "__VIEWSTATEGENERATOR"),
            "__VIEWSTATEENCRYPTED": "",
            "__EVENTVALIDATION": hidden(html, "__EVENTVALIDATION"),
            P + "txtPesquisa": "", P + "rblTipo": "nif", P + "txtNumeroProcesso": "",
            P + "txtCalendarDesde": "01/09/2026", P + "txtCalendarAte": "23/09/2026",
            P + "ddlTribunais": "", P + "ddlGrupoActos": "", P + "ddlActos": "",
            P + "rblDias": "todos", "__ASYNCPOST": "true",
        }
        r = c.post(URL, data=data, headers={"Referer": URL})
        panels = parse_delta(r.text)
        print("resp:", len(r.text))
        for k, v in panels.items():
            kind, ident = k.split(":", 1)
            print(f"  {kind:28} {ident:50} len={len(v)}")
        panel = next((v for k, v in panels.items() if k.endswith("upResultados")), "")
        (OUT / "p1c.html").write_text(panel, encoding="utf-8")
        txt = norm(panel)
        cnt = re.search(r"([\d\.]+)\s+documentos encontrados", txt)
        print("\nitens (divs):", panel.count('class="resultadocdital"'), "total:", cnt.group(1) if cnt else "-")
        print("texto:", txt[:300])


if __name__ == "__main__":
    main()
