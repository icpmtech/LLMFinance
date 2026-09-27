"""Sondagem: recolher por **tribunal/serviço** com o nome vazio.

O plano para recolher a lista completa em tempo útil é dividir o espaço por
serviço (257 valores do `ddlTribunais`) e correr vários serviços em paralelo
(cada um com a sua sessão). Antes disso é preciso confirmar:

1. que o filtro por serviço **com o nome vazio** devolve os éditos desse serviço;
2. quanto vale a soma dos serviços (deve dar o total da lista completa, 26 992);
3. que, dentro de um serviço, as datas também vêm por ordem descendente.

Uso:
    python _probe_citedital_por_tribunal.py [n_tribunais]
"""
from __future__ import annotations

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

N = int(sys.argv[1]) if len(sys.argv) > 1 else 5

client = CitacoesEditalClient()
client.fetch_form()
tribunais = client.tribunais()
print(f"serviços: {len(tribunais)} · exemplo: {tribunais[1]['label']}")

prefixo = FIELD_NOME.rsplit("$", 1)[0]
total = 0
for opcao in tribunais[1 : N + 1]:
    html = client._post(
        client._payload(
            BUTTON_SEARCH,
            **{FIELD_NOME: "", FIELD_DIAS: "todos", FIELD_TRIBUNAL: opcao["value"]},
        )
    )
    client._absorb(html)
    itens = parse_items(html)
    declarados = result_count(html)
    total += declarados
    print(
        f"\n{opcao['label'][:52]:<52} {declarados:>6} éditos · página {current_page(html)} · itens {len(itens)}"
    )
    print("   datas:", [i.data_publicacao for i in itens][:5], "…", [i.data_publicacao for i in itens][-2:])

    # segunda página do mesmo serviço (confirma a ordenação descendente)
    if len(itens):
        html2 = client._post(client._payload(f"{prefixo}$Pager1$lnkNext"))
        client._absorb(html2)
        itens2 = parse_items(html2)
        print("   página 2:", [i.data_publicacao for i in itens2][:5])

print(f"\nsoma dos {N} primeiros serviços: {total} éditos")
