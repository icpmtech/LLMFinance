"""Tipos dentro dos objetos `nested` (`adjudicatarios.parsed`, `titulaires`)."""
from __future__ import annotations

import os

os.environ.setdefault("ELASTICSEARCH_URL", "http://127.0.0.1:9200")

from api.elasticsearch_client import get_es_client  # noqa: E402

es = get_es_client(request_timeout=60)


def resumir(no: object, caminho: str = "", profundidade: int = 0) -> None:
    if not isinstance(no, dict) or profundidade > 3:
        return
    tipo = no.get("type")
    if tipo:
        print(f"  {caminho} -> {tipo}")
        return
    prog = no.get("properties")
    if isinstance(prog, dict):
        for chave, valor in prog.items():
            resumir(valor, f"{caminho}.{chave}" if caminho else chave, profundidade + 1)


for indice, campos in {
    "contratos": ["adjudicatarios.parsed", "adjudicantes.parsed"],
    "contratos_fr": ["titulaires"],
}.items():
    print("==", indice)
    props = list(es.indices.get_mapping(index=indice).values())[0]["mappings"].get("properties", {})
    for campo in campos:
        resumir(props.get(campo), campo)
