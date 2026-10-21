"""Serviço do módulo **EU Taxonomy Navigator**.

Oferece:
- recolha e normalização dos dados oficiais do Compass;
- tradução incremental para português (mantendo os originais em inglês);
- indexação no Elasticsearch (`finance_eu_taxonomy`);
- exportação do snapshot para `data/eu_taxonomy.json`;
- pesquisa com facetas por tipo, setor e objetivo ambiental.
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from api import eu_taxonomy_navigator as navigator
from api.elasticsearch_client import (
    EU_TAXONOMY_INDEX,
    get_es_client,
    index_eu_taxonomy,
    search_eu_taxonomy,
)

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_recolha_em_curso: Optional[Dict[str, Any]] = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def status() -> Dict[str, Any]:
    """Estado do módulo: existência do snapshot, contagens do Elasticsearch."""
    es = get_es_client()
    info: Dict[str, Any] = {"index": EU_TAXONOMY_INDEX, "snapshot_exists": navigator.SNAPSHOT_PATH.exists()}
    if es:
        try:
            info["es_available"] = True
            info["count"] = es.count(index=EU_TAXONOMY_INDEX).get("count", 0)
        except Exception as exc:
            info["es_available"] = False
            info["error"] = str(exc)
    else:
        info["es_available"] = False
    return info


def coletar(*, force: bool = False, translate: bool = True) -> Dict[str, Any]:
    """Recolhe, normaliza, traduz, indexa e exporta os dados do Compass."""
    global _recolha_em_curso
    with _lock:
        if _recolha_em_curso and not _recolha_em_curso.get("completed_at"):
            return {"error": "Já existe uma recolha em curso", "run": _recolha_em_curso}
        run_id = _now()
        _recolha_em_curso = {"run_id": run_id, "started_at": _now(), "completed_at": None, "error": None}

    try:
        snapshot = navigator.run(force=force, translate=translate)
        items = snapshot.get("activities", []) + snapshot.get("objectives", []) + snapshot.get("sectors", [])
        index_result = index_eu_taxonomy(items)

        with _lock:
            _recolha_em_curso.update(
                {
                    "completed_at": _now(),
                    "total_activities": snapshot.get("total_activities", 0),
                    "total_objectives": snapshot.get("total_objectives", 0),
                    "total_sectors": snapshot.get("total_sectors", 0),
                    "indexed_count": index_result.get("indexed_count", 0),
                    "index_error": index_result.get("error"),
                }
            )
        return {
            "run_id": run_id,
            "snapshot_path": str(navigator.SNAPSHOT_PATH),
            "source": snapshot.get("source"),
            "totals": {
                "activities": snapshot.get("total_activities"),
                "objectives": snapshot.get("total_objectives"),
                "sectors": snapshot.get("total_sectors"),
            },
            "index": index_result,
            "translated_names": sum(1 for a in snapshot.get("activities", []) if a.get("name_pt")),
            "translated_descriptions": sum(1 for a in snapshot.get("activities", []) if a.get("description_pt")),
        }
    except Exception as exc:
        logger.exception("EU Taxonomy: recolha falhou")
        with _lock:
            _recolha_em_curso.update({"completed_at": _now(), "error": str(exc)})
        return {"error": str(exc)}


def pesquisar(
    q: Optional[str] = None,
    kind: Optional[str] = None,
    sector: Optional[str] = None,
    objective_id: Optional[int] = None,
    nace: Optional[str] = None,
    size: int = 20,
    from_: int = 0,
    sort: str = "relevance",
) -> Dict[str, Any]:
    """Pesquisa no índice `finance_eu_taxonomy`."""
    return search_eu_taxonomy(
        q=q,
        kind=kind,
        sector=sector,
        objective_id=objective_id,
        nace=nace,
        size=size,
        from_=from_,
        sort=sort,
    )


def panorama() -> Dict[str, Any]:
    """Devolve a visão geral do Compass: objetivos, setores e contagens."""
    if not navigator.SNAPSHOT_PATH.exists():
        return {"error": "Snapshot ainda não existe. Execute a recolha primeiro.", "totals": {}}
    try:
        snapshot = json.loads(navigator.SNAPSHOT_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"error": str(exc), "totals": {}}

    setores: Dict[str, Dict[str, Any]] = {}
    for atividade in snapshot.get("activities", []):
        sector_en = atividade.get("sector_en") or "Outro"
        sector_pt = atividade.get("sector_pt") or sector_en
        if sector_en not in setores:
            setores[sector_en] = {"sector_en": sector_en, "sector_pt": sector_pt, "count": 0}
        setores[sector_en]["count"] += 1

    objetivos = []
    for obj in snapshot.get("objectives", []):
        objetivos.append(
            {
                "id": obj.get("objective_id"),
                "name_en": obj.get("name_en"),
                "name_pt": obj.get("name_pt"),
                "short_en": obj.get("short_en"),
                "short_pt": obj.get("short_pt"),
                "color": obj.get("color"),
            }
        )

    return {
        "source": snapshot.get("source"),
        "totals": {
            "activities": snapshot.get("total_activities"),
            "objectives": snapshot.get("total_objectives"),
            "sectors": snapshot.get("total_sectors"),
        },
        "objectives": sorted(objetivos, key=lambda x: x["id"]),
        "sectors": sorted(setores.values(), key=lambda x: (-x["count"], x["sector_en"])),
    }


def atividade(activity_id: int) -> Optional[Dict[str, Any]]:
    """Ficha de uma atividade do Compass (do snapshot local)."""
    if not navigator.SNAPSHOT_PATH.exists():
        return None
    try:
        snapshot = json.loads(navigator.SNAPSHOT_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None
    for atividade in snapshot.get("activities", []):
        if atividade.get("activity_id") == activity_id:
            return atividade
    return None


def recolha_em_curso() -> Optional[Dict[str, Any]]:
    with _lock:
        return dict(_recolha_em_curso) if _recolha_em_curso else None
