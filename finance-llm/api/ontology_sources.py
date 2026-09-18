"""Fontes de dados da ontologia: leitura, diagnóstico e inferência de tipos.

Uma **fonte** é a ligação a um sítio onde os dados vivem de facto. A ontologia
guarda-as em `data/ontology/<ontologia>.json` (`sources`) e cada tipo de objeto
pode apontar para uma delas através de `binding.source` — assim é possível
trazer dados novos sem tocar no registo base (`api/ontology_registry.py`).

Tipos de fonte suportados:

- `elasticsearch` — índice do Elasticsearch: diagnóstico com contagem de
  documentos, *mapping* real e amostra de valores por campo;
- `rest` — endpoint HTTP que devolve JSON: valida o estado, o tipo de conteúdo e
  a forma da resposta (chaves de topo, caminho da lista, campos do primeiro item);
- `file` — ficheiro local JSON/CSV: valida o caminho e lê o cabeçalho/estrutura;
- `derived` — resolvedor Python da plataforma (sem diagnóstico próprio).

A partir do diagnóstico, `infer_object_type()` propõe um **tipo de objeto**
completo (chave primária, campos pesquisáveis/filtráveis, ordenação) — é a via
determinística para acrescentar dados, usada pela IA como base e disponível
mesmo sem nenhum modelo configurado.
"""
from __future__ import annotations

import csv
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

PROBE_TIMEOUT = 15.0
MAX_FIELDS = 400
AI_FIELDS = 40
SAMPLE_FIELDS = 8
SAMPLE_TERM_SIZE = 4

# Campos internos/de conveniência que não valem uma propriedade da ontologia.
NOISY_FIELDS = {"search_text", "search_texto", "all_text", "texto_pesquisa", "_source", "_score", "highlight"}

ELASTIC_TYPES: Dict[str, Dict[str, Any]] = {
    "text": {"type": "text", "searchable": True, "filterable": False},
    "keyword": {"type": "keyword", "searchable": True, "filterable": True},
    "long": {"type": "number", "sortable": True, "filterable": True},
    "integer": {"type": "number", "sortable": True, "filterable": True},
    "short": {"type": "number", "sortable": True, "filterable": True},
    "byte": {"type": "number", "sortable": True, "filterable": True},
    "double": {"type": "number", "sortable": True, "filterable": True},
    "float": {"type": "number", "sortable": True, "filterable": True},
    "half_float": {"type": "number", "sortable": True, "filterable": True},
    "scaled_float": {"type": "number", "sortable": True, "filterable": True},
    "date": {"type": "date", "sortable": True, "filterable": True},
    "boolean": {"type": "boolean", "filterable": True},
    "ip": {"type": "keyword", "filterable": True},
    "geo_point": {"type": "keyword", "filterable": True},
}

# Nomes que valem por uma chave primária / título, por ordem de preferência.
PK_CANDIDATES = (
    "id",
    "idcontrato",
    "id_contrato",
    "nif",
    "nipc",
    "codigo",
    "code",
    "ticker",
    "symbol",
    "isin",
    "referencia",
    "ref",
    "numero",
    "num",
    "processo",
    "slug",
    "email",
)
TITLE_CANDIDATES = (
    "nome",
    "name",
    "title",
    "titulo",
    "designacao",
    "subject",
    "assunto",
    "objecto",
    "objeto",
    "objectoContrato",
    "descricao",
    "description",
    "resumo",
    "summary",
)
DATE_CANDIDATES = ("data", "date", "published", "published_at", "created_at", "updated_at", "timestamp", "dia")

FIELD_TYPE_LABEL = {
    "text": "texto livre",
    "keyword": "valor exato",
    "number": "número",
    "date": "data",
    "boolean": "booleano",
}


# --------------------------------------------------------------------------
# Leitura de Elasticsearch
# --------------------------------------------------------------------------
def _es_client() -> Any:
    from api.elasticsearch_client import get_es_client

    return get_es_client()


