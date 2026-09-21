"""Persistência dos dashboards do Visualizador.

Um dashboard é a **definição** de uma análise: o dataset, os filtros, os visuais
(tipo de gráfico, dimensões, medidas, fórmulas) e a disposição no ecrã. Não
guarda dados: ao abrir, o Visualizador volta a consultar as fontes, pelo que um
dashboard reaberto mostra sempre os números atuais.

Os dashboards são privados de quem os criou (`owner_id`), tal como o CRM e o
Office. Vivem em `data/visualizador/dashboards.json`, com escrita atómica, para
poderem ser copiados/versionados como o resto dos dados da plataforma.
"""
from __future__ import annotations

import copy
import json
import logging
import re
import threading
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
STORE_DIR = ROOT / "data" / "visualizador"
STORE_PATH = STORE_DIR / "dashboards.json"
STORE_VERSION = 1

MAX_DASHBOARDS = 400
MAX_VISUALS = 40
MAX_DESCRIPTION = 2000

_lock = threading.Lock()
_cache: Optional[Dict[str, Any]] = None

DEFAULT_VISUAL = {
    "id": "visual",
    "title": "Novo visual",
    "chart": "bar",
    "dimension": None,
    "dimensions": [],
    "measure": "contagem",
    "measures": [],
    "formulas": [],
    "limit": 25,
    "top_n": 10,
    "others": False,
    "sort": {"by": "", "order": "desc"},
    "interval": None,
    "width": 6,
}


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug(value: str, fallback: str = "dashboard") -> str:
    text = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_").lower()
    return re.sub(r"_+", "_", text)[:64] or fallback


def _empty_store() -> Dict[str, Any]:
    return {"version": STORE_VERSION, "updated_at": _now(), "dashboards": []}


def _read_store() -> Dict[str, Any]:
    if not STORE_PATH.exists():
        return _empty_store()
    try:
        data = json.loads(STORE_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Ficheiro de dashboards ilegível (%s): %s", STORE_PATH, exc)
        return _empty_store()
    if not isinstance(data, dict) or not isinstance(data.get("dashboards"), list):
        return _empty_store()
    data.setdefault("version", STORE_VERSION)
    return data


def _write_store(store: Dict[str, Any]) -> None:
    STORE_DIR.mkdir(parents=True, exist_ok=True)
    store["version"] = STORE_VERSION
    store["updated_at"] = _now()
    tmp = STORE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STORE_PATH)


def _store() -> Dict[str, Any]:
    global _cache
    with _lock:
        if _cache is None:
            _cache = _read_store()
        return copy.deepcopy(_cache)


def clear_cache() -> None:
    global _cache
    with _lock:
        _cache = None


# ---------------------------------------------------------------------------
# Normalização
# ---------------------------------------------------------------------------
def _clean_visual(raw: Dict[str, Any], position: int) -> Dict[str, Any]:
    visual = {**DEFAULT_VISUAL, **(raw if isinstance(raw, dict) else {})}
    visual["id"] = str(visual.get("id") or f"v{position}")
    visual["title"] = str(visual.get("title") or f"Visual {position + 1}")[:120]
    visual["chart"] = str(visual.get("chart") or "bar")[:24]
    visual["dimensions"] = [entry for entry in (visual.get("dimensions") or []) if isinstance(entry, (dict, str))][:3]
    visual["measures"] = [entry for entry in (visual.get("measures") or []) if isinstance(entry, (dict, str))][:12]
    visual["formulas"] = [entry for entry in (visual.get("formulas") or []) if isinstance(entry, dict)][:12]
    visual["limit"] = max(1, min(int(visual.get("limit") or 25), 1000))
    visual["top_n"] = max(0, min(int(visual.get("top_n") or 0), 1000))
    visual["others"] = bool(visual.get("others"))
    visual["width"] = max(1, min(int(visual.get("width") or 6), 12))
    sort = visual.get("sort") if isinstance(visual.get("sort"), dict) else {}
    visual["sort"] = {"by": str(sort.get("by") or "")[:80], "order": "asc" if str(sort.get("order")) == "asc" else "desc"}
    if visual.get("dimension"):
        visual["dimension"] = str(visual["dimension"])[:80]
    if visual.get("measure"):
        visual["measure"] = str(visual["measure"])[:80]
    if visual.get("interval"):
        visual["interval"] = str(visual["interval"])[:16]
    return visual


