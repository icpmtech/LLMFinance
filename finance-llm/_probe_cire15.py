"""Guarda o HTML bruto do painel de resultados (itens) para desenhar o parser."""
from __future__ import annotations

import re
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


def main() -> None:
    delta = (OUT / "v_sfm_target_btn_datas.txt").read_text(encoding="utf-8")
    content = next(c for k, i, c in parse(delta) if i.endswith("upResultados"))
    (OUT / "resultados.html").write_text(content, encoding="utf-8")
    i = content.find("divResultados")
    seg = content[i:i + 6000]
    (OUT / "item_sample.html").write_text(seg, encoding="utf-8")
    print("guardado. classes usadas:")
    print(sorted(set(re.findall(r'class="([^"]+)"', content)))[:40])
    print("ids de itens:", sorted(set(re.findall(r"id=\"([^\"]+)\"", content)))[:40])
    print("links:", sorted(set(re.findall(r'href="([^"]+)"', content)))[:20])


if __name__ == "__main__":
    main()
