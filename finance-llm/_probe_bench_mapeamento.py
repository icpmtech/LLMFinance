"""Tipos dos campos de entidade nos três índices (para o filtro de pesquisa)."""
from __future__ import annotations

import json
import os

os.environ.setdefault("ELASTICSEARCH_URL", "http://127.0.0.1:9200")

from api.elasticsearch_client import get_es_client  # noqa: E402

es = get_es_client(request_timeout=60)
print("cliente:", bool(es))

ALVOS = {
    "contratos": ["adjudicatarios", "adjudicantes"],
    "contratos_es": ["adjudicatario_nif", "adjudicatario_nombre", "organo_id", "organo_nombre"],
    "contratos_fr": ["titulaires", "acheteur_id", "acheteur_nom"],
}


def resumir(no: object, caminho: str = "") -> None:
    if not isinstance(no, dict):
        return
    tipo = no.get("type")
    if tipo:
        print(f"  {caminho} -> {tipo}")
        return
    prog = no.get("properties")
    if isinstance(prog, dict):
        for chave, valor in prog.items():
            resumir(valor, f"{caminho}.{chave}" if caminho else chave)


for indice, campos in ALVOS.items():
    print("==", indice)
    mapeamento = es.indices.get_mapping(index=indice)
    props = list(mapeamento.values())[0]["mappings"].get("properties", {})
    for campo in campos:
        resumir(props.get(campo), campo)
