"""Testes dos relatórios do módulo Contribuintes (PDF, Excel e CSV com o logo).

Verifica as agregações novas (distritos, concelhos, tipos × localização) e gera
os três formatos para uma ficha e para uma lista, confirmando que os ficheiros
têm conteúdo válido e a marca do IQ OS.

Uso:
    python _test_contribuintes_report.py [nif]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from api import contribuintes_report as report
from api import contribuintes_service as service

PASSES: list[str] = []
FAILURES: list[str] = []
OUTPUT = Path("data/contribuintes/_reports_teste")


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"  [{'OK  ' if condition else 'FALHA'}] {label}" + (f" — {detail}" if detail else ""))
    (PASSES if condition else FAILURES).append(label)


def section(title: str) -> None:
    print(f"\n=== {title}")


def test_logo() -> None:
    section("Marca")
    logo = report.logo_path()
    check("logótipo do IQ OS localizado", logo is not None, str(logo))
    if logo:
        check("logótipo é PNG e não está vazio", logo.suffix == ".png" and logo.stat().st_size > 1000, f"{logo.stat().st_size} B")
    available = report.available()
    check("PDF disponível (reportlab)", any(f["id"] == "pdf" and f["available"] for f in available["formats"]))
    check("Excel disponível (openpyxl)", any(f["id"] == "xlsx" and f["available"] for f in available["formats"]))
    check("marca identificada", available["brand"] == "IQ OS", available["tagline"])


def test_status_aggregations() -> None:
    section("Agregações de tipos e localização")
    status = service.status()
    if status.get("error"):
        check("status do índice", False, str(status["error"])[:120])
        return
    check("status do índice", True, f"{status.get('documents')} contribuintes")
    districts = status.get("districts") or []
    municipalities = status.get("municipalities") or []
    matrix = status.get("types_by_district") or []
    print(f"       tipos: {[(f['key'], f['count']) for f in (status.get('types') or [])]}")
    print(f"       distritos: {[(f['key'], f['count']) for f in districts[:6]]}")
    print(f"       concelhos: {[(f['key'], f['count']) for f in municipalities[:6]]}")
    print(f"       com localização: {status.get('with_location')}")
    check("distritos agregados", bool(districts), f"{len(districts)} distritos")
    check("concelhos agregados", bool(municipalities), f"{len(municipalities)} concelhos")
    check("matriz tipos × distrito", bool(matrix) and all("types" in row for row in matrix), f"{len(matrix)} distritos")
    if matrix:
        first = matrix[0]
        print(
            f"       exemplo: {first['key']} → "
            + ", ".join(f"{t['label']}={t['count']}" for t in first["types"][:5])
            + f" (valor {first.get('value'):,.2f} €)"
        )


def test_reports(nif: str) -> None:
    section(f"Relatórios da ficha ({nif})")
    doc = service.detail(nif)
    if doc.get("error"):
        check("ficha obtida", False, str(doc["error"])[:120])
        return
    check("ficha obtida", True, f"{doc.get('name')} · {doc.get('type_label')}")

    sections = report.contribuinte_sections(doc)
    check("secções da ficha construídas", len(sections) >= 3, f"{len(sections)} secções: {[s['title'] for s in sections]}")
    check(
        "secção de localização presente",
        any(s["title"] == "Localização" for s in sections) or not doc.get("location"),
        str(doc.get("location") or "sem localização no documento"),
    )

    OUTPUT.mkdir(parents=True, exist_ok=True)
    signatures = {
        "pdf": (b"%PDF", "application/pdf"),
        "xlsx": (b"PK", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        "csv": ("\ufeff".encode("utf-8"), "text/csv"),
    }
    for fmt, (magic, mime) in signatures.items():
        filename, content, media_type = report.contribuinte_report(doc, format=fmt)
        path = OUTPUT / filename
        path.write_bytes(content)
        check(
            f"relatório {fmt.upper()} gerado",
            content.startswith(magic) and media_type.startswith(mime.split(";")[0]),
            f"{filename} · {len(content)} B",
        )
        if fmt == "csv":
            text = content.decode("utf-8-sig")
            check("CSV com cabeçalho da marca", "IQ OS" in text.splitlines()[0], text.splitlines()[0])
            check("CSV com a designação do contribuinte", str(doc.get("nif")) in text)
        if fmt == "xlsx":
            from openpyxl import load_workbook

            workbook = load_workbook(path)
            check("Excel com folha de relatório", "Relatório" in workbook.sheetnames, str(workbook.sheetnames))
            check("Excel com logótipo embutido", bool(workbook["Relatório"]._images), f"{len(workbook['Relatório']._images)} imagem(ns)")
        if fmt == "pdf":
            pages = content.count(b"/Type /Page") - content.count(b"/Type /Pages")
            check("PDF com pelo menos uma página", pages >= 1, f"{pages} página(s)")
            check("PDF com título no documento", b"IQ OS" in content, "marca no PDF")


def test_list_report() -> None:
    section("Relatório de lista")
    result = service.search(None, sort="contracts", size=25, from_=0)
    if result.get("error"):
        check("pesquisa para o relatório", False, str(result["error"])[:120])
        return
    items = result.get("items") or []
    check("pesquisa para o relatório", bool(items), f"{len(items)} de {result.get('total')}")
    if not items:
        return
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for fmt in ("pdf", "xlsx", "csv"):
        filename, content, media_type = report.list_report(
            items, total=int(result.get("total") or len(items)), format=fmt, filters_label="ordenação: contracts"
        )
        (OUTPUT / filename).write_bytes(content)
        check(f"lista em {fmt.upper()}", len(content) > 500, f"{filename} · {len(content)} B · {media_type.split(';')[0]}")
    check(
        "linhas do CSV correspondem aos contribuintes",
        sum(1 for line in (OUTPUT / f"iq-os-contribuintes_{report._stamp()}.csv").read_text(encoding="utf-8-sig").splitlines() if line.count(";") >= 9)
        >= len(items),
        f"{len(items)} contribuintes",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Testes dos relatórios de contribuintes.")
    parser.add_argument("nif", nargs="?", default="500189412", help="NIF a usar na ficha (omissão: 500189412)")
    args = parser.parse_args()

    test_logo()
    test_status_aggregations()
    test_reports(args.nif)
    test_list_report()

    print("\n" + "=" * 62)
    print(f"Passaram: {len(PASSES)} · Falharam: {len(FAILURES)}")
    if OUTPUT.exists():
        print(f"Ficheiros de teste em: {OUTPUT}")
        for path in sorted(OUTPUT.glob("*")):
            print(f"  · {path.name} ({path.stat().st_size} B)")
    for label in FAILURES:
        print(f"  ✗ {label}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
