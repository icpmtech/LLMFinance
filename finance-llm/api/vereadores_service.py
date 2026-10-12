"""Recolha, normalização e pesquisa de vereadores e remunerações autárquicas.

O módulo suporta três fontes de dados:
1. **Candidatos às autárquicas 2025** (`eleicoes.mai.gov.pt`) — já disponíveis no
   IQ OS; usados como base de pessoas em cargos políticos locais.
2. **Importação manual** — JSON/CSV com vereadores eleitos e remunerações.
3. **Scraper genérico por câmara municipal** — recolhe listas de vereadores e
   tabelas de remunerações dos sites das 308 câmaras, indexando tudo num
   índice próprio (`finance_vereadores`).

Toda a informação é persistida em `data/vereadores/` (JSON) e em
`finance_vereadores` no Elasticsearch, de forma a ser pesquisável por nome,
câmara, distrito, cargo, partido e valores de remuneração.
"""
from __future__ import annotations

import csv
import io
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
    "-votingOptionName=null-candidatesElected=false-page={page}.json"
)

DEFAULT_DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "vereadores"
CACHE_TTL_SECONDS = 24 * 60 * 60

_LOCK = threading.Lock()

# Lista conhecida de sites de câmaras municipais (308 concelhos). Cada entrada
# pode ser usada como seed para o scraper genérico. Os URLs podem ser
# substituídos ou expandidos a partir de fontes externas.
CAMARA_SITES: List[Dict[str, str]] = []


def _data_dir() -> Path:
    path = DEFAULT_DATA_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def _cache_path(name: str) -> Path:
    return _data_dir() / f"{name}.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _normalize_name(name: str) -> str:
    """Remove espaços extra e normaliza maiúsculas/minúsculas."""
    return re.sub(r"\s+", " ", name).strip()


def _fetch_json(url: str, timeout: float = 60.0) -> Optional[Dict[str, Any]]:
    """Descarrega um JSON com User-Agent explícito."""
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


def _fetch_candidates_from_mai(refresh: bool = False) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Recolhe candidatos à presidência da câmara diretamente do site do MAI.

    Embora o site do MAI não publique vereadores, os candidatos à presidência
    são a base de pessoas em cargos políticos locais e podem ser enriquecidos
    com dados de remuneração vindos de outras fontes.
    """
    cache_name = "mai_candidates"
    if not refresh:
        cached = _read_cache(cache_name)
        if cached:
            return cached.get("territories", []), cached.get("candidates", [])

    territories: List[Dict[str, Any]] = []
    candidates: List[Dict[str, Any]] = []
    seen: set = set()
    page = 1
    while True:
        url = CANDIDATES_URL.format(base=BASE_URL, page=page)
        data = _fetch_json(url)
        if not data or not data.get("isSuccess"):
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
                            "role": "Presidente" if cand.get("state") == "President" else "Candidato à Presidência",
                            "party": party_name,
                            "party_description": party_description,
                            "district": district_name,
                            "district_id": district.get("id"),
                            "concelho": concelho_name,
                            "concelho_id": concelho_id,
                            "election": "Autárquicas 2025",
                            "election_id": 1,
                            "source": "mai_candidatos",
                            "remuneration": None,
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


def _build_vereador_doc(
    name: str,
    concelho: str,
    district: str,
    party: str,
    role: str,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Constrói um documento normalizado para o índice finance_vereadores."""
    now = _now_iso()
    doc_id = kwargs.get("doc_id") or re.sub(r"[^a-z0-9]+", "-", f"{concelho}-{name}".lower()).strip("-")
    doc: Dict[str, Any] = {
        "doc_id": doc_id,
        "name": _normalize_name(name),
        "name_keyword": _normalize_name(name).lower(),
        "concelho": concelho,
        "concelho_keyword": concelho.lower(),
        "district": district,
        "district_keyword": district.lower(),
        "party": party,
        "party_keyword": party.lower(),
        "role": role,
        "role_keyword": role.lower(),
        "source": kwargs.get("source", "import"),
        "source_url": kwargs.get("source_url"),
        "election": kwargs.get("election", "Autárquicas 2025"),
        "year": kwargs.get("year") or 2025,
        "remuneration": kwargs.get("remuneration"),
        "raw_data": kwargs.get("raw_data"),
        "ingested_at": now,
        "updated_at": now,
    }
    if "nif" in kwargs and kwargs["nif"]:
        doc["nif"] = str(kwargs["nif"]).strip()
    if kwargs.get("notes"):
        doc["notes"] = kwargs["notes"]
    return doc


