"""Importar entidades.json para o índice finance_entities."""
import sys
import time

sys.path.insert(0, ".")

from api.elasticsearch_client import ENTITIES_INDEX, get_es_client  # noqa: E402
from api.entities_service import ENTITIES_JSON, iter_normalized_entities  # noqa: E402
from api.elasticsearch_client import index_entities  # noqa: E402

es = get_es_client()
print("ES ok:", es is not None)
if not es:
    raise SystemExit("Elasticsearch indisponível")

# Recriar o índice para remover documentos com _ids antigos.
if es.indices.exists(index=ENTITIES_INDEX):
    before = es.count(index=ENTITIES_INDEX).get("count", 0)
    es.indices.delete(index=ENTITIES_INDEX)
    print(f"índice removido (tinha {before} documentos)")

t0 = time.time()
result = index_entities(
    iter_normalized_entities(ENTITIES_JSON),
    chunk_size=2000,
    refresh=True,
)
elapsed = time.time() - t0

print(f"\nresultado: {result}")
print(f"tempo: {elapsed:.1f}s")

count = es.count(index=ENTITIES_INDEX).get("count", 0)
print("documentos no índice:", count)
