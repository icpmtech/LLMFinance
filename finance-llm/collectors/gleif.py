"""Recolha de dados do GLEIF — registos **LEI** (Legal Entity Identifier).

O GLEIF publica o *Golden Copy* dos registos LEI em dois formatos distintos:

* a **API oficial** (`https://api.gleif.org/api/v1/lei-records`), paginada, com
  filtros por jurisdição/país e a marca da versão do golden copy em `meta.goldenCopy`
  (é o «golden copy» servido por pedido);
* os **ficheiros Golden Copy** (`https://leidata.gleif.org/api/v1/concatenated-files/lei2`),
  ZIP de ~3,4 milhões de registos (LEI-CDF v3.1) — usados quando se quer o
  universo completo numa só passagem.

Este módulo traz as duas vias:

- :func:`fetch_from_api` — iterador de registos normalizados, por país/jurisdição
  (usado pela ingestão normal, rápida);
- :func:`iter_golden_copy_file` — iterador sobre um ficheiro local (`.zip` com
  CSV/XML, `.csv`, `.xml` ou `.jsonl`) para a ingestão em massa;
- :func:`golden_copy_urls` / :func:`download_golden_copy` — resolvem e descarregam
  o ficheiro Golden Copy mais recente.

Todos os iteradores devolvem o **mesmo documento normalizado** (ver
:func:`normalize_lei_record`), que é o que `api/gleif_service.py` guarda no
ficheiro `data/gleif/lei.jsonl` e indexa em `finance_gleif_lei`.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import re
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence

import httpx

logger = logging.getLogger(__name__)

GLEIF_API = "https://api.gleif.org/api/v1"
LEIDATA_API = "https://leidata.gleif.org/api/v1"
#: A API do GLEIF aceita no máximo 200 registos por página.
API_PAGE_SIZE = 200
#: Jurisdições recolhidas por omissão (a ingestão completa do mundo não cabe no
#: tempo de uma passagem da UI; PT é a base do módulo).
DEFAULT_COUNTRIES = ("PT",)

#: Nomes dos distritos/regiões autónomas de Portugal (ISO 3166-2:PT), para o
#: filtro e o mapa não mostrarem apenas o código.
PT_REGIONS: Dict[str, str] = {
    "PT-01": "Aveiro",
    "PT-02": "Beja",
    "PT-03": "Braga",
    "PT-04": "Bragança",
    "PT-05": "Castelo Branco",
    "PT-06": "Coimbra",
    "PT-07": "Évora",
    "PT-08": "Faro",
    "PT-09": "Guarda",
    "PT-10": "Leiria",
    "PT-11": "Lisboa",
    "PT-12": "Portalegre",
    "PT-13": "Porto",
    "PT-14": "Santarém",
    "PT-15": "Setúbal",
    "PT-16": "Viana do Castelo",
    "PT-17": "Vila Real",
    "PT-18": "Viseu",
    "PT-20": "Região Autónoma dos Açores",
    "PT-30": "Região Autónoma da Madeira",
}


def _text(value: Any) -> Optional[str]:
    """Texto limpo (sem espaços a mais) ou `None` se ficar vazio."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def fold(value: Optional[str]) -> str:
    """Minúsculas e sem acentos — usado em chaves de pesquisa e duplicados."""
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKD", value)
    stripped = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", stripped).strip().lower()


def _iso_date(value: Optional[str]) -> Optional[str]:
    """Normaliza datas do GLEIF para ISO 8601 (`2023-12-18T00:00:00Z`)."""
    text = _text(value)
    if not text:
        return None
    text = text.replace(" ", "T")
    if text.endswith("Z") or re.search(r"[+-]\d{2}:?\d{2}$", text):
        return text
    if len(text) == 10:
        return f"{text}T00:00:00Z"
    return f"{text}Z"


