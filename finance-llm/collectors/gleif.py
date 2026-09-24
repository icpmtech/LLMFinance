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
from typing import Any, Dict, Iterator, List, Optional, Sequence

import httpx

logger = logging.getLogger(__name__)

GLEIF_API = "https://api.gleif.org/api/v1"
LEIDATA_API = "https://leidata.gleif.org/api/v1"
#: Tag de abertura de um registo do LEI-CDF no XML, com o prefixo de namespace
#: opcional (`<lei:LEIRecord>` no ficheiro publicado pelo GLEIF). O grupo 1 é o
#: prefixo, para que o tag de fecho seja procurado com o mesmo prefixo.
_RECORD_OPEN_RE = re.compile(r"<([A-Za-z0-9_.-]*:)?(?:LEIRecordData|LEIRecord)(?:\s[^>]*)?>")
#: A API oficial não permite paginação profunda além de 10 000 resultados
#: (`page[number] * page[size] <= 10000`). Acima disso é preciso o ficheiro
#: Golden Copy, que não tem esse limite.
API_MAX_RESULTS = 10000
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
                # Paginação profunda não é suportada: parar antes do limite em vez
                # de esperar por um 400. Para o universo completo existe o ficheiro
                # Golden Copy (`iter_golden_copy_file`).
                if (page - 1) * page_size >= API_MAX_RESULTS:
                    logger.info(
                        "GLEIF API: limite de %s resultados atingido (%s) — use a origem «golden-copy» para o total.",
                        API_MAX_RESULTS,
                        country or "global",
                    )
                    break
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
    "lei": ("lei",),
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


def _column_indexes(header: Sequence[str]) -> Dict[str, List[int]]:
    """Mapeia cada campo normalizado para as **posições** das colunas do CSV.

    Trabalha com índices (e não com nomes) porque a golden copy tem ~3,4 milhões
    de linhas e uma busca por nome em cada linha seria o principal custo da
    ingestão. O CSV do GLEIF também não é estável entre versões, pelo que se
    procura por subcadeia e não por nome exato.
    """
    normalized = [fold(column.replace("_", ".")) for column in header]
    resolved: Dict[str, List[int]] = {}
    for field, aliases in {**_CSV_ALIASES, **_CSV_ALIAS_RANGES}.items():
        positions = [index for index, key in enumerate(normalized) if any(alias in key for alias in aliases)]
        if positions:
            resolved[field] = positions
    return resolved


def _first_value(row: Sequence[str], positions: Sequence[int]) -> Optional[str]:
    """Primeiro valor não vazio de uma lista de posições da linha."""
    for index in positions:
        if index < len(row):
            value = row[index].strip()
            if value:
                return value
    return None


def _csv_row_to_doc(row: Sequence[str], indexes: Dict[str, List[int]], source: str) -> Optional[Dict[str, Any]]:
    """Converte uma linha de CSV (por índices) num documento por finalizar."""
    if not row:
        return None
    doc: Dict[str, Any] = {"lei": _first_value(row, indexes.get("lei", []))}
    if not doc["lei"]:
        return None
    for field, positions in indexes.items():
        if field in {"lei", "address_extra"}:
            continue
        value = _first_value(row, positions)
        if value:
            doc[field] = value
    extras = [value for index in indexes.get("address_extra", []) if index < len(row) and (value := row[index].strip())]
    lines = [doc["address_lines"]] if doc.get("address_lines") else []
    lines.extend(extras)
    if lines:
        doc["address_lines"] = lines
    if not doc.get("legal_name"):
        return None
    doc["source"] = source
    return doc


def _iter_csv(handle: io.TextIOBase, source: str, countries: Optional[Sequence[str]] = None) -> Iterator[Dict[str, Any]]:
    """Itera um CSV do LEI-CDF (a primeira linha é o cabeçalho).

    O filtro por país é aplicado **antes** de construir o documento: na golden
    copy completa a maioria das linhas não interessa e construir o `dict` de 40
    campos para todas elas era o grosso do tempo de ingestão.
    """
    reader = csv.reader(handle)
    try:
        header = next(reader)
    except StopIteration:
        return
    indexes = _column_indexes(header)
    country_positions = [*indexes.get("country", []), *indexes.get("jurisdiction", [])]
    wanted = {code.strip().upper() for code in (countries or []) if code and code.strip()}
    for row in reader:
        if wanted and country_positions:
            country = _first_value(row, country_positions)
            if not country or country.upper() not in wanted:
                continue
        doc = _csv_row_to_doc(row, indexes, source)
        if not doc:
            continue
        final = _finalize_golden_doc(doc, source)
        if final:
            yield final



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


