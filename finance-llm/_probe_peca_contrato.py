"""Probe: descarrega a «peça do procedimento» de um contrato e inspeciona o conteúdo.

Uso:
    python _probe_peca_contrato.py 15609253
"""
from __future__ import annotations

import io
import json
import sys
import zipfile

import requests

UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "pt-PT,pt;q=0.9",
}

BASE = "http://127.0.0.1:8002"
ES = "http://127.0.0.1:9200"


def get_contract(idcontrato: str) -> dict:
    r = requests.get(f"{ES}/contratos/_search?q=idcontrato:{idcontrato}&size=1", timeout=20)
    hits = r.json().get("hits", {}).get("hits", [])
    return hits[0]["_source"] if hits else {}


def main() -> None:
    idcontrato = sys.argv[1] if len(sys.argv) > 1 else "15609253"
    src = get_contract(idcontrato)
    print("linkPecasProc:", src.get("linkPecasProc"))
    print("idprocedimento:", src.get("idprocedimento"))
    print("precoContratual:", src.get("precoContratual"), "| base:", src.get("precoBaseProcedimento"))

    link = src.get("linkPecasProc")
    if not link:
        print("sem linkPecasProc")
        return

    s = requests.Session()
    s.headers.update(UA)
    r = s.get(link, timeout=60)
    print("GET", r.status_code, r.headers.get("content-type"), len(r.content), "bytes")
    data = r.content
    if data[:2] != b"PK":
        print("não é ZIP; primeiros bytes:", data[:16])
        return

    zf = zipfile.ZipFile(io.BytesIO(data))
    print("\n--- conteúdo do ZIP ---")
    for info in zf.infolist():
        print(f"  {info.file_size:>9}  {info.filename}")

    try:
        import fitz  # pymupdf
    except Exception as exc:  # pragma: no cover
        print("pymupdf indisponível:", exc)
        fitz = None  # type: ignore

    for info in zf.infolist():
        name = info.filename.lower()
        if name.endswith(".pdf") and fitz is not None:
            doc = fitz.open(stream=zf.read(info.filename), filetype="pdf")
            print(f"\n--- {info.filename}: {doc.page_count} páginas ---")
            text = "\n".join(page.get_text() for page in doc)
        elif name.endswith(".docx"):
            text = _docx_text(zf.read(info.filename))
            print(f"\n--- {info.filename} (docx) ---")
        else:
            continue
        print(text[:2500])
        print("... [len texto]", len(text))


def _docx_text(blob: bytes) -> str:
    """Extrai o texto de um .docx sem dependências externas."""
    import xml.etree.ElementTree as ET

    with zipfile.ZipFile(io.BytesIO(blob)) as inner:
        xml = inner.read("word/document.xml")
    root = ET.fromstring(xml)
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    lines = []
    for para in root.iter(f"{ns}p"):
        chunks = [t.text or "" for t in para.iter(f"{ns}t")]
        if chunks:
            lines.append("".join(chunks))
    return "\n".join(lines)


if __name__ == "__main__":
    main()
