"""Última página da lista completa: por que razão não tem itens e que data traz.

Guarda o HTML em ``logs/citedital/ultima_pagina.html`` e mostra os blocos de
resultado, para se perceber o âmbito real do histórico do portal (a lista vem por
data descendente, pelo que a última página é a mais antiga).
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

DESTINO = Path("logs/citedital/ultima_pagina.html")
DESTINO.parent.mkdir(parents=True, exist_ok=True)

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
print(f"pesquisa completa: {result_count(html)} editais declarados")

html = client._post(client._payload(f"{prefixo}$Pager1$btnLastPage"))
client._absorb(html)
DESTINO.write_text(html, encoding="utf-8")
print(f"última página: {current_page(html)} · itens parseados: {len(parse_items(html))}")
print("blocos «resultadocdital»:", len(re.findall(r'class="resultadocdital"', html)))
print("ids DataList:", sorted(set(re.findall(r"DataList_ctl\d+", html)))[:6])
print("datas no HTML:", sorted(set(re.findall(r"\d{2}/\d{2}/\d{4}", html)))[:8])

# O bloco de resultados e o aviso (se existir) explicam a página vazia.
for padrao in (r'<div id="divresultadocdital".{0,700}', r"resultadocdital.{0,400}", r"(?:Nenhum|Sem|não)\s+\w+\s+\w+.{0,120}"):
    m = re.search(padrao, html, re.S | re.I)
    if m:
        print(f"\n--- {padrao} ---")
        print(" ", re.sub(r"\s+", " ", m.group(0))[:700])
