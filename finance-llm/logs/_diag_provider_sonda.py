"""Que fornecedor de IA é que a sonda vai usar? (diagnóstico rápido)

Responde em segundos, sem chamar a rede: mostra o fornecedor e o modelo que
`scraper_ai.pick_provider` devolve sem indicações — é o que a sonda usa por
omissão. Sem fornecedor configurado, a sonda continua a funcionar (análise
determinística) e a resposta traz a nota de como ligar a IA.
"""
from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8")

from api import scraper_ai  # noqa: E402

provider_id, spec, model_id, chave = scraper_ai.pick_provider(None, None, None)
print("fornecedor :", provider_id)
print("etiqueta   :", (spec or {}).get("label"))
print("modelo     :", model_id or (spec or {}).get("default_model"))
print("chave      :", "sim" if chave else "não")
print("base_url   :", (spec or {}).get("base_url"))
