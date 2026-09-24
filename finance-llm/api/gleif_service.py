"""Módulo GLEIF / LEI — registos *Legal Entity Identifier* (Golden Copy).

O **GLEIF** (Global Legal Entity Identifier Foundation) publica o *Golden Copy*
dos registos LEI: quem é quem no sistema financeiro global (nome legal, endereço,
jurisdição, forma jurídica, estado do registo, datas e identificadores
associados — BIC, MIC, OCID, QCC, S&P Global).

Este serviço guarda esses registos em **dois sítios**, para que o módulo funcione
mesmo com o Elasticsearch em baixo:

1. **ficheiro** — `data/gleif/lei.jsonl`, um documento normalizado por linha
   (a «golden copy» local, versionável e inspecionável);
2. **Elasticsearch** — índice `finance_gleif_lei`, com pesquisa incremental por
   nome (`gleif_index_analyzer`, n-gramas) e agregações por país, região,
   estado, categoria e forma jurídica (alimenta a vista e o mapa).

Origem dos dados (``source``):

======  ==========================================================================
Valor                O que faz
======  ==========================================================================
`api`                Percorre a API oficial do GLEIF por país/jurisdição. É a via
                     normal: o universo completo são 3,4 M de registos.
`golden-copy`        Lê um ficheiro Golden Copy local (ZIP com CSV/XML do
                     LEI-CDF, `.csv`, `.xml`, `.json` ou `.jsonl`) — a carga em massa.
`golden-copy-download`  Descarrega o Golden Copy mais recente do `leidata.gleif.org`
                     (LEI2 ≈ 540 MB) e importa-o.
`file`               (Re)indexa a golden copy local (`data/gleif/lei.jsonl`) sem
                     voltar a descarregar nada.
======  ==========================================================================

As rotas vivem em `api/gleif_routes.py` (`/gleif/*`); a recolha em
`collectors/gleif.py`.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from elasticsearch.helpers import bulk

from api.elasticsearch_client import (
    GLEIF_LEI_INDEX,
    ensure_indices,
    get_es_client,
)
from collectors import gleif as collector

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "gleif"
LEI_FILE = DATA_DIR / "lei.jsonl"
META_FILE = DATA_DIR / "meta.json"
GOLDEN_DIR = DATA_DIR / "golden-copy"

#: Dimensões agregáveis do índice (usadas pela vista e pelos filtros da UI).
FACET_FIELDS: Dict[str, str] = {
    "country": "country",
    "region": "region",
    "status": "status",
    "category": "category",
    "legal_form": "legal_form",
    "verification": "corroboration_level",
    "lou": "managing_lou",
}

#: Rótulos legíveis das facetas (a UI mostra-os nos chips).
FACET_LABELS: Dict[str, str] = {
    "country": "País da sede",
    "region": "Região (distrito)",
    "status": "Estado da entidade",
    "category": "Categoria",
    "legal_form": "Forma jurídica",
    "verification": "Nível de corroboração",
    "lou": "LOU emissor",
}

WRITE_CHUNK = 2000

#: Registo de sincronizações (em memória, como nos restantes módulos de recolha).
_JOBS: Dict[str, Dict[str, Any]] = {}
_JOBS_LOCK = threading.Lock()
_MAX_JOBS = 20


# --------------------------------------------------------------------- estado
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_meta() -> Dict[str, Any]:
    if not META_FILE.exists():
        return {
            "last_run": None,
            "history": [],
            "golden_copy": None,
            "countries": list(collector.DEFAULT_COUNTRIES),
        }
    try:
        return json.loads(META_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"last_run": None, "history": [], "golden_copy": None}


def _save_meta(meta: Dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(meta, ensure_ascii=False, indent=2, default=str)
    tmp = META_FILE.with_suffix(".json.part")
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(META_FILE)


def _file_stats() -> Dict[str, Any]:
    """Estatísticas da golden copy local (linhas, tamanho e última alteração)."""
    if not LEI_FILE.exists():
        return {"path": str(LEI_FILE), "exists": False, "records": 0, "bytes": 0, "modified": None}
    lines = 0
    with LEI_FILE.open("r", encoding="utf-8") as handle:
        for _ in handle:
            lines += 1
    stat = LEI_FILE.stat()
    return {
        "path": str(LEI_FILE),
        "exists": True,
        "records": lines,
        "bytes": stat.st_size,
        "modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
    }


def _golden_copy_files() -> List[Dict[str, Any]]:
    if not GOLDEN_DIR.exists():
        return []
    out: List[Dict[str, Any]] = []
    for path in sorted(GOLDEN_DIR.glob("*")):
        if path.is_file() and not path.name.endswith(".part"):
            stat = path.stat()
            out.append(
                {
                    "name": path.name,
                    "path": str(path),
                    "bytes": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                }
            )
    return out


def meta() -> Dict[str, Any]:
    """Metadados do módulo: índice, ficheiro, fontes, facetas e agendamento."""
    meta_state = _load_meta()
    return {
        "module": "gleif",
        "label": "GLEIF / LEI",
        "index": GLEIF_LEI_INDEX,
        "file": str(LEI_FILE),
        "golden_copy_dir": str(GOLDEN_DIR),
        "sources": [
            {"id": "api", "label": "API oficial do GLEIF (por país/jurisdição)"},
            {"id": "file", "label": "Golden copy local (data/gleif/lei.jsonl)"},
            {"id": "golden-copy", "label": "Ficheiro Golden Copy local (ZIP/CSV/XML/JSON)"},
            {"id": "golden-copy-download", "label": "Descarregar Golden Copy do GLEIF (leidata)"},
        ],
        "levels": [
            {"id": "lei", "label": "Nível 1 — quem é quem (LEI-CDF)"},
            {"id": "rr", "label": "Nível 2 — relações (RR-CDF)"},
        ],
        "default_countries": list(collector.DEFAULT_COUNTRIES),
        "facets": [{"id": key, "label": FACET_LABELS.get(key, key), "field": field} for key, field in FACET_FIELDS.items()],
        "pt_regions": collector.PT_REGIONS,
        "last_run": meta_state.get("last_run"),
        "countries": meta_state.get("countries") or list(collector.DEFAULT_COUNTRIES),
    }


def status() -> Dict[str, Any]:
    """Volumetria e distribuições: o que está no Elasticsearch e no ficheiro."""
    client = get_es_client()
    out: Dict[str, Any] = {
        "index": GLEIF_LEI_INDEX,
        "file": _file_stats(),
        "golden_copy_files": _golden_copy_files(),
        "meta": _load_meta(),
        "elasticsearch": {"available": bool(client)},
    }
    if not client:
        out["error"] = "Elasticsearch indisponível"
        return out

    ensure_indices(client)
    try:
        out["elasticsearch"]["count"] = client.count(index=GLEIF_LEI_INDEX).get("count", 0)
    except Exception as exc:  # noqa: BLE001
        out["elasticsearch"]["error"] = str(exc)
        return out

    facets: Dict[str, List[Dict[str, Any]]] = {}
    for key, field in FACET_FIELDS.items():
        try:
            response = client.search(
                index=GLEIF_LEI_INDEX,
                size=0,
                body={"aggs": {"values": {"terms": {"field": field, "size": 40}}}},
            )
            buckets = response.get("aggregations", {}).get("values", {}).get("buckets", [])
            facets[key] = [{"key": b["key"], "count": b["doc_count"]} for b in buckets]
        except Exception:  # noqa: BLE001
            facets[key] = []
    out["facets"] = facets

    # Série temporal: LEIs por ano de registo inicial.
    try:
        response = client.search(
            index=GLEIF_LEI_INDEX,
            size=0,
            body={
                "aggs": {
                    "years": {
                        "date_histogram": {
                            "field": "initial_registration_date",
                            "calendar_interval": "year",
                            "format": "yyyy",
                            "min_doc_count": 1,
                        }
                    }
                }
            },
        )
        out["timeline"] = [
            {"year": b.get("key_as_string") or str(b.get("key")), "count": b["doc_count"]}
            for b in response.get("aggregations", {}).get("years", {}).get("buckets", [])
        ]
    except Exception:  # noqa: BLE001
        out["timeline"] = []
    return out


# ------------------------------------------------------------------- pesquisa
def _filters(
    *,
    country: Optional[str] = None,
    region: Optional[str] = None,
    status: Optional[str] = None,
    category: Optional[str] = None,
    legal_form: Optional[str] = None,
    verification: Optional[str] = None,
    lou: Optional[str] = None,
    city: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Constrói as cláusulas `filter` a partir dos parâmetros da UI."""
    clauses: List[Dict[str, Any]] = []
    for field, value in (
        ("country", country),
        ("region", region),
        ("status", status),
        ("category", category),
        ("legal_form", legal_form),
        ("corroboration_level", verification),
        ("managing_lou", lou),
        ("city", city),
    ):
        if value:
            clauses.append({"term": {field: value}})
    return clauses


