"""Sondagem: recolher TODOS os éditos (sem nome) e ver até onde vai o histórico.

O formulário exige o nome do interveniente (validator `cvRequiredFields`, do lado
do cliente), mas o servidor aceita o campo vazio e devolve a lista completa. Este
script confirma isso e procura o controlo da **última página** do paginador, para
saber a data mais antiga publicada no portal sem percorrer as ~530 páginas.

Uso:
    python _probe_citedital_tudo.py [pagina_a_saltar]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from collectors.citius_citacoes import (  # noqa: E402
    BUTTON_SEARCH,
    CitacoesEditalClient,
    FIELD_DIAS,
    FIELD_NOME,
    FIELD_TRIBUNAL,
)

client = CitacoesEditalClient()
client.fetch_form()
print(f"serviços: {len(client.tribunais())}")

# --- pesquisa sem nome -------------------------------------------------------
html = client._post(
    client._payload(  # noqa: SLF001 - sondagem
        BUTTON_SEARCH,
        **{FIELD_NOME: "", FIELD_DIAS: "todos", FIELD_TRIBUNAL: client.tribunais()[0]["value"]},
    )
)
client._absorb(html)  # noqa: SLF001
total = re.search(r"([\d\.]+)\s*(?:editais|registos)\s+encontrad", html, re.I)
print("sem nome -> total:", total.group(1) if total else "?")
print("  página:", re.search(r'Pager1_lblPageNumber"[^>]*>\s*(\d+)', html).group(1))
datas = re.findall(r"(\d{2}/\d{2}/\d{4})", html)[:12]
print("  datas da 1.ª página:", datas)

# --- controlos do paginador --------------------------------------------------
pager = re.findall(r"Pager1_[A-Za-z0-9_]+", html)
print("controlos Pager1:", sorted(set(pager)))
for alvo in ("lnkLast", "btnLastPage", "lblPageNumber", "LastDots"):
    m = re.search(rf'.{{0,220}}Pager1_{alvo}.{{0,220}}', html, re.S)
    if m:
        print(f"--- {alvo} ---")
        print(" ", re.sub(r"\s+", " ", m.group(0))[:400])

# --- última página (data mais antiga do portal) ------------------------------
from collectors.citius_citacoes import parse_items  # noqa: E402

html_last = client._post(client._payload(f"{FIELD_NOME.rsplit('$', 1)[0]}$Pager1$btnLastPage"))  # noqa: SLF001
client._absorb(html_last)  # noqa: SLF001
itens = parse_items(html_last)
print("\núltima página:", re.search(r'Pager1_lblPageNumber"[^>]*>\s*(\d+)', html_last).group(1))
print("  itens:", len(itens), "| datas:", [i.data_publicacao for i in itens])
print("  títulos:", [i.ato for i in itens][:3])
