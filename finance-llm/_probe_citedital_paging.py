"""Paginador + ordenação da «Citação e Notificação Edital» (CITIUS).

Confirma que o postback de paginação funciona com um POST normal (sem delta) e
que os resultados vêm ordenados por data descendente (para permitir parar a
recolha ao passar o limite pedido, ex.: últimos 6 meses).
"""
from __future__ import annotations

import re

import requests

URL = "https://www.citius.mj.pt/portal/consultas/ConsultasCitEdital.aspx"
PREFIX = "ctl00$ContentPlaceHolder1$"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.8",
    "Referer": URL,
}


def state(html: str) -> dict:
    def value(name: str) -> str:
        m = re.search(r'id="' + name + r'"[^>]*value="([^"]*)"', html)
        return m.group(1) if m else ""

    return {
        "__EVENTTARGET": "",
        "__EVENTARGUMENT": "",
        "__LASTFOCUS": "",
        "__VIEWSTATE": value("__VIEWSTATE"),
        "__VIEWSTATEGENERATOR": value("__VIEWSTATEGENERATOR"),
        "__VIEWSTATEENCRYPTED": value("__VIEWSTATEENCRYPTED"),
        "__EVENTVALIDATION": value("__EVENTVALIDATION"),
    }


def clean(fragment: str) -> str:
    text = re.sub(r"<[^>]+>", " ", fragment or "")
    import html as _html

    text = _html.unescape(text).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def items(html: str) -> list[dict]:
    out = []
    for block in re.findall(
        r'<div class="resultadocdital">(.*?)</div>\s*(?=<div class="resultadocdital">|</span>)', html, re.S
    ):
        flat = re.sub(r"<br\s*/?>", "|", block)
        flat = re.sub(r"<strong>(.*?)</strong>", r"\1", flat, flags=re.S)
        flat = clean(flat)
        fields = dict(
            (k.strip(), v.strip())
            for k, v in (part.split(":", 1) for part in flat.split("|") if ":" in part)
        )
        out.append(fields)
    return out


def count(html: str) -> int:
    m = re.search(r"([\d\.\s]+)\s+editais encontrados", clean(html))
    return int(re.sub(r"\D", "", m.group(1))) if m else 0


def page_number(html: str) -> int:
    m = re.search(r'Pager1_lblPageNumber"[^>]*>\s*(\d+)\s*<', html)
    return int(m.group(1)) if m else 1


def main() -> int:
    s = requests.Session()
    s.headers.update(HEADERS)
    html = s.get(URL, timeout=60).content.decode("utf-8", errors="replace")
    print("total declarado:", count(html))
    data = dict(state(html))
    data[PREFIX + "txtNome"] = "SILVA"
    data[PREFIX + "rblDias"] = "todos"
    data[PREFIX + "ddlTribunais"] = "todos"
    data[PREFIX + "btnSearch"] = "Pesquisar"
    html = s.post(URL, data=data, timeout=90).content.decode("utf-8", errors="replace")
    print("total:", count(html), "| página", page_number(html))
    rows = items(html)
    print(f"  {len(rows)} itens: ", [r.get("Data") for r in rows])

    for step in range(1, 3):
        data = dict(state(html))
        data["__EVENTTARGET"] = PREFIX + "Pager1$lnkNext"
        data[PREFIX + "txtNome"] = "SILVA"
        data[PREFIX + "rblDias"] = "todos"
        data[PREFIX + "ddlTribunais"] = "todos"
        html = s.post(URL, data=data, timeout=90).content.decode("utf-8", errors="replace")
        rows = items(html)
        print(f"  página {page_number(html)}: {len(rows)} itens", [r.get("Data") for r in rows])

    # Sem critérios: o que faz o portal?
    html2 = s.get(URL, timeout=60).content.decode("utf-8", errors="replace")
    data = dict(state(html2))
    data[PREFIX + "txtNome"] = ""
    data[PREFIX + "rblDias"] = "todos"
    data[PREFIX + "ddlTribunais"] = "todos"
    data[PREFIX + "btnSearch"] = "Pesquisar"
    html3 = s.post(URL, data=data, timeout=90).content.decode("utf-8", errors="replace")
    print("\nsem nome -> itens:", len(items(html3)), "| texto:", clean(html3)[:0] or "")
    for pat in ("obrigat", "Introduza", "introduza", "aviso", "Aviso", "erro"):
        for m in list(re.finditer(pat, html3))[:2]:
            print("  ...", clean(html3[max(0, m.start() - 120): m.end() + 120]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
