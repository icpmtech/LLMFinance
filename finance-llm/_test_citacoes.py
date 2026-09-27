"""Testa o coletor `collectors/citius_citacoes.py` contra o portal real."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from collectors.citius_citacoes import (  # noqa: E402
    CitacoesEditalClient,
    form_state,
    parse_items,
    result_count,
    total_pages,
)
from datetime import date, timedelta  # noqa: E402


def main() -> int:
    nome = sys.argv[1] if len(sys.argv) > 1 else "SILVA"
    meses = int(sys.argv[2]) if len(sys.argv) > 2 else 6
    desde = (date.today() - timedelta(days=31 * meses)).isoformat()
    print(f"pesquisa «{nome}» · corte {desde}")

    with CitacoesEditalClient(min_interval=1.0) as client:
        html = client.fetch_form()
        print("viewstate:", len(form_state(html)["__VIEWSTATE"]), "| serviços:", len(client.tribunais()))
        print("  ex.:", [t["label"] for t in client.tribunais()[:3]])
        page = client.search(nome=nome)
        print(
            f"total: {page.total} ({total_pages(page.html)} páginas) · página {page.page} · "
            f"itens {len(page.items)} · has_next {page.has_next}"
        )
        if page.items:
            print(json.dumps(page.items[0].to_dict(), ensure_ascii=False, indent=2)[:1600])

        def on_page(p, novos):
            print(f"  página {p.page}: {len(novos)} novos (total acumulado)")

        items, resumo = client.collect(nome=nome, desde=desde, max_pages=6, on_page=on_page)
        print("\nresumo:", resumo)
        print("datas:", sorted({i.data_publicacao for i in items if i.data_publicacao})[:5], "...")
        print("processos únicos:", len({i.processo_numero for i in items if i.processo_numero}))
        print("tribunais:", len({i.tribunal for i in items if i.tribunal}))
        print("com documento:", sum(1 for i in items if i.doc_token), "/", len(items))
        papeis = {}
        for item in items:
            for p in item.papeis:
                papeis[p] = papeis.get(p, 0) + 1
        print("papéis:", sorted(papeis.items(), key=lambda kv: -kv[1])[:8])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
