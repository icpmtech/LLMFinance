"""Lista de sociedades com **mais de 200 ações** (Portaria n.º 200/2011).

Para efeitos de aplicação da taxa de justiça das **tabelas I-C e II-B** do
Regulamento das Custas Processuais, a DGAJ elabora — até 15 de janeiro, em
colaboração com o IGFEJ — a lista das sociedades comerciais que, no ano civil
anterior, **intentaram mais de 200 ações, procedimentos ou execuções**
(n.º 3 do artigo 13.º do RCP e Portaria n.º 200/2011, de 20 de maio). As
sociedades da lista autoliquidam a taxa agravada em todos os processos que
intentem e são notificadas, até 25 de janeiro, por carta registada.

O que este módulo faz:

1. **recolhe** a lista da consulta pública do Portal CITIUS
   (`/portal/consultas/Custas/Portaria200-2011.aspx`), percorrendo todas as
   páginas da grelha (`collectors/citius_200_acoes.py`);
2. **guarda um instantâneo** em JSON, por data de recolha, em
   `data/grandes-litigantes/`, com o manifesto das recolhas;
3. **indexa** um documento por **sociedade e ano** em
   `finance_grandes_litigantes` (o histórico das recolhas vai para
   `finance_grandes_litigantes_recolhas`);
4. serve a **pesquisa** (texto, NIPC, ano e faixa), os **KPIs**, a **ficha por
   NIPC** (todos os anos em que a sociedade entrou na lista) e a **exportação
   CSV**.

O portal publica apenas a **faixa** de processos — «Entre 201 e 500» ou «501 ou
superior» —, nunca o número exato; é essa a informação que fica indexada.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import os
import re
import threading
import time
import unicodedata
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)

MODULE = "grandes-litigantes"
FONTE = "citius_portaria_200_2011"
FONTE_LABEL = "Portal CITIUS — Lista de Sociedades com mais de 200 acções"
SOURCE_URL = "https://www.citius.mj.pt/portal/consultas/Custas/Portaria200-2011.aspx"

#: Faixas do artigo 13.º do RCP (o que o portal publica).
FAIXAS: Dict[str, str] = {"201-500": "Entre 201 e 500", "501+": "501 ou superior"}

DATA_DIR_ENV = "GRANDES_LITIGANTES_DIR"
_DEFAULT_DIR = Path(__file__).resolve().parents[1] / "data" / "grandes-litigantes"
_MANIFEST = "_manifest.json"
_RUNNING = "running"
_JOBS: Dict[str, Dict[str, Any]] = {}
_JOBS_LOCK = threading.Lock()
_JOBS_KEEP = 20


# ---------------------------------------------------------------------------
# Pastas, manifesto e utilidades
# ---------------------------------------------------------------------------

def data_dir() -> Path:
    """Pasta raiz dos instantâneos (criada se não existir)."""
    raw = (os.environ.get(DATA_DIR_ENV) or "").strip()
    path = Path(raw).expanduser() if raw else _DEFAULT_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def json_dir() -> Path:
    caminho = data_dir() / "json"
    caminho.mkdir(parents=True, exist_ok=True)
    return caminho


def _manifest_path() -> Path:
    return data_dir() / _MANIFEST


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _hoje() -> str:
    return date.today().isoformat()


def fold(value: Any) -> str:
    """Minúsculas sem acentos (ordenação e chave de pesquisa)."""
    normalizado = unicodedata.normalize("NFKD", str(value or "").strip().lower())
    return "".join(ch for ch in normalizado if not unicodedata.combining(ch))


def nipc_digitos(nipc: Any) -> str:
    """Só os dígitos do NIPC (as sucursais estrangeiras trazem letras: ``LU 31006073``)."""
    return re.sub(r"\D", "", str(nipc or ""))


def read_manifest() -> Dict[str, Any]:
    """Manifesto das recolhas (recolha → resumo)."""
    path = _manifest_path()
    if not path.exists():
        return {"generated_at": None, "recolhas": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - manifesto ilegível não pode travar o módulo
        logger.warning("Manifesto de grandes litigantes ilegível (%s): %s", path, exc)
        return {"generated_at": None, "recolhas": {}}
    if not isinstance(data, dict):
        return {"generated_at": None, "recolhas": {}}
    data.setdefault("recolhas", {})
    return data


def _write_manifest(manifest: Dict[str, Any]) -> None:
    manifest["generated_at"] = _now()
    path = _manifest_path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def registar_recolha(entrada: Dict[str, Any]) -> Dict[str, Any]:
    """Regista no manifesto uma recolha (por id)."""
    manifest = read_manifest()
    recolha_id = str(entrada.get("recolha_id") or "")
    if not recolha_id:
        recolha_id = f"{FONTE}:{entrada.get('collected_at') or _now()}"
    entrada = {**entrada, "recolha_id": recolha_id}
    manifest["recolhas"][recolha_id] = entrada
    _write_manifest(manifest)
    return entrada


def list_recolhas() -> Dict[str, Any]:
    """Recolhas registadas (mais recentes primeiro)."""
    manifest = read_manifest()
    entradas = list((manifest.get("recolhas") or {}).values())
    entradas.sort(key=lambda item: str(item.get("collected_at") or ""), reverse=True)
    return {
        "dir": str(data_dir()),
        "dir_env": DATA_DIR_ENV,
        "generated_at": manifest.get("generated_at"),
        "total": len(entradas),
        "registos": sum(int(item.get("registos") or 0) for item in entradas),
        "items": entradas,
    }


def _base_name(collected_at: str) -> str:
    return f"lista-{collected_at[:10]}"


# ---------------------------------------------------------------------------
# Recolha (scraper do CITIUS) e instantâneo em JSON
# ---------------------------------------------------------------------------

def recolher(
    *,
    termo: str = "",
    tipo: str = "nipc",
    max_paginas: int = 200,
    progresso: Optional[Dict[str, Any]] = None,
    run_id: Optional[str] = None,
    cliente: Any = None,
) -> Dict[str, Any]:
    """Percorre a lista no CITIUS, grava o instantâneo em JSON e registra a recolha."""
    from collectors.citius_200_acoes import Portaria200Client

    inicio = time.monotonic()
    progresso = progresso if progresso is not None else {}

    def _on_page(pagina: int, total_lido: int, total_portal: Optional[int]) -> None:
        progresso["phase"] = "a ler a lista do CITIUS"
        progresso["pagina"] = pagina
        progresso["registos"] = total_lido
        progresso["total_portal"] = total_portal
        progresso["paginas"] = max(int(progresso.get("paginas") or 0), pagina)

    cliente = cliente or Portaria200Client()
    if hasattr(cliente, "__enter__") and hasattr(cliente, "__exit__"):
        with cliente as c:
            lista = c.recolher(termo=termo, tipo=tipo, max_paginas=max_paginas, on_page=_on_page)
    else:
        lista = cliente.recolher(termo=termo, tipo=tipo, max_paginas=max_paginas, on_page=_on_page)

    collected_at = _now()
    registos = [
        {
            "nipc": r.get("nipc"),
            "nipc_digitos": nipc_digitos(r.get("nipc")),
            "denominacao": r.get("denominacao"),
            "denominacao_fold": fold(r.get("denominacao")),
            "ano": r.get("ano"),
            "acoes_texto": r.get("acoes_texto"),
            "acoes_min": r.get("acoes_min"),
            "faixa": r.get("faixa"),
            "faixa_label": r.get("faixa_label"),
            "pagina": r.get("pagina"),
        }
        for r in lista.get("registos") or []
    ]
    registos.sort(key=lambda r: (str(r.get("denominacao_fold") or ""), str(r.get("nipc") or "")))

    base = _base_name(collected_at)
    recolha_id = f"{FONTE}:{collected_at[:10]}"
    payload = {
        "fonte": FONTE,
        "fonte_label": FONTE_LABEL,
        "source_url": SOURCE_URL,
        "base": base,
        "recolha_id": recolha_id,
        "collected_at": collected_at,
        "termo": termo or None,
        "tipo": tipo,
        "total_portal": lista.get("total_portal"),
        "paginas": lista.get("paginas"),
        "anos": lista.get("anos") or [],
        "total": len(registos),
        "duracao_ms": int((time.monotonic() - inicio) * 1000),
        **({"run_id": run_id} if run_id else {}),
        "registos": registos,
    }

    caminho = json_dir() / f"{base}.json"
    caminho.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    registar_recolha(
        {
            "recolha_id": recolha_id,
            "fonte": FONTE,
            "source_url": SOURCE_URL,
            "anos": payload["anos"],
            "ano_principal": max(payload["anos"]) if payload["anos"] else None,
            "total_portal": payload["total_portal"],
            "registos": payload["total"],
            "paginas": payload["paginas"],
            "duracao_ms": payload["duracao_ms"],
            "collected_at": collected_at,
            "json_path": str(caminho),
            "run_id": run_id,
        }
    )
    return payload


def read_export(base: str) -> Dict[str, Any]:
    """Lê um instantâneo guardado (por nome base, sem extensão)."""
    nome = re.sub(r"[^A-Za-z0-9._-]+", "-", str(base or "")).strip("-")
    caminho = json_dir() / f"{nome}.json"
    if not caminho.exists():
        raise FileNotFoundError(f"Instantâneo não encontrado: {base}")
    return json.loads(caminho.read_text(encoding="utf-8"))


def list_snapshots() -> Dict[str, Any]:
    """Instantâneos presentes no disco (mais recentes primeiro)."""
    itens: List[Dict[str, Any]] = []
    for caminho in sorted(json_dir().glob("*.json"), key=lambda p: p.name, reverse=True):
        itens.append(
            {
                "base": caminho.stem,
                "bytes": caminho.stat().st_size,
                "modificado_em": datetime.fromtimestamp(caminho.stat().st_mtime, tz=timezone.utc)
                .replace(microsecond=0)
                .isoformat()
                .replace("+00:00", "Z"),
                "path": str(caminho),
            }
        )
    return {"dir": str(json_dir()), "total": len(itens), "items": itens}


# ---------------------------------------------------------------------------
# Indexação
# ---------------------------------------------------------------------------

def _doc_id(ano: Any, nipc: Any) -> str:
    return f"{ano}:{nipc}"


def _preparar(registo: Dict[str, Any], payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Documento a indexar (um por sociedade e ano)."""
    nipc = str(registo.get("nipc") or "").strip()
    if not nipc:
        return None
    ano = registo.get("ano")
    ano_num = int(ano) if str(ano or "").strip().isdigit() else None
    faixa = str(registo.get("faixa") or "201-500")
    return {
        "doc_id": _doc_id(ano_num, nipc),
        "nipc": nipc,
        "nipc_digitos": nipc_digitos(nipc),
        "denominacao": registo.get("denominacao"),
        "denominacao_fold": registo.get("denominacao_fold") or fold(registo.get("denominacao")),
        "ano": ano_num,
        "acoes_texto": registo.get("acoes_texto"),
        "acoes_min": registo.get("acoes_min"),
        "faixa": faixa,
        "faixa_label": registo.get("faixa_label") or FAIXAS.get(faixa),
        "fonte": payload.get("fonte") or FONTE,
        "fonte_label": payload.get("fonte_label") or FONTE_LABEL,
        "source_url": payload.get("source_url") or SOURCE_URL,
        "collected_at": payload.get("collected_at"),
        "recolha_id": payload.get("recolha_id"),
        "ingested_at": _now(),
    }


