"""Motor da ontologia do IQ OS.

Converte o registo declarativo (`api/ontology_registry.py`) em funcionalidade:

- **Consulta de objetos** — pesquisa, filtros e ordenação traduzidos para
  Elasticsearch (ou para agregados/resolvedores derivados).
- **Ligações** — navegação entre objetos (contrato → partes, empresa → marcas,
  conta → contactos, notícia → pessoas, …), incluindo ligações inversas.
- **Resolução de entidades** — de texto livre (NIF, nome, ticker) para objetos
  canónicos, com nível de confiança.
- **Contexto para IA** — objetos + relações + bloco de contexto textual, para
  fundamentar respostas (grounding) em vez de as deixar inventar.
- **Validação** — verifica se as entidades e os valores de uma resposta existem
  nos dados (anti-alucinação).
- **Ferramentas geradas** — esquemas de função derivados da ontologia, para o
  agente usar a mesma camada semântica.

Honestidade dos dados: nunca se apresentam valores como exatos quando vêm de
amostras ou de agregados; os `notes` de cada resposta dizem de onde vêm.
"""
from __future__ import annotations

import logging
import re
import time
import unicodedata
from difflib import SequenceMatcher
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from api import ontology_registry as registry
from api.elasticsearch_client import (
    CONTRACTS_INDEX,
    UNSPECIFIED_LABEL,
    get_es_client,
    list_indexed_tickers,
)

logger = logging.getLogger(__name__)

MAX_QUERY_SIZE = 200
_DEFAULT_QUERY_SIZE = 20
_SCORE_THRESHOLD = 0.45

# Cache curta de consultas: a ontologia é lida muitas vezes pela UI e pelo
# agente; sem isto, agregados pesados (empresas, cotações, CPV) repetiam-se a
# cada pergunta. Os dados não são em tempo real, por isso 60 s é suficiente.
_QUERY_TTL = 60.0
_CACHE_MAX = 160
_query_cache: Dict[str, Tuple[float, Any]] = {}

# Palavras de ligação que não devem ficar no fim de uma menção («EDP e» → «EDP»).
_CONNECTORS = {"e", "de", "da", "do", "das", "dos", "em", "no", "na", "nos", "nas", "para", "por", "com", "&", "the", "of"}

# Palavras genéricas: não identificam nada por si só (evita menções inúteis
# como «Contratos do NIF», que só gastam consultas).
_GENERIC_WORDS = {
    "contrato", "contratos", "noticia", "noticias", "empresa", "empresas", "entidade", "entidades",
    "dados", "valor", "valores", "ano", "anos", "nif", "nipc", "ticker", "tickers", "acao", "acoes",
    "preco", "precos", "marca", "marcas", "firma", "firmas", "conta", "contas", "contacto", "contactos",
    "pessoa", "pessoas", "cpv", "regiao", "regioes", "topicos", "topico", "sentimento", "cotacao", "cotacoes",
    "cargo", "cargos", "gestor", "gestores", "administrador", "administradores", "socio", "socios",
    "qual", "quais", "quantos", "quantas", "quanto", "quanta", "lista", "listar", "mostra", "mostrar",
    "diz", "sobre", "existe", "existem", "informacao", "relacao", "relacoes", "ontologia", "resumo",
}

_STOPWORDS = {
    "a", "o", "as", "os", "de", "da", "do", "das", "dos", "em", "no", "na", "nos", "nas",
    "para", "por", "com", "sem", "que", "e", "ou", "se", "mas", "sao", "foi", "ser", "estar",
    "um", "uma", "qual", "quais", "como", "mais", "menos", "muito", "pelo", "pela", "the",
    "and", "of", "in", "to", "is", "for", "on", "at", "or", "it", "its", "an", "that",
    "this", "with", "from", "by", "are", "was", "were", "be", "been", "have", "has", "not",
    "quanto", "quantos", "quanta", "quantas", "qual", "quem", "onde", "quando", "porque",
    "mostra", "mostrar", "lista", "listar", "dados", "diz", "sobre", "entre", "seu", "sua",
}

_NIF_RE = re.compile(r"\b(\d{9})\b")
_QUOTED_RE = re.compile(r"[\"“”«»']([^\"“”«»']{3,80})[\"“”«»']")
# Códigos que identificam um objeto diretamente: CPV e região NUTS.
_CPV_RE = re.compile(r"\b(\d{8}-\d)\b")
_NUTS_RE = re.compile(r"\b(PT[0-9A-Z]{3,4})\b")
_CAPS_RE = re.compile(r"\b([A-ZÀ-Þ][\wÀ-ÿ&.\-]*(?:\s+(?:de|da|do|das|dos|e|&)\s+)?(?:\s*[A-ZÀ-Þ][\wÀ-ÿ&.\-]*){0,3})\b")
_TICKER_RE = re.compile(r"\b([A-Z]{2,5}(?:\.[A-Z]{2})?)\b")
_MONEY_RE = re.compile(r"(\d{1,3}(?:[ .\u00a0]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)\s*(?:€|EUR|euros?|M€|m€|M\s?€|milhões)", re.IGNORECASE)
_YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")

_ticker_cache: Dict[str, Any] = {"at": 0.0, "values": []}
_TICKER_TTL = 300.0


# --------------------------------------------------------------------------
# Utilidades de texto e de valores
# --------------------------------------------------------------------------
def _normalize(text: Any) -> str:
    """Minúsculas sem acentos, para comparação tolerante."""
    if text is None:
        return ""
    value = unicodedata.normalize("NFD", str(text))
    value = "".join(ch for ch in value if unicodedata.category(ch) != "Mn")
    return re.sub(r"\s+", " ", value).strip().lower()


