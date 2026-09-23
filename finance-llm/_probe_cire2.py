"""Sonda 2 — submeter pesquisa no CIRE (sem captcha) e mapear a grelha de resultados."""
from __future__ import annotations

import re
from pathlib import Path

import httpx

URL = "https://www.citius.mj.pt/portal/consultas/ConsultasCire.aspx"
OUT = Path(__file__).parent / "_probe_cire_out"
OUT.mkdir(exist_ok=True)

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


def radios(html: str) -> None:
    for m in re.finditer(r'<input[^>]*name="ctl00\$ContentPlaceHolder1\$(rblTipo|rblDias)"[^>]*>', html):
        tag = m.group(0)
        val = re.search(r'value="([^"]*)"', tag)
        after = re.sub(r"<[^>]+>", " ", html[m.end():m.end() + 400])
        after = re.sub(r"\s+", " ", after).strip()[:80]
        print(f"RADIO {m.group(1)} = {val.group(1) if val else None!r} | {after}")


def show_grid(html: str, tag: str) -> None:
    print(f"\n=== {tag} ===")
    m = re.search(r'id="ctl00_ContentPlaceHolder1_lblMsg"[^>]*>(.*?)</', html, re.S)
    if m:
        print("lblMsg:", re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m.group(1))).strip()[:200])
    tables = re.findall(r"<table[^>]*id=\"(ctl00_ContentPlaceHolder1_[^\"]*)\"", html)
    print("tables:", tables)
    grid = re.search(r"<table[^>]*id=\"ctl00_ContentPlaceHolder1_gvResultados\"(.*?)</table>", html, re.S)
    if not grid:
        grid = re.search(r"<table[^>]*>(?:(?!</table>).)*?Resultados?(?:(?!</table>).)*?</table>", html, re.S)
    if grid:
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", grid.group(0), re.S)
        for i, r in enumerate(rows[:4]):
            cells = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", c)).strip() for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", r, re.S)]
            links = re.findall(r'href="([^"]+)"', r)
            print(f"  row{i}: cells={len(cells)} {cells[:8]}")
            if links:
                print(f"        links={links[:3]}")
    for pat in (r"Page\$Next", r"Page\$Previous", r"gvResultados", r"____", r"lblTotal"):
        if re.search(pat, html):
            print("  contém:", pat)
    # paginação
    for m in re.finditer(r'<a[^>]*href="javascript:__doPostBack\(&#39;([^&]*?)&#39;', html):
        print("  postback:", m.group(1)[:80])
    (OUT / f"grid_{tag}.html").write_text(html, encoding="utf-8")


def main() -> None:
    with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=60) as c:
        r = c.get(URL)
        html = r.text
        radios(html)
        base = {
            "__EVENTTARGET": "",
            "__EVENTARGUMENT": "",
            "__VIEWSTATE": hidden(html, "__VIEWSTATE"),
            "__VIEWSTATEGENERATOR": hidden(html, "__VIEWSTATEGENERATOR"),
            "__EVENTVALIDATION": hidden(html, "__EVENTVALIDATION"),
            P + "txtPesquisa": "",
            P + "rblTipo": "0",
            P + "txtNumeroProcesso": "",
            P + "txtCalendarDesde": "01/09/2026",
            P + "txtCalendarAte": "23/09/2026",
            P + "ddlTribunais": "",
            P + "ddlGrupoActos": "",
            P + "ddlActos": "",
            P + "rblDias": "0",
            P + "btnSearch": "Pesquisar",
        }
        r2 = c.post(URL, data=base, headers={**HEADERS, "Referer": URL, "Content-Type": "application/x-www-form-urlencoded"})
        print("\nPOST", r2.status_code, "len", len(r2.content))
        show_grid(r2.text, "01")


if __name__ == "__main__":
    main()
