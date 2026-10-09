"""Probe: inspeciona os ficheiros ODS de subvencoes publicas.

Le o diretorio data/subvencoes (com subpastas por ano) e mostra folhas,
numero de linhas, cabecalho e as primeiras linhas de dados.
"""
from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BASE = ROOT / "data" / "subvencoes"

NS = {
    "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
    "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
    "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
}


def read_sheets(path: Path) -> dict[str, list[list[str]]]:
    import xml.etree.ElementTree as ET

    with zipfile.ZipFile(path) as zf:
        xml = zf.read("content.xml")
    root = ET.fromstring(xml)
    sheets: dict[str, list[list[str]]] = {}
    for table in root.iter("{%s}table" % NS["table"]):
        name = table.get("{%s}name" % NS["table"]) or "?"
        rows: list[list[str]] = []
        for row in table.findall("{%s}table-row" % NS["table"]):
            repeat_rows = int(row.get("{%s}number-rows-repeated" % NS["table"]) or 1)
            cells: list[str] = []
            for cell in row:
                tag = cell.tag.split("}")[-1]
                if tag not in ("table-cell", "covered-table-cell"):
                    continue
                repeat = int(cell.get("{%s}number-columns-repeated" % NS["table"]) or 1)
                value = cell.get("{%s}value" % NS["office"])
                if value is None:
                    value = cell.get("{%s}date-value" % NS["office"])
                if value is None:
                    value = " ".join(
                        t for t in cell.itertext() if t
                    ).strip()
                value = (value or "").strip()
                if repeat > 200:
                    repeat = 1
                cells.extend([value] * repeat)
            while cells and cells[-1] == "":
                cells.pop()
            if not any(cells):
                # linha vazia: so conta uma vez
                rows.append([])
                if repeat_rows > 1 and len(rows) > 3:
                    continue
                continue
            for _ in range(min(repeat_rows, 1)):
                rows.append(list(cells))
        while rows and not any(rows[-1]):
            rows.pop()
        sheets[name] = rows
    return sheets


def main() -> int:
    print("BASE:", BASE, "existe:", BASE.is_dir())
    if not BASE.is_dir():
        return 1
    files = sorted(p for p in BASE.rglob("*") if p.suffix.lower() in (".ods", ".xlsx", ".csv"))
    print("ficheiros:", [str(p.relative_to(BASE)) for p in files])
    for path in files:
        print("=" * 100)
        print("FICHEIRO:", path.relative_to(ROOT), path.stat().st_size, "bytes")
        try:
            sheets = read_sheets(path)
        except Exception as exc:  # noqa: BLE001
            print("  ERRO a ler:", type(exc).__name__, exc)
            continue
        for name, rows in sheets.items():
            filled = [r for r in rows if any(r)]
            print("-" * 90)
            print(f"  folha={name!r} linhas_totais={len(rows)} linhas_com_dados={len(filled)}")
            for i, row in enumerate(filled[:6]):
                print(f"    [{i}] {row}")
            if len(filled) > 6:
                print(f"    ... última: {filled[-1]}")
            if filled:
                width = max(len(r) for r in filled)
                print(f"    largura_max={width} larguras={[len(r) for r in filled[:5]]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