def _similarity(left: str, right: str) -> float:
    """Semelhança entre dois textos (0..1), com bónus para contenção de tokens."""
    a, b = _normalize(left), _normalize(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    ratio = SequenceMatcher(None, a, b).ratio()
    short, long = (a, b) if len(a) <= len(b) else (b, a)
    if short in long:
        ratio = max(ratio, 0.72 + 0.28 * (len(short) / len(long)))
    else:
        tokens = [token for token in short.split() if len(token) > 2]
        if tokens and all(token in long for token in tokens):
            ratio = max(ratio, 0.82)
    return round(ratio, 3)


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _flatten(values: Any) -> List[Any]:
    out: List[Any] = []
    for value in _as_list(values):
        if isinstance(value, list):
            out.extend(_flatten(value))
        elif value is not None and value != "":
            out.append(value)
    return out


def _dig(value: Any, path: str) -> Any:
    """Extrai um caminho com pontos, atravessando listas de dicionários."""
    parts = [part for part in str(path).split(".") if part]
    return _dig_parts(value, parts)


def _dig_parts(value: Any, parts: Sequence[str]) -> Any:
    if value is None:
        return None
    if not parts:
        return value
    head, rest = parts[0], parts[1:]
    if isinstance(value, dict):
        return _dig_parts(value.get(head), rest)
    if isinstance(value, list):
        collected: List[Any] = []
        for item in value:
            found = _dig_parts(item, parts)
            if isinstance(found, list):
                collected.extend(found)
            elif found is not None:
                collected.append(found)
        return collected or None
    return None


def _first(value: Any) -> Any:
    values = _flatten(value)
    return values[0] if values else None


def _hit_value(hit: Dict[str, Any], path: str) -> Any:
    """Lê um valor de um hit de agregação, tolerando hits de contexto aninhado.

    Num `top_hits` dentro de um agregado `nested`, o `_source` devolvido é o
    documento *aninhado* (não o documento raiz), pelo que a mesma etiqueta pode
    vir em `cpv.description` ou apenas em `description`.
    """
    source = hit.get("_source") or {}
    value = _first(_dig(source, path))
    if value is None and "." in path:
        value = _first(_dig(source, path.split(".")[-1]))
    return value


def _to_number(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(" ", "").replace("\u00a0", "")
    if not text:
        return None
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".") if text.rfind(",") > text.rfind(".") else text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def _fmt_money(value: Any) -> str:
    number = _to_number(value)
    if number is None:
        return "n/d"
    if abs(number) >= 1_000_000:
        return f"{number / 1_000_000:,.2f} M€".replace(",", " ")
    return f"{number:,.0f} €".replace(",", " ")


# --------------------------------------------------------------------------
# Índice de tipos
# --------------------------------------------------------------------------
def _ontology() -> Dict[str, Any]:
    return registry.load_ontology()


def object_types() -> List[Dict[str, Any]]:
    return _ontology()["object_types"]


def link_types() -> List[Dict[str, Any]]:
    return _ontology()["link_types"]


def actions() -> List[Dict[str, Any]]:
    return _ontology()["actions"]


def get_object_type(type_id: str) -> Dict[str, Any]:
    obj = next((item for item in object_types() if item["id"] == type_id), None)
    if not obj:
        raise KeyError(f"Tipo de objeto desconhecido: {type_id}")
    return obj


def _prop_map(obj_type: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {prop["id"]: prop for prop in obj_type.get("properties", [])}


def _pk_prop(obj_type: Dict[str, Any]) -> Dict[str, Any]:
    props = obj_type.get("properties", [])
    return next((prop for prop in props if prop.get("pk")), props[0] if props else {"id": "id"})


def _title_field(obj_type: Dict[str, Any]) -> str:
    return obj_type.get("title_field") or _pk_prop(obj_type)["id"]


def _scoped(obj_type: Dict[str, Any]) -> bool:
    return bool(obj_type.get("binding", {}).get("scoped") or obj_type.get("requires_session"))


def requires_session(obj_type: Dict[str, Any]) -> bool:
    """Indica se o tipo exige sessão iniciada (dados privados do CRM)."""
    return _scoped(obj_type)


def _object_label(obj_type: Dict[str, Any], item: Dict[str, Any]) -> str:
    title = item.get(_title_field(obj_type)) or item.get(_pk_prop(obj_type)["id"]) or "—"
    return str(title)


# --------------------------------------------------------------------------
# Construção de consultas (Elasticsearch)
# --------------------------------------------------------------------------
def _scope_clause(obj_type: Dict[str, Any], scope: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not _scoped(obj_type):
        return []
    if not scope:
        optional = bool(obj_type.get("binding", {}).get("optional_scope"))
        if optional:
            return []
        raise PermissionError(f"O tipo «{obj_type['label']}» exige sessão iniciada.")
    if scope.get("see_all"):
        return []
    return [{"term": {"owner_id": scope.get("user_id")}}]


def _scoped_out(obj_type: Dict[str, Any], scope: Optional[Dict[str, Any]]) -> bool:
    """True quando o tipo deve ser saltado por falta de sessão."""
    if not _scoped(obj_type):
        return False
    if scope:
        return False
    return not bool(obj_type.get("binding", {}).get("optional_scope"))


def _range_from_value(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for src, dst in (("min", "gte"), ("gte", "gte"), ("max", "lte"), ("lte", "lte"), ("gt", "gt"), ("lt", "lt")):
            if value.get(src) is not None:
                out[dst] = value[src]
        return out
    if isinstance(value, list) and len(value) == 2:
        return {"gte": value[0], "lte": value[1]}
    return {"gte": value, "lte": value}


def _filter_clause(prop: Dict[str, Any], value: Any) -> Optional[Dict[str, Any]]:
    field = prop.get("field")
    if not field or value is None or value == "":
        return None
    ptype = prop.get("type")
    if ptype in ("number", "date"):
        body = _range_from_value(value)
        if not body:
            return None
        clause: Dict[str, Any] = {"range": {field: body}}
    elif ptype in ("keyword", "enum"):
        values = [str(item) for item in _as_list(value)]
        clause = {"terms": {field: values}} if len(values) != 1 else {"term": {field: values[0]}}
    elif ptype == "boolean":
        clause = {"term": {field: bool(value)}}
    else:  # texto
        clause = {"match": {field: value}}
    where = prop.get("where")
    if where:
        prefix = prop.get("nested") or ""
        where_clauses = [
            {"term": {f"{prefix}.{key}" if prefix and "." not in key else key: value}}
            for key, value in where.items()
        ]
        clause = {"bool": {"must": [clause, *where_clauses]}}
    if prop.get("nested"):
        return {"nested": {"path": prop["nested"], "query": clause}}
    return clause


def _build_filters(obj_type: Dict[str, Any], filters: Optional[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[str]]:
    props = _prop_map(obj_type)
    clauses: List[Dict[str, Any]] = []
    unknown: List[str] = []
    for key, value in (filters or {}).items():
        if key in ("_raw", "search"):
            if key == "_raw" and isinstance(value, dict):
                clauses.append(value)
            continue
        prop = props.get(key)
        if not prop:
            unknown.append(key)
            continue
        clause = _filter_clause(prop, value)
        if clause:
            clauses.append(clause)
    return clauses, unknown


def _sort_body(obj_type: Dict[str, Any], sort: Optional[Any]) -> List[Dict[str, Any]]:
    props = _prop_map(obj_type)
    request = sort
    if isinstance(request, str):
        request = {"id": request, "order": "desc"}
    if isinstance(request, dict) and request.get("id"):
        prop = props.get(request["id"])
        if prop and prop.get("field"):
            order = "asc" if str(request.get("order", "desc")).lower() == "asc" else "desc"
            return [{prop["field"]: {"order": order, "missing": "_last"}}]
    default = obj_type.get("binding", {}).get("default_sort")
    if default and default.get("field"):
        return [{default["field"]: {"order": default.get("order", "desc"), "missing": "_last"}}]
    return []


def _map_document(obj_type: Dict[str, Any], source: Dict[str, Any], hit_id: Optional[str] = None) -> Dict[str, Any]:
    """Mapeia um documento de origem para as propriedades do tipo de objeto."""
    item: Dict[str, Any] = {}
    for prop in obj_type.get("properties", []):
        pid = prop["id"]
        if prop.get("field"):
            raw = _dig(source, prop["field"])
        elif pid in source:
            raw = source[pid]
        elif pid == "id":
            raw = hit_id
        elif pid == "idcontrato":
            raw = source.get("idcontrato") or hit_id
        else:
            raw = None
        if isinstance(raw, list):
            flat = _flatten(raw)
            raw = flat[0] if flat else None
        item[pid] = raw
    pk = _pk_prop(obj_type)["id"]
    id_field = obj_type.get("binding", {}).get("id_field")
    if item.get(pk) in (None, "") and hit_id and (pk == "id" or id_field == "_id"):
        item[pk] = hit_id
    item["_id"] = str(item.get(pk) if item.get(pk) is not None else (hit_id or ""))
    item["_label"] = _object_label(obj_type, item)
    return item


# --------------------------------------------------------------------------
# Resolvedores derivados
# --------------------------------------------------------------------------
def _company_item_from_search(entry: Dict[str, Any]) -> Dict[str, Any]:
    adjudicante = entry.get("adjudicante") or {}
    adjudicatario = entry.get("adjudicatario") or {}
    if adjudicante and adjudicatario:
        papel = "ambos"
    elif adjudicante:
        papel = "adjudicante"
    elif adjudicatario:
        papel = "adjudicatario"
    else:
        papel = None
    years = [value for value in (adjudicante.get("first_year"), adjudicatario.get("first_year")) if value]
    last_years = [value for value in (adjudicante.get("last_year"), adjudicatario.get("last_year")) if value]
    return {
        "nif": entry.get("nif"),
        "nome": entry.get("name") or entry.get("normalized_name"),
        "regiao": entry.get("region"),
        "papel": papel,
        "contratos": entry.get("contracts_total"),
        "valor_total": entry.get("total_value"),
        "contratos_adjudicante": adjudicante.get("contracts_count"),
        "contratos_adjudicatario": adjudicatario.get("contracts_count"),
        "valor_adjudicante": adjudicante.get("total_value"),
        "primeiro_ano": min(years) if years else None,
        "ultimo_ano": max(last_years) if last_years else None,
    }


# Quantas entidades (por NIF) a agregação devolve por papel. É uma amostra das
# entidades com mais contratos (ordenadas depois por valor em Python) — está
# declarado nos `notes` de cada resposta.
_COMPANY_TERMS_SIZE = 150
# Tempo-limite das consultas de agregação: nunca bloquear o chat/UI mais do que isto.
_AGG_TIMEOUT_SECONDS = 20


def _company_side_agg(path: str, nif_field: str, nome_field: str, size: int) -> Dict[str, Any]:
    return {
        "nested": {"path": path},
        "aggs": {
            "por_nif": {
                # Ordenar por `_count` é imediato; ordenar por uma sub-agregação
                # aninhada obrigaria o Elasticsearch a calcular o valor de todas
                # as entidades (milhares), provocando timeouts. A ordenação por
                # valor faz-se depois, em Python, sobre esta amostra.
                "terms": {"field": nif_field, "size": size, "order": {"_count": "desc"}},
                "aggs": {
                    "valor": {"reverse_nested": {}, "aggs": {"soma": {"sum": {"field": "precoContratual"}}}},
                    "anos": {"reverse_nested": {}, "aggs": {"stats": {"stats": {"field": "Ano"}}}},
                    "nome": {"top_hits": {"size": 1, "_source": [nome_field]}},
                },
            }
        },
    }


def _company_aggregate(payload: Dict[str, Any], scope: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Agrega empresas (por NIF) a partir dos contratos, sem cardinality aggs pesadas.

    Devolve as entidades mais relevantes (por valor contratual) entre as que
    correspondem à pesquisa/filtros — amostra declarada em `notes`.
    """
    client = payload.get("es") or get_es_client()
    if not client:
        return {"total": 0, "items": [], "exact": False, "notes": ["Elasticsearch indisponível."], "error": "Elasticsearch indisponível"}

    filters = payload.get("filters") or {}
    search = payload.get("search")
    doc_filters: List[Dict[str, Any]] = []
    if filters.get("ano"):
        doc_filters.append({"term": {"Ano": filters["ano"]}})
    region = filters.get("regiao")
    if region:
        if str(region) == UNSPECIFIED_LABEL:
            doc_filters.append(
                {
                    "bool": {
                        "should": [
                            {"bool": {"must_not": [{"exists": {"field": "NUTs"}}]}},
                            {"term": {"NUTs": ""}},
                        ],
                        "minimum_should_match": 1,
                    }
                }
            )
        else:
            doc_filters.append({"term": {"NUTs": region}})
    kinds = filters.get("tipo_contrato") or filters.get("procedimento")
    if kinds:
        field = "tipoContrato" if filters.get("tipo_contrato") else "tipoprocedimento"
        doc_filters.append({"terms": {field: [str(value) for value in _as_list(kinds)]}})
    nif = filters.get("nif")
    if nif:
        doc_filters.append(
            {
                "bool": {
                    "should": [
                        {"nested": {"path": "adjudicantes.parsed", "query": {"term": {"adjudicantes.parsed.nif": str(nif)}}}},
                        {"nested": {"path": "adjudicatarios.parsed", "query": {"term": {"adjudicatarios.parsed.nif": str(nif)}}}},
                    ],
                    "minimum_should_match": 1,
                }
            }
        )

    query: Dict[str, Any] = {"bool": {}}
    if doc_filters:
        query["bool"]["filter"] = doc_filters
    if isinstance(search, str) and search.strip():
        query["bool"]["must"] = {
            "bool": {
                "should": [
                    {"nested": {"path": "adjudicantes.parsed", "query": {"match": {"adjudicantes.parsed.nome": search.strip()}}}},
                    {"nested": {"path": "adjudicatarios.parsed", "query": {"match": {"adjudicatarios.parsed.nome": search.strip()}}}},
                ],
                "minimum_should_match": 1,
            }
        }
    if not query["bool"]:
        query = {"match_all": {}}

    try:
        resp = client.search(
            index=CONTRACTS_INDEX,
            body={
                "size": 0,
                "query": query,
                "aggs": {
                    "adjudicantes": _company_side_agg("adjudicantes.parsed", "adjudicantes.parsed.nif", "adjudicantes.parsed.nome", _COMPANY_TERMS_SIZE),
                    "adjudicatarios": _company_side_agg("adjudicatarios.parsed", "adjudicatarios.parsed.nif", "adjudicatarios.parsed.nome", _COMPANY_TERMS_SIZE),
                },
            },
            request_timeout=_AGG_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        logger.warning("Agregação de empresas falhou: %s", exc)
        return {
            "total": 0,
            "items": [],
            "exact": False,
            "notes": ["A agregação de empresas no Elasticsearch falhou (tempo-limite excedido) — tenta novamente."],
            "error": str(exc),
        }

    merged: Dict[str, Dict[str, Any]] = {}
    for agg_key, role in (("adjudicantes", "adjudicante"), ("adjudicatarios", "adjudicatario")):
        buckets = resp["aggregations"][agg_key]["por_nif"]["buckets"]
        for bucket in buckets:
            key = str(bucket.get("key") or "").strip()
            if not key:
                continue
            entry = merged.setdefault(
                key,
                {"nif": key, "name": key, "contracts_total": 0, "total_value": 0.0, "adjudicante": None, "adjudicatario": None},
            )
            hops = (bucket.get("nome") or {}).get("hits", {}).get("hits") or []
            if hops:
                name = _hit_value(hops[0], "adjudicantes.parsed.nome") or _hit_value(hops[0], "nome")
                if name:
                    entry["name"] = name
            value = ((bucket.get("valor") or {}).get("soma") or {}).get("value") or 0.0
            stats = (bucket.get("anos") or {}).get("stats") or {}
            entry[role] = {
                "contracts_count": bucket.get("doc_count", 0),
                "total_value": round(value, 2),
                "first_year": int(stats["min"]) if stats.get("min") is not None else None,
                "last_year": int(stats["max"]) if stats.get("max") is not None else None,
            }
            entry["contracts_total"] += bucket.get("doc_count", 0)
            entry["total_value"] += value

    items = [_company_item_from_search(entry) for entry in merged.values()]

    papel = filters.get("papel") or payload.get("role")
    if papel in ("adjudicante", "adjudicatario"):
        items = [item for item in items if item.get(f"contratos_{papel}")]
    if filters.get("min_contratos"):
        items = [item for item in items if (item.get("contratos") or 0) >= int(filters["min_contratos"])]
    if filters.get("valor") is not None:
        bounds = _range_from_value(filters["valor"])
        items = [
            item
            for item in items
            if (bounds.get("gte") is None or (item.get("valor_total") or 0) >= _to_number(bounds["gte"]))
            and (bounds.get("lte") is None or (item.get("valor_total") or 0) <= _to_number(bounds["lte"]))
        ]
    items.sort(key=lambda item: (item.get("valor_total") or 0, item.get("contratos") or 0), reverse=True)

    from_ = int(payload.get("from_") or 0)
    size = min(int(payload.get("size") or _DEFAULT_QUERY_SIZE), MAX_QUERY_SIZE)
    notes = [
        f"As empresas são agregadas dos contratos: amostra das {_COMPANY_TERMS_SIZE} entidades com mais contratos por papel, "
        f"ordenada por valor contratual (não é o universo completo)."
    ]
    if nif:
        notes.append("Filtro por NIF aplicado a ambos os papéis.")
    return {"total": len(items), "items": items[from_: from_ + size], "exact": False, "notes": notes}


def _resolve_companies(payload: Dict[str, Any], scope: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    return _company_aggregate(payload, scope)


def _resolve_public_entities(payload: Dict[str, Any], scope: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    filters = {**(payload.get("filters") or {}), "papel": "adjudicante"}
    result = _company_aggregate({**payload, "filters": filters}, scope)
    result["items"] = [item for item in result["items"] if item.get("contratos_adjudicante")]
    return result


def _people_from_news(payload: Dict[str, Any], scope: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    client = payload.get("es") or get_es_client()
    if not client:
        return []
    search = payload.get("search")
    wanted = payload.get("size") or 100
    try:
        resp = client.search(
            index="finance_news",
            body={
                "size": 0,
                "query": {"bool": {"filter": [{"nested": {"path": "entities", "query": {"term": {"entities.type": "pessoa"}}}}]}},
                "aggs": {
                    "pessoas": {
                        "nested": {"path": "entities"},
                        "aggs": {
                            "por_nome": {
                                "terms": {"field": "entities.name", "size": 400},
                                "aggs": {
                                    # `reverse_nested` é obrigatório: `published` é do documento raiz.
                                    "datas": {
                                        "reverse_nested": {},
                                        "aggs": {
                                            "minha": {"min": {"field": "published"}},
                                            "maxima": {"max": {"field": "published"}},
                                        },
                                    }
                                },
                            }
                        },
                    }
                },
            },
        )
        buckets = resp["aggregations"]["pessoas"]["por_nome"]["buckets"]
    except Exception as exc:  # pragma: no cover - depende do ES
        logger.warning("Falha a agregar pessoas das notícias: %s", exc)
        return []

    items = []
    for bucket in buckets:
        name = str(bucket.get("key") or "").strip()
        # Ruído da extração: siglas/tickers curtos em maiúsculas não são pessoas.
        if len(name) < 5 or (" " not in name and name.isupper()):
            continue
        if search and _normalize(search) not in _normalize(name) and _similarity(search, name) < 0.6:
            continue
        dates = bucket.get("datas") or {}
        items.append(
            {
                "id": name,
                "nome": name,
                "origem": "Notícias",
                "mencoes": bucket.get("doc_count"),
                "primeira_mencao": (dates.get("minha") or {}).get("value_as_string"),
                "ultima_mencao": (dates.get("maxima") or {}).get("value_as_string"),
            }
        )
    return items[: int(wanted)]


def _resolve_people(payload: Dict[str, Any], scope: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    items: List[Dict[str, Any]] = []
    notes: List[str] = []
    size = payload.get("size") or _DEFAULT_QUERY_SIZE
    search = payload.get("search")

    # Cargos do CRM (só com sessão; são dados privados do utilizador).
    if scope:
        contact_type = next((item for item in object_types() if item["id"] == "contacto"), None)
        if contact_type:
            try:
                crm = _query_es(contact_type, {"search": search, "size": size, "from_": 0}, scope)
                for item in crm["items"]:
                    items.append(
                        {
                            "id": item.get("id"),
                            "nome": item.get("nome"),
                            "cargo": item.get("cargo"),
                            "organizacao": item.get("nome_conta"),
                            "email": item.get("email"),
                            "telefone": item.get("telefone") or item.get("telemovel"),
                            "linkedin": item.get("linkedin"),
                            "conta_id": item.get("conta_id"),
                            "origem": "CRM",
                        }
                    )
            except Exception as exc:  # pragma: no cover
                notes.append(f"Não foi possível consultar os contactos do CRM: {exc}")
    else:
        notes.append("Sem sessão iniciada: os cargos do CRM não entram nos resultados (dados privados).")

    notes.append("Menções em notícias derivam do campo `entities` (tipo «pessoa») — cobertura limitada às notícias indexadas.")
    items.extend(_people_from_news({**payload, "size": size, "search": search}, scope))

    # Deduplica por nome normalizado, preferindo a entrada do CRM (tem cargo).
    merged: Dict[str, Dict[str, Any]] = {}
    for item in items:
        key = _normalize(item.get("nome"))
        if not key:
            continue
        current = merged.get(key)
        if current is None:
            merged[key] = item
        else:
            current["mencoes"] = sum(filter(None, [current.get("mencoes"), item.get("mencoes")])) or None
            if not current.get("cargo") and item.get("cargo"):
                current["cargo"] = item["cargo"]
            if current.get("origem") != item.get("origem"):
                current["origem"] = "CRM+Notícias"
    values = sorted(merged.values(), key=lambda item: (item.get("mencoes") or 0, item.get("cargo") or ""), reverse=True)
    if search:
        needle = _normalize(search)
        values.sort(key=lambda item: (needle in _normalize(item.get("nome")), _similarity(search, item.get("nome") or "")), reverse=True)
    # Remove duplicados mantendo a ordem.
    seen: set = set()
    deduped = []
    for item in values:
        key = _normalize(item.get("nome"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return {"total": len(deduped), "items": deduped[:size], "notes": notes, "exact": False}


RESOLVERS = {
    "companies": _resolve_companies,
    "public_entities": _resolve_public_entities,
    "people": _resolve_people,
}


# --------------------------------------------------------------------------
# Consulta de objetos
# --------------------------------------------------------------------------
def _query_es(
    obj_type: Dict[str, Any],
    payload: Dict[str, Any],
    scope: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    binding = obj_type["binding"]
    index = binding["index"]
    client = payload.get("es") or get_es_client()
    if not client:
        return {"total": 0, "items": [], "notes": ["Elasticsearch indisponível."], "error": "Elasticsearch indisponível"}

    clauses = _scope_clause(obj_type, scope)
    filter_clauses, unknown = _build_filters(obj_type, payload.get("filters"))
    clauses.extend(filter_clauses)
    if binding.get("filter"):
        clauses.append(binding["filter"])

    search = payload.get("search")
    query: Dict[str, Any] = {"bool": {}}
    if clauses:
        query["bool"]["filter"] = clauses
    if isinstance(search, str) and search.strip() and binding.get("search_fields"):
        query["bool"]["must"] = {
            "multi_match": {
                "query": search.strip(),
                "fields": binding["search_fields"],
                "operator": "and",
            }
        }
    if not query["bool"]:
        query = {"match_all": {}}

    size = min(int(payload.get("size") or _DEFAULT_QUERY_SIZE), MAX_QUERY_SIZE)
    body: Dict[str, Any] = {
        "query": query,
        "size": size,
        "from": int(payload.get("from_") or 0),
        "track_total_hits": True,
    }
    sort = _sort_body(obj_type, payload.get("sort"))
    if sort:
        body["sort"] = sort

    notes: List[str] = []
    if unknown:
        notes.append("Filtros ignorados (não existem neste tipo): " + ", ".join(sorted(unknown)))
    try:
        resp = client.search(index=index, body=body, request_timeout=_AGG_TIMEOUT_SECONDS)
    except Exception as exc:
        logger.warning("Consulta da ontologia falhou (%s): %s", obj_type["id"], exc)
        return {"total": 0, "items": [], "notes": notes, "error": str(exc)}

    items = []
    for hit in resp["hits"]["hits"]:
        item = _map_document(obj_type, hit.get("_source") or {}, hit.get("_id"))
        item["_score"] = hit.get("_score")
        items.append(item)
    return {
        "total": (resp["hits"]["total"] or {}).get("value", len(items)),
        "items": items,
        "exact": True,
        "notes": notes,
    }


def _aggregation_terms_body(obj_type: Dict[str, Any], binding: Dict[str, Any], search: Optional[str], size: int) -> Dict[str, Any]:
    terms: Dict[str, Any] = {"field": binding["field"], "size": int(binding.get("size") or 2000)}
    if binding.get("missing_label"):
        terms["missing"] = binding["missing_label"]
    agg: Dict[str, Any] = {"terms": terms}
    sub: Dict[str, Any] = {}
    for name, metric in (binding.get("metrics") or {}).items():
        kind = metric.get("kind")
        if kind == "count":
            continue
        if kind in ("sum", "min", "max", "avg"):
            sub[name] = {kind: {"field": metric["field"]}}
        elif kind == "top_hits":
            spec: Dict[str, Any] = {"size": metric.get("size", 1)}
            if metric.get("sort"):
                spec["sort"] = metric["sort"]
            if metric.get("source"):
                spec["_source"] = metric["source"]
            sub[name] = {"top_hits": spec}
    label_agg = binding.get("label_agg")
    if label_agg and label_agg.get("kind") == "top_hits":
        spec = {"size": label_agg.get("size", 1)}
        if label_agg.get("source"):
            spec["_source"] = label_agg["source"]
        sub["_label_hit"] = {"top_hits": spec}
    if sub:
        agg["aggs"] = sub

    if binding.get("nested"):
        wrapper = {"nested_agg": {"nested": {"path": binding["nested"]}, "aggs": {"values": agg}}}
        aggs = wrapper
    else:
        aggs = {"values": agg}
    return {"size": 0, "query": {"match_all": {}}, "aggs": aggs}


def _query_aggregation(
    obj_type: Dict[str, Any],
    payload: Dict[str, Any],
    scope: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    binding = obj_type["binding"]
    client = payload.get("es") or get_es_client()
    if not client:
        return {"total": 0, "items": [], "notes": ["Elasticsearch indisponível."], "error": "Elasticsearch indisponível"}
    body = _aggregation_terms_body(obj_type, binding, payload.get("search"), payload.get("size") or 0)
    try:
        resp = client.search(index=binding["index"], body=body, request_timeout=_AGG_TIMEOUT_SECONDS)
    except Exception as exc:
        logger.warning("Agregação da ontologia falhou (%s): %s", obj_type["id"], exc)
        return {"total": 0, "items": [], "notes": [], "error": str(exc)}

    nested = binding.get("nested")
    node = resp["aggregations"]
    if nested:
        node = node.get("nested_agg", {})
    buckets = (node.get("values") or {}).get("buckets", [])

    missing_label = binding.get("missing_label")
    metrics = binding.get("metrics") or {}
    props = _prop_map(obj_type)
    pk = _pk_prop(obj_type)["id"]
    items: List[Dict[str, Any]] = []
    for bucket in buckets:
        key = bucket.get("key")
        if isinstance(key, bool):
            key = str(key)
        if key in (None, ""):
            if not missing_label:
                continue
            key = missing_label
        item: Dict[str, Any] = {pk: key, "_id": str(key), "_count": bucket.get("doc_count", 0)}
        for name, metric in metrics.items():
            if metric.get("kind") == "count":
                item[name] = bucket.get("doc_count", 0)
            elif metric.get("kind") == "top_hits":
                hits = (bucket.get(name) or {}).get("hits", {}).get("hits", [])
                if hits:
                    path = ".".join(metric.get("path") or [name])
                    item[name] = _hit_value(hits[0], path)
            else:
                item[name] = (bucket.get(name) or {}).get("value")
        # Propriedades com o mesmo nome da métrica (ex.: contratos = doc_count).
        for pid, prop in props.items():
            if pid in item:
                continue
            if prop.get("type") == "number" and bucket.get("doc_count") is not None and pid == "contratos":
                item[pid] = bucket["doc_count"]
        label_hit = _first((bucket.get("_label_hit") or {}).get("hits", {}).get("hits"))
        if label_hit:
            path = ".".join((binding.get("label_agg") or {}).get("path") or ["cpv", "description"])
            label = _hit_value(label_hit, path)
            if label:
                item["descricao"] = label
        item["_label"] = _object_label(obj_type, item)
        if missing_label and key == missing_label:
            item["_unspecified"] = True
        items.append(item)

    search = payload.get("search")
    if isinstance(search, str) and search.strip():
        needle = _normalize(search)
        items = [item for item in items if needle in _normalize(item.get(_title_field(obj_type))) or needle in _normalize(item.get(pk))]

    # Filtros aplicados em memória (todos os buckets do agregado já foram obtidos).
    filters = payload.get("filters") or {}
    if filters:
        for pid, value in filters.items():
            prop = props.get(pid)
            if not prop or value in (None, ""):
                continue
            if prop.get("pk"):
                wanted = _normalize(value)
                items = [item for item in items if _normalize(item.get(pid)) == wanted]
            elif prop.get("type") == "number":
                bounds = _range_from_value(value)
                items = [
                    item
                    for item in items
                    if _to_number(item.get(pid)) is not None
                    and (bounds.get("gte") is None or _to_number(item.get(pid)) >= _to_number(bounds["gte"]))
                    and (bounds.get("lte") is None or _to_number(item.get(pid)) <= _to_number(bounds["lte"]))
                ]
            elif prop.get("type") in ("keyword", "enum"):
                wanted = {_normalize(entry) for entry in _as_list(value)}
                items = [item for item in items if _normalize(item.get(pid)) in wanted]

    sort_field = None
    if isinstance(payload.get("sort"), dict):
        sort_field = payload["sort"].get("id")
    elif isinstance(payload.get("sort"), str):
        sort_field = payload["sort"]
    if not sort_field:
        metric_names = [name for name, metric in metrics.items()] or ["contratos"]
        sort_field = "contratos" if "contratos" in props else metric_names[0]
    reverse = True
    if isinstance(payload.get("sort"), dict) and str(payload["sort"].get("order", "desc")).lower() == "asc":
        reverse = False
    items.sort(key=lambda item: (_to_number(item.get(sort_field)) or item.get("_count") or 0), reverse=reverse)

    size = min(int(payload.get("size") or _DEFAULT_QUERY_SIZE), MAX_QUERY_SIZE)
    total = len(items)
    page = items[int(payload.get("from_") or 0): int(payload.get("from_") or 0) + size]
    notes = [
        f"Agregado sobre {binding['index']}"
        + (f" (campo aninhado `{binding['nested']}`)" if binding.get("nested") else "")
        + "; os totais provêm de agregações do Elasticsearch."
    ]
    bucket_limit = int(binding.get("size") or 2000)
    if len(buckets) >= bucket_limit:
        notes.append(f"Amostra de {bucket_limit} valores mais frequentes (existem mais).")
    return {"total": total, "items": page, "exact": len(buckets) < bucket_limit, "notes": notes}


def _cache_key(type_id: str, payload: Dict[str, Any], scope: Optional[Dict[str, Any]]) -> str:
    return "|".join(
        [
            type_id,
            str(payload.get("search") or ""),
            repr(sorted((payload.get("filters") or {}).items())) if isinstance(payload.get("filters"), dict) else str(payload.get("filters")),
            str(payload.get("size")),
            str(payload.get("from_")),
            str(payload.get("sort")),
            (scope or {}).get("user_id") or "anon",
            "all" if (scope or {}).get("see_all") else "own",
        ]
    )


def _cache_get(key: str) -> Optional[Any]:
    hit = _query_cache.get(key)
    if not hit:
        return None
    stamp, value = hit
    if time.time() - stamp > _QUERY_TTL:
        _query_cache.pop(key, None)
        return None
    return value


def _cache_set(key: str, value: Any) -> None:
    if len(_query_cache) >= _CACHE_MAX:
        _query_cache.clear()
    _query_cache[key] = (time.time(), value)


def clear_cache() -> None:
    """Invalida a cache de consultas (usado quando a ontologia é alterada)."""
    _query_cache.clear()


def query_objects(
    type_id: str,
    search: Optional[str] = None,
    filters: Optional[Dict[str, Any]] = None,
    size: int = _DEFAULT_QUERY_SIZE,
    from_: int = 0,
    sort: Optional[Any] = None,
    scope: Optional[Dict[str, Any]] = None,
    es: Any = None,
) -> Dict[str, Any]:
    """Consulta objetos de um tipo, com pesquisa, filtros e ordenação."""
    obj_type = get_object_type(type_id)
    binding = obj_type.get("binding", {})
    payload = {"search": search, "filters": filters or {}, "size": size, "from_": from_, "sort": sort, "es": es}
    kind = binding.get("kind")

    cache_key = _cache_key(type_id, payload, scope) if es is None else None
    if cache_key:
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached

    if kind == "derived":
        if _scoped_out(obj_type, scope):
            raise PermissionError(f"O tipo «{obj_type['label']}» exige sessão iniciada.")
        resolver = RESOLVERS.get(binding.get("resolver") or "")
        if not resolver:
            raise KeyError(f"Resolvedor desconhecido: {binding.get('resolver')}")
        result = resolver(payload, scope)
    elif kind == "aggregation":
        result = _query_aggregation(obj_type, payload, scope)
    else:
        result = _query_es(obj_type, payload, scope)

    out = {
        "type": type_id,
        "label": obj_type["label"],
        "source_kind": kind,
        "query": {"search": search, "filters": filters or {}, "sort": sort, "size": size, "from": from_},
        "total": result.get("total", 0),
        "items": [_pick_object_item(obj_type, item) for item in result.get("items", [])],
        "exact": result.get("exact", True),
        "notes": result.get("notes", []),
    }
    if result.get("error"):
        out["error"] = result["error"]
    if cache_key and not out.get("error"):
        _cache_set(cache_key, out)
    return out


def _pick_object_item(obj_type: Dict[str, Any], item: Dict[str, Any]) -> Dict[str, Any]:
    """Mantém as propriedades definidas no tipo (remove campos internos do ES)."""
    out = {key: value for key, value in item.items() if not key.startswith("_") or key in ("_id", "_label", "_score", "_count")}
    out["_id"] = str(item.get("_id") or item.get(_pk_prop(obj_type)["id"]) or "")
    out["_label"] = item.get("_label") or _object_label(obj_type, item)
    return out


# --------------------------------------------------------------------------
# Objeto individual
# --------------------------------------------------------------------------
def _fetch_raw(type_id: str, object_id: str, scope: Optional[Dict[str, Any]], es: Any = None) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    obj_type = get_object_type(type_id)
    binding = obj_type.get("binding", {})
    if binding.get("kind") != "es":
        result = query_objects(type_id, filters={_pk_prop(obj_type)["id"]: object_id}, size=1, scope=scope, es=es)
        item = (result.get("items") or [None])[0]
        return obj_type, item
    if _scoped_out(obj_type, scope):
        raise PermissionError(f"O tipo «{obj_type['label']}» exige sessão iniciada.")
    client = es or get_es_client()
    if not client:
        return obj_type, None
    id_field = binding.get("id_field") or _pk_prop(obj_type)["id"]
    source: Optional[Dict[str, Any]] = None
    if id_field == "_id":
        try:
            source = client.get(index=binding["index"], id=object_id).get("_source")
        except Exception:
            source = None
    if source is None:
        clauses = [{("terms" if isinstance(object_id, list) else "term"): {id_field: object_id}}]
        clauses.extend(_scope_clause(obj_type, scope))
        if binding.get("filter"):
            clauses.append(binding["filter"])
        try:
            resp: Dict[str, Any] = client.search(
                index=binding["index"], body={"query": {"bool": {"filter": clauses}}, "size": 1}
            )
            hits = resp["hits"]["hits"]
            source = hits[0].get("_source") if hits else None
            if hits and not source:
                return obj_type, None
        except Exception as exc:
            logger.warning("Obtenção de objeto falhou (%s/%s): %s", type_id, object_id, exc)
            return obj_type, None
    if source is None and not isinstance(object_id, list):
        # Objetos cujo identificador é o próprio `_id` do documento (ex.: firmas sem NIPC).
        try:
            source = client.get(index=binding["index"], id=object_id).get("_source")
        except Exception:
            source = None
    if source is None:
        return obj_type, None
    hit_id = str(source.get(id_field) if source.get(id_field) is not None else object_id)
    return obj_type, {"_source": source, "_mapped": _map_document(obj_type, source, hit_id)}


def get_object(
    type_id: str,
    object_id: str,
    scope: Optional[Dict[str, Any]] = None,
    include_source: bool = False,
    with_links: bool = False,
    es: Any = None,
) -> Dict[str, Any]:
    """Devolve um objeto (propriedades + ligações, opcionalmente o documento de origem)."""
    obj_type, raw = _fetch_raw(type_id, object_id, scope, es)
    if raw is None:
        return {"type": type_id, "id": object_id, "found": False, "object": None, "notes": ["Objeto não encontrado."]}
    mapped = raw.get("_mapped") or (raw if "properties" not in raw else _pick_object_item(obj_type, raw))
    item = _pick_object_item(obj_type, mapped)
    out: Dict[str, Any] = {
        "type": type_id,
        "label": obj_type["label"],
        "id": item["_id"] or str(object_id),
        "found": True,
        "object": item,
        "notes": [],
    }
    if include_source and "_source" in raw:
        out["source_document"] = raw["_source"]
    if with_links:
        out["links"] = object_links(type_id, object_id, scope=scope, es=es)
    return out


# --------------------------------------------------------------------------
# Ligações
# --------------------------------------------------------------------------
def _link_index(for_type: str) -> List[Tuple[Dict[str, Any], str]]:
    """Ligações aplicáveis a um tipo: (definição, direção) com `forward`/`reverse`."""
    out: List[Tuple[Dict[str, Any], str]] = []
    for link in link_types():
        if link["from"] == for_type:
            out.append((link, "forward"))
        elif link["to"] == for_type:
            out.append((link, "reverse"))
    return out


def links_for_type(type_id: str) -> List[Dict[str, Any]]:
    """Descreve as ligações de um tipo (com as inversas), para a UI e para a IA."""
    out = []
    for link, direction in _link_index(type_id):
        other = link["to"] if direction == "forward" else link["from"]
        try:
            other_label = get_object_type(other)["label"]
        except KeyError:
            continue
        binding = link.get("binding") if direction == "forward" else link.get("reverse")
        out.append(
            {
                "id": link["id"],
                "direction": direction,
                "label": link["label"] if direction == "forward" else f"{link['label']} (inverso)",
                "description": link.get("description"),
                "other_type": other,
                "other_label": other_label,
                "cardinality": link.get("cardinality"),
                "available": bool(binding),
                "note": None if binding else "Sem ligação inversa definida na ontologia.",
            }
        )
    return out


def _hits_to_objects(obj_type: Dict[str, Any], hits: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    items = []
    for hit in hits:
        source = hit.get("_source") or {}
        items.append(_pick_object_item(obj_type, _map_document(obj_type, source, hit.get("_id"))))
    return items


def _synthesize(obj_type: Dict[str, Any], object_id: str, reason: str) -> Dict[str, Any]:
    pk = _pk_prop(obj_type)["id"]
    return {pk: object_id, "_id": object_id, "_label": object_id, "_unresolved": True, "_note": reason}


def _resolve_link_binding(
    link: Dict[str, Any],
    binding: Dict[str, Any],
    obj_type: Dict[str, Any],
    target_type: Dict[str, Any],
    raw: Dict[str, Any],
    object_id: str,
    size: int,
    scope: Optional[Dict[str, Any]],
    es: Any,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Resolve uma ligação (já com a direção escolhida) para objetos do tipo alvo."""
    notes: List[str] = []
    client = es or get_es_client()
    kind = binding.get("kind")
    target_pk = _pk_prop(target_type)["id"]

    if _scoped_out(target_type, scope):
        return [], [f"«{target_type['label']}» exige sessão iniciada (dados privados do CRM)."]

    if kind == "union":
        collected: Dict[str, Dict[str, Any]] = {}
        for part in binding.get("parts") or []:
            items, part_notes = _resolve_link_binding(
                link, part, obj_type, target_type, raw, object_id, size, scope, es
            )
            for item in items:
                key = str(item.get("_id") or item.get(target_pk) or "")
                if key and key not in collected:
                    collected[key] = item
            for note in part_notes:
                if note not in notes:
                    notes.append(note)
        merged = list(collected.values())[:size]
        if len(collected) > len(merged):
            notes.append(f"{len(collected) - len(merged)} objetos adicionais omitidos (limite de {size}).")
        return merged, notes

    if kind == "cross_ref":
        field = binding.get("from_field")
        value = _first(_dig(raw, field)) if field else None
        if not value:
            return [], []
        target_id = str(value)
        try:
            detail = get_object(target_type["id"], target_id, scope=scope, es=es)
        except PermissionError as exc:
            return [], [str(exc)]
        if detail.get("found") and detail.get("object"):
            return [detail["object"]], notes
        return [_synthesize(target_type, target_id, f"não encontrado por `{field}`")], [
            f"«{value}» não existe como {target_type['label']} na plataforma."
        ]

    if kind == "field_values":
        field = binding.get("field")
        raw_values = _dig(raw, field)
        values: List[str] = []
        items = raw_values if isinstance(raw_values, list) else ([raw_values] if raw_values is not None else [])
        where = binding.get("where") or {}
        value_path = binding.get("value_path")
        for item in items:
            if isinstance(item, dict):
                if where and any(_normalize(item.get(key)) != _normalize(value) for key, value in where.items()):
                    continue
                found = _dig(item, value_path) if value_path else None
                values.extend(str(value) for value in _flatten(found))
            elif item not in (None, ""):
                values.append(str(item))
        missing_label = binding.get("missing_label")
        if not values and missing_label:
            values = [missing_label]
        objects: List[Dict[str, Any]] = []
        seen: set = set()
        for value in values[: size]:
            if value in seen:
                continue
            seen.add(value)
            if target_type.get("binding", {}).get("kind") == "aggregation":
                try:
                    found = query_objects(target_type["id"], filters={target_pk: value}, size=1, scope=scope, es=es)
                except PermissionError as exc:
                    return objects, [str(exc)]
                if found.get("items"):
                    objects.append(found["items"][0])
                elif found.get("total"):
                    objects.append(found["items"][0])
                else:
                    objects.append(_synthesize(target_type, value, "valor sem agregado correspondente"))
            else:
                try:
                    detail = get_object(target_type["id"], value, scope=scope, es=es)
                except PermissionError as exc:
                    return objects, [str(exc)]
                objects.append(detail.get("object") or _synthesize(target_type, value, "não encontrado"))
        return objects, notes

    # Ligações que consultam um índice alvo (term / nested_terms / term_value).
    if not client:
        return [], ["Elasticsearch indisponível."]
    index = binding.get("index")
    field = binding.get("field")
    clauses: List[Dict[str, Any]] = []
    if binding.get("nested"):
        inner: Dict[str, Any] = {"term": {field: object_id}}
        where = binding.get("where")
        if where:
            inner = {
                "bool": {
                    "must": [
                        inner,
                        *[
                            {"term": {f"{binding['nested']}.{key}": value}}
                            if "." not in key
                            else {"term": {key: value}}
                            for key, value in where.items()
                        ],
                    ]
                }
            }
        clauses.append({"nested": {"path": binding["nested"], "query": inner}})
    else:
        clauses.append({"term": {field: object_id}})
    if binding.get("filter"):
        clauses.append(binding["filter"])
    try:
        resp = client.search(
            index=index,
            body={"query": {"bool": {"filter": clauses}}, "size": max(1, min(size, 50)), "track_total_hits": True},
        )
        hits = resp["hits"]["hits"]
        total = (resp["hits"]["total"] or {}).get("value", len(hits))
        if total > len(hits):
            notes.append(f"{total - len(hits)} objetos adicionais não listados (limite de {len(hits)}).")
        return _hits_to_objects(target_type, hits), notes
    except Exception as exc:
        logger.warning("Ligação %s falhou: %s", link["id"], exc)
        return [], [f"Consulta da ligação falhou: {exc}"]


def object_links(
    type_id: str,
    object_id: str,
    link_id: Optional[str] = None,
    size: int = 10,
    scope: Optional[Dict[str, Any]] = None,
    es: Any = None,
) -> Dict[str, Any]:
    """Devolve os objetos ligados a um objeto (por ligação, com inversas quando existem)."""
    obj_type, raw = _fetch_raw(type_id, object_id, scope, es)
    if raw is None:
        return {"type": type_id, "id": object_id, "found": False, "links": []}
    source = raw.get("_source")
    if source is None:
        # Tipos derivados/agregados: usa as propriedades já normalizadas como "documento".
        source = raw.get("_mapped") or raw

    size = max(1, min(int(size or 10), registry.load_ontology()["limits"]["max_links_per_object"]))
    results = []
    for link, direction in _link_index(type_id):
        if link_id and link["id"] != link_id:
            continue
        binding = link.get("binding") if direction == "forward" else link.get("reverse")
        other_id = link["to"] if direction == "forward" else link["from"]
        try:
            other_type = get_object_type(other_id)
        except KeyError:
            continue
        entry: Dict[str, Any] = {
            "id": link["id"],
            "direction": direction,
            "label": link["label"] if direction == "forward" else f"{link['label']} (inverso)",
            "other_type": other_id,
            "other_label": other_type["label"],
            "cardinality": link.get("cardinality"),
            "available": bool(binding),
            "items": [],
            "notes": [],
        }
        if not binding:
            # Ligações sem inverso definido não entram na navegação (só na documentação).
            continue
        try:
            items, notes = _resolve_link_binding(link, binding, obj_type, other_type, source, object_id, size, scope, es)
        except PermissionError as exc:
            items, notes = [], [str(exc)]
        entry["items"] = items
        entry["count"] = len(items)
        entry["notes"] = notes
        results.append(entry)
    return {"type": type_id, "id": object_id, "found": True, "label": obj_type["label"], "links": results}


# --------------------------------------------------------------------------
# Resolução de entidades
# --------------------------------------------------------------------------
def _extract_mentions(text: str) -> List[Dict[str, str]]:
    """Extrai menções tipadas do texto: NIF, citação, frase com maiúsculas, ticker."""
    if not text:
        return []
    out: List[Dict[str, str]] = []
    seen: set = set()

    def add(value: str, kind: str) -> None:
        cleaned = value.strip(" \t\n.,;:!?()[]{}«»\"'|")
        # Remove conectores no fim (ex.: "EDP e" → "EDP").
        tokens = [token for token in cleaned.split() if token]
        while len(tokens) > 1 and _normalize(tokens[-1]) in _CONNECTORS:
            tokens.pop()
        cleaned = " ".join(tokens)
        key = _normalize(cleaned)
        if len(cleaned) < 3 or not key or key in seen or key in _STOPWORDS:
            return
        seen.add(key)
        out.append({"text": cleaned, "kind": kind})

    for match in _NIF_RE.finditer(text):
        add(match.group(1), "nif")
    # Códigos antes das frases: «PT150» deve ser código de região, não nome de empresa.
    for match in _CPV_RE.finditer(text):
        add(match.group(1), "code")
    for match in _NUTS_RE.finditer(text):
        add(match.group(1), "code")
    for match in _QUOTED_RE.finditer(text):
        add(match.group(1), "quoted")
    for match in _CAPS_RE.finditer(text):
        candidate = match.group(1)
        tokens = [token for token in re.split(r"\s+", candidate) if token]
        meaningful = [
            token
            for token in tokens
            if _normalize(token) not in _STOPWORDS and _normalize(token) not in _GENERIC_WORDS and len(token) > 2
        ]
        if not meaningful:
            continue
        if len(tokens) == 1:
            # Siglas curtas (EDP, GALP, NOS): só interessam se existirem como
            # ticker indexado ou como nome de empresa — tratado em `resolve_entities`.
            add(candidate, "ticker" if len(tokens[0]) <= 3 else "phrase")
            continue
        add(candidate, "phrase")
    for match in _TICKER_RE.finditer(text):
        add(match.group(1), "ticker")

    order = {"nif": 0, "code": 1, "quoted": 2, "phrase": 3, "ticker": 4}
    out.sort(key=lambda entry: (order.get(entry["kind"], 9), -len(entry["text"])))
    return out[:10]


def _known_tickers(es: Any = None) -> List[str]:
    now = time.time()
    if _ticker_cache["values"] and now - _ticker_cache["at"] < _TICKER_TTL:
        return list(_ticker_cache["values"])
    try:
        values = list_indexed_tickers(es=es) or []
    except Exception:
        values = []
    _ticker_cache.update({"at": now, "values": values})
    return list(values)


def _candidate_score(mention: str, obj_type: Dict[str, Any], item: Dict[str, Any]) -> Tuple[float, str]:
    pk = _pk_prop(obj_type)["id"]
    if str(item.get(pk) or "") == mention:
        return 1.0, f"identificador exato ({pk})"
    best = 0.0
    best_field = ""
    for prop in obj_type.get("properties", []):
        if not prop.get("searchable"):
            continue
        value = item.get(prop["id"])
        if value in (None, ""):
            continue
        score = _similarity(str(mention), str(value))
        if score > best:
            best, best_field = score, prop["label"]
    if best == 0.0:
        title = _object_label(obj_type, item)
        best, best_field = _similarity(mention, title), "nome"
    return round(best, 3), best_field


def _candidate(mention: str, obj_type: Dict[str, Any], item: Dict[str, Any], score: float, matched_on: str) -> Dict[str, Any]:
    return {
        "mention": mention,
        "type": obj_type["id"],
        "type_label": obj_type["label"],
        "domain": obj_type["domain"],
        "object": item,
        "confidence": round(score, 3),
        "matched_on": matched_on,
    }


# Tipos pesquisados por nome próprio, pela ordem em que são tentados.
# `cpv` e `regiao` ficam de fora: são agregações caras sobre o índice de
# contratos e as pessoas não os nomeiam em linguagem natural («Lisboa» não é o
# valor do campo NUTs). Resolvem-se por código, quando o texto o parece.
_NAME_TYPES = ("marca", "firma", "topico", "conta", "contacto", "pessoa")
_CODE_TYPES = {"cpv": re.compile(r"\d{8}(-\d)?"), "regiao": re.compile(r"[A-Z]{2}[A-Z0-9]{2,4}")}
_QUERY_BUDGET = 12


def _company_candidates(
    mention: str,
    type_id: str,
    by_id: Dict[str, Dict[str, Any]],
    items: Sequence[Dict[str, Any]],
    out: List[Dict[str, Any]],
) -> None:
    """Gera candidatos de Empresa/Entidade Pública a partir de um resultado de empresas."""
    for item in items:
        for candidate_type in ("empresa", "entidade_publica"):
            obj_type = by_id.get(candidate_type)
            if not obj_type:
                continue
            if candidate_type == "entidade_publica" and not item.get("contratos_adjudicante"):
                continue
            score, matched_on = _candidate_score(mention, obj_type, item)
            if score >= 0.35:
                out.append(_candidate(mention, obj_type, item, score, matched_on))


def resolve_entities(
    text: str,
    limit: int = 5,
    type_ids: Optional[Sequence[str]] = None,
    scope: Optional[Dict[str, Any]] = None,
    es: Any = None,
) -> Dict[str, Any]:
    """Resolve texto livre (NIF, nome, ticker) em objetos canónicos da ontologia."""
    ontology = _ontology()
    mentions = _extract_mentions(text)
    allowed = set(type_ids) if type_ids else None
    known_tickers = {ticker.upper() for ticker in _known_tickers(es)}
    resolvable = [
        obj
        for obj in ontology["object_types"]
        if obj.get("resolvable") and not _scoped_out(obj, scope) and (allowed is None or obj["id"] in allowed)
    ]
    by_id = {obj["id"]: obj for obj in resolvable}
    candidates: List[Dict[str, Any]] = []
    notes: List[str] = []
    queries = 0
    company_cache: Dict[str, List[Dict[str, Any]]] = {}

    def company_items(phrase: str) -> List[Dict[str, Any]]:
        key = _normalize(phrase)
        if key not in company_cache:
            try:
                company_cache[key] = query_objects("empresa", search=phrase, size=3, scope=scope, es=es).get("items", [])
            except Exception as exc:  # pragma: no cover - depende do ES
                notes.append(f"Pesquisa de empresas falhou: {exc}")
                company_cache[key] = []
        return company_cache[key]

    for mention in mentions:
        mtext, kind = mention["text"], mention["kind"]

        if kind == "ticker":
            symbol = mtext.upper()
            if symbol in known_tickers and "ticker" in by_id:
                queries += 1
                try:
                    found = query_objects("ticker", filters={"simbolo": symbol}, size=1, scope=scope, es=es)
                except Exception:
                    found = {"items": []}
                for item in found.get("items", []):
                    candidates.append(_candidate(mtext, by_id["ticker"], item, 0.95, "símbolo indexado"))
                continue
            # Siglas genéricas (NIF, CPV, CRM) só gastariam consultas.
            if _normalize(symbol) in _GENERIC_WORDS:
                continue
            if "empresa" in by_id and queries < _QUERY_BUDGET:
                queries += 1
                _company_candidates(mtext, "empresa", by_id, company_items(mtext), candidates)
                continue
            continue

        if kind == "code":
            # CPV e NUTS identificam-se pelo próprio código (exato ou por prefixo).
            for code_type, pattern in _CODE_TYPES.items():
                obj_type = by_id.get(code_type)
                if not obj_type or queries >= _QUERY_BUDGET:
                    continue
                token = mtext.strip().upper()
                if not pattern.fullmatch(token):
                    continue
                queries += 1
                pk = _pk_prop(obj_type)["id"]
                try:
                    found = query_objects(code_type, filters={pk: token}, size=1, scope=scope, es=es)
                    if not found.get("items"):
                        # Região guarda «PT150 - Algarve»: o código é um prefixo.
                        found = query_objects(code_type, search=token, size=1, scope=scope, es=es)
                except Exception:
                    continue
                for item in found.get("items", []):
                    candidates.append(_candidate(mtext, obj_type, item, 0.95, "código identificado"))
            continue

        if kind == "nif":
            for type_id in ("empresa", "firma", "conta", "entidade_publica"):
                obj_type = by_id.get(type_id)
                if not obj_type or queries >= _QUERY_BUDGET:
                    continue
                queries += 1
                pk = _pk_prop(obj_type)["id"]
                try:
                    found = query_objects(type_id, filters={pk: mtext}, size=1, scope=scope, es=es)
                except Exception:
                    continue
                for item in found.get("items", []):
                    candidates.append(_candidate(mtext, obj_type, item, 1.0, f"{pk} exato"))
            continue

        # Frases, citações e siglas: procura por nome nos tipos com título pesquisável.
        if "empresa" in by_id and queries < _QUERY_BUDGET:
            queries += 1
            _company_candidates(mtext, "empresa", by_id, company_items(mtext), candidates)

        is_sigla = bool(re.fullmatch(r"[A-ZÀ-Þ0-9&.\-]{2,6}", mtext))
        if is_sigla:
            symbol = mtext.upper()
            if symbol in known_tickers and "ticker" in by_id:
                queries += 1
                try:
                    found = query_objects("ticker", filters={"simbolo": symbol}, size=1, scope=scope, es=es)
                except Exception:
                    found = {"items": []}
                for item in found.get("items", []):
                    candidates.append(_candidate(mtext, by_id["ticker"], item, 0.95, "símbolo indexado"))
            continue

        for type_id in _NAME_TYPES:
            obj_type = by_id.get(type_id)
            if not obj_type or queries >= _QUERY_BUDGET:
                continue
            queries += 1
            try:
                found = query_objects(type_id, search=mtext, size=3, scope=scope, es=es)
            except Exception as exc:
                notes.append(f"Pesquisa em «{obj_type['label']}» falhou: {exc}")
                continue
            for item in found.get("items", []):
                score, matched_on = _candidate_score(mtext, obj_type, item)
                if score >= 0.35:
                    candidates.append(_candidate(mtext, obj_type, item, score, matched_on))

    candidates.sort(key=lambda entry: entry["confidence"], reverse=True)
    per_mention: Dict[str, int] = {}
    selected: List[Dict[str, Any]] = []
    for entry in candidates:
        key = _normalize(entry["mention"])
        per_mention[key] = per_mention.get(key, 0) + 1
        if per_mention[key] > 2:
            continue
        selected.append(entry)
        if len(selected) >= min(limit, registry.load_ontology()["limits"]["max_resolve_candidates"]):
            break
    return {
        "text": text,
        "mentions": [mention["text"] for mention in mentions],
        "entities": selected,
        "count": len(selected),
        "queries": queries,
        "notes": list(dict.fromkeys(notes))[:4],
    }


# --------------------------------------------------------------------------
# Contexto para IA (grounding)
# --------------------------------------------------------------------------
def _object_facts(obj_type: Dict[str, Any], item: Dict[str, Any]) -> List[str]:
    facts: List[str] = []
    for prop in obj_type.get("properties", []):
        if prop.get("pk") or prop["id"] in ("id", "descricao"):
            continue
        value = item.get(prop["id"])
        if value in (None, ""):
            continue
        label = prop["label"]
        if prop.get("unit") == "€":
            facts.append(f"{label}: {_fmt_money(value)}")
        elif prop.get("type") == "number":
            facts.append(f"{label}: {value:,.0f}".replace(",", " ") if isinstance(value, (int, float)) else f"{label}: {value}")
        else:
            facts.append(f"{label}: {value}")
        if len(facts) >= 6:
            break
    return facts


def ai_context(
    question: str,
    limit: int = 5,
    links_per_object: int = 3,
    link_size: int = 3,
    link_budget: int = 8,
    scope: Optional[Dict[str, Any]] = None,
    es: Any = None,
) -> Dict[str, Any]:
    """Constrói o contexto ontológico de uma pergunta (objetos + relações + texto)."""
    started = time.time()
    resolved = resolve_entities(question, limit=limit, scope=scope, es=es)
    entities = [entry for entry in resolved["entities"] if entry["confidence"] >= _SCORE_THRESHOLD][:limit]
    if not entities and resolved["entities"]:
        entities = resolved["entities"][: min(2, len(resolved["entities"]))]

    objects: List[Dict[str, Any]] = []
    relations: List[Dict[str, Any]] = []
    notes: List[str] = list(resolved.get("notes") or [])
    suggested_tools: List[str] = []
    links_used = 0

    for entry in entities:
        obj_type = get_object_type(entry["type"])
        item = entry["object"]
        object_entry = {
            "type": obj_type["id"],
            "type_label": obj_type["label"],
            "domain": obj_type["domain"],
            "id": item.get("_id"),
            "label": item.get("_label"),
            "confidence": entry["confidence"],
            "matched_on": entry["matched_on"],
            "mention": entry["mention"],
            "properties": {key: value for key, value in item.items() if not key.startswith("_")},
        }
        objects.append(object_entry)
        suggested_tools.append(f"ontology_get_object(type=\"{obj_type['id']}\", id=\"{item.get('_id')}\")")
        for action in actions():
            if action.get("object_type") == obj_type["id"]:
                suggested_tools.append(f"ação: {action['label']} ({action['id']})")
                if len(suggested_tools) > 14:
                    break

        if links_per_object <= 0 or links_used >= link_budget:
            continue
        try:
            link_map = object_links(obj_type["id"], str(item.get("_id")), size=link_size, scope=scope, es=es)
        except (PermissionError, KeyError) as exc:
            notes.append(str(exc))
            continue
        links_used += 1
        available = [link for link in link_map.get("links", []) if link.get("available")]
        available.sort(key=lambda link: (link["direction"] == "forward", link.get("count", 0)), reverse=True)
        for link in available[:links_per_object]:
            if not link.get("items"):
                continue
            relations.append(
                {
                    "from": {"type": obj_type["id"], "id": item.get("_id"), "label": item.get("_label")},
                    "link": link["id"],
                    "label": link["label"],
                    "direction": link["direction"],
                    "to_type": link["other_type"],
                    "to_type_label": link["other_label"],
                    "count": link.get("count"),
                    "items": [
                        {"id": related.get("_id"), "label": related.get("_label")} for related in link["items"][:link_size]
                    ],
                }
            )
            for note in link.get("notes") or []:
                if note not in notes:
                    notes.append(note)

    lines: List[str] = []
    if objects:
        lines.append("Objetos da ontologia identificados na pergunta:")
        for entry in objects:
            obj_type = get_object_type(entry["type"])
            facts = ", ".join(_object_facts(obj_type, entry["properties"]))
            lines.append(f'- {obj_type["label"].upper()} «{entry["label"]}» (id {entry["id"]}) — {facts}')
    else:
        lines.append("Nenhum objeto da ontologia foi identificado na pergunta.")
    if relations:
        lines.append("Relações verificadas nos dados:")
        for rel in relations:
            names = ", ".join(f'«{item["label"]}»' for item in rel["items"])
            lines.append(f'- {rel["from"]["label"]} {rel["label"]} → {rel["to_type_label"]}: {names}')
    for note in resolved.get("notes") or []:
        lines.append(f"Nota: {note}")
    lines.extend(
        [
            "Nota: usa apenas estes objetos, ligações e valores; se algo não constar aqui, diz que não tens dados suficientes.",
            "Nota: valores de tipos `aggregation` e `derived` são agregados/derivados — apresentam-se como tal.",
        ]
    )

    return {
        "question": question,
        "objects": objects,
        "relations": relations,
        "grounding": "\n".join(lines),
        "mentions": resolved.get("mentions", []),
        "notes": list(dict.fromkeys(notes))[:6],
        "suggested_tools": suggested_tools[:16],
        "elapsed_ms": int((time.time() - started) * 1000),
    }


# --------------------------------------------------------------------------
# Ferramentas geradas a partir da ontologia
# --------------------------------------------------------------------------
def generated_tools(include_crm: bool = False) -> List[Dict[str, Any]]:
    """Esquemas de função (estilo OpenAI) derivados da ontologia, para o agente."""
    types = [obj for obj in object_types() if include_crm or not _scoped(obj)]
    type_ids = [obj["id"] for obj in types]
    link_ids = sorted({link["id"] for link in link_types() if link["to"] in type_ids or link["from"] in type_ids})
    catalog = [
        {
            "type": obj["id"],
            "label": obj["label"],
            "description": obj.get("description"),
            "domain": obj["domain"],
            "properties": [
                {"id": prop["id"], "label": prop["label"], "type": prop["type"], "unit": prop.get("unit"), "filterable": bool(prop.get("filterable"))}
                for prop in obj.get("properties", [])
            ],
        }
        for obj in types
    ]
    return [
        {
            "name": "ontology_query_objects",
            "description": (
                "Consulta objetos da ontologia do IQ OS (empresas, contratos, CPV, regiões, marcas, firmas, "
                "tickers, cotações, notícias, sentimento, tópicos, contas/contactos/oportunidades do CRM, pessoas). "
                "Devolve propriedades normalizadas e o total."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": type_ids, "description": "Tipo de objeto a consultar."},
                    "search": {"type": "string", "description": "Texto livre (nome, NIF, objeto do contrato, título da notícia)."},
                    "filters": {"type": "object", "description": "Filtros por propriedade, ex. {\"ano\": 2025, \"regiao\": \"Lisboa\"}."},
                    "size": {"type": "integer", "minimum": 1, "maximum": MAX_QUERY_SIZE},
                    "sort": {"type": "object", "description": "{\"id\": \"valor_total\", \"order\": \"desc\"}"},
                },
                "required": ["type"],
            },
            "catalog": catalog,
        },
        {
            "name": "ontology_get_object",
            "description": "Obtém um objeto pelo identificador (NIF, idcontrato, símbolo, id do CRM) e, opcionalmente, as suas ligações.",
            "parameters": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": type_ids},
                    "id": {"type": "string"},
                    "with_links": {"type": "boolean"},
                },
                "required": ["type", "id"],
            },
        },
        {
            "name": "ontology_object_links",
            "description": "Navega nas relações de um objeto (contratos da empresa, marcas, contactos da conta, notícias do ticker, …).",
            "parameters": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": type_ids},
                    "id": {"type": "string"},
                    "link": {"type": "string", "enum": link_ids},
                    "size": {"type": "integer", "minimum": 1, "maximum": 50},
                },
                "required": ["type", "id"],
            },
        },
        {
            "name": "ontology_resolve_entities",
            "description": "Resolve um texto livre (pergunta, nome, NIF, ticker) nos objetos canónicos da ontologia, com nível de confiança.",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 10}},
                "required": ["text"],
            },
        },
    ]


