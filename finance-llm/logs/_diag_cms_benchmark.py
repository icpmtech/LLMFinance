"""Diagnóstico da publicação de benchmarks no CMS (porque é que o caminho dá 404)."""
from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8")

from api import cms_store as cms  # noqa: E402


def main() -> int:
    listagem = cms.list_items("pages", limit=50) or {}
    print("chaves da resposta:", sorted(listagem)[:6])
    for pagina in (listagem.get("items") or [])[:14]:
        parent = str(pagina.get("parent_id") or "")[:14]
        print(
            f"  {str(pagina.get('status')):10} "
            f"path={str(pagina.get('path')):30} "
            f"slug={str(pagina.get('slug')):22} "
            f"parent={parent:14} "
            f"title={str(pagina.get('title'))[:34]}"
        )
    print("---- resolução de caminhos ----")
    for caminho in ("benchmarks", "benchmarks/livros_demo", "benchmarks/livros-demo"):
        pagina = cms.resolve_page_by_path(caminho, published_only=True)
        print(f"  {caminho:26} -> {(pagina or {}).get('title')} | estado {(pagina or {}).get('status')}")
    print("---- definições de benchmark ----")
    from api import benchmarks_store as store

    for benchmark in store.listar():
        print(
            f"  slug={benchmark.get('slug'):22} público={benchmark.get('public')} "
            f"page_id={benchmark.get('cms_page_id')} caminho={benchmark.get('public_path')} "
            f"stats={benchmark.get('stats')}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
