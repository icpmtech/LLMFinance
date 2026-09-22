"""Inspeciona captcha/NoBot e scripts do formulário do MJ."""
from __future__ import annotations

import re

HTML = open("_probe_mj.html", encoding="utf-8").read()


def show(pat: str, label: str, n: int = 8, w: int = 600) -> None:
    print(f"=== {label} ===")
    found = list(re.finditer(pat, HTML, re.I | re.S))
    print(f"  ({len(found)} ocorrências)")
    for m in found[:n]:
        print("  ", re.sub(r"\s+", " ", m.group(0))[:w])
    print()


show(r"<script[^>]*src=[\"']([^\"']+)", "scripts src", 25, 220)
show(r"divCaptcha.*?</div>", "divCaptcha", 1, 1200)
show(r"divRecaptcha.*?</div>", "divRecaptcha", 1, 1200)
show(r"ctl00_ContentPlaceHolderMain_NoBot1.*?</div>", "NoBot div", 1, 1200)
show(r"[A-Za-z0-9_]*NoBot[A-Za-z0-9_]*", "noBot ids", 25, 160)
show(r"recaptcha|grecaptcha", "recaptcha refs", 10, 300)
show(r"document\.cookie|sessionStorage|localStorage", "client state", 10, 300)
