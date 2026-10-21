"""Scraper e normalizador do **EU Taxonomy Navigator**.

Recolhe os dados oficiais da Comissão Europeia (DG FISMA) a partir das APIs
públicas do *EU Taxonomy Navigator*:

- https://webgate.ec.europa.eu/sft/api/v1/en/activities/matches
- https://webgate.ec.europa.eu/sft/api/v1/en/objectives
- https://webgate.ec.europa.eu/sft/api/v1/en/sectors

Os dados são normalizados em documentos prontos a indexar no Elasticsearch,
com texto original (EN) e tradução para português (quando disponível). A
cache local em `data/eu_taxonomy_raw/` evita downloads repetidos.

Última sincronização: 2026-10-21.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "eu_taxonomy_raw"
CACHE_DIR = ROOT / "data" / "eu_taxonomy_cache"
SNAPSHOT_PATH = ROOT / "data" / "eu_taxonomy.json"

URL_ACTIVITIES = "https://webgate.ec.europa.eu/sft/api/v1/en/activities/matches"
URL_OBJECTIVES = "https://webgate.ec.europa.eu/sft/api/v1/en/objectives"
URL_SECTORS = "https://webgate.ec.europa.eu/sft/api/v1/en/sectors"
ACTIVITY_VIEW_URL = "https://ec.europa.eu/sustainable-finance-taxonomy/activities/activity/{id}/view"

_translate_cache: Optional[Dict[str, str]] = None
_translate_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _http_get_json(url: str) -> Any:
    import urllib.request

    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _ensure_dirs() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def fetch_raw(force: bool = False) -> Dict[str, Any]:
    """Faz download dos ficheiros raw da API oficial (com cache local)."""
    _ensure_dirs()
    paths = {
        "activities": RAW_DIR / "activities.json",
        "objectives": RAW_DIR / "objectives.json",
        "sectors": RAW_DIR / "sectors.json",
    }
    urls = {
        "activities": URL_ACTIVITIES,
        "objectives": URL_OBJECTIVES,
        "sectors": URL_SECTORS,
    }
    result: Dict[str, Any] = {}
    for key, path in paths.items():
        if not force and path.exists():
            logger.info("EU Taxonomy: a usar cache local de %s", path.name)
            result[key] = json.loads(path.read_text(encoding="utf-8"))
            continue
        try:
            data = _http_get_json(urls[key])
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            result[key] = data
            logger.info("EU Taxonomy: descarregado %s (%d itens)", key, len(data))
        except Exception as exc:
            logger.warning("EU Taxonomy: falha a descarregar %s: %s", key, exc)
            if path.exists():
                result[key] = json.loads(path.read_text(encoding="utf-8"))
            else:
                result[key] = []
    result["synced_at"] = _now()
    return result


def _html_to_text(html: Optional[str]) -> str:
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all("sup"):
        tag.decompose()
    text = soup.get_text(separator=" ")
    text = re.sub(r"\s+", " ", text).strip()
    # Normaliza as aspas curvas que o BeautifulSoup pode deixar mal
    text = text.replace("\u2018", "'").replace("\u2019", "'").replace("\u201c", '"').replace("\u201d", '"')
    return text


def _nace_codes(nace_codes: List[str]) -> List[str]:
    return [str(c).strip().upper() for c in (nace_codes or []) if str(c).strip()]


def _contribuicao_pt(tipo: Optional[str]) -> str:
    mapping = {
        "Enabling": "Atividade facilitadora",
        "Transitional": "Atividade transicional",
        "Contribui significativamente": "Contribui significativamente",
    }
    return mapping.get(str(tipo or ""), str(tipo or ""))


def _objective_label_pt(name: Optional[str], short: Optional[str]) -> Tuple[str, str]:
    mapping: Dict[str, Tuple[str, str]] = {
        "Climate change mitigation": ("Mitigação das alterações climáticas", "Clima (mitigação)"),
        "Climate change adaptation": ("Adaptação às alterações climáticas", "Clima (adaptação)"),
        "Sustainable use and protection of water and marine resources": (
            "Utilização sustentável e proteção dos recursos hídricos e marinhos",
            "Água e mares",
        ),
        "Transition to a circular economy": ("Transição para uma economia circular", "Economia circular"),
        "Pollution prevention and control": ("Prevenção e controlo da poluição", "Poluição"),
        "Protection and restoration of biodiversity and ecosystems": (
            "Proteção e restauro da biodiversidade e dos ecossistemas",
            "Biodiversidade",
        ),
    }
    return mapping.get(str(name or ""), (str(name or ""), str(short or "")))


def _sector_pt(name: str) -> str:
    mapping = {
        "Accommodation activities": "Alojamento",
        "Arts, entertainment and recreation": "Artes, entretenimento e recreação",
        "Construction and real estate activities": "Construção e atividades imobiliárias",
        "Disaster risk management": "Gestão do risco de catástrofes",
        "Education": "Educação",
        "Energy": "Energia",
        "Environmental protection and restoration activities": "Proteção e restauro ambiental",
        "Financial and insurance activities": "Atividades financeiras e de seguros",
        "Forestry": "Silvicultura",
        "Human health and social work activities": "Saúde humana e atividades de apoio social",
        "Information and communication": "Informação e comunicação",
        "Manufacturing": "Indústria transformadora",
        "Professional, scientific and technical activities": "Atividades profissionais, científicas e técnicas",
        "Services": "Serviços",
        "Transport": "Transportes",
        "Water supply, sewerage, waste management and remediation": (
            "Abastecimento de água, saneamento, gestão de resíduos e reabilitação"
        ),
    }
    return mapping.get(name, name)


def build_activities(raw: Dict[str, Any], translate: bool = True) -> List[Dict[str, Any]]:
    """Normaliza a lista de atividades do Compass com campos EN e PT."""
    activities = raw.get("activities") or []
    objectives = raw.get("objectives") or []
    obj_by_id = {int(o["id"]): o for o in objectives}

    docs: List[Dict[str, Any]] = []
    for activity in activities:
        act_id = int(activity.get("id") or 0)
        name_en = str(activity.get("name") or "").strip()
        sector_en = activity.get("sector", {}).get("name") or ""
        sector_id = activity.get("sector", {}).get("id")
        description_en = _html_to_text(activity.get("description"))
        nace = _nace_codes(activity.get("naceCodes") or [])

        matches: List[Dict[str, Any]] = []
        for m in activity.get("matches") or []:
            obj = m.get("objective") or {}
            obj_id = int(obj.get("id") or 0)
            name_obj_en = obj.get("name") or ""
            short_obj_en = obj.get("shortName") or ""
            label_pt, curto_pt = _objective_label_pt(name_obj_en, short_obj_en)
            matches.append(
                {
                    "objective_id": obj_id,
                    "objective_name_en": name_obj_en,
                    "objective_short_en": short_obj_en,
                    "objective_name_pt": label_pt,
                    "objective_short_pt": curto_pt,
                    "contribution_type_en": m.get("activityContributionType") or "Substantial contribution",
                    "contribution_type_pt": _contribuicao_pt(m.get("activityContributionType")),
                }
            )

        doc: Dict[str, Any] = {
            "kind": "activity",
            "activity_id": act_id,
            "name_en": name_en,
            "name_pt": None,
            "sector_id": sector_id,
            "sector_en": sector_en,
            "sector_pt": _sector_pt(sector_en),
            "description_en": description_en,
            "description_pt": None,
            "nace_codes": nace,
            "objectives": matches,
            "url": ACTIVITY_VIEW_URL.format(id=act_id),
            "synced_at": raw.get("synced_at") or _now(),
        }
        docs.append(doc)

    if translate:
        docs = translate_docs(docs)
    return docs


def build_objectives(raw: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Normaliza os objetivos ambientais com campos EN e PT."""
    objectives = raw.get("objectives") or []
    cores = {
        41: "#34d399",
        42: "#38bdf8",
        43: "#22d3ee",
        44: "#a78bfa",
        45: "#fbbf24",
        46: "#fb7185",
    }
    docs: List[Dict[str, Any]] = []
    for obj in objectives:
        obj_id = int(obj.get("id") or 0)
        name_en = str(obj.get("name") or "").strip()
        short_en = str(obj.get("shortName") or "").strip()
        label_pt, curto_pt = _objective_label_pt(name_en, short_en)
        docs.append(
            {
                "kind": "objective",
                "objective_id": obj_id,
                "name_en": name_en,
                "name_pt": label_pt,
                "short_en": short_en,
                "short_pt": curto_pt,
                "color": cores.get(obj_id, "#94a3b8"),
                "synced_at": raw.get("synced_at") or _now(),
            }
        )
    return docs