def indexar(payload: Dict[str, Any], *, es: Any = None) -> Dict[str, Any]:
    """Indexa um instantâneo em `finance_grandes_litigantes`."""
    from api import elasticsearch_client as esc

    cliente = es or esc.get_es_client()
    if not cliente:
        return {"error": "Elasticsearch indisponível", "indexados": 0}
    esc.ensure_indices(cliente)

    acoes: List[Dict[str, Any]] = []
    vistos: set = set()
    for registo in payload.get("registos") or []:
        documento = _preparar(registo, payload)
        if not documento or documento["doc_id"] in vistos:
            continue
        vistos.add(documento["doc_id"])
        acoes.append({"_index": esc.GRANDES_LITIGANTES_INDEX, "_id": documento["doc_id"], "_source": documento})

    if not acoes:
        return {"indexados": 0, "index": esc.GRANDES_LITIGANTES_INDEX}

    from elasticsearch.helpers import bulk

    try:
        indexados, erros = bulk(cliente, acoes, raise_on_error=False)
        cliente.indices.refresh(index=esc.GRANDES_LITIGANTES_INDEX)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Indexação de grandes litigantes falhou")
        return {"error": str(exc), "indexados": 0, "index": esc.GRANDES_LITIGANTES_INDEX}

    recolha = payload.get("recolha_id") or f"{FONTE}:{payload.get('collected_at') or _now()}"
    anos = [int(a) for a in (payload.get("anos") or []) if str(a).isdigit()]
    try:
        cliente.index(
            index=esc.GRANDES_LITIGANTES_RECOLHAS_INDEX,
            id=recolha,
            document={
                "recolha_id": recolha,
                "fonte": payload.get("fonte") or FONTE,
                "source_url": payload.get("source_url") or SOURCE_URL,
                "anos": anos,
                "ano_principal": max(anos) if anos else None,
                "total_portal": payload.get("total_portal"),
                "registos": len(acoes),
                "paginas": payload.get("paginas"),
                "duracao_ms": payload.get("duracao_ms"),
                "collected_at": payload.get("collected_at"),
                "json_path": payload.get("json_path"),
                "run_id": payload.get("run_id"),
                "ingested_at": _now(),
            },
            refresh=True,
        )
    except Exception as exc:  # noqa: BLE001 - o histórico não pode invalidar a indexação
        logger.warning("Não foi possível registar a recolha em %s: %s", esc.GRANDES_LITIGANTES_RECOLHAS_INDEX, exc)

    return {
        "index": esc.GRANDES_LITIGANTES_INDEX,
        "recolhas_index": esc.GRANDES_LITIGANTES_RECOLHAS_INDEX,
        "indexados": indexados,
        "errors": len(erros) if erros else 0,
        "anos": anos,
    }


