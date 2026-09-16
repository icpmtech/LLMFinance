#!/usr/bin/env python3
"""Reprocessamento paralelo dos contratos do Portal Base, com indexação
integrada no Elasticsearch e pausa/retoma.

Fluxo por lote: normaliza (em processos paralelos) -> indexa no ES
(_id = Ano:idcontrato, portanto idempotente e único entre anos) -> escreve JSONL -> avança
checkpoint. Só se avança o checkpoint depois do ES confirmar o lote, para
que uma falha a meio nunca deixe o JSONL "à frente" do que está indexado.

Retoma: cada ano tem um checkpoint (.ckpt.json) com o nº de registos e o
offset em bytes do JSONL. Ao retomar, o ficheiro é truncado nesse offset
(descarta escritas parciais) e a leitura salta os registos já processados.
Como a indexação é idempotente por id, mesmo que um lote seja reprocessado
por causa de uma falha anterior, o ES fica correcto (apenas sobrescreve).

Pausa: ficheiro de controlo (.pause) ou SIGUSR1 (não existe no Windows —
usa `--pause` / `--resume`). Ctrl+C = paragem graciosa.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from collections import deque
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from itertools import islice
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Ajusta o nome do módulo se o teu ficheiro original não se chamar assim.
from contratos import (  # noqa: E402
    CONTRACTS_DIR,
    PROCESSED_DIR,
    extract_zip_jsonl,
    normalize_contract,
)

CKPT_DIR = PROCESSED_DIR / ".checkpoints"
PAUSE_FILE = PROCESSED_DIR / ".pause"

_STOP = False
_PAUSED = False


# --------------------------------------------------------------------------- #
# Sinais / controlo
# --------------------------------------------------------------------------- #
def _install_signals() -> None:
    def _on_int(signum, frame):
        global _STOP
        if _STOP:
            raise KeyboardInterrupt
        _STOP = True
        print("\n[sinal] a terminar graciosamente — checkpoint será gravado...", flush=True)

    def _on_toggle(signum, frame):
        global _PAUSED
        _PAUSED = not _PAUSED
        print(f"[sinal] {'PAUSA' if _PAUSED else 'RETOMA'}", flush=True)

    signal.signal(signal.SIGINT, _on_int)
    signal.signal(signal.SIGTERM, _on_int)
    if hasattr(signal, "SIGUSR1"):
        signal.signal(signal.SIGUSR1, _on_toggle)


def _wait_while_paused() -> None:
    announced = False
    while not _STOP and (_PAUSED or PAUSE_FILE.exists()):
        if not announced:
            print("[pausa] em espera (apaga o ficheiro .pause ou usa --resume para continuar)", flush=True)
            announced = True
        time.sleep(1.0)
    if announced:
        print("[pausa] retomado", flush=True)


# --------------------------------------------------------------------------- #
# Leitura em streaming
# --------------------------------------------------------------------------- #
def iter_raw(json_path: Path) -> Iterator[Dict[str, Any]]:
    try:
        import ijson  # pip install ijson
    except ImportError:
        with open(json_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        rows = data if isinstance(data, list) else (data.get("contratos") or data.get("data") or [])
        yield from rows
        return

    with open(json_path, "rb") as fh:
        head = fh.read(4096).lstrip()
        fh.seek(0)
        prefixes = ["item"] if head[:1] == b"[" else ["contratos.item", "data.item", "item"]
        for prefix in prefixes:
            fh.seek(0)
            found = False
            for obj in ijson.items(fh, prefix):
                found = True
                yield obj
            if found:
                return
        raise ValueError(f"Não encontrei a lista de contratos em {json_path}")


def _batched(it: Iterator[Dict[str, Any]], size: int) -> Iterator[List[Dict[str, Any]]]:
    while True:
        chunk = list(islice(it, size))
        if not chunk:
            return
        yield chunk


# --------------------------------------------------------------------------- #
# Worker (top-level: tem de ser picklable para ProcessPoolExecutor)
# --------------------------------------------------------------------------- #
def _normalize_batch(batch: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[str]]:
    docs: List[Dict[str, Any]] = []
    errors: List[str] = []
    for raw in batch:
        try:
            docs.append(normalize_contract(raw))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{raw.get('idcontrato', '?')}: {type(exc).__name__}: {exc}")
    return docs, errors


# --------------------------------------------------------------------------- #
# Elasticsearch
# --------------------------------------------------------------------------- #
class ESSink:
    """Wrapper fino: cria o índice e indexa lotes com _id único por ano e contrato."""

    def __init__(self, url: str, index: str, user: Optional[str], password: Optional[str],
                 verify_certs: bool, ca_certs: Optional[str], api_key: Optional[str]):
        from elasticsearch import Elasticsearch  # pip install elasticsearch

        kwargs: Dict[str, Any] = {"verify_certs": verify_certs}
        if user and password:
            kwargs["basic_auth"] = (user, password)
        if api_key:
            kwargs["api_key"] = api_key
        if ca_certs:
            kwargs["ca_certs"] = ca_certs
        self.client = Elasticsearch(url, **kwargs)
        self.index = index
        self._ensure_index()

    def _ensure_index(self) -> None:
        if self.client.indices.exists(index=self.index):
            return
        try:
            self._create_index()
        except Exception as exc:  # noqa: BLE001 — queremos o corpo real do erro
            body = getattr(exc, "body", None) or getattr(exc, "info", None)
            print(f"[ES] erro ao criar índice '{self.index}': {exc}\n[ES] corpo: {body}", flush=True)
            raise

    def _create_index(self) -> None:
        mapping = {
            "settings": {"number_of_shards": 1, "number_of_replicas": 0},
            "mappings": {
                "properties": {
                    "idcontrato": {"type": "keyword"},
                    "nAnuncio": {"type": "keyword"},
                    "TipoAnuncio": {"type": "keyword"},
                    "tipoContrato": {"type": "keyword"},
                    "idprocedimento": {"type": "keyword"},
                    "tipoprocedimento": {"type": "keyword"},
                    "objectoContrato": {"type": "text"},
                    "descContrato": {"type": "text"},
                    "search_text": {"type": "text", "analyzer": "portuguese"},
                    "dataPublicacao": {"type": "date", "ignore_malformed": True},
                    "dataCelebracaoContrato": {"type": "date", "ignore_malformed": True},
                    "dataDecisaoAdjudicacao": {"type": "date", "ignore_malformed": True},
                    "dataFechoContrato": {"type": "date", "ignore_malformed": True},
                    "precoContratual": {"type": "double"},
                    "precoBaseProcedimento": {"type": "double"},
                    "PrecoTotalEfetivo": {"type": "double"},
                    "prazoExecucao": {"type": "double"},
                    "localExecucao": {"type": "keyword"},
                    "NUTs": {"type": "keyword"},
                    "regime": {"type": "keyword"},
                    "Ano": {"type": "integer"},
                    "cpv": {
                        "type": "nested",
                        "properties": {
                            "code": {"type": "keyword"},
                            "description": {"type": "text"},
                        },
                    },
                    "entities": {
                        "type": "nested",
                        "properties": {
                            "name": {"type": "keyword"},
                            "type": {"type": "keyword"},
                            "nif": {"type": "keyword"},
                            "code": {"type": "keyword"},
                        },
                    },
                    "adjudicantes": {
                        "properties": {
                            "raw": {"type": "text"},
                            "parsed": {
                                "type": "nested",
                                "properties": {"nif": {"type": "keyword"}, "nome": {"type": "keyword"}},
                            },
                        }
                    },
                    "adjudicatarios": {
                        "properties": {
                            "raw": {"type": "text"},
                            "parsed": {
                                "type": "nested",
                                "properties": {"nif": {"type": "keyword"}, "nome": {"type": "keyword"}},
                            },
                        }
                    },
                    "ingested_at": {"type": "date"},
                }
            },
        }
        self.client.indices.create(index=self.index, **mapping)

    def bulk_index(self, docs: List[Dict[str, Any]]) -> Tuple[int, List[str]]:
        from elasticsearch.helpers import bulk as es_bulk

        if not docs:
            return 0, []

        def _actions():
            for d in docs:
                contract_id = d.get("idcontrato")
                year = d.get("Ano")
                doc_id = f"{year}:{contract_id}" if year is not None and contract_id else contract_id or None
                action = {"_index": self.index, "_source": d}
                if doc_id:
                    action["_id"] = doc_id
                yield action

        ok, errors = es_bulk(self.client, _actions(), raise_on_error=False, stats_only=False)
        err_msgs = [str(e)[:300] for e in errors]
        return ok, err_msgs


# --------------------------------------------------------------------------- #
# Checkpoint
# --------------------------------------------------------------------------- #
def _ckpt_path(year: int) -> Path:
    return CKPT_DIR / f"contratos_{year}.ckpt.json"


def _load_ckpt(year: int) -> Dict[str, Any]:
    p = _ckpt_path(year)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _save_ckpt(year: int, state: Dict[str, Any]) -> None:
    CKPT_DIR.mkdir(parents=True, exist_ok=True)
    p = _ckpt_path(year)
    tmp = p.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    last_exc: Optional[Exception] = None
    for attempt in range(8):
        try:
            os.replace(tmp, p)
            return
        except PermissionError as exc:  # Windows: AV pode segurar o handle por instantes
            last_exc = exc
            time.sleep(0.05 * (2 ** attempt))
    print(f"\n[aviso] não consegui gravar checkpoint de {year}: {last_exc}", flush=True)
    tmp.unlink(missing_ok=True)


# --------------------------------------------------------------------------- #
# Reprocessamento de um ano
# --------------------------------------------------------------------------- #
def reprocess_year(
    year: int,
    es: Optional[ESSink],
    workers: int = 4,
    batch_size: int = 2000,
    mode: str = "process",
    force: bool = False,
    limit: Optional[int] = None,
    log_errors: bool = True,
) -> Dict[str, Any]:
    zip_path = CONTRACTS_DIR / f"contratos{year}.zip"
    if not zip_path.exists():
        return {"year": year, "error": f"ZIP não encontrado: {zip_path}"}

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    json_path = extract_zip_jsonl(zip_path, PROCESSED_DIR / "raw", force=force)
    jsonl_path = PROCESSED_DIR / f"contratos_{year}.jsonl"
    err_path = PROCESSED_DIR / f"contratos_{year}.errors.log"

    state = {} if force else _load_ckpt(year)
    if state.get("done") and not force:
        print(f"[{year}] já concluído ({state.get('records')} registos) — usa --force para refazer")
        return {"year": year, "count": state.get("records", 0), "skipped": True}

    skip = int(state.get("records", 0))
    offset = int(state.get("bytes", 0))

    if skip and jsonl_path.exists():
        out = open(jsonl_path, "r+b")
        out.truncate(offset)
        out.seek(offset)
        print(f"[{year}] retomar em {skip} registos ({offset} bytes)")
    else:
        out = open(jsonl_path, "wb")
        skip, offset = 0, 0

    errors_total = int(state.get("errors", 0))
    es_indexed_total = int(state.get("es_indexed", 0))
    written = skip
    started = time.time()
    exhausted = False
    Executor = ProcessPoolExecutor if mode == "process" else ThreadPoolExecutor
    errs_fh = open(err_path, "a", encoding="utf-8") if log_errors else None

    try:
        src = iter_raw(json_path)
        if skip:
            next(islice(src, skip, skip), None)
        batches = _batched(src, batch_size)
        pending: deque = deque()

        with Executor(max_workers=workers) as ex:
            while True:
                _wait_while_paused()
                if _STOP:
                    break

                while not exhausted and len(pending) < workers * 2:
                    batch = next(batches, None)
                    if batch is None:
                        exhausted = True
                        break
                    pending.append(ex.submit(_normalize_batch, batch))

                if not pending:
                    break

                docs, errs = pending.popleft().result()

                # 1) indexa no ES primeiro (idempotente por _id) — só depois
                #    disto avançamos o checkpoint, para nunca ficar "à frente".
                if es is not None and docs:
                    for attempt in range(5):
                        try:
                            n_ok, es_errs = es.bulk_index(docs)
                            break
                        except Exception as exc:  # noqa: BLE001 — ES em baixo/instável
                            if attempt == 4:
                                raise
                            print(f"\n[{year}] ES falhou ({exc}); nova tentativa em {2 ** attempt}s", flush=True)
                            time.sleep(2 ** attempt)
                    es_indexed_total += n_ok
                    if es_errs and errs_fh:
                        errs_fh.write("\n".join(f"[ES] {e}" for e in es_errs) + "\n")
                        errs_fh.flush()

                # 2) escreve o JSONL
                if docs:
                    payload = ("\n".join(json.dumps(d, ensure_ascii=False) for d in docs) + "\n").encode("utf-8")
                    out.write(payload)
                    out.flush()
                    os.fsync(out.fileno())

                written += len(docs)
                errors_total += len(errs)
                if errs and errs_fh:
                    errs_fh.write("\n".join(errs) + "\n")
                    errs_fh.flush()

                offset = out.tell()
                _save_ckpt(year, {"year": year, "records": written, "bytes": offset,
                                  "errors": errors_total, "es_indexed": es_indexed_total, "done": False})

                rate = (written - skip) / max(time.time() - started, 1e-6)
                print(f"[{year}] {written} registos | {es_indexed_total} no ES | "
                      f"{errors_total} erros | {rate:,.0f} rec/s", end="\r", flush=True)

                if limit and (written - skip) >= limit:
                    exhausted = False
                    break

            if _STOP:
                for f in pending:
                    f.cancel()
    finally:
        out.close()
        if errs_fh:
            errs_fh.close()

    done = exhausted and not pending and not _STOP and not limit
    _save_ckpt(year, {"year": year, "records": written, "bytes": offset,
                      "errors": errors_total, "es_indexed": es_indexed_total, "done": done})
    print()
    return {"year": year, "jsonl": str(jsonl_path), "count": written, "es_indexed": es_indexed_total,
            "errors": errors_total, "done": done, "elapsed_s": round(time.time() - started, 1)}


def discover_years() -> List[int]:
    import re
    out = []
    for p in CONTRACTS_DIR.glob("contratos*.zip"):
        m = re.search(r"(\d{4})", p.stem)
        if m:
            out.append(int(m.group(1)))
    return sorted(out)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main() -> None:
    ap = argparse.ArgumentParser(description="Reprocessa contratos em paralelo, indexando no ES, com pausa/retoma")
    ap.add_argument("--years", nargs="*", type=int, help="Anos (omite para todos)")
    ap.add_argument("--workers", type=int, default=max(os.cpu_count() or 2, 2))
    ap.add_argument("--batch-size", type=int, default=2000)
    ap.add_argument("--mode", choices=["process", "thread"], default="process")
    ap.add_argument("--limit", type=int, default=None, help="Máx. registos novos por ano")
    ap.add_argument("--force", action="store_true", help="Ignora checkpoint e recomeça do zero")
    ap.add_argument("--status", action="store_true", help="Mostra os checkpoints e sai")
    ap.add_argument("--pause", action="store_true", help="Cria o ficheiro de pausa e sai")
    ap.add_argument("--resume", action="store_true", help="Remove o ficheiro de pausa e sai")

    ap.add_argument("--no-es", action="store_true", help="Desliga a indexação (só gera JSONL)")
    ap.add_argument("--es-url", default="http://localhost:9200")
    ap.add_argument("--es-index", default="contratos")
    ap.add_argument("--es-user", default=os.environ.get("ES_USER"))
    ap.add_argument("--es-password", default=os.environ.get("ES_PASSWORD"))
    ap.add_argument("--es-api-key", default=os.environ.get("ES_API_KEY"))
    ap.add_argument("--es-ca-certs", default=os.environ.get("ES_CA_CERTS"))
    ap.add_argument("--es-no-verify-certs", action="store_true",
                     help="Desliga verificação TLS (docker local com cert self-signed)")
    args = ap.parse_args()

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    if args.pause:
        PAUSE_FILE.touch()
        print(f"pausa activa: {PAUSE_FILE}")
        return
    if args.resume:
        PAUSE_FILE.unlink(missing_ok=True)
        print("pausa removida")
        return
    if args.status:
        for y in (args.years or discover_years()):
            print(y, _load_ckpt(y) or "sem checkpoint")
        return

    es: Optional[ESSink] = None
    if not args.no_es:
        try:
            es = ESSink(
                url=args.es_url, index=args.es_index,
                user=args.es_user, password=args.es_password,
                verify_certs=not args.es_no_verify_certs,
                ca_certs=args.es_ca_certs, api_key=args.es_api_key,
            )
            print(f"[ES] ligado a {args.es_url}, índice '{args.es_index}'")
        except Exception as exc:  # noqa: BLE001
            print(f"[ES] falha a ligar ({exc}) — usa --no-es para gerar só JSONL, "
                  f"ou confirma URL/credenciais/`pip install elasticsearch`.")
            sys.exit(1)

    _install_signals()
    years = args.years or discover_years()
    if not years:
        print(f"Nenhum ZIP em {CONTRACTS_DIR}")
        return

    results = []
    for y in years:
        if _STOP:
            break
        results.append(reprocess_year(
            y, es, workers=args.workers, batch_size=args.batch_size,
            mode=args.mode, force=args.force, limit=args.limit,
        ))
        print(results[-1])

    total = sum(r.get("count", 0) for r in results)
    total_es = sum(r.get("es_indexed", 0) for r in results)
    print(f"\nTotal: {total} registos ({total_es} indexados no ES) em {len(results)} ano(s)"
          f"{' (interrompido — volta a correr para continuar)' if _STOP else ''}")


if __name__ == "__main__":
    main()
