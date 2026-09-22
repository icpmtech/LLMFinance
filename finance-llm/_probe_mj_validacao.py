"""Extrai a validação cliente da pesquisa (limite de datas / critérios)."""
from __future__ import annotations

import re

for name in ("_probe_mj_webpub.js",):
    html = open(name, encoding="utf-8", errors="replace").read()
    for match in re.finditer(r"function\s+validarDadosPesquisa", html):
        print(f"--- {name} ---")
        print(html[match.start() : match.start() + 2600])
        print()
