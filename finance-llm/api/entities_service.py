"""Serviço do cadastro de entidades do portal base (``data/entidades-gov-portal-base/entidades.json``).

O ficheiro tem ~74 MB e ~214 mil registos, pelo que é lido em streaming (sem
carregar tudo em memória) e normalizado para o formato do índice
``finance_entities``.

Esquema de origem (por registo):
    nifEntidade, desigEntidade, numContratos, totAdjudicante, totAdjudicatario,
    totValorContratIni, totAdjudicanteValorContratIni, descPais, AliasPais

Notas:
- ``nifEntidade`` pode ser ``"-"`` (entidades estrangeiras ou antigas sem NIF).
- Entidades sem NIF recebem um ``_id`` determinístico baseado no nome, para que
  reingestões sejam idempotentes.
- CAE é enriquecido a partir do serviço ``collectors.cae_service`` (PNS/RNPC).
  A ingestão em massa não chama o serviço automaticamente por questões de
  performance; o enriquecimento faz-se sob demanda via ``enrich_entity_cae``.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from api.elasticsearch_client import search_directory, search_entities
from api.racius_service import INDEX as RACIUS_INDEX, available as racius_available

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
ENTITIES_JSON = ROOT / "data" / "entidades-gov-portal-base" / "entidades.json"

NIF_RE = re.compile(r"^\d{9}$")

# Campos alternativos aceites caso a origem mude de nome.
NAME_KEYS = ("desigEntidade", "name", "nome", "denominacao", "designacao")
NIF_KEYS = ("nifEntidade", "nif", "NIF")
COUNTRY_KEYS = ("descPais", "pais", "country")
COUNTRY_CODE_KEYS = ("AliasPais", "country_code")


def iter_json_array(path: Path, read_size: int = 1 << 16) -> Iterator[Any]:
    """Itera um array JSON de topo em streaming, sem carregar o ficheiro todo.

    Usa ``JSONDecoder.raw_decode`` sobre um buffer incremental, o que evita
    dependências externas (ijson/orjson) e mantém o uso de memória baixo.
    """
    decoder = json.JSONDecoder()
    with open(path, encoding="utf-8-sig") as fh:
        buf = ""
        # Avançar até ao início do array.
        while True:
            chunk = fh.read(read_size)
            if not chunk:
                return
            buf += chunk
            start = buf.find("[")
            if start != -1:
                buf = buf[start + 1:]
                break

        eof = False
        while True:
            # Saltar separadores e espaços.
            buf = buf.lstrip()
            while buf and buf[0] in ", \r\n\t":
                buf = buf[1:]
                buf = buf.lstrip()
            if not buf:
                if eof:
                    return
                chunk = fh.read(read_size)
                if not chunk:
                    eof = True
                    continue
                buf += chunk
                continue
            if buf[0] == "]":
                return
            try:
                obj, index = decoder.raw_decode(buf)
            except ValueError:
                # Objeto ainda incompleto: ler mais dados.
                if eof:
                    logger.warning("JSON inválido e fim de ficheiro em %s", path)
                    return
                chunk = fh.read(read_size)
                if not chunk:
                    eof = True
                    continue
                buf += chunk
                continue
            yield obj
            buf = buf[index:]


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _first(raw: Dict[str, Any], keys: tuple) -> str:
    for key in keys:
        value = _text(raw.get(key))
        if value and value != "-":
            return value
    return ""


def _as_int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def normalize_entity(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Normaliza um registo de entidade para o documento do Elasticsearch."""
    if not isinstance(raw, dict):
        return None
    name = _first(raw, NAME_KEYS)
    if not name:
        return None

    nif_raw = _first(raw, NIF_KEYS)
    nif = nif_raw if NIF_RE.match(nif_raw) else None

    country = _first(raw, COUNTRY_KEYS)
    country_code = _first(raw, COUNTRY_CODE_KEYS)

    doc: Dict[str, Any] = {
        "nif": nif,
        "name": name,
        "country": country,
        "country_code": country_code.upper() if country_code else "",
        "has_nif": nif is not None,
        "contracts_count": _as_int(raw.get("numContratos")),
        "as_adjudicante_count": _as_int(raw.get("totAdjudicante")),
        "as_adjudicatario_count": _as_int(raw.get("totAdjudicatario")),
        "total_value": round(_as_float(raw.get("totValorContratIni")), 2),
        "as_adjudicante_value": round(_as_float(raw.get("totAdjudicanteValorContratIni")), 2),
        "cae_principal": None,
        "caes_secundarios": [],
        "source": "entidades_gov_portal_base",
    }
    return doc


