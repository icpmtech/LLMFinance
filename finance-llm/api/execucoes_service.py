"""Serviço do módulo «Lista Pública de Execuções» do CITIUS.

Liga o coletor (`collectors/citius_execucoes.py`) ao disco
(`data/execucoes/runs/`) e ao Elasticsearch (`finance_execucoes`), no mesmo
desenho dos restantes módulos.

1. **Recolha** — `collect()` pesquisa o portal do CITIUS e grava tudo em JSON
   (`data/execucoes/runs/<run_id>.json`) com um resumo ao lado
   (`<run_id>.meta.json`). Nada é indexado neste passo.
2. **Importação** — `ingest_run()` lê o JSON gravado e indexa no Elasticsearch
   (idempotente: o `_id` é o `pub_id`).
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from collectors.citius_execucoes import (
    DIAS_OPCOES,
    PAGE,
    RegistoExecucao,
    ExecucoesClient,
    ExecucoesError,
    letras_alfabeto,
)

logger = logging.getLogger(__name__)

# Raiz dos ficheiros de recolha (JSON), ao lado das outras fontes da solução.
ROOT = Path(__file__).resolve().parents[1]
RUNS_DIR = ROOT / "data" / "execucoes" / "runs"
RUNS_DIR.mkdir(parents=True, exist_ok=True)

INDEX_NAME = "finance_execucoes"
SOURCE = "citius_execucoes"
SOURCE_LABEL = "Lista Pública de Execuções"

#: Páginas entre gravações do progresso parcial.
DEFAULT_PARTIAL_PAGES = 50

#: Intervalo mínimo entre pedidos ao portal (segundos).
DEFAULT_MIN_INTERVAL = 1.5

#: Páginas máximas por letra do alfabeto por omissão.
DEFAULT_MAX_PAGES_PER_LETRA = 2000

# Cache das opções do formulário (alfabeto).
_OPTIONS_CACHE: Dict[str, Any] = {"at": 0.0, "data": None}
_OPTIONS_TTL = 3600.0


# --------------------------------------------------------------- metadados
def meta() -> Dict[str, Any]:
    """Metadados do módulo (para a UI e para clientes da API)."""
    return {
        "module": "execucoes",
        "source": SOURCE,
        "source_label": SOURCE_LABEL,
        "source_url": PAGE,
        "index": INDEX_NAME,
        "storage": str(RUNS_DIR),
        "page_size": 10,
        "captcha_required": False,
        "dias_opcoes": DIAS_OPCOES,
        "notas": (
            "Lista Pública de Execuções do CITIUS. Os registos não contêm "
            "documentos PDF: cada entrada é uma linha da tabela com o nome do "
            "executado, processo, tribunal, valor da execução e estado. A recolha "
            "completa itera por letra do alfabeto (A-Z)."
        ),
    }


def form_options(force: bool = False) -> Dict[str, Any]:
    """Opções do formulário (alfabeto)."""
    import time

    now = time.time()
    if not force and _OPTIONS_CACHE["data"] and now - _OPTIONS_CACHE["at"] < _OPTIONS_TTL:
        return _OPTIONS_CACHE["data"]

    try:
        with ExecucoesClient(min_interval=0.5) as client:
            client.fetch_form()
            data = {"alfabeto": client.alfabeto()}
    except Exception as exc:  # noqa: BLE001
        logger.warning("Não foi possível obter as opções do CITIUS execuções: %s", exc)
        return {"error": str(exc), "alfabeto": []}

    _OPTIONS_CACHE["at"] = now
    _OPTIONS_CACHE["data"] = data
    return data


# --------------------------------------------------------------- ficheiros
def run_path(run_id: str) -> Path:
    """Caminho do JSON de uma recolha."""
    safe = "".join(ch for ch in run_id if ch.isalnum() or ch in "-_")
    return RUNS_DIR / f"{safe}.json"


def run_meta_path(run_id: str) -> Path:
    """Caminho do resumo (``.meta.json``) de uma recolha."""
    safe = "".join(ch for ch in run_id if ch.isalnum() or ch in "-_")
    return RUNS_DIR / f"{safe}.meta.json"


def save_run(payload: Dict[str, Any], meta_info: Dict[str, Any]) -> Dict[str, str]:
    """Grava a recolha em JSON (itens) e o respetivo resumo (escrita atómica)."""
    run_id = payload["run_id"]
    path = run_path(run_id)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)

    meta_path = run_meta_path(run_id)
    tmp_meta = meta_path.with_suffix(".json.tmp")
    tmp_meta.write_text(json.dumps(meta_info, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    tmp_meta.replace(meta_path)
    return {"run_id": run_id, "path": str(path), "meta_path": str(meta_path)}


def load_run(run_id: str) -> Dict[str, Any]:
    """Lê o JSON de uma recolha (itens + critérios)."""
    path = run_path(run_id)
    if not path.exists():
        raise FileNotFoundError(f"Recolha «{run_id}» não encontrada em {RUNS_DIR}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_run_meta(run_id: str) -> Dict[str, Any]:
    """Lê o resumo de uma recolha."""
    meta_path = run_meta_path(run_id)
    if not meta_path.exists():
        return {}
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def list_runs(limit: int = 50) -> List[Dict[str, Any]]:
    """Recolhas gravadas (meta.json), da mais recente para a mais antiga."""
    metas: List[Dict[str, Any]] = []
    for path in sorted(RUNS_DIR.glob("*.meta.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            meta_info = json.loads(path.read_text(encoding="utf-8"))
            meta_info.setdefault("run_id", path.stem.replace(".meta", ""))
            meta_info.setdefault("file", str(run_path(meta_info["run_id"])))
            metas.append(meta_info)
        except Exception:  # noqa: BLE001
            continue
    return metas[:limit]


def delete_run(run_id: str, drop_index: bool = True) -> Dict[str, Any]:
    """Apaga ficheiros de uma recolha e, opcionalmente, os documentos do índice."""
    path = run_path(run_id)
    meta_path = run_meta_path(run_id)
    removed: List[str] = []
    for p in (path, meta_path):
        if p.exists():
            p.unlink()
            removed.append(p.name)
    resultado: Dict[str, Any] = {"run_id": run_id, "removed": removed}
    if drop_index:
        from api.elasticsearch_client import delete_execucoes_run

        resultado["index"] = delete_execucoes_run(run_id)
    return resultado


def latest_run_id() -> Optional[str]:
    """Identificador da recolha mais recente (ou ``None``)."""
    runs = list_runs(1)
    return runs[0].get("run_id") if runs else None


def _new_run_id(prefix: str, extra: Optional[str] = None) -> str:
    """Identificador da recolha: ``execucoes-<data>-<prefixo>-<aleatório>``."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    alvo = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in str(extra or prefix))[:30]
    return f"execucoes-{stamp}-{prefix}-{alvo}-{uuid.uuid4().hex[:4]}"


