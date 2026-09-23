"""Descobrir como o CIRE abre o documento (Ver Mais) — ler DocumentoViewer.js e testar MostraPdf.aspx."""
from __future__ import annotations

import re
from pathlib import Path

import requests

BASE = "https://www.citius.mj.pt/portal/consultas/"
PAGE = BASE + "ConsultasCire.aspx"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.8",
}
OUT = Path(__file__).parent / "_probe_cire_out"

for js_url in ("https://www.citius.mj.pt/portal/Js/DocumentoViewer.js",
               BASE + "Js/DocumentoViewer.js"):
    r = requests.get(js_url, headers=HEADERS, timeout=30)
    print("JS", js_url, r.status_code, len(r.content))
    if r.status_code == 200:
        (OUT / "DocumentoViewer.js").write_text(r.text, encoding="utf-8")
        i = r.text.find("Ver")
        print(re.sub(r"\s+", " ", r.text[i:i + 1200]))
        break

# procurar o token de um item e testar variantes de URL
from collectors.citius_cire import CireClient  # noqa: E402

with CireClient(min_interval=1.0) as client:
    page = client.search(desde="2026-09-23", ate="2026-09-23")
    pub = next((p for p in page.items if p.doc_token), None)
    print("\nitem:", pub.referencia if pub else None)
    if pub and pub.doc_token:
        tok = pub.doc_token
        variantes = [
            BASE + "Viewer/MostraPdf.aspx?" + tok,
            BASE + "Viewer/MostraPdf.aspx?queryString=" + tok,
            BASE + "Viewer/MostraPdf.aspx?qs=" + tok,
            BASE + "Viewer/MostraPdf.aspx?QueryString=" + tok,
            BASE + "MostraPdf.aspx?" + tok,
        ]
        for url in variantes:
            try:
                r = client.session.get(url, headers={"Referer": PAGE}, timeout=45)
                ct = r.headers.get("content-type", "")
                print(f"  {url[:70]}... -> {r.status_code} {ct} len={len(r.content)} magic={r.content[:12]!r}")
                if b"%PDF" in r.content[:1024]:
                    (OUT / "doc_ok.pdf").write_bytes(r.content)
                    print("   --> PDF guardado")
                    break
            except Exception as exc:  # noqa: BLE001
                print("   erro", exc)