def enrich_entity_cae(doc: Dict[str, Any], min_interval: float = 0.5) -> Dict[str, Any]:
    """Completa um documento de entidade com CAE recolhido do PNS/RNPC.

    A função é segura: não levanta exceções e devolve o doc inalterado se a
    recolha falhar.
    """
    from collectors.cae_service import collect_cae

    name = doc.get("name")
    nif = doc.get("nif")
    if not name:
        return doc
    try:
        result = collect_cae(name, nif=nif, save=False, min_interval=min_interval)
        if result.get("cae_principal"):
            doc["cae_principal"] = result["cae_principal"]
        if result.get("caes_secundarios"):
            doc["caes_secundarios"] = result["caes_secundarios"]
        doc["cae_source"] = "pns_rnpc"
        doc["cae_match"] = result.get("match")
    except Exception as exc:
        logger.warning("Falha ao enriquecer CAE de %s: %s", name, exc)
    return doc


def entity_doc_id(doc: Dict[str, Any]) -> str:
    """Devolve um identificador estável para o documento.

    Usa o NIF quando existe. Caso contrário recorre a um hash do conteúdo
    relevante (nome, país, contagens e valor) — e não apenas do nome — porque a
    origem contém registos distintos com o mesmo nome (entidades anonimizadas
    com "Nome suprimido face a dados pessoais", descrições genéricas, etc.).
    Assim preservam-se todos os registos e reingestões continuam idempotentes.
    """
    if doc.get("nif"):
        return str(doc["nif"])

    canonical = "|".join(
        str(doc.get(key) or "")
        for key in (
            "name",
            "country",
            "country_code",
            "contracts_count",
            "as_adjudicante_count",
            "as_adjudicatario_count",
            "total_value",
            "as_adjudicante_value",
        )
    )
    digest = hashlib.sha1(canonical.encode("utf-8")).hexdigest()
    return f"nome:{digest[:24]}"


#: Campos do Racius que queremos expor como complemento no cadastro de entidades.
_RACIUS_ITEM_FIELDS: tuple = (
    "nome",
    "nif",
    "concelho",
    "distrito",
    "forma_juridica",
    "capital_social_eur",
    "morada",
    "atividade",
    "cae",
    "url",
    "ficha",
    "scraped_at",
    "source_id",
    "source_name",
    "localizacao",
)


def _normalize_racius_item(source: Dict[str, Any]) -> Dict[str, Any]:
    """Converte um documento do Racius num dicionário compatível com EntityItem."""
    item: Dict[str, Any] = {}
    for name in _RACIUS_ITEM_FIELDS:
        value = source.get(name)
        if value not in (None, "", [], {}):
            item[name] = value
    item["source"] = "racius"
    item["has_nif"] = bool(item.get("nif"))
    item["name"] = item.get("nome", "(sem nome)")
    item["country"] = "Portugal"
    item["country_code"] = "PT"
    item["contracts_count"] = 0
    item["as_adjudicante_count"] = 0
    item["as_adjudicatario_count"] = 0
    item["total_value"] = 0.0
    item["as_adjudicante_value"] = 0.0
    item["cae_principal"] = item.pop("cae", None)
    item["ingested_at"] = item.get("scraped_at")
    item["racius_source_id"] = item.pop("source_id", None)
    item["racius_source_name"] = item.pop("source_name", None)
    item["racius_ficha"] = item.pop("ficha", None)
    item["doc_id"] = source.get("_id") or source.get("item_id")
    return item


