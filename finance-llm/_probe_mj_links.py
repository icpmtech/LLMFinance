"""Procura links de detalhe de publicação nas páginas do MJ."""
from __future__ import annotations

import re
import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/129.0.0.0 Safari/537.36",
      "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.8"}
s = requests.Session()
s.headers.update(UA)

for url in ("https://publicacoes.mj.pt/Index.aspx", "https://publicacoes.mj.pt/Ajuda.aspx"):
    r = s.get(url, timeout=40)
    h = r.content.decode("utf-8", errors="replace")
    print(f"### {url}")
    hrefs = set(re.findall(r'href="([^"#]+)"', h, re.I))
    for x in sorted(hrefs):
        print("   href:", x)
    for kw in (r"\.ashx", r"\.asmx", r"\.json", r"\.xml", r"api/", r"javascript:__doPostBack\(&#39;([^&]+)"):
        for m in list(re.finditer(kw, h, re.I))[:20]:
            print("   kw:", re.sub(r"\s+", " ", m.group(0))[:150])
    txt = re.sub(r"<script.*?</script>", " ", h, flags=re.I | re.S)
    txt = re.sub(r"<[^>]+>", " ", txt)
    txt = re.sub(r"&nbsp;?", " ", txt)
    txt = re.sub(r"\s+", " ", txt).strip()
    print("   texto:", txt[:1500])
    print()
