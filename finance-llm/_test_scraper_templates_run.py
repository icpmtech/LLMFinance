"""Valida o caminho completo de um template: fonte → recolha → índice → pesquisa.

Cria uma fonte a partir do template do ECO (texto integral limitado a 4 itens),
executa a recolha de forma síncrona, confirma que o texto integral ficou
pesquisável e no fim apaga a fonte e os itens indexados — o ambiente fica como
estava.

Uso:  python _test_scraper_templates_run.py
Grava o relatório em `_test_scraper_templates_run.txt` (UTF-8).
"""
from __future__ import annotations

from pathlib import Path

from api import scraper_service as scraper
from api import scraper_templates as templates

OUT = Path(__file__).resolve().parent / "_test_scraper_templates_run.txt"
lines: list[str] = []


def emit(text: str = "") -> None:
    lines.append(text)
    print(text)


def main() -> None:
    source = templates.build_source(
        "eco",
        {"name": "QA templates · ECO", "detail": {"max_items": 4, "delay": 0.4}},
    )
    created = scraper.upsert_source(source)
    source_id = created["id"]
    emit(
        "definição: id={0} fetcher={1} detail={2} max_items={3}".format(
            source_id,
            created["fetcher"],
            created["detail"]["enabled"],
            created["detail"]["max_items"],
        )
    )

    meta = scraper.execute_run_sync(source_id, trigger="teste")
    emit(
        "execução: estado={0} itens={1} indexados={2} páginas={3} textos={4} erros_texto={5} {6} ms".format(
            meta["status"],
            meta["items_count"],
            meta["indexed_count"],
            meta["pages"],
            meta["detail_count"],
            meta["detail_errors"],
            meta["duration_ms"],
        )
    )

    items = scraper.read_run_items(meta["run_id"], source_id, limit=3)["items"]
    for item in items:
        emit(f"  · {item['title'][:80]}")
        emit(f"    {item['url'][:100]}")
        emit(f"    texto={len(item.get('text') or '')} caracteres · detalhe={bool(item.get('detail'))}")

    resultado = scraper.search_items(q="habitação", source_id=source_id, size=5)
    emit(f"pesquisa «habitação»: total={resultado.get('total')} erro={resultado.get('error')}")
    for hit in (resultado.get("items") or [])[:3]:
        emit(f"  · [{hit.get('title', '')[:60]}] texto indexado={len(hit.get('text') or '')} caracteres")

    resultado = scraper.search_items(q="arrendamento", source_id=source_id, size=5)
    emit(f"pesquisa «arrendamento»: total={resultado.get('total')}")

    emit(f"apagar fonte e itens: {scraper.delete_source(source_id, purge_items=True)}")
    emit(f"fontes depois da limpeza: {[s['id'] for s in scraper.list_sources()]}")

    OUT.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