def indexar_ficheiros(bases: Optional[Iterable[str]] = None) -> Dict[str, Any]:
    """(Re)indexa os instantâneos guardados (todos ou os indicados)."""
    nomes = list(bases) if bases else [item["base"] for item in list_snapshots()["items"]]
    resultados: List[Dict[str, Any]] = []
    for nome in nomes:
        try:
            payload = read_export(nome)
        except FileNotFoundError as exc:
            resultados.append({"base": nome, "error": str(exc)})
            continue
        resultados.append({"base": nome, **indexar(payload)})
    return {
        "total": len(resultados),
        "indexados": sum(int(r.get("indexados") or 0) for r in resultados),
        "resultados": resultados,
    }


# ---------------------------------------------------------------------------
# Pesquisa
# ---------------------------------------------------------------------------

def _filtros(
    q: Optional[str],
    *,
    nipc: Optional[str],
    ano: Optional[int],
    anos: Optional[List[int]],
    faixa: Optional[List[str]],
) -> Dict[str, Any]:
    filtros: List[Dict[str, Any]] = []
    must: List[Dict[str, Any]] = []

    termo = (q or "").strip()
    if termo:
        digitos = re.sub(r"\D", "", termo)
        if digitos and len(digitos) >= 6 and re.fullmatch(r"[\d\s.\-/]+", termo):
            filtros.append({"term": {"nipc_digitos": digitos}})
        else:
            must.append(
                {
                    "multi_match": {
                        "query": termo,
                        "fields": ["denominacao^3", "denominacao.keyword"],
                        "type": "best_fields",
                        "operator": "and",
                    }
                }
            )
    if nipc:
        bruto = str(nipc).strip()
        digitos = nipc_digitos(bruto)
        if digitos:
            filtros.append({"term": {"nipc_digitos": digitos}})
        elif bruto:
            filtros.append({"term": {"nipc": bruto}})
    if ano:
        filtros.append({"term": {"ano": int(ano)}})
    if anos:
        filtros.append({"terms": {"ano": [int(a) for a in anos]}})
    if faixa:
        filtros.append({"terms": {"faixa": list(faixa)}})

    return {"bool": {"must": must or [{"match_all": {}}], "filter": filtros}}


