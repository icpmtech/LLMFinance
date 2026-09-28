"""Contagem global de pessoas extraídas de todas as publicações societárias."""
from __future__ import annotations

import os

os.environ.setdefault("ELASTICSEARCH_URL", "http://127.0.0.1:9200")

from api.elasticsearch_client import _publicacoes_for_people  # noqa: E402
from collectors.people_extractor import extract_from_publicacoes  # noqa: E402

items = _publicacoes_for_people(None)
people = extract_from_publicacoes(items)
cargos = sum(len(p.get("roles") or []) for p in people)
coletivas = sum(1 for p in people if p.get("is_company"))
com_cargo = sum(1 for p in people if (p.get("roles") or [{}])[0].get("role"))
print(f"publicações lidas: {len(items)}")
print(f"pessoas extraídas: {len(people)} (pessoas coletivas: {coletivas})")
print(f"cargos: {cargos} | pessoas com cargo preenchido: {com_cargo}")