def _item(source: Dict[str, Any]) -> Dict[str, Any]:
    """Cartão de resultado (o que a lista da UI mostra)."""
    return {
        "lei": source.get("lei"),
        "legal_name": source.get("legal_name"),
        "other_names": source.get("other_names") or [],
        "country": source.get("country"),
        "region": source.get("region"),
        "region_name": source.get("region_name"),
        "city": source.get("city"),
        "address_lines": source.get("address_lines") or [],
        "postal_code": source.get("postal_code"),
        "status": source.get("status"),
        "registration_status": source.get("registration_status"),
        "category": source.get("category"),
        "legal_form": source.get("legal_form"),
        "legal_form_other": source.get("legal_form_other"),
        "jurisdiction": source.get("jurisdiction"),
        "managing_lou": source.get("managing_lou"),
        "corroboration_level": source.get("corroboration_level"),
        "conformity_flag": source.get("conformity_flag"),
        "registered_as": source.get("registered_as"),
        "registered_at": source.get("registered_at"),
        "initial_registration_date": source.get("initial_registration_date"),
        "last_update_date": source.get("last_update_date"),
        "next_renewal_date": source.get("next_renewal_date"),
        "creation_date": source.get("creation_date"),
        "bic": source.get("bic"),
        "mic": source.get("mic"),
        "ocid": source.get("ocid"),
        "qcc": source.get("qcc"),
        "gem": source.get("gem"),
        "spglobal": source.get("spglobal"),
        "source": source.get("source"),
    }