def _xml_country(element: ET.Element) -> Optional[str]:
    """País do endereço da sede legal dentro de um `<LEIRecord>` (leitura leve).

    Serve só para decidir se o registo interessa: evitar construir o
    dicionário achatado dos ~3,4 M de registos que não são pedidos é o que
    torna a ingestão do ficheiro Golden Copy viável.
    """
    for child in element.iter():
        if _strip_ns(child.tag) == "Country" and child.text:
            return child.text.strip()
    return None


def _iter_xml(
    handle: io.TextIOBase,
    source: str,
    countries: Optional[Sequence[str]] = None,
) -> Iterator[Dict[str, Any]]:
    """Itera um XML do LEI-CDF (`<lei:LEIRecord>`), opcionalmente filtrado por país.

    O XML do Golden Copy tem ~8,4 GB. Em vez de `ElementTree.iterparse` — que ou
    acumula 3,4 milhões de nós vazios na árvore (memória a crescer e leitura a
    degradar-se) ou obriga a gerir a pilha de elementos a cada evento (600 M de
    eventos) — o ficheiro é lido em blocos de 4 MB e cada registo é recortado
    pelo seu tag de abertura/fecho (com o prefixo de namespace que o ficheiro
    usar, tipicamente `lei:`) e interpretado isoladamente com `ET.fromstring`:
    memória constante e o custo fica na busca de subcadeias, que corre em C.
    """
    wanted = {code.strip().upper() for code in (countries or []) if code and code.strip()}
    # Pré-filtro barato: um bloco sem `>PT<`/`>ES<` nunca tem a sede legal num
    # país pedido, pelo que não vale a pena interpretar o XML (94% dos registos
    # da golden copy completa ficam de fora). O filtro exato por campo continua a
    # ser aplicado depois, se este passar.
    hint = re.compile(">\\s*(" + "|".join(sorted(wanted)) + ")\\s*<", re.IGNORECASE) if wanted else None
    buffer = ""
    pos = 0
    while True:
        chunk = handle.read(4 * 1024 * 1024)
        if chunk:
            if pos:
                buffer = buffer[pos:]
                pos = 0
            buffer += chunk
        while True:
            opening = _RECORD_OPEN_RE.search(buffer, pos)
            if not opening:
                # Sem registo a começar: descarta tudo menos a cauda (o tag pode
                # estar dividido entre dois blocos). É assim que o cabeçalho do
                # ficheiro (com a lista de LOUs) sai sem custo.
                if len(buffer) - pos > 4096:
                    buffer = buffer[-64:]
                    pos = 0
                break
            tag = opening.group(0)
            prefix = opening.group(1) or ""
            name = "LEIRecordData" if "LEIRecordData" in tag else "LEIRecord"
            closing = f"</{prefix}{name}>"
            end = buffer.find(closing, opening.end())
            if end < 0:
                # Registo incompleto: descarta o que está antes e espera pelo resto.
                if opening.start() > pos:
                    buffer = buffer[opening.start() :]
                    pos = 0
                break
            block = buffer[opening.start() : end + len(closing)]
            pos = end + len(closing)
            if hint is not None and not hint.search(block):
                continue
            try:
                element = ET.fromstring(block)
            except ET.ParseError:
                continue
            if wanted and (_xml_country(element) or "").upper() not in wanted:
                continue
            doc = normalize_lei_record({"id": None, "attributes": _xml_record_to_dict(element)}, source=source)
            if doc:
                yield doc
                continue
            # Formato inesperado: cair no mapeamento dos filhos diretos.
            raw = {_strip_ns(child.tag): (child.text or "").strip() for child in element.iter() if child.text}
            fallback = _finalize_golden_doc(_alias_lookup({fold(k): v for k, v in raw.items()}), source)
            if fallback:
                yield fallback
        if not chunk:
            break


def _alias_lookup(values: Dict[str, str]) -> Dict[str, Any]:
    """Procura os campos normalizados num dicionário achatado (chaves já sem acentos)."""
    out: Dict[str, Any] = {"lei": values.get("lei")}
    for field, aliases in _CSV_ALIASES.items():
        for key, value in values.items():
            if any(alias in key for alias in aliases):
                out[field] = value
                break
    return out


def _child(element: Optional[ET.Element], *path: str) -> Optional[ET.Element]:
    """Desce por uma sequência de nomes de elementos (sem o namespace)."""
    current = element
    for name in path:
        if current is None:
            return None
        current = next((child for child in current if _strip_ns(child.tag) == name), None)
    return current


def _child_text(element: Optional[ET.Element], *path: str) -> Optional[str]:
    """Texto do elemento no caminho indicado (ou `None` se não existir/vazio)."""
    node = _child(element, *path)
    if node is None or not node.text:
        return None
    return node.text.strip() or None


