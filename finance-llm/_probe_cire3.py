"""Sonda 3 — depurar o POST do CIRE: imprimir a resposta à procura de erros e da grelha."""
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


def form(html: str) -> dict:
    return {
        "__EVENTTARGET": "",
        "__EVENTARGUMENT": "",
        "__VIEWSTATE": hidden(html, "__VIEWSTATE"),
        "__VIEWSTATEGENERATOR": hidden(html, "__VIEWSTATEGENERATOR"),
        "__EVENTVALIDATION": hidden(html, "__EVENTVALIDATION"),
        P + "txtPesquisa": "",
        P + "rblTipo": "nome",
        P + "txtNumeroProcesso": "",
        P + "txtCalendarDesde": "01/09/2026",
        P + "txtCalendarAte": "23/09/2026",
        P + "ddlTribunais": "",
        P + "ddlGrupoActos": "",
        P + "ddlActos": "",
        P + "rblDias": "todos",
        P + "btnSearch": "Pesquisar",
    }


def main() -> None:
    with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=60) as c:
        html = c.get(URL).text
        r = c.post(URL, data=form(html), headers={"Referer": URL})
        print("POST", r.status_code, "len", len(r.content), "url", r.url)
        body = r.text
        (OUT / "post_body.html").write_text(body, encoding="utf-8")
        print("---- body (1000) ----")
        print(re.sub(r"\s+", " ", body)[:1200])
        print("---- sinais ----")
        for pat in ("lblMsg", "gvResultados", "GridView", "erro", "Erro", "ErroException", "AspxAutoDetect",
                    "Page$Next", "Resultado", "NoBot", "captcha"):
            if re.search(pat, body, re.I):
                print("  tem:", pat)
        print("---- texto visível ----")
        txt = re.sub(r"<script.*?</script>", " ", body, flags=re.S | re.I)
        txt = re.sub(r"<[^>]+>", " ", txt)
        print(re.sub(r"\s+", " ", txt).strip()[:800])


if __name__ == "__main__":
    main()
