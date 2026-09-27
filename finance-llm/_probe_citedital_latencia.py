"""Mede a resposta do portal agora (o portal limita pedidos agressivos?).

Faz 3 pedidos espaçados e cronometra cada um, para distinguir entre «portal lento»
e «portal a bloquear esta origem» — foi o que deixou uma recolha presa na página 13.

Uso:
    python _probe_citedital_latencia.py [n_pedidos]
"""
from __future__ import annotations

import sys
import time
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
)

N = int(sys.argv[1]) if len(sys.argv) > 1 else 3

client = CitacoesEditalClient(min_interval=0.0)
inicio = time.monotonic()
client.fetch_form()
print(f"formulário: {time.monotonic() - inicio:.1f}s · serviços {len(client.tribunais())}")

prefixo = FIELD_NOME.rsplit("$", 1)[0]
for i in range(N):
    t0 = time.monotonic()
    try:
        if i == 0:
            html = client._post(
                client._payload(
                    BUTTON_SEARCH,
                    **{FIELD_NOME: "", FIELD_DIAS: "todos", FIELD_TRIBUNAL: client.tribunais()[0]["value"]},
                )
            )
        else:
            html = client._post(client._payload(f"{prefixo}$Pager1$lnkNext"))
        client._absorb(html)
        print(
            f"pedido {i + 1}: {time.monotonic() - t0:.1f}s · página {current_page(html)} · "
            f"itens {len(parse_items(html))}"
        )
    except Exception as exc:  # noqa: BLE001
        print(f"pedido {i + 1}: FALHOU em {time.monotonic() - t0:.1f}s · {type(exc).__name__}: {exc}")
    time.sleep(2)
