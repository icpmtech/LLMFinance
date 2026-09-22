"""Reconhecimento de rotas alternativas no publicacoes.mj.pt e fontes abertas."""
from __future__ import annotations

import re
import requests

UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.8",
}

CANDIDATES = [
    "https://publicacoes.mj.pt/robots.txt",
    "https://publicacoes.mj.pt/sitemap.xml",
    "https://publicacoes.mj.pt/Index.aspx",
    "https://publicacoes.mj.pt/Ajuda.aspx",
    "https://publicacoes.mj.pt/Dados.aspx",
    "https://publicacoes.mj.pt/Resultado.aspx",
    "https://publicacoes.mj.pt/pt/Resultado.aspx",
    "https://publicacoes.mj.pt/Detalhe.aspx",
    "https://publicacoes.mj.pt/PesquisaAvancada.aspx",
]

s = requests.Session()
s.headers.update(UA)
for url in CANDIDATES:
    try:
        r = s.get(url, timeout=30, allow_redirects=True)
        body = r.content.decode("utf-8", errors="replace")
        title = re.search(r"<title>(.*?)</title>", body, re.I | re.S)
        print(f"{r.status_code} {len(body):>7} {url} -> {re.sub(r'<[^>]+>','',title.group(1)).strip() if title else ''}")
        if url.endswith("robots.txt") and r.status_code == 200:
            print("   robots:", re.sub(r"\s+", " ", body)[:600])
    except Exception as exc:
        print("ERR", url, exc)

print("\n=== hrefs 'Detalhe/Publicacao' na página de pesquisa ===")
h = open("_probe_mj.html", encoding="utf-8").read()
for m in re.finditer(r'href="([^"]*(?:Detalhe|Publicacao|Result|Ver)[^"]*)"', h, re.I):
    print("  ", m.group(1))
