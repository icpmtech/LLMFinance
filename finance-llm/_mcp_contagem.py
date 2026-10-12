"""Conta as ferramentas MCP do IQ OS por grupo (para caber no limite de 128 funções).

Uso:
    python _mcp_contagem.py [tags,...]
"""
from __future__ import annotations

import os
import sys
from collections import Counter

sys.path.insert(0, ".")

from mcp_server.catalog import OPERATIONS, TAGS  # noqa: E402

por_tag = Counter(op.tag for op in OPERATIONS)
print(f"catálogo completo: {len(OPERATIONS)} ferramentas em {len(por_tag)} grupos\n")
print(f"{'grupo':<22}{'ferramentas':>12}")
for tag, count in sorted(por_tag.items(), key=lambda item: -item[1]):
    print(f"{tag:<22}{count:>12}")

grupos = [tag.strip() for tag in (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("IQOS_MCP_TAGS", "")).split(",") if tag.strip()]
if grupos:
    selecionadas = [op for op in OPERATIONS if op.tag in grupos]
    print(f"\nseleção pedida ({', '.join(grupos)}): {len(selecionadas)} ferramentas")
    for tag in grupos:
        print(f"  {tag:<20}{por_tag.get(tag, 0):>5}")
    desconhecidos = [tag for tag in grupos if tag not in TAGS]
    if desconhecidos:
        print("  grupos desconhecidos:", ", ".join(desconhecidos))
