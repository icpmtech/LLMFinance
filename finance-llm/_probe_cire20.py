"""Sonda 20 — parser correto do delta ASP.NET + extração de itens, paginação e link do documento."""
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
    "pageRedirect|focus|hiddenField"
)
_REC = re.compile(r"(\d+)\|(" + _TYPES + r")\|([^|]*)\|")


def parse_delta(delta: str) -> dict[str, str]:
    """Devolve {'id': conteúdo} (e 'hiddenField:__X' para os campos escondidos).

    O formato dos registos é ``comprimento|tipo|id|conteúdo|``; os ids dos painéis
    vêm com ``_`` no lugar dos ``$`` de ``UniqueID``.
    """
    out: dict[str, str] = {}
    for m in _REC.finditer(delta):
        length = int(m.group(1))
        kind, ident = m.group(2), m.group(3)
        content = delta[m.end(): m.end() + length]
        out[ident] = content
        out[f"{kind}:{ident}"] = content
    return out


def hidden(html: str, name: str) -> str:
    m = re.search(r'id="' + name.replace("$", r"\$") + r'"[^>]*value="([^"]*)"', html)
    return m.group(1) if m else ""


def norm(s: str) -> str:
    s = s.replace("\xa0", " ")
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s)).strip()


def post(c: httpx.Client, delta_from: str, target: str, manager: str, **over) -> dict[str, str]:
    html = c.get(URL).text if not over.pop("_reuse", False) else None
    data = {
        SM: manager,
        "__EVENTTARGET": target,
        "__EVENTARGUMENT": "",
        "__LASTFOCUS": "",
        "__VIEWSTATE": hidden(html, "__VIEWSTATE") if html else over.pop("__VIEWSTATE", ""),
        "__VIEWSTATEGENERATOR": hidden(html, "__VIEWSTATEGENERATOR") if html else "C35E1E25",
        "__VIEWSTATEENCRYPTED": "",
        "__EVENTVALIDATION": hidden(html, "__EVENTVALIDATION") if html else over.pop("__EVENTVALIDATION", ""),
        P + "txtPesquisa": "", P + "rblTipo": "nif", P + "txtNumeroProcesso": "",
        P + "txtCalendarDesde": "", P + "txtCalendarAte": "",
        P + "ddlTribunais": "", P + "ddlGrupoActos": "", P + "ddlActos": "",
        P + "rblDias": "todos", "__ASYNCPOST": "true",
    }
    data.update({k: v for k, v in over.items() if v is not None})
    r = c.post(URL, data=data, headers={"Referer": URL})
    return parse_delta(r.text)


def parse_items(panel: str) -> list[dict]:
    items: list[dict] = []
    chunks = re.split(r'<div class="resultadocdital">', panel)[1:]
    for chunk in chunks:
        blk = re.split(r'<div id="ctl00_ContentPlaceHolder1_dlResultados_ctl\d+_pnlPDF"', chunk)[0]
        flat = re.sub(r"\s+", " ", blk)
        fields: dict[str, str] = {}
        for m in re.finditer(r"<strong>([^<]+?)\s*:?\s*</strong>\s*(?:&nbsp;)?\s*(.*?)(?=<br\s*/?>|$)", flat, re.S):
            key = norm(m.group(1)).rstrip(":").strip()
            val = norm(m.group(2))
            if key and val:
                fields.setdefault(key, val)
        # intervenientes: blocos InterDataList com label e NIF
        intervenientes = []
        for m in re.finditer(r'<span id="[^"]*InterDataList"[^>]*>(.*?)</span>\s*(?:<br\s*/?>|$)', flat, re.S):
            seg = m.group(1)
            nome = re.search(r"<strong>([^<]+)\s*:?\s*</strong>\s*(.*?)(?:<br\s*/?>|$)", seg, re.S)
            nif = re.search(r"<strong>\s*NIF/NIPC\s*:?\s*</strong>\s*([\dA-Za-z]+)", seg)
            if nome:
                intervenientes.append({"papel": norm(nome.group(1)).rstrip(":").strip(),
                                       "nome": norm(nome.group(2)),
                                       "nif": nif.group(1) if nif else None})
        qs = re.search(r"id='queryString'\s*type='hidden'\s*value=([^\s>]+)", flat, re.I) or \
             re.search(r'id="queryString"\s*type="hidden"\s*value=([^\s>]+)', flat, re.I)
        fields["_intervenientes"] = intervenientes
        fields["_doc_token"] = qs.group(1).replace("&amp;", "&") if qs else None
        items.append(fields)
    return items


