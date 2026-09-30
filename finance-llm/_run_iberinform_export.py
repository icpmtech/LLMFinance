"""Recolhe Iberinform.pt por distrito/concelho e exporta JSON organizado.

Uso:
    c:\LLMFinance\.venv\Scripts\python.exe _run_iberinform_export.py evora alandroal --start 1 --end 6
    c:\LLMFinance\.venv\Scripts\python.exe _run_iberinform_export.py evora alandroal --page 6
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, r"c:\LLMFinance\finance-llm")

from api.scraper_templates import build_source
from api import scraper_service


def build_source_for(distrito: str, concelho: str, start_page: int = 1, max_pages: int = 1, detail: bool = True) -> dict:
    url = f"https://www.iberinform.pt/diretorio/{distrito}/{concelho}/pagina/{start_page}"
    src = build_source(
        "iberinform-diretorio",
        overrides={
            "url": url,
            "name": f"Iberinform {distrito.title()}/{concelho.title()}",
            "enabled": True,
            "tags": ["empresas", "iberinform", "diretorio", distrito.lower(), concelho.lower()],
        },
    )
    src["pagination"] = {
        **src.get("pagination", {}),
        "max_pages": max(1, int(max_pages)),
    }
    src["detail"] = {
        **src.get("detail", {}),
        "enabled": bool(detail),
        "max_items": 0,
        "delay": 1.0,
        "max_chars": 20000,
    }
    return src


def run_and_export(distrito: str, concelho: str, start_page: int, max_pages: int, *, detail: bool = True, keep_in_es: bool = True):
    distrito = distrito.lower().strip()
    concelho = concelho.lower().strip()

    src = build_source_for(distrito, concelho, start_page, max_pages, detail=detail)
    # Registar temporariamente para poder correr via execute_run_sync
    saved = scraper_service.upsert_source(src)
    source_id = saved["id"]
    print(f"Fonte registada: {source_id}")

    try:
        meta = scraper_service.execute_run_sync(source_id, trigger="manual")
    finally:
        # Manter a fonte registada para futuras execuções, mas pode-se apagar se se quiser
        pass

    run_id = meta.get("run_id")
    items_path = scraper_service._items_path(run_id, source_id)
    print(f"Run {run_id} -> {items_path}")
    print(f"Itens recolhidos: {meta.get('items_count')}, detalhes: {meta.get('detail_count')}, erros: {meta.get('error_count')}, duplicados: {meta.get('duplicates')}")

    # Ler todos os itens do JSONL
    items: list[dict] = []
    if items_path.exists():
        with items_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    items.append(json.loads(line))
                except Exception:
                    continue

    # Exportar para ficheiro organizado por distrito/concelho
    out_dir = Path(r"c:\LLMFinance\finance-llm\data\scraper\exports\iberinform") / distrito / concelho
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"pagina_{start_page}_a_{start_page + max_pages - 1}.json"
    out_file.write_text(json.dumps({
        "distrito": distrito,
        "concelho": concelho,
        "start_page": start_page,
        "max_pages": max_pages,
        "run_id": run_id,
        "source_id": source_id,
        "meta": meta,
        "items": items,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Exportado: {out_file} ({len(items)} itens)")

    # Resumo
    nifs = [i.get("data", {}).get("nif") for i in items if i.get("data", {}).get("nif")]
    sem_nif = [i for i in items if not i.get("data", {}).get("nif")]
    com_detalhe = [i for i in items if i.get("detail_text")]
    print(f"NIFs extraídos: {len(nifs)} / {len(items)}; com detalhe: {len(com_detalhe)}; sem NIF: {len(sem_nif)}")

    return meta, items, out_file


def main():
    parser = argparse.ArgumentParser(description="Recolher Iberinform.pt por distrito/concelho")
    parser.add_argument("distrito")
    parser.add_argument("concelho")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--page", type=int, help="Página única")
    group.add_argument("--start", type=int, help="Página inicial")
    parser.add_argument("--end", type=int, help="Página final (usado com --start)")
    parser.add_argument("--no-detail", action="store_true", help="Não recolher texto de detalhe")
    args = parser.parse_args()

    if args.page is not None:
        start, max_pages = args.page, 1
    else:
        if args.end is None or args.end < args.start:
            parser.error("--end deve ser >= --start")
        start, max_pages = args.start, args.end - args.start + 1

    run_and_export(args.distrito, args.concelho, start, max_pages, detail=not args.no_detail)


if __name__ == "__main__":
    main()
