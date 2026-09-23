"""Sonda 16 — fechar o desenho do coletor CIRE: paginação, PDF (Ver Mais), robots.txt, itens/página."""
from __future__ import annotations

import re
from pathlib import Path

import httpx

BASE = "https://www.citius.mj.pt/portal/consultas/"
URL = BASE + "ConsultasCire.aspx"
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


def parse_delta(delta: str):
    parts, i, n = [], 0, len(delta)
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
        parts.append((kind, ident, delta[start:start + length]))
        i = start + length
        if i < n and delta[i] == "|":
            i += 1
    return dict((ident, content) for kind, ident, content in parts if kind == "updatePanel")


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s)).strip()


def items_from(panel: str) -> list[dict]:
    out = []
    for chunk in re.split(r'<div class="resultadocdital">', panel)[1:]:
        chunk = re.split(r'<div id="ctl00_ContentPlaceHolder1_dlResultados_ctl\d+_pnlPDF"', chunk)[0]
        fields: dict[str, str] = {}
        for m in re.finditer(r"<strong>([^<]+?):?\s*</strong>\s*(?:&nbsp;)?\s*(.*?)(?:<br />|$)", chunk, re.S):
            key = norm(m.group(1)).rstrip(":").strip()
            val = norm(m.group(2))
            if key and val:
                fields.setdefault(key, val)
        out.append(fields)
    return out


def main() -> None:
    with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=120) as c:
        print("robots:", c.get("https://www.citius.mj.pt/robots.txt").status_code,
              c.get("https://www.citius.mj.pt/robots.txt").text[:200].replace("\n", " | "))
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
            P + "txtCalendarDesde": "14/09/2026", P + "txtCalendarAte": "23/09/2026",
            P + "ddlTribunais": "", P + "ddlGrupoActos": "", P + "ddlActos": "",
            P + "rblDias": "todos", "__ASYNCPOST": "true",
        }
        r = c.post(URL, data=data, headers={**HEADERS, "Referer": URL, "X-MicrosoftAjax": "Delta=true"})
        panels = parse_delta(r.text)
        res = panels.get(P + "upResultados", "")
        (OUT / "p1.html").write_text(res, encoding="utf-8")
        items = items_from(res)
        print("página 1: itens =", len(items))
        print("total:", re.search(r"([\d\.]+)\s+documentos", norm(res)).group(1) if re.search(r"([\d\.]+)\s+documentos", norm(res)) else "?")
        print("1.º item:", items[0] if items else None)
        # capturar ViewState novo para o próximo pedido
        vs = panels.get("__VIEWSTATE", "")
        ev = panels.get("__EVENTVALIDATION", "")
        print("viewstate delta:", len(vs), "eventvalidation delta:", len(ev), "| chaves:", list(panels.keys())[:12])

        # paginação: usar o ViewState NOVO da resposta
        data2 = dict(data)
        data2.update({
            SM: f"{P}upResultados|{P}Pager1$lnkNext",
            "__EVENTTARGET": P + "Pager1$lnkNext",
            "__VIEWSTATE": vs or data["__VIEWSTATE"],
            "__EVENTVALIDATION": ev or data["__EVENTVALIDATION"],
        })
        r2 = c.post(URL, data=data2, headers={**HEADERS, "Referer": URL, "X-MicrosoftAjax": "Delta=true"})
        panels2 = parse_delta(r2.text)
        res2 = panels2.get(P + "upResultados", "")
        items2 = items_from(res2)
        print("página 2: itens =", len(items2))
        page = re.search(r'Pager1_lblPageNumber"[^>]*>(\d+)<', res2)
        print("nº de página:", page.group(1) if page else "?")
        print("2.º item (pág.2):", items2[0] if items2 else None)
        # repetições entre páginas
        k1 = {i.get("Referência") for i in items}
        k2 = {i.get("Referência") for i in items2}
        print("sobreposição refs:", len(k1 & k2))

        # PDF: extrair queryString do primeiro item da página 1
        m = re.search(r"<input id='queryString' type='hidden' value=([^\s>]+)", res, re.I)
        print("queryString:", (m.group(1)[:60] + "...") if m else None)
        if m:
            qs = m.group(1).replace("&amp;", "&")
            for path in ("Viewer/MostraPdf.aspx", "MostraPdf.aspx", "Viewer/MostraPdf.aspx?queryString="):
                url = BASE + path if "?" not in path else BASE + path + qs
                try:
                    rp = c.get(url, headers={**HEADERS, "Referer": URL}, timeout=60)
                    print(f"  {path} -> {rp.status_code} {rp.headers.get('content-type')} len={len(rp.content)}")
                    if rp.headers.get("content-type", "").startswith("application/pdf"):
                        (OUT / "doc.pdf").write_bytes(rp.content)
                        print("   PDF guardado em _probe_cire_out/doc.pdf")
                        break
                except Exception as exc:  # noqa: BLE001
                    print("  erro", path, exc)
        # JS do viewer
        js = c.get(BASE + "Viewer/DocumentoViewer.js", headers=HEADERS)
        print("DocumentoViewer.js:", js.status_code, len(js.text))
        i = js.text.find("Ver")
        print("  trecho:", re.sub(r"\s+", " ", js.text[i:i + 900])[:900])


if __name__ == "__main__":
    main()
