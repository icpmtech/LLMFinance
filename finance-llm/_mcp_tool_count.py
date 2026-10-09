"""Conta as ferramentas MCP por grupo — ajuda a manter-se sob o limite do cliente.

O DeepSeek (e outros clientes) recusam pedidos com mais de 128 funções
(``tools``). Este utilitário mostra quantas ferramentas cada grupo do catálogo
expõe e quantas ficam expostas para uma dada lista de grupos, para se poder
ajustar ``IQOS_MCP_TAGS`` sem estourar o limite.

Uso:
    python _mcp_tool_count.py                        # tabela por grupo
    python _mcp_tool_count.py contratos,empresas     # contagem da seleção

Nota: o servidor regista também 4 ferramentas genéricas
(``iqos_api_call``, ``iqos_search_endpoints``, ``iqos_describe_endpoint``,
``iqos_modules``), que não pertencem a nenhum grupo.
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mcp_server.catalog import OPERATIONS, TAGS  # noqa: E402

GENERICAS = 4
LIMITE_CLIENTE = 128


def main(argv: list[str]) -> int:
    por_grupo = Counter(op.tag for op in OPERATIONS)

    if len(argv) > 1:
        escolhidos = {t.strip().lower() for t in argv[1].split(",") if t.strip()}
        validos = {t.lower() for t in TAGS}
        desconhecidos = escolhidos - validos
        if desconhecidos:
            print(f"Grupos desconhecidos: {sorted(desconhecidos)}")
            print(f"Válidos: {sorted(TAGS)}")
            return 2
        curadas = sum(n for t, n in por_grupo.items() if t.lower() in escolhidos)
        for t in sorted(escolhidos):
            nome = next((g for g in TAGS if g.lower() == t), t)
            print(f"  {nome}: {por_grupo.get(nome, 0)}")
        total = curadas + GENERICAS
        print(f"\nTotal exposto pelo servidor MCP: {total} ({curadas} curadas + {GENERICAS} genéricas)")
        print(f"Limite do cliente: {LIMITE_CLIENTE} (deixar folga para ~64 ferramentas do VS Code)")
        print("Margem: " + ("OK" if total <= LIMITE_CLIENTE - 64 else "DEMASIADO ALTO — reduzir grupos"))
        return 0

    print(f"Catálogo: {sum(por_grupo.values())} operações curadas em {len(TAGS)} grupos\n")
    for tag, n in por_grupo.most_common():
        print(f"{tag:<20} {n:>3}")
    print(f"\n{'TOTAL':<20} {sum(por_grupo.values()):>3}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