def search(
    q: Optional[str] = None,
    *,
    nipc: Optional[str] = None,
    ano: Optional[int] = None,
    anos: Optional[List[int]] = None,
    faixa: Optional[List[str]] = None,
    sort: str = "relevancia",
    order: str = "asc",
    page: int = 1,
    size: int = 25,
    es: Any = None,
) -> Dict[str, Any]:
    """Pesquisa as sociedades da lista, com facetas por ano e por faixa."""
    from api import elasticsearch_client as esc

    cliente = es or esc.get_es_client()
    if not cliente:
        return {"error": "Elasticsearch indisponível", "total": 0, "items": [], "facets": {}, "kpis": {}}
    esc.ensure_indices(cliente)

    ordenacoes = {
        "relevancia": [{"_score": "desc"}, {"denominacao_fold": "asc"}],
        "nome": [{"denominacao_fold": order}, {"ano": "desc"}],
        "ano": [{"ano": order}, {"denominacao_fold": "asc"}],
        "faixa": [{"acoes_min": order}, {"denominacao_fold": "asc"}],
        "nipc": [{"nipc": order}],
    }
    corpo = {
        "query": _filtros(q, nipc=nipc, ano=ano, anos=anos, faixa=faixa),
        "from": max(0, (page - 1) * size),
        "size": size,
        "sort": ordenacoes.get(sort) or ordenacoes["relevancia"],
        "track_total_hits": True,
        "aggs": {
            "ano": {"terms": {"field": "ano", "size": 30, "order": {"_key": "desc"}}},
            "faixa": {"terms": {"field": "faixa", "size": 10, "order": {"min_acoes": "desc"}}, "aggs": {"min_acoes": {"min": {"field": "acoes_min"}}}},
            "sociedades": {"cardinality": {"field": "nipc_digitos"}},
        },
    }

    try:
        resposta = cliente.search(index=esc.GRANDES_LITIGANTES_INDEX, body=corpo)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Pesquisa de grandes litigantes falhou")
        return {"error": str(exc), "total": 0, "items": [], "facets": {}, "kpis": {}}

    agregacoes = resposta.get("aggregations") or {}

    def _buckets(nome: str) -> List[Dict[str, Any]]:
        return [
            {"key": bucket.get("key"), "count": bucket.get("doc_count")}
            for bucket in ((agregacoes.get(nome) or {}).get("buckets") or [])
        ]

    itens = [{**(hit.get("_source") or {}), "score": hit.get("_score")} for hit in resposta.get("hits", {}).get("hits", [])]
    total = (resposta.get("hits", {}).get("total") or {}).get("value", 0)
    por_faixa = {bucket["key"]: bucket["count"] for bucket in _buckets("faixa")}

    return {
        "total": total,
        "page": page,
        "size": size,
        "items": itens,
        "facets": {"ano": _buckets("ano"), "faixa": _buckets("faixa")},
        "kpis": {
            "registos": total,
            "sociedades_distintas": (agregacoes.get("sociedades") or {}).get("value", 0),
            "faixa_201_500": por_faixa.get("201-500", 0),
            "faixa_501": por_faixa.get("501+", 0),
            "anos": [bucket["key"] for bucket in _buckets("ano")],
            "ano_mais_recente": (_buckets("ano") or [{}])[0].get("key"),
        },
    }


