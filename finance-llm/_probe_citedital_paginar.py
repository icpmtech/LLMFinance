"""Sondagem: paginação profunda da lista completa (sem nome).

Confirma três coisas antes de lançar uma recolha de vários milhares de éditos:
1. que a lista completa (``txtNome`` vazio) se mantém estável ao longo das páginas;
2. que as datas **descem** (é isso que permite cortar nos «últimos N anos»);
3. que a última página (2700) não é um erro do parser.

Uso:
    python _probe_citedital_paginar.py [numero_de_paginas]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from collectors.citius_citacoes import (  # noqa: E402
    BUTTON_SEARCH,
    FIELD_DIAS,
    FIELD_NOME,
    FIELD_TRIBUNAL,
    CitacoesEditalClient,
    current_page,
    parse_items,
    result_count,
)

PAGINAS = int(sys.argv[1]) if len(sys.argv) > 1 else 60

client = CitacoesEditalClient()
client.fetch_form()
prefixo = FIELD_NOME.rsplit("$", 1)[0]

html = client._post(
    client._payload(
        BUTTON_SEARCH,
        **{FIELD_NOME: "", FIELD_DIAS: "todos", FIELD_TRIBUNAL: client.tribunais()[0]["value"]},
    )
)
client._absorb(html)
print(f"página {current_page(html)} · declarados {result_count(html)} · itens {len(parse_items(html))}")
print("  datas:", [i.data_publicacao for i in parse_items(html)])

for _ in range(PAGINAS - 1):
    html = client._post(client._payload(f"{prefixo}$Pager1$lnkNext"))
    client._absorb(html)
    pagina = current_page(html)
    itens = parse_items(html)
    if _ % 10 == 9 or pagina <= 3:
        print(
            f"página {pagina} · itens {len(itens)} · "
            f"{itens[0].data_publicacao if itens else '—'} → {itens[-1].data_publicacao if itens else '—'}"
        )
    if not itens:
        print(f"página {pagina}: sem itens — a parar. "
              f"blocos resultadocdital: {len(re.findall('resultadocdital', html))}")
        break

# última página
html_last = client._post(client._payload(f"{prefixo}$Pager1$btnLastPage"))
client._absorb(html_last)
print(
    f"\núltima página {current_page(html_last)} · itens {len(parse_items(html_last))} · "
    f"blocos resultadocdital: {len(re.findall('resultadocdital', html_last))}"
)
m = re.search(r"(?:Nenhum|Sem)\s+\w+.{0,80}", html_last, re.I)
if m:
    print("  aviso da página:", re.sub(r"\s+", " ", m.group(0))[:120])
