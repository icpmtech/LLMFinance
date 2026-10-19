"""Recolha nacional do Racius por CAE, paralela, com checkpoint e deduplicacao.

- 351 CAE de 5 digitos x ate 3 ordenacoes, ate 200 paginas (teto de 3.000 por
  consulta no Racius).
- Deduplica por NIF (fallback URL) e valida no fim que nao ha NIF repetidos.
- Checkpoint em JSON a cada 60 s e retoma de onde ficou (`CAE_LIMIT` so para
  testes).
- Indexa no ES local (9200) e no ES da VM (tunel 19200).
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, r"C:\LLMFinance\finance-llm")
from collectors import racius  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("racius-cae-nacional")
logging.getLogger("racius").setLevel(logging.WARNING)

CAES = [
    "41000", "41100", "41200", "42110", "42120", "42130", "42210", "42220", "42910", "42990",
    "43110", "43120", "43130", "43210", "43220", "43290", "43310", "43320", "43330", "43341",
    "43342", "43390", "43910", "43991", "43999",
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
    "49100", "49200", "49310", "49320", "49390", "49410", "49420", "49500", "50101", "50102",
    "50200", "50300", "50400", "51101", "51102", "51210", "51220", "52101", "52102", "52210",
    "52212", "52219", "52220", "52229", "52230", "52240", "52290", "53100", "53200",
    "55100", "55201", "55202", "55300", "55901", "55902", "56101", "56102", "56210", "56290",
    "56301", "56302",
    "58110", "58120", "58130", "58140", "58190", "58210", "58290", "59110", "59120", "59130",
    "59200", "60100", "60200", "61100", "61200", "61300", "61900", "6201", "62020", "62090",
    "63110", "63120", "63910", "63990",
    "64110", "64190", "64201", "64202", "64300", "64910", "64921", "64922", "64991", "64999",
    "65110", "65120", "65200", "65300", "66110", "66120", "66190", "66210", "66220", "66290",
    "66300", "68100", "68200", "68311", "68321",
    "69101", "69102", "69201", "69202", "70100", "70210", "70220", "71110", "71120", "71200",
    "72110", "72190", "72200", "73110", "73120", "73200", "74100", "74200", "74300", "74901",
    "74902", "74909", "75000",
    "77110", "77120", "77210", "77220", "77290", "77310", "77320", "77330", "77340", "77341",
    "77350", "77390", "77400", "78100", "78200", "78300", "79110", "79120", "79901", "79909",
    "80100", "80200", "80300", "81100", "81210", "81220", "81290", "81300", "82110", "82190",
    "82200", "82300", "82910", "82920", "82990",
    "85100", "85200", "85310", "85320", "85410", "85420", "85421", "85422", "85429", "85510",
    "85520", "85590", "85600", "86101", "86102", "86210", "86220", "86230", "86901", "86902",
    "86903", "86904", "86905", "86906", "86909", "87100", "87200", "87301", "87901", "87909",
    "88101", "88102", "88910", "88990",
    "90010", "90020", "90030", "90040", "91010", "91020", "91030", "91040", "92000", "93110",
    "93120", "93130", "93191", "93192", "93199", "93210", "93291", "93299", "94110", "94120",
    "94200", "94910", "94920", "94990", "95110", "95120", "95210", "95220", "95230", "95240",
    "95250", "95290", "96010", "96020", "96030", "96040", "96090", "97000", "98100", "98200",
]

PAGES = 200
TETO_CONSULTA = 3000
PAGE_DELAY = 0.15
WORKERS = int(os.getenv("CAE_WORKERS", "4") or 4)
STATE = Path(r"C:\LLMFinance\finance-llm\data\racius")
OUT_JSON = STATE / "racius_cae_nacional.json"
OUT_JSONL = STATE / "racius_cae_nacional.jsonl"
PROGRESS = STATE / "racius_cae_nacional.progress.json"

if int(os.getenv("CAE_LIMIT", "0") or 0):
    CAES = CAES[: int(os.getenv("CAE_LIMIT", "0"))]

_lock = threading.Lock()
_vistos: dict[str, dict] = {}
_feitos: set[str] = set()
_consultas = 0
_ultimo_checkpoint = 0.0


def chave(doc: dict) -> str:
    return (doc.get("nif") or "").strip() or (doc.get("url") or "").strip()


def gravar(force: bool = False) -> None:
    global _ultimo_checkpoint
    with _lock:
        if not force and time.time() - _ultimo_checkpoint < 60:
            return
        items = list(_vistos.values())
        feitos = sorted(_feitos)
        consultas = _consultas
        _ultimo_checkpoint = time.time()
    tmp = OUT_JSON.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, OUT_JSON)
    racius.write_jsonl(items, OUT_JSONL)
    PROGRESS.write_text(
        json.dumps(
            {
                "empresas": len(items),
                "caes_feitos": feitos,
                "caes_total": len(CAES),
                "consultas": consultas,
                "atualizado_em": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    logger.info("checkpoint: %s empresas, %s/%s CAEs", len(items), len(feitos), len(CAES))


def carregar() -> None:
    if not OUT_JSON.exists() or not PROGRESS.exists():
        return
    try:
        itens = json.loads(OUT_JSON.read_text(encoding="utf-8"))
        prog = json.loads(PROGRESS.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("checkpoint ilegivel (%s); a comecar do zero", exc)
        return
    for doc in itens:
        k = chave(doc)
        if k:
            _vistos[k] = doc
    _feitos.update(prog.get("caes_feitos") or [])
    logger.info("retomado: %s empresas, %s CAEs ja feitos", len(_vistos), len(_feitos))


def recolher_cae(cae: str) -> tuple[str, int]:
    global _consultas
    novos_cae = 0
    for sort in ("relevance", "recent", "oldest"):
        recebidos = 0
        try:
            for doc in racius.collect(
                q=cae, sort=sort, pages=PAGES, with_detail=False,
                page_delay=PAGE_DELAY, stop_on_empty_pages=3,
            ):
                recebidos += 1
                k = chave(doc)
                if not k:
                    continue
                with _lock:
                    if k not in _vistos:
                        _vistos[k] = doc
                        novos_cae += 1
        except Exception as exc:  # noqa: BLE001
            logger.error("CAE %s (%s): %s", cae, sort, exc)
        with _lock:
            _consultas += 1
            total = len(_vistos)
        logger.info("CAE %s sort=%s: %s recebidos (+%s neste CAE, total %s)", cae, sort, recebidos, novos_cae, total)
        if recebidos < TETO_CONSULTA:
            break
    with _lock:
        _feitos.add(cae)
    gravar()
    return cae, novos_cae


def main() -> int:
    inicio = time.time()
    carregar()
    pendentes = [c for c in CAES if c not in _feitos]
    logger.info("a recolher %s CAEs pendentes com %s workers", len(pendentes), WORKERS)
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futuros = {pool.submit(recolher_cae, c): c for c in pendentes}
        for i, fut in enumerate(as_completed(futuros), 1):
            cae = futuros[fut]
            try:
                fut.result()
            except Exception as exc:  # noqa: BLE001
                logger.error("CAE %s falhou: %s", cae, exc)
            if i % 10 == 0:
                logger.info("progresso: %s/%s CAEs", i, len(pendentes))
    gravar(force=True)

    items = list(_vistos.values())
    logger.info("JSON: %s empresas em %s", len(items), OUT_JSON)
    logger.info("JSONL: %s empresas em %s", len(items), OUT_JSONL)
    nifs = [d.get("nif") for d in items if d.get("nif")]
    repetidos = len(nifs) - len(set(nifs))
    logger.info("validacao: %s empresas, %s com NIF, %s repetidos", len(items), len(nifs), repetidos)
    if repetidos:
        logger.error("Ha NIF repetidos no ficheiro; abortar a indexacao.")
        return 2
    resultado = racius.index_items(items)
    logger.info("ES local: %s indexadas, %s erros", resultado.get("indexed_count"), resultado.get("error_count"))
    logger.info("duracao: %.1f min", (time.time() - inicio) / 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