def search(
    q: Optional[str] = None,
    *,
    size: int = 20,
    from_: int = 0,
    sort: str = "relevance",
    **filters: Optional[str],
) -> Dict[str, Any]:
    """Pesquisa registos LEI (nome, LEI, cidade, NIF de registo) com filtros."""
    client = get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "items": [], "total": 0}
    ensure_indices(client)

    must: List[Dict[str, Any]] = []
    text = (q or "").strip()
    if text:
        must.append(
            {
                "bool": {
                    "should": [
                        {"match": {"legal_name": {"query": text, "boost": 4}}},
                        {"match_phrase": {"legal_name": {"query": text, "boost": 6}}},
                        {"match": {"other_names": {"query": text}}},
                        {"match": {"transliterated_names": {"query": text}}},
                        {"match": {"city": {"query": text, "boost": 2}}},
                        {"term": {"lei": {"value": text.upper(), "boost": 8}}},
                        {"term": {"registered_as": {"value": text, "boost": 5}}},
                        {"term": {"bic": {"value": text.upper(), "boost": 3}}},
                        {"term": {"managing_lou": {"value": text.upper()}}},
                    ],
                    "minimum_should_match": 1,
                }
            }
        )

    body: Dict[str, Any] = {
        "query": {"bool": {"must": must or [{"match_all": {}}], "filter": _filters(**filters)}},
        "from": max(0, from_),
        "size": max(1, min(200, size)),
        "track_total_hits": True,
        "aggs": {
            key: {"terms": {"field": field, "size": 30}} for key, field in FACET_FIELDS.items()
        },
    }
    if sort == "name":
        body["sort"] = [{"legal_name.keyword": "asc"}]
    elif sort == "updated":
        body["sort"] = [{"last_update_date": "desc"}]
    elif sort == "registered":
        body["sort"] = [{"initial_registration_date": "desc"}]

    try:
        response = client.search(index=GLEIF_LEI_INDEX, body=body)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "items": [], "total": 0}

    hits = response.get("hits", {})
    total = hits.get("total", {})
    total_value = total.get("value", 0) if isinstance(total, dict) else int(total or 0)
    facets = {
        key: [{"key": b["key"], "count": b["doc_count"]} for b in (response.get("aggregations", {}).get(key, {}).get("buckets", []))]
        for key in FACET_FIELDS
    }
    return {
        "query": text or None,
        "total": total_value,
        "from": max(0, from_),
        "size": body["size"],
        "items": [_item(hit.get("_source") or {}) for hit in hits.get("hits", [])],
        "facets": facets,
        "facet_labels": FACET_LABELS,
        "took_ms": response.get("took"),
    }


