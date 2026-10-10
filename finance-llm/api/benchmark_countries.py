"""Dialetos por país do **benchmark de contratos públicos** (Portugal, Espanha, França).

Os três índices guardam a mesma realidade com nomes diferentes: as partes
(quem compra / quem vende), o valor, o CPV, o ano e a data. Este módulo é o único
sítio onde essas diferenças vivem, para o serviço de benchmark poder ser escrito
uma vez e correr nos três países.

| | Portugal (`contratos`) | Espanha (`contratos_es`) | França (`contratos_fr`) |
|---|---|---|---|
| quem compra | `adjudicantes.parsed` (nested) | `organo_id` / `organo_nombre` (plano) | `acheteur_id` (plano) |
| quem vende | `adjudicatarios.parsed` (nested) | `adjudicatario_nif` / `adjudicatario_nombre` | `titulaires` (nested, id + nom) |
| valor | `precoContratual` | `valor_adjudicado` (+ `valor_base`) | `valor` |
| CPV | `cpv` nested (`code`, `description`) | `cpv` nested (`code`, `nombre`) | `cpv` nested (`code`, `nom`) |
| ano | `Ano` | `ano` | `ano` |
| data | `dataCelebracaoContrato` | `fecha_adjudicacion` | `date_notification` |
| geografia | `NUTs` / `localExecucao` | `nuts` / `localidad` | `lieu_execution_code` |

Notas de dados (medidas no cluster, 2026-10-10):

- **Espanha**: o valor adjudicado pode faltar e existir só o base, por isso a
  *soma* usa um script `max(valor_adjudicado, valor_base)`; `stats`/`percentiles`
  não aceitam `script` nesta versão do Elasticsearch e usam o campo
  `valor_adjudicado`.
- **França**: `acheteur_nom`/`adjudicatario_nom` estão vazios nos documentos
  carregados — os compradores são identificados pelo SIRET e os titulares pelo
  par `titulaires.id` + `titulaires.nom`. Há ainda um documento com o valor
  sentinela `99999999999999`, pelo que existe um teto de sanidade por país.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from api.elasticsearch_client import (
    CONTRATOS_ES_INDEX,
    CONTRATOS_FR_INDEX,
    CONTRACTS_INDEX,
)

#: Países suportados, pela ordem em que aparecem na interface.
COUNTRIES: tuple[str, ...] = ("pt", "es", "fr")

#: Papéis da entidade no contrato.
BUYER = "adjudicante"
SUPPLIER = "adjudicatario"


def _es_valor_script() -> Dict[str, Any]:
    """`max(valor_adjudicado, valor_base)` — a soma robusta da analítica espanhola."""
    return {
        "script": {
            "source": (
                "Math.max("
                "doc['valor_adjudicado'].size() != 0 ? doc['valor_adjudicado'].value : 0.0, "
                "doc['valor_base'].size() != 0 ? doc['valor_base'].value : 0.0)"
            )
        }
    }


DIALECTS: Dict[str, Dict[str, Any]] = {
    "pt": {
        "label": "Portugal",
        "short": "PT",
        "index": CONTRACTS_INDEX,
        "buyer": {
            "nested": "adjudicantes.parsed",
            "id": "adjudicantes.parsed.nif",
            "nome": "adjudicantes.parsed.nome",
            "nome_kw": "adjudicantes.parsed.nome.keyword",
        },
        "supplier": {
            "nested": "adjudicatarios.parsed",
            "id": "adjudicatarios.parsed.nif",
            "nome": "adjudicatarios.parsed.nome",
            "nome_kw": "adjudicatarios.parsed.nome.keyword",
        },
        "valor_campo": "precoContratual",
        "valor_soma_corpo": {"field": "precoContratual"},
        "valor_teto": 1e10,
        "ano": "Ano",
        "data": "dataCelebracaoContrato",
        "cpv": {"nested": "cpv", "code": "cpv.code", "descricao": "description"},
        "geografia": {"field": "NUTs", "usa_region_filter": True},
        "recent": {
            "id": "idcontrato",
            "objeto": "objectoContrato",
            "valor": "precoContratual",
            "data": "dataCelebracaoContrato",
            "data2": "dataPublicacao",
            "proc": "tipoprocedimento",
        },
    },
    "es": {
        "label": "Espanha",
        "short": "ES",
        "index": CONTRATOS_ES_INDEX,
        "buyer": {
            "nested": None,
            "id": "organo_id",
            "nome": "organo_nombre",
            "nome_kw": "organo_nombre.keyword",
        },
        "supplier": {
            "nested": None,
            "id": "adjudicatario_nif",
            "nome": "adjudicatario_nombre",
            "nome_kw": "adjudicatario_nombre.keyword",
        },
        "valor_campo": "valor_adjudicado",
        "valor_soma_corpo": _es_valor_script(),
        "valor_teto": 1e11,
        "ano": "ano",
        "data": "fecha_adjudicacion",
        "cpv": {"nested": "cpv", "code": "cpv.code", "descricao": "nombre"},
        "geografia": {"field": "nuts", "usa_region_filter": False},
        "recent": {
            "id": "id_expediente",
            "objeto": "objeto",
            "valor": "valor_adjudicado",
            "data": "fecha_adjudicacion",
            "data2": "fecha_publicacion",
            "proc": "procedimiento_label",
        },
    },
    "fr": {
        "label": "França",
        "short": "FR",
        "index": CONTRATOS_FR_INDEX,
        "buyer": {
            "nested": None,
            "id": "acheteur_id",
            "nome": "acheteur_nom",
            "nome_kw": "acheteur_nom.keyword",
        },
        "supplier": {
            "nested": "titulaires",
            "id": "titulaires.id",
            "nome": "titulaires.nom",
            "nome_kw": None,
        },
        "valor_campo": "valor",
        "valor_soma_corpo": {"field": "valor"},
        # Há um documento com 99 999 999 999 999 € (sentinela): o teto corta-o.
        "valor_teto": 1e12,
        "ano": "ano",
        "data": "date_notification",
        "cpv": {"nested": "cpv", "code": "cpv.code", "descricao": "nom"},
        "geografia": {"field": "lieu_execution_code", "usa_region_filter": False},
        "recent": {
            "id": "doc_id",
            "objeto": "objet",
            "valor": "valor",
            "data": "date_notification",
            "data2": "date_publication",
            "proc": "procedure",
        },
    },
}

#: Nomes legíveis dos papéis, por país (para a interface).
ROLE_LABELS: Dict[str, Dict[str, str]] = {
    "pt": {SUPPLIER: "adjudicatário", BUYER: "adjudicante"},
    "es": {SUPPLIER: "empresa adjudicataria", BUYER: "órgão adjudicante"},
    "fr": {SUPPLIER: "titulaire", BUYER: "acheteur"},
}


def dialect(country: Optional[str]) -> Dict[str, Any]:
    """Dialeto de um país (`pt` por omissão)."""
    chave = (country or "pt").strip().lower()
    return DIALECTS.get(chave, DIALECTS["pt"])


def country_key(country: Optional[str]) -> str:
    """Chave normalizada do país (`pt`/`es`/`fr`)."""
    chave = (country or "pt").strip().lower()
    return chave if chave in DIALECTS else "pt"


def party(country: Optional[str], role: str) -> Dict[str, Any]:
    """Campos da parte (quem compra ou quem vende) no país."""
    spec = dialect(country)
    return spec["buyer"] if role == BUYER else spec["supplier"]


def is_nested(country: Optional[str], role: str) -> bool:
    return bool(party(country, role).get("nested"))


# --------------------------------------------------------------------- filtros

def entity_filter(
    country: Optional[str],
    role: str,
    *,
    nif: Optional[str] = None,
    name: Optional[str] = None,
) -> Dict[str, Any]:
    """Filtro que identifica uma entidade no seu papel (por identificador ou nome).

    Aceita `nif` (NIF/DIR3/SIRET, que é o campo `id` do dialeto) ou `name`. Se
    vierem os dois, o identificador manda — é exato e não depende do analisador.
    """
    spec = party(country, role)
    nested = spec.get("nested")
    codigo = (nif or "").strip()
    texto = (name or "").strip()
    if codigo:
        consulta: Dict[str, Any] = {"term": {spec["id"]: codigo}}
    elif texto:
        consulta = {
            "bool": {
                "should": [
                    {"match_phrase": {spec["nome"]: texto}},
                    {"match_phrase_prefix": {spec["nome"]: texto}},
                ],
                "minimum_should_match": 1,
            }
        }
    else:
        return {"match_all": {}}
    if nested:
        return {"nested": {"path": nested, "query": consulta}}
    return consulta


def rank_agg(country: Optional[str], role: str, size: int) -> Dict[str, Any]:
    """Ranking das entidades de um papel, por valor contratado.

    Em PT/FR a parte é `nested` (o valor soma-se com `reverse_nested` e a ordem
    usa `value>sum`); em ES os campos são planos (ordem por `value`).
    """
    spec = party(country, role)
    nested = spec.get("nested")
    dialeto = dialect(country)
    if nested:
        return {
            "nested": {"path": nested},
            "aggs": {
                "top": {
                    "terms": {"field": spec["id"], "size": size, "order": {"value>sum": "desc"}},
                    "aggs": {
                        "nome": {"top_hits": {"size": 1, "_source": True}},
                        "value": {
                            "reverse_nested": {},
                            "aggs": {
                                "sum": {"sum": dialeto["valor_soma_corpo"]},
                                "last": {"max": {"field": dialeto["data"]}},
                            },
                        },
                    },
                }
            },
        }
    return {
        "terms": {"field": spec["id"], "size": size, "order": {"value": "desc"}},
        "aggs": {
            "nome": {"top_hits": {"size": 1, "_source": True}},
            "value": {"sum": dialeto["valor_soma_corpo"]},
            "last": {"max": {"field": dialeto["data"]}},
        },
    }


def rank_rows(
    country: Optional[str],
    role: str,
    agg: Optional[Dict[str, Any]],
    top: int,
    total_value: Optional[float],
) -> List[Dict[str, Any]]:
    """Linhas do ranking (nº, nome, valor, nº de contratos, quota, última data).

    Normaliza as duas formas: nested (PT/FR — valor dentro de `value`) e plana
    (ES — `value` é o próprio `sum`).
    """
    if not agg:
        return []
    nested = "top" in agg
    buckets = (((agg.get("top") or {}).get("buckets")) if nested else agg.get("buckets")) or []
    rows: List[Dict[str, Any]] = []
    for bucket in buckets:
        chave = bucket.get("key")
        if not chave:
            continue
        if nested:
            valor = (((bucket.get("value") or {}).get("sum")) or {}).get("value")
            ultima = ((bucket.get("value") or {}).get("last")) or {}
        else:
            valor = (bucket.get("value") or {}).get("value")
            ultima = bucket.get("last") or {}
        rows.append(
            {
                "nif": str(chave),
                "name": rank_row_name(country, role, bucket) or str(chave),
                "count": int(bucket.get("doc_count") or 0),
                "value": round(float(valor), 2) if valor is not None else None,
                "last_date": ultima.get("value_as_string") or None,
            }
        )
    rows.sort(key=lambda row: (row.get("value") or 0.0, row.get("count") or 0), reverse=True)
    for posicao, row in enumerate(rows):
        row["rank"] = posicao + 1
        row["share_pct"] = (
            round(100.0 * (row.get("value") or 0.0) / total_value, 2) if total_value else None
        )
    return rows[:top]


def rank_row_name(country: Optional[str], role: str, bucket: Dict[str, Any]) -> str:
    """Nome de uma linha de ranking, a partir do `top_hits` respetivo."""
    hits = (((bucket.get("nome") or {}).get("hits")) or {}).get("hits") or []
    for hit in hits:
        nome = nome_da_entidade(hit.get("_source"), country, role)
        if nome:
            return nome
    return ""


def cardinality_agg(country: Optional[str], role: str) -> Dict[str, Any]:
    """Cardinalidade (nº de entidades distintas) de um papel no país."""
    spec = party(country, role)
    nested = spec.get("nested")
    if nested:
        return {"nested": {"path": nested}, "aggs": {"value": {"cardinality": {"field": spec["id"]}}}}
    return {"cardinality": {"field": spec["id"]}}


def cardinality_value(agg: Optional[Dict[str, Any]]) -> int:
    """Valor de uma cardinalidade, seja nested (PT/FR) ou plana (ES)."""
    dados = agg or {}
    internos = dados.get("value") if isinstance(dados.get("value"), dict) else dados
    return int(((internos or {}).get("value")) or 0)



def value_filters(country: Optional[str]) -> List[Dict[str, Any]]:
    """Filtro de valores utilizáveis: positivos e abaixo do teto de sanidade."""
    spec = dialect(country)
    return [{"range": {spec["valor_campo"]: {"gt": 0, "lte": spec["valor_teto"]}}}]


def value_sum(country: Optional[str]) -> Dict[str, Any]:
    """Fonte da soma de valores do país, pronta a usar como agregação."""
    return {"sum": dialect(country)["valor_soma_corpo"]}


def year_filter(country: Optional[str], year_from: Optional[int], year_to: Optional[int]) -> Optional[Dict[str, Any]]:
    """Filtro do intervalo de anos (o campo muda de nome entre países)."""
    faixa: Dict[str, Any] = {}
    if year_from is not None:
        faixa["gte"] = int(year_from)
    if year_to is not None:
        faixa["lte"] = int(year_to)
    if not faixa:
        return None
    return {"range": {dialect(country)["ano"]: faixa}}


def cpv_filter(country: Optional[str], cpv_code: Optional[str]) -> Optional[Dict[str, Any]]:
    """Filtro por CPV (prefixo: `90511000` casa `90511000-2`)."""
    codigo = (cpv_code or "").strip()
    if not codigo:
        return None
    spec = dialect(country)["cpv"]
    return {"nested": {"path": spec["nested"], "query": {"prefix": {spec["code"]: codigo}}}}


def region_filter(country: Optional[str], region: Optional[str]) -> Optional[Dict[str, Any]]:
    """Filtro geográfico (em PT reutiliza a lógica de NUTs/distrito já existente)."""
    texto = (region or "").strip()
    if not texto:
        return None
    spec = dialect(country)
    if spec["geografia"].get("usa_region_filter"):
        from api.elasticsearch_client import _region_filter

        return _region_filter(texto)
    campo = spec["geografia"]["field"]
    return {
        "bool": {
            "should": [
                {"term": {campo: texto}},
                {"prefix": {campo: texto}},
            ],
            "minimum_should_match": 1,
        }
    }


# ------------------------------------------------------------------- agregações

def cpv_agg(country: Optional[str], size: int, *, com_mediana: bool = False) -> Dict[str, Any]:
    """Nested `terms` por CPV, com valor somado (e mediana opcional) por país."""
    spec = dialect(country)["cpv"]
    valor = dialect(country)["valor_campo"]
    aggs: Dict[str, Any] = {
        "description": {"top_hits": {"size": 1, "_source": True}},
        "value": {"reverse_nested": {}, "aggs": {"sum": value_sum(country)}},
    }
    if com_mediana:
        aggs["value"]["aggs"]["pc"] = {"percentiles": {"field": valor, "percents": [50]}}
    return {
        "nested": {"path": spec["nested"]},
        "aggs": {
            "top": {
                "terms": {"field": spec["code"], "size": size, "order": {"_count": "desc"}},
                "aggs": aggs,
            }
        },
    }


def cpv_rows(country: Optional[str], agg: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Linhas `{code, description, count, value, median}` de um perfil de CPV."""
    spec = dialect(country)["cpv"]
    rows: List[Dict[str, Any]] = []
    for item in (((agg or {}).get("top") or {}).get("buckets")) or []:
        valor = (((item.get("value") or {}).get("sum")) or {}).get("value")
        mediana = ((((item.get("value") or {}).get("pc")) or {}).get("values") or {}).get("50.0")
        rows.append(
            {
                "code": str(item.get("key")),
                "description": _cpv_descricao(item.get("description"), item.get("key"), spec["descricao"]),
                "count": int(item.get("doc_count") or 0),
                "value": round(float(valor), 2) if valor is not None else None,
                "median": round(float(mediana), 2) if mediana is not None else None,
            }
        )
    return rows