def _address(element: Optional[ET.Element]) -> Dict[str, Any]:
    """Endereço de um `<LegalAddress>`/`<HeadquartersAddress>` do LEI-CDF."""
    if element is None:
        return {}
    lines = [
        child.text.strip()
        for child in element
        if _strip_ns(child.tag) in {"FirstAddressLine", "AdditionalAddressLine"} and child.text and child.text.strip()
    ]
    return {
        "addressLines": lines,
        "city": _child_text(element, "City"),
        "region": _child_text(element, "Region"),
        "country": _child_text(element, "Country"),
        "postalCode": _child_text(element, "PostalCode"),
    }


def _xml_record_to_dict(element: ET.Element) -> Dict[str, Any]:
    """Converte um `<LEIRecord>` do LEI-CDF na estrutura equivalente à da API do GLEIF.

    Percorre o caminho dos elementos (e não um dicionário achatado) porque o
    LEI-CDF tem blocos com os mesmos nomes em sítios diferentes — `City` existe
    tanto no endereço da sede legal como no da sede operacional, e o nível de
    corroboração chama-se `ValidationSources` no XML (a API do GLEIF expõe-o
    como `corroborationLevel`).
    """
    entity = _child(element, "Entity")
    registration = _child(element, "Registration")
    legal_address = _child(entity, "LegalAddress")
    headquarters = _child(entity, "HeadquartersAddress")
    authority = _child(entity, "RegistrationAuthority")
    legal_form = _child(entity, "LegalForm")
    validation = _child(registration, "ValidationAuthority")
    conformity = _child(element, "Extension", "ConformityFlag")

    def names(container: Optional[ET.Element], tag: str) -> List[str]:
        """Nomes alternativos (um ou vários elementos `<…Name>` com o mesmo tag)."""
        if container is None:
            return []
        out: List[str] = []
        for child in container:
            if _strip_ns(child.tag) == tag and child.text and child.text.strip() and child.text.strip() not in out:
                out.append(child.text.strip())
        return out

    return {
        "lei": _child_text(element, "LEI"),
        "entity": {
            "legalName": {"name": _child_text(entity, "LegalName")},
            "otherNames": [{"name": name} for name in names(entity, "OtherEntityName")],
            "transliteratedOtherNames": [{"name": name} for name in names(entity, "TransliteratedOtherEntityName")],
            "legalAddress": _address(legal_address),
            "headquartersAddress": _address(headquarters),
            "registeredAt": {"id": _child_text(authority, "RegistrationAuthorityID")},
            "registeredAs": _child_text(authority, "RegistrationAuthorityEntityID"),
            "jurisdiction": _child_text(entity, "LegalJurisdiction"),
            "category": _child_text(entity, "EntityCategory"),
            "subCategory": _child_text(entity, "EntitySubCategory"),
            "legalForm": {
                "id": _child_text(legal_form, "EntityLegalFormCode") or (legal_form.text or "").strip() or None,
                "other": _child_text(legal_form, "OtherLegalForm"),
            },
            "status": _child_text(entity, "EntityStatus"),
            "creationDate": _child_text(entity, "EntityCreationDate"),
        },
        "registration": {
            "initialRegistrationDate": _child_text(registration, "InitialRegistrationDate"),
            "lastUpdateDate": _child_text(registration, "LastUpdateDate"),
            "status": _child_text(registration, "RegistrationStatus"),
            "nextRenewalDate": _child_text(registration, "NextRenewalDate"),
            "managingLou": _child_text(registration, "ManagingLOU"),
            # No LEI-CDF o nível de corroboração chama-se `ValidationSources`.
            "corroborationLevel": _child_text(registration, "ValidationSources"),
            "validatedAt": {"id": _child_text(validation, "ValidationAuthorityID")},
            "validatedAs": _child_text(validation, "ValidationAuthorityEntityID"),
        },
        "conformityFlag": _child_text(conformity) or _child_text(element, "Extension", "ConformityFlag"),
    }


def iter_golden_copy_file(
    path: Path,
    *,
    source: str = "golden-copy",
    countries: Optional[Sequence[str]] = None,
) -> Iterator[Dict[str, Any]]:
    """Itera os registos de um ficheiro Golden Copy local, opcionalmente filtrados por país.

    `countries` (ISO 3166-1 alfa-2) é aplicado durante a leitura do CSV — evita
    construir os ~3,4 M de documentos quando só se quer uma parte.

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
                if target.lower().endswith(".csv"):
                    yield from _iter_csv(handle, source, countries)
                else:
                    yield from _iter_xml(handle, source, countries)
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
            yield from _iter_xml(handle, source, countries)
        else:
            yield from _iter_csv(handle, source, countries)
