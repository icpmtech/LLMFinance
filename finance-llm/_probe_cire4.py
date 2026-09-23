"""Sonda 4 — extrair TODOS os campos do formulário CIRE e replicar o POST tal e qual."""
from __future__ import annotations

import re
from html.parser import HTMLParser
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


class FormParser(HTMLParser):
    """Recolhe inputs/selects/textarea do formulário aspnetForm."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_form = False
        self.fields: list[dict] = []
        self._select: dict | None = None
        self._opt: dict | None = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "form":
            self.in_form = a.get("id") == "aspnetForm" or self.in_form
        elif not self.in_form:
            return
        elif tag == "input":
            self.fields.append({"tag": "input", **a})
        elif tag == "select":
            self._select = {"tag": "select", **a, "options": []}
        elif tag == "option" and self._select is not None:
            self._opt = dict(a)
        elif tag == "textarea":
            self.fields.append({"tag": "textarea", **a, "value": ""})

    def handle_endtag(self, tag):
        if tag == "select" and self._select is not None:
            self.fields.append(self._select)
            self._select = None
            self._opt = None
        elif tag == "form":
            self.in_form = False

    def handle_data(self, data):
        if self._opt is not None:
            self._opt["text"] = (self._opt.get("text", "") + data).strip()
        elif self.fields and self.fields[-1]["tag"] == "textarea":
            self.fields[-1]["value"] += data


def main() -> None:
    with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=60) as c:
        html = c.get(URL).text
        p = FormParser()
        p.feed(html)
        data: dict[str, str] = {}
        radios: dict[str, list[str]] = {}
        for f in p.fields:
            name = f.get("name")
            if not name:
                continue
            if f["tag"] == "input":
                t = (f.get("type") or "text").lower()
                if t in ("checkbox", "radio"):
                    vals = radios.setdefault(name, [])
                    if t == "radio":
                        vals.append(f.get("value", ""))
                    if "checked" in f:
                        data[name] = f.get("value", "")
                    elif t == "checkbox":
                        data.setdefault(name, "")
                elif t in ("submit", "button", "image"):
                    data.setdefault(name, f.get("value", ""))
                else:
                    data[name] = f.get("value", "")
            elif f["tag"] == "select":
                sel = ""
                for o in f["options"]:
                    if "selected" in o:
                        sel = o.get("value", "")
                if not sel and f["options"]:
                    sel = f["options"][0].get("value", "")
                data[name] = sel
            else:
                data[name] = f.get("value", "")
        print("campos:", len(data), "| radios:", radios)
        print("nomes:", sorted(data.keys()))
        # preencher critérios
        P = "ctl00$ContentPlaceHolder1$"
        data[P + "rblTipo"] = "nome"
        data[P + "txtCalendarDesde"] = "01/09/2026"
        data[P + "txtCalendarAte"] = "23/09/2026"
        data[P + "rblDias"] = "todos"
        data["__EVENTTARGET"] = ""
        data["__EVENTARGUMENT"] = ""
        r = c.post(URL, data=data, headers={"Referer": URL})
        print("\nPOST", r.status_code, r.url, "len", len(r.content))
        body = r.text
        (OUT / "post_full.html").write_text(body, encoding="utf-8")
        for pat in ("gvResultados", "lblMsg", "Page$Next", "erro.htm"):
            if re.search(pat, body):
                print("  tem:", pat)
        txt = re.sub(r"<script.*?</script>", " ", body, flags=re.S | re.I)
        txt = re.sub(r"<[^>]+>", " ", txt)
        txt = re.sub(r"\s+", " ", txt).strip()
        print("texto:", txt.encode("cp1252", "replace").decode("cp1252")[:900])


if __name__ == "__main__":
    main()