def _dictify(item: RegistoExecucao) -> Dict[str, Any]:
    """Converte um modelo em dicionário plano (válido para JSON)."""
    return item.to_dict()


def _payload(
    run_id: str,
    criteria: Dict[str, Any],
    items: List[Dict[str, Any]],
    partial: bool = False,
) -> Dict[str, Any]:
    return {
        "run_id": run_id,
        "source": SOURCE,
        "source_url": PAGE,
        "criteria": criteria,
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "partial": partial,
        "count": len(items),
        "items": items,
    }


def _meta(
    run_id: str,
    criteria: Dict[str, Any],
    collected: int,
    declared_total: int,
    pages: int,
    started: datetime,
    finished: datetime,
    errors: List[str],
    partial: bool = False,
    **extra: Any,
) -> Dict[str, Any]:
    return {
        "run_id": run_id,
        "source": SOURCE,
        "criteria": criteria,
        "collected": collected,
        "declared_total": declared_total,
        "pages": pages,
        "errors": errors,
        "partial": partial,
        "created_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "duration_s": round((finished - started).total_seconds(), 1),
        "index": INDEX_NAME,
        "indexed": 0,
        "file": str(run_path(run_id)),
        **extra,
    }


# --------------------------------------------------------------- recolha
def collect(
    *,
    nome: Optional[str] = None,
    documento: Optional[str] = None,
    tipo_documento: Optional[str] = None,
    numero_processo: Optional[str] = None,
    dias: Optional[str] = None,
    letras: Optional[List[str]] = None,
    max_pages_per_letra: int = DEFAULT_MAX_PAGES_PER_LETRA,
    max_items: Optional[int] = None,
    min_interval: float = DEFAULT_MIN_INTERVAL,
    proxy: Optional[str] = None,
    run_id: Optional[str] = None,
    partial_every: int = DEFAULT_PARTIAL_PAGES,
    on_progress: Optional[Callable[[Dict[str, Any]], None]] = None,
    stop: Optional[Callable[[], bool]] = None,
    persist: bool = True,
) -> Dict[str, Any]:
    """Recolhe registos da Lista Pública de Execuções e grava-os em JSON.

    Sem critérios, faz uma recolha completa por letra do alfabeto (A-Z). Quando
    são fornecidos critérios específicos (nome, processo, ...), usa a pesquisa
    simples. Os critérios e itens ficam em disco; a importação para o
    Elasticsearch faz-se depois com ``ingest_run``.
    """
    dias = dias or "todos"
    run_id = run_id or _new_run_id("full" if not any((nome, documento, numero_processo)) else "search", extra=dias)
    started = datetime.now(timezone.utc)

    criterios = {
        "nome": nome,
        "documento": documento,
        "tipo_documento": tipo_documento,
        "numero_processo": numero_processo,
        "dias": dias,
        "letras": letras,
        "max_pages_per_letra": max_pages_per_letra,
        "max_items": max_items,
    }

    itens: List[Dict[str, Any]] = []
    erros: List[str] = []
    seen: set[str] = set()

    def _add(records: List[RegistoExecucao]) -> int:
        added = 0
        for item in records:
            doc = _dictify(item)
            doc.setdefault("source", SOURCE)
            if doc["pub_id"] in seen:
                continue
            seen.add(doc["pub_id"])
            itens.append(doc)
            added += 1
        return added

    def _progress(stage: str, **campos: Any) -> None:
        if on_progress:
            on_progress({"stage": stage, "collected": len(itens), "errors": erros, **campos})

    def _guardar_parcial(motivo: str) -> None:
        if not persist or not itens:
            return
        agora = datetime.now(timezone.utc)
        payload = _payload(run_id, criterios, itens, partial=True)
        meta_info = _meta(
            run_id,
            criterios,
            len(itens),
            0,
            0,
            started,
            agora,
            erros,
            partial=True,
            motivo=motivo,
        )
        try:
            save_run(payload, meta_info)
            logger.info("Execuções %s: progresso parcial gravado (%s itens).", run_id, len(itens))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Não foi possível gravar o progresso parcial de %s: %s", run_id, exc)

    try:
        with ExecucoesClient(min_interval=min_interval, proxy=proxy) as client:
            if letras or not any((nome, documento, numero_processo)):
                alvos = letras or letras_alfabeto()
                total_declared = 0
                pages_done = 0
                letras_feitas = 0
                for letra in alvos:
                    if stop and stop():
                        break
                    try:
                        records, resumo = client.collect(
                            dias=dias,
                            max_pages=max_pages_per_letra,
                            max_items=max_items,
                            letras=[letra],
                            on_page=lambda page, novos, letra=letra: _progress(
                                "collecting",
                                letra=letra,
                                page=page.page,
                                pages=page.page,
                                declared_total=page.total,
                            ),
                            stop=stop,
                        )
                    except Exception as exc:  # noqa: BLE001
                        erros.append(f"letra {letra}: {exc}")
                        logger.warning("Execuções: falha na letra %s: %s", letra, exc)
                        continue
                    _add(records)
                    total_declared += resumo.get("total", 0)
                    pages_done += resumo.get("pages", 0)
                    letras_feitas += 1
                    if partial_every and len(itens) // partial_every > 0:
                        _guardar_parcial(f"letra {letra}")
                    if max_items and len(itens) >= max_items:
                        itens = itens[:max_items]
                        break
                finished = datetime.now(timezone.utc)
                payload = _payload(run_id, criterios, itens, partial=False)
                meta_info = _meta(
                    run_id,
                    criterios,
                    len(itens),
                    total_declared,
                    pages_done,
                    started,
                    finished,
                    erros,
                    partial=False,
                    letras=letras_feitas,
                )
            else:
                records, resumo = client.collect(
                    nome=nome,
                    documento=documento,
                    tipo_documento=tipo_documento,
                    numero_processo=numero_processo,
                    dias=dias,
                    max_pages=max_pages_per_letra,
                    max_items=max_items,
                    on_page=lambda page, novos: _progress(
                        "collecting",
                        page=page.page,
                        pages=page.page,
                        declared_total=page.total,
                    ),
                    stop=stop,
                )
                _add(records)
                finished = datetime.now(timezone.utc)
                payload = _payload(run_id, criterios, itens, partial=False)
                meta_info = _meta(
                    run_id,
                    criterios,
                    len(itens),
                    resumo.get("total", 0),
                    resumo.get("pages", 0),
                    started,
                    finished,
                    erros,
                    partial=False,
                )
    except Exception as exc:  # noqa: BLE001
        erros.append(str(exc))
        logger.exception("Recolha de execuções falhou (%s)", run_id)
        finished = datetime.now(timezone.utc)
        payload = _payload(run_id, criterios, itens, partial=False)
        meta_info = _meta(run_id, criterios, len(itens), 0, 0, started, finished, erros, partial=False)

    if persist:
        paths = save_run(payload, meta_info)
        meta_info["file"] = paths["path"]
        meta_info["meta_file"] = paths["meta_path"]

    _progress("collected", collected=len(itens), pages=meta_info.get("pages", 0))
    return {"run_id": run_id, "payload": payload, "meta": meta_info}