def _cpv_descricao(agg: Optional[Dict[str, Any]], code: Any, chave: str) -> str:
    """Descrição legível de um CPV a partir de `top_hits` (a chave varia por país)."""
    hits = (((agg or {}).get("hits")) or {}).get("hits") or []
    for hit in hits:
        source = hit.get("_source") if isinstance(hit, dict) else None
        if not isinstance(source, dict):
            continue
        if source.get("code") == code and source.get(chave):
            return str(source[chave])
        if source.get(chave) and not source.get("code"):
            return str(source[chave])
    for hit in hits:
        source = hit.get("_source") if isinstance(hit, dict) else None
        if isinstance(source, dict):
            entries = source.get("cpv") if isinstance(source.get("cpv"), list) else [source]
            for entry in entries:
                if isinstance(entry, dict) and entry.get(chave):
                    return str(entry[chave])
    return ""


def ano_agg(country: Optional[str], size: int = 50) -> Dict[str, Any]:
    """Anos disponíveis, do mais recente para o mais antigo."""
    return {"terms": {"field": dialect(country)["ano"], "size": size, "order": {"_key": "desc"}}}


def _nome_em(objeto: Any) -> str:
    """Nome dentro de um objeto de parte (`nome`/`nom`) ou do seu `parsed`."""
    if not isinstance(objeto, dict):
        return ""
    for chave in ("nome", "nom", "name"):
        valor = objeto.get(chave)
        if isinstance(valor, str) and valor.strip():
            return valor.strip()
    parsed = objeto.get("parsed")
    if isinstance(parsed, dict):
        return _nome_em(parsed)
    if isinstance(parsed, list):
        for item in parsed:
            nome = _nome_em(item)
            if nome:
                return nome
    return ""


def nome_da_entidade(source: Optional[Dict[str, Any]], country: Optional[str], role: str) -> str:
    """Nome legível a partir do `_source` de um `top_hits` (nested ou plano).

    O `_source` tanto pode ser o documento do contrato (com a parte em
    `adjudicatarios`/`titulaires`, e, em PT, dentro de `parsed`) como o próprio
    documento nested da parte.
    """
    if not isinstance(source, dict):
        return ""
    spec = party(country, role)
    if spec.get("nested"):
        raiz = spec["nested"].split(".")[0]
        valor = source.get(raiz)
        candidatos = valor if isinstance(valor, list) else ([valor] if isinstance(valor, dict) else [])
        for item in candidatos:
            nome = _nome_em(item)
            if nome:
                return nome
        return _nome_em(source)
    valor = source.get(spec["nome"])
    if isinstance(valor, str) and valor.strip():
        return valor.strip()
    return ""
