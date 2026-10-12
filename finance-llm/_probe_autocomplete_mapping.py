"""Sonda: mapping real das partes e dos CPV no índice de contratos (autocomplete)."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api.elasticsearch_client import CONTRACTS_INDEX, get_es_client  # noqa: E402

cliente = get_es_client()
mapping = cliente.indices.get_mapping(index=CONTRACTS_INDEX)
propriedades = list(mapping.values())[0]["mappings"]["properties"]


def mostrar(caminho: str) -> None:
    no = propriedades
    for parte in caminho.split("."):
        if parte not in no:
            print(f"{caminho}: (não existe)")
            return
        no = no[parte]
    print(f"{caminho}: {json.dumps(no, ensure_ascii=False)[:400]}")


for caminho in [
    "objectoContrato",
    "descContrato",
    "adjudicantes",
    "adjudicantes.parsed",
    "adjudicantes.parsed.nome",
    "adjudicatarios.parsed.nome",
    "cpv",
    "cpv.code",
]:
    mostrar(caminho)

# Amostra de valores reais (maiúsculas/minúsculas) das partes.
amostra = cliente.search(
    index=CONTRACTS_INDEX,
    body={
        "size": 3,
        "_source": ["adjudicantes.parsed.nome", "adjudicatarios.parsed.nome", "cpv.code"],
    },
)
print("\namostra:")
print(json.dumps([hit["_source"] for hit in amostra["hits"]["hits"]], ensure_ascii=False)[:900])
