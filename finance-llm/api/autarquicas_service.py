"""Recolha e cache dos candidatos às Autárquicas 2025 (site eleicoes.mai.gov.pt).

A fonte oficial publica os dados em JSON estáticos. Este serviço descarrega-os,
normaliza-os e guarda uma cache local para não sobrecarregar o site. A cache
é válida por 24 horas; pode ser forçada a recarregar através da rota de refresh.
"""
from __future__ import annotations

import json
import logging
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://www.eleicoes.mai.gov.pt/autarquicas2025"
CANDIDATES_URL = (
    "{base}/assets/static/candidate/candidates-electionId=1-territoryId=null"
    "-votingOptionName={party}-candidatesElected=false-page={page}.json"
)
TERRITORY_CHILDREN_URL = "{base}/assets/static/territory/children-electionId=1-territoryId={territory_id}.json"

# Cache local no disco (mesma pasta que outras caches de dados públicos).
DEFAULT_DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "autarquicas2025"
CACHE_TTL_SECONDS = 24 * 60 * 60

_LOCK = threading.Lock()


def _data_dir() -> Path:
    path = DEFAULT_DATA_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def _cache_path(name: str) -> Path:
    return _data_dir() / f"{name}.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _fetch_json(url: str, timeout: float = 60.0) -> Optional[Dict[str, Any]]:
    """Descarrega um JSON do site oficial, com User-Agent explícito."""
    try:
        with httpx.Client(
            timeout=timeout,
            headers={"User-Agent": "IQOS/1.0 (analise politica; contacto@icpm.tech)"},
            follow_redirects=True,
        ) as client:
            resp = client.get(url)
            resp.raise_for_status()
            return resp.json()
    except Exception as exc:
        logger.warning("Falha a obter %s: %s", url, exc)
        return None


def _read_cache(name: str) -> Optional[Dict[str, Any]]:
    path = _cache_path(name)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        cached_at = data.get("cached_at", "")
        if cached_at:
            try:
                dt = datetime.fromisoformat(cached_at.replace("Z", "+00:00"))
                age = (datetime.now(timezone.utc) - dt).total_seconds()
                if age > CACHE_TTL_SECONDS:
                    return None
            except Exception:
                return None
        return data
    except Exception as exc:
        logger.debug("Cache %s inválida: %s", name, exc)
        return None


def _write_cache(name: str, payload: Dict[str, Any]) -> None:
    path = _cache_path(name)
    try:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.warning("Não foi possível guardar cache %s: %s", name, exc)


def _fetch_all_candidates(refresh: bool = False) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Percorre as páginas de candidatos e devolve (territórios, candidatos)."""
    cache_name = "candidates_all"
    if not refresh:
        cached = _read_cache(cache_name)
        if cached:
            return cached.get("territories", []), cached.get("candidates", [])

    territories: List[Dict[str, Any]] = []
    candidates: List[Dict[str, Any]] = []
    seen: set = set()
    page = 1
    while True:
        url = CANDIDATES_URL.format(base=BASE_URL, party="null", page=page)
        data = _fetch_json(url)
        if not data:
            break
        if not data.get("isSuccess"):
            # A API devolve isSuccess:false nas páginas vazias (ex.: página 3).
            break
        batch = (data.get("data") or {}).get("territories") or []
        if not batch:
            break
        for district in batch:
            district_name = district.get("description", "")
            for concelho in district.get("territories") or []:
                concelho_name = concelho.get("description", "")
                concelho_id = concelho.get("id")
                for option in concelho.get("votingOptions") or []:
                    vo = option.get("votingOption") or {}
                    party_name = vo.get("name", "")
                    party_description = vo.get("description", "")
                    for cand in option.get("candidates") or []:
                        name = cand.get("name", "").strip()
                        if not name:
                            continue
                        key = (concelho_id, party_name, name)
                        if key in seen:
                            continue
                        seen.add(key)
                        candidates.append({
                            "name": name,
                            "position": cand.get("position") or 1,
                            "type": cand.get("type", "Efetivo"),
                            "state": cand.get("state", "NA"),
                            "party": party_name,
                            "party_description": party_description,
                            "district": district_name,
                            "district_id": district.get("id"),
                            "concelho": concelho_name,
                            "concelho_id": concelho_id,
                            "election": "Autárquicas 2025",
                            "election_id": 1,
                        })
        territories.extend(batch)
        page += 1

    payload = {
        "cached_at": _now_iso(),
        "ttl_seconds": CACHE_TTL_SECONDS,
        "territories": territories,
        "candidates": candidates,
    }
    _write_cache(cache_name, payload)
    return territories, candidates


def _normalize_name(name: str) -> str:
    """Remove espaços extra e normaliza maiúsculas/minúsculas."""
    return re.sub(r"\s+", " ", name).strip()


def _match_person(name: str, party: str, people: List[Dict[str, Any]]) -> Optional[str]:
    """Tenta encontrar um NIF na ficha de pessoas pelo nome e partido.

    Usa uma correspondência simples: nome normalizado igual. A ligação NIF é
    opcional — muitos candidatos autárquicos não têm ficha societária.
    """
    target = _normalize_name(name).lower()
    for person in people:
        person_name = _normalize_name(person.get("name") or "").lower()
        if person_name == target:
            return person.get("nif")
        # Permite procurar por parte do nome quando o candidato tem vários nomes.
        if target in person_name or person_name in target:
            # Só aceita se partido bater (evita homónimos).
            person_party = (person.get("metadata") or {}).get("party") or person.get("party") or ""
            if person_party and party and party.lower() in str(person_party).lower():
                return person.get("nif")
    return None


def _enrich_candidates(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Tenta ligar cada candidato a uma ficha de pessoa existente."""
    from api.elasticsearch_client import search_people

    try:
        # Recolhe um lote de candidatos por partido para minimizar pedidos.
        parties: Dict[str, List[Dict[str, Any]]] = {}
        for cand in candidates:
            parties.setdefault(cand["party"], []).append(cand)

        enriched = []
        for party, items in parties.items():
            people_resp = search_people(party=party, size=100)
            people = people_resp.get("items", []) if not people_resp.get("error") else []
            for cand in items:
                cand_copy = dict(cand)
                cand_copy["nif"] = _match_person(cand["name"], cand["party"], people)
                enriched.append(cand_copy)
        return enriched
    except Exception as exc:
        logger.warning("Erro ao enriquecer candidatos: %s", exc)
        return candidates