def por_nipc(nipc: str, *, es: Any = None) -> Dict[str, Any]:
    """Ficha: todos os anos em que um NIPC entrou na lista."""
    limpo = str(nipc or "").strip()
    if not limpo:
        return {"nipc": "", "total": 0, "items": [], "lista": False}
    cliente = es
    if cliente is None:
        from api import elasticsearch_client as esc

        cliente = esc.get_es_client()
    if not cliente:
        return {"nipc": limpo, "total": 0, "items": [], "lista": False, "error": "Elasticsearch indisponível"}

    resposta = search(nipc=limpo, size=50, sort="ano", order="desc", es=cliente)
    itens = resposta.get("items") or []
    return {
        "nipc": limpo,
        "nipc_digitos": nipc_digitos(limpo),
        "denominacao": (itens[0].get("denominacao") if itens else None),
        "total": len(itens),
        "lista": bool(itens),
        "anos": sorted({int(i["ano"]) for i in itens if i.get("ano")}),
        "items": itens,
        "source_url": SOURCE_URL,
    }


def export_csv(**kwargs: Any) -> str:
    """CSV da pesquisa (mesmos filtros da API), com cabeçalho em português."""
    resultado = search(size=min(int(kwargs.pop("maximo", 5000) or 5000), 20000), page=1, **kwargs)
    buffer = io.StringIO()
    escritor = csv.writer(buffer, delimiter=";", lineterminator="\n")
    escritor.writerow(["NIPC", "Designação", "Ano", "Ações, procedimentos ou execuções", "Faixa", "Recolhido em", "Fonte"])
    for item in resultado.get("items") or []:
        escritor.writerow(
            [
                item.get("nipc") or "",
                item.get("denominacao") or "",
                item.get("ano") or "",
                item.get("acoes_texto") or "",
                item.get("faixa_label") or "",
                item.get("collected_at") or "",
                item.get("source_url") or SOURCE_URL,
            ]
        )
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Trabalhos em segundo plano
# ---------------------------------------------------------------------------

