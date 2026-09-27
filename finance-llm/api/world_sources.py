"""Camada «Public Data» do World Model — leitura dos dados públicos do IQ OS.

O World Model não tem recolha própria: alimenta-se dos índices que a plataforma
já mantém a partir das fontes públicas. Este módulo é o **adaptador** entre
esses índices e a representação normalizada que o `world_model` consome:

======================  =======================================================
Fonte                   O que dá ao World Model
======================  =======================================================
`contratos`             Contratos públicos PT: adjudicantes, adjudicatários,
                        valor, CPV, datas (nested `*.parsed`).
`contratos_es`          Contratos públicos de Espanha (PLACSP): órgão,
                        adjudicatário, valor, CPV, datas (campos planos).
`finance_entities`      Cadastro de entidades do Portal BASE (designações).
`finance_cire`          Insolvências / revitalizações (evento de insolvência).
`finance_people`        Pessoas e cargos (relações pessoa→empresa).
`finance_contribuintes` Agregado por NIF/NIPC (designação canónica e país).
======================  =======================================================

Duas formas de leitura, ambas **limitadas** (o World Model é um modelo, não uma
cópia dos dados):

- **Agregações** (`terms` sobre os NIF das partes) — dão contagens e somas
  exatas por entidade, com um teto (`limit`) nas entidades consideradas;
- **Amostra de documentos** (`contract_sample`) — dá os pares
  adjudicante↔adjudicatário, o valor e as datas que alimentam as **relações** e
  os **eventos**. Sem a amostra não haveria arestas para o grafo.

Todas as leituras degradam em silêncio (lista vazia) se o Elasticsearch estiver
indisponível ou o índice não existir/falhar, para nunca bloquear a
reconstrução do mundo.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

from elasticsearch import Elasticsearch

from api.elasticsearch_client import (
    CIRE_INDEX,
    CONTRATOS_ES_INDEX,
    CONTRACTS_INDEX,
    CONTRIBUINTES_INDEX,
    ENTITIES_INDEX,
    FIRMAS_INDEX,
    GLEIF_LEI_INDEX,
    PEOPLE_INDEX,
    SCRAPED_INDEX,
    SOCIAL_INDEX,
    SOCIETARIO_INDEX,
    TRADEMARKS_INDEX,
    get_es_client,
)

logger = logging.getLogger(__name__)

#: Fontes públicas que alimentam o World Model (catálogo para a UI).
#:
#: Cada fonte declara **como entra** no mundo — o `adapter` diz o que se extrai
#: dela e o `join` diz como se liga às entidades já conhecidas:
#:
#: - `join: "nif"` — junção exata pelo NIF/NIPC (a mais fiável);
#: - `join: "nome"` — junção por designação normalizada (só quando a fonte não
#:   tem NIF, ex.: GLEIF);
#: - `join: "texto"` — o nome da entidade aparece no texto (menções sociais).
#:
#: `default: True` marca as fontes que a reconstrução usa **por omissão**; as
#: restantes são associáveis (`associable`), ie. o utilizador liga-as quando
#: quiser — e passam a constar do pipeline e da reconstrução.
SOURCES: List[Dict[str, Any]] = [
    {
        "id": "contratos",
        "label": "Contratos Públicos (PT)",
        "index": CONTRACTS_INDEX,
        "country": "Portugal",
        "kind": "contratos",
        "adapter": "contratos",
        "join": "nif",
        "contributes": ["entidades", "relações", "eventos", "métricas", "histórico"],
        "default": True,
        "associable": False,
        "description": "Portal BASE: adjudicantes, adjudicatários, valor, CPV e datas.",
    },
    {
        "id": "contratos_es",
        "label": "Contratos Públicos (ES)",
        "index": CONTRATOS_ES_INDEX,
        "country": "Espanha",
        "kind": "contratos",
        "adapter": "contratos_es",
        "join": "nif",
        "contributes": ["entidades", "relações", "eventos", "métricas", "histórico"],
        "default": True,
        "associable": True,
        "description": "PLACSP: órgão de contratação, adjudicatário, valor e estado.",
    },
    {
        "id": "cire",
        "label": "Insolvências (CIRE)",
        "index": CIRE_INDEX,
        "country": "Portugal",
        "kind": "insolvencias",
        "adapter": "insolvencias",
        "join": "nif",
        "contributes": ["eventos", "sinal de risco"],
        "default": True,
        "associable": True,
        "description": "Publicidade do PER/PEAP/PEVE e insolvências (intervenientes).",
    },
    {
        "id": "pessoas",
        "label": "Pessoas e Cargos",
        "index": PEOPLE_INDEX,
        "country": "Portugal",
        "kind": "pessoas",
        "adapter": "pessoas",
        "join": "nif",
        "contributes": ["relações (cargos)", "eventos"],
        "default": True,
        "associable": True,
        "description": "Pessoas e cargos extraídos das publicações societárias.",
    },
    {
        "id": "contribuintes",
        "label": "Contribuintes (designação canónica)",
        "index": CONTRIBUINTES_INDEX,
        "country": "Portugal",
        "kind": "contribuintes",
        "adapter": "registo",
        "join": "nif",
        "contributes": ["nome canónico", "tipo", "país"],
        "default": False,
        "associable": True,
        "description": "Agregado por NIF/NIPC: nome, tipo (empresa/particular) e país. Corrige designações divergentes.",
    },
    {
        "id": "entidades",
        "label": "Entidades Públicas",
        "index": ENTITIES_INDEX,
        "country": "Portugal",
        "kind": "entidades",
        "adapter": "registo",
        "join": "nif",
        "contributes": ["entidades públicas", "nome", "país"],
        "default": False,
        "associable": True,
        "description": "Cadastro de entidades (designações e volumetria) — acrescenta organismos sem contratos na amostra.",
    },
    {
        "id": "gleif",
        "label": "GLEIF LEI",
        "index": GLEIF_LEI_INDEX,
        "country": "Internacional",
        "kind": "registo",
        "adapter": "registo",
        "join": "nome",
        "join_field": "legal_name_folded",
        "contributes": ["identificador LEI", "país", "forma jurídica"],
        "default": False,
        "associable": True,
        "description": "Registo oficial global: liga a entidade ao LEI por designação legal exata (a fonte não tem NIF).",
    },
    {
        "id": "societario",
        "label": "Publicações Societárias (MJ)",
        "index": SOCIETARIO_INDEX,
        "country": "Portugal",
        "kind": "publicacoes",
        "adapter": "publicacoes",
        "join": "nif",
        "contributes": ["eventos (actos societários)", "firma"],
        "default": False,
        "associable": True,
        "description": "Publicações do Ministério da Justiça: constituição, alterações, capital e gerência.",
    },
    {
        "id": "marcas",
        "label": "Marcas (INPI)",
        "index": TRADEMARKS_INDEX,
        "country": "Portugal",
        "kind": "propriedade",
        "adapter": "propriedade",
        "join": "nif",
        "contributes": ["eventos (marcas)", "relações titular↔empresa"],
        "default": False,
        "associable": True,
        "description": "Marcas registadas por NIF: nome, tipo, fases e datas.",
    },
    {
        "id": "firmas",
        "label": "Firmas / CAE",
        "index": FIRMAS_INDEX,
        "country": "Portugal",
        "kind": "propriedade",
        "adapter": "propriedade",
        "join": "nif",
        "contributes": ["métricas (CAE, situação)"],
        "default": False,
        "associable": True,
        "description": "Firmas com CAE principal e situação declarada.",
    },
    {
        "id": "sociais",
        "label": "Menções sociais",
        "index": SOCIAL_INDEX,
        "country": "Internacional",
        "kind": "mencoes",
        "adapter": "mencoes",
        "join": "nif",
        "contributes": ["eventos (menções)", "sentimento"],
        "default": False,
        "associable": True,
        "description": "Publicações em redes sociais ligadas a pessoas/entidades por NIF, com sentimento.",
    },
    {
        "id": "recolha",
        "label": "Recolha de imprensa",
        "index": SCRAPED_INDEX,
        "country": "Internacional",
        "kind": "mencoes",
        "adapter": "mencoes",
        "join": "texto",
        "contributes": ["eventos (menções na imprensa)", "sentimento"],
        "default": False,
        "associable": True,
        "description": "Notícias recolhidas: liga-se à entidade quando o nome aparece no título (sem NIF na fonte).",
    },
]

SOURCE_BY_ID = {source["id"]: source for source in SOURCES}

#: Fontes associadas por omissão (as que garantem o núcleo do mundo).
DEFAULT_SOURCE_IDS: List[str] = [source["id"] for source in SOURCES if source.get("default")]

#: Fontes que não podem ser desligadas: sem contratos não há mundo.
REQUIRED_SOURCE_IDS: List[str] = ["contratos"]

#: Campos das partes nos contratos PT (nested) e de valor/data/CPV.
_PT_PARTY_PATH = {"adjudicante": "adjudicantes.parsed", "adjudicatario": "adjudicatarios.parsed"}
_PT_VALUE_FIELD = "precoContratual"
_PT_DATE_FIELDS = ("dataCelebracaoContrato", "dataDecisaoAdjudicacao", "dataPublicacao")


def default_client(es: Optional[Elasticsearch] = None) -> Optional[Elasticsearch]:
    """Cliente Elasticsearch (o passado ou um novo), ou ``None``."""
    return es or get_es_client()


# ---------------------------------------------------------------------------
# Disponibilidade das fontes
# ---------------------------------------------------------------------------
def availability(es: Optional[Elasticsearch] = None) -> List[Dict[str, Any]]:
    """Estado de cada fonte pública: índice, nº de documentos e se existe."""
    client = default_client(es)
    result: List[Dict[str, Any]] = []
    for source in SOURCES:
        entry = dict(source)
        entry["exists"] = False
        entry["documents"] = 0
        if client is not None:
            try:
                if client.indices.exists(index=source["index"]):
                    entry["exists"] = True
                    entry["documents"] = int(client.count(index=source["index"])["count"])
            except Exception as exc:  # pragma: no cover - depende do cluster
                entry["error"] = str(exc)[:200]
        result.append(entry)
    return result


def sources_by_ids(ids: Optional[Iterable[str]]) -> List[Dict[str, Any]]:
    """Catálogo das fontes pedidas, pela ordem do catálogo (ignora ids inválidos)."""
    wanted = {str(item).strip() for item in (ids or []) if str(item).strip()}
    return [source for source in SOURCES if source["id"] in wanted]


def normalize_source_ids(ids: Optional[Iterable[str]]) -> List[str]:
    """Valida e ordena uma lista de fontes associadas (garante as obrigatórias)."""
    chosen = [source["id"] for source in sources_by_ids(ids)]
    for required in REQUIRED_SOURCE_IDS:
        if required not in chosen:
            chosen.insert(0, required)
    return chosen


def source_counts(ids: Optional[Iterable[str]], es: Optional[Elasticsearch] = None) -> Dict[str, int]:
    """Volumetria por fonte associada (para o grafo do pipeline)."""
    client = default_client(es)
    out: Dict[str, int] = {}
    for source in sources_by_ids(ids):
        out[source["id"]] = 0
        if client is None:
            continue
        try:
            if client.indices.exists(index=source["index"]):
                out[source["id"]] = int(client.count(index=source["index"])["count"])
        except Exception as exc:  # pragma: no cover - depende do cluster
            logger.debug("contagem de %s falhou: %s", source["index"], exc)
    return out


def fold_name(value: Any) -> str:
    """Designação normalizada para junções por nome (sem acentos nem pontuação)."""
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"[^0-9A-Za-z]+", " ", text).strip().upper()
    return re.sub(r"\s+", " ", text)


def fold_name_loose(value: Any) -> str:
    """Normalização do **próprio índice** (GLEIF: minúsculas, sem acentos, com pontuação).

    `fold_name` não serve para consultar `legal_name_folded`: o campo guarda
    «dc merito inversiones sl» e não «DC MERITO INVERSIONES SL». Cada índice tem
    a sua convenção e é essa que tem de ser usada na consulta.
    """
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", text).strip().lower()


# ---------------------------------------------------------------------------
# Utilidades internas
# ---------------------------------------------------------------------------
def _clean_name(value: Any) -> Optional[str]:
    """Limpa e normaliza uma designação (espaços, travessões, vazios).

    Aceita listas (a fonte guarda, por vezes, um campo com um só valor numa
    lista — ex.: `tipoContrato` e `NUTs` nos contratos PT), devolvendo o primeiro
    valor útil.
    """
    if isinstance(value, (list, tuple)):
        for item in value:
            cleaned = _clean_name(item)
            if cleaned:
                return cleaned
        return None
    if value is None:
        return None
    text = " ".join(str(value).replace("\xa0", " ").split())
    if not text or text.lower() in {"n/a", "na", "-", "--", "none", "nan"}:
        return None
    return text[:400]


def _as_float(value: Any) -> Optional[float]:
    try:
        if value in (None, ""):
            return None
        number = float(value)
    except (TypeError, ValueError):
        return None
    # Valores absurdos (a fonte tem gralhas) são descartados em vez de
    # contaminarem as somas e o risco.
    if number != number or abs(number) > 1e13:  # NaN ou > 10 biliões
        return None
    return number


def _iso_day(value: Any) -> Optional[str]:
    """Devolve `AAAA-MM-DD` a partir de uma data ISO (ou None)."""
    if not value:
        return None
    text = str(value)[:10]
    if len(text) != 10 or text[4] != "-":
        return None
    year = text[:4]
    # Gralhas conhecidas da fonte (ex.: ano 0018) ficam de fora.
    if not year.isdigit() or not (1900 <= int(year) <= datetime.now(timezone.utc).year + 1):
        return None
    return text


def _hit_source(hit: Dict[str, Any]) -> Dict[str, Any]:
    return hit.get("_source") or hit.get("fields") or {}


def _top_hit_name(agg: Optional[Dict[str, Any]]) -> Optional[str]:
    """Lê o nome de um `top_hits` dentro de `nested` (com ou sem prefixo)."""
    try:
        hits = (agg or {}).get("hits", {}).get("hits") or []
        if not hits:
            return None
        source = _hit_source(hits[0])
        for key in ("nome", "name", "adjudicatario_nombre", "organo_nombre"):
            if isinstance(source.get(key), str):
                return _clean_name(source[key])
        # `top_hits` dentro de `nested` pode devolver o objeto aninhado inteiro.
        for value in source.values():
            if isinstance(value, dict):
                for key in ("nome", "name"):
                    if value.get(key):
                        return _clean_name(value[key])
    except Exception:
        return None
    return None


def _search(client: Elasticsearch, index: str, body: Dict[str, Any], timeout: int = 90) -> Dict[str, Any]:
    try:
        return client.search(index=index, body=body, request_timeout=timeout)
    except Exception as exc:
        logger.warning("Leitura de %s falhou: %s", index, str(exc)[:300])
        return {}


# ---------------------------------------------------------------------------
# Contagens/somas por entidade (agregações)
# ---------------------------------------------------------------------------
def pt_party_metrics(
    role: str = "adjudicatario",
    limit: int = 2000,
    es: Optional[Elasticsearch] = None,
) -> List[Dict[str, Any]]:
    """Entidades PT com nº de contratos, valor, primeira e última data.

    `role` é `adjudicante` (tipicamente entidade pública) ou `adjudicatario`
    (tipicamente empresa). A agregação é `nested` sobre `*.parsed`, com
    `reverse_nested` para ler os campos do contrato (valor e datas).
    """
    client = default_client(es)
    if client is None:
        return []
    path = _PT_PARTY_PATH.get(role)
    if not path:
        return []
    body = {
        "size": 0,
        "track_total_hits": False,
        "aggs": {
            "parties": {
                "nested": {"path": path},
                "aggs": {
                    "by_nif": {
                        "terms": {"field": f"{path}.nif", "size": max(1, int(limit))},
                        "aggs": {
                            "nome": {"top_hits": {"size": 1, "_source": [f"{path}.nome"]}},
                            "valor": {"reverse_nested": {}, "aggs": {"s": {"sum": {"field": _PT_VALUE_FIELD}}}},
                            "primeiro": {"reverse_nested": {}, "aggs": {"m": {"min": {"field": "dataCelebracaoContrato"}}}},
                            "ultimo": {"reverse_nested": {}, "aggs": {"m": {"max": {"field": "dataCelebracaoContrato"}}}},
                        },
                    }
                },
            }
        },
    }
    resp = _search(client, CONTRACTS_INDEX, body)
    buckets = ((resp.get("aggregations") or {}).get("parties") or {}).get("by_nif", {}).get("buckets") or []
    out: List[Dict[str, Any]] = []
    for bucket in buckets:
        nif = str(bucket.get("key") or "").strip()
        if not nif:
            continue
        out.append(
            {
                "nif": nif,
                "name": _top_hit_name(bucket.get("nome")),
                "contracts": int(bucket.get("doc_count") or 0),
                "value": _as_float(((bucket.get("valor") or {}).get("s") or {}).get("value")),
                "first": _iso_day(((bucket.get("primeiro") or {}).get("m") or {}).get("value_as_string")),
                "last": _iso_day(((bucket.get("ultimo") or {}).get("m") or {}).get("value_as_string")),
                "country": "Portugal",
                "source": "contratos",
            }
        )
    return out


def es_party_metrics(
    role: str = "adjudicatario",
    limit: int = 2000,
    es: Optional[Elasticsearch] = None,
) -> List[Dict[str, Any]]:
    """Entidades de Espanha (PLACSP) com nº de contratos, valor e datas.

    Nos contratos de Espanha os campos são planos (`organo_id`,
    `adjudicatario_nif`), pelo que a agregação é imediata.
    """
    client = default_client(es)
    if client is None:
        return []
    if role == "adjudicante":
        nif_field, name_field = "organo_id", "organo_nombre"
    else:
        nif_field, name_field = "adjudicatario_nif", "adjudicatario_nombre"
    body = {
        "size": 0,
        "track_total_hits": False,
        "query": {"bool": {"filter": [{"exists": {"field": nif_field}}]}},
        "aggs": {
            "by_nif": {
                "terms": {"field": nif_field, "size": max(1, int(limit))},
                "aggs": {
                    "nome": {"top_hits": {"size": 1, "_source": [name_field]}},
                    "valor": {"sum": {"field": "valor_adjudicado"}},
                    "primeiro": {"min": {"field": "fecha_adjudicacion"}},
                    "ultimo": {"max": {"field": "fecha_adjudicacion"}},
                },
            }
        },
    }
    resp = _search(client, CONTRATOS_ES_INDEX, body)
    buckets = ((resp.get("aggregations") or {}).get("by_nif") or {}).get("buckets") or []
    out: List[Dict[str, Any]] = []
    for bucket in buckets:
        nif = str(bucket.get("key") or "").strip()
        if not nif:
            continue
        out.append(
            {
                "nif": nif,
                "name": _top_hit_name(bucket.get("nome")),
                "contracts": int(bucket.get("doc_count") or 0),
                "value": _as_float((bucket.get("valor") or {}).get("value")),
                "first": _iso_day(((bucket.get("primeiro") or {}).get("value_as_string"))),
                "last": _iso_day(((bucket.get("ultimo") or {}).get("value_as_string"))),
                "country": "Espanha",
                "source": "contratos_es",
            }
        )
    return out


# ---------------------------------------------------------------------------
# Amostra de contratos (pares, valor, datas, CPV)
# ---------------------------------------------------------------------------
def _pt_parties(source: Dict[str, Any], role: str) -> List[Dict[str, str]]:
    raw = source.get("adjudicantes" if role == "adjudicante" else "adjudicatarios") or []
    out: List[Dict[str, str]] = []
    for item in raw if isinstance(raw, list) else [raw]:
        parsed = item.get("parsed") if isinstance(item, dict) else None
        entries = parsed if isinstance(parsed, list) else ([parsed] if isinstance(parsed, dict) else [])
        for entry in entries:
            nif = str((entry or {}).get("nif") or "").strip()
            name = _clean_name((entry or {}).get("nome"))
            if nif:
                out.append({"nif": nif, "name": name})
    return out


def _pt_cpvs(source: Dict[str, Any]) -> List[Dict[str, str]]:
    raw = source.get("cpv") or []
    out: List[Dict[str, str]] = []
    for item in raw if isinstance(raw, list) else [raw]:
        code = str((item or {}).get("code") or "").strip()
        if code:
            out.append({"code": code, "label": _clean_name((item or {}).get("description"))})
    return out


def _es_cpvs(source: Dict[str, Any]) -> List[Dict[str, str]]:
    raw = source.get("cpv") or []
    out: List[Dict[str, str]] = []
    for item in raw if isinstance(raw, list) else [raw]:
        code = str((item or {}).get("code") or "").strip()
        if code:
            out.append({"code": code, "label": _clean_name((item or {}).get("nombre"))})
    return out


def _first_iso(source: Dict[str, Any], fields: Iterable[str]) -> Optional[str]:
    for field in fields:
        value = _iso_day(source.get(field))
        if value:
            return value
    return None


def _add_days(day: Optional[str], days: Optional[float]) -> Optional[str]:
    """Soma dias a uma data ISO (`AAAA-MM-DD`) — usado para o fim previsto dos contratos."""
    if not day or not days or days <= 0:
        return None
    try:
        start = datetime.fromisoformat(day[:10])
    except ValueError:
        return None
    return (start + timedelta(days=float(days))).strftime("%Y-%m-%d")


def contract_sample(
    size: int = 3000,
    year_from: Optional[int] = None,
    spread_years: int = 12,
    es: Optional[Elasticsearch] = None,
) -> List[Dict[str, Any]]:
    """Amostra normalizada de contratos PT + ES, **estratificada por ano**.

    É desta amostra que saem as relações (adjudicante↔adjudicatário) e os eventos
    de adjudicação. `size` é o total por país (PT/ES) e é repartido pelos últimos
    `spread_years` anos.

    A estratificação é essencial: ordenar só por data descendente traz contratos
    dos últimos meses e o **histórico temporal** ficaria com um único período com
    atividade (uma "parede" no último trimestre), o que torna inútil qualquer
    análise de evolução, de anomalia e de transição.
    """
    client = default_client(es)
    if client is None:
        return []
    size = max(1, int(size))
    current_year = datetime.now(timezone.utc).year
    first_year = int(year_from) if year_from else current_year - max(1, int(spread_years)) + 1
    first_year = max(1990, min(first_year, current_year))
    years = list(range(first_year, current_year + 1))
    per_year = max(1, size // len(years))

    out: List[Dict[str, Any]] = []
    for year in years:
        # --- Portugal -----------------------------------------------------
        pt_body = {
            "size": per_year,
            "track_total_hits": False,
            "query": {
                "bool": {
                    # `exists` num subcampo **nested** tem de ser embrulhado na
                    # query `nested`, senão não devolve nada (o campo não existe
                    # ao nível do documento raiz). Ver `_probe_world_parties.py`.
                    "filter": [
                        {
                            "nested": {
                                "path": "adjudicatarios.parsed",
                                "query": {"exists": {"field": "adjudicatarios.parsed.nif"}},
                            }
                        },
                        {
                            "bool": {
                                "should": [
                                    {"range": {"dataCelebracaoContrato": {"gte": f"{year}-01-01", "lt": f"{year + 1}-01-01"}}},
                                    {"range": {"dataDecisaoAdjudicacao": {"gte": f"{year}-01-01", "lt": f"{year + 1}-01-01"}}},
                                    {"range": {"dataPublicacao": {"gte": f"{year}-01-01", "lt": f"{year + 1}-01-01"}}},
                                ],
                                "minimum_should_match": 1,
                            }
                        },
                    ]
                }
            },
            # Sem `sort`: a ordenação global por data é a parte mais cara destas
            # consultas e a amostra é reordenada em Python no fim.
            "_source": [
                "idcontrato",
                "precoContratual",
                "dataCelebracaoContrato",
                "dataDecisaoAdjudicacao",
                "dataPublicacao",
                "dataFechoContrato",
                "prazoExecucao",
                "tipoContrato",
                "tipoFimContrato",
                "objectoContrato",
                "adjudicantes",
                "adjudicatarios",
                "cpv",
                "NUTs",
                "Ano",
            ],
        }
        for hit in (_search(client, CONTRACTS_INDEX, pt_body).get("hits") or {}).get("hits") or []:
            source = _hit_source(hit)
            uid = str(source.get("idcontrato") or hit.get("_id") or "").strip()
            if not uid:
                continue
            celebrated = _first_iso(source, _PT_DATE_FIELDS)
            # Fim previsto = data de celebração (ou adjudicação) + prazo de execução.
            expected_end = _add_days(celebrated, _as_float(source.get("prazoExecucao")))
            out.append(
                {
                    "uid": f"contratos:{uid}",
                    "source": "contratos",
                    "index": CONTRACTS_INDEX,
                    "country": "Portugal",
                    "id": uid,
                    "date": celebrated,
                    "end_date": _iso_day(source.get("dataFechoContrato")),
                    "expected_end": expected_end,
                    "prazo_dias": _as_float(source.get("prazoExecucao")),
                    "value": _as_float(source.get("precoContratual")),
                    "cpv": _pt_cpvs(source),
                    "adjudicantes": _pt_parties(source, "adjudicante"),
                    "adjudicatarios": _pt_parties(source, "adjudicatario"),
                    "contract_type": _clean_name(source.get("tipoContrato")),
                    "end_type": _clean_name(source.get("tipoFimContrato")),
                    "object": _clean_name(source.get("objectoContrato")),
                    "region": _clean_name(source.get("NUTs")),
                }
            )

        # --- Espanha ------------------------------------------------------
        es_body = {
            "size": per_year,
            "track_total_hits": False,
            "query": {
                "bool": {
                    "filter": [
                        {"exists": {"field": "adjudicatario_nif"}},
                        {"term": {"ano": year}},
                    ]
                }
            },
            "_source": [
                "id_expediente",
                "fonte",
                "organo_id",
                "organo_nombre",
                "adjudicatario_nif",
                "adjudicatario_nombre",
                "valor_adjudicado",
                "valor_base",
                "fecha_adjudicacion",
                "fecha_publicacion",
                "estado",
                "estado_label",
                "tipo_contrato_label",
                "cpv",
                "ano",
            ],
        }
        for hit in (_search(client, CONTRATOS_ES_INDEX, es_body, timeout=60).get("hits") or {}).get("hits") or []:
            source = _hit_source(hit)
            uid = str(source.get("id_expediente") or hit.get("_id") or "").strip()
            if not uid:
                continue
            organo = str(source.get("organo_id") or "").strip()
            adjudicatario = str(source.get("adjudicatario_nif") or "").strip()
            out.append(
                {
                    "uid": f"contratos_es:{source.get('fonte') or 'x'}:{uid}",
                    "source": "contratos_es",
                    "index": CONTRATOS_ES_INDEX,
                    "country": "Espanha",
                    "id": uid,
                    "date": _first_iso(source, ("fecha_adjudicacion", "fecha_publicacion")),
                    "end_date": None,
                    "expected_end": None,
                    "prazo_dias": None,
                    "value": _as_float(source.get("valor_adjudicado")) or _as_float(source.get("valor_base")),
                    "cpv": _es_cpvs(source),
                    "adjudicantes": [{"nif": organo, "name": _clean_name(source.get("organo_nombre"))}] if organo else [],
                    "adjudicatarios": (
                        [{"nif": adjudicatario, "name": _clean_name(source.get("adjudicatario_nombre"))}]
                        if adjudicatario
                        else []
                    ),
                    "contract_type": _clean_name(source.get("tipo_contrato_label")),
                    "end_type": None,
                    "object": None,
                    "region": None,
                    "state": source.get("estado_label"),
                }
            )

    out.sort(key=lambda item: item.get("date") or "", reverse=True)
    return out


# ---------------------------------------------------------------------------
# Evidência por entidade (contratos de um NIF)
# ---------------------------------------------------------------------------
def entity_contracts(nif: str, size: int = 40, es: Optional[Elasticsearch] = None) -> List[Dict[str, Any]]:
    """Contratos de um NIF/NIPC (PT e ES), normalizados e ordenados por data.

    Usado como **evidência** pelo agente de investigação: cada contrato traz o
    índice e o identificador de origem, para o relatório citar a proveniência.
    """
    client = default_client(es)
    nif = str(nif or "").strip()
    if client is None or not nif:
        return []
    size = max(1, min(200, int(size)))
    out: List[Dict[str, Any]] = []

    pt_body = {
        "size": size,
        "track_total_hits": False,
        "query": {
            "bool": {
                "should": [
                    {"nested": {"path": "adjudicatarios.parsed", "query": {"term": {"adjudicatarios.parsed.nif": nif}}}},
                    {"nested": {"path": "adjudicantes.parsed", "query": {"term": {"adjudicantes.parsed.nif": nif}}}},
                ],
                "minimum_should_match": 1,
            }
        },
        "sort": [{"dataCelebracaoContrato": {"order": "desc", "missing": "_last"}}],
        "_source": [
            "idcontrato",
            "precoContratual",
            "dataCelebracaoContrato",
            "dataDecisaoAdjudicacao",
            "dataPublicacao",
            "tipoContrato",
            "objectoContrato",
            "adjudicantes",
            "adjudicatarios",
            "cpv",
        ],
    }
    resp = _search(client, CONTRACTS_INDEX, pt_body)
    for hit in (resp.get("hits") or {}).get("hits") or []:
        source = _hit_source(hit)
        uid = str(source.get("idcontrato") or hit.get("_id") or "").strip()
        out.append(
            {
                "uid": f"contratos:{uid}",
                "source": "contratos",
                "index": CONTRACTS_INDEX,
                "country": "Portugal",
                "id": uid,
                "date": _first_iso(source, _PT_DATE_FIELDS),
                "value": _as_float(source.get("precoContratual")),
                "cpv": _pt_cpvs(source),
                "adjudicantes": _pt_parties(source, "adjudicante"),
                "adjudicatarios": _pt_parties(source, "adjudicatario"),
                "contract_type": _clean_name(source.get("tipoContrato")),
                "object": _clean_name(source.get("objectoContrato")),
                "role": "adjudicatario"
                if any(p.get("nif") == nif for p in _pt_parties(source, "adjudicatario"))
                else "adjudicante",
            }
        )

    es_body = {
        "size": size,
        "track_total_hits": False,
        "query": {"bool": {"should": [{"term": {"adjudicatario_nif": nif}}, {"term": {"organo_id": nif}}], "minimum_should_match": 1}},
        "sort": [{"fecha_adjudicacion": {"order": "desc", "missing": "_last"}}],
        "_source": [
            "id_expediente",
            "fonte",
            "organo_id",
            "organo_nombre",
            "adjudicatario_nif",
            "adjudicatario_nombre",
            "valor_adjudicado",
            "fecha_adjudicacion",
            "tipo_contrato_label",
            "cpv",
        ],
    }
    resp = _search(client, CONTRATOS_ES_INDEX, es_body)
    for hit in (resp.get("hits") or {}).get("hits") or []:
        source = _hit_source(hit)
        uid = str(source.get("id_expediente") or hit.get("_id") or "").strip()
        out.append(
            {
                "uid": f"contratos_es:{source.get('fonte') or 'x'}:{uid}",
                "source": "contratos_es",
                "index": CONTRATOS_ES_INDEX,
                "country": "Espanha",
                "id": uid,
                "date": _first_iso(source, ("fecha_adjudicacion",)),
                "value": _as_float(source.get("valor_adjudicado")),
                "cpv": _es_cpvs(source),
                "adjudicantes": [{"nif": str(source.get("organo_id") or ""), "name": _clean_name(source.get("organo_nombre"))}],
                "adjudicatarios": [
                    {"nif": str(source.get("adjudicatario_nif") or ""), "name": _clean_name(source.get("adjudicatario_nombre"))}
                ],
                "contract_type": _clean_name(source.get("tipo_contrato_label")),
                "object": None,
                "role": "adjudicatario" if str(source.get("adjudicatario_nif") or "") == nif else "adjudicante",
            }
        )

    out.sort(key=lambda item: item.get("date") or "", reverse=True)
    return out


def entity_insolvencies(nif: str, size: int = 20, es: Optional[Elasticsearch] = None) -> List[Dict[str, Any]]:
    """Processos CIRE em que o NIF aparece como interveniente."""
    client = default_client(es)
    nif = str(nif or "").strip()
    if client is None or not nif:
        return []
    body = {
        "size": max(1, min(50, int(size))),
        "track_total_hits": False,
        "query": {
            "bool": {
                "should": [
                    {"term": {"nifs": nif}},
                    {"nested": {"path": "intervenientes", "query": {"term": {"intervenientes.nif": nif}}}},
                ],
                "minimum_should_match": 1,
            }
        },
        "sort": [{"data_publicacao": {"order": "desc", "missing": "_last"}}],
        "_source": ["pub_id", "data_publicacao", "tribunal", "processo", "tipo", "especie", "intervenientes"],
    }
    resp = _search(client, CIRE_INDEX, body)
    out: List[Dict[str, Any]] = []
    for hit in (resp.get("hits") or {}).get("hits") or []:
        source = _hit_source(hit)
        roles = [
            {"papel": (p or {}).get("papel"), "nome": _clean_name((p or {}).get("nome"))}
            for p in (source.get("intervenientes") or [])
            if isinstance(p, dict) and str((p or {}).get("nif") or "") == nif
        ]
        out.append(
            {
                "index": CIRE_INDEX,
                "id": source.get("pub_id") or hit.get("_id"),
                "ts": _iso_day(source.get("data_publicacao")),
                "court": _clean_name(source.get("tribunal")),
                "process": source.get("processo"),
                "type": source.get("tipo"),
                "species": source.get("especie"),
                "roles": roles,
            }
        )
    return out


# ---------------------------------------------------------------------------
# Insolvências, pessoas e designações canónicas
# ---------------------------------------------------------------------------
def insolvency_records(size: int = 2000, es: Optional[Elasticsearch] = None) -> List[Dict[str, Any]]:
    """Processos de insolvência (CIRE) com os NIF intervenientes.

    Devolve uma lista de `{"nif", "name", "role", "ts", "process", "court"}` —
    as empresas que aparecem como insolventes (ou credoras) entram no World
    Model como entidades em risco.
    """
    client = default_client(es)
    if client is None:
        return []
    body = {
        "size": max(1, int(size)),
        "track_total_hits": False,
        "sort": [{"data_publicacao": {"order": "desc", "missing": "_last"}}],
        "_source": ["pub_id", "data_publicacao", "tribunal", "processo", "tipo", "intervenientes", "nifs"],
    }
    resp = _search(client, CIRE_INDEX, body)
    out: List[Dict[str, Any]] = []
    for hit in (resp.get("hits") or {}).get("hits") or []:
        source = _hit_source(hit)
        ts = _iso_day(source.get("data_publicacao"))
        process = source.get("processo") or source.get("process") or hit.get("_id")
        court = _clean_name(source.get("tribunal"))
        people = source.get("intervenientes") or []
        for person in people if isinstance(people, list) else []:
            nif = str((person or {}).get("nif") or "").strip()
            if not nif:
                continue
            role = str((person or {}).get("papel") or (person or {}).get("role") or "").strip().lower()
            out.append(
                {
                    "nif": nif,
                    "name": _clean_name((person or {}).get("nome") or (person or {}).get("name")),
                    "role": role or "interveniente",
                    "ts": ts,
                    "process": str(process) if process else None,
                    "court": court,
                    "kind": _clean_name(source.get("tipo")) or "insolvencia",
                }
            )
    return out


def canonical_names(nifs: List[str], es: Optional[Elasticsearch] = None) -> Dict[str, Dict[str, Any]]:
    """Designação/tipo/país canónicos por NIF, a partir de `finance_contribuintes`.

    Evita que a mesma entidade apareça com dois nomes diferentes no mundo
    (ex.: «SONAE» no contrato e «Sonae, SGPS, S.A.» no cadastro).
    """
    client = default_client(es)
    wanted = [str(nif).strip() for nif in nifs if str(nif).strip()]
    if client is None or not wanted:
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    # Buscas em blocos: `terms` com milhares de valores estoura o limite de
    # cláusulas e é mais lento do que várias buscas médias.
    for start in range(0, len(wanted), 500):
        chunk = wanted[start : start + 500]
        body = {
            "size": len(chunk),
            "track_total_hits": False,
            "_source": ["nif", "name", "type", "type_label", "country", "is_company"],
            "query": {"terms": {"nif": chunk}},
        }
        resp = _search(client, CONTRIBUINTES_INDEX, body)
        for hit in (resp.get("hits") or {}).get("hits") or []:
            source = _hit_source(hit)
            nif = str(source.get("nif") or "").strip()
            if nif:
                out[nif] = {
                    "name": _clean_name(source.get("name")),
                    "type": source.get("type"),
                    "country": source.get("country"),
                    "is_company": source.get("is_company"),
                }
    return out


def people_relations(size: int = 5000, es: Optional[Elasticsearch] = None) -> List[Dict[str, Any]]:
    """Relações pessoa→empresa (cargos) a partir de `finance_people`.

    Cada registo é `{"person_id", "person_name", "company_nif", "company_name",
    "role", "ts"}`. Alimenta as arestas `gerente_de`/`cargo_em` do grafo.
    """
    client = default_client(es)
    if client is None:
        return []
    body = {
        "size": max(1, int(size)),
        "track_total_hits": False,
        "_source": ["person_id", "nif", "name", "roles", "companies"],
    }
    resp = _search(client, PEOPLE_INDEX, body)
    out: List[Dict[str, Any]] = []
    for hit in (resp.get("hits") or {}).get("hits") or []:
        source = _hit_source(hit)
        person_id = str(source.get("person_id") or source.get("nif") or hit.get("_id") or "").strip()
        person_name = _clean_name(source.get("name"))
        roles = source.get("roles") or source.get("companies") or []
        for entry in roles if isinstance(roles, list) else []:
            entry = entry or {}
            company_nif = str(entry.get("company_nif") or entry.get("nif") or "").strip()
            if not company_nif:
                continue
            out.append(
                {
                    "person_id": person_id,
                    "person_name": person_name,
                    "company_nif": company_nif,
                    "company_name": _clean_name(entry.get("company_name") or entry.get("name")),
                    "role": _clean_name(entry.get("role") or entry.get("cargo")) or "cargo",
                    "ts": _iso_day(entry.get("date") or entry.get("ts")),
                }
            )
    return out


# ---------------------------------------------------------------------------
# Fontes adicionais (associáveis): registo, publicações, propriedade, menções
# ---------------------------------------------------------------------------
# Cada adaptador devolve registos **normalizados**; quem os transforma em
# entidades/eventos/relações é o `world_model`. Assim, associar uma fonte nova
# não obriga a mexer na construção do mundo.
def _chunks(values: List[str], size: int = 500) -> Iterable[List[str]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def registry_records(
    source_ids: List[str],
    nifs: Optional[List[str]] = None,
    names: Optional[List[str]] = None,
    size: int = 20000,
    es: Optional[Elasticsearch] = None,
) -> List[Dict[str, Any]]:
    """Registos de identificação (nome, país, tipo, LEI) das fontes associadas.

    Junção **por NIF** (contribuintes, entidades públicas): procura-se apenas os
    NIF que o mundo já conhece — 500 de cada vez evita o limite de cláusulas do
    `terms` e é mais rápido do que ler 700 mil documentos.

    Junção **por nome** (GLEIF, que não tem NIF): procura-se as designações do
    mundo no campo normalizado do índice (`legal_name_folded`), também em blocos —
    ler uma amostra arbitrária de 20 mil documentos quase nunca acertaria em
    nenhuma entidade. Sem nomes (chamada isolada), cai na amostra limitada.
    """
    client = default_client(es)
    if client is None:
        return []
    out: List[Dict[str, Any]] = []
    for source in sources_by_ids(source_ids):
        if source.get("adapter") != "registo":
            continue
        fields = {
            "contribuintes": ["nif", "name", "country", "is_company", "roles"],
            "entidades": ["nif", "name", "country", "source", "contracts_count", "total_value"],
            "gleif": [
                "lei",
                "legal_name",
                "legal_name_folded",
                "other_names",
                "country",
                "hq_country",
                "legal_form",
                "category",
                "conformity_flag",
                "last_update_date",
            ],
        }.get(source["id"], ["nif", "name", "country"])
        if source["join"] == "nif":
            wanted = [str(nif).strip() for nif in (nifs or []) if str(nif).strip()]
            if not wanted:
                continue
            for chunk in _chunks(sorted(set(wanted))):
                body = {
                    "size": len(chunk),
                    "track_total_hits": False,
                    "_source": fields,
                    "query": {"terms": {"nif": chunk}},
                }
                resp = _search(client, source["index"], body)
                for hit in (resp.get("hits") or {}).get("hits") or []:
                    record = _registry_from_hit(source, _hit_source(hit), nif_field="nif")
                    if record:
                        out.append(record)
            continue
        join_field = source.get("join_field")
        wanted_names = [str(name) for name in (names or []) if str(name).strip()]
        if join_field and wanted_names:
            normalized = sorted({fold_name_loose(name) for name in wanted_names})
            for chunk in _chunks(normalized):
                body = {
                    "size": len(chunk),
                    "track_total_hits": False,
                    "_source": fields,
                    "query": {"terms": {join_field: chunk}},
                }
                resp = _search(client, source["index"], body)
                for hit in (resp.get("hits") or {}).get("hits") or []:
                    record = _registry_from_hit(source, _hit_source(hit), nif_field=None)
                    if record:
                        out.append(record)
            continue
        body = {"size": max(1, min(int(size), 20000)), "track_total_hits": False, "_source": fields}
        resp = _search(client, source["index"], body)
        for hit in (resp.get("hits") or {}).get("hits") or []:
            record = _registry_from_hit(source, _hit_source(hit), nif_field=None)
            if record:
                out.append(record)
    return out


def _registry_from_hit(source: Dict[str, Any], hit: Dict[str, Any], nif_field: Optional[str]) -> Optional[Dict[str, Any]]:
    """Normaliza um documento de registo (com NIF ou com designação legal)."""
    if source["id"] == "gleif":
        name = _clean_name(hit.get("legal_name")) or _clean_name((hit.get("other_names") or [None])[0])
        folded = _clean_name(hit.get("legal_name_folded")) or fold_name(name)
        if not name:
            return None
        return {
            "source": source["id"],
            "index": source["index"],
            "nif": None,
            "name": name,
            "name_folded": fold_name(folded or name),
            "country": _clean_name(hit.get("country") or hit.get("hq_country")),
            "entity_type": "empresa",
            "ts": _iso_day(hit.get("last_update_date")),
            "identifiers": {"lei": hit.get("lei")},
            "extra": {
                "legal_form": _clean_name(hit.get("legal_form")),
                "category": _clean_name(hit.get("category")),
                "conformity": _clean_name(hit.get("conformity_flag")),
            },
        }
    nif = str(hit.get(nif_field or "nif") or "").strip()
    if not nif:
        return None
    is_company = hit.get("is_company")
    entity_type = "empresa" if is_company in (None, True) else "pessoa"
    if source["id"] == "entidades":
        entity_type = "entidade_publica"
    return {
        "source": source["id"],
        "index": source["index"],
        "nif": nif,
        "name": _clean_name(hit.get("name")),
        "name_folded": fold_name(hit.get("name")),
        "country": _clean_name(hit.get("country")),
        "entity_type": entity_type,
        "ts": None,
        "identifiers": {},
        "extra": {
            "roles": hit.get("roles"),
            "contracts_count": hit.get("contracts_count"),
            "total_value": hit.get("total_value"),
        },
    }


def publication_records(size: int = 5000, es: Optional[Elasticsearch] = None) -> List[Dict[str, Any]]:
    """Publicações societárias (MJ) → eventos com data, acto e firma."""
    client = default_client(es)
    if client is None:
        return []
    body = {
        "size": max(1, min(int(size), 5000)),
        "track_total_hits": False,
        "sort": [{"data_publicacao": {"order": "desc", "missing": "_last"}}],
        "_source": [
            "nif",
            "search_nif",
            "matricula_nipc",
            "entidade",
            "firma",
            "acto",
            "tipo",
            "tipo_label",
            "data_publicacao",
            "concelho",
            "distrito",
            "natureza_juridica",
            "documento_url",
            "pub_id",
        ],
    }
    resp = _search(client, SOCIETARIO_INDEX, body)
    out: List[Dict[str, Any]] = []
    for hit in (resp.get("hits") or {}).get("hits") or []:
        source = _hit_source(hit)
        raw_nif = source.get("nif") or source.get("search_nif") or source.get("matricula_nipc")
        nif = re.sub(r"\D", "", str(raw_nif or ""))
        if not nif:
            continue
        out.append(
            {
                "nif": nif,
                "name": _clean_name(source.get("firma") or source.get("entidade")),
                "ts": _iso_day(source.get("data_publicacao")),
                "act": _clean_name(source.get("acto") or source.get("tipo")) or "publicação",
                "act_label": _clean_name(source.get("tipo_label") or source.get("tipo")) or "Publicação societária",
                "nature": _clean_name(source.get("natureza_juridica")),
                "place": _clean_name(source.get("concelho") or source.get("distrito")),
                "url": source.get("documento_url"),
                "id": str(source.get("pub_id") or hit.get("_id") or ""),
                "source": "societario",
                "index": SOCIETARIO_INDEX,
            }
        )
    return out


def property_records(size: int = 5000, es: Optional[Elasticsearch] = None) -> List[Dict[str, Any]]:
    """Marcas e firmas → eventos de propriedade e métricas por NIF."""
    client = default_client(es)
    if client is None:
        return []
    out: List[Dict[str, Any]] = []
    body = {
        "size": max(1, min(int(size), 5000)),
        "track_total_hits": False,
        "_source": [
            "process_number",
            "mark_name",
            "mark_type",
            "nice_classes",
            "application_date",
            "current_phase",
            "company_nif",
            "company_name",
            "holder_nif",
            "holder_name",
        ],
    }
    for hit in (_search(client, TRADEMARKS_INDEX, body).get("hits") or {}).get("hits") or []:
        source = _hit_source(hit)
        nif = re.sub(r"\D", "", str(source.get("company_nif") or source.get("holder_nif") or ""))
        name = _clean_name(source.get("mark_name"))
        if not nif or not name:
            continue
        out.append(
            {
                "kind": "marca",
                "nif": nif,
                "entity_name": _clean_name(source.get("company_name") or source.get("holder_name")),
                "name": name,
                "detail": _clean_name(source.get("mark_type")) or "marca",
                "ts": _iso_day(source.get("application_date")),
                "phase": _clean_name(source.get("current_phase")),
                "classes": source.get("nice_classes"),
                "id": str(source.get("process_number") or hit.get("_id") or ""),
                "source": "marcas",
                "index": TRADEMARKS_INDEX,
            }
        )
    body = {
        "size": max(1, min(int(size), 5000)),
        "track_total_hits": False,
        "_source": ["company_nif", "nipc", "company_name", "nome", "cae_principal", "situacao", "situacao_detalhe", "concelho_sede"],
    }
    for hit in (_search(client, FIRMAS_INDEX, body).get("hits") or {}).get("hits") or []:
        source = _hit_source(hit)
        nif = re.sub(r"\D", "", str(source.get("company_nif") or source.get("nipc") or ""))
        name = _clean_name(source.get("company_name") or source.get("nome"))
        if not nif:
            continue
        out.append(
            {
                "kind": "firma",
                "nif": nif,
                "entity_name": name,
                "name": name,
                "detail": _clean_name(source.get("cae_principal")) or "firma",
                "ts": None,
                "phase": _clean_name(source.get("situacao")),
                "classes": None,
                "id": str(hit.get("_id") or ""),
                "source": "firmas",
                "index": FIRMAS_INDEX,
                "extra": {
                    "situacao": _clean_name(source.get("situacao_detalhe") or source.get("situacao")),
                    "concelho": _clean_name(source.get("concelho_sede")),
                },
            }
        )
    return out


def mention_records(size: int = 5000, es: Optional[Elasticsearch] = None) -> List[Dict[str, Any]]:
    """Menções (redes sociais e imprensa) → eventos com data, título e sentimento."""
    client = default_client(es)
    if client is None:
        return []
    out: List[Dict[str, Any]] = []
    body = {
        "size": max(1, min(int(size), 5000)),
        "track_total_hits": False,
        "_source": [
            "person_nif",
            "person_name",
            "title",
            "text",
            "url",
            "platform",
            "source_name",
            "published_at",
            "data",
            "sentiment",
            "sentiment_score",
            "metrics",
        ],
    }
    for hit in (_search(client, SOCIAL_INDEX, body).get("hits") or {}).get("hits") or []:
        source = _hit_source(hit)
        text = _clean_name(source.get("title") or source.get("text")) or ""
        out.append(
            {
                "kind": "mencao",
                "nif": re.sub(r"\D", "", str(source.get("person_nif") or "")) or None,
                "entity_name": _clean_name(source.get("person_name")),
                "text": text[:240],
                "ts": _iso_day(source.get("published_at") or source.get("data")),
                "url": source.get("url"),
                "channel": _clean_name(source.get("platform") or source.get("source_name")) or "social",
                "sentiment": source.get("sentiment"),
                "sentiment_score": _as_float(source.get("sentiment_score")),
                "engagement": (source.get("metrics") or {}).get("likes") if isinstance(source.get("metrics"), dict) else None,
                "id": str(source.get("item_id") or hit.get("_id") or ""),
                "source": "sociais",
                "index": SOCIAL_INDEX,
            }
        )
    body = {
        "size": max(1, min(int(size), 5000)),
        "track_total_hits": False,
        "_source": ["title", "summary", "text", "url", "source_name", "data", "scraped_at", "sentiment", "sentiment_score", "tags"],
    }
    for hit in (_search(client, SCRAPED_INDEX, body).get("hits") or {}).get("hits") or []:
        source = _hit_source(hit)
        title = _clean_name(source.get("title")) or _clean_name(source.get("summary")) or ""
        if not title:
            continue
        out.append(
            {
                "kind": "mencao",
                "nif": None,
                "entity_name": None,
                "text": title[:240],
                "ts": _iso_day(source.get("data") or source.get("scraped_at")),
                "url": source.get("url"),
                "channel": _clean_name(source.get("source_name")) or "imprensa",
                "sentiment": source.get("sentiment"),
                "sentiment_score": _as_float(source.get("sentiment_score")),
                "engagement": None,
                "id": str(source.get("item_id") or hit.get("_id") or ""),
                "source": "recolha",
                "index": SCRAPED_INDEX,
            }
        )
    return out
