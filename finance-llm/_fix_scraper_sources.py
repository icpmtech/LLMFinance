"""Limpeza das fontes de teste e sincronização da fonte do Investing com o template.

Uso:
    python _fix_scraper_sources.py --limpar      # apaga as fontes de teste (*-teste-do-fluxo-*)
    python _fix_scraper_sources.py --template    # reaplica o template à fonte do Investing
Grava o relatório em `_fix_scraper_sources.txt` (UTF-8).
"""
from __future__ import annotations

import sys
from pathlib import Path

from api import scraper_service as scraper
from api import scraper_templates as templates

OUT = Path(__file__).resolve().parent / "_fix_scraper_sources.txt"
lines: list[str] = []


def emit(text: str = "") -> None:
    lines.append(text)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    try:
        print(text)
    except UnicodeEncodeError:  # console do Windows em cp1252
        print(text.encode("ascii", "replace").decode("ascii"))


def limpar() -> None:
    for source in scraper.list_sources():
        if "-teste-do-fluxo-" in source["id"]:
            emit(f"apagar fonte de teste {source['id']}: {scraper.delete_source(source['id'], purge_items=True)}")


def sincronizar(template_id: str = "") -> None:
    """Reaplica o template às fontes que dele vieram (ou só a um template)."""
    for source in scraper.list_sources():
        origem = source.get("template_id")
        if not origem:
            continue
        if template_id and origem != template_id:
            continue
        antes = source["fields"][0]["selector"]
        refreshed = templates.refresh_source(source)
        guardada = scraper.upsert_source({**refreshed, "_must_exist": True})
        emit(f"fonte {guardada['id']}: titulo {antes!r} -> {guardada['fields'][0]['selector']!r}")
        emit(f"  campos: {[f['name'] for f in guardada['fields']]}")
        emit(f"  selectors do titulo: {(guardada['fields'][0].get('selectors'))}")
        emit(f"  nome/agenda/int.: {guardada['name']!r} {guardada['schedule']} enabled={guardada['enabled']}")


def verificar() -> None:
    """Testa cada fonte criada a partir de um template (sem guardar nem indexar)."""
    for source in scraper.list_sources():
        if not source.get("template_id"):
            continue
        preview = scraper.preview_source(source, limit=100, max_pages=1)
        items = preview.get("items") or []
        titulos = [str(i.get("title") or "").strip() for i in items]
        distintos = {t for t in titulos if t}
        emit(
            f"{source['id']:48s} ok={preview.get('ok')} itens={preview.get('total')} "
            f"repetidos={preview.get('duplicates')} titulos={len(distintos)} "
            f"sem_titulo={sum(1 for t in titulos if not t)} "
            f"titulos_repetidos={len(titulos) - len(distintos)} erro={preview.get('error')}"
        )


def recolher(source_id: str = "", template_id: str = "") -> None:
    """Recolhe agora as fontes indicadas (por id ou as de um template), de forma síncrona."""
    for source in scraper.list_sources():
        if source_id and source["id"] != source_id:
            continue
        if template_id and source.get("template_id") != template_id:
            continue
        if not source_id and not template_id:
            break
        meta = scraper.execute_run_sync(source["id"], trigger="manual")
        emit(
            f"recolha {source['id']}: estado={meta['status']} itens={meta['items_count']} "
            f"indexados={meta['indexed_count']} repetidos={meta.get('duplicates', 0)} {meta['duration_ms']} ms"
        )


if __name__ == "__main__":
    argumentos = sys.argv[1:]
    alvo = next((a for a in argumentos if not a.startswith("--")), "")
    if "--limpar" in argumentos:
        limpar()
    if "--template" in argumentos:
        sincronizar(alvo)
    if "--recolher" in argumentos:
        recolher(alvo)
    if "--verificar" in argumentos:
        verificar()
    OUT.write_text("\n".join(lines), encoding="utf-8")