# --------------------------------------------------------------------------
# Validação anti-alucinação
# --------------------------------------------------------------------------
def _context_values(context: Dict[str, Any]) -> Tuple[set, set, set]:
    nifs: set = set()
    numbers: set = set()
    years: set = set()
    for entry in context.get("objects", []):
        for key, value in (entry.get("properties") or {}).items():
            if value in (None, ""):
                continue
            if key in ("nif", "nif_empresa", "titular_nif", "nipc", "adjudicante_nif", "adjudicatario_nif"):
                nifs.add(str(value))
            if key == "ano":
                years.add(str(value))
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                numbers.add(float(value))
    for rel in context.get("relations", []):
        for item in rel.get("items", []):
            identifier = str(item.get("id") or "")
            if re.fullmatch(r"\d{9}", identifier):
                nifs.add(identifier)
    return nifs, numbers, years


def _parse_money(raw: str) -> Optional[float]:
    text = raw.replace("\u00a0", "").replace(" ", "")
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def validate_answer(
    answer: str,
    question: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
    scope: Optional[Dict[str, Any]] = None,
    es: Any = None,
) -> Dict[str, Any]:
    """Verifica se as entidades e valores da resposta estão fundamentados nos dados."""
    if context is None:
        context = ai_context(question or answer, scope=scope, es=es)
    known_nifs, known_numbers, known_years = _context_values(context)
    checks: List[Dict[str, Any]] = []
    penalties: List[float] = []

    # NIFs citados que não constam do contexto.
    for nif in sorted(set(_NIF_RE.findall(answer or ""))):
        if nif in known_nifs:
            checks.append({"kind": "nif", "value": nif, "status": "ok", "message": "NIF presente nos dados usados como contexto."})
        else:
            checks.append({"kind": "nif", "value": nif, "status": "erro", "message": "NIF não encontrado nos dados usados como contexto — entidade potencialmente inventada."})
            penalties.append(0.25)

    # Valores monetários.
    for match in _MONEY_RE.finditer(answer or ""):
        number = _parse_money(match.group(1))
        if number is None:
            continue
        if abs(number) < 1:
            continue
        if any(abs(number - known) <= max(0.01 * abs(known), 0.5) for known in known_numbers):
            checks.append({"kind": "valor", "value": number, "status": "ok", "message": "Valor presente nos dados do contexto."})
        else:
            checks.append({"kind": "valor", "value": number, "status": "aviso", "message": "Valor não corresponde exatamente a nenhum valor do contexto (pode ser uma soma ou um valor de outra fonte)."})
            penalties.append(0.08)

    # Anos.
    for year in sorted(set(_YEAR_RE.findall(answer or ""))):
        if not known_years or year in known_years or (known_years and min(map(int, known_years)) <= int(year) <= max(map(int, known_years))):
            checks.append({"kind": "ano", "value": year, "status": "ok", "message": "Ano dentro do intervalo dos dados usados."})
        else:
            checks.append({"kind": "ano", "value": year, "status": "aviso", "message": "Ano fora do intervalo dos objetos do contexto."})
            penalties.append(0.05)

    # Tickers mencionados que existam na plataforma mas não no contexto.
    context_tickers = {
        str(entry["properties"].get("simbolo") or entry["properties"].get("ticker") or "").upper()
        for entry in context.get("objects", [])
        if entry.get("type") in ("ticker", "cotacao", "noticia", "sentimento_diario")
    }
    known = {ticker.upper() for ticker in _known_tickers(es)}
    mentioned = {token.upper() for token in _TICKER_RE.findall(answer or "")}
    for ticker in sorted(mentioned - context_tickers):
        if ticker in known:
            checks.append({"kind": "ticker", "value": ticker, "status": "aviso", "message": "Ticker existe na plataforma mas não foi usado como contexto desta resposta."})
            penalties.append(0.06)

    if not checks:
        checks.append({"kind": "geral", "value": None, "status": "ok", "message": "A resposta não contém entidades nem valores verificáveis."})

    score = max(0.0, 1.0 - min(sum(penalties), 0.95))
    supported = not any(check["status"] == "erro" for check in checks)
    return {
        "supported": supported,
        "score": round(score, 2),
        "checks": checks,
        "objects": [
            {"type": entry["type"], "id": entry["id"], "label": entry["label"], "confidence": entry["confidence"]}
            for entry in context.get("objects", [])
        ],
        "notes": context.get("notes", []),
        "grounding": context.get("grounding"),
    }