# --------------------------------------------------------------- importação
def ingest_run(
    run_id: Optional[str] = None,
    items: Optional[List[Dict[str, Any]]] = None,
    mark_meta: bool = True,
    update_existing: bool = False,
) -> Dict[str, Any]:
    """Importa para o Elasticsearch uma recolha gravada (ou a lista de itens dada).

    Sem ``run_id`` nem ``items``, importa a recolha mais recente em disco. Os
    documentos já existentes no índice são ignorados (``update_existing=True``
    força a reescrita).
    """
    from api.elasticsearch_client import index_execucoes_items, search_execucoes

    if items is None:
        run_id = run_id or latest_run_id()
        if not run_id:
            raise FileNotFoundError("Não há recolhas em data/execucoes/runs para importar.")
        payload = load_run(run_id)
        items = payload.get("items", [])
        run_id = payload.get("run_id", run_id)

    if not items:
        return {"run_id": run_id, "indexed_count": 0, "total": 0, "error": "A recolha não tem itens."}

    result = index_execucoes_items(items, run_id=run_id, skip_existing=not update_existing)
    result["run_id"] = run_id
    result["total"] = len(items)

    if mark_meta and run_id:
        meta_info = load_run_meta(run_id)
        if meta_info:
            meta_info["indexed"] = result.get("indexed_count", 0)
            meta_info["skipped_existing"] = result.get("skipped_existing", 0)
            meta_info["indexed_at"] = datetime.now(timezone.utc).isoformat()
            run_meta_path(run_id).write_text(
                json.dumps(meta_info, ensure_ascii=False, indent=2), encoding="utf-8"
            )

    try:
        estado = search_execucoes(size=1)
        result["index_total"] = estado.get("total")
    except Exception:  # noqa: BLE001
        pass
    return result


# --------------------------------------------------------------- leitura
def search(**kwargs: Any) -> Dict[str, Any]:
    """Pesquisa execuções já indexadas."""
    from api.elasticsearch_client import search_execucoes as _search

    return _search(**kwargs)


def status() -> Dict[str, Any]:
    """Volumetria do índice de execuções."""
    from api.elasticsearch_client import execucoes_status

    return execucoes_status()


def get(pub_id: str) -> Dict[str, Any]:
    """Devolve um registo pelo ``pub_id``."""
    from api.elasticsearch_client import get_execucao

    return get_execucao(pub_id)


def runs_with_index_counts(limit: int = 50) -> List[Dict[str, Any]]:
    """Recolhas em disco, anotadas com o número de documentos no Elasticsearch."""
    from api.elasticsearch_client import execucoes_runs_summary

    metas = list_runs(limit)
    counts = execucoes_runs_summary([m["run_id"] for m in metas if m.get("run_id")])
    for meta_info in metas:
        meta_info["index_count"] = counts.get(meta_info.get("run_id"), 0)
    return metas