# ---------------------------------------------------------------------------
# API pública do serviço
# ---------------------------------------------------------------------------

def list_candidates(
    q: Optional[str] = None,
    district: Optional[str] = None,
    concelho: Optional[str] = None,
    party: Optional[str] = None,
    refresh: bool = False,
    size: int = 200,
    page: int = 1,
) -> Dict[str, Any]:
    """Lista e filtra candidatos autárquicos."""
    territories, candidates = _fetch_all_candidates(refresh=refresh)

    items = candidates
    if q:
        term = q.lower()
        items = [c for c in items if term in c["name"].lower() or term in (c["party"] or "").lower()]
    if district:
        items = [c for c in items if district.lower() in (c["district"] or "").lower()]
    if concelho:
        items = [c for c in items if concelho.lower() in (c["concelho"] or "").lower()]
    if party:
        party_lower = party.lower()
        items = [c for c in items if party_lower == (c["party"] or "").lower() or party_lower in (c["party_description"] or "").lower()]

    total = len(items)
    from_ = max(0, (page - 1) * size)
    to = from_ + size
    page_items = items[from_:to]

    # Distritos, concelhos e partidos disponíveis para filtros.
    facets = {
        "districts": sorted({c["district"] for c in candidates if c.get("district")}),
        "concelhos": sorted({c["concelho"] for c in candidates if c.get("concelho")}),
        "parties": sorted({c["party"] for c in candidates if c.get("party")}),
    }

    return {
        "total": total,
        "page": page,
        "size": size,
        "items": page_items,
        "facets": facets,
        "cached_at": _read_cache("candidates_all") or {},
    }


def candidate_detail(name: str, party: Optional[str] = None, concelho: Optional[str] = None) -> Dict[str, Any]:
    """Devolve os registos de um candidato (pode haver homónimos)."""
    territories, candidates = _fetch_all_candidates(refresh=False)
    name_norm = _normalize_name(name).lower()
    matches = [
        c for c in candidates
        if _normalize_name(c["name"]).lower() == name_norm
        and (not party or party.lower() in (c["party"] or "").lower())
        and (not concelho or concelho.lower() in (c["concelho"] or "").lower())
    ]
    # Tenta ligar a pessoas.
    enriched = _enrich_candidates(matches)
    return {
        "total": len(enriched),
        "items": enriched,
    }


def refresh_candidates() -> Dict[str, Any]:
    """Força a recolha nova dos dados oficiais."""
    territories, candidates = _fetch_all_candidates(refresh=True)
    return {
        "refreshed_at": _now_iso(),
        "total": len(candidates),
        "territories": len(territories),
    }


def stats() -> Dict[str, Any]:
    """Resumo da cache e volumetria."""
    territories, candidates = _fetch_all_candidates(refresh=False)
    parties = {}
    districts = {}
    for c in candidates:
        parties[c["party"]] = parties.get(c["party"], 0) + 1
        districts[c["district"]] = districts.get(c["district"], 0) + 1
    cache = _read_cache("candidates_all") or {}
    return {
        "total_candidates": len(candidates),
        "total_concelhos": len({c["concelho"] for c in candidates}),
        "total_parties": len(parties),
        "total_districts": len(districts),
        "cached_at": cache.get("cached_at"),
        "ttl_seconds": CACHE_TTL_SECONDS,
        "top_parties": sorted(parties.items(), key=lambda kv: kv[1], reverse=True)[:20],
        "districts": sorted(districts.items(), key=lambda kv: kv[1], reverse=True),
    }