# --------------------------------------------------------------------------
# Resposta fundamentada (sem LLM)
# --------------------------------------------------------------------------
def _answer_from_context(context: Dict[str, Any]) -> str:
    """Constrói uma resposta factual a partir de um contexto já calculado."""
    if not context.get("objects"):
        return (
            "Não identifiquei objetos na ontologia do IQ OS para esta pergunta. "
            "Tenta mencionar uma empresa (nome ou NIF), um contrato, um ticker, uma marca ou uma conta do CRM."
        )
    lines: List[str] = []
    for entry in context["objects"]:
        obj_type = get_object_type(entry["type"])
        facts = _object_facts(obj_type, entry["properties"])
        detail = f" ({'; '.join(facts)})" if facts else ""
        lines.append(f"- {obj_type['label']} «{entry['label']}» — id {entry['id']}{detail}")
    relations_by_object: Dict[str, List[str]] = {}
    for rel in context.get("relations", []):
        key = str(rel["from"]["id"])
        names = ", ".join(item["label"] for item in rel["items"][:3])
        relations_by_object.setdefault(key, []).append(f"{rel['label']}: {names}")
    for entry in context["objects"]:
        related = relations_by_object.get(str(entry["id"]))
        if related:
            lines.append(f"  Relações de «{entry['label']}»: " + "; ".join(related))
    return "Com base na ontologia do IQ OS:\n" + "\n".join(lines)