def _prune_jobs() -> None:
    if len(_JOBS) <= _JOBS_KEEP:
        return
    antigos = sorted(_JOBS.values(), key=lambda job: str(job.get("started_at") or ""))
    for job in antigos[: len(_JOBS) - _JOBS_KEEP]:
        if job.get("status") == _RUNNING:
            continue
        _JOBS.pop(str(job["job_id"]), None)


def start_job(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Arranca uma recolha (+ indexação) em segundo plano."""
    payload = dict(payload or {})
    with _JOBS_LOCK:
        a_correr = [job for job in _JOBS.values() if job.get("status") == _RUNNING]
        if a_correr:
            return {
                "job_id": a_correr[0]["job_id"],
                "status": _RUNNING,
                "already_running": True,
                "message": "Já existe uma recolha da lista a correr.",
            }
        job: Dict[str, Any] = {
            "job_id": uuid.uuid4().hex[:12],
            "status": _RUNNING,
            "started_at": _now(),
            "finished_at": None,
            "payload": payload,
            "progress": {"phase": "a começar", "pagina": 0, "registos": 0, "paginas": 0},
            "result": None,
            "error": None,
        }
        _JOBS[job["job_id"]] = job
        _prune_jobs()

    threading.Thread(target=_run_job, args=(job,), name="grandes-litigantes-recolha", daemon=True).start()
    return dict(job)


def _run_job(job: Dict[str, Any]) -> None:
    try:
        _run_job_inner(job)
    except Exception as exc:  # noqa: BLE001 - o trabalho nunca pode morrer em silêncio
        logger.exception("Recolha da lista de grandes litigantes falhou")
        job["status"] = "error"
        job["finished_at"] = _now()
        job["error"] = f"{type(exc).__name__}: {exc}"
        job["progress"]["phase"] = "erro"


def _run_job_inner(job: Dict[str, Any]) -> None:
    payload = job["payload"]
    progresso = job["progress"]
    lista = recolher(
        termo=str(payload.get("termo") or ""),
        tipo=str(payload.get("tipo") or "nipc"),
        max_paginas=int(payload.get("max_paginas") or 200),
        progresso=progresso,
        run_id=job["job_id"],
    )
    indice: Dict[str, Any] = {}
    if payload.get("indexar", True):
        progresso["phase"] = "a indexar no Elasticsearch"
        indice = indexar(lista)

    job["result"] = {"lista": {k: v for k, v in lista.items() if k != "registos"}, "indice": indice}
    job["status"] = "done"
    job["finished_at"] = _now()
    if indice.get("error"):
        job["status"] = "error"
        job["error"] = indice["error"]
    progresso["phase"] = "concluído" if job["status"] == "done" else "concluído com erro"
    progresso["registos"] = lista.get("total", 0)


def list_jobs() -> Dict[str, Any]:
    """Estado dos trabalhos (mais recentes primeiro)."""
    with _JOBS_LOCK:
        jobs = sorted(_JOBS.values(), key=lambda job: str(job.get("started_at") or ""), reverse=True)
        return {"total": len(jobs), "items": [dict(job) for job in jobs]}


def job_status(job_id: str) -> Optional[Dict[str, Any]]:
    """Estado de um trabalho."""
    with _JOBS_LOCK:
        job = _JOBS.get(str(job_id))
        return dict(job) if job else None


# ---------------------------------------------------------------------------
# Metadados
# ---------------------------------------------------------------------------

def meta() -> Dict[str, Any]:
    """Metadados do módulo: pasta, índices, volumetria e enquadramento legal."""
    from api import elasticsearch_client as esc

    recolhas = list_recolhas()
    resumo_indice: Dict[str, Any] = {}
    cliente = esc.get_es_client()
    if cliente:
        try:
            if cliente.indices.exists(index=esc.GRANDES_LITIGANTES_INDEX):
                contagem = cliente.count(index=esc.GRANDES_LITIGANTES_INDEX)
                resumo_indice = {
                    "index": esc.GRANDES_LITIGANTES_INDEX,
                    "registos": contagem.get("count", 0),
                    "recolhas_index": esc.GRANDES_LITIGANTES_RECOLHAS_INDEX,
                }
        except Exception as exc:  # noqa: BLE001
            resumo_indice = {"error": str(exc)}

    anos: List[int] = []
    for item in recolhas["items"]:
        anos.extend(int(a) for a in (item.get("anos") or []) if str(a).isdigit())
    return {
        "module": MODULE,
        "dir": str(data_dir()),
        "dir_env": DATA_DIR_ENV,
        "json_dir": str(json_dir()),
        "index": esc.GRANDES_LITIGANTES_INDEX,
        "recolhas_index": esc.GRANDES_LITIGANTES_RECOLHAS_INDEX,
        "indice": resumo_indice,
        "recolhas": recolhas["total"],
        "registos_recolhidos": recolhas["registos"],
        "anos": sorted(set(anos)),
        "ano_mais_recente": max(anos) if anos else None,
        "ultima_recolha": (recolhas["items"][0]["collected_at"] if recolhas["items"] else None),
        "fonte": {"id": FONTE, "label": FONTE_LABEL, "url": SOURCE_URL},
        "faixas": FAIXAS,
        "notes": (
            "Lista anual das sociedades comerciais que, no ano civil anterior, intentaram mais de 200 "
            "ações, procedimentos ou execuções (n.º 3 do artigo 13.º do RCP; Portaria n.º 200/2011, de 20 "
            "de maio). Serve para aplicar a taxa de justiça das tabelas I-C e II-B. A consulta é pública no "
            "Portal CITIUS e publica apenas a faixa de processos (entre 201 e 500, ou 501 e superior), "
            "nunca o número exato."
        ),
    }