def autocomplete(q: str, *, size: int = 8) -> Dict[str, Any]:
    """Sugestões de entidades para a caixa de pesquisa (nome + LEI + cidade)."""
    text = (q or "").strip()
    if len(text) < 2:
        return {"query": text, "suggestions": []}
    result = search(text, size=size, sort="relevance")
    suggestions = [
        {
            "lei": item["lei"],
            "name": item["legal_name"],
            "label": f"{item['legal_name']} · {item['lei']}",
            "country": item["country"],
            "city": item["city"],
            "status": item["status"],
        }
        for item in result.get("items", [])
    ]
    return {"query": text, "suggestions": suggestions}


def detail(lei: str) -> Optional[Dict[str, Any]]:
    """Ficha completa de um LEI (null se não existir)."""
    client = get_es_client()
    if not client:
        return None
    ensure_indices(client)
    try:
        response = client.get(index=GLEIF_LEI_INDEX, id=lei.upper())
    except Exception:  # noqa: BLE001
        # Sem `_id` conhecido, procura pelo campo.
        result = search(lei, size=1)
        items = result.get("items") or []
        if not items:
            return None
        try:
            response = client.get(index=GLEIF_LEI_INDEX, id=items[0]["lei"])
        except Exception:
            return None
    source = response.get("_source") or {}
    return {**_item(source), "transliterated_names": source.get("transliterated_names") or [], "hq_city": source.get("hq_city"), "hq_country": source.get("hq_country"), "hq_region": source.get("hq_region"), "validated_as": source.get("validated_as"), "ingested_at": source.get("ingested_at")}


# -------------------------------------------------------------------- o mapa
def map_data(
    *,
    level: str = "country",
    metric: str = "count",
    country: Optional[str] = None,
    size: int = 400,
    **filters: Optional[str],
) -> Dict[str, Any]:
    """Agrega os registos por **país** ou por **região** — a base do mapa OSM.

    Devolve `{key, label, count}` por cada divisão; o frontend resolve as
    coordenadas (centroides de país/distrito) e desenha os círculos sobre os
    tiles do OpenStreetMap.
    """
    client = get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "regions": []}
    ensure_indices(client)

    field = "country" if level == "country" else "region"
    clauses = _filters(country=country, **filters)
    body: Dict[str, Any] = {
        "size": 0,
        "query": {"bool": {"filter": clauses or [{"match_all": {}}]}},
        "aggs": {
            "regions": {
                "terms": {"field": field, "size": max(1, min(1000, size))},
                "aggs": {
                    "cities": {"cardinality": {"field": "city", "precision_threshold": 40000}},
                    "active": {"filter": {"term": {"status": "ACTIVE"}}},
                    "updated": {"max": {"field": "last_update_date"}},
                },
            }
        },
    }
    try:
        response = client.search(index=GLEIF_LEI_INDEX, body=body)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "regions": []}

    regions: List[Dict[str, Any]] = []
    for bucket in response.get("aggregations", {}).get("regions", {}).get("buckets", []):
        key = bucket["key"]
        label = collector.PT_REGIONS.get(key, key) if level == "region" else key
        regions.append(
            {
                "key": key,
                "label": label,
                "count": bucket["doc_count"],
                "active": bucket.get("active", {}).get("doc_count", 0),
                "cities": bucket.get("cities", {}).get("value", 0),
                "last_update": bucket.get("updated", {}).get("value_as_string"),
            }
        )

    total = client.count(index=GLEIF_LEI_INDEX).get("count", 0)
    return {
        "level": level,
        "metric": metric,
        "field": field,
        "regions": regions,
        "index_total": total,
        "returned_total": sum(r["count"] for r in regions),
        "took_ms": response.get("took"),
    }


# ------------------------------------------------------------------ ingestão
def _job_snapshot(job: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in job.items() if k != "cancel"}


def jobs() -> List[Dict[str, Any]]:
    with _JOBS_LOCK:
        return [_job_snapshot(job) for job in _JOBS.values()]


def job(job_id: str) -> Optional[Dict[str, Any]]:
    with _JOBS_LOCK:
        found = _JOBS.get(job_id)
        return _job_snapshot(found) if found else None


def _register_job(job_id: str, **fields: Any) -> None:
    with _JOBS_LOCK:
        _JOBS[job_id] = {"id": job_id, "started_at": _now(), "status": "running", **fields}
        if len(_JOBS) > _MAX_JOBS:
            for key in list(_JOBS)[: len(_JOBS) - _MAX_JOBS]:
                if key != job_id:
                    _JOBS.pop(key, None)


def _update_job(job_id: str, **fields: Any) -> None:
    with _JOBS_LOCK:
        if job_id in _JOBS:
            _JOBS[job_id].update(fields)


