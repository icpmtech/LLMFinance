"""Analisa a resposta ao POST de pesquisa do MJ."""
from __future__ import annotations

import re

HTML = open("_probe_mj_results.html", encoding="utf-8").read()
TEXT = re.sub(r"<script.*?</script>", " ", HTML, flags=re.I | re.S)
TEXT = re.sub(r"<style.*?</style>", " ", TEXT, flags=re.I | re.S)
TEXT = re.sub(r"<[^>]+>", "\n", TEXT)
TEXT = re.sub(r"&nbsp;?", " ", TEXT)
TEXT = re.sub(r"\n\s*\n+", "\n", TEXT).strip()
print("=== TEXTO VISÍVEL ===")
print(TEXT[:4000])

print("\n=== bloco divContent ===")
m = re.search(r'id="ctl00_ContentPlaceHolderMain_divContent"(.*?)<div id="ctl00_divFooter"', HTML, re.S)
print((m.group(1)[:6000] if m else "não encontrado"))

print("\n=== inputs com valor não vazio ===")
for mm in re.finditer(r"<input([^>]*)>", HTML, re.I):
    a = mm.group(1)
    n = re.search(r'name=["\']([^"\']+)["\']', a)
    v = re.search(r'value=["\']([^"\']*)["\']', a)
    if n and v and v.group(1) and not n.group(1).startswith("__"):
        print("  ", n.group(1), "=", v.group(1)[:80])
print("\n=== captcha/data-sitekey ===")
for mm in re.finditer(r'g-recaptcha[^>]*', HTML, re.I):
    print("  ", mm.group(0)[:200])