def _flatten_mapping(properties: Dict[str, Any], prefix: str = "", nested: Optional[str] = None) -> List[Dict[str, Any]]:
    """Achata o *mapping* do ES em `[{name, type, nested, sub}]`."""
    fields: List[Dict[str, Any]] = []
    for name, spec in (properties or {}).items():
        if not isinstance(spec, dict):
            continue
        path = f"{prefix}{name}"
        kind = str(spec.get("type") or ("nested" if spec.get("properties") else "object"))
        if kind in ("nested", "object"):
            if spec.get("properties"):
                fields.extend(_flatten_mapping(spec["properties"], f"{path}.", path if kind == "nested" else nested))
            else:
                fields.append({"name": path, "type": "keyword", "nested": nested})
            continue
        entry = {"name": path, "type": kind, "nested": nested}
        # Campos multi-índice (`nome.keyword`) servem para filtros exatos.
        if kind == "text":
            sub = ((spec.get("fields") or {}).get("keyword") or {}).get("type")
            if sub == "keyword":
                entry["exact_field"] = f"{path}.keyword"
        fields.append(entry)
    return fields


def _types_from_mapping(flattened: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Converte o *mapping* numa lista de campos (nome, tipo, rótulo, amostra)."""
    fields: List[Dict[str, Any]] = []
    for entry in flattened[:MAX_FIELDS]:
        mapping = ELASTIC_TYPES.get(entry["type"])
        if not mapping:
            continue
        leaf = entry["name"].split(".")[-1]
        if leaf.lower() in NOISY_FIELDS:
            continue
        label = leaf.replace("_", " ").strip().capitalize()
        fields.append(
            {
                "name": entry["name"],
                "type": mapping["type"],
                "label": label,
                "elastic_type": entry["type"],
                "nested": entry.get("nested"),
                "exact_field": entry.get("exact_field"),
                "searchable": bool(mapping.get("searchable")),
                "filterable": bool(mapping.get("filterable")),
                "sortable": bool(mapping.get("sortable")),
            }
        )
    return fields


def _sample_values(index: str, fields: List[Dict[str, Any]], client: Any) -> Dict[str, List[str]]:
    """Amostra dos valores mais frequentes de alguns campos (para contexto da IA)."""
    samples: Dict[str, List[str]] = {}
    used = 0
    for field in fields:
        if used >= SAMPLE_FIELDS or not field.get("filterable"):
            continue
        agg_field = field.get("exact_field") or field["name"]
        body: Dict[str, Any] = {"size": 0, "aggs": {"top": {"terms": {"field": agg_field, "size": SAMPLE_TERM_SIZE}}}}
        if field.get("nested"):
            body["aggs"] = {"nested_agg": {"nested": {"path": field["nested"]}, "aggs": {"top": {"terms": {"field": agg_field, "size": SAMPLE_TERM_SIZE}}}}}
        try:
            response = client.search(index=index, body=body, request_timeout=PROBE_TIMEOUT)
            node = response.get("aggregations") or {}
            if field.get("nested"):
                node = (node.get("nested_agg") or {}).get("top") or {}
            else:
                node = node.get("top") or {}
            values = [str(bucket.get("key")) for bucket in (node.get("buckets") or []) if bucket.get("key") is not None]
        except Exception:  # campo não agregável / índice fechado
            continue
        if values:
            samples[field["name"]] = values
            used += 1
    return samples


def probe_elasticsearch(source: Dict[str, Any], *, with_samples: bool = True) -> Dict[str, Any]:
    """Diagnóstico de um índice: documentos, campos reais e amostras de valores."""
    config = source.get("config") if isinstance(source.get("config"), dict) else {}
    index = str(source.get("index") or config.get("index") or "").strip()
    if not index:
        return {"state": "error", "ok": False, "note": "Falta o índice do Elasticsearch na fonte."}
    client = _es_client()
    if not client:
        return {"state": "error", "ok": False, "note": "Elasticsearch indisponível nesta instalação."}
    result: Dict[str, Any] = {"state": "ok", "ok": True, "index": index, "documents": None, "fields": [], "samples": {}}
    try:
        result["documents"] = int(client.count(index=index).get("count", 0))
    except Exception as exc:
        return {"state": "error", "ok": False, "index": index, "note": f"Não foi possível contar os documentos: {exc}"}
    try:
        mapping = client.indices.get_mapping(index=index)
        properties: Dict[str, Any] = {}
        for entry in mapping.values():
            properties.update(((entry.get("mappings") or {}).get("properties") or {}))
        fields = _types_from_mapping(_flatten_mapping(properties))
        result["fields"] = fields
        if with_samples and fields:
            result["samples"] = _sample_values(index, fields, client)
    except Exception as exc:
        result["note"] = f"Índice encontrado, mas o mapeamento não foi lido: {exc}"
    if not result["fields"]:
        result.setdefault("note", "Índice sem mapeamento declarado.")
    return result


def probe_rest(source: Dict[str, Any]) -> Dict[str, Any]:
    """Diagnóstico de um endpoint JSON: estado, tipo de conteúdo e forma da resposta."""
    config = source.get("config") if isinstance(source.get("config"), dict) else {}
    url = str(source.get("url") or config.get("url") or "").strip()
    if not url:
        return {"state": "error", "ok": False, "note": "Falta o endereço (url) da fonte."}
    headers = {"accept": "application/json, text/csv;q=0.9, */*;q=0.8", "user-agent": "IQOS-Ontology/1.0"}
    for key, value in (source.get("headers") or {}).items():
        headers[str(key)] = str(value)
    try:
        with httpx.Client(timeout=PROBE_TIMEOUT, follow_redirects=True) as client:
            response = client.get(url, headers=headers)
        payload: Dict[str, Any] = {
            "state": "ok",
            "ok": response.status_code < 400,
            "url": str(response.url),
            "status": response.status_code,
            "content_type": response.headers.get("content-type", ""),
            "bytes": len(response.content),
            "fields": [],
        }
        if response.status_code >= 400:
            payload["note"] = f"O servidor respondeu {response.status_code}."
            return payload
        text = response.text
        if "json" in payload["content_type"] or text.lstrip()[:1] in ("{", "["):
            try:
                data = response.json()
            except ValueError:
                payload["note"] = "A resposta não é JSON válido."
                return payload
            fields, items_path, count = infer_from_json(data)
            payload.update({"fields": fields, "items_path": items_path, "items": count})
        elif "csv" in payload["content_type"] or "\n" in text[:500]:
            fields = fields_from_csv(text)
            payload.update({"fields": fields, "items": len(text.splitlines()) - 1})
        return payload
    except httpx.HTTPError as exc:
        return {"state": "error", "ok": False, "url": url, "note": f"Falha de rede: {exc}"}


def probe_file(source: Dict[str, Any]) -> Dict[str, Any]:
    """Diagnóstico de um ficheiro JSON/CSV local."""
    config = source.get("config") if isinstance(source.get("config"), dict) else {}
    raw_path = str(source.get("path") or config.get("path") or "").strip()
    if not raw_path:
        return {"state": "error", "ok": False, "note": "Falta o caminho do ficheiro."}
    path = Path(raw_path)
    if not path.exists():
        return {"state": "error", "ok": False, "path": str(path), "note": "O ficheiro não existe."}
    payload: Dict[str, Any] = {"state": "ok", "ok": True, "path": str(path), "bytes": path.stat().st_size, "fields": []}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")[:400_000]
    except OSError as exc:
        return {"state": "error", "ok": False, "path": str(path), "note": f"Não foi possível ler: {exc}"}
    if path.suffix.lower() in (".json",):
        try:
            fields, items_path, count = infer_from_json(json.loads(text))
            payload.update({"fields": fields, "items_path": items_path, "items": count})
        except ValueError as exc:
            payload.update({"state": "error", "ok": False, "note": f"JSON inválido: {exc}"})
    else:
        fields = fields_from_csv(text)
        payload.update({"fields": fields, "items": max(len(text.splitlines()) - 1, 0)})
    return payload


def probe(source: Dict[str, Any], *, with_samples: bool = True) -> Dict[str, Any]:
    """Diagnóstico de uma fonte, conforme o seu tipo."""
    kind = str(source.get("kind") or "").strip().lower()
    if kind == "elasticsearch":
        return probe_elasticsearch(source, with_samples=with_samples)
    if kind == "rest":
        return probe_rest(source)
    if kind == "file":
        return probe_file(source)
    return {"state": "skipped", "ok": True, "note": "Fontes derivadas não têm diagnóstico próprio."}


# --------------------------------------------------------------------------
# Inferência a partir de JSON/CSV
# --------------------------------------------------------------------------
def _json_type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        text = value.strip()
        if text[:1].isdigit() and ("-" in text[:5] or ":" in text):
            return "date"
        return "text" if len(text) > 24 or " " in text else "keyword"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "object"
    return "keyword"


def infer_from_json(data: Any) -> Tuple[List[Dict[str, Any]], Optional[str], int]:
    """Infere campos a partir de um JSON: `(campos, caminho da lista, nº de itens)`."""
    items_path: Optional[str] = None
    sample: Any = data
    count = 0
    if isinstance(data, list):
        sample = data[0] if data else {}
        items_path = ""
        count = len(data)
    elif isinstance(data, dict):
        # Procura a primeira chave cujo valor é uma lista de dicionários.
        for key, value in data.items():
            if isinstance(value, list) and (not value or isinstance(value[0], dict)):
                items_path = key
                sample = value[0] if value else {}
                count = len(value)
                break
        else:
            count = 1
    if not isinstance(sample, dict):
        return [], items_path, count
    fields: List[Dict[str, Any]] = []
    for name, value in list(sample.items())[:MAX_FIELDS]:
        kind = _json_type(value)
        if kind in ("object", "list"):
            continue
        fields.append(
            {
                "name": name,
                "label": name.replace("_", " ").strip().capitalize(),
                "type": kind if kind in ("number", "boolean", "date") else ("text" if kind == "text" else "keyword"),
                "searchable": kind == "text",
                "filterable": kind in ("keyword", "boolean", "date", "number"),
                "sortable": kind in ("number", "date"),
                "sample": value if not isinstance(value, (dict, list)) else None,
            }
        )
    return fields, items_path, count


def fields_from_csv(text: str) -> List[Dict[str, Any]]:
    """Lê o cabeçalho de um CSV e infere o tipo de cada coluna."""
    rows = list(csv.reader(text.splitlines()[:80]))
    if not rows:
        return []
    header = [cell.strip() for cell in rows[0]]
    body = rows[1:]
    fields: List[Dict[str, Any]] = []
    for position, name in enumerate(header[:MAX_FIELDS]):
        if not name:
            continue
        values = [row[position] for row in body if position < len(row) and row[position].strip()]
        kind = _json_type(values[0]) if values else "keyword"
        numeric = bool(values) and all(_to_float(value) is not None for value in values[:20])
        fields.append(
            {
                "name": name,
                "label": name.replace("_", " ").strip().capitalize(),
                "type": "number" if numeric else ("date" if kind == "date" else ("text" if kind == "text" else "keyword")),
                "searchable": not numeric and kind == "text",
                "filterable": numeric or kind in ("date", "keyword"),
                "sortable": numeric or kind == "date",
                "sample": values[0] if values else None,
            }
        )
    return fields


def _to_float(value: str) -> Optional[float]:
    try:
        return float(str(value).replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        return None


def _sentence_case(text: str) -> str:
    """Maiúscula apenas na primeira letra (evita «Contratos Do Portal Base»)."""
    clean = str(text or "").strip()
    return clean[:1].upper() + clean[1:] if clean else clean


def _pluralize(text: str) -> str:
    """Plural simples do primeiro nome (o resto fica igual): «Contrato de energia» → «Contratos de energia»."""
    words = str(text or "").split()
    if not words:
        return str(text or "")
    first = words[0]
    if first.lower().endswith(("s", "x", "z")):
        plural = first
    elif first.lower().endswith(("r", "l", "n")) or first.lower().endswith("es"):
        plural = f"{first}es"
    elif first.lower().endswith(("a", "e", "i", "o", "u")):
        plural = f"{first}s"
    else:
        plural = f"{first}s"
    return " ".join([plural, *words[1:]])


# --------------------------------------------------------------------------
# Proposta de tipo de objeto a partir de uma fonte
# --------------------------------------------------------------------------
def _pick(
    fields: List[Dict[str, Any]],
    candidates: Tuple[str, ...],
    *,
    exact_type: Optional[str] = None,
    allow_nested: bool = False,
) -> Optional[Dict[str, Any]]:
    """Procura um campo por ordem de preferência (primeiro os de topo, depois os aninhados)."""
    for nested_ok in ((False, True) if allow_nested else (False,)):
        for candidate in candidates:
            for field in fields:
                if field.get("nested") and not nested_ok:
                    continue
                if exact_type and field.get("type") != exact_type:
                    continue
                leaf = field["name"].split(".")[-1].lower()
                if leaf == candidate.lower():
                    return field
    return None


def _pick_by_suffix(fields: List[Dict[str, Any]], suffixes: Tuple[str, ...]) -> Optional[Dict[str, Any]]:
    """Campo de topo cujo nome termina num sufixo (`idcontrato`, `contrato_id`, …)."""
    for suffix in suffixes:
        for field in fields:
            if field.get("nested"):
                continue
            leaf = field["name"].split(".")[-1].lower()
            if leaf.endswith(suffix) and len(leaf) > len(suffix):
                return field
    return None


def guess_keys(fields: List[Dict[str, Any]], index: str = "") -> Tuple[str, str]:
    """Adivinha `(chave primária, campo de título)` a partir dos nomes reais."""
    # Chave primária: candidatos de topo → sufixos comuns → primeiro campo filtrável.
    pk = _pick(fields, PK_CANDIDATES)
    if pk is None:
        pk = _pick_by_suffix(fields, ("id", "_id", "codigo", "code", "nif", "nipc"))
    if pk is None:
        pk = next((field for field in fields if field.get("filterable") and not field.get("nested")), None)
    primary = (pk or {}).get("name") or "_id"
    if not pk or pk.get("nested"):
        # Um campo aninhado não serve de chave (o documento não tem um valor único).
        primary = "_id"

    # Título: primeiro nome "legível" de topo, depois campos de texto aninhados.
    title = _pick(fields, TITLE_CANDIDATES, exact_type="text") or _pick(fields, TITLE_CANDIDATES)
    if title is None:
        title = _pick_by_suffix(fields, ("nome", "name", "titulo", "title"))
    if title is None:
        title = next((field for field in fields if field.get("searchable") and not field.get("nested")), None)
    if title is None:
        title = next((field for field in fields if field.get("searchable")), None) or (fields[0] if fields else None)
    return primary, (title or {}).get("name") or primary


def infer_object_type(
    source: Dict[str, Any],
    *,
    fields: List[Dict[str, Any]],
    type_id: Optional[str] = None,
    label: Optional[str] = None,
    domain: Optional[str] = None,
    samples: Optional[Dict[str, List[str]]] = None,
) -> Dict[str, Any]:
    """Constrói a proposta de um tipo de objeto ligado a esta fonte."""
    from api.ontology_registry import slugify

    index = str(source.get("index") or (source.get("config") or {}).get("index") or "").strip()
    identifier = slugify(type_id or source.get("label") or source.get("id") or index or "objeto", fallback="objeto")
    samples = samples or {}
    primary, title = guess_keys(fields, index)
    kind = str(source.get("kind") or "").lower()
    binding: Dict[str, Any] = {"kind": "es" if kind == "elasticsearch" else "derived", "source": source.get("id")}
    if kind == "elasticsearch" and index:
        binding["index"] = index
        binding["id_field"] = primary if primary != "_id" else "_id"
        # Pesquisa livre: título primeiro e só campos de topo (o `multi_match` não
        # atravessa `nested` — esses ficam com filtro próprio na propriedade).
        search_fields = [title] if title and title != "_id" else []
        for field in fields:
            if len(search_fields) >= 6:
                break
            if field.get("searchable") and not field.get("nested") and field["name"] not in search_fields:
                search_fields.append(field["name"])
        binding["search_fields"] = search_fields
        date_field = _pick(fields, DATE_CANDIDATES, exact_type="date")
        if date_field:
            binding["default_sort"] = {"field": date_field["name"], "order": "desc"}
        binding["sources"] = [source.get("id")]
    elif kind in ("rest", "file"):
        binding = {
            "kind": "derived",
            "source": source.get("id"),
            "resolver": "source_snapshot",
            "items_path": source.get("items_path"),
            "notes": "Tipo de leitura: instantâneo da fonte (sem indexação).",
        }
    properties: List[Dict[str, Any]] = []
    used_ids: Dict[str, int] = {}
    # Nome do campo na fonte → id da propriedade (a ontologia usa ids, não nomes
    # de campo: `objectoContrato` passa a `objectocontrato`).
    id_by_field: Dict[str, str] = {}
    for field in fields:
        # O id da propriedade é o nome curto (`nif`), salvo se houver colisão
        # entre campos aninhados com o mesmo nome (aí usa-se o caminho todo).
        leaf_slug = slugify(field["name"].split(".")[-1], fallback="campo")
        used_ids[leaf_slug] = used_ids.get(leaf_slug, 0) + 1
        prop_id = leaf_slug if used_ids[leaf_slug] == 1 else slugify(field["name"].replace(".", "_"), fallback="campo")
        id_by_field[field["name"]] = prop_id
        prop: Dict[str, Any] = {
            "id": prop_id,
            "label": field.get("label") or field["name"],
            "type": field.get("type") or "keyword",
        }
        if kind == "elasticsearch" and field["name"] != "_id":
            prop["field"] = field["name"]
        if field.get("nested"):
            prop["nested"] = field["nested"]
        if field.get("searchable"):
            prop["searchable"] = True
        if field.get("filterable"):
            prop["filterable"] = True
        if field.get("sortable"):
            prop["sortable"] = True
        if prop["type"] == "number":
            prop["sortable"] = True
        if field.get("name") == primary:
            prop["pk"] = True
        sample = samples.get(field["name"])
        if sample:
            prop["sample_values"] = sample[:3]
        properties.append(prop)
    if not any(prop.get("pk") for prop in properties) and properties:
        properties[0]["pk"] = True
    plural = _pluralize(str(source.get("label") or identifier))
    # `primary`/`title` são nomes de campo na fonte: passam a ids de propriedade.
    primary_id = id_by_field.get(primary, primary)
    title_id = id_by_field.get(title, primary_id)
    return {
        "id": identifier,
        "label": label or _sentence_case(str(source.get("label") or source.get("name") or identifier)),
        "plural": _sentence_case(plural),
        "description": (source.get("description") or f"Objetos lidos de «{source.get('label') or index}».").strip(),
        "domain": domain or source.get("domain") or "dados",
        "icon": "database",
        "primary_key": primary_id,
        "title_field": title_id,
        "subtitle_fields": [prop["id"] for prop in properties if prop.get("filterable") and prop["id"] != primary_id][:3],
        "resolvable": bool(properties),
        "binding": binding,
        "query_hint": f"Pesquisa por {', '.join(binding.get('search_fields') or [title])}.",
        "properties": properties,
    }


def describe_source(source: Dict[str, Any], diagnostic: Optional[Dict[str, Any]] = None) -> str:
    """Descrição textual de uma fonte (contexto para a IA), com os campos reais."""
    diagnostic = diagnostic or probe(source, with_samples=False)
    lines = [
        f"Fonte «{source.get('label') or source.get('id')}» (tipo {source.get('kind')})",
    ]
    if source.get("description"):
        lines.append(f"Descrição: {source['description']}")
    if diagnostic.get("index"):
        lines.append(f"Índice: {diagnostic['index']} — {diagnostic.get('documents')} documentos")
    if diagnostic.get("url"):
        lines.append(f"Endpoint: {diagnostic['url']} (estado {diagnostic.get('status')}, {diagnostic.get('bytes')} bytes)")
    if diagnostic.get("path"):
        lines.append(f"Ficheiro: {diagnostic['path']} ({diagnostic.get('bytes')} bytes)")
    if diagnostic.get("items_path") is not None:
        lines.append(f"Caminho da lista: {diagnostic.get('items_path') or '(raiz)'} ({diagnostic.get('items')} itens)")
    fields = diagnostic.get("fields") or []
    if fields:
        lines.append("Campos:")
        for field in fields[:AI_FIELDS]:
            extra = ""
            sample = (diagnostic.get("samples") or {}).get(field["name"]) or ([field["sample"]] if field.get("sample") is not None else [])
            if sample:
                extra = f" | exemplos: {', '.join(str(value)[:24] for value in sample[:3])}"
            lines.append(f"- {field['name']} ({FIELD_TYPE_LABEL.get(field.get('type'), field.get('type'))}){extra}")
    if diagnostic.get("note"):
        lines.append(f"Nota: {diagnostic['note']}")
    return "\n".join(lines)
