"""Converte as cores fixas dos componentes IQ OS em variaveis de tema.

Reporta cada substituicao com a contagem, para poder ser conferido - em vez de
30 edicoes manuais sem rasto. Só mexe em `docker/mirofish/frontend/src`.

Uso: python _tema_css.py            (aplica)
     python _tema_css.py --check    (so relatorio)
"""

import pathlib
import re
import sys

ROOT = pathlib.Path(r"c:\LLMFinance\finance-llm\docker\mirofish\frontend\src")
FILES = [
    ROOT / "views" / "Home.vue",
    ROOT / "components" / "IqosHistory.vue",
    ROOT / "components" / "IqosCharts.vue",
]

# Substituicoes por token: cada uma tem sempre o mesmo significado nos tres
# ficheiros (superficie, texto, borda, aviso...), por isso pode ser global.
PAIRS = [
    ("var(--border)", "var(--iq-border)"),
    ("var(--gray-text)", "var(--iq-muted)"),
    ("var(--orange)", "var(--iq-accent)"),
    ("background: #fff;", "background: var(--iq-surface);"),
    ("background: #fafafa;", "background: var(--iq-surface-2);"),
    ("background: #f0f0f0;", "background: var(--iq-track);"),
    ("background: #ddd;", "background: var(--iq-track);"),
    ("background: #111;", "background: var(--iq-fg);"),
    ("background: #D92D20;", "background: var(--iq-danger);"),
    ("background: #FFF6ED;", "background: var(--iq-accent-soft);"),
    ("background: #fff7f4;", "background: var(--iq-accent-soft);"),
    ("background: rgba(255, 255, 255, 0.94);", "background: var(--iq-topbar);"),
    ("background: rgba(0, 0, 0, 0.55);", "background: var(--iq-overlay);"),
    ("border: 1px solid #111;", "border: 1px solid var(--iq-fg);"),
    ("border-color: #111;", "border-color: var(--iq-fg);"),
    ("border-color: #ddd;", "border-color: var(--iq-track);"),
    ("border-color: #D92D20;", "border-color: var(--iq-danger);"),
    ("border-top-color: #D92D20;", "border-top-color: var(--iq-danger);"),
    ("border-left: 3px solid #111;", "border-left: 3px solid var(--iq-fg);"),
    ("border-bottom: 1px solid #f2f2f2;", "border-bottom: 1px solid var(--iq-border);"),
    ("color: #111;", "color: var(--iq-fg);"),
    ("color: #D92D20;", "color: var(--iq-danger);"),
    ("color: #8a8a8a;", "color: var(--iq-muted);"),
    ("color: #888;", "color: var(--iq-muted);"),
    ("fill: #111;", "fill: var(--iq-fg);"),
    ("box-shadow: 0 6px 18px rgba(0, 0, 0, 0.07);", "box-shadow: 0 6px 18px var(--iq-shadow);"),
]

# Blocos em que o fundo e escuro e o texto tem de ficar com a cor oposta
# (`.ghost.active`, `.view-toggle button.active`): o `color: #fff` generico
# teria de ser tratado antes de qualquer substituicao de `#111`.
DARK_PAIR = (r"background: #111;\r?\n(\s*)color: #fff;", r"background: var(--iq-fg);\n\1color: var(--iq-bg);")

check_only = "--check" in sys.argv

for path in FILES:
    original = path.read_text(encoding="utf-8")
    text = original
    print(f"\n=== {path.name} ===")

    text, blocks = re.subn(DARK_PAIR[0], DARK_PAIR[1], text)
    if blocks:
        print(f"  {blocks}x  bloco fundo escuro + texto oposto")

    for old, new in PAIRS:
        count = text.count(old)
        if count:
            text = text.replace(old, new)
            print(f"  {count:>3}x  {old}  ->  {new}")

    if text != original:
        if check_only:
            print("  (nao gravado: --check)")
        else:
            path.write_text(text, encoding="utf-8")
            print("  gravado")

print("\n--- cores fixas restantes (para revisao manual) ---")
for path in FILES:
    text = path.read_text(encoding="utf-8")
    for line_no, line in enumerate(text.splitlines(), 1):
        for match in re.finditer(r"(#[0-9A-Fa-f]{3,8}|rgba?\([^)]*\))", line):
            print(f"{path.name}:{line_no}: {line.strip()}")