def answer_from_context(context: Dict[str, Any]) -> str:
    """Resposta factual a partir de um contexto já calculado (usado pelo agente)."""
    return _answer_from_context(context)


def grounded_answer(
    question: str,
    scope: Optional[Dict[str, Any]] = None,
    es: Any = None,
) -> Dict[str, Any]:
    """Responde apenas com factos da ontologia (útil como fallback e como referência)."""
    context = ai_context(question, scope=scope, es=es)
    answer = _answer_from_context(context)
    validation = validate_answer(answer, context=context, scope=scope, es=es)
    return {
        "answer": answer,
        "context": context,
        "validation": validation,
        "generated": False,
        "notes": ["Resposta determinística construída a partir de objetos e relações verificados (sem modelo generativo)."],
    }


# --------------------------------------------------------------------------
# Ações
# --------------------------------------------------------------------------
def resolve_action(
    action_id: str,
    object_id: Optional[str] = None,
    type_id: Optional[str] = None,
    params: Optional[Dict[str, Any]] = None,
    scope: Optional[Dict[str, Any]] = None,
    es: Any = None,
) -> Dict[str, Any]:
    """Traduz uma ação da ontologia num pedido concreto (método, URL, corpo)."""
    action = next((item for item in actions() if item["id"] == action_id), None)
    if not action:
        raise KeyError(f"Ação desconhecida: {action_id}")
    if action.get("requires_session") and not scope:
        raise PermissionError("Esta ação exige sessão iniciada.")

    values: Dict[str, Any] = dict(params or {})
    obj_type: Optional[Dict[str, Any]] = None
    item: Optional[Dict[str, Any]] = None
    if object_id and type_id:
        obj_type = get_object_type(type_id)
        detail = get_object(type_id, object_id, scope=scope, es=es)
        item = detail.get("object")
        if not detail.get("found"):
            raise KeyError(f"Objeto {type_id}/{object_id} não encontrado.")
    for spec in action.get("params", []):
        name = spec.get("id")
        if name in values and values[name] not in (None, ""):
            continue
        if spec.get("from") == "primary_key" and item:
            values[name] = item.get(_pk_prop(obj_type)["id"]) if obj_type else None
        elif spec.get("from") == "property" and item:
            values[name] = item.get(spec.get("property"))

    def render(template: str) -> str:
        def replace(match: "re.Match[str]") -> str:
            value = values.get(match.group(1))
            return "" if value is None else str(value)

        return re.sub(r"\{(\w+)\}", replace, template)

    method = action.get("method") or ("POST" if action.get("kind") == "ai" else "GET")
    url = render(action.get("target") or action.get("url") or "")
    body = None
    if action.get("kind") == "ontology_links":
        method = "POST"
        url = ""
        if object_id and type_id:
            url = f"/ontology/objects/{type_id}/{object_id}/links?link={action.get('link', '')}"
    if action.get("body_params"):
        body = {name: values.get(name) for name in action["body_params"] if values.get(name) is not None}
    notes = ["A plataforma devolve o pedido a executar; a execução é feita pelo cliente autenticado."]
    if action.get("kind") == "ontology_links" and not url:
        notes.append("Indica o objeto (tipo + identificador) para obter o URL de navegação.")
    return {
        "action": action,
        "method": method,
        "url": url,
        "body": body,
        "values": values,
        "notes": notes,
    }
