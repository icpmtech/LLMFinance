"""Serviço do módulo «Venda de Bens Penhorados» (CITIUS + e-leilões).

Liga os coletores (`collectors/vendas_penhorados.py`) ao disco
(`data/vendas_penhorados/runs/`) e ao Elasticsearch
(`finance_vendas_penhorados`), no mesmo desenho dos restantes módulos.

1. **Recolha** — `collect()` pesquisa o portal do CITIUS e/ou a API do
   e-leiloes.pt e grava tudo em JSON (`data/vendas_penhorados/runs/<run_id>.json`)
   com um resumo ao lado (`<run_id>.meta.json`). Nada é indexado neste passo.
2. **Importação** — `ingest_run()` lê o JSON gravado e indexa no Elasticsearch
   (idempotente: o `_id` é o `venda_id`).
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from collectors.vendas_penhorados import (
    CITIUS_PAGE,
    ELEILOES_PAGE,
    CitiusVendasClient,
    EleiloesClient,
    VendaPenhorada,
    VendasError,
    default_window,
)

logger = logging.getLogger(__name__)

# Raiz dos ficheiros de recolha (JSON), ao lado das outras fontes da solução.
ROOT = Path(__file__).resolve().parents[1]
RUNS_DIR = ROOT / "data" / "vendas_penhorados" / "runs"
RUNS_DIR.mkdir(parents=True, exist_ok=True)

INDEX_NAME = "finance_vendas_penhorados"
SOURCE = "vendas_penhorados"
SOURCE_LABEL = "Venda de Bens Penhorados em Processos Executivos"

#: Datas de venda por omissão: janela que o CITIUS aceita (cerca de 1 mês atrás,
#: 2 meses à frente). O e-leiloes.pt não tem esta restrição.
DEFAULT_WINDOW_DIAS_ATRAS = 30
DEFAULT_WINDOW_DIAS_FRENTE = 62

#: Documentos detalhados por recolha por omissão (CITIUS pede um por bem).
DEFAULT_MAX_DETAILS = 400

#: Páginas entre gravações do progresso parcial.
DEFAULT_PARTIAL_PAGES = 50

#: Sessões em paralelo na recolha CITIUS por tribunal.
DEFAULT_WORKERS = 4
MAX_WORKERS = 8

# Cache das opções dos formulários (tribunais, tipos, modalidades, estados).
_OPTIONS_CACHE: Dict[str, Any] = {"at": 0.0, "data": None}
_OPTIONS_TTL = 3600.0


# --------------------------------------------------------------- metadados
def meta() -> Dict[str, Any]:
    """Metadados do módulo (para a UI e para clientes da API)."""
    inicio, fim = default_window(DEFAULT_WINDOW_DIAS_ATRAS, DEFAULT_WINDOW_DIAS_FRENTE)
    return {
        "module": "vendas_penhorados",
        "source": SOURCE,
        "source_label": SOURCE_LABEL,
        "source_url": CITIUS_PAGE,
        "index": INDEX_NAME,
        "storage": str(RUNS_DIR),
        "page_size": 10,
        "captcha_required": False,
        "default_window": {"desde": inicio, "ate": fim},
        "max_details": DEFAULT_MAX_DETAILS,
        "notas": (
            "Consulta pública do CITIUS «Venda de Bens Penhorados em Processos Executivos» e, "
            "opcionalmente, o sítio e-leiloes.pt dos agentes de execução. A pesquisa do CITIUS "
            "exige tribunal e intervalo de datas da venda (janela de cerca de três meses); o "
            "e-leiloes.pt devolve os eventos mais recentes primeiro. Os ficheiros ficam em "
            "`data/vendas_penhorados/runs/` e só depois são importados para "
            "`finance_vendas_penhorados`."
        ),
    }


def form_options(force: bool = False) -> Dict[str, Any]:
    """Opções dos formulários (CITIUS: tribunais/tipos/modalidades/estados)."""
    import time

    now = time.time()
    if not force and _OPTIONS_CACHE["data"] and now - _OPTIONS_CACHE["at"] < _OPTIONS_TTL:
        return _OPTIONS_CACHE["data"]

    try:
        with CitiusVendasClient(min_interval=0.5) as client:
            client.fetch_form()
            data = {
                "tribunais": client.tribunais(),
                "tipos_bem": client.tipos_bem(),
                "modalidades": client.modalidades(),
                "estados": client.estados(),
            }
    except Exception as exc:  # noqa: BLE001
        logger.warning("Não foi possível obter as opções do CITIUS vendas: %s", exc)
        return {"error": str(exc), "tribunais": [], "tipos_bem": [], "modalidades": [], "estados": []}

    _OPTIONS_CACHE["at"] = now
    _OPTIONS_CACHE["data"] = data
    return data


# --------------------------------------------------------------- datas
def default_date_window(
    dias_atras: int = DEFAULT_WINDOW_DIAS_ATRAS,
    dias_frente: int = DEFAULT_WINDOW_DIAS_FRENTE,
) -> Tuple[str, str]:
    """Janela de datas (ISO 8601) por omissão."""
    return default_window(dias_atras, dias_frente)


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


def save_run_meta(meta_info: Dict[str, Any]) -> str:
    """Grava apenas o resumo (``.meta.json``) de uma recolha."""
    meta_path = run_meta_path(str(meta_info["run_id"]))
    tmp = meta_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(meta_info, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    tmp.replace(meta_path)
    return str(meta_path)


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
        from api.elasticsearch_client import delete_vendas_penhorados_run

        resultado["index"] = delete_vendas_penhorados_run(run_id)
    return resultado


def latest_run_id() -> Optional[str]:
    """Identificador da recolha mais recente (ou ``None``)."""
    runs = list_runs(1)
    return runs[0].get("run_id") if runs else None


def _new_run_id(prefix: str, extra: Optional[str] = None) -> str:
    """Identificador da recolha: ``vendas-<data>-<prefixo>-<aleatório>``."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    alvo = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in str(extra or prefix))[:30]
    return f"vendas-{stamp}-{prefix}-{alvo}-{uuid.uuid4().hex[:4]}"


