"""Sonda: estrutura dos ATOM do PLACSP (licitaciones / contratos menores)."""
import sys
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree as ET

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SAMPLES = {
    "licitaciones": Path(r"C:\temp\es_probe\lic2012.atom"),
    "menores": Path(r"C:\temp\es_probe\menor2018.atom"),
}


def local(tag: str) -> str:
    return tag.split("}")[-1]


def dump(node, trail, out):
    for ch in node:
        dump(ch, trail + [local(ch.tag)], out)
    if len(node) == 0:
        path = "/".join(trail)
        txt = (node.text or "").strip()
        attrs = {local(k): v for k, v in node.attrib.items()}
        key = path + (f"@{sorted(attrs)}" if attrs else "")
        out[key] += 1
        if out[key] == 1:
            print(f"  {key} = {txt[:100]!r}")


for nome, path in SAMPLES.items():
    print("=" * 100)
    print(nome, path, f"{path.stat().st_size / 1e6:.1f} MB")
    root = ET.parse(path).getroot()
    entries = [c for c in root if local(c.tag) == "entry"]
    print("entries:", len(entries))
    out: Counter[str] = Counter()
    print("---- campos da 1ª entry ----")
    dump(entries[0], [], out)
    out2: Counter[str] = Counter()
    dump(entries[1], [], out2)
    extra = {k for k in out2 if k.rsplit("@", 1)[0] not in out and k not in out}
    if extra:
        print("---- campos só na 2ª entry ----")
        for k in sorted(extra):
            print("  extra:", k)
    print("---- total caminhos distintos:", len(out))
    print("---- 2ª entry bruta (2500 chars) ----")
    print(ET.tostring(entries[1], encoding="unicode")[:2500])