def main() -> None:
    with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=120) as c:
        panels = post(c, "", P + "btnSearch", f"{P}UpdatePanel1|{P}btnSearch",
                      **{P + "txtCalendarDesde": "01/09/2026", P + "txtCalendarAte": "23/09/2026"})
        panel = next((v for k, v in panels.items() if k.endswith("upResultados")), "")
        (OUT / "p1b.html").write_text(panel, encoding="utf-8")
        items = parse_items(panel)
        txt = norm(panel)
        cnt = re.search(r"([\d\.]+)\s+documentos encontrados", txt)
        page = re.search(r'Pager1_lblPageNumber"[^>]*>(\d+)<', panel)
        print(f"painel={len(panel)} itens={len(items)} total={cnt.group(1) if cnt else '-'} página={page.group(1) if page else '-'}")
        first = items[0] if items else {}
        for k, v in first.items():
            print(f"   {k} = {v}")

        # página seguinte: reutilizar ViewState devolvido no delta
        vs = panels.get("__VIEWSTATE", "") or panels.get("hiddenField:__VIEWSTATE", "")
        ev = panels.get("__EVENTVALIDATION", "") or panels.get("hiddenField:__EVENTVALIDATION", "")
        print("novo viewstate:", len(vs), "novo eventvalidation:", len(ev))
        html = c.get(URL).text
        data2 = {
            SM: f"{P}upResultados|{P}Pager1$lnkNext",
            "__EVENTTARGET": P + "Pager1$lnkNext",
            "__EVENTARGUMENT": "",
            "__LASTFOCUS": "",
            "__VIEWSTATE": vs or hidden(html, "__VIEWSTATE"),
            "__VIEWSTATEGENERATOR": "C35E1E25",
            "__VIEWSTATEENCRYPTED": "",
            "__EVENTVALIDATION": ev or hidden(html, "__EVENTVALIDATION"),
            P + "txtPesquisa": "", P + "rblTipo": "nif", P + "txtNumeroProcesso": "",
            P + "txtCalendarDesde": "01/09/2026", P + "txtCalendarAte": "23/09/2026",
            P + "ddlTribunais": "", P + "ddlGrupoActos": "", P + "ddlActos": "",
            P + "rblDias": "todos", "__ASYNCPOST": "true",
        }
        r2 = c.post(URL, data=data2, headers={"Referer": URL})
        panels2 = parse_delta(r2.text)
        panel2 = next((v for k, v in panels2.items() if k.endswith("upResultados")), "")
        (OUT / "p2b.html").write_text(panel2, encoding="utf-8")
        items2 = parse_items(panel2)
        pg2 = re.search(r'Pager1_lblPageNumber"[^>]*>(\d+)<', panel2)
        print(f"página {pg2.group(1) if pg2 else '?'}: itens={len(items2)}")
        if items2:
            print("   refs p2:", [i.get("Referência") for i in items2][:4])
        print("   refs p1:", [i.get("Referência") for i in items][:4])

        # PDF do primeiro item
        tok = first.get("_doc_token")
        if tok:
            for url in (f"{URL.rsplit('/', 1)[0]}/Viewer/MostraPdf.aspx?{tok}",
                        f"{URL.rsplit('/', 1)[0]}/Viewer/MostraPdf.aspx?queryString={tok}",
                        f"{URL.rsplit('/', 1)[0]}/Viewer/MostraPdf.aspx?qs={tok}"):
                rp = c.get(url, headers={"Referer": URL})
                ct = rp.headers.get("content-type", "")
                print(f"  PDF {url[-60:]} -> {rp.status_code} {ct} len={len(rp.content)}")
                if rp.status_code == 200 and len(rp.content) > 1000:
                    (OUT / "doc.pdf").write_bytes(rp.content)
                    print("   guardado doc.pdf")
                    break


if __name__ == "__main__":
    main()
