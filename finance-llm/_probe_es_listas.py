"""Sonda: extrai os listURI dos códigos usados no feed PLACSP e descarrega as listas oficiais."""
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import requests

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
DIR = Path(r"c:\LLMFinance\finance-llm\data\contratos-espanha")
CACHE = Path(r"C:\temp\es_probe\codigos")
CACHE.mkdir(parents=True, exist_ok=True)


def local(tag):
    return tag.split("}")[-1]


def walk(node, trail, out, listuris):
    for ch in node:
        walk(ch, trail + [local(ch.tag)], out, listuris)
        uri = ch.attrib.get("listURI") or ch.attrib.get("listAgencyID")
        if uri:
            listuris.setdefault("/".join(trail + [local(ch.tag)]), set()).add(uri)
    if len(node) == 0:
        out["/".join(trail)] = (node.text or "").strip()


zp = DIR / "licitacionesPerfilesContratanteCompleto3_2023.zip"
with zipfile.ZipFile(zp) as zf:
    name = sorted(n for n in zf.namelist() if n.lower().endswith(".atom"))[0]
    root = ET.fromstring(zf.read(name))

entries = [c for c in root if local(c.tag) == "entry"]
listuris: dict[str, set] = {}
for entry in entries[:50]:
    walk(entry, [], {}, listuris)
for path, uris in sorted(listuris.items()):
    print(f"{path}: {sorted(uris)}")

# Descarregar as listas relevantes (.gc = genericode XML)
alvos = {}
for path, uris in listuris.items():
    if path.split("/")[-1] in {"TypeCode", "SubTypeCode", "ContractFolderStatusCode", "ResultCode", "ProcedureCode"}:
        for u in uris:
            alvos.setdefault(path, u)

for path, url in alvos.items():
    dest = CACHE / (url.rsplit("/", 1)[-1] + ".xml")
    if not dest.exists():
        try:
            r = requests.get(url, timeout=30)
            dest.write_bytes(r.content)
        except Exception as exc:  # noqa: BLE001
            print(f"ERRO {path}: {exc}")
            continue
    print("=" * 90)
    print(path, "->", url, f"({dest.stat().st_size} bytes)")
    try:
        tree = ET.parse(dest)
    except Exception as exc:  # noqa: BLE001
        print("  parse falhou:", exc, dest.read_text(encoding="utf-8", errors="replace")[:500])
        continue
    gc_root = tree.getroot()
    pairs = []
    for row in gc_root.iter():
        if local(row.tag) != "Row":
            continue
        code = value = label = None
        for ch in row:
            vals = [ (g.text or "").strip() for g in ch.iter() if local(g.tag) == "SimpleValue" ]
            if local(ch.tag) == "Value":
                code_name = ch.attrib.get("ColumnRef", "")
                v = vals[0] if vals else ""
                if code_name == "code":
                    code = v
                elif code_name in {"name", "description", "label"}:
                    label = v
        pairs.append((code, label))
    for c, l in pairs[:60]:
        print(f"  {c} = {l}")