def normalize_lei_record(record: Dict[str, Any], *, source: str = "api") -> Optional[Dict[str, Any]]:
    """Converte um registo LEI da API do GLEIF num documento plano e indexável."""
    attributes = record.get("attributes") or record
    entity = (attributes.get("entity") or {}) if isinstance(attributes, dict) else {}
    if not entity:
        return None
    registration = attributes.get("registration") or {}

    legal_name_block = entity.get("legalName") or {}
    legal_name = _text(legal_name_block.get("name") if isinstance(legal_name_block, dict) else legal_name_block)
    lei = _text(attributes.get("lei") or record.get("id"))
    if not lei or not legal_name:
        return None

    legal_address = entity.get("legalAddress") or {}
    hq_address = entity.get("headquartersAddress") or {}
    country = _text(legal_address.get("country")) or _text(entity.get("jurisdiction"))
    region = _text(legal_address.get("region"))
    legal_form = entity.get("legalForm") or {}

    def _names(block: Any) -> List[str]:
        """Nomes alternativos (`[{name, language}]`) ou lista simples de strings."""
        if not block:
            return []
        items = block if isinstance(block, list) else [block]
        out: List[str] = []
        for item in items:
            if isinstance(item, dict):
                name = _text(item.get("name"))
            else:
                name = _text(item)
            if name and name not in out:
                out.append(name)
        return out

    def _address_lines(address: Any) -> List[str]:
        if not isinstance(address, dict):
            return []
        return [line for line in (_text(v) for v in (address.get("addressLines") or [])) if line]

    return {
        "lei": lei,
        "legal_name": legal_name,
        "legal_name_folded": fold(legal_name),
        "other_names": _names(entity.get("otherNames")),
        "transliterated_names": _names(entity.get("transliteratedOtherNames")),
        "country": country,
        "region": region,
        "region_name": PT_REGIONS.get(region or "", region),
        "city": _text(legal_address.get("city")),
        "postal_code": _text(legal_address.get("postalCode")),
        "address_lines": _address_lines(legal_address),
        "hq_country": _text(hq_address.get("country")),
        "hq_region": _text(hq_address.get("region")),
        "hq_city": _text(hq_address.get("city")),
        "jurisdiction": _text(entity.get("jurisdiction")),
        "category": _text(entity.get("category")),
        "sub_category": _text(entity.get("subCategory")),
        "legal_form": _text(legal_form.get("id")) if isinstance(legal_form, dict) else None,
        "legal_form_other": _text(legal_form.get("other")) if isinstance(legal_form, dict) else None,
        "status": _text(entity.get("status")),
        "registration_status": _text(registration.get("status")),
        "corroboration_level": _text(registration.get("corroborationLevel")),
        "conformity_flag": _text(attributes.get("conformityFlag")),
        "managing_lou": _text(registration.get("managingLou")),
        "registered_as": _text(entity.get("registeredAs")),
        "registered_at": _text((entity.get("registeredAt") or {}).get("id")) if isinstance(entity.get("registeredAt"), dict) else None,
        "validated_as": _text(registration.get("validatedAs")),
        "bic": _text(attributes.get("bic")),
        "mic": _text(attributes.get("mic")),
        "ocid": _text(attributes.get("ocid")),
        "qcc": _text(attributes.get("qcc")),
        "gem": _text(attributes.get("gem")),
        "spglobal": _text(attributes.get("spglobal")),
        "creation_date": _iso_date(entity.get("creationDate")),
        "initial_registration_date": _iso_date(registration.get("initialRegistrationDate")),
        "last_update_date": _iso_date(registration.get("lastUpdateDate")),
        "next_renewal_date": _iso_date(registration.get("nextRenewalDate")),
        "source": source,
        "ingested_at": datetime.now(timezone.utc).isoformat(),
    }


