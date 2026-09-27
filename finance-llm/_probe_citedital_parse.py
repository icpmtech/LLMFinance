"""Detalhes do HTML do CitEdital: charset, contagem, paginador e DataList."""
from __future__ import annotations

import re
from pathlib import Path

base = Path(__file__).with_name("logs") / "citedital"
raw = (base / "search.html").read_bytes()

m = re.search(rb'charset=([\w\-]+)', raw[:3000], re.I)
print("charset declarado:", m.group(1) if m else None)
try:
    raw.decode("utf-8")
    print("decodifica como utf-8: sim")
except UnicodeDecodeError as exc:
    print("utf-8 falha:", exc)
text = raw.decode("utf-8", errors="replace")

for pat in [r"[\d\.,\s]{0,12}encontrad\w*", r"Página\s*\d+", r"resultados?", r"Mostrando"]:
    print(f"\n--- {pat} ---")
    for mm in list(re.finditer(pat, text, re.I))[:6]:
        print("  ", re.sub(r"\s+", " ", text[max(0, mm.start() - 90): mm.end() + 90]))

print("\n--- paginador (contexto de lblPageNumber) ---")
for mm in list(re.finditer(r"lblPageNumber", text))[:3]:
    print(re.sub(r"\s+", " ", text[max(0, mm.start() - 700): mm.start() + 400]))
    print("-" * 60)

print("\n--- lnkNext ---")
for mm in list(re.finditer(r"lnkNext", text))[:4]:
    print(re.sub(r"\s+", " ", text[max(0, mm.start() - 350): mm.start() + 200]))
    print("-" * 60)

print("\n--- ids DataList ---")
for mm in list(re.finditer(r'id="(ctl00_ContentPlaceHolder1_DataList[^"]*)"', text))[:8]:
    print("  ", mm.group(1))

