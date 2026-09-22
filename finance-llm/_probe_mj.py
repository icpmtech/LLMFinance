"""Sonda ao formulário de publicações do MJ (publicacoes.mj.pt)."""
from __future__ import annotations

import re
import sys
from html import unescape

import requests

PAGE = "https://publicacoes.mj.pt/Pesquisa.aspx"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-PT,pt;q=0.9,en-US;q=0.8,en;q=0.7",
}


def main() -> None:
    s = requests.Session()
    s.headers.update(HEADERS)
    r = s.get(PAGE, timeout=60)
    print("HTTP", r.status_code, "bytes", len(r.content), "enc", r.encoding)
    html = r.content.decode("utf-8", errors="replace")
    open("_probe_mj.html", "w", encoding="utf-8").write(html)

    print("\n=== <form> ===")
    for m in re.finditer(r"<form[^>]*>", html, re.I):
        print(m.group(0))

    print("\n=== inputs/selects/textarea (name -> value) ===")
    for m in re.finditer(r"<(input|select|textarea)([^>]*)>", html, re.I):
        tag, attrs = m.group(1).lower(), m.group(2)
        name_m = re.search(r'name=["\']([^"\']+)["\']', attrs, re.I)
        if not name_m:
            continue
        name = name_m.group(1)
        type_m = re.search(r'type=["\']([^"\']*)["\']', attrs, re.I)
        value_m = re.search(r'value=["\']([^"\']*)["\']', attrs, re.I)
        val = unescape(value_m.group(1)) if value_m else ""
        t = type_m.group(1) if type_m else tag
        if t == "hidden" or name.startswith("__"):
            val = f"<{len(val)} chars>"
        print(f"  [{t:8}] {name} = {val[:120]}")

    print("\n=== checkboxes com texto visível (tipos de publicação) ===")
    for m in re.finditer(r'<input([^>]*type=["\']checkbox["\'][^>]*)>(.*?)(?=<input|<br|</td|\Z)', html, re.I | re.S):
        attrs = m.group(1)
        name_m = re.search(r'name=["\']([^"\']+)["\']', attrs, re.I)
        value_m = re.search(r'value=["\']([^"\']*)["\']', attrs, re.I)
        if not name_m:
            continue
        label = re.sub(r"<[^>]+>", " ", m.group(2))
        label = re.sub(r"\s+", " ", unescape(label)).strip()
        print(f"  {name_m.group(1)} = {value_m.group(1) if value_m else ''!r} :: {label[:100]}")

    print("\n=== grelhas/tabelas com id ===")
    for m in re.finditer(r"<(table|div|ul)[^>]*id=[\"']([^\"']+)[\"'][^>]*>", html, re.I):
        print("  ", m.group(1), m.group(2))

    print("\n=== selects e opções ===")
    for m in re.finditer(r"<select([^>]*)>(.*?)</select>", html, re.I | re.S):
        name_m = re.search(r'name=["\']([^"\']+)["\']', m.group(1), re.I)
        opts = re.findall(r'<option[^>]*value=["\']([^"\']*)["\'][^>]*>(.*?)</option>', m.group(2), re.I | re.S)
        print(f"  {name_m.group(1) if name_m else '?'} -> {len(opts)} opções")
        for v, t in opts[:8]:
            print(f"      {v!r} = {re.sub(r'<[^>]+>', ' ', t).strip()[:60]}")

    print("\n=== scripts com __doPostBack / funções de pesquisa ===")
    for m in re.finditer(r".{0,80}__doPostBack.{0,120}", html):
        print("  ", m.group(0).replace("\n", " ")[:200])


if __name__ == "__main__":
    sys.exit(main())
