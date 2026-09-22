"""Diagnóstico: itens repetidos (por URL e por título) nas execuções das fontes.

Uso:  python _probe_repetidos.py [limite_de_execucoes]
Grava em `_probe_repetidos.txt` (UTF-8).
"""
from __future__ import annotations

import collections
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api import scraper_service as scraper  # noqa: E402

OUT = Path(__file__).resolve().parent / "_probe_repetidos.txt"
lines: list[str] = []


def emit(text: str = "") -> None:
    lines.append(text)
    print(text)


def main() -> None:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    runs = scraper.list_runs(limit=200)
    vistas: dict[str, str] = {}
    for run in runs[:limit]:
        source_id = run.get("source_id", "")
        vistas.setdefault(source_id, run.get("run_id", ""))
    for source_id, run_id in vistas.items():
        items = scraper.read_run_items(run_id, source_id, limit=5000)["items"]
        if not items:
            continue
        urls = collections.Counter(str(i.get("url") or "") for i in items)
        titulos = collections.Counter(str(i.get("title") or "").strip() for i in items)
        ids = collections.Counter(str(i.get("item_id") or "") for i in items)
        emit("=" * 100)
        emit(
            f"{source_id}  run={run_id}  itens={len(items)} "
            f"urls_distintas={len(urls)} titulos_distintos={len(titulos)} item_ids_distintos={len(ids)}"
        )
        for valor, contagem in titulos.most_common(5):
            if contagem > 1:
                emit(f"  título ×{contagem}: {valor[:110]!r}")
        for valor, contagem in urls.most_common(5):
            if contagem > 1:
                emit(f"  URL   ×{contagem}: {valor[:110]}")
        if all(c == 1 for c in titulos.values()):
            emit("  sem títulos repetidos")
    OUT.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
