"""Geocodificação dos registos LEI pela **sede legal** (endereço da empresa).

Os registos do GLEIF trazem o endereço da sede legal — linha de rua, **código
postal**, cidade, região (ISO 3166-2) e país — mas **não** coordenadas. Este
módulo resolve esse endereço para um ponto, por ordem de precisão decrescente:

1. `postal` — código postal (PT: `2680-102` e o prefixo `2680`; ES: `28001`);
2. `city` — nome da cidade, sem acentos e em minúsculas;
3. (sem resultado) — a ingestão deixa o registo sem ponto e o mapa coloca-o no
   centroide da região/país.

As tabelas vêm do **GeoNames** (ficheiros livres, `zip/` e `dump/`) e são
construídas por `_gleif_geo_build.py` em `data/gleif/geo/<país>.json`. É
geocodificação *offline*: nenhum pedido por registo a serviços externos (o
Nominatim limita a 1 pedido/s e não se pode usar para 212 mil registos).

O resultado é gravado em cada documento (`lat`, `lon`, `location` como
`geo_point` e `geo_precision`), pelo que o mapa pode agregar as empresas por
célula geográfica (`geohash_grid`) — «as empresas pelas suas sedes legais».
"""
from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
GEO_DIR = ROOT / "data" / "gleif" / "geo"

#: Precisões possíveis (a mais fina primeiro) — usado na interface e no relatório.
PRECISION_LABELS: Dict[str, str] = {
    "postal": "Código postal",
    "city": "Cidade",
    "region": "Região (centroide)",
    "country": "País (centroide)",
}

#: Base32 do geohash (para descodificar as células devolvidas pelo Elasticsearch).
_GEOHASH_BASE32 = "0123456789bcdefghjkmnpqrstuvwxyz"


@lru_cache(maxsize=8)
def tables(country: str) -> Optional[Dict[str, Any]]:
    """Carrega (e memoriza) a tabela de um país, ou `None` se não existir."""
    path = GEO_DIR / f"{(country or '').lower()}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Tabela de geocodificação ilegível (%s): %s", path, exc)
        return None


def available_countries() -> List[str]:
    """Países com tabela de geocodificação construída."""
    if not GEO_DIR.exists():
        return []
    return sorted(path.stem.upper() for path in GEO_DIR.glob("*.json"))


def stats() -> Dict[str, Any]:
    """Volumetria das tabelas (para o ecrã de ingestão)."""
    out: Dict[str, Any] = {}
    for country in available_countries():
        table = tables(country) or {}
        out[country] = {
            "postal": len(table.get("postal") or {}),
            "city": len(table.get("city") or {}),
            "generated_at": table.get("generated_at"),
            "sources": table.get("sources"),
        }
    return out


def _postal_candidates(country: str, postal_code: Optional[str]) -> List[str]:
    """Formas do código postal a tentar (mais preciso primeiro)."""
    code = (postal_code or "").strip().upper().replace(" ", "")
    if not code:
        return []
    candidates = [code]
    if country == "PT":
        # `2680-102` → também `2680`; `2680` → também `2680-000`? não vale a pena.
        prefix = code.split("-")[0]
        if prefix != code:
            candidates.append(prefix)
        elif len(code) == 4:
            candidates.append(f"{code}-000")
    return candidates


def resolve(country: Optional[str], postal_code: Optional[str], city: Optional[str]) -> Optional[Tuple[float, float, str]]:
    """Devolve `(lat, lon, precisão)` para o endereço, ou `None` se não souber."""
    code = (country or "").strip().upper()
    table = tables(code) if code else None
    if not table:
        return None
    postal_table: Dict[str, Any] = table.get("postal") or {}
    for candidate in _postal_candidates(code, postal_code):
        point = postal_table.get(candidate)
        if point:
            return float(point[0]), float(point[1]), "postal"
    city_table: Dict[str, Any] = table.get("city") or {}
    key = _fold(city)
    if key:
        point = city_table.get(key)
        if point:
            return float(point[0]), float(point[1]), "city"
    return None


def _fold(value: Optional[str]) -> str:
    """Minúsculas sem acentos (a mesma normalização usada ao construir as tabelas)."""
    if not value:
        return ""
    import unicodedata

    normalized = unicodedata.normalize("NFKD", str(value))
    stripped = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", stripped).strip().lower()


def enrich(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Acrescenta `lat`/`lon`/`location`/`geo_precision` a um documento de LEI.

    Os documentos sem endereço resolvido ficam **sem** ponto: o mapa trata-os
    pelo centroide da região/país, em vez de os colocar numa posição inventada.
    """
    resolved = resolve(doc.get("country"), doc.get("postal_code"), doc.get("city"))
    if not resolved:
        return doc
    lat, lon, precision = resolved
    doc["lat"] = lat
    doc["lon"] = lon
    # `geo_point` aceita [lon, lat] (convenção GeoJSON).
    doc["location"] = [lon, lat]
    doc["geo_precision"] = precision
    return doc


def decode_geohash(cell: str) -> Optional[Tuple[float, float]]:
    """Centro de uma célula geohash (o Elasticsearch devolve só a chave)."""
    if not cell:
        return None
    lat_range = [-90.0, 90.0]
    lon_range = [-180.0, 180.0]
    even = True
    try:
        for char in cell.lower():
            value = _GEOHASH_BASE32.index(char)
            for mask in (16, 8, 4, 2, 1):
                if even:
                    span = (lon_range[1] - lon_range[0]) / 2
                    if value & mask:
                        lon_range[0] += span
                    else:
                        lon_range[1] -= span
                else:
                    span = (lat_range[1] - lat_range[0]) / 2
                    if value & mask:
                        lat_range[0] += span
                    else:
                        lat_range[1] -= span
                even = not even
    except ValueError:
        return None
    return (lat_range[0] + lat_range[1]) / 2, (lon_range[0] + lon_range[1]) / 2


__all__ = ["GEO_DIR", "PRECISION_LABELS", "available_countries", "decode_geohash", "enrich", "resolve", "stats", "tables"]
