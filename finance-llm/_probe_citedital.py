"""Sonda da página «Citação e Notificação Edital» do CITIUS.

Lê o formulário (inputs/selects/botões), guarda o HTML e tenta uma pesquisa
por nome para perceber a forma dos resultados.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import requests

URL = "https://www.citius.mj.pt/portal/consultas/ConsultasCitEdital.aspx"
OUT = Path(__file__).with_name("logs") / "citedital"
OUT.mkdir(parents=True, exist_ok=True)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.8",
    "Referer": URL,
}


def form_elements(html: str) -> dict:
    out: dict = {"inputs": [], "selects": [], "buttons": [], "textareas": []}
    for m in re.finditer(r"<input\b([^>]*)/?>", html, re.I):
        attrs = m.group(1)
        def attr(name: str) -> str:
            a = re.search(name + r'\s*=\s*"([^"]*)"', attrs, re.I)
            return a.group(1) if a else ""
        out["inputs"].append(
            {
                "id": attr("id"),
                "name": attr("name"),
                "type": (attr("type") or "text").lower(),
                "value": attr("value")[:80],
            }
        )
    for m in re.finditer(r"<select\b([^>]*)>(.*?)</select>", html, re.S | re.I):
        attrs, body = m.group(1), m.group(2)
        sel_id = re.search(r'id="([^"]*)"', attrs, re.I)
        opts = [
            {"value": o.group(1), "label": re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", o.group(2))).strip()}
            for o in re.finditer(r'<option\b[^>]*value="([^"]*)"[^>]*>(.*?)</option>', body, re.S | re.I)
        ]
        out["selects"].append({"id": sel_id.group(1) if sel_id else "", "options": opts})
    for m in re.finditer(r"<(?:a|input)\b([^>]*)(?:onclick|href)=\"([^\"]*)\"([^>]*)>", html, re.I):
        pass
    for m in re.finditer(r'<a\b[^>]*id="([^"]*)"[^>]*href="([^"]*)"', html, re.I):
        out["buttons"].append({"id": m.group(1), "href": m.group(2)[:80]})
    for m in re.finditer(r"<textarea\b([^>]*)>", html, re.I):
        t = re.search(r'id="([^"]*)"', m.group(1), re.I)
        out["textareas"].append({"id": t.group(1) if t else ""})
    return out


def main() -> int:
    s = requests.Session()
    s.headers.update(HEADERS)
    r = s.get(URL, timeout=60)
    print("GET", r.status_code, len(r.content), "bytes")
    html = r.content.decode("utf-8", errors="replace")
    (OUT / "form.html").write_text(html, encoding="utf-8")

    els = form_elements(html)
    (OUT / "form.json").write_text(json.dumps(els, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n--- inputs ---")
    for i in els["inputs"]:
        print(f"  {i['type']:10} name={i['name']!r} id={i['id']!r} value={i['value']!r}")
    print("\n--- selects ---")
    for sel in els["selects"]:
        print(f"  {sel['id']}: {len(sel['options'])} opções")
        for o in sel["options"][:20]:
            print(f"      {o['value']!r} -> {o['label']!r}")
    print("\n--- textareas ---")
    for t in els["textareas"]:
        print("  ", t["id"])

    # Guardar o estado do formulário e tentar uma pesquisa.
    def value(name: str) -> str:
        m = re.search(r'id="' + name.replace("$", r"\$") + r'"[^>]*value="([^"]*)"', html)
        return m.group(1) if m else ""

    state = {
        "__EVENTTARGET": value("__EVENTTARGET"),
        "__EVENTARGUMENT": value("__EVENTARGUMENT"),
        "__LASTFOCUS": value("__LASTFOCUS"),
        "__VIEWSTATE": value("__VIEWSTATE"),
        "__VIEWSTATEGENERATOR": value("__VIEWSTATEGENERATOR"),
        "__VIEWSTATEENCRYPTED": value("__VIEWSTATEENCRYPTED"),
        "__EVENTVALIDATION": value("__EVENTVALIDATION"),
    }
    print("\nviewstate:", len(state["__VIEWSTATE"]), "chars")

    prefix = "ctl00$ContentPlaceHolder1$"
    search_term = sys.argv[1] if len(sys.argv) > 1 else "SILVA"
    data = dict(state)
    for name in ("txtPesquisa", "txtNome", "txtInterveniente", "txtTexto"):
        data[prefix + name] = search_term
    data[prefix + "btnSearch"] = "Pesquisar"
    data["__EVENTTARGET"] = ""
    data["__EVENTARGUMENT"] = ""
    r2 = s.post(URL, data=data, timeout=90, headers={"Referer": URL})
    print("POST", r2.status_code, len(r2.content), "bytes")
    html2 = r2.content.decode("utf-8", errors="replace")
    (OUT / "search.html").write_text(html2, encoding="utf-8")
    text2 = re.sub(r"<[^>]+>", " ", html2)
    text2 = re.sub(r"\s+", " ", text2)
    print(text2[:2500])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