def build_sectors(raw: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Normaliza os setores do Compass com campos EN e PT."""
    sectors = raw.get("sectors") or []
    docs: List[Dict[str, Any]] = []
    for sector in sectors:
        name_en = str(sector.get("name") or "").strip()
        docs.append(
            {
                "kind": "sector",
                "sector_id": sector.get("id"),
                "name_en": name_en,
                "name_pt": _sector_pt(name_en),
                "synced_at": raw.get("synced_at") or _now(),
            }
        )
    return docs


def build_snapshot(raw: Dict[str, Any], translate: bool = True) -> Dict[str, Any]:
    """Cria o snapshot normalizado (atividades + objetivos + setores)."""
    activities = build_activities(raw, translate=translate)
    objectives = build_objectives(raw)
    sectors = build_sectors(raw)
    return {
        "source": {
            "id": "eu_taxonomy_navigator",
            "label": "EU Taxonomy Navigator — Comissão Europeia",
            "url": "https://ec.europa.eu/sustainable-finance-taxonomy/home",
            "api": "https://webgate.ec.europa.eu/sft/api/v1/en",
            "synced_at": raw.get("synced_at") or _now(),
            "aviso": (
                "A lista serve para elegibilidade indicativa. O alinhamento exige critérios técnicos, "
                "DNSH e salvaguardas mínimas documentados."
            ),
        },
        "total_activities": len(activities),
        "total_objectives": len(objectives),
        "total_sectors": len(sectors),
        "activities": activities,
        "objectives": objectives,
        "sectors": sectors,
    }


# ---------------------------------------------------------------------------
# Tradução PT via IA (mesmo padrão de contratos_fr_translate.py)
# ---------------------------------------------------------------------------

def _load_translate_cache() -> Dict[str, str]:
    global _translate_cache
    if _translate_cache is not None:
        return _translate_cache
    cache_path = CACHE_DIR / "traducao-pt.json"
    try:
        if cache_path.is_file():
            dados = json.loads(cache_path.read_text(encoding="utf-8"))
            _translate_cache = {str(k): str(v) for k, v in dados.items()} if isinstance(dados, dict) else {}
        else:
            _translate_cache = {}
    except Exception as exc:
        logger.warning("Cache de tradução da taxonomia ilegível (%s); a recomeçar.", exc)
        _translate_cache = {}
    return _translate_cache


def _save_translate_cache() -> None:
    if _translate_cache is None:
        return
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_path = CACHE_DIR / "traducao-pt.json"
        temporario = cache_path.with_suffix(f".{uuid.uuid4().hex}.tmp")
        temporario.write_text(json.dumps(_translate_cache, ensure_ascii=False, indent=0), encoding="utf-8")
        temporario.replace(cache_path)
    except Exception as exc:
        logger.warning("Não foi possível gravar a cache de tradução da taxonomia: %s", exc)


def _normalizar(texto: str) -> str:
    return re.sub(r"\s+", " ", (texto or "")).strip()


def translate_docs(
    docs: List[Dict[str, Any]],
    *,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    user_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Traduz nome e descrição das atividades para PT, mantendo originais.

    Usa o modelo local Helsinki-NLP/opus-mt-tc-big-en-pt (o mesmo do módulo
    de notícias), garantindo que a tradução não depende de fornecedores de IA
    externos nem de créditos. Textos longos são truncados a 512 tokens.
    """
    with _translate_lock:
        cache = _load_translate_cache()

    # Coletar textos únicos por traduzir
    textos: List[str] = []
    indices: List[Tuple[int, str]] = []  # (índice do doc, campo: 'name' ou 'desc')
    for idx, doc in enumerate(docs):
        nome = _normalizar(doc.get("name_en") or "")
        desc = _normalizar(doc.get("description_en") or "")
        if nome and nome not in cache and nome not in textos:
            textos.append(nome)
            indices.append((idx, "name"))
        if desc and desc not in cache and desc not in textos:
            textos.append(desc)
            indices.append((idx, "desc"))

    if not textos:
        return [
            {
                **doc,
                "name_pt": doc.get("name_pt") or cache.get(_normalizar(doc.get("name_en") or "")),
                "description_pt": doc.get("description_pt") or cache.get(_normalizar(doc.get("description_en") or "")),
            }
            for doc in docs
        ]

    try:
        from api.news_nlp import _translate_en_to_pt
    except Exception as exc:
        logger.warning("EU Taxonomy: tradutor local não disponível: %s", exc)
        return docs

    novas_traducoes: Dict[str, str] = {}
    for original in textos:
        try:
            traduzido = _translate_en_to_pt(original)
            limpo = _normalizar(traduzido)
            if limpo and limpo != original:
                novas_traducoes[original] = limpo
        except Exception as exc:
            logger.debug("EU Taxonomy: falha a traduzir '%s...': %s", original[:40], exc)

    with _translate_lock:
        cache.update(novas_traducoes)
        if len(cache) > 50000:
            for chave in list(cache)[: len(cache) - 50000]:
                cache.pop(chave, None)
        _save_translate_cache()

    for idx, campo in indices:
        original = _normalizar(docs[idx].get("name_en" if campo == "name" else "description_en") or "")
        if original in novas_traducoes:
            if campo == "name":
                docs[idx]["name_pt"] = novas_traducoes[original]
            else:
                docs[idx]["description_pt"] = novas_traducoes[original]

    return docs


def save_snapshot(snapshot: Dict[str, Any]) -> Path:
    """Grava o snapshot normalizado em `data/eu_taxonomy.json`."""
    _ensure_dirs()
    temporario = SNAPSHOT_PATH.with_suffix(f".{uuid.uuid4().hex}.tmp")
    temporario.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    temporario.replace(SNAPSHOT_PATH)
    logger.info("EU Taxonomy: snapshot gravado em %s", SNAPSHOT_PATH)
    return SNAPSHOT_PATH


def run(force: bool = False, translate: bool = True) -> Dict[str, Any]:
    """Executa a recolha completa: download, normalização, tradução e snapshot."""
    raw = fetch_raw(force=force)
    snapshot = build_snapshot(raw, translate=translate)
    save_snapshot(snapshot)
    return snapshot
