"""Testar MostraPdf.aspx?q=<token> e descodificar a resposta (pageRedirect?)."""
from __future__ import annotations

from pathlib import Path

from collectors.citius_cire import BASE, PAGE, CireClient, parse_delta

OUT = Path(__file__).parent / "_probe_cire_out"

with CireClient(min_interval=1.0) as client:
    page = client.search(desde="2026-09-23", ate="2026-09-23")
    pub = next((p for p in page.items if p.doc_token), None)
    tok = pub.doc_token if pub else None
    print("item:", pub.referencia if pub else None)
    url = BASE + "Viewer/MostraPdf.aspx?q=" + (tok or "")
    r = client.session.get(url, headers={"Referer": PAGE}, timeout=45, allow_redirects=False)
    print("GET", r.status_code, r.headers.get("content-type"), len(r.content))
    print("body:", r.content[:200])
    print("location:", r.headers.get("location"))
    delta = parse_delta(r.content.decode("utf-8", "replace"))
    for k, v in delta.items():
        print(f"  {k} = {v[:160]!r}")
    # se houver redirect, seguir
    if r.headers.get("location"):
        r2 = client.session.get(r.headers["location"], headers={"Referer": PAGE}, timeout=60)
        print("depois do redirect:", r2.status_code, r2.headers.get("content-type"), len(r2.content), r2.content[:8])
        if b"%PDF" in r2.content[:1024]:
            (OUT / "doc_ok.pdf").write_bytes(r2.content)
            print("PDF guardado em _probe_cire_out/doc_ok.pdf")