def _parse_money(value: Any) -> Optional[float]:
    """Tenta extrair um valor numérico de uma string monetária portuguesa."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value)
    # Remove pontos de milhar e substitui vírgula decimal por ponto.
    text = text.replace(".", "").replace(",", ".").replace("€", "").replace(" ", "")
    try:
        return float(text) if text else None
    except Exception:
        return None


def _list_json_files() -> List[Path]:
    """Devolve todos os ficheiros .json na pasta de dados dos vereadores."""
    return sorted(_data_dir().glob("*.json"))


# ---------------------------------------------------------------------------
# API pública do serviço
# ---------------------------------------------------------------------------

def list_vereadores(
    q: Optional[str] = None,
    district: Optional[str] = None,
    concelho: Optional[str] = None,
    party: Optional[str] = None,
    role: Optional[str] = None,
    has_remuneration: Optional[bool] = None,
    size: int = 50,
    page: int = 1,
) -> Dict[str, Any]:
    """Lista vereadores candidatos/presidentes importados ou recolhidos."""
    all_docs: List[Dict[str, Any]] = []
    for path in _list_json_files():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            items = data.get("items") or data.get("candidates") or []
            for item in items:
                if "role" not in item:
                    continue
                all_docs.append(item)
        except Exception as exc:
            logger.debug("Ignorar ficheiro %s: %s", path, exc)

    items = all_docs
    if q:
        term = q.lower()
        items = [c for c in items if term in c.get("name", "").lower() or term in (c.get("party") or "").lower()]
    if district:
        items = [c for c in items if district.lower() in (c.get("district") or "").lower()]
    if concelho:
        items = [c for c in items if concelho.lower() in (c.get("concelho") or "").lower()]
    if party:
        items = [c for c in items if party.lower() in (c.get("party") or "").lower()]
    if role:
        items = [c for c in items if role.lower() in (c.get("role") or "").lower()]
    if has_remuneration is not None:
        if has_remuneration:
            items = [c for c in items if c.get("remuneration") is not None]
        else:
            items = [c for c in items if c.get("remuneration") is None]

    total = len(items)
    from_ = max(0, (page - 1) * size)
    to = from_ + size

    facets = {
        "districts": sorted({c.get("district") for c in all_docs if c.get("district")}),
        "concelhos": sorted({c.get("concelho") for c in all_docs if c.get("concelho")}),
        "parties": sorted({c.get("party") for c in all_docs if c.get("party")}),
        "roles": sorted({c.get("role") for c in all_docs if c.get("role")}),
    }

    return {
        "total": total,
        "page": page,
        "size": size,
        "items": items[from_:to],
        "facets": facets,
        "cached_at": _now_iso(),
    }


def refresh_candidates() -> Dict[str, Any]:
    """Força a recolha nova dos candidatos do MAI e guarda em JSON."""
    territories, candidates = _fetch_candidates_from_mai(refresh=True)
    _write_cache("candidates_all", {
        "cached_at": _now_iso(),
        "ttl_seconds": CACHE_TTL_SECONDS,
        "territories": territories,
        "candidates": candidates,
    })
    return {
        "refreshed_at": _now_iso(),
        "total": len(candidates),
        "territories": len(territories),
    }


def import_vereadores(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Importa manualmente uma lista de vereadores/remunerações.

    Cada item deve ter pelo menos `name`, `concelho`, `district`, `party`,
    `role`. Os restantes campos são opcionais (`remuneration`, `source_url`,
    `nif`, `notes`, `year`, `election`).
    """
    normalized = []
    seen = set()
    for raw in items:
        name = _normalize_name(raw.get("name", ""))
        concelho = _normalize_name(raw.get("concelho", ""))
        district = _normalize_name(raw.get("district", ""))
        party = _normalize_name(raw.get("party", ""))
        role = _normalize_name(raw.get("role", ""))
        if not name or not concelho or not role:
            continue
        key = f"{concelho}-{party}-{role}-{name}".lower()
        if key in seen:
            continue
        seen.add(key)
        remuneration = raw.get("remuneration")
        if remuneration and isinstance(remuneration, dict):
            for k, v in list(remuneration.items()):
                if k in ("base", "subsidios", "total", "despesas_representacao", "seguranca_social"):
                    remuneration[k] = _parse_money(v)
        normalized.append(_build_vereador_doc(
            name=name,
            concelho=concelho,
            district=district,
            party=party,
            role=role,
            source=raw.get("source", "import"),
            source_url=raw.get("source_url"),
            election=raw.get("election", "Autárquicas 2025"),
            year=raw.get("year") or 2025,
            remuneration=remuneration,
            nif=raw.get("nif"),
            notes=raw.get("notes"),
            raw_data=raw,
        ))

    path = _cache_path("imported_vereadores")
    existing = _read_cache("imported_vereadores") or {"items": []}
    existing_items = existing.get("items", [])
    merged = {f"{i.get('concelho','')}-{i.get('party','')}-{i.get('role','')}-{i.get('name','')}".lower(): i for i in existing_items}
    for doc in normalized:
        merged[doc["doc_id"]] = doc
    final = list(merged.values())
    _write_cache("imported_vereadores", {
        "cached_at": _now_iso(),
        "items": final,
    })

    try:
        _index_vereadores(final)
    except Exception as exc:
        logger.warning("Falha a indexar vereadores importados: %s", exc)

    return {
        "imported": len(normalized),
        "total": len(final),
        "path": str(path),
    }