def _docs_from_source(
    source: str,
    *,
    countries: List[str],
    path: Optional[Path],
    limit: Optional[int],
    job_id: str,
    download: bool = False,
) -> Iterable[Dict[str, Any]]:
    """Escolhe o iterador de documentos adequado à origem pedida."""
    if source == "file":
        return _iter_local_file(limit)
    if source == "golden-copy":
        if not path:
            raise RuntimeError("Indique o ficheiro Golden Copy (ZIP/CSV/XML/JSON).")
        resolved = Path(path)
        if not resolved.is_absolute():
            resolved = GOLDEN_DIR / resolved
        if not resolved.exists():
            raise RuntimeError(f"Ficheiro não encontrado: {resolved}")
        return collector.iter_golden_copy_file(resolved)

    if source in {"golden-copy-download", "download"}:
        GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
        dest = GOLDEN_DIR / "lei2-latest.zip"
        if download or not dest.exists():
            _update_job(job_id, phase="download", note=f"a descarregar {dest.name}")
            collector.download_golden_copy(dest)
        _update_job(job_id, phase="parse", note=f"a ler {dest.name}")
        meta_state = _load_meta()
        _save_meta({**meta_state, "golden_copy": {"path": str(dest), "at": _now()}})
        return collector.iter_golden_copy_file(dest)

    return collector.fetch_from_api(countries or [], limit=limit)


def _iter_local_file(limit: Optional[int]) -> Iterable[Dict[str, Any]]:
    if not LEI_FILE.exists():
        raise RuntimeError(f"Golden copy local inexistente: {LEI_FILE}")
    count = 0
    with LEI_FILE.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except Exception:
                continue
            count += 1
            if limit and count >= limit:
                return


def _delete_country_docs(client: Any, countries: List[str]) -> int:
    if not countries:
        return 0
    try:
        response = client.delete_by_query(
            index=GLEIF_LEI_INDEX,
            body={"query": {"terms": {"country": countries}}},
            refresh=False,
            conflicts="proceed",
        )
        return int(response.get("deleted") or 0)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Não foi possível apagar documentos de %s: %s", countries, exc)
        return 0


def _run_ingest(
    job_id: str,
    *,
    source: str,
    countries: List[str],
    path: Optional[Path],
    limit: Optional[int],
    replace: bool,
    download: bool,
    fetch_remote: bool,
) -> None:
    """Trabalho de ingestão (corre numa thread): ficheiro + índice."""
    started = time.time()
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        client = get_es_client()
        if not client:
            raise RuntimeError("Elasticsearch indisponível — a recolha precisa do índice.")
        ensure_indices(client)

        if replace and source in {"api", "golden-copy", "file"} and countries:
            _update_job(job_id, phase="replace", note=f"a substituir {', '.join(countries)}")
            _delete_country_docs(client, countries)

        iterator = _docs_from_source(
            source,
            countries=countries,
            path=path,
            limit=limit,
            job_id=job_id,
            download=download,
        )

        # 1) Escrever a golden copy local (substitui-a quando a recolha é completa
        #    para os países pedidos; acrescenta quando é um `limit` de amostra).
        append = bool(limit)
        mode = "a" if append else "w"
        seen: set[str] = set()
        total = 0
        indexed = 0
        errors = 0
        batch: List[Dict[str, Any]] = []
        _update_job(job_id, phase="index", total=0, indexed=0)

        with LEI_FILE.open(mode, encoding="utf-8") as handle:
            for doc in iterator:
                lei = doc.get("lei")
                if not lei or lei in seen:
                    continue
                seen.add(lei)
                handle.write(json.dumps(doc, ensure_ascii=False) + "\n")
                total += 1
                batch.append(doc)
                if len(batch) >= WRITE_CHUNK:
                    ok, bad = _bulk(client, batch)
                    indexed += ok
                    errors += bad
                    batch = []
                    _update_job(job_id, total=total, indexed=indexed, errors=errors)
                if total % 5000 == 0:
                    _update_job(job_id, total=total, indexed=indexed, errors=errors)
            if batch:
                ok, bad = _bulk(client, batch)
                indexed += ok
                errors += bad
            handle.flush()

        try:
            client.indices.refresh(index=GLEIF_LEI_INDEX)
        except Exception:
            pass

        duration = round(time.time() - started, 1)
        summary = {
            "job_id": job_id,
            "source": source,
            "countries": countries,
            "records": total,
            "indexed": indexed,
            "errors": errors,
            "duration_s": duration,
            "finished_at": _now(),
            "file": str(LEI_FILE),
            "index_total": client.count(index=GLEIF_LEI_INDEX).get("count", 0),
        }
        meta_state = _load_meta()
        history = [summary, *(meta_state.get("history") or [])][:20]
        _save_meta(
            {
                **meta_state,
                "last_run": summary,
                "history": history,
                "countries": countries or meta_state.get("countries"),
            }
        )
        _update_job(job_id, status="done", phase="done", **summary)
        logger.info("GLEIF: %s registos indexados (%s erros) em %ss", indexed, errors, duration)
    except Exception as exc:  # noqa: BLE001
        logger.exception("GLEIF: ingestão falhou")
        _update_job(job_id, status="error", error=str(exc), finished_at=_now())