# --------------------------------------------------------------- recolha
def _dictify(item: VendaPenhorada) -> Dict[str, Any]:
    """Converte um modelo em dicionário plano (válido para JSON)."""
    doc = item.to_dict()
    # Manter `venda_id` como identificador único mesmo quando a referência muda.
    if not doc.get("venda_id"):
        doc["venda_id"] = item.pub_id
    return doc


def _payload(
    run_id: str,
    criteria: Dict[str, Any],
    items: List[Dict[str, Any]],
    source: str,
    partial: bool = False,
) -> Dict[str, Any]:
    return {
        "run_id": run_id,
        "source": source,
        "source_url": CITIUS_PAGE if source == "citius" else ELEILOES_PAGE,
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
    details: int,
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
        "details": details,
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


def collect(
    *,
    fontes: Optional[List[str]] = None,
    tribunais: Optional[List[str]] = None,
    desde: Optional[str] = None,
    ate: Optional[str] = None,
    tipo_bem: Optional[str] = None,
    modalidade: Optional[str] = None,
    estado: Optional[str] = None,
    max_pages_per_tribunal: int = 50,
    max_pages_eleiloes: int = 100,
    max_details: int = DEFAULT_MAX_DETAILS,
    max_items: Optional[int] = None,
    min_interval: float = 1.0,
    proxy: Optional[str] = None,
    run_id: Optional[str] = None,
    partial_every: int = DEFAULT_PARTIAL_PAGES,
    workers: int = 1,
    on_progress: Optional[Callable[[Dict[str, Any]], None]] = None,
    stop: Optional[Callable[[], bool]] = None,
    persist: bool = True,
) -> Dict[str, Any]:
    """Recolhe vendas de bens penhorados e grava-as em JSON.

    ``fontes`` pode conter ``citius``, ``eleiloes`` ou ambos. Sem ``tribunais``,
    a recolha CITIUS percorre todos os tribunais. O e-leiloes.pt não precisa de
    tribunal. Os critérios e itens ficam em disco; a importação para o
    Elasticsearch faz-se depois com ``ingest_run``.
    """
    fontes = fontes or ["citius", "eleiloes"]
    fontes = [f.lower().strip() for f in fontes]
    if not desde or not ate:
        desde, ate = default_window(DEFAULT_WINDOW_DIAS_ATRAS, DEFAULT_WINDOW_DIAS_FRENTE)

    run_id = run_id or _new_run_id("mix", extra="-".join(fontes))
    started = datetime.now(timezone.utc)

    criterios = {
        "fontes": fontes,
        "tribunais": tribunais,
        "desde": desde,
        "ate": ate,
        "tipo_bem": tipo_bem,
        "modalidade": modalidade,
        "estado": estado,
        "max_pages_per_tribunal": max_pages_per_tribunal,
        "max_pages_eleiloes": max_pages_eleiloes,
        "max_details": max_details,
        "max_items": max_items,
    }

    itens: List[Dict[str, Any]] = []
    erros: List[str] = []
    details_total = 0
    seen: set[str] = set()

    def _add(items: List[VendaPenhorada], source: str) -> int:
        """Adiciona itens ao lote global, evitando duplicados por venda_id."""
        added = 0
        for item in items:
            doc = _dictify(item)
            doc.setdefault("source", source)
            if doc["venda_id"] in seen:
                continue
            seen.add(doc["venda_id"])
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
        payload = _payload(run_id, criterios, itens, SOURCE, partial=True)
        meta_info = _meta(
            run_id,
            criterios,
            len(itens),
            0,
            0,
            details_total,
            started,
            agora,
            erros,
            partial=True,
            motivo=motivo,
        )
        try:
            save_run(payload, meta_info)
            logger.info("Vendas %s: progresso parcial gravado (%s itens).", run_id, len(itens))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Não foi possível gravar o progresso parcial de %s: %s", run_id, exc)

    # --- CITIUS ----------------------------------------------------------
    if "citius" in fontes:
        try:
            with CitiusVendasClient(min_interval=min_interval, proxy=proxy) as client:
                client.fetch_form()
                alvos = tribunais or [item["label"] for item in client.tribunais()]
                for tribunal in alvos:
                    if stop and stop():
                        break
                    try:
                        page = client.search(
                            tribunal=tribunal,
                            desde=desde,
                            ate=ate,
                            tipo_bem=tipo_bem,
                            modalidade=modalidade,
                            estado=estado,
                            fetch_options=False,
                        )
                    except Exception as exc:  # noqa: BLE001
                        erros.append(f"citius/{tribunal}: {exc}")
                        continue
                    paginas_tribunal = 0
                    while True:
                        novos = [item for item in page.items if item.venda_id not in seen]
                        if novos and details_total < max_details:
                            for item in novos:
                                if details_total >= max_details:
                                    break
                                try:
                                    client.enrich(item)
                                    details_total += 1
                                except Exception as exc:  # noqa: BLE001
                                    logger.debug("Detalhe CITIUS %s falhou: %s", item.venda_id, exc)
                        _add(novos, "citius")
                        paginas_tribunal += 1
                        _progress(
                            "collecting_citius",
                            tribunal=tribunal,
                            page=page.page,
                            pages=page.pages_total,
                            declared_total=page.total,
                        )
                        if max_items and len(itens) >= max_items:
                            itens = itens[:max_items]
                            break
                        if paginas_tribunal >= max_pages_per_tribunal:
                            break
                        if not page.has_next or not page.items:
                            break
                        try:
                            page = client.next_page()
                        except Exception as exc:  # noqa: BLE001
                            erros.append(f"citius/{tribunal} paginação: {exc}")
                            break
                    if partial_every and len(itens) // partial_every > 0:
                        _guardar_parcial("partial")
                    if max_items and len(itens) >= max_items:
                        break
        except Exception as exc:  # noqa: BLE001
            erros.append(f"citius: {exc}")

    # --- e-leiloes -------------------------------------------------------
    if "eleiloes" in fontes and (not max_items or len(itens) < max_items):
        try:
            with EleiloesClient(min_interval=min_interval, proxy=proxy) as client:
                restantes = max_items - len(itens) if max_items else None
                paginas = 0
                first = 0
                total = 0
                while paginas < max_pages_eleiloes:
                    if stop and stop():
                        break
                    try:
                        payload = client.list_events(first=first, filtros={})
                    except Exception as exc:  # noqa: BLE001
                        erros.append(f"eleiloes: {exc}")
                        break
                    total = int((payload.get("pagination") or {}).get("total") or 0)
                    novos: List[VendaPenhorada] = []
                    for bruto in payload.get("list") or []:
                        item = client._to_item(bruto)
                        if not item or item.venda_id in seen:
                            continue
                        try:
                            client.enrich(item)
                        except Exception as exc:  # noqa: BLE001
                            logger.debug("Detalhe e-leiloes %s falhou: %s", item.venda_id, exc)
                        novos.append(item)
                    _add(novos, "eleiloes")
                    paginas += 1
                    first += 12
                    _progress(
                        "collecting_eleiloes",
                        page=paginas,
                        declared_total=total,
                    )
                    if restantes is not None and len(itens) >= max_items:
                        itens = itens[:max_items]
                        break
                    if len(novos) == 0:
                        break
        except Exception as exc:  # noqa: BLE001
            erros.append(f"eleiloes: {exc}")

    finished = datetime.now(timezone.utc)
    payload = _payload(run_id, criterios, itens, SOURCE, partial=False)
    meta_info = _meta(
        run_id,
        criterios,
        len(itens),
        0,
        0,
        details_total,
        started,
        finished,
        erros,
        partial=False,
    )
    if persist:
        paths = save_run(payload, meta_info)
        meta_info["file"] = paths["path"]
        meta_info["meta_file"] = paths["meta_path"]

    _progress("collected", collected=len(itens), details=details_total, pages=0)
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
    from api.elasticsearch_client import index_vendas_penhorados_items, search_vendas_penhorados

    payload: Dict[str, Any] = {}
    if items is None:
        run_id = run_id or latest_run_id()
        if not run_id:
            raise FileNotFoundError("Não há recolhas em data/vendas_penhorados/runs para importar.")
        payload = load_run(run_id)
        items = payload.get("items", [])
        run_id = payload.get("run_id", run_id)

    if not items:
        return {"run_id": run_id, "indexed_count": 0, "total": 0, "error": "A recolha não tem itens."}

    result = index_vendas_penhorados_items(items, run_id=run_id, skip_existing=not update_existing)
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
        estado = search_vendas_penhorados(size=1)
        result["index_total"] = estado.get("total")
    except Exception:  # noqa: BLE001
        pass
    return result


# --------------------------------------------------------------- leitura
def search(**kwargs: Any) -> Dict[str, Any]:
    """Pesquisa vendas já indexadas."""
    from api.elasticsearch_client import search_vendas_penhorados as _search

    return _search(**kwargs)


def status() -> Dict[str, Any]:
    """Volumetria do índice de vendas penhoradas."""
    from api.elasticsearch_client import vendas_penhorados_status

    return vendas_penhorados_status()


def runs_with_index_counts(limit: int = 50) -> List[Dict[str, Any]]:
    """Recolhas em disco, anotadas com o número de documentos no Elasticsearch."""
    from api.elasticsearch_client import vendas_penhorados_runs_summary

    metas = list_runs(limit)
    counts = vendas_penhorados_runs_summary([m["run_id"] for m in metas if m.get("run_id")])
    for meta_info in metas:
        meta_info["index_count"] = counts.get(meta_info.get("run_id"), 0)
    return metas
