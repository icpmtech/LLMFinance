"""Compara a página inicial e a resposta ao POST quanto ao captcha."""
from __future__ import annotations

import re

for name in ("_probe_mj.html", "_probe_mj_results.html"):
    h = open(name, encoding="utf-8").read()
    print(f"--- {name} ---")
    m = re.search(r'<span id="ctl00_ContentPlaceHolderMain_lbCaptcha"[^>]*>(.*?)</span>', h, re.S)
    print("  lbCaptcha =", repr(re.sub(r"<[^>]+>", "", m.group(1)).strip()) if m else "n/a")
    m2 = re.search(r'<div id="ctl00_ContentPlaceHolderMain_divCaptcha"([^>]*)>', h, re.I)
    print("  divCaptcha attrs =", (m2.group(1).strip() if m2 else "n/a"))
    m3 = re.search(r'<div id="ctl00_ContentPlaceHolderMain_divRecaptcha"([^>]*)>', h, re.I)
    print("  divRecaptcha attrs =", (m3.group(1).strip() if m3 else "n/a"))
    m4 = re.search(r'id="ctl00_ContentPlaceHolderMain_divValidator"(.*?)</div>', h, re.S)
    print("  divValidator =", (re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m4.group(1))).strip()[:300] if m4 else "n/a"))
    print("  'efetue a Validação' presente:", "efetue a Valida" in h)
    for mm in re.finditer(r"g-recaptcha[^>]*", h, re.I):
        print("   widget:", mm.group(0)[:220])
    # recaptcha response field
    for mm in re.finditer(r'name="g-recaptcha-response"[^>]*', h, re.I):
        print("   g-recaptcha-response:", mm.group(0)[:160])
    print()
