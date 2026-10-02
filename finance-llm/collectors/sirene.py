"""Cliente leve para a API Sirene (data.gouv.fr / INSEE).

Utiliza o endpoint público de pesquisa de estabelecimentos/sediados:
https://recherche-entreprises.api.gouv.fr/recherche?mtm_campaign=portail-api&mtm_kwd=recherche-entreprises

A pesquisa pode ser por SIRET (14 dígitos) ou SIREN (9 dígitos). O campo
`nom_complet` devolve a denominação normalizada da entidade.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import httpx

ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / "data" / "cache" / "sirene"
CACHE_TTL_SECONDS = 86400 * 7  # 7 dias

API_BASE = "https://recherche-entreprises.api.gouv.fr"
SEARCH_URL = f"{API_BASE}/search"


@dataclass(frozen=True, slots=True)
class SireneResult:
    siren: Optional[str]
    siret: Optional[str]
    nom_complet: Optional[str]
    nom_raison_sociale: Optional[str]
    sigle: Optional[str]
    prenom: Optional[str]
    nom: Optional[str]
    siege: bool
    complement_adresse: Optional[str]
    numero_voie: Optional[str]
    indice_repetition: Optional[str]
    type_voie: Optional[str]
    libelle_voie: Optional[str]
    distribution_speciale: Optional[str]
    code_postal: Optional[str]
    libelle_commune: Optional[str]
    code_commune: Optional[str]
    activite_principale: Optional[str]
    section_activite_principale: Optional[str]
    date_creation: Optional[str]
    tranche_effectif: Optional[str]
    raw: Dict[str, Any]

    def display_name(self) -> str:
        """Nome legível preferido: nom_complet > raison sociale > SIRET."""
        return (
            self.nom_complet
            or self.nom_raison_sociale
            or (f"{self.prenom} {self.nom}".strip() if (self.prenom or self.nom) else "")
            or self.siret
            or self.siren
            or ""
        )


def _normalize_id(value: Optional[Union[str, int]]) -> Optional[str]:
    if value is None:
        return None
    s = re.sub(r"\D", "", str(value))
    return s or None


def _cache_path(key: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", key)[:120]
    return CACHE_DIR / f"{safe}.json"


def _read_cache(key: str) -> Optional[List[Dict[str, Any]]]:
    path = _cache_path(key)
    if not path.exists():
        return None
    try:
        if time.time() - path.stat().st_mtime > CACHE_TTL_SECONDS:
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_cache(key: str, payload: List[Dict[str, Any]]) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _cache_path(key).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _parse_result(item: Dict[str, Any]) -> SireneResult:
    siege = item.get("siege", {}) or {}
    nom = item.get("nom_complet") or item.get("nom_raison_sociale")
    return SireneResult(
        siren=_normalize_id(item.get("siren")),
        siret=_normalize_id(item.get("siret")) or _normalize_id(siege.get("siret")),
        nom_complet=item.get("nom_complet"),
        nom_raison_sociale=item.get("nom_raison_sociale"),
        sigle=item.get("sigle"),
        prenom=item.get("prenom"),
        nom=item.get("nom"),
        siege=bool(item.get("siege") and isinstance(item.get("siege"), dict)),
        complement_adresse=siege.get("complement_adresse"),
        numero_voie=siege.get("numero_voie"),
        indice_repetition=siege.get("indice_repetition"),
        type_voie=siege.get("type_voie"),
        libelle_voie=siege.get("libelle_voie"),
        distribution_speciale=siege.get("distribution_speciale"),
        code_postal=siege.get("code_postal"),
        libelle_commune=siege.get("libelle_commune"),
        code_commune=siege.get("code_commune"),
        activite_principale=item.get("activite_principale"),
        section_activite_principale=item.get("section_activite_principale"),
        date_creation=item.get("date_creation"),
        tranche_effectif=item.get("tranche_effectif_salarie"),
        raw=item,
    )


def search_sirene(
    q: str,
    *,
    page: int = 1,
    per_page: int = 10,
    cache: bool = True,
    timeout: float = 30.0,
) -> List[SireneResult]:
    """Pesquisa entidades francesas por SIRET, SIREN ou texto.

    A API recherche-entreprises.api.gouv.fr aceita q=SIRET(14) ou SIREN(9)
    diretamente e devolve os resultados mais relevantes.
    """
    key = f"search_{q}_p{page}_pp{per_page}"
    if cache:
        cached = _read_cache(key)
        if cached is not None:
            return [_parse_result(item) for item in cached]

    params: Dict[str, Any] = {"q": q, "page": page, "per_page": per_page}
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        resp = client.get(SEARCH_URL, params=params)
    resp.raise_for_status()
    data = resp.json()
    items = data.get("results", []) if isinstance(data, dict) else []
    if cache and items:
        _write_cache(key, items)
    return [_parse_result(item) for item in items]


def enrich_name(identifier: Optional[Union[str, int]], *, cache: bool = True) -> Optional[str]:
    """Devolve o `nom_complet` para um SIRET/SIREN, ou None se falhar."""
    ident = _normalize_id(identifier)
    if not ident:
        return None
    try:
        results = search_sirene(ident, per_page=5, cache=cache)
        for r in results:
            name = r.display_name()
            if name:
                return name
        return None
    except Exception:
        return None


def _siret_from_siren(siren: str) -> Optional[str]:
    """Devolve o SIRET do estabelecimento sede quando só temos SIREN (9)."""
    if len(siren) != 9:
        return None
    try:
        results = search_sirene(siren, per_page=5)
        for r in results:
            if r.siret and r.siret.startswith(siren):
                return r.siret
            if r.siege and r.siret:
                return r.siret
        # fallback: qualquer siret do resultado
        for r in results:
            if r.siret:
                return r.siret
    except Exception:
        pass
    return None


def batch_enrich(identifiers: List[str], *, cache: bool = True, delay: float = 0.05) -> Dict[str, Optional[str]]:
    """Enriquece um lote de identificadores SIRET/SIREN com respeito de rate limit."""
    out: Dict[str, Optional[str]] = {}
    seen: set[str] = set()
    for ident in identifiers:
        n = _normalize_id(ident)
        if not n or n in seen:
            continue
        seen.add(n)
        out[ident] = enrich_name(n, cache=cache)
        if delay > 0:
            time.sleep(delay)
    return out


if __name__ == "__main__":
    import sys

    query = sys.argv[1] if len(sys.argv) > 1 else "13000548100010"
    print(f"Pesquisar: {query}")
    for r in search_sirene(query, per_page=3):
        print(r.siret or r.siren, "-", r.display_name(), "-", r.libelle_commune)
