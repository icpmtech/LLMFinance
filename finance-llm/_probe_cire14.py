"""Extrai o painel upResultados de um delta ASP.NET e mostra a grelha (linhas/colunas/links)."""
from __future__ import annotations

import re
import sys
from pathlib import Path

OUT = Path(__file__).parent / "_probe_cire_out"


def parse(delta: str):
    parts, i, n = [], 0, len(delta)
    while i < n:
        j = delta.find("|", i)
        if j < 0:
            break
        try:
            length = int(delta[i:j])
        except ValueError:
            break
        k = delta.find("|", j + 1)
        kind = delta[j + 1:k]
        m = delta.find("|", k + 1)
        ident = delta[k + 1:m]
        start = m + 1
        parts.append((kind, ident, delta[start:start + length]))
        i = start + length
        if i < n and delta[i] == "|":
            i += 1
    return parts


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s)).strip()


def main() -> None:
    name = sys.argv[1] if len(sys.argv) > 1 else "v_sfm_target_btn_datas.txt"
    delta = (OUT / name).read_text(encoding="utf-8")
    lines: list[str] = [f"### {name} len={len(delta)}"]
    for kind, ident, content in parse(delta):
        if not ident.endswith("upResultados"):
            continue
        lines.append(f"\n=== upResultados ({len(content)} chars) ===")
        lines.append("TEXTO: " + norm(content)[:600])
        lines.append("TABELAS: " + repr(re.findall(r'<table[^>]*id="([^"]*)"', content)))
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", content, re.S)
        lines.append(f"LINHAS: {len(rows)}")
        headers = [norm(c) for c in re.findall(r"<th[^>]*>(.*?)</th>", content, re.S)]
        if headers:
            lines.append("CABEÇALHOS: " + repr(headers))
        for ri, row in enumerate(rows[:6]):
            cells = [norm(c)[:80] for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row, re.S)]
            links = re.findall(r'href="([^"]+)"', row)
            lines.append(f"  r{ri} n={len(cells)}: {cells}")
            if links:
                lines.append(f"      links: {links[:4]}")
        lines.append("POSTBACKS: " + repr(sorted(set(re.findall(r"__doPostBack\(&#39;([^&]+)&#39;", content)))[:12]))
        lines.append("HTML BRUTO (1500): " + re.sub(r"\s+", " ", content)[:1500])
    (OUT / "grid_report.txt").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines)[:6000])


if __name__ == "__main__":
    main()
