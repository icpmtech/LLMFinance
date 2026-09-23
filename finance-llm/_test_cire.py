"""Teste manual do coletor CIRE (formulário, pesquisa, paginação, itens e documento)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from collectors.citius_cire import CireClient  # noqa: E402

OUT = Path(__file__).parent / "_probe_cire_out"


def main() -> None:
    with CireClient(min_interval=1.0) as client:
        html = client.fetch_form()
        print("formulário:", len(html), "bytes")
        print("tribunais:", len(client.tribunais()), "| exemplos:",
              [t["label"] for t in client.tribunais()[:3]])
        print("atos:", len(client.actos()))

        page = client.search(desde="2026-09-22", ate="2026-09-23")
        print(f"\npesquisa: total={page.total} páginas~{page.pages_total} "
              f"página={page.page} itens={len(page.items)} next={page.has_next}")
        for i, pub in enumerate(page.items[:3]):
            print(f"\n--- item {i + 1} ---")
            print(json.dumps(pub.to_dict(), ensure_ascii=False, indent=2)[:1400])

        # paginação
        page2 = client.next_page()
        print(f"\npágina {page2.page}: itens={len(page2.items)} next={page2.has_next}")
        refs1 = {p.referencia for p in page.items}
        refs2 = {p.referencia for p in page2.items}
        print("referências repetidas entre páginas:", len(refs1 & refs2))
        if page2.items:
            p = page2.items[0]
            print("exemplo pág.2:", p.referencia, "|", p.tribunal, "|", p.data_publicacao, "|", p.especie)
            print("intervenientes:", p.intervenientes)

        # recolha limitada
        items, summary = client.collect(desde="2026-09-23", ate="2026-09-23", max_pages=3)
        print("\ncollect:", summary)
        import collections
        print("tipos:", collections.Counter(i.tipo for i in items))
        print("tribunais:", collections.Counter(i.tribunal for i in items).most_common(3))

        # documento (PDF)
        com_doc = next((i for i in items if i.doc_token), None)
        if com_doc:
            pdf = client.fetch_documento(com_doc.doc_token or "")
            print(f"\ndocumento {com_doc.referencia}: {len(pdf)} bytes, magic={pdf[:5]!r}")
            (OUT / "doc_item.pdf").write_bytes(pdf)
        else:
            print("\nsem documento nos itens recolhidos")

        (OUT / "collect_test.json").write_text(
            json.dumps([i.to_dict() for i in items], ensure_ascii=False, indent=2), encoding="utf-8"
        )


if __name__ == "__main__":
    main()
