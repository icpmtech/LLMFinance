"""Valida os templates de recolha contra os sites reais.

Para cada template: constrói a definição (`scraper_templates.build_source`),
corre uma recolha de amostra com o motor verdadeiro (`preview_source`) e mede
quantos itens saíram e quantos trouxeram cada campo. No fim escreve um relatório
em `_test_scraper_templates.json` e em `_test_scraper_templates.txt`.

Uso:
    python _test_scraper_templates.py                 # todos
    python _test_scraper_templates.py eco expansion   # só alguns
    python _test_scraper_templates.py --limit 3 --no-detail
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api import scraper_service as scraper  # noqa: E402
from api import scraper_templates as templates  # noqa: E402

ROOT = Path(__file__).resolve().parent
REPORT_JSON = ROOT / "_test_scraper_templates.json"
REPORT_TXT = ROOT / "_test_scraper_templates.txt"


def check(template_id: str, limit: int, use_detail: bool) -> Dict[str, Any]:
    started = time.perf_counter()
    result: Dict[str, Any] = {"template": template_id, "ok": False}
    try:
        source = templates.build_source(template_id)
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result
    result["url"] = source["url"]
    result["fetcher"] = source["fetcher"]
    result["list"] = source["list"]["selector"]
    if not use_detail:
        source = {**source, "detail": {**(source.get("detail") or {}), "enabled": False}}
    try:
        preview = scraper.preview_source(source, limit=limit, max_pages=1)
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["duration_ms"] = int((time.perf_counter() - started) * 1000)
        return result
    result["duration_ms"] = int((time.perf_counter() - started) * 1000)
    result["ok"] = bool(preview.get("ok"))
    result["error"] = preview.get("error")
    result["items"] = preview.get("total", 0)
    result["detail_count"] = preview.get("detail_count", 0)
    result["duplicates"] = preview.get("duplicates", 0)

    items: List[Dict[str, Any]] = preview.get("items") or []
    coverage: Dict[str, int] = {}
    for item in items:
        data = item.get("data") or {}
        for field in source.get("fields", []):
            name = field["name"]
            if data.get(name) not in (None, "", []):
                coverage[name] = coverage.get(name, 0) + 1
    result["coverage"] = coverage
    result["sample"] = [
        {
            "titulo": item.get("title", "")[:90],
            "url": item.get("url", "")[:110],
            "data": {k: str(v)[:60] for k, v in (item.get("data") or {}).items()},
            "text_chars": len(str(item.get("text") or "")),
        }
        for item in items[:2]
    ]
    return result


def main() -> None:
    args = [a for a in sys.argv[1:]]
    use_detail = "--no-detail" not in args
    limit = 3
    if "--limit" in args:
        limit = int(args[args.index("--limit") + 1])
    wanted = [a for a in args if not a.startswith("--") and not a.isdigit()]
    ids = wanted or [t["id"] for t in templates.TEMPLATES]

    reports = []
    for template_id in ids:
        report = check(template_id, limit, use_detail)
        reports.append(report)
        print(
            f"{template_id:26s} ok={report.get('ok')!s:5s} itens={report.get('items', 0):3d} "
            f"textos={report.get('detail_count', 0):3d} repetidos={report.get('duplicates', 0):2d} "
            f"{report.get('duration_ms', 0):6d} ms {report.get('error') or ''}"
        )

    REPORT_JSON.write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
    lines: List[str] = []
    for report in reports:
        lines.append("=" * 100)
        lines.append(f"template={report['template']} url={report.get('url')} fetcher={report.get('fetcher')}")
        lines.append(
            f"  ok={report.get('ok')} itens={report.get('items')} textos={report.get('detail_count')} "
            f"repetidos={report.get('duplicates')} erro={report.get('error')}"
        )
        lines.append(f"  lista: {report.get('list')}")
        lines.append(f"  cobertura: {report.get('coverage')}")
        for sample in report.get("sample") or []:
            lines.append(f"  · {sample['titulo']}")
            lines.append(f"    {sample['url']}")
            lines.append(f"    dados: {sample['data']}")
            lines.append(f"    texto: {sample['text_chars']} caracteres")
    REPORT_TXT.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nRelatórios: {REPORT_TXT.name} e {REPORT_JSON.name}")


if __name__ == "__main__":
    main()
