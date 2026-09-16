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
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

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
        "source": "entidades_gov_portal_base",
    }
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
