"""Probe 2: encontrar o cabecalho real e amostrar linhas de dados."""
from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BASE = ROOT / "data" / "subvencoes"
OUT = ROOT / "_probe_subvencoes_ods.json"

T = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"
O = "{urn:oasis:names:tc:opendocument:xmlns:office:1.0}"


def read_sheets(path: Path):
    import xml.etree.ElementTree as ET

    with zipfile.ZipFile(path) as zf:
        root = ET.fromstring(zf.read("content.xml"))
    out = {}
    for table in root.iter(T + "table"):
        name = table.get(T + "name")
        rows = []
        for row in table.findall(T + "table-row"):
            cells = []
            for cell in row:
                tag = cell.tag.split("}")[-1]
                if tag not in ("table-cell", "covered-table-cell"):
                    continue
                repeat = int(cell.get(T + "number-columns-repeated") or 1)
                value = cell.get(O + "value")
                if value is None:
                    value = cell.get(O + "date-value")
                if value is None:
                    value = " ".join(t for t in cell.itertext() if t).strip()
                value = (value or "").strip()
                if repeat > 200:
                    repeat = 1
                cells.extend([value] * repeat)
            while cells and cells[-1] == "":
                cells.pop()
            rows.append(cells)
        out[name] = rows
    return out


def main() -> int:
    report = {}
    for path in sorted(p for p in BASE.rglob("*.ods")):
        rel = str(path.relative_to(BASE))
        for sheet, rows in read_sheets(path).items():
            key = f"{rel}::{sheet}"
            info = {"rows": len(rows), "head": [], "header_row": None, "sample": []}
            # primeiras 20 linhas nao vazias
            nonempty = [(i, r) for i, r in enumerate(rows) if any(r)]
            for i, r in nonempty[:20]:
                info["head"].append({"i": i, "cells": r})
            # procurar a linha de cabecalho: a que tem mais celulas preenchidas
            # entre as primeiras 60 linhas nao vazias
            best = None
            for i, r in nonempty[:60]:
                filled = len(r)
                if best is None or filled > best[1]:
                    best = (i, filled, r)
            if best:
                info["header_row"] = {"i": best[0], "cells": best[2]}
            start = (best[0] + 1) if best else 0
            info["sample"] = rows[start : start + 5]
            # estatisticas de largura em linhas de dados
            widths = {}
            for r in rows[start : start + 5000]:
                widths[len(r)] = widths.get(len(r), 0) + 1
            info["width_hist"] = widths
            report[key] = info

    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("escrito:", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
