"""Sonda ao portal CITIUS — Publicidade do PER/PEAP/PEVE e insolvência (consultascire.aspx).

Objetivo: descobrir a estrutura do formulário ASP.NET (campos, ViewState), verificar se há
captcha e perceber se a paginação/resultados são acessíveis sem interação humana.
"""
from __future__ import annotations

import re
import sys
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


def decode(resp: httpx.Response) -> str:
    raw = resp.content
    enc = resp.encoding or "utf-8"
    for candidate in (enc, "utf-8", "cp1252"):
        try:
            return raw.decode(candidate)
        except Exception:
            continue
    return raw.decode("cp1252", errors="replace")


def dump_form(html: str) -> None:
    forms = re.findall(r"<form[^>]*>", html, re.I)
    print("FORM TAGS:", *forms, sep="\n  ")
    # inputs
    for m in re.finditer(r"<(input|select|textarea)\b[^>]*>", html, re.I):
        tag = m.group(0)
        name = re.search(r'\bname="([^"]+)"', tag)
        typ = re.search(r'\btype="([^"]+)"', tag)
        if name:
            print(f"  {m.group(1).lower():8} {name.group(1):55} type={typ.group(1) if typ else '-'}")
    # hidden state
    hs = re.search(r'id="__VIEWSTATE"[^>]*value="([^"]*)"', html)
    print("VIEWSTATE len:", len(hs.group(1)) if hs else 0)
    print("has recaptcha:", bool(re.search(r"g-recaptcha|recaptcha/api.js", html, re.I)))
    print("has NoBot:", "NoBot" in html)
    print("scripts:", sorted(set(re.findall(r'src="([^"]+\.js[^"]*)"', html, re.I)))[:12])
    for kw in ("Captcha", "captcha", "Resultado", "AspxAutoDetectCookieSupport", "aspx"):
        hits = sorted(set(re.findall(r'["\']([^"\']*' + kw + r'[^"\']*)["\']', html)))[:6]
        if hits:
            print(f"  ~{kw}:", hits)
    print("meta charset:", re.findall(r'charset=([\w-]+)', html, re.I)[:3])


def main() -> int:
    with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=40) as client:
        r = client.get(URL)
        print("GET", r.status_code, r.url, "len", len(r.content), "enc", r.encoding)
        print("headers:", dict(list(r.headers.items())[:15]))
        html = decode(r)
        (OUT / "page.html").write_text(html, encoding="utf-8")
        dump_form(html)
        print("cookies:", client.cookies)
    return 0


if __name__ == "__main__":
    sys.exit(main())
