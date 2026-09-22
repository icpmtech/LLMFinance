"""Exporta a especificação OpenAPI do IQ OS para ficheiro.

Gera:

* ``docs/openapi.json`` — a especificação OpenAPI 3.1 completa (Swagger);
* ``docs/API_REFERENCE.md`` — índice legível por grupo, com método, caminho
  e resumo de cada operação.

Uso::

    python scripts/export_openapi.py                 # tudo
    python scripts/export_openapi.py --json-only     # só o JSON
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DOCS = ROOT / "docs"
HTTP_METHODS = ("get", "post", "put", "patch", "delete", "head", "options")


def build_spec() -> Dict[str, Any]:
    """Importa a app FastAPI e devolve a especificação OpenAPI."""
    from api.main import app

    return app.openapi()


def write_json(spec: Dict[str, Any], path: Path) -> None:
    path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")


def write_reference(spec: Dict[str, Any], path: Path) -> None:
    info = spec.get("info") or {}
    tags: List[Dict[str, str]] = spec.get("tags") or []
    descriptions = {tag["name"]: tag.get("description", "") for tag in tags}

    by_tag: Dict[str, List[str]] = {}
    for route, operations in sorted((spec.get("paths") or {}).items()):
        for method, operation in operations.items():
            if method.lower() not in HTTP_METHODS or not isinstance(operation, dict):
                continue
            tag = (operation.get("tags") or ["core"])[0]
            summary = (operation.get("summary") or "").strip()
            by_tag.setdefault(tag, []).append(
                f"| `{method.upper()}` | `{route}` | {summary} |"
            )

    order = [tag["name"] for tag in tags] if tags else sorted(by_tag)
    total = sum(len(rows) for rows in by_tag.values())

    lines: List[str] = [
        f"# {info.get('title', 'IQ OS API')} — referência",
        "",
        f"Versão `{info.get('version', '')}` · "
        f"**{total} operações** em **{len(by_tag)} grupos**.",
        "",
        "> Ficheiro gerado por `python scripts/export_openapi.py`. "
        "A especificação completa está em `docs/openapi.json`; "
        "a interface interativa corre em `/docs` (Swagger UI) e `/redoc`.",
        "",
        "## Grupos",
        "",
    ]
    for tag in order:
        if tag not in by_tag:
            continue
        lines.append(f"- **{tag}** — {descriptions.get(tag, '')}")
    lines.append("")

    for tag in order:
        rows = by_tag.get(tag)
        if not rows:
            continue
        lines.append(f"## {tag}")
        lines.append("")
        if descriptions.get(tag):
            lines.append(descriptions[tag])
            lines.append("")
        lines.append("| Método | Caminho | Resumo |")
        lines.append("| --- | --- | --- |")
        lines.extend(rows)
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Exporta a especificação OpenAPI do IQ OS")
    parser.add_argument("--json-only", action="store_true", help="Não gerar a referência em Markdown.")
    parser.add_argument("--out", default=str(DOCS / "openapi.json"), help="Destino do JSON.")
    args = parser.parse_args()

    DOCS.mkdir(parents=True, exist_ok=True)
    spec = build_spec()

    json_path = Path(args.out)
    write_json(spec, json_path)
    print(f"openapi.json → {json_path}")

    operations = sum(
        1
        for ops in (spec.get("paths") or {}).values()
        for method in ops
        if method.lower() in HTTP_METHODS
    )
    print(f"  {operations} operações, {len(spec.get('paths') or {})} caminhos, {len(spec.get('tags') or [])} grupos")

    if not args.json_only:
        md_path = DOCS / "API_REFERENCE.md"
        write_reference(spec, md_path)
        print(f"API_REFERENCE.md → {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
