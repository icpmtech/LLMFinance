"""Inspeção do delta do UpdatePanel devolvido pelo CIRE (fica em _probe_cire_out/async_datas.txt)."""
from __future__ import annotations

import re
from pathlib import Path

OUT = Path(__file__).parent / "_probe_cire_out"


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s)).strip()


def main() -> None:
    txt = (OUT / "async_datas.txt").read_text(encoding="utf-8")
    (OUT / "report.txt").write_text("", encoding="utf-8")
    lines: list[str] = []

    def out(s: str) -> None:
        lines.append(s)

    out(f"len={len(txt)}")
    out("tabelas: " + repr(re.findall(r'<table[^>]*id="([^"]+)"', txt)))
    out("inputs grid: " + repr(sorted(set(re.findall(r'id="(ctl00_ContentPlaceHolder1_gv[^"]*)"', txt)))[:20]))
    out("postbacks: " + repr(sorted(set(re.findall(r"__doPostBack\(&#39;([^&]+)&#39;", txt)))[:20]))
    out("Page$Next: " + str("Page$Next" in txt))
    msg = re.search(r'id="ctl00_ContentPlaceHolder1_lblMsg"[^>]*>(.*?)</', txt, re.S)
    out("lblMsg: " + (norm(msg.group(1)) if msg else "None"))
    # cabeçalhos de grelha
    ths = re.findall(r"<th[^>]*>(.*?)</th>", txt, re.S)
    out("THs: " + repr([norm(t)[:60] for t in ths])[:1500])
    # por cada bloco entre <tr> - testar linhas
    tables = re.findall(r"<table[^>]*>(.*?)</table>", txt, re.S)
    out(f"nº de tabelas: {len(tables)}")
    for ti, t in enumerate(tables):
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", t, re.S)
        out(f"\n### tabela {ti}: {len(rows)} linhas")
        for ri, r in enumerate(rows[:3]):
            cells = [norm(c)[:70] for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", r, re.S)]
            links = re.findall(r'href="([^"]+)"', r)
            out(f"  r{ri} ({len(cells)}): {cells}")
            if links:
                out(f"      links: {links[:3]}")
    # procurar texto total de resultados
    idx = txt.find("resultado")
    out("\ncontexto 'resultado': " + repr(norm(txt[max(0, idx - 200): idx + 400])) if idx >= 0 else "sem 'resultado'")
    (OUT / "report.txt").write_text("\n".join(lines), encoding="utf-8")
    print("relatório escrito")


if __name__ == "__main__":
    main()
