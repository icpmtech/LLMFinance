"""Reconcilia as páginas de benchmark no CMS: uma só por estudo, no caminho certo.

Apaga páginas órfãs debaixo de `benchmarks/` (sobras de estudos apagados ou de
publicações antigas) e liberta as definições que apontam para páginas que já não
existem. É o passo de limpeza a correr quando o site fica com páginas repetidas
(`livros-demo`, `livros-demo-2`, …).

Uso (dentro do container)::

    python /app/logs/_limpar_paginas_benchmarks.py            # relatório
    python /app/logs/_limpar_paginas_benchmarks.py --aplicar  # apaga de facto
"""
from __future__ import annotations

import argparse
import sys

sys.stdout.reconfigure(encoding="utf-8")

from api import benchmarks_store as store  # noqa: E402
from api import cms_store as cms  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Limpa páginas de benchmark repetidas no CMS.")
    parser.add_argument("--aplicar", action="store_true", help="Apagar as páginas órfãs (por omissão só relata)")
    parser.add_argument("--autor", default="sistema", help="Autor do registo de auditoria")
    args = parser.parse_args()

    benchmarks = store.listar()
    referenciadas = {str(b.get("cms_page_id") or "") for b in benchmarks if b.get("cms_page_id")}
    print(f"benchmarks: {len(benchmarks)} · páginas referenciadas: {len(referenciadas)}")

    paginas = (cms.list_items("pages", limit=200, with_blocks=False) or {}).get("items") or []
    alvo = [
        pagina
        for pagina in paginas
        if str(pagina.get("path") or "").startswith("benchmarks")
        or str(pagina.get("slug") or "") == "benchmarks"
    ]
    for pagina in alvo:
        # A página-mãe «Benchmarks» é a secção do site: mantém-se sempre, mesmo
        # que nenhum estudo a referencie (é ela que agrupa as publicações).
        e_mae = str(pagina.get("slug") or "") == "benchmarks"
        usada = e_mae or str(pagina.get("id") or "") in referenciadas
        marca = "mantém" if usada else "órfã  "
        print(f"  {marca} path={str(pagina.get('path')):34} id={str(pagina.get('id'))} título={str(pagina.get('title'))[:30]}")
        if not usada and args.aplicar:
            resultado = cms.delete_item("pages", str(pagina.get("id")), author=args.autor)
            print(f"        apagada: {resultado.get('deleted', resultado)}")
    if not args.aplicar:
        print("\n(relatório apenas — use --aplicar para apagar)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
