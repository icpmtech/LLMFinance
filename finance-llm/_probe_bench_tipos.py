"""Tipos exatos dos campos usados no filtro de pesquisa de entidades."""
from __future__ import annotations

import os

os.environ.setdefault("ELASTICSEARCH_URL", "http://127.0.0.1:9200")

from api.elasticsearch_client import get_es_client  # noqa: E402

es = get_es_client(request_timeout=60)

PEDIDOS = {
    "contratos": ["adjudicatarios.parsed.nif", "adjudicatarios.parsed.nome", "adjudicantes.parsed.nif", "adjudicantes.parsed.nome"],
    "contratos_es": ["adjudicatario_nif", "adjudicatario_nombre", "organo_id", "organo_nombre"],
    "contratos_fr": ["titulaires.id", "titulaires.nom", "acheteur_id", "acheteur_nom"],
}

for indice, campos in PEDIDOS.items():
    print("==", indice)
    resposta = es.indices.get_field_mapping(index=indice, fields=",".join(campos))
    mapeamento = resposta.get(indice, {}).get("mappings", {})
    for campo in campos:
        entradas = mapeamento.get(campo, {}).get("mapping", {})
        tipos = sorted({valor.get("type") for valor in entradas.values() if valor.get("type")})
        print(f"  {campo} -> {tipos or 'não mapeado'}")