def normalize_dashboard(payload: Dict[str, Any], *, owner_id: str, owner_email: Optional[str] = None,
                        existing: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ValueError("O dashboard precisa de um nome.")
    visuals = [_clean_visual(raw, position) for position, raw in enumerate((payload.get("visuals") or [])[:MAX_VISUALS])]
    filters = payload.get("filters") if isinstance(payload.get("filters"), dict) else {}
    dataset = payload.get("dataset")
    if not visuals and not dataset:
        raise ValueError("Escolha um dataset antes de guardar.")
    base = existing or {}
    return {
        "id": base.get("id") or _slug(payload.get("id") or name, "dashboard"),
        "name": name[:120],
        "description": str(payload.get("description") or "")[:MAX_DESCRIPTION],
        "owner_id": base.get("owner_id") or owner_id,
        "owner_email": base.get("owner_email") or owner_email,
        "dataset": (str(dataset)[:80] if dataset else base.get("dataset")),
        "filters": filters,
        "visuals": visuals,
        "layout": payload.get("layout") if isinstance(payload.get("layout"), dict) else {},
        "theme": str(payload.get("theme") or "iqos")[:24],
        "tags": [str(tag)[:40] for tag in (payload.get("tags") or [])][:12],
        "created_at": base.get("created_at") or _now(),
        "updated_at": _now(),
        "version": STORE_VERSION,
    }


def _summary(dashboard: Dict[str, Any], owner_id: Optional[str]) -> Dict[str, Any]:
    return {
        "id": dashboard.get("id"),
        "name": dashboard.get("name"),
        "description": dashboard.get("description"),
        "dataset": dashboard.get("dataset"),
        "tags": dashboard.get("tags") or [],
        "visuals": len(dashboard.get("visuals") or []),
        "owner_id": dashboard.get("owner_id"),
        "owner_email": dashboard.get("owner_email"),
        "mine": bool(owner_id) and dashboard.get("owner_id") == owner_id,
        "created_at": dashboard.get("created_at"),
        "updated_at": dashboard.get("updated_at"),
    }


# ---------------------------------------------------------------------------
# API do store
# ---------------------------------------------------------------------------
def list_dashboards(owner_id: Optional[str], *, see_all: bool = False) -> Dict[str, Any]:
    """Dashboards do utilizador (e, para administradores, os de toda a equipa)."""
    dashboards = _store()["dashboards"]
    if not see_all:
        dashboards = [item for item in dashboards if item.get("owner_id") == owner_id]
    items = [_summary(item, owner_id) for item in dashboards]
    items.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
    return {
        "total": len(items),
        "items": items[:MAX_DASHBOARDS],
        "shared": len([item for item in items if not item["mine"]]),
    }


def get_dashboard(dashboard_id: str, owner_id: Optional[str], *, see_all: bool = False) -> Dict[str, Any]:
    for item in _store()["dashboards"]:
        if item.get("id") == dashboard_id:
            if see_all or item.get("owner_id") == owner_id:
                return item
            raise PermissionError("Este dashboard pertence a outro utilizador.")
    raise KeyError(f"Dashboard {dashboard_id} não encontrado.")


def save_dashboard(payload: Dict[str, Any], owner_id: str, *, owner_email: Optional[str] = None) -> Dict[str, Any]:
    """Cria ou atualiza um dashboard do utilizador (por `id` ou por nome)."""
    with _lock:
        store = _read_store()
        wanted = str(payload.get("id") or "").strip()
        existing = None
        if wanted:
            existing = next((item for item in store["dashboards"] if item.get("id") == wanted), None)
            if existing and existing.get("owner_id") != owner_id:
                raise PermissionError("Este dashboard pertence a outro utilizador.")
        if not existing:
            slug = _slug(payload.get("name") or wanted or "dashboard", "dashboard")
            taken = {str(item.get("id")) for item in store["dashboards"]}
            if slug in taken:
                suffix = 2
                while f"{slug}_{suffix}" in taken:
                    suffix += 1
                slug = f"{slug}_{suffix}"
        else:
            slug = existing["id"]
        entry = normalize_dashboard({**payload, "id": slug}, owner_id=owner_id,
                                   owner_email=owner_email, existing=existing)
        entry["id"] = slug
        for index, item in enumerate(store["dashboards"]):
            if item.get("id") == slug:
                store["dashboards"][index] = entry
                break
        else:
            if len(store["dashboards"]) >= MAX_DASHBOARDS:
                raise ValueError(f"Limite de {MAX_DASHBOARDS} dashboards atingido.")
            store["dashboards"].append(entry)
        _write_store(store)
    clear_cache()
    return entry


def delete_dashboard(dashboard_id: str, owner_id: str) -> Dict[str, Any]:
    with _lock:
        store = _read_store()
        target = next((item for item in store["dashboards"] if item.get("id") == dashboard_id), None)
        if not target:
            return {"removed": False, "id": dashboard_id}
        if target.get("owner_id") != owner_id:
            raise PermissionError("Este dashboard pertence a outro utilizador.")
        store["dashboards"] = [item for item in store["dashboards"] if item.get("id") != dashboard_id]
        _write_store(store)
    clear_cache()
    return {"removed": True, "id": dashboard_id}


def duplicate_dashboard(dashboard_id: str, owner_id: str, *, owner_email: Optional[str] = None,
                        name: Optional[str] = None) -> Dict[str, Any]:
    source = get_dashboard(dashboard_id, owner_id, see_all=True)
    payload = {**source, "id": None, "name": name or f"{source.get('name')} (cópia)"}
    return save_dashboard(payload, owner_id, owner_email=owner_email)


def stats(owner_id: Optional[str], *, see_all: bool = False) -> Dict[str, Any]:
    dashboards = _store()["dashboards"] if see_all else [item for item in _store()["dashboards"] if item.get("owner_id") == owner_id]
    visuals = sum(len(item.get("visuals") or []) for item in dashboards)
    datasets: Dict[str, int] = {}
    for item in dashboards:
        key = str(item.get("dataset") or "—")
        datasets[key] = datasets.get(key, 0) + 1
    return {
        "dashboards": len(dashboards),
        "visuals": visuals,
        "datasets": sorted(
            [{"dataset": key, "dashboards": value} for key, value in datasets.items()],
            key=lambda item: -item["dashboards"],
        ),
        "storage": str(STORE_PATH),
    }


def export_payloads(dashboards: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Versão portátil (sem dono) para partilha/exportação de definições."""
    out = []
    for item in dashboards:
        payload = copy.deepcopy(item)
        payload.pop("owner_id", None)
        payload.pop("owner_email", None)
        out.append(payload)
    return out
