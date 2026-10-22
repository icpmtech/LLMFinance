"""Serviço do módulo Massa Insolvente (art.º 152.º do CIRE).

Liga o coletor (`collectors/citius_massa.py`) ao disco (`data/massa_insolvente/`)
e ao Elasticsearch (`finance_massa_insolvente`), no mesmo desenho dos outros
módulos:

1. **Recolha** — `collect()` pesquisa o portal, percorre a lista de resultados e
   grava tudo em **JSON** (`data/massa_insolvente/runs/<run_id>.json`) com um
   resumo ao lado (`<run_id>.meta.json`).
2. **Importação** — `ingest_run()` lê o JSON gravado e indexa no Elasticsearch
   (idempotente: o `_id` é o `pub_id`).
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from collectors.citius_massa import (
    DIAS_OPCOES,
    MIN_REQUEST_INTERVAL,
    PAGE,
    PAGE_SIZE,
    MassaError,
    MassaInsolventeClient,
)

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
RUNS_DIR = ROOT / "data" / "massa_insolvente" / "runs"
RUNS_DIR.mkdir(parents=True, exist_ok=True)

MAX_WINDOW_DAYS = 366
DEFAULT_WINDOW_DAYS = 31

_OPTIONS_CACHE: Dict[str, Any] = {"at": 0.0, "data": None}
_OPTIONS_TTL = 3600.0


# --------------------------------------------------------------- metadados
def meta() -> Dict[str, Any]:
    """Metadados do módulo (para a UI e para clientes da API)."""
    return {
        "module": "massa_insolvente",
        "source": "citius.mj.pt",
        "source_label": "Publicidade da Composição da Massa Insolvente (art.º 152.º do CIRE)",
        "source_url": PAGE,
        "index": "finance_massa_insolvente",
        "storage": str(RUNS_DIR),
        "page_size": PAGE_SIZE,
        "captcha_required": False,
        "max_window_days": MAX_WINDOW_DAYS,
        "default_window_days": DEFAULT_WINDOW_DAYS,
        "min_request_interval": MIN_REQUEST_INTERVAL,
        "dias": [{"value": k, "label": v} for k, v in DIAS_OPCOES.items()],
        "notes": (
            "Anúncios publicados pelo Administrador Judicial nos termos do art.º 152.º do CIRE. "
            "Cada página traz 10 documentos; a recolha avança página a página (1 pedido por página). "
            "Os ficheiros ficam em `data/massa_insolvente/runs/` (JSON) e só depois são importados "
            "para `finance_massa_insolvente`."
        ),
    }


def form_options(force: bool = False) -> Dict[str, Any]:
    """Opções do formulário do portal (tipos de ativo, localizações e áreas de negócio)."""
    import time

    now = time.time()
    if not force and _OPTIONS_CACHE["data"] and now - _OPTIONS_CACHE["at"] < _OPTIONS_TTL:
        return _OPTIONS_CACHE["data"]

    try:
        with MassaInsolventeClient(min_interval=0.5) as client:
            client.fetch_form()
            data = {
                "tipos_ativo": client.tipos_ativo(),
                "localizacoes": client.localizacoes(),
                "areas_negocio": client.areas_negocio(),
                "dias": [{"value": k, "label": v} for k, v in DIAS_OPCOES.items()],
            }
    except Exception as exc:  # noqa: BLE001
        logger.warning("Não foi possível obter as opções da massa insolvente: %s", exc)
        return {
            "error": str(exc),
            "tipos_ativo": [],
            "localizacoes": [],
            "areas_negocio": [],
            "dias": [{"value": k, "label": v} for k, v in DIAS_OPCOES.items()],
        }

    _OPTIONS_CACHE["at"] = now
    _OPTIONS_CACHE["data"] = data
    return data


# --------------------------------------------------------------- datas
def normalize_date(value: Optional[str]) -> Optional[str]:
    """Aceita ``AAAA-MM-DD`` e ``DD/MM/AAAA`` e devolve ISO 8601."""
    value = (value or "").strip()
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    return value


def _windows(desde: Optional[str], ate: Optional[str], window_days: Optional[int]) -> List[Tuple[Optional[str], Optional[str]]]:
    """Divide o intervalo em janelas de ``window_days`` dias (mais recente primeiro)."""
    if not desde or not ate or not window_days or window_days <= 0:
        return [(desde, ate)]
    try:
        start = date.fromisoformat(normalize_date(desde) or "")
        end = date.fromisoformat(normalize_date(ate) or "")
    except ValueError:
        return [(desde, ate)]
    if end < start:
        return [(desde, ate)]
    janelas: List[Tuple[Optional[str], Optional[str]]] = []
    cursor = end
    while cursor >= start:
        ini = max(start, cursor - timedelta(days=window_days - 1))
        janelas.append((ini.isoformat(), cursor.isoformat()))
        cursor = ini - timedelta(days=1)
    return janelas


# --------------------------------------------------------------- ficheiros
def run_path(run_id: str) -> Path:
    safe = "".join(ch for ch in run_id if ch.isalnum() or ch in "-_")
    return RUNS_DIR / f"{safe}.json"


def run_meta_path(run_id: str) -> Path:
    safe = "".join(ch for ch in run_id if ch.isalnum() or ch in "-_")
    return RUNS_DIR / f"{safe}.meta.json"


def save_run(payload: Dict[str, Any], meta_info: Dict[str, Any]) -> Dict[str, str]:
    run_id = payload["run_id"]
    path = run_path(run_id)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)

    meta_path = run_meta_path(run_id)
    tmp_meta = meta_path.with_suffix(".json.tmp")
    tmp_meta.write_text(json.dumps(meta_info, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_meta.replace(meta_path)
    return {"run_id": run_id, "path": str(path), "meta_path": str(meta_path)}


def load_run(run_id: str) -> Dict[str, Any]:
    path = run_path(run_id)
    if not path.exists():
        raise FileNotFoundError(f"Recolha «{run_id}» não encontrada em {RUNS_DIR}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_run_meta(run_id: str) -> Dict[str, Any]:
    meta_path = run_meta_path(run_id)
    if not meta_path.exists():
        return {}
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def list_runs(limit: int = 50) -> List[Dict[str, Any]]:
    metas: List[Dict[str, Any]] = []
    for meta_path in RUNS_DIR.glob("*.meta.json"):
        try:
            payload = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        payload.setdefault("run_id", meta_path.name.removesuffix(".meta.json"))
        metas.append(payload)
    metas.sort(key=lambda m: m.get("created_at") or "", reverse=True)
    return metas[: max(1, limit)]


def delete_run(run_id: str) -> Dict[str, Any]:
    removed: List[str] = []
    for path in (run_path(run_id), run_meta_path(run_id)):
        if path.exists():
            path.unlink()
            removed.append(path.name)
    return {"run_id": run_id, "removed": removed}


def latest_run_id() -> Optional[str]:
    runs = list_runs(1)
    return runs[0].get("run_id") if runs else None


def processed_windows(limit: int = 500) -> List[Dict[str, Any]]:
    janelas: List[Dict[str, Any]] = []
    vistos: set[tuple] = set()
    for meta_info in list_runs(limit):
        run_id = meta_info.get("run_id")
        if meta_info.get("errors") and not meta_info.get("collected"):
            continue
        for janela in meta_info.get("windows") or []:
            desde, ate = janela.get("desde"), janela.get("ate")
            if not desde or not ate or janela.get("error"):
                continue
            chave = (desde, ate)
            if chave in vistos:
                continue
            vistos.add(chave)
            janelas.append(
                {
                    "desde": desde,
                    "ate": ate,
                    "run_id": run_id,
                    "collected": janela.get("collected") or 0,
                    "total": janela.get("total") or 0,
                    "finished_at": meta_info.get("finished_at") or meta_info.get("created_at"),
                }
            )
    janelas.sort(key=lambda item: (item.get("ate") or "", item.get("desde") or ""), reverse=True)
    return janelas


def coverage() -> Dict[str, Any]:
    janelas = processed_windows()
    return {
        "windows": janelas,
        "total": len(janelas),
        "days": sorted({j["ate"] for j in janelas if j.get("ate")}, reverse=True),
    }


# --------------------------------------------------------------- recolha
def collect(
    *,
    desde: Optional[str] = None,
    ate: Optional[str] = None,
    dias: Optional[str] = None,
    tipo_ativo: Optional[str] = None,
    localizacao: Optional[str] = None,
    area_negocio: Optional[str] = None,
    max_pages: int = 20,
    max_items: Optional[int] = None,
    window_days: Optional[int] = DEFAULT_WINDOW_DAYS,
    min_interval: float = MIN_REQUEST_INTERVAL,
    proxy: Optional[str] = None,
    run_id: Optional[str] = None,
    force: bool = False,
    split_runs: bool = False,
    ingest_each: bool = False,
    on_progress: Optional[Callable[[Dict[str, Any]], None]] = None,
    stop: Optional[Callable[[], bool]] = None,
    persist: bool = True,
) -> Dict[str, Any]:
    """Recolhe anúncios da massa insolvente e grava-os em JSON."""
    desde = normalize_date(desde)
    ate = normalize_date(ate)
    if bool(desde) != bool(ate):
        raise ValueError("Indique as duas datas (início e fim) ou nenhuma.")
    if desde and ate and date.fromisoformat(ate) < date.fromisoformat(desde):
        raise ValueError("A data final não pode ser anterior à inicial.")
    if dias and dias not in DIAS_OPCOES:
        raise ValueError("Atalho de dias inválido (use 15).")

    run_id = run_id or _new_run_id(desde, ate, tipo_ativo, localizacao, area_negocio)
    janelas = _windows(desde, ate, window_days if desde and ate else None)
    started = datetime.now(timezone.utc)

    processadas = {(janela["desde"], janela["ate"]): janela for janela in processed_windows()}
    warnings: List[str] = []
    ignoradas: List[Dict[str, Any]] = []
    if not force and processadas:
        for janela in list(janelas):
            anterior = processadas.get((janela[0], janela[1]))
            if not anterior:
                continue
            janelas.remove(janela)
            ignoradas.append({**anterior, "motivo": "já processada"})
            warnings.append(
                f"Janela {janela[0]} → {janela[1]} já foi processada "
                f"({anterior.get('collected', 0)} documentos em {anterior.get('run_id')}) — ignorada."
            )

    criterios = {
        "desde": desde,
        "ate": ate,
        "dias": dias,
        "tipo_ativo": tipo_ativo,
        "localizacao": localizacao,
        "area_negocio": area_negocio,
        "max_pages": max_pages,
        "max_items": max_items,
        "window_days": window_days,
        "force": force,
    }

    items: List[Dict[str, Any]] = []
    seen: set[str] = set()
    janelas_info: List[Dict[str, Any]] = []
    total_declarado = 0
    paginas = 0
    erros: List[str] = []
    parado = False
    recolhas: List[str] = []
    indexados = 0
    ignorados_index = 0
    progresso: Dict[str, Any] = {"collected": 0, "pages": 0}

    with MassaInsolventeClient(min_interval=min_interval, proxy=proxy) as client:
        for janela_desde, janela_ate in janelas:
            if stop and stop():
                parado = True
                break
            try:
                recolhidos, resumo = client.collect(
                    desde=janela_desde,
                    ate=janela_ate,
                    dias=dias if not (janela_desde and janela_ate) else None,
                    tipo_ativo=tipo_ativo,
                    localizacao=localizacao,
                    area_negocio=area_negocio,
                    max_pages=max_pages,
                    max_items=max_items,
                    stop=stop,
                    on_page=lambda page, new, _d=janela_desde, _a=janela_ate: _report_page(
                        on_progress, progresso, page, new, _d, _a
                    ),
                )
                total_declarado += resumo.get("total", 0)
                paginas += resumo.get("pages", 0)
                novos: List[Dict[str, Any]] = []
                for pub in recolhidos:
                    doc = pub.to_dict()
                    if doc["pub_id"] in seen:
                        continue
                    seen.add(doc["pub_id"])
                    novos.append(doc)
                    items.append(doc)

                if split_runs:
                    child_id = _window_run_id(run_id, janela_desde, janela_ate)
                    child_payload = {
                        "run_id": child_id,
                        "source": "citius_massa_insolvente",
                        "source_url": PAGE,
                        "criteria": {**criterios, "desde": janela_desde, "ate": janela_ate},
                        "collected_at": datetime.now(timezone.utc).isoformat(),
                        "count": len(novos),
                        "items": novos,
                    }
                    child_meta = {
                        "run_id": child_id,
                        "source": "citius_massa_insolvente",
                        "criteria": {**criterios, "desde": janela_desde, "ate": janela_ate},
                        "windows": [{"desde": janela_desde, "ate": janela_ate, "collected": len(novos), "total": resumo.get("total", 0), "pages": resumo.get("pages", 0)}],
                        "collected": len(novos),
                        "declared_total": resumo.get("total", 0),
                        "pages": resumo.get("pages", 0),
                        "created_at": datetime.now(timezone.utc).isoformat(),
                        "index": "finance_massa_insolvente",
                        "indexed": 0,
                    }
                    if persist:
                        save_run(child_payload, child_meta)
                    recolhas.append(child_id)
                    if ingest_each:
                        ing = _ingest_items(novos, run_id=child_id)
                        indexados += ing.get("indexed_count", 0)
                        ignorados_index += ing.get("skipped_existing", 0)
                        child_meta["indexed"] = ing.get("indexed_count", 0)
                        child_meta["skipped_existing"] = ing.get("skipped_existing", 0)
                        if persist:
                            save_run(child_payload, child_meta)

                janelas_info.append(
                    {
                        "desde": janela_desde,
                        "ate": janela_ate,
                        "collected": len(novos),
                        "total": resumo.get("total", 0),
                        "pages": resumo.get("pages", 0),
                    }
                )
            except (MassaError, ValueError) as exc:
                logger.warning("Janela %s–%s falhou: %s", janela_desde, janela_ate, exc)
                erros.append(f"{janela_desde}–{janela_ate}: {exc}")
                janelas_info.append({"desde": janela_desde, "ate": janela_ate, "error": str(exc)})

            if max_items and len(items) >= max_items:
                items = items[:max_items]
                break

    finished = datetime.now(timezone.utc)
    payload = {
        "run_id": run_id,
        "source": "citius_massa_insolvente",
        "source_url": PAGE,
        "criteria": criterios,
        "collected_at": finished.isoformat(),
        "count": len(items),
        "items": items,
    }
    meta_info = {
        "run_id": run_id,
        "source": "citius_massa_insolvente",
        "criteria": criterios,
        "windows": janelas_info,
        "collected": len(items) if not split_runs else sum(w.get("collected") or 0 for w in janelas_info),
        "declared_total": total_declarado,
        "pages": paginas,
        "page_size": PAGE_SIZE,
        "errors": erros,
        "warnings": warnings,
        "skipped_windows": ignoradas,
        "stopped": parado,
        "created_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "duration_s": round((finished - started).total_seconds(), 1),
        "index": "finance_massa_insolvente",
        "indexed": indexados,
        "skipped_existing": ignorados_index,
        "split_runs": split_runs,
        "runs": recolhas,
        "file": str(run_path(run_id)),
    }
    if persist:
        if split_runs or not items:
            save_run_meta(meta_info)
            meta_info["meta_file"] = str(run_meta_path(run_id))
        else:
            paths = save_run(payload, meta_info)
            meta_info["file"] = paths["path"]
            meta_info["meta_file"] = paths["meta_path"]

    if on_progress:
        on_progress(
            {
                "stage": "collected",
                "collected": meta_info["collected"],
                "pages": paginas,
                "runs": len(recolhas),
                "indexed": indexados,
                "warnings": warnings,
                "skipped_windows": len(ignoradas),
            }
        )

    return {"run_id": run_id, "payload": payload, "meta": meta_info}


def _window_run_id(parent: str, desde: Optional[str], ate: Optional[str]) -> str:
    sufixo = f"{desde or 'inicio'}_{ate or 'fim'}"
    sufixo = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in sufixo)
    return f"{parent}-{sufixo}"


def save_run_meta(meta_info: Dict[str, Any]) -> str:
    meta_path = run_meta_path(str(meta_info["run_id"]))
    tmp = meta_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(meta_info, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(meta_path)
    return str(meta_path)


def _new_run_id(
    desde: Optional[str],
    ate: Optional[str],
    tipo_ativo: Optional[str],
    localizacao: Optional[str],
    area_negocio: Optional[str],
) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    parts = [p for p in (tipo_ativo, localizacao, area_negocio) if p]
    alvo = "_".join(parts) if parts else (f"{desde}_{ate}" if desde else "todos")
    alvo = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in str(alvo))
    return f"massa-{stamp}-{alvo}-{uuid.uuid4().hex[:4]}"


def _report_page(
    on_progress: Optional[Callable[[Dict[str, Any]], None]],
    progresso: Dict[str, Any],
    page: Any,
    new: Any,
    desde: Optional[str],
    ate: Optional[str],
) -> None:
    progresso["pages"] += 1
    progresso["collected"] += len(new)
    if not on_progress:
        return
    on_progress(
        {
            "stage": "collecting",
            "window": {"desde": desde, "ate": ate},
            "page": getattr(page, "page", None),
            "declared_total": getattr(page, "total", 0),
            "collected": progresso["collected"],
            "pages": progresso["pages"],
            "last_batch": len(new),
        }
    )


# --------------------------------------------------------------- importação
def _ingest_items(items: List[Dict[str, Any]], run_id: Optional[str] = None, update_existing: bool = False) -> Dict[str, Any]:
    from api.elasticsearch_client import index_massa_insolvente_items

    return index_massa_insolvente_items(items, run_id=run_id, skip_existing=not update_existing)


def ingest_run(
    run_id: Optional[str] = None,
    items: Optional[List[Dict[str, Any]]] = None,
    mark_meta: bool = True,
    update_existing: bool = False,
) -> Dict[str, Any]:
    """Importa para o Elasticsearch uma recolha gravada (ou itens avulsos)."""
    from api.elasticsearch_client import search_massa_insolvente

    payload: Dict[str, Any] = {}
    if items is None:
        run_id = run_id or latest_run_id()
        if not run_id:
            raise FileNotFoundError("Não há recolhas em data/massa_insolvente/runs para importar.")
        payload = load_run(run_id)
        items = payload.get("items", [])
        run_id = payload.get("run_id", run_id)

    if not items:
        return {"run_id": run_id, "indexed_count": 0, "total": 0, "error": "A recolha não tem itens."}

    result = _ingest_items(items, run_id=run_id, update_existing=update_existing)
    result["run_id"] = run_id
    result["total"] = len(items)

    if mark_meta and run_id:
        meta_info = load_run_meta(run_id)
        if meta_info:
            meta_info["indexed"] = result.get("indexed_count", 0)
            meta_info["skipped_existing"] = result.get("skipped_existing", 0)
            meta_info["indexed_at"] = datetime.now(timezone.utc).isoformat()
            run_meta_path(run_id).write_text(json.dumps(meta_info, ensure_ascii=False, indent=2), encoding="utf-8")

    try:
        estado = search_massa_insolvente(size=1)
        result["index_total"] = estado.get("total")
    except Exception:  # noqa: BLE001
        pass
    return result


# --------------------------------------------------------------- leitura
def search(**kwargs: Any) -> Dict[str, Any]:
    """Pesquisa anúncios indexados da massa insolvente."""
    from api.elasticsearch_client import search_massa_insolvente

    return search_massa_insolvente(**kwargs)


def status() -> Dict[str, Any]:
    """Volumetria do índice da massa insolvente."""
    from api.elasticsearch_client import massa_insolvente_status

    return massa_insolvente_status()


def runs_with_index_counts(limit: int = 50) -> List[Dict[str, Any]]:
    """Recolhas em disco, anotadas com o número de documentos no Elasticsearch."""
    from api.elasticsearch_client import massa_insolvente_runs_summary

    metas = list_runs(limit)
    counts = massa_insolvente_runs_summary([m["run_id"] for m in metas if m.get("run_id")])
    for meta_info in metas:
        meta_info["index_count"] = counts.get(meta_info.get("run_id"), 0)
    return metas
