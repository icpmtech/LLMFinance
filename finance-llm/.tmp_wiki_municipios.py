"""Inspecciona a Lista de municípios de Portugal (temporário)."""
import re
from collections import Counter

import httpx

CABECALHOS = {"User-Agent": "IQOS/1.0 (analise de financas publicas; contacto@icpm.tech)"}
API = "https://pt.wikipedia.org/w/api.php"
cliente = httpx.Client(timeout=90.0, headers=CABECALHOS)

for titulo in ("Lista de municípios de Portugal", "Municípios de Portugal"):
    try:
        dados = cliente.get(
            API,
            params={"action": "parse", "page": titulo, "prop": "wikitext", "format": "json", "formatversion": "2"},
        ).json()
        if "error" in dados:
            print(titulo, "-> erro:", dados["error"].get("info"))
            continue
        texto = dados["parse"]["wikitext"]
        print("=" * 70)
        print(titulo, "| wikitext:", len(texto), "caracteres | tabelas:", texto.count("{|"))
        print("predefinicoes:", Counter(re.findall(r"\{\{([A-Za-zÀ-ÿ0-9 _\-]+)", texto)).most_common(8))
        for i, bloco in enumerate(re.findall(r"\{\|.*?\|\}", texto, re.S)[:3]):
            print(f"---- tabela {i} (primeiros 1200 caracteres) ----")
            print(bloco[:1200])
    except Exception as excecao:  # noqa: BLE001
        print(titulo, "-> falhou:", excecao)