# --------------------------------------------------------------- API oficial
def fetch_from_api(
    countries: Sequence[str] = DEFAULT_COUNTRIES,
    *,
    limit: Optional[int] = None,
    page_size: int = API_PAGE_SIZE,
    timeout: float = 60.0,
    progress: Optional[Any] = None,
) -> Iterator[Dict[str, Any]]:
    """Itera os registos LEI da API do GLEIF, por país da sede legal.

    `countries` são códigos ISO 3166-1 alfa-2 (ex.: `["PT"]`). Com
    `countries=[]`/`None` percorre **todo** o universo (3,4 M de registos — muitas
    horas); use-se apenas para uma carga completa.
    """
    yielded = 0
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        targets: Sequence[Optional[str]] = list(countries) if countries else [None]
        for country in targets:
            page = 1
            while True:
                params: Dict[str, Any] = {"page[size]": page_size, "page[number]": page}
                if country:
                    params["filter[entity.legalAddress.country]"] = country
                for attempt in range(4):
                    try:
                        response = client.get(f"{GLEIF_API}/lei-records", params=params)
                        response.raise_for_status()
                        break
                    except Exception as exc:  # noqa: BLE001
                        if attempt == 3:
                            logger.warning("GLEIF API falhou (%s, página %s): %s", country, page, exc)
                            return
                        logger.info("GLEIF API tentativa %s falhou (%s): %s", attempt + 1, country, exc)
                payload = response.json()
                records = payload.get("data") or []
                if not records:
                    break
                for record in records:
                    doc = normalize_lei_record(record, source="api")
                    if not doc:
                        continue
                    yielded += 1
                    yield doc
                    if limit and yielded >= limit:
                        return
                if progress:
                    try:
                        progress(yielded)
                    except Exception:
                        pass
                pagination = (payload.get("meta") or {}).get("pagination") or {}
                if page >= int(pagination.get("lastPage") or page):
                    break
                page += 1


# ------------------------------------------------------- ficheiros Golden Copy
def golden_copy_urls(
    *, kind: str = "lei2", limit: int = 1, timeout: float = 60.0
) -> List[Dict[str, Any]]:
    """Devolve os ficheiros *Golden Copy* mais recentes publicados pelo GLEIF.

    `kind` é `lei2` (registos LEI, nível 1), `rr` (relações, nível 2) ou
    `repex` (exceções de reporte). Cada item traz `id`, `content_date`,
    `record_count`, `file` (URL do ZIP) e `filesize`.
    """
    listing_url = f"{LEIDATA_API}/concatenated-files/{kind}"
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        response = client.get(listing_url)
        response.raise_for_status()
        payload = response.json()
    items = payload.get("data") or []
    return items[: max(1, limit)]


def download_golden_copy(dest: Path, *, kind: str = "lei2", index: int = 0, timeout: float = 900.0) -> Path:
    """Descarrega o ficheiro Golden Copy (`kind`) para `dest` e devolve o caminho.

    O ficheiro é grande (LEI2 ≈ 540 MB); a escrita é feita em blocos para não
    carregar tudo em memória.
    """
    items = golden_copy_urls(kind=kind, limit=index + 1)
    if len(items) <= index:
        raise RuntimeError(f"Golden copy «{kind}» indisponível (índice {index}).")
    item = items[index]
    url = item["file"]
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    logger.info("Golden copy %s: %s (%s bytes)", kind, url, item.get("filesize"))
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        with client.stream("GET", url) as response:
            response.raise_for_status()
            with tmp.open("wb") as handle:
                for chunk in response.iter_bytes(chunk_size=1024 * 1024):
                    handle.write(chunk)
    tmp.replace(dest)
    return dest