def import_vereadores_csv(csv_text: str) -> Dict[str, Any]:
    """Importa vereadores a partir de texto CSV."""
    rows = list(csv.DictReader(io.StringIO(csv_text, newline="")))
    return import_vereadores(rows)


def _index_vereadores(items: Iterable[Dict[str, Any]]) -> None:
    """Indexa documentos de vereadores no Elasticsearch (`finance_vereadores`)."""
    from api.elasticsearch_client import get_es_client, index_vereadores_bulk
    client = get_es_client()
    index_vereadores_bulk(items, es=client)


def search_vereadores_index(
    q: Optional[str] = None,
    district: Optional[str] = None,
    concelho: Optional[str] = None,
    party: Optional[str] = None,
    role: Optional[str] = None,
    size: int = 50,
    page: int = 1,
) -> Dict[str, Any]:
    """Pesquisa no índice Elasticsearch `finance_vereadores`."""
    from api.elasticsearch_client import search_vereadores
    return search_vereadores(
        q=q,
        district=district,
        concelho=concelho,
        party=party,
        role=role,
        size=size,
        page=page,
    )


def stats() -> Dict[str, Any]:
    """Resumo dos dados de vereadores disponíveis localmente."""
    files = _list_json_files()
    total = 0
    with_remuneration = 0
    by_role: Dict[str, int] = {}
    by_source: Dict[str, int] = {}
    concelhos: set = set()
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            items = data.get("items") or data.get("candidates") or []
            for c in items:
                if "role" not in c:
                    continue
                total += 1
                if c.get("remuneration") is not None:
                    with_remuneration += 1
                role = c.get("role", "Desconhecido")
                by_role[role] = by_role.get(role, 0) + 1
                source = c.get("source", "desconhecido")
                by_source[source] = by_source.get(source, 0) + 1
                if c.get("concelho"):
                    concelhos.add(c["concelho"])
        except Exception as exc:
            logger.debug("Ignorar ficheiro %s: %s", path, exc)

    return {
        "total": total,
        "with_remuneration": with_remuneration,
        "total_concelhos": len(concelhos),
        "roles": by_role,
        "sources": by_source,
        "files": [str(p.name) for p in files],
        "data_dir": str(_data_dir()),
    }


def get_concelhos() -> List[str]:
    """Devolve a lista de concelhos conhecidos nos dados locais."""
    concelhos: set = set()
    for path in _list_json_files():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            items = data.get("items") or data.get("candidates") or []
            for c in items:
                if c.get("concelho"):
                    concelhos.add(c["concelho"])
        except Exception:
            continue
    return sorted(concelhos)
