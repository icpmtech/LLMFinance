"""Recolha alargada por CAE: nacional + distrito do Porto.

Estratégia:
1. Gera CAEs de 5 dígitos relevantes a partir de uma seed list (construção,
   restauração, transportes, comércio, serviços, TI, etc.).
2. Para cada CAE, recolhe até 200 páginas (3.000 empresas) por ordenação
   (score, -id, id) dentro do distrito do Porto.
3. Deduplica por NIF/URL e indexa em finance_racius.
"""
import sys
import json
import logging
import time

sys.path.insert(0, r"C:\LLMFinance\finance-llm")
from collectors import racius  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("racius-cae")

# CAEs de 5 dígitos que o Racius reconhece e têm volume em Portugal.
# Selecionados para cobrir atividades comuns em contratos públicos.
CAES = [
    # Construção (grupo 41)
    "41000", "41100", "41200", "42110", "42120", "42130", "42210", "42910", "43110", "43120",
    "43210", "43220", "43290", "43310", "43320", "43330", "43341", "43342", "43910", "43991",
    "43999",
    # Comércio por grosso/retalho (45-47)
    "45111", "45200", "45310", "45320", "45400", "46111", "46121", "46131", "46211", "46212",
    "46311", "46341", "46431", "46450", "46460", "46494", "46510", "46610", "46711", "46712",
    "46900", "47110", "47190", "47210", "47220", "47230", "47240", "47250", "47290", "47530",
    "47710", "47780", "47782", "47789", "47910",
    # Transportes (49-52)
    "49100", "49200", "49310", "49320", "49410", "49510", "50200", "51102", "51210", "52212",
    "52219", "52222", "52229",
    # Alojamento/restauração (55-56)
    "55100", "55201", "55300", "55901", "55902", "56101", "56102", "56210", "56301",
    # TI / telecoms / media (58-63)
    "58210", "61100", "61200", "61300", "6201", "6202", "6311", "6312", "63990",
    # Serviços profissionais / técnicos (64-78)
    "6420", "64910", "64922", "64991", "6621", "6622", "6629", "68311", "68320", "69102",
    "69201", "70220", "7111", "7112", "71200", "7311", "7312", "7320", "74300", "74901",
    "74909", "77110", "77320", "77341", "77390", "78100", "80100", "80200", "81210",
    # Saúde, educação, social (85-88)
    "85510", "86101", "86210", "86901", "87301", "88100", "88910",
    # Outros com volume
    "6820", "68100", "70100", "82920",
]

PAGES = 200
vistos = {}


def coletar(cae: str):
    global vistos
    for sort in ("relevance", "recent", "oldest"):
        antes = len(vistos)
        empty_pages = 0
        try:
            for doc in racius.collect(
                q=cae,
                distrito="porto",
                sort=sort,
                pages=PAGES,
                with_detail=False,
                page_delay=0.2,
            ):
                chave = doc.get("nif") or doc.get("url")
                if chave and chave not in vistos:
                    vistos[chave] = doc
        except Exception as exc:  # noqa: BLE001
            logger.error("CAE %s sort=%s interrompido: %s", cae, sort, exc)
        logger.info("CAE %s sort=%s: +%s (total %s)", cae, sort, len(vistos) - antes, len(vistos))

for cae in CAES:
    coletar(cae)

items = list(vistos.values())
out = racius.SINK_DIR / "porto_por_cae.jsonl"
logger.info("JSONL: %s empresas", racius.write_jsonl(items, out))
logger.info("JSON: %s empresas", racius.write_json(items, out.with_suffix(".json")))
result = racius.index_items(items)
logger.info("Elasticsearch: %s indexadas, %s erros", result.get("indexed_count"), result.get("error_count"))