# Aliases das colunas do LEI-CDF (o CSV do GLEIF não é estável entre versões,
# pelo que se procura por subcadeia, não por nome exato).
_CSV_ALIASES: Dict[str, Sequence[str]] = {
    "legal_name": ("entity.legalname", "legalname", "legal name"),
    "other_names": ("entity.otherentitynames", "otherentitynames", "other entity names"),
    "transliterated_names": ("entity.transliteratedothernames",),
    "address_lines": ("entity.legaladdress.firstaddressline", "legaladdress.firstaddressline"),
    "city": ("entity.legaladdress.city", "legaladdress.city"),
    "region": ("entity.legaladdress.region", "legaladdress.region"),
    "country": ("entity.legaladdress.country", "legaladdress.country"),
    "postal_code": ("entity.legaladdress.postalcode", "legaladdress.postalcode"),
    "hq_city": ("entity.headquartersaddress.city", "headquartersaddress.city"),
    "hq_region": ("entity.headquartersaddress.region",),
    "hq_country": ("entity.headquartersaddress.country",),
    "jurisdiction": ("entity.legaljurisdiction", "legaljurisdiction"),
    "category": ("entity.entitycategory", "entitycategory"),
    "sub_category": ("entity.entitysubcategory", "entitysubcategory"),
    "legal_form": ("entity.legalform", "legalform"),
    "status": ("entity.entitystatus", "entitystatus"),
    "creation_date": ("entity.entitycreationdate", "entitycreationdate"),
    "registered_as": ("entity.registrationauthority.registrationauthorityentityid", "registeredas"),
    "registered_at": ("entity.registrationauthority.registrationauthorityid", "registeredat"),
    "initial_registration_date": ("registration.initialregistrationdate",),
    "last_update_date": ("registration.lastupdatedate",),
    "registration_status": ("registration.registrationstatus",),
    "next_renewal_date": ("registration.nextrenewaldate",),
    "managing_lou": ("registration.managinglou",),
    "corroboration_level": ("registration.corroborationlevel",),
    "validated_as": ("registration.validationauthority.registrationauthorityentityid",),
    "bic": ("bic",),
    "mic": ("mic",),
    "ocid": ("ocid",),
    "qcc": ("qcc",),
    "gem": ("gem",),
    "spglobal": ("spglobal",),
}

_CSV_ALIAS_RANGES: Dict[str, Sequence[str]] = {
    # Várias linhas de endereço: o CSV usa FirstAddressLine/AdditionalAddressLine.N.
    "address_extra": ("additionaladdressline",),
}


def _match_columns(header: Sequence[str]) -> Dict[str, List[str]]:
    """Mapeia cada campo normalizado para as colunas do CSV que o alimentam."""
    normalized = {fold(h.replace("_", ".")): h for h in header}
    resolved: Dict[str, List[str]] = {}
    for field, aliases in _CSV_ALIASES.items():
        matches = [column for key, column in normalized.items() if any(alias in key for alias in aliases)]
        if matches:
            resolved[field] = matches
    for field, aliases in _CSV_ALIAS_RANGES.items():
        matches = [column for key, column in normalized.items() if any(alias in key for alias in aliases)]
        if matches:
            resolved[field] = matches
    return resolved


def _normalize_from_csv_rows(row: Dict[str, str], columns: Dict[str, List[str]], source: str) -> Optional[Dict[str, Any]]:
    """Converte uma linha do CSV do LEI-CDF num documento (ainda por finalizar)."""
    doc: Dict[str, Any] = {"lei": _text(row.get("LEI") or row.get("lei")), "source": source}
    for field, cols in columns.items():
        if field == "address_extra":
            continue
        value = next((_text(row.get(col)) for col in cols if _text(row.get(col))), None)
        if value:
            doc[field] = value
    extra = [v for col in columns.get("address_extra", []) if (v := _text(row.get(col)))]
    lines = [v for v in [doc.get("address_lines")] if v] + extra
    if lines:
        doc["address_lines"] = lines
    if not doc.get("legal_name") or not doc.get("lei"):
        return None
    return doc


