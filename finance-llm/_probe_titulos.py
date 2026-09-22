"""Confirma os títulos extraídos por um template (amostra larga, sem indexar).

Uso:  python _probe_titulos.py <template_id> [limite]
Grava em `_probe_titulos.txt` (UTF-8).
"""
from __future__ import annotations

import collections
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api import scraper_service as scraper  # noqa: E402
from api import scraper_templates as templates  # noqa: E402

OUT = Path(__file__).resolve().parent / "_probe_titulos.txt"


def main() -> None:
    template_id = sys.argv[1] if len(sys.argv) > 1 else "investing-mercados"
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 100
    source = templates.build_source(template_id)
    preview = scraper.preview_source(source, limit=limit, max_pages=1)
    items = preview.get("items") or []
    lines = [
        f"template={template_id} ok={preview.get('ok')} itens={preview.get('total')} "
        f"repetidos_ignorados={preview.get('duplicates')} na_amostra={len(items)}"
    ]
    titulos = collections.Counter(str(i.get("title") or "") for i in items)
    lines.append(f"títulos distintos: {len(titulos)}")
    for titulo, contagem in titulos.most_common(12):
        lines.append(f"  ×{contagem} {titulo[:110]!r}")
    vazios = sum(1 for i in items if not str(i.get("title") or "").strip())
    curtos = sum(1 for i in items if 0 < len(str(i.get("title") or "").strip()) < 25)
    lines.append(f"sem título: {vazios} · títulos com menos de 25 caracteres: {curtos}")
    OUT.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