def _deduplicate_and_merge(
    entities: List[Dict[str, Any]],
    racius: List[Dict[str, Any]],
    *,
    prefer_racius_for_missing: bool = True,
) -> List[Dict[str, Any]]:
    """Junta entidades do cadastro com Racius, removendo duplicados por NIF.

    Estratégia:
    1. Preserva a ordem e prioridade do cadastro de entidades (elas têm dados de
       contratos públicos, mais relevantes para a plataforma).
    2. Empresas do Racius que já existem no cadastro são descartadas, a menos
       que seja para enriquecer campos vazios (ex.: CAE, morada) — isso é
       controlado por `prefer_racius_for_missing`.
    3. Empresas do Racius sem NIF ou cujo NIF não existe no cadastro são
       adicionadas no final como complemento.
    """
    seen: Dict[str, Dict[str, Any]] = {}
    result: List[Dict[str, Any]] = []

    for item in entities:
        nif = str(item.get("nif") or "").strip()
        result.append(item)
        if nif:
            seen[nif] = item

    for raw in racius:
        item = _normalize_racius_item(raw)
        nif = str(item.get("nif") or "").strip()
        if nif and nif in seen:
            if prefer_racius_for_missing:
                existing = seen[nif]
                for key in ("cae_principal", "morada", "atividade", "localizacao"):
                    if not existing.get(key) and item.get(key):
                        existing[key] = item[key]
                for racius_key in ("distrito", "concelho", "forma_juridica", "capital_social_eur"):
                    if existing.get(racius_key) is None and item.get(racius_key) is not None:
                        existing[racius_key] = item[racius_key]
                if not existing.get("url") and item.get("url"):
                    existing["url"] = item["url"]
            continue
        result.append(item)

    return result


def search_entities_with_racius(
    *,
    q: Optional[str] = None,
    country: Optional[str] = None,
    only_with_nif: Optional[bool] = None,
    min_contracts: Optional[int] = None,
    max_contracts: Optional[int] = None,
    min_value: Optional[float] = None,
    max_value: Optional[float] = None,
    role: Optional[str] = "all",
    cae: Optional[str | list[str]] = None,
    cpv: Optional[str] = None,
    sort_by: Optional[str] = "total_value",
    sort_order: Optional[str] = "desc",
    size: int = 20,
    from_: int = 0,
    racius_size: int = 50,
) -> Dict[str, Any]:
    """Pesquisa o cadastro de entidades e complementa com resultados do Racius.

    Os resultados do cadastro vêm primeiro (ordenados pelos critérios habituais).
    Empresas do Racius que não existem no cadastro são adicionadas depois,
    sem duplicar entradas por NIF.
    """
    entities = search_entities(
        q=q,
        country=country,
        only_with_nif=only_with_nif,
        min_contracts=min_contracts,
        max_contracts=max_contracts,
        min_value=min_value,
        max_value=max_value,
        role=role,
        cae=cae,
        cpv=cpv,
        sort_by=sort_by,
        sort_order=sort_order,
        size=size,
        from_=from_,
    )

    if entities.get("error"):
        return entities

    racius_items: List[Dict[str, Any]] = []
    if racius_available():
        racius_result = search_directory(
            RACIUS_INDEX,
            q=q,
            sort="relevance" if q else "recent",
            size=racius_size,
            offset=0,
            search_fields=("nome^4", "nif^2", "morada^2", "atividade", "acerca", "localizacao", "data.*"),
        )
        if not racius_result.get("error"):
            racius_items = racius_result.get("items", [])

    merged = _deduplicate_and_merge(entities.get("items", []), racius_items)

    total = len(merged)
    page = merged[from_: from_ + size]

    notes = list(entities.get("notes", []))
    racius_count = len([it for it in merged if it.get("source") == "racius"])
    if racius_count:
        notes.append(f"+{racius_count} resultado(s) do diretório Racius.")

    return {
        "query": q,
        "total": total,
        "items": page,
        "from": from_,
        "size": size,
        "notes": notes,
    }


def iter_normalized_entities(path: Optional[Path] = None) -> Iterator[Dict[str, Any]]:
    """Itera as entidades já normalizadas. Registos inválidos são ignorados."""
    target = Path(path) if path else ENTITIES_JSON
    for raw in iter_json_array(target):
        doc = normalize_entity(raw)
        if doc:
            yield doc


def count_entities(path: Optional[Path] = None) -> int:
    """Conta os registos válidos do ficheiro de entidades."""
    return sum(1 for _ in iter_normalized_entities(path))
