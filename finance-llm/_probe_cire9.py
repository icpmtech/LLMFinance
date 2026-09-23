"""Lista todas as ocorrências de btnSearch / validadores no HTML para perceber o fluxo de submissão."""
from __future__ import annotations

import re
from pathlib import Path

OUT = Path(__file__).parent / "_probe_cire_out"


def main() -> None:
    page = (OUT / "page.html").read_text(encoding="utf-8")
    out: list[str] = []
    for m in re.finditer(r"btnSearch", page):
        i = m.start()
        out.append(f"\n--- ocorrência @{i} ---\n" + re.sub(r"\s+", " ", page[max(0, i - 700): i + 700]))
    out.append("\n\n===== validadores =====")
    for vid in ("cvDates", "cvRequiredDataDesde", "cvRequiredDataAte", "cvNif", "cvNome", "revPesquisaNomeSpecialChars"):
        for m in re.finditer(r'id="ctl00_ContentPlaceHolder1_' + vid + r'"[^>]*', page):
            out.append(re.sub(r"\s+", " ", m.group(0))[:600])
    out.append("\n\n===== ValidationSummary / Validators JS =====")
    for m in re.finditer(r"<script[^>]*>(.*?)</script>", page, re.S):
        s = m.group(1)
        if "Valid" in s and ("function" in s):
            out.append(re.sub(r"\s+", " ", s)[:2000])
    (OUT / "btns.txt").write_text("\n".join(out), encoding="utf-8")
    print("ok -> _probe_cire_out/btns.txt", len(out), "blocos")


if __name__ == "__main__":
    main()
