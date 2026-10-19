"""Recolha alargada do distrito do Porto (lista, sem fichas).

O Racius devolve no máximo 3.000 resultados por consulta (200 páginas de 15), por
isso percorrem-se as três ordenações e deduplica-se por NIF/URL. Grava JSONL e
JSON em `data/racius/` e indexa em `finance_racius`.
"""
import sys
import logging

sys.path.insert(0, r"C:\LLMFinance\finance-llm")
from collectors import racius  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("porto")

PAGES = 200
PREFIX = racius.SINK_DIR
vistos = {}
for sort in ("relevance", "recent", "oldest"):
    antes = len(vistos)
    try:
        for doc in racius.collect(
            "", distrito="porto", sort=sort, pages=PAGES, with_detail=False, page_delay=0.25
        ):
            chave = doc.get("nif") or doc.get("url")
            if chave and chave not in vistos:
                vistos[chave] = doc
    except Exception as exc:  # noqa: BLE001 — guarda o que já veio
        logger.error("Ordenação %s interrompida: %s", sort, exc)
    logger.info("sort=%s: +%s novos (total %s)", sort, len(vistos) - antes, len(vistos))

items = list(vistos.values())
out = PREFIX / "porto.jsonl"
logger.info("JSONL: %s empresas", racius.write_jsonl(items, out))
logger.info("JSON: %s empresas", racius.write_json(out.with_suffix(".json"), items))
result = racius.index_items(items)
logger.info("Elasticsearch: %s indexadas, %s erros", result.get("indexed_count"), result.get("error_count"))