def _bulk(client: Any, docs: List[Dict[str, Any]]) -> Tuple[int, int]:
    """Indexa um bloco de documentos (um por LEI) e devolve (ok, erros)."""
    actions = [
        {"_index": GLEIF_LEI_INDEX, "_id": doc["lei"], "_source": doc}
        for doc in docs
        if doc.get("lei")
    ]
    if not actions:
        return 0, 0
    try:
        ok, errors = bulk(client, actions, raise_on_error=False, stats_only=False)
        bad = len(errors) if isinstance(errors, list) else int(errors or 0)
        return int(ok), bad
    except Exception as exc:  # noqa: BLE001
        logger.warning("Bulk GLEIF falhou: %s", exc)
        return 0, len(actions)


def ingest(
    *,
    source: str = "api",
    countries: Optional[List[str]] = None,
    path: Optional[str] = None,
    limit: Optional[int] = None,
    replace: bool = True,
    download: bool = False,
    wait: bool = False,
) -> Dict[str, Any]:
    """Arranca uma ingestão (em segundo plano, salvo `wait=True`)."""
    job_id = uuid.uuid4().hex[:12]
    scope = [c.strip().upper() for c in (countries or list(collector.DEFAULT_COUNTRIES)) if c and c.strip()]
    if source in {"golden-copy", "golden-copy-download", "download"}:
        scope = list(collector.DEFAULT_COUNTRIES) if replace and not countries else scope
        if not countries:
            scope = []
    _register_job(job_id, source=source, countries=scope, phase="start", total=0, indexed=0, errors=0)
    thread = threading.Thread(
        target=_run_ingest,
        kwargs={
            "job_id": job_id,
            "source": source,
            "countries": scope,
            "path": Path(path) if path else None,
            "limit": limit,
            "replace": replace,
            "download": download,
            "fetch_remote": source == "api",
        },
        daemon=True,
    )
    thread.start()
    if wait:
        thread.join()
        return job(job_id) or {"id": job_id, "status": "unknown"}
    return {"job_id": job_id, "status": "running", "source": source, "countries": scope}


def delete_index() -> Dict[str, Any]:
    """Esvazia o índice (e opcionalmente a golden copy local não é tocada)."""
    client = get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}
    try:
        if client.indices.exists(index=GLEIF_LEI_INDEX):
            client.indices.delete(index=GLEIF_LEI_INDEX)
        ensure_indices(client)
        return {"deleted": True, "index": GLEIF_LEI_INDEX}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


def export_csv(limit: int = 5000) -> str:
    """Exporta a golden copy local para CSV (nome, LEI, país, região, cidade…)."""
    import csv
    import io as _io

    buffer = _io.StringIO()
    fields = [
        "lei",
        "legal_name",
        "country",
        "region",
        "region_name",
        "city",
        "postal_code",
        "status",
        "registration_status",
        "category",
        "legal_form",
        "managing_lou",
        "registered_as",
        "initial_registration_date",
        "last_update_date",
        "next_renewal_date",
        "bic",
        "ocid",
    ]
    writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for index, doc in enumerate(_iter_local_file(None)):
        if index >= limit:
            break
        writer.writerow({field: doc.get(field) for field in fields})
    return buffer.getvalue()


def warmup() -> None:
    """Aquece o índice (a primeira pesquisa a frio pode demorar na criação)."""
    try:
        client = get_es_client()
        if client:
            ensure_indices(client)
    except Exception:  # noqa: BLE001
        pass


__all__ = [
    "DATA_DIR",
    "LEI_FILE",
    "GOLDEN_DIR",
    "FACET_FIELDS",
    "FACET_LABELS",
    "meta",
    "status",
    "search",
    "autocomplete",
    "detail",
    "map_data",
    "ingest",
    "jobs",
    "job",
    "delete_index",
    "export_csv",
    "warmup",
]
