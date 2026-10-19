"""Recolha nacional do Racius por CAE, com checkpoint e deduplicacao.

- Percorre uma lista de CAE de 5 digitos (o Racius so reconhece o codigo
  completo) em tres ordenacoes, ate 200 paginas (o teto de 3.000 por consulta).
- Deduplica por NIF (fallback: URL) em memoria.
- Grava JSON a cada CAE (checkpoint atomico), para nada se perder.
- No fim valida que nao ha NIF repetidos e indexa no Elasticsearch.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, r"C:\LLMFinance\finance-llm")
from collectors import racius  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("racius-cae-nacional")

CAES = [
    # Construcao (41-43)
    "41000", "41100", "41200", "42110", "42120", "42130", "42210", "42220", "42910", "42990",
    "43110", "43120", "43130", "43210", "43220", "43290", "43310", "43320", "43330", "43341",
    "43342", "43390", "43910", "43991", "43999",
    # Comercio (45-47)
    "45111", "45112", "45190", "45200", "45201", "45310", "45320", "45400", "46111", "46121",
    "46131", "46140", "46150", "46170", "46180", "46190", "46211", "46212", "46213", "46220",
    "46230", "46311", "46321", "46331", "46341", "46342", "46350", "46360", "46370", "46381",
    "46382", "46390", "46410", "46420", "46431", "46441", "46450", "46460", "46470", "46480",
    "46491", "46492", "46494", "46499", "46510", "46520", "46530", "46610", "46620", "46630",
    "46640", "46650", "46660", "46690", "46711", "46712", "46720", "46730", "46740", "46750",
    "46760", "46771", "46779", "46900", "47110", "47190", "47210", "47220", "47230", "47240",
    "47250", "47260", "47290", "47300", "47410", "47420", "47430", "47510", "47520", "47530",
    "47540", "47591", "47599", "47610", "47620", "47630", "47710", "47720", "47730", "47740",
    "47750", "47760", "47770", "47780", "47781", "47782", "47783", "47789", "47791", "47799",
    "47810", "47820", "47910", "47990",
    # Transportes (49-53)
    "49100", "49200", "49310", "49320", "49390", "49410", "49420", "49500", "50101", "50102",
    "50200", "50300", "50400", "51101", "51102", "51210", "51220", "52101", "52102", "52210",
    "52212", "52219", "52220", "52229", "52230", "52240", "52290", "53100", "53200",
    # Alojamento e restauracao (55-56)
    "55100", "55201", "55202", "55300", "55901", "55902", "56101", "56102", "56210", "56290",
    "56301", "56302",
    # Informacao e comunicacao (58-63)
    "58110", "58120", "58130", "58140", "58190", "58210", "58290", "59110", "59120", "59130",
    "59200", "60100", "60200", "61100", "61200", "61300", "61900", "6201", "62020", "62090",
    "63110", "63120", "63910", "63990",
    # Financeiro e imobiliario (64-68)
    "64110", "64190", "64201", "64202", "64300", "64910", "64921", "64922", "64991", "64999",
    "65110", "65120", "65200", "65300", "66110", "66120", "66190", "66210", "66220", "66290",
    "66300", "68100", "68200", "68311", "68321",
    # Servicos profissionais e tecnicos (69-75)
    "69101", "69102", "69201", "69202", "70100", "70210", "70220", "71110", "71120", "71200",
    "72110", "72190", "72200", "73110", "73120", "73200", "74100", "74200", "74300", "74901",
    "74902", "74909", "75000",
    # Administrativos e apoio (77-82)
    "77110", "77120", "77210", "77220", "77290", "77310", "77320", "77330", "77340", "77341",
    "77350", "77390", "77400", "78100", "78200", "78300", "79110", "79120", "79901", "79909",
    "80100", "80200", "80300", "81100", "81210", "81220", "81290", "81300", "82110", "82190",
    "82200", "82300", "82910", "82920", "82990",
    # Educacao, saude, acao social (85-88)
    "85100", "85200", "85310", "85320", "85410", "85420", "85421", "85422", "85429", "85510",
    "85520", "85590", "85600", "86101", "86102", "86210", "86220", "86230", "86901", "86902",
    "86903", "86904", "86905", "86906", "86909", "87100", "87200", "87301", "87901", "87909",
    "88101", "88102", "88910", "88990",
    # Artes, desporto e outros servicos (90-96)
    "90010", "90020", "90030", "90040", "91010", "91020", "91030", "91040", "92000", "93110",
    "93120", "93130", "93191", "93192", "93199", "93210", "93291", "93299", "94110", "94120",
    "94200", "94910", "94920", "94990", "95110", "95120", "95210", "95220", "95230", "95240",
    "95250", "95290", "96010", "96020", "96030", "96040", "96090", "97000", "98100", "98200",
]

PAGES = 200
#: Teto de resultados por consulta no Racius (200 paginas de 15).
TETO_CONSULTA = 3000
PAGE_DELAY = 0.12
#: Limite opcional de CAEs (testes): `$env:CAE_LIMIT=2`.
_limite = int(os.getenv("CAE_LIMIT", "0") or 0)
if _limite:
    CAES = CAES[:_limite]
STATE = Path(r"C:\LLMFinance\finance-llm\data\racius")
OUT_JSON = STATE / "racius_cae_nacional.json"
OUT_JSONL = STATE / "racius_cae_nacional.jsonl"
PROGRESS = STATE / "racius_cae_nacional.progress.json"


def chave(doc: dict) -> str:
    return (doc.get("nif") or "").strip() or (doc.get("url") or "").strip()


def gravar(vistos: dict, caes_feitos: list, total_consultas: int) -> None:
    items = list(vistos.values())
    tmp = OUT_JSON.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, OUT_JSON)
    racius.write_jsonl(items, OUT_JSONL)
    PROGRESS.write_text(
        json.dumps(
            {
                "empresas": len(items),
                "caes_feitos": caes_feitos,
                "caes_total": len(CAES),
                "consultas": total_consultas,
                "atualizado_em": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    logger.info("checkpoint: %s empresas, %s/%s CAEs", len(items), len(caes_feitos), len(CAES))


def main() -> int:
    vistos: dict[str, dict] = {}
    feitos: list[str] = []
    consultas = 0
    inicio = time.time()

    for indice_cae, cae in enumerate(CAES, 1):
        for sort in ("relevance", "recent", "oldest"):
            antes = len(vistos)
            recebidos = 0
            try:
                for doc in racius.collect(
                    q=cae,
                    sort=sort,
                    pages=PAGES,
                    with_detail=False,
                    page_delay=PAGE_DELAY,
                    stop_on_empty_pages=3,
                ):
                    recebidos += 1
                    k = chave(doc)
                    if k and k not in vistos:
                        vistos[k] = doc
            except Exception as exc:  # noqa: BLE001 — segue com o que tem
                logger.error("CAE %s (%s) interrompido: %s", cae, sort, exc)
            consultas += 1
            logger.info(
                "CAE %s [%s/%s] sort=%s: %s recebidos, +%s novos (total %s)",
                cae, indice_cae, len(CAES), sort, recebidos, len(vistos) - antes, len(vistos),
            )
            # Consulta abaixo do teto: nao ha mais resultados por outra ordenacao.
            if recebidos < TETO_CONSULTA:
                break
        feitos.append(cae)
        gravar(vistos, feitos, consultas)

    items = list(vistos.values())
    gravar(vistos, feitos, consultas)
    logger.info("JSON: %s empresas em %s", len(items), OUT_JSON)
    logger.info("JSONL: %s empresas em %s", len(items), OUT_JSONL)

    # Validacao de duplicados antes de indexar.
    nifs = [d.get("nif") for d in items if d.get("nif")]
    repetidos = len(nifs) - len(set(nifs))
    logger.info("validacao: %s empresas, %s com NIF, %s repetidos", len(items), len(nifs), repetidos)
    if repetidos:
        logger.error("Ha NIF repetidos; abortar a indexacao.")
        return 2

    result = racius.index_items(items)
    logger.info("Elasticsearch local: %s indexadas, %s erros", result.get("indexed_count"), result.get("error_count"))
    logger.info("duracao: %.1f min", (time.time() - inicio) / 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