def _finalize_golden_doc(doc: Dict[str, Any], source: str) -> Optional[Dict[str, Any]]:
    """Completa os campos derivados de um documento lido de ficheiro."""
    legal_name = _text(doc.get("legal_name"))
    lei = _text(doc.get("lei"))
    if not legal_name or not lei:
        return None

    def _split(value: Any) -> List[str]:
        text = _text(value)
        if not text:
            return []
        parts = [p.strip() for p in re.split(r"[|;]\s*", text) if p.strip()]
        return parts

    region = _text(doc.get("region"))
    out: Dict[str, Any] = {
        "lei": lei,
        "legal_name": legal_name,
        "legal_name_folded": fold(legal_name),
        "other_names": _split(doc.get("other_names")),
        "transliterated_names": _split(doc.get("transliterated_names")),
        "country": _text(doc.get("country")) or _text(doc.get("jurisdiction")),
        "region": region,
        "region_name": PT_REGIONS.get(region or "", region),
        "city": _text(doc.get("city")),
        "postal_code": _text(doc.get("postal_code")),
        "address_lines": doc.get("address_lines") or [],
        "hq_country": _text(doc.get("hq_country")),
        "hq_region": _text(doc.get("hq_region")),
        "hq_city": _text(doc.get("hq_city")),
        "jurisdiction": _text(doc.get("jurisdiction")),
        "category": _text(doc.get("category")),
        "sub_category": _text(doc.get("sub_category")),
        "legal_form": _text(doc.get("legal_form")),
        "legal_form_other": _text(doc.get("legal_form_other")),
        "status": _text(doc.get("status")),
        "registration_status": _text(doc.get("registration_status")),
        "corroboration_level": _text(doc.get("corroboration_level")),
        "conformity_flag": _text(doc.get("conformity_flag")),
        "managing_lou": _text(doc.get("managing_lou")),
        "registered_as": _text(doc.get("registered_as")),
        "registered_at": _text(doc.get("registered_at")),
        "validated_as": _text(doc.get("validated_as")),
        "bic": _text(doc.get("bic")),
        "mic": _text(doc.get("mic")),
        "ocid": _text(doc.get("ocid")),
        "qcc": _text(doc.get("qcc")),
        "gem": _text(doc.get("gem")),
        "spglobal": _text(doc.get("spglobal")),
        "creation_date": _iso_date(doc.get("creation_date")),
        "initial_registration_date": _iso_date(doc.get("initial_registration_date")),
        "last_update_date": _iso_date(doc.get("last_update_date")),
        "next_renewal_date": _iso_date(doc.get("next_renewal_date")),
        "source": source,
        "ingested_at": datetime.now(timezone.utc).isoformat(),
    }
    return out


def _iter_csv(handle: io.TextIOBase, source: str) -> Iterator[Dict[str, Any]]:
    """Itera um CSV do LEI-CDF (a primeira linha é o cabeçalho)."""
    reader = csv.DictReader(handle)
    if not reader.fieldnames:
        return
    columns = _match_columns([c for c in reader.fieldnames if c])
    for row in reader:
        doc = _normalize_from_csv_rows(row, columns, source)
        if doc:
            final = _finalize_golden_doc(doc, source)
            if final:
                yield final


def _strip_ns(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _iter_xml(handle: io.TextIOBase, source: str) -> Iterator[Dict[str, Any]]:
    """Itera um XML do LEI-CDF (`<LEIHeader>` ou `<LEIRecords>` com `<LEIRecord>`)."""
    context = ET.iterparse(handle, events=("end",))
    for _event, element in context:
        if _strip_ns(element.tag) not in {"LEIRecord", "LEIRecordData"}:
            continue
        doc = normalize_lei_record({"id": None, "attributes": _xml_record_to_dict(element)}, source=source)
        element.clear()
        if doc:
            yield doc
        else:
            # Sem nome/LEI no formato esperado: tentar o mapeamento dos filhos diretos.
            raw = {_strip_ns(child.tag): (child.text or "").strip() for child in element.iter() if child.text}
            alias_doc = {fold(k): v for k, v in raw.items()}
            fallback = _finalize_golden_doc(_alias_lookup(alias_doc), source)
            if fallback:
                yield fallback


def _alias_lookup(values: Dict[str, str]) -> Dict[str, Any]:
    """Procura os campos normalizados num dicionário achatado (chaves já sem acentos)."""
    out: Dict[str, Any] = {"lei": values.get("lei")}
    for field, aliases in _CSV_ALIASES.items():
        for key, value in values.items():
            if any(alias in key for alias in aliases):
                out[field] = value
                break
    return out


def _xml_record_to_dict(element: ET.Element) -> Dict[str, Any]:
    """Achata um `<LEIRecord>` do LEI-CDF numa estrutura equivalente à da API."""
    flat: Dict[str, str] = {}
    for child in element.iter():
        name = _strip_ns(child.tag)
        if child is element or child.text is None:
            continue
        text = (child.text or "").strip()
        if not text:
            continue
        flat.setdefault(name, text)
        flat.setdefault(name.lower(), text)

    def get(*names: str) -> Optional[str]:
        for name in names:
            if flat.get(name):
                return flat[name]
        for key, value in flat.items():
            if any(name.lower() in key for name in names):
                return value
        return None

    def get_all(*names: str) -> List[str]:
        out: List[str] = []
        for name in names:
            for key, value in flat.items():
                if name.lower() in key and value not in out:
                    out.append(value)
        return out

    return {
        "lei": get("LEI"),
        "entity": {
            "legalName": {"name": get("LegalName")},
            "otherNames": [{"name": n} for n in get_all("OtherEntityName")],
            "transliteratedOtherNames": [{"name": n} for n in get_all("TransliteratedOtherEntityName")],
            "legalAddress": {
                "addressLines": get_all("FirstAddressLine", "AdditionalAddressLine"),
                "city": get("City"),
                "region": get("Region"),
                "country": get("Country"),
                "postalCode": get("PostalCode"),
            },
            "headquartersAddress": {
                "city": get("RegistrationAuthorityEntityID") or None,
            },
            "legalJurisdiction": get("LegalJurisdiction"),
            "category": get("EntityCategory"),
            "subCategory": get("EntitySubCategory"),
            "legalForm": {"id": get("LegalForm")},
            "status": get("EntityStatus"),
            "creationDate": get("EntityCreationDate"),
            "registeredAs": get("RegistrationAuthorityEntityID"),
            "registeredAt": {"id": get("RegistrationAuthorityID")},
        },
        "registration": {
            "initialRegistrationDate": get("InitialRegistrationDate"),
            "lastUpdateDate": get("LastUpdateDate"),
            "status": get("RegistrationStatus"),
            "nextRenewalDate": get("NextRenewalDate"),
            "managingLou": get("ManagingLOU"),
            "corroborationLevel": get("CorroborationLevel"),
            "validatedAs": get("ValidationAuthorityEntityID"),
        },
        "conformityFlag": get("ConformityFlag"),
        "bic": get("BIC"),
        "mic": get("MIC"),
        "ocid": get("OCID"),
        "qcc": get("QCC"),
        "gem": get("GEM"),
        "spglobal": get("SPGlobal"),
    }


def iter_golden_copy_file(path: Path, *, source: str = "golden-copy") -> Iterator[Dict[str, Any]]:
    """Itera os registos de um ficheiro Golden Copy local.

    Aceita `.zip` (com CSV ou XML do LEI-CDF), `.csv`, `.xml`, `.json`/`.jsonl`
    (a resposta da API, item a item ou uma lista).
    """
    path = Path(path)
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            csv_name = next((n for n in names if n.lower().endswith(".csv")), None)
            xml_name = next((n for n in names if n.lower().endswith(".xml")), None)
            target = csv_name or xml_name
            if not target:
                raise RuntimeError(f"ZIP sem CSV/XML do LEI-CDF: {names[:5]}")
            with archive.open(target) as raw:
                handle = io.TextIOWrapper(raw, encoding="utf-8-sig", errors="replace")
                yield from (_iter_csv(handle, source) if target.lower().endswith(".csv") else _iter_xml(handle, source))
            return

    suffix = path.suffix.lower()
    if suffix in {".json", ".jsonl"}:
        with path.open("r", encoding="utf-8") as handle:
            if suffix == ".jsonl":
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    doc = normalize_lei_record(json.loads(line), source=source)
                    if doc:
                        yield doc
            else:
                payload = json.load(handle)
                records = payload.get("data") if isinstance(payload, dict) else payload
                for record in records or []:
                    doc = normalize_lei_record(record, source=source)
                    if doc:
                        yield doc
        return

    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        if suffix == ".xml":
            yield from _iter_xml(handle, source)
        else:
            yield from _iter_csv(handle, source)
