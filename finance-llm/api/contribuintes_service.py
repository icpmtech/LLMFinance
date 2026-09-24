"""Contribuintes: índice único com todos os **NIF/NIPC** do sistema.

O índice `finance_contribuintes` é **derivado**: não tem recolha própria, é
reconstruído a partir de todos os índices da plataforma que guardam
identificadores fiscais. Cada documento é um contribuinte (um NIF/NIPC) com:

- as designações conhecidas (a preferida em `name`, todas em `names`);
- o **tipo** de contribuinte (empresa, pessoa, empresário, entidade pública,
  estrangeiro), o país e a validade do dígito de controlo;
- de que **fontes** veio (`sources`) e com que **papéis** aparece
  (`roles`: adjudicante, adjudicatário, insolvente, credor, gerente, firma, marca…);
- os totais por fonte (contratos e valor, publicações societárias, processos
  CIRE, marcas, firmas, cargos, conta de CRM) e as datas de atividade;
- a evidência em bruto de cada fonte em `src_<fonte>` (não indexada), que
  alimenta a ficha do contribuinte.

Fontes percorridas (todas por agregação, sem ler documentos um a um):

======  ==============================================  ==========================
Índice                                          O que dá
======  ==============================================  ==========================
`contratos`  Contratos públicos PT: adjudicantes e adjudicatários
`contratos_es`  Contratos públicos de Espanha (PLACSP)
`finance_entities`  Cadastro de entidades do Portal BASE
`finance_publicacoes_mj`  Publicações societárias (NIF e matrícula)
`finance_cire`  Insolvências/revitalizações (intervenientes e papéis)
`finance_people`  Pessoas e cargos (PessoasIQ)
`finance_firmas`  Firmas e denominações (RNPC)
`finance_trademarks`  Marcas (INPI) — titulares
`finance_crm`  Contas do CRM
======  ==============================================  ==========================

Como a sincronização é feita (`run_sync`):

1. cada fonte é agregada com uma `composite aggregation` paginada (memória
   constante, independentemente do tamanho do índice) e o resultado é
   acumulado num **registo SQLite temporário** (`data/contribuintes/parts.sqlite3`),
   para não manter centenas de milhares de contribuintes em memória;
2. o registo é lido por NIF, os contributos das várias fontes são fundidos e
   os documentos finais são escritos em `bulk` no índice de contribuintes;
3. o `run_id` marca os documentos escritos nesta passagem: os que ficaram de
   sincronizações anteriores são apagados (uma sincronização completa é uma
   reconstrução, não um append).

Sincronizações parciais (um subconjunto de fontes) fundem-se com o que já
está no índice, e não apagam nada.

O módulo expõe também o **agendamento cron** (`contribuintes_scheduler.py`) e
as rotas `/contribuintes/*` (`contribuintes_routes.py`).
"""
from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Tuple

from elasticsearch.helpers import bulk

from api.elasticsearch_client import (
    CIRE_INDEX,
    CONTRIBUINTES_INDEX,
    CONTRATOS_ES_INDEX,
    CONTRACTS_INDEX,
    CRM_INDEX,
    ENTITIES_INDEX,
    FIRMAS_INDEX,
    PEOPLE_INDEX,
    SOCIETARIO_INDEX,
    TRADEMARKS_INDEX,
    ensure_indices,
    get_es_client,
)

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "contribuintes"
CONFIG_PATH = DATA_DIR / "config.json"
LOCK_PATH = DATA_DIR / "sync.lock"
# Registo temporário da sincronização: um ficheiro por passagem, para que duas
# sincronizações (cron, API, script) nunca colidam no mesmo ficheiro.
LEDGER_PREFIX = "parts-"
LOCK_MAX_AGE_S = 6 * 3600
#: Sem heartbeat durante este tempo, o cadeado é considerado órfão: uma
#: sincronização pendurada numa página não pode bloquear indefinidamente as
#: seguintes (o maior pedido possível são 4 tentativas de 3 min).
LOCK_STALE_AFTER_S = int(os.getenv("CONTRIBUINTES_LOCK_STALE", "1200"))

# Tamanho de página das agregações `composite` (valores distintos por pedido) e
# do bloco de escrita no Elasticsearch. Uma página maior reduz muito o número de
# passagens sobre índices grandes (15 M de contratos são varridos em cada
# página), pelo que é a alavanca principal da duração da sincronização.
DEFAULT_PAGE_SIZE = 5000
MAX_PAGE_SIZE = 5000
WRITE_CHUNK = 2000
#: Página usada nas repetições quando uma página grande falha (menos pressão no
#: Elasticsearch e muito menos probabilidade de «read past EOF»).
RECOVERY_PAGE_SIZE = 400
#: Limite de tempo (segundos) de cada pedido de agregação ao Elasticsearch.
#: Curto de propósito: com o cluster sobrecarregado os pedidos penduram-se.
REQUEST_TIMEOUT_S = int(os.getenv("CONTRIBUINTES_TIMEOUT", "180"))

DEFAULT_CONFIG: Dict[str, Any] = {
    "enabled": False,
    "cron": "0 3 * * *",
    "timezone": "Europe/Lisbon",
    "page_size": DEFAULT_PAGE_SIZE,
    "sources": None,
    "last_run": None,
    "history": [],
}

# --------------------------------------------------------------------------
# Catálogo de fontes
# --------------------------------------------------------------------------
# Cada fonte tem um ou mais "specs": uma passagem de agregação sobre um campo
# com NIF/NIPC (com `nested` quando o campo vive dentro de um objeto aninhado).
#   field        campo agregado (keyword)
#   nested       caminho aninhado a percorrer, se aplicável
#   name_fields  campos do documento a usar como designação
#   roles        papéis atribuídos a esta passagem
#   role_field   campo (aninhado) com o papel variável (ex.: CIRE `papel`)
#   detail       campos extra a guardar na evidência
#   metrics      agregações de valor/data: nome → (campo, tipo)
#   query        filtro aplicado a esta passagem
SOURCES: List[Dict[str, Any]] = [
    {
        "id": "contratos",
        "label": "Contratos públicos (PT)",
        "index": CONTRACTS_INDEX,
        "specs": [
            {
                "key": "adjudicante",
                "nested": "adjudicantes.parsed",
                "field": "adjudicantes.parsed.nif",
                "name_fields": ["nome"],
                "roles": ["adjudicante"],
                # `localExecucao` («Portugal, Distrito, Concelho») vive na **raiz**
                # do contrato e é a principal fonte de localização: dentro da
                # agregação aninhada só chega pelo `reverse_nested`.
                "root_detail": ["localExecucao"],
                "metrics": {
                    "first": ("dataCelebracaoContrato", "min"),
                    "last": ("dataCelebracaoContrato", "max"),
                    "value": ("precoContratual", "sum"),
                },
            },
            {
                "key": "adjudicatario",
                "nested": "adjudicatarios.parsed",
                "field": "adjudicatarios.parsed.nif",
                "name_fields": ["nome"],
                "roles": ["adjudicatario"],
                "root_detail": ["localExecucao"],
                "metrics": {
                    "first": ("dataCelebracaoContrato", "min"),
                    "last": ("dataCelebracaoContrato", "max"),
                    "value": ("precoContratual", "sum"),
                },
            },
        ],
    },
    {
        "id": "contratos_es",
        "label": "Contratos públicos (ES)",
        "index": CONTRATOS_ES_INDEX,
        "country": "Espanha",
        "specs": [
            {
                "key": "adjudicatario",
                "field": "adjudicatario_nif",
                "name_fields": ["adjudicatario_nombre"],
                "roles": ["adjudicatario"],
                "detail": ["adjudicatario_nuts", "adjudicatario_nacionalidad"],
                "metrics": {
                    "first": ("fecha_adjudicacion", "min"),
                    "last": ("fecha_adjudicacion", "max"),
                    "value": ("valor_adjudicado", "sum"),
                },
            },
        ],
    },
    {
        "id": "entidades",
        "label": "Cadastro de entidades",
        "index": ENTITIES_INDEX,
        "specs": [
            {
                "key": "cadastro",
                "field": "nif",
                "name_fields": ["name"],
                "roles": ["cadastro"],
                "detail": [
                    "contracts_count",
                    "total_value",
                    "country",
                    "country_code",
                    "as_adjudicante_count",
                    "as_adjudicatario_count",
                ],
            },
        ],
    },
    {
        "id": "societario",
        "label": "Publicações societárias (MJ)",
        "index": SOCIETARIO_INDEX,
        "specs": [
            {
                "key": "publicacao",
                "field": "nif",
                "name_fields": ["entidade", "firma"],
                "roles": ["societario"],
                "detail": ["concelho", "distrito", "freguesia", "codigo_postal", "tipo_label", "natureza_juridica"],
                "metrics": {
                    "first": ("data_publicacao", "min"),
                    "last": ("data_publicacao", "max"),
                },
            },
            {
                "key": "matricula",
                "field": "matricula_nipc",
                "name_fields": ["entidade", "firma"],
                "roles": ["matriculado"],
                "metrics": {
                    "first": ("data_publicacao", "min"),
                    "last": ("data_publicacao", "max"),
                },
            },
        ],
    },
    {
        "id": "cire",
        "label": "Insolvências (CIRE)",
        "index": CIRE_INDEX,
        "specs": [
            {
                "key": "interveniente",
                "nested": "intervenientes",
                "field": "intervenientes.nif",
                "name_fields": ["nome"],
                "role_field": "papel",
                "roles": ["interveniente"],
                # Tribunal, espécie e tipo descrevem o processo (raiz do documento),
                # não o interveniente aninhado.
                "root_detail": ["tribunal_comarca", "especie", "tipo"],
                "metrics": {
                    "first": ("data_publicacao", "min"),
                    "last": ("data_publicacao", "max"),
                },
            },
        ],
    },
    {
        "id": "pessoas",
        "label": "Pessoas e cargos (PessoasIQ)",
        "index": PEOPLE_INDEX,
        "specs": [
            {
                "key": "ficha",
                "field": "nif",
                "name_fields": ["name"],
                "roles": ["pessoa"],
                "detail": ["is_company", "roles_count", "companies_count", "source"],
            },
        ],
    },
    {
        "id": "firmas",
        "label": "Firmas (RNPC)",
        "index": FIRMAS_INDEX,
        "specs": [
            {
                "key": "firma",
                "field": "nipc",
                "name_fields": ["nome"],
                "roles": ["firma"],
                "detail": ["concelho", "situacao", "cae_principal", "score"],
            },
        ],
    },
    {
        "id": "marcas",
        "label": "Marcas (INPI)",
        "index": TRADEMARKS_INDEX,
        "specs": [
            {
                "key": "titular",
                "field": "holder_nif",
                "name_fields": ["holder_name"],
                "roles": ["titular_marca"],
                "detail": ["mark_type", "modality", "current_phase"],
            },
            {
                # O INPI só devolve o NIF do titular em parte dos registos; o NIF da
                # empresa pesquisada (`company_nif`) preenche a lacuna.
                "key": "empresa",
                "field": "company_nif",
                "name_fields": ["holder_name"],
                "roles": ["titular_marca"],
                "detail": ["mark_type", "modality", "current_phase"],
            },
        ],
    },
    {
        "id": "crm",
        "label": "CRM (contas)",
        "index": CRM_INDEX,
        "specs": [
            {
                "key": "conta",
                "field": "nif",
                "query": {"term": {"kind": "account"}},
                "name_fields": ["name"],
                "roles": ["crm"],
                "detail": ["sector", "status", "city", "country", "postal_code"],
            },
        ],
    },
]

SOURCE_BY_ID: Dict[str, Dict[str, Any]] = {source["id"]: source for source in SOURCES}
SOURCE_ORDER: List[str] = [source["id"] for source in SOURCES]

# Ordem de preferência das designações: a mais "oficial" primeiro.
NAME_PRIORITY: List[str] = [
    "entidades",
    "societario",
    "pessoas",
    "firmas",
    "contratos",
    "contratos_es",
    "crm",
    "marcas",
    "cire",
]

# Ordem de apresentação dos papéis na ficha.
ROLE_ORDER: List[str] = [
    "cadastro",
    "adjudicante",
    "adjudicatario",
    "firma",
    "titular_marca",
    "societario",
    "matriculado",
    "insolvente",
    "administrador",
    "credor",
    "interveniente",
    "gerente",
    "socio",
    "pessoa",
    "crm",
]


# --------------------------------------------------------------------------
# NIF/NIPC
# --------------------------------------------------------------------------

_NIF_RE = re.compile(r"[^0-9A-Za-z]")
_PT_KIND_BY_DIGIT: Dict[str, Tuple[str, bool]] = {
    "1": ("pessoa", False),
    "2": ("pessoa", False),
    "3": ("pessoa", False),
    "5": ("empresa", True),
    "6": ("entidade_publica", False),
    "7": ("estrangeiro", False),
    "8": ("empresario", False),
    "9": ("outro", False),
}

TYPE_LABELS: Dict[str, str] = {
    "empresa": "Empresa",
    "pessoa": "Pessoa singular",
    "empresario": "Empresário em nome individual",
    "entidade_publica": "Entidade pública",
    "estrangeiro": "Contribuinte estrangeiro",
    "outro": "Outro contribuinte",
    "desconhecido": "Tipo desconhecido",
}


def normalize_nif(value: Any) -> str:
    """Normaliza um NIF/NIPC: sem espaços, pontuação ou prefixo de país."""
    if value is None:
        return ""
    text = str(value).strip().upper()
    text = re.sub(r"^(PT|ES|PT-|ES-)\s*", "", text)
    text = _NIF_RE.sub("", text)
    if not text or not any(ch.isdigit() for ch in text) or not (4 <= len(text) <= 20):
        return ""
    return text


def nif_checksum_valid(nif: str) -> bool:
    """Valida o dígito de controlo de um NIF português (módulo 11)."""
    digits = normalize_nif(nif)
    if len(digits) != 9 or not digits.isdigit() or digits[0] == "0":
        return False
    total = sum(int(digit) * (9 - position) for position, digit in enumerate(digits[:8]))
    check = 11 - (total % 11)
    if check >= 10:
        check = 0
    return check == int(digits[8])


def classify_nif(nif: str, *, is_company: Optional[bool] = None, country: Optional[str] = None) -> Dict[str, Any]:
    """Classifica um contribuinte (tipo, país e validade do NIF).

    ``nif_valid`` só é preenchido para NIF portugueses (9 dígitos): nos
    estrangeiros não há dígito de controlo a validar, pelo que o campo fica
    ausente em vez de sugerir um erro.
    """
    digits = normalize_nif(nif)
    if len(digits) == 9 and digits.isdigit() and digits[0] in _PT_KIND_BY_DIGIT:
        kind, company = _PT_KIND_BY_DIGIT[digits[0]]
        if is_company is True and kind in ("pessoa", "empresario", "outro"):
            kind, company = "empresa", True
        return {
            "type": kind,
            "is_company": bool(company),
            "nif_valid": nif_checksum_valid(digits),
            "country": country or "Portugal",
        }
    if country == "Espanha":
        return {"type": "estrangeiro", "is_company": bool(is_company), "country": "Espanha"}
    return {
        "type": "estrangeiro" if digits else "desconhecido",
        "is_company": bool(is_company),
        "country": country or "Internacional",
    }


def _fold(value: Any) -> str:
    """Texto para pesquisa: sem acentos, minúsculas e espaços colapsados."""
    import unicodedata

    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text).strip().lower()


# --------------------------------------------------------------------------
# Configuração (ficheiro JSON, como as fontes da Recolha)
# --------------------------------------------------------------------------

_config_lock = threading.RLock()


def load_config() -> Dict[str, Any]:
    """Configuração do módulo (agendamento, página, histórico recente)."""
    config = dict(DEFAULT_CONFIG)
    try:
        if CONFIG_PATH.exists():
            stored = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(stored, dict):
                config.update(stored)
    except Exception as exc:
        logger.warning("Configuração de contribuintes ilegível (%s): %s", CONFIG_PATH, exc)
    config["page_size"] = _clamp_page_size(config.get("page_size"))
    if not isinstance(config.get("history"), list):
        config["history"] = []
    return config


def save_config(patch: Dict[str, Any]) -> Dict[str, Any]:
    """Grava (parcialmente) a configuração do módulo."""
    with _config_lock:
        config = load_config()
        for key, value in (patch or {}).items():
            if key in ("last_run", "history") or value is None:
                config[key] = value
                continue
            config[key] = value
        config["page_size"] = _clamp_page_size(config.get("page_size"))
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
        return config


def _clamp_page_size(value: Any) -> int:
    try:
        size = int(value)
    except (TypeError, ValueError):
        return DEFAULT_PAGE_SIZE
    return max(100, min(size, MAX_PAGE_SIZE))


def validate_cron(expression: str) -> None:
    """Valida uma expressão cron de 5 campos (minuto hora dia mês dia-semana)."""
    parts = str(expression or "").split()
    if len(parts) != 5:
        raise ValueError("Expressão cron inválida: são precisos 5 campos (minuto hora dia mês dia-semana).")
    checks = [
        (parts[0], 0, 59, "minuto"),
        (parts[1], 0, 23, "hora"),
        (parts[2], 1, 31, "dia do mês"),
        (parts[3], 1, 12, "mês"),
        (parts[4], 0, 7, "dia da semana"),
    ]
    for token, low, high, label in checks:
        if token == "*":
            continue
        for chunk in token.split(","):
            step = chunk
            if "/" in chunk:
                step, _, step_value = chunk.partition("/")
                if not step_value.isdigit() or int(step_value) < 1:
                    raise ValueError(f"Passo inválido no campo {label}: {chunk!r}.")
                step = step or "*"
            if step == "*":
                continue
            if "-" in step:
                start, _, end = step.partition("-")
                if not (start.isdigit() and end.isdigit()):
                    raise ValueError(f"Intervalo inválido no campo {label}: {chunk!r}.")
                if not (low <= int(start) <= high and low <= int(end) <= high):
                    raise ValueError(f"Valores fora do intervalo no campo {label}: {chunk!r}.")
                continue
            if not step.isdigit():
                raise ValueError(f"Valor inválido no campo {label}: {chunk!r}.")
            if not (low <= int(step) <= high):
                raise ValueError(f"Valores fora do intervalo no campo {label}: {chunk!r}.")


def meta() -> Dict[str, Any]:
    """Metadados do módulo: fontes, índice e agendamento."""
    config = load_config()
    return {
        "index": CONTRIBUINTES_INDEX,
        "title": "Contribuintes",
        "description": (
            "Índice único com todos os contribuintes (NIF/NIPC) do sistema, "
            "agregado a partir de todos os índices da plataforma."
        ),
        "sources": [
            {
                "id": source["id"],
                "label": source["label"],
                "index": source["index"],
                "fields": [spec["field"] for spec in source["specs"]],
                "roles": sorted({role for spec in source["specs"] for role in spec.get("roles") or []}),
            }
            for source in SOURCES
        ],
        "types": [{"id": key, "label": label} for key, label in TYPE_LABELS.items()],
        "schedule": {
            "enabled": bool(config.get("enabled")),
            "cron": config.get("cron"),
            "timezone": config.get("timezone"),
        },
        "page_size": config.get("page_size"),
        "last_run": config.get("last_run"),
    }


# --------------------------------------------------------------------------
# Agregação das fontes (composite, paginada)
# --------------------------------------------------------------------------


def _spec_aggs(
    spec: Dict[str, Any],
    page_size: int,
    after: Optional[Dict[str, Any]],
    *,
    with_top: bool = True,
) -> Dict[str, Any]:
    """Corpo de agregação de uma passagem (uma spec).

    ``with_top=False`` omite o `top_hits` que traz as designações: serve de
    alternativa quando o Elasticsearch devolve erro 500 nestas agregações
    (acontece com o índice a ser reescrito em paralelo) — os nomes acabam por vir
    das restantes fontes.
    """
    composite: Dict[str, Any] = {
        "size": page_size,
        "sources": [{"value": {"terms": {"field": spec["field"], "missing_bucket": False}}}],
    }
    if after:
        composite["after"] = after
    sub: Dict[str, Any] = {}
    if with_top:
        sub["top"] = {"top_hits": {"size": 3, "_source": list(spec.get("top_hits") or [])}}
    metrics: Dict[str, Tuple[str, str]] = dict(spec.get("metrics") or {})
    root_fields = [field for field in list(spec.get("root_detail") or []) if field]
    back_aggs: Dict[str, Any] = {}
    if metrics:
        back_aggs.update({name: {kind: {"field": field}} for name, (field, kind) in metrics.items()})
    if root_fields and with_top and spec.get("nested"):
        # O `top_hits` dentro de uma agregação `nested` devolve o **objeto
        # aninhado**: os campos da raiz (localização do contrato, tribunal do
        # CIRE…) só são acessíveis depois de voltar ao documento pai.
        back_aggs["root"] = {"top_hits": {"size": 1, "_source": root_fields}}
    if spec.get("nested"):
        if back_aggs:
            sub["back"] = {"reverse_nested": {}, "aggs": back_aggs}
    else:
        sub.update(back_aggs)
    node: Dict[str, Any] = {"composite": composite, "aggs": sub}
    if spec.get("nested"):
        return {"n": {"nested": {"path": spec["nested"]}, "aggs": {"c": node}}}
    return {"c": node}


def _spec_top_hits(spec: Dict[str, Any]) -> List[str]:
    """Campos a trazer no `top_hits` (designação, papel e extras).

    Dentro de uma agregação `nested`, o `top_hits` devolve o **objeto aninhado**
    e o filtro `_source` tem de usar o caminho completo
    (`adjudicatarios.parsed.nome`); com o nome simples (`nome`) a resposta vem
    vazia — era o que deixava os contratos e o CIRE sem designações.

    Os campos de `root_detail` vivem na raiz do documento e por isso **não**
    levam o prefixo: numa spec aninhada vêm pelo `reverse_nested` (ver
    `_spec_aggs`), nas restantes pelo próprio `top_hits`.
    """
    fields: List[str] = []
    for field in list(spec.get("name_fields") or []):
        if field not in fields:
            fields.append(field)
    role_field = spec.get("role_field")
    if role_field and role_field not in fields:
        fields.append(role_field)
    for field in list(spec.get("detail") or []):
        if field not in fields:
            fields.append(field)
    nested = str(spec.get("nested") or "").strip(".")
    if nested:
        prefix = f"{nested}."
        fields = [field if field.startswith(prefix) else f"{prefix}{field}" for field in fields]
    else:
        for field in list(spec.get("root_detail") or []):
            if field and field not in fields:
                fields.append(field)
    return fields


def _metric_value(bucket: Dict[str, Any], spec: Dict[str, Any], name: str) -> Optional[float]:
    node = bucket.get("back") if spec.get("nested") else bucket
    metric = (node or {}).get(name) or {}
    value = metric.get("value")
    if value is None:
        return None
    if metric.get("value_as_string"):
        return metric["value_as_string"]
    return value


def _bucket_payload(source_id: str, spec: Dict[str, Any], bucket: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Converte um `bucket` de agregação no contributo de uma fonte para um NIF."""
    nif = normalize_nif((bucket.get("key") or {}).get("value"))
    if not nif:
        return None
    hits = ((bucket.get("top") or {}).get("hits") or {}).get("hits") or []
    names: List[str] = []
    roles: List[str] = []
    detail: Dict[str, Any] = {}
    role_field = spec.get("role_field")
    for hit in hits:
        fields = hit.get("_source") or {}
        for field in list(spec.get("name_fields") or []):
            name = str(fields.get(field) or "").strip()
            if name and name not in names:
                names.append(name)
        if role_field:
            role = str(fields.get(role_field) or "").strip()
            if role and role not in roles:
                roles.append(role)
        for field in list(spec.get("detail") or []):
            value = fields.get(field)
            if value in (None, "", [], {}):
                continue
            if field in ("contracts_count", "total_value", "as_adjudicante_count", "as_adjudicatario_count", "roles_count", "companies_count", "score"):
                if isinstance(value, (int, float)) and float(value) == 0:
                    continue
            detail.setdefault(field, value)
    root_fields = [field for field in list(spec.get("root_detail") or []) if field]
    if root_fields:
        # Campos da raiz do documento: dentro da agregação aninhada só chegam
        # pelo `reverse_nested` (ver `_spec_aggs`); nas specs planas já vieram
        # no `top_hits` normal, acima.
        root_hits = (((bucket.get("back") or {}).get("root") or {}).get("hits") or {}).get("hits") or []
        sources = root_hits or hits
        for hit in sources:
            source_fields = hit.get("_source") or {}
            for field in root_fields:
                value = source_fields.get(field)
                if value in (None, "", [], {}):
                    continue
                detail.setdefault(field, value)
    payload: Dict[str, Any] = {
        "nif": nif,
        "count": int(bucket.get("doc_count") or 0),
        "names": names[:5],
        "detail": detail,
    }
    roles = list(spec.get("roles") or []) + roles
    if role_field and roles:
        payload["roles"] = roles
    elif spec.get("roles"):
        payload["roles"] = list(spec["roles"])
    value = _metric_value(bucket, spec, "value")
    if value is not None:
        payload["value"] = round(float(value), 2)
    first = _metric_value(bucket, spec, "first")
    last = _metric_value(bucket, spec, "last")
    if first is not None:
        payload["first"] = _as_iso(first)
    if last is not None:
        payload["last"] = _as_iso(last)
    if source_id and spec.get("country"):
        payload["country"] = spec["country"]
    return payload


def _as_iso(value: Any) -> Optional[str]:
    """Normaliza datas vindas das agregações (ISO ou epoch em milissegundos)."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value) / 1000.0, tz=timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    return str(value)


def _search_with_retry(client: Any, index: str, body: Dict[str, Any], *, attempts: int = 4, delay: float = 2.0) -> Dict[str, Any]:
    """Executa uma pesquisa com repetição — as agregações grandes sofrem de falhas
    transitórias do Elasticsearch (IO, escritas concorrentes no índice) sem que o
    índice esteja doente.

    O limite por pedido é curto de propósito (``REQUEST_TIMEOUT_S``): quando o
    Elasticsearch está sobrecarregado, um pedido pode ficar pendurado; com um
    limite de 15 minutos a sincronização ficava presa meia hora na mesma página.
    """
    last_error: Optional[Exception] = None
    for attempt in range(1, max(1, attempts) + 1):
        try:
            return client.search(index=index, body=body, request_timeout=REQUEST_TIMEOUT_S)
        except Exception as exc:  # noqa: BLE001 - devolve o erro original se esgotar
            last_error = exc
            if attempt < attempts:
                logger.warning("Contribuintes: pesquisa em %s falhou (%s); nova tentativa %s/%s", index, exc, attempt + 1, attempts)
                time.sleep(delay * attempt)
    raise last_error if last_error else RuntimeError("pesquisa falhou")


def _collect_spec(
    client: Any,
    ledger: sqlite3.Connection,
    source: Dict[str, Any],
    spec: Dict[str, Any],
    *,
    page_size: int,
    progress: Optional[Callable[[Dict[str, Any]], None]] = None,
    counters: Optional[Dict[str, int]] = None,
) -> Dict[str, int]:
    """Percorre uma passagem de agregação e grava os contributos no registo.

    O dicionário ``counters`` é atualizado à medida que as páginas são lidas:
    se a agregação falhar a meio (erro transitório do Elasticsearch), o que já
    foi recolhido fica no registo e é contabilizado no resumo.
    """
    counters = counters if counters is not None else {"pages": 0, "buckets": 0, "nifs": 0}
    counters.setdefault("pages", 0)
    counters.setdefault("buckets", 0)
    counters.setdefault("nifs", 0)
    after: Optional[Dict[str, Any]] = None
    spec = {**spec, "top_hits": _spec_top_hits(spec)}
    while True:
        body: Dict[str, Any] = {"size": 0, "track_total_hits": False, "aggs": _spec_aggs(spec, page_size, after)}
        if spec.get("query"):
            body["query"] = spec["query"]
        try:
            response = _search_with_retry(client, source["index"], body, attempts=3)
        except Exception as exc:
            # As falhas transitórias («read past EOF») acontecem sobretudo nas
            # páginas grandes. Antes de desistir das designações (e da
            # localização, que vem no `top_hits`), repete com uma página mais
            # pequena: o `after_key` da agregação composta não depende do
            # tamanho da página, pelo que a paginação continua correta.
            response = None
            if page_size > RECOVERY_PAGE_SIZE:
                smaller = {"size": 0, "track_total_hits": False, "aggs": _spec_aggs(spec, RECOVERY_PAGE_SIZE, after)}
                if spec.get("query"):
                    smaller["query"] = spec["query"]
                try:
                    response = _search_with_retry(client, source["index"], smaller, attempts=2)
                    logger.info(
                        "Contribuintes: %s.%s recuperado com página de %d.",
                        source["id"],
                        spec.get("key"),
                        RECOVERY_PAGE_SIZE,
                    )
                except Exception:
                    response = None
            if response is None:
                # Última oportunidade sem `top_hits`: perdem-se as designações
                # desta página (que vêm das restantes fontes), mas os totais
                # ficam certos.
                logger.warning(
                    "Contribuintes: %s.%s falhou com nomes (%s); nova tentativa sem top_hits.",
                    source["id"],
                    spec.get("key"),
                    exc,
                )
                fallback = {
                    "size": 0,
                    "track_total_hits": False,
                    "aggs": _spec_aggs(spec, RECOVERY_PAGE_SIZE, after, with_top=False),
                }
                if spec.get("query"):
                    fallback["query"] = spec["query"]
                try:
                    response = _search_with_retry(client, source["index"], fallback, attempts=2)
                except Exception as exc2:
                    raise RuntimeError(f"{source['id']}.{spec['key']}: {exc2}") from exc2
        node = response.get("aggregations", {})
        if spec.get("nested"):
            node = (node.get("n") or {}).get("c") or {}
        else:
            node = node.get("c") or {}
        buckets = node.get("buckets") or []
        rows: List[Tuple[str, str, str, str]] = []
        for bucket in buckets:
            payload = _bucket_payload(source["id"], spec, bucket)
            if not payload:
                continue
            rows.append((payload["nif"], source["id"], spec["key"], json.dumps(payload, ensure_ascii=False)))
        if rows:
            ledger.executemany(
                "INSERT OR REPLACE INTO parts (nif, source, spec_key, payload) VALUES (?, ?, ?, ?)",
                rows,
            )
            ledger.commit()
        counters["pages"] += 1
        counters["buckets"] += len(buckets)
        counters["nifs"] += len(rows)
        _touch_lock()
        if progress:
            progress(
                {
                    "source": source["id"],
                    "spec": spec["key"],
                    "pages": counters["pages"],
                    "nifs": counters["nifs"],
                }
            )
        after = node.get("after_key")
        if not buckets or not after:
            break
    return counters


def _open_ledger(path: Path) -> sqlite3.Connection:
    """Abre o registo SQLite temporário da sincronização."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    connection = sqlite3.connect(str(path), timeout=60)
    connection.execute("PRAGMA journal_mode=OFF")
    connection.execute("PRAGMA synchronous=OFF")
    connection.execute("PRAGMA temp_store=MEMORY")
    connection.execute(
        "CREATE TABLE parts ("
        "  nif TEXT NOT NULL,"
        "  source TEXT NOT NULL,"
        "  spec_key TEXT NOT NULL,"
        "  payload TEXT NOT NULL,"
        "  PRIMARY KEY (nif, source, spec_key)"
        ") WITHOUT ROWID"
    )
    return connection


# --------------------------------------------------------------------------
# Cadeado entre processos (cron, API e scripts partilham o índice)
# --------------------------------------------------------------------------


def _pid_alive(pid: Any) -> bool:
    """Diz se um processo ainda existe.

    Serve para reconhecer um cadeado deixado por um processo que morreu (crash,
    terminal fechado, `Ctrl+C`): sem isto, uma sincronização interrompida
    bloqueava as seguintes durante `LOCK_MAX_AGE_S` (6 horas). Em caso de dúvida
    devolve `True` — nunca declarar obsoleto o cadeado de um processo vivo.
    """
    try:
        number = int(pid)
    except (TypeError, ValueError):
        return False
    if number <= 0:
        return False
    if os.name == "nt":  # pragma: no cover - depende do sistema
        try:
            import subprocess

            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {number}", "/NH"],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except Exception:
            return True
        return str(number) in (result.stdout or "")
    try:  # pragma: no cover - POSIX
        os.kill(number, 0)
        return True
    except OSError:
        return False


def _acquire_lock(run_id: str) -> None:
    """Marca a sincronização em curso; recusa (RuntimeError) se já houver uma.

    O cadeado é um ficheiro criado em modo exclusivo (``O_EXCL``). É substituído
    quando o processo que o criou já não existe ou quando não dá sinal de vida há
    ``LOCK_STALE_AFTER_S`` (uma sincronização pendurada não pode bloquear as
    seguintes; o dono vai tocando no ficheiro com ``_touch_lock``).
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"run_id": run_id, "pid": os.getpid(), "started_at": _now_iso()}, ensure_ascii=False)
    try:
        handle = os.open(str(LOCK_PATH), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        age = time.time() - LOCK_PATH.stat().st_mtime
        stale = age >= LOCK_STALE_AFTER_S
        current = ""
        if stale:
            logger.warning("Cadeado de contribuintes sem progresso há %.0f s: a substituir.", age)
        else:
            try:
                current = LOCK_PATH.read_text(encoding="utf-8")[:200]
            except OSError:
                current = ""
            try:
                owner = json.loads(current or "{}").get("pid")
            except (ValueError, AttributeError):
                owner = None
            if owner is not None and not _pid_alive(owner):
                logger.warning("Cadeado de contribuintes de um processo inexistente (pid %s): a substituir.", owner)
                stale = True
        if not stale:
            raise RuntimeError(
                f"Já existe uma sincronização de contribuintes em curso ({current or 'cadeado ativo'})."
            )
        handle = os.open(str(LOCK_PATH), os.O_CREAT | os.O_TRUNC | os.O_WRONLY)
    try:
        os.write(handle, payload.encode("utf-8"))
    finally:
        os.close(handle)


def _release_lock() -> None:
    try:
        LOCK_PATH.unlink()
    except OSError:
        pass


def _touch_lock() -> None:
    """Marca o cadeado como vivo (a sincronização continua a fazer progresso)."""
    try:
        os.utime(LOCK_PATH, None)
    except OSError:
        pass


def _cleanup_ledgers(keep: Optional[Path] = None) -> None:
    """Remove registos temporários de passagens anteriores."""
    try:
        for path in DATA_DIR.glob(f"{LEDGER_PREFIX}*.sqlite3"):
            if keep is not None and path == keep:
                continue
            path.unlink()
    except OSError as exc:
        logger.debug("Limpeza de registos temporários falhou: %s", exc)


# --------------------------------------------------------------------------
# Construção dos documentos
# --------------------------------------------------------------------------


def _merge_specs(source: Dict[str, Any], specs: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Funde as várias passagens de uma fonte num só contributo."""
    names: List[str] = []
    roles: List[str] = []
    count = 0
    value = 0.0
    has_value = False
    first: Optional[str] = None
    last: Optional[str] = None
    detail: Dict[str, Any] = {}
    parts: Dict[str, Any] = {}
    country = source.get("country")
    for key, data in specs.items():
        count += int(data.get("count") or 0)
        if data.get("value") is not None:
            value += float(data["value"])
            has_value = True
        first = _earlier(first, data.get("first"))
        last = _later(last, data.get("last"))
        for name in data.get("names") or []:
            if name not in names:
                names.append(name)
        for role in data.get("roles") or []:
            if role not in roles:
                roles.append(role)
        if data.get("country"):
            country = data["country"]
        for field, entry in (data.get("detail") or {}).items():
            if entry not in (None, "", [], {}):
                detail.setdefault(field, entry)
        parts[key] = {
            "count": data.get("count"),
            "value": data.get("value"),
            "first": data.get("first"),
            "last": data.get("last"),
            "names": (data.get("names") or [])[:3],
        }
    block: Dict[str, Any] = {
        "label": source["label"],
        "count": count,
        "names": names[:8],
        "roles": roles,
        "parts": parts,
    }
    if has_value:
        block["value"] = round(value, 2)
    if first:
        block["first"] = first
    if last:
        block["last"] = last
    if detail:
        block["detail"] = detail
    if country:
        block["country"] = country
    block.pop("nif", None)
    return block


def _location_from_local_execucao(value: Any) -> Dict[str, str]:
    """«Portugal, Lisboa, Cascais» → `{pais, distrito, concelho}`.

    É o formato do `localExecucao` dos contratos públicos: a primeira parte é o
    pais, a segunda o distrito e a terceira o concelho. O campo é multi-valor e
    traz muitas vezes entradas com detalhe diferente (ex.: `["Portugal",
    "Portugal, Guarda, Fig. Castelo Rodrigo"]`), pelo que se aproveita a **mais
    completa**. Valores com menos partes são utilizados até onde for possivel.
    """
    values = value if isinstance(value, (list, tuple)) else [value]
    best: Dict[str, str] = {}
    for item in values:
        text = _text(item) or ""
        if not text:
            continue
        parts = [part.strip() for part in text.split(",") if part.strip()]
        if not parts:
            continue
        candidate: Dict[str, str] = {"pais": parts[0]}
        if len(parts) >= 2:
            candidate["distrito"] = parts[1]
        if len(parts) >= 3:
            candidate["concelho"] = parts[2]
        if len(candidate) > len(best):
            best = candidate
    return best


def _merge_location(location: Dict[str, Any], candidate: Dict[str, str]) -> None:
    """Acrescenta localização apenas nos campos ainda vazios (a 1.ª fonte manda)."""
    for key, value in candidate.items():
        if value and not location.get(key):
            location[key] = value


def _earlier(current: Optional[str], candidate: Optional[str]) -> Optional[str]:
    if not candidate:
        return current
    if not current:
        return candidate
    return candidate if str(candidate) < str(current) else current


def _later(current: Optional[str], candidate: Optional[str]) -> Optional[str]:
    if not candidate:
        return current
    if not current:
        return candidate
    return candidate if str(candidate) > str(current) else current


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _text(value: Any) -> Optional[str]:
    if value is None or isinstance(value, (dict, list)):
        return None
    text = str(value).strip()
    return text or None


def _build_doc(nif: str, blocks: Dict[str, Dict[str, Any]], run_id: str) -> Dict[str, Any]:
    """Constrói o documento final de um contribuinte a partir dos blocos das fontes."""
    doc: Dict[str, Any] = {"nif": nif, "run_id": run_id, "synced_at": _now_iso()}
    sources: List[str] = []
    roles: List[str] = []
    names: List[str] = []
    seen_names: set = set()

    def add_name(value: Any) -> None:
        """Acrescenta uma designação, sem repetir (comparação sem acentos/maiúsculas)."""
        text = _text(value)
        if not text:
            return
        key = _fold(text)
        if not key or key in seen_names:
            return
        seen_names.add(key)
        names.append(text)

    for source_id in NAME_PRIORITY:
        block = blocks.get(source_id)
        if block:
            for name in block.get("names") or []:
                add_name(name)
    for source_id in SOURCE_ORDER:
        block = blocks.get(source_id)
        if not block:
            continue
        sources.append(source_id)
        for name in block.get("names") or []:
            add_name(name)
        for role in block.get("roles") or []:
            if role not in roles:
                roles.append(role)
        doc[f"src_{source_id}"] = block

    # --- identificação ----------------------------------------------------
    doc["names"] = names[:20]
    doc["name"] = names[0] if names else nif
    doc["name_norm"] = _fold(doc["name"])
    doc["sources"] = sources
    doc["source_labels"] = sorted({blocks[source_id].get("label", source_id) for source_id in sources})

    # --- métricas por fonte ----------------------------------------------
    records_total = 0
    first_seen: Optional[str] = None
    last_seen: Optional[str] = None
    is_company_hint: Optional[bool] = None
    country: Optional[str] = None
    location: Dict[str, Any] = {}
    # Local de execução dos contratos: só entra na localização se as fontes de
    # **sede** (publicações societárias, firmas, CRM) não a tiverem preenchido.
    contracts_location: Dict[str, str] = {}
    cire_roles: List[str] = []

    for source_id in sources:
        block = blocks[source_id]
        detail = block.get("detail") or {}
        parts = block.get("parts") or {}
        records_total += int(block.get("count") or 0)
        first_seen = _earlier(first_seen, block.get("first"))
        last_seen = _later(last_seen, block.get("last"))
        if block.get("country"):
            country = block["country"]

        if source_id == "contratos":
            doc["contracts_count"] = int(block.get("count") or 0)
            doc["contracts_as_adjudicante"] = int((parts.get("adjudicante") or {}).get("count") or 0)
            doc["contracts_as_adjudicatario"] = int((parts.get("adjudicatario") or {}).get("count") or 0)
            if block.get("value") is not None:
                doc["contracts_value"] = block["value"]
            if block.get("first"):
                doc["contracts_first_date"] = block["first"]
            if block.get("last"):
                doc["contracts_last_date"] = block["last"]
            contracts_location = _location_from_local_execucao(detail.get("localExecucao"))
        elif source_id == "contratos_es":
            doc["contratos_es_count"] = int(block.get("count") or 0)
            if block.get("value") is not None:
                doc["contratos_es_value"] = block["value"]
            if block.get("last"):
                doc["contratos_es_last_date"] = block["last"]
        elif source_id == "entidades":
            count = _number(detail.get("contracts_count"))
            if count:
                doc["entities_contracts_count"] = int(count)
            value = _number(detail.get("total_value"))
            if value:
                doc["entities_value"] = round(value, 2)
            country = _text(detail.get("country")) or country
        elif source_id == "societario":
            doc["societario_count"] = int(block.get("count") or 0)
            if block.get("last"):
                doc["societario_last_date"] = block["last"]
            for field in ("distrito", "concelho", "freguesia", "codigo_postal"):
                value = _text(detail.get(field))
                if value and field not in location:
                    location[field] = value
        elif source_id == "cire":
            doc["cire_count"] = int(block.get("count") or 0)
            if block.get("last"):
                doc["cire_last_date"] = block["last"]
            for role in block.get("roles") or []:
                if role != "interveniente" and role not in cire_roles:
                    cire_roles.append(role)
        elif source_id == "pessoas":
            roles_count = _number(detail.get("roles_count"))
            if roles_count:
                doc["people_roles_count"] = int(roles_count)
            companies_count = _number(detail.get("companies_count"))
            if companies_count:
                doc["people_companies_count"] = int(companies_count)
            if isinstance(detail.get("is_company"), bool):
                is_company_hint = detail["is_company"]
        elif source_id == "firmas":
            doc["firmas_count"] = int(block.get("count") or 0)
            if not location.get("concelho"):
                value = _text(detail.get("concelho"))
                if value:
                    location["concelho"] = value
        elif source_id == "marcas":
            doc["trademarks_count"] = int(block.get("count") or 0)
        elif source_id == "crm":
            doc["crm_account"] = True
            # Nomes normalizados para os mesmos campos de `location` que as
            # restantes fontes usam (o CRM traz `city`/`country`/`postal_code`).
            _merge_location(
                location,
                {
                    "concelho": _text(detail.get("city")) or "",
                    "pais": _text(detail.get("country")) or "",
                    "codigo_postal": _text(detail.get("postal_code")) or "",
                },
            )

    # --- classificação ----------------------------------------------------
    # A sede (publicações societárias, firmas, CRM) tem prioridade; o local de
    # execução dos contratos preenche o que ficou em falta — é o que dá
    # localização a centenas de milhares de contribuintes com contratos.
    _merge_location(location, contracts_location)
    profile = classify_nif(nif, is_company=is_company_hint, country=country)
    doc.update(profile)
    if location:
        doc["location"] = location
    if cire_roles:
        doc["cire_roles"] = cire_roles
    doc["roles"] = sorted(
        set(roles),
        key=lambda role: (ROLE_ORDER.index(role) if role in ROLE_ORDER else len(ROLE_ORDER), role),
    )
    doc["records_total"] = records_total
    if first_seen:
        doc["first_seen"] = first_seen
    if last_seen:
        doc["last_seen"] = last_seen
    doc["search_text"] = " ".join(
        [nif] + names[:8] + doc["roles"] + [TYPE_LABELS.get(doc["type"], ""), doc.get("country") or ""]
    ).strip()
    return doc


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iter_docs(ledger: sqlite3.Connection, run_id: str) -> Iterator[Dict[str, Any]]:
    """Gera os documentos finais, um NIF de cada vez (memória constante)."""
    cursor = ledger.execute("SELECT nif, source, spec_key, payload FROM parts ORDER BY nif")
    current: Optional[str] = None
    blocks: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for nif, source_id, spec_key, payload in cursor:
        if nif != current:
            if current is not None:
                yield _build_doc(current, _merge_blocks(blocks), run_id)
            current = nif
            blocks = {}
        try:
            data = json.loads(payload)
        except (TypeError, ValueError):
            continue
        blocks.setdefault(source_id, {})[spec_key] = data
    if current is not None:
        yield _build_doc(current, _merge_blocks(blocks), run_id)


def _merge_blocks(blocks: Dict[str, Dict[str, Dict[str, Any]]]) -> Dict[str, Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}
    for source_id, specs in blocks.items():
        source = SOURCE_BY_ID.get(source_id)
        if not source:
            continue
        merged[source_id] = _merge_specs(source, specs)
    return merged


# --------------------------------------------------------------------------
# Escrita no índice
# --------------------------------------------------------------------------


def _existing_blocks(client: Any, nifs: List[str]) -> Dict[str, Dict[str, Any]]:
    """Blocos já indexados, prontos a fundir (chave = id da fonte, sem `src_`).

    O `_source` traz as chaves com o prefixo (`src_contratos`), mas o
    `_build_doc` procura-as pelo **id da fonte** (`contratos`). Devolver as
    chaves com prefixo fazia com que uma sincronização parcial ignorasse tudo o
    que já estava indexado — os contribuintes ficavam só com a fonte da passagem
    (bug corrigido nesta revisão).
    """
    out: Dict[str, Dict[str, Any]] = {}
    if not nifs:
        return out
    try:
        response = client.mget(index=CONTRIBUINTES_INDEX, body={"ids": [f"{CONTRIBUINTES_INDEX}:{nif}" for nif in nifs]})
    except Exception as exc:
        logger.debug("mget de contribuintes falhou: %s", exc)
        return out
    for doc in response.get("docs") or []:
        if not doc.get("found"):
            continue
        source = doc.get("_source") or {}
        nif = normalize_nif(source.get("nif"))
        if not nif:
            continue
        out[nif] = {
            key[len("src_") :]: value
            for key, value in source.items()
            if key.startswith("src_") and isinstance(value, dict)
        }
    return out


def _write_docs(
    client: Any,
    docs: Iterable[Dict[str, Any]],
    *,
    merge_existing: bool = False,
    keep_sources: Optional[Iterable[str]] = None,
    chunk_size: int = WRITE_CHUNK,
    progress: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """Escreve os documentos no índice de contribuintes.

    ``keep_sources`` permite preservar, do documento já indexado, apenas os
    blocos dessas fontes. Serve para uma passagem **completa** em que algumas
    fontes falharam: em vez de perder os dados dessas fontes, ficam os que já
    estavam no índice.
    """
    keep = {str(source) for source in (keep_sources or [])}
    written = 0
    errors = 0
    chunk: List[Dict[str, Any]] = []
    total = 0

    def flush() -> None:
        nonlocal written, errors, chunk, total
        if not chunk:
            return
        payload = chunk
        chunk = []
        if merge_existing:
            existing = _existing_blocks(client, [doc["nif"] for doc in payload])
            merged: List[Dict[str, Any]] = []
            for doc in payload:
                previous = existing.get(doc["nif"], {})
                blocks = {
                    key: value
                    for key, value in previous.items()
                    if not keep or key in keep
                }
                blocks.update({key[len("src_") :]: value for key, value in doc.items() if key.startswith("src_")})
                merged.append(_build_doc(doc["nif"], blocks, doc["run_id"]))
            payload = merged
        actions = [
            {
                "_op_type": "index",
                "_index": CONTRIBUINTES_INDEX,
                "_id": f"{CONTRIBUINTES_INDEX}:{doc['nif']}",
                **doc,
            }
            for doc in payload
        ]
        try:
            success, failed = bulk(client, actions, raise_on_error=False, refresh=False)
            written += success
            if failed:
                errors += len(failed)
        except Exception as exc:
            logger.warning("Escrita de contribuintes falhou: %s", exc)
            errors += len(actions)
        total += len(actions)
        _touch_lock()
        if progress:
            progress({"phase": "write", "written": written, "total": total})

    for doc in docs:
        chunk.append(doc)
        if len(chunk) >= chunk_size:
            flush()
    flush()
    return {"written": written, "errors": errors, "total": total}


def _delete_stale(client: Any, run_id: str) -> int:
    """Apaga os contribuintes que não foram vistos na passagem atual."""
    try:
        response = client.delete_by_query(
            index=CONTRIBUINTES_INDEX,
            body={"query": {"bool": {"must_not": [{"term": {"run_id": run_id}}]}}},
            refresh=False,
            conflicts="proceed",
        )
        return int(response.get("deleted") or 0)
    except Exception as exc:
        logger.warning("Limpeza de contribuintes obsoletos falhou: %s", exc)
        return 0


# --------------------------------------------------------------------------
# Sincronização
# --------------------------------------------------------------------------


def _select_sources(sources: Optional[Iterable[str]]) -> List[Dict[str, Any]]:
    if not sources:
        return list(SOURCES)
    wanted: List[str] = []
    for raw in sources:
        source_id = str(raw).strip()
        if source_id and source_id not in wanted:
            wanted.append(source_id)
    unknown = [source_id for source_id in wanted if source_id not in SOURCE_BY_ID]
    if unknown:
        raise ValueError(f"Fontes desconhecidas: {', '.join(unknown)}")
    if not wanted:
        return list(SOURCES)
    return [SOURCE_BY_ID[source_id] for source_id in wanted]


def run_sync(
    sources: Optional[Iterable[str]] = None,
    *,
    page_size: Optional[int] = None,
    progress: Optional[Callable[[Dict[str, Any]], None]] = None,
    trigger: str = "manual",
) -> Dict[str, Any]:
    """Reconstrói (total ou parcialmente) o índice de contribuintes.

    Sem `sources`, percorre todas as fontes e o índice é **substituído**: os
    contribuintes que já não apareçam em nenhuma fonte são apagados. Com um
    subconjunto de fontes, o resultado é fundido com o que já está indexado.
    """
    started = time.time()
    client = get_es_client(request_timeout=900)
    if client is None:
        raise RuntimeError("Elasticsearch indisponível: não é possível sincronizar contribuintes.")
    config = load_config()
    page_size = _clamp_page_size(page_size or config.get("page_size"))
    selected = _select_sources(sources)
    full = len(selected) == len(SOURCES)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    ensure_indices(client)

    summary: Dict[str, Any] = {
        "run_id": run_id,
        "trigger": trigger,
        "started_at": _now_iso(),
        "full": full,
        "page_size": page_size,
        "sources": {},
        "errors": [],
    }

    _acquire_lock(run_id)
    ledger_path = DATA_DIR / f"{LEDGER_PREFIX}{run_id}.sqlite3"
    _cleanup_ledgers(keep=ledger_path)
    ledger: Optional[sqlite3.Connection] = None
    try:
        ledger = _open_ledger(ledger_path)
        for source in selected:
            source_stats: Dict[str, Any] = {"label": source["label"], "index": source["index"], "nifs": 0, "pages": 0}
            source_started = time.time()
            for spec in source["specs"]:
                try:
                    _collect_spec(
                        client,
                        ledger,
                        source,
                        spec,
                        page_size=page_size,
                        progress=progress,
                        counters=source_stats,
                    )
                except Exception as exc:
                    logger.warning("Contribuintes: fonte %s (%s) falhou: %s", source["id"], spec["key"], exc)
                    summary["errors"].append(
                        {
                            "source": source["id"],
                            "spec": spec["key"],
                            "error": str(exc),
                            "partial_nifs": source_stats.get("nifs", 0),
                        }
                    )
                    continue
            source_stats["seconds"] = round(time.time() - source_started, 2)
            summary["sources"][source["id"]] = source_stats
            if progress:
                progress({"phase": "source-done", "source": source["id"], "sources": summary["sources"]})

        # Fontes que falharam: os seus blocos são preservados do que já estava
        # indexado (uma passagem incompleta não deve apagar dados de uma fonte).
        failed = {str(error.get("source")) for error in summary["errors"] if error.get("source")}
        if failed:
            logger.warning("Contribuintes: fontes com falha (%s) mantêm os dados já indexados.", ", ".join(sorted(failed)))

        write_stats = _write_docs(
            client,
            _iter_docs(ledger, run_id),
            merge_existing=not full or bool(failed),
            keep_sources=failed,
            progress=progress,
        )
        summary["written"] = write_stats["written"]
        summary["write_errors"] = write_stats["errors"]
        summary["unique"] = write_stats["total"]
        summary["preserved_sources"] = sorted(failed)
        # Só se pode remover contribuintes obsoletos quando todas as fontes
        # correram: com fontes em falta, um NIF ausente pode vir delas.
        summary["deleted"] = _delete_stale(client, run_id) if (full and not failed) else 0
        try:
            client.indices.refresh(index=CONTRIBUINTES_INDEX)
        except Exception:
            pass
    finally:
        if ledger is not None:
            try:
                ledger.close()
            except Exception:
                pass
        try:
            ledger_path.unlink()
        except OSError:
            pass
        _release_lock()

    summary["duration_s"] = round(time.time() - started, 2)
    summary["finished_at"] = _now_iso()
    summary["status"] = "ok" if not summary["errors"] else "parcial"
    _record_run(summary)
    return summary


def _record_run(summary: Dict[str, Any]) -> None:
    """Guarda o resultado da sincronização na configuração (histórico recente)."""
    with _config_lock:
        config = load_config()
        config["last_run"] = summary
        history = [entry for entry in config.get("history") or [] if isinstance(entry, dict)]
        history.insert(0, summary)
        config["history"] = history[:20]
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


# --------------------------------------------------------------------------
# Jobs (sincronizações em segundo plano)
# --------------------------------------------------------------------------

_jobs: Dict[str, Dict[str, Any]] = {}
_jobs_lock = threading.RLock()
_sync_lock = threading.Lock()
MAX_JOBS = 20


def start_sync(
    sources: Optional[Iterable[str]] = None,
    *,
    page_size: Optional[int] = None,
    trigger: str = "manual",
    background: bool = True,
) -> Dict[str, Any]:
    """Arranca uma sincronização (em segundo plano por omissão)."""
    if _sync_lock.locked():
        return {"error": "Já existe uma sincronização de contribuintes em curso.", "running": True, "jobs": jobs()}
    job_id = f"contribuintes-{uuid.uuid4().hex[:10]}"
    job: Dict[str, Any] = {
        "id": job_id,
        "status": "running",
        "trigger": trigger,
        "started_at": _now_iso(),
        "progress": {"phase": "start"},
        "summary": None,
        "error": None,
    }
    with _jobs_lock:
        _jobs[job_id] = job
        for stale in sorted(_jobs, key=lambda key: _jobs[key].get("started_at") or "")[:-MAX_JOBS]:
            _jobs.pop(stale, None)

    if not background:
        _execute_job(job_id, sources, page_size, trigger)
        return {"job_id": job_id, **_jobs[job_id]}

    thread = threading.Thread(
        target=_execute_job,
        args=(job_id, sources, page_size, trigger),
        name=f"contribuintes-sync-{job_id}",
        daemon=True,
    )
    thread.start()
    return {"job_id": job_id, "status": "running", "started_at": job["started_at"]}


def _execute_job(
    job_id: str,
    sources: Optional[Iterable[str]],
    page_size: Optional[int],
    trigger: str,
) -> None:
    job = _jobs.get(job_id)
    if job is None:
        return
    if not _sync_lock.acquire(blocking=False):
        job.update({"status": "error", "error": "Sincronização concorrente.", "finished_at": _now_iso()})
        return
    try:
        def on_progress(payload: Dict[str, Any]) -> None:
            job["progress"] = {**payload, "at": time.time()}

        summary = run_sync(sources, page_size=page_size, progress=on_progress, trigger=trigger)
        job.update({"status": "ok", "summary": summary, "finished_at": _now_iso()})
    except Exception as exc:
        logger.exception("Sincronização de contribuintes falhou")
        job.update({"status": "error", "error": str(exc), "finished_at": _now_iso()})
    finally:
        _sync_lock.release()


def jobs() -> List[Dict[str, Any]]:
    """Sincronizações em curso e recentes (mais recentes primeiro)."""
    with _jobs_lock:
        items = list(_jobs.values())
    items.sort(key=lambda job: job.get("started_at") or "", reverse=True)
    return items


def job(job_id: str) -> Optional[Dict[str, Any]]:
    with _jobs_lock:
        return _jobs.get(job_id)


def sync_running() -> bool:
    with _jobs_lock:
        return any(job.get("status") == "running" for job in _jobs.values())


# --------------------------------------------------------------------------
# Pesquisa e ficha
# --------------------------------------------------------------------------


def _base_query(
    q: Optional[str] = None,
    *,
    source: Optional[str] = None,
    role: Optional[str] = None,
    type_: Optional[str] = None,
    country: Optional[str] = None,
    is_company: Optional[bool] = None,
    has_contracts: Optional[bool] = None,
) -> Dict[str, Any]:
    must: List[Dict[str, Any]] = []
    filters: List[Dict[str, Any]] = []
    text = (q or "").strip()
    if text:
        should: List[Dict[str, Any]] = []
        normalized = normalize_nif(text)
        if normalized:
            should.append({"term": {"nif": normalized}})
        fields = ["name^4", "name.autocomplete^3", "names^3", "nif^5", "search_text"]
        should.append({"multi_match": {"query": text, "fields": fields, "type": "best_fields", "operator": "and", "boost": 3}})
        should.append({"multi_match": {"query": text, "fields": fields, "type": "best_fields", "operator": "or"}})
        must.append({"bool": {"should": should, "minimum_should_match": 1}})
    if source:
        filters.append({"term": {"sources": source}})
    if role:
        filters.append({"term": {"roles": role}})
    if type_:
        filters.append({"term": {"type": type_}})
    if country:
        filters.append({"term": {"country": country}})
    if is_company is not None:
        filters.append({"term": {"is_company": bool(is_company)}})
    if has_contracts is not None:
        clause = {"range": {"contracts_count": {"gte": 1}}}
        filters.append(clause if has_contracts else {"bool": {"must_not": [clause]}})
    if not must and not filters:
        return {"match_all": {}}
    body: Dict[str, Any] = {}
    if must:
        body["must"] = must
    if filters:
        body["filter"] = filters
    return {"bool": body}


_SORTS: Dict[str, List[Any]] = {
    "relevance": [{"records_total": {"order": "desc", "missing": 0}}, "_score"],
    "activity": [{"last_seen": {"order": "desc", "missing": "_last"}}, {"records_total": {"order": "desc", "missing": 0}}],
    "contracts": [{"contracts_count": {"order": "desc", "missing": 0}}, "_score"],
    "value": [{"contracts_value": {"order": "desc", "missing": 0}}, "_score"],
    "name": [{"name.keyword": {"order": "asc", "missing": "_last"}}],
    "nif": [{"nif": {"order": "asc"}}],
}


def search(
    q: Optional[str] = None,
    *,
    source: Optional[str] = None,
    role: Optional[str] = None,
    type_: Optional[str] = None,
    country: Optional[str] = None,
    is_company: Optional[bool] = None,
    has_contracts: Optional[bool] = None,
    sort: str = "relevance",
    size: int = 20,
    from_: int = 0,
    include_detail: bool = True,
) -> Dict[str, Any]:
    """Pesquisa contribuintes (nome, NIF, papéis) com filtros por fonte e tipo."""
    client = get_es_client()
    if client is None:
        return {"error": "Elasticsearch indisponível", "items": [], "total": 0}
    ensure_indices(client)
    size = max(1, min(int(size or 20), 200))
    from_ = max(0, int(from_ or 0))
    body: Dict[str, Any] = {
        "query": _base_query(
            q,
            source=source,
            role=role,
            type_=type_,
            country=country,
            is_company=is_company,
            has_contracts=has_contracts,
        ),
        "from": from_,
        "size": size,
        "sort": _SORTS.get(sort or "relevance", _SORTS["relevance"]),
        "track_total_hits": True,
    }
    if not include_detail:
        body["_source"] = {"excludes": [f"src_{source_id}" for source_id in SOURCE_ORDER]}
    try:
        response = client.search(index=CONTRIBUINTES_INDEX, body=body)
    except Exception as exc:
        return {"error": str(exc), "items": [], "total": 0}
    return {
        "total": response["hits"]["total"]["value"],
        "items": [{**hit["_source"], "doc_id": hit["_id"], "score": hit.get("_score")} for hit in response["hits"]["hits"]],
        "from": from_,
        "size": size,
        "sort": sort,
        "query": q,
    }


def autocomplete(q: str, size: int = 10) -> List[Dict[str, Any]]:
    """Sugestões de contribuintes (nome ou NIF) para caixas de pesquisa."""
    client = get_es_client()
    text = (q or "").strip()
    if client is None or len(text) < 2:
        return []
    try:
        response = client.search(
            index=CONTRIBUINTES_INDEX,
            body={
                "size": max(1, min(size, 25)),
                "_source": ["nif", "name", "type", "sources", "contracts_count"],
                "query": {
                    "bool": {
                        "should": [
                            {"term": {"nif": normalize_nif(text) or text.upper()}},
                            {"multi_match": {"query": text, "fields": ["name.autocomplete^3", "name^2", "names"], "type": "best_fields", "operator": "and"}},
                        ],
                        "minimum_should_match": 1,
                    }
                },
                "sort": ["_score", {"records_total": {"order": "desc", "missing": 0}}],
            },
        )
    except Exception as exc:
        logger.debug("Autocomplete de contribuintes falhou: %s", exc)
        return []
    return [
        {
            "nif": hit["_source"].get("nif"),
            "name": hit["_source"].get("name"),
            "type": hit["_source"].get("type"),
            "type_label": TYPE_LABELS.get(hit["_source"].get("type"), ""),
            "sources": hit["_source"].get("sources") or [],
            "contracts_count": hit["_source"].get("contracts_count") or 0,
        }
        for hit in response["hits"]["hits"]
    ]


def detail(nif: str) -> Dict[str, Any]:
    """Ficha de um contribuinte (com a evidência por fonte)."""
    client = get_es_client()
    if client is None:
        return {"error": "Elasticsearch indisponível"}
    ensure_indices(client)
    normalized = normalize_nif(nif)
    if not normalized:
        return {"error": "NIF inválido"}
    try:
        response = client.get(index=CONTRIBUINTES_INDEX, id=f"{CONTRIBUINTES_INDEX}:{normalized}", _source=True)
    except Exception as exc:
        if "NotFoundError" in type(exc).__name__:
            return {"error": "Contribuinte não encontrado no índice", "nif": normalized, "hint": "Sincronize o índice ou confirme o NIF."}
        return {"error": str(exc), "nif": normalized}
    source = dict(response.get("_source") or {})
    return {**source, "doc_id": response.get("_id"), "type_label": TYPE_LABELS.get(source.get("type"), "")}


def status() -> Dict[str, Any]:
    """Volumetria do índice de contribuintes (KPIs e distribuições)."""
    client = get_es_client()
    if client is None:
        return {"error": "Elasticsearch indisponível"}
    ensure_indices(client)
    config = load_config()
    try:
        total = int(client.count(index=CONTRIBUINTES_INDEX).get("count") or 0)
    except Exception as exc:
        return {"error": str(exc)}
    out: Dict[str, Any] = {
        "index": CONTRIBUINTES_INDEX,
        "documents": total,
        "running": sync_running(),
        "schedule": {
            "enabled": bool(config.get("enabled")),
            "cron": config.get("cron"),
            "timezone": config.get("timezone"),
        },
        "last_run": config.get("last_run"),
        "history": config.get("history") or [],
    }
    if not total:
        return out
    try:
        response = client.search(
            index=CONTRIBUINTES_INDEX,
            body={
                "size": 0,
                "track_total_hits": False,
                "aggs": {
                    "types": {"terms": {"field": "type", "size": 10}},
                    "countries": {"terms": {"field": "country", "size": 10}},
                    "sources": {"terms": {"field": "sources", "size": 20}},
                    "roles": {"terms": {"field": "roles", "size": 25}},
                    # Localização: o distrito e o concelho vêm dos contratos e do
                    # CIRE, pelo que só existem para parte do índice (daí o
                    # contador `with_location`, que diz sobre quantos incide).
                    "districts": {"terms": {"field": "location.distrito", "size": 25}},
                    "municipalities": {"terms": {"field": "location.concelho", "size": 25}},
                    "with_location": {"filter": {"exists": {"field": "location.distrito"}}},
                    # Matriz tipo × localização: é o que permite ver «que tipos
                    # de contribuinte há em cada distrito» numa só passagem.
                    "types_by_district": {
                        "terms": {"field": "location.distrito", "size": 20},
                        "aggs": {
                            "types": {"terms": {"field": "type", "size": 10}},
                            "value": {"sum": {"field": "contracts_value"}},
                        },
                    },
                    "companies": {"filter": {"term": {"is_company": True}}},
                    "with_contracts": {"filter": {"range": {"contracts_count": {"gte": 1}}}},
                    "with_cire": {"filter": {"range": {"cire_count": {"gte": 1}}}},
                    "invalid_nif": {"filter": {"term": {"nif_valid": False}}},
                    "contracts_value": {"sum": {"field": "contracts_value"}},
                    "last_seen": {"max": {"field": "last_seen"}},
                },
            },
        )
    except Exception as exc:
        out["error"] = str(exc)
        return out
    aggs = response.get("aggregations", {})

    def buckets(name: str) -> List[Dict[str, Any]]:
        return [{"key": bucket["key"], "count": bucket["doc_count"]} for bucket in (aggs.get(name) or {}).get("buckets") or []]

    out.update(
        {
            "types": [
                {"key": bucket["key"], "label": TYPE_LABELS.get(bucket["key"], bucket["key"]), "count": bucket["count"]}
                for bucket in buckets("types")
            ],
            "countries": buckets("countries"),
            "sources": [
                {"key": bucket["key"], "label": (SOURCE_BY_ID.get(bucket["key"]) or {}).get("label", bucket["key"]), "count": bucket["count"]}
                for bucket in buckets("sources")
            ],
            "roles": buckets("roles"),
            # Localização (distrito/concelho) e a matriz tipo × distrito.
            "districts": buckets("districts"),
            "municipalities": buckets("municipalities"),
            "with_location": (aggs.get("with_location") or {}).get("doc_count", 0),
            "types_by_district": [
                {
                    "key": bucket["key"],
                    "count": bucket["doc_count"],
                    "value": round(float(((bucket.get("value") or {}).get("value")) or 0.0), 2),
                    "types": [
                        {
                            "key": sub["key"],
                            "label": TYPE_LABELS.get(sub["key"], sub["key"]),
                            "count": sub["doc_count"],
                        }
                        for sub in ((bucket.get("types") or {}).get("buckets") or [])
                    ],
                }
                # Aqui não se usa o helper `buckets()`: ele achata os buckets e
                # perderia os sub-agregados (`types` e `value`).
                for bucket in ((aggs.get("types_by_district") or {}).get("buckets") or [])
            ],
            "companies": (aggs.get("companies") or {}).get("doc_count", 0),
            "with_contracts": (aggs.get("with_contracts") or {}).get("doc_count", 0),
            "with_cire": (aggs.get("with_cire") or {}).get("doc_count", 0),
            "invalid_nif": (aggs.get("invalid_nif") or {}).get("doc_count", 0),
            "contracts_value": round(float((aggs.get("contracts_value") or {}).get("value") or 0.0), 2),
            "last_seen": ((aggs.get("last_seen") or {}).get("value_as_string") if isinstance(aggs.get("last_seen"), dict) else None),
        }
    )
    return out


def delete_index_documents() -> Dict[str, Any]:
    """Esvazia o índice de contribuintes (obriga a uma nova sincronização)."""
    client = get_es_client()
    if client is None:
        return {"error": "Elasticsearch indisponível"}
    try:
        response = client.delete_by_query(
            index=CONTRIBUINTES_INDEX,
            body={"query": {"match_all": {}}},
            refresh=True,
            conflicts="proceed",
        )
        return {"deleted": int(response.get("deleted") or 0)}
    except Exception as exc:
        return {"error": str(exc)}


def schedule() -> Dict[str, Any]:
    """Estado do agendamento cron da sincronização."""
    config = load_config()
    status_payload: Dict[str, Any] = {}
    try:
        from api import contribuintes_scheduler

        status_payload = contribuintes_scheduler.status()
    except Exception as exc:  # pragma: no cover - só sem APScheduler
        status_payload = {"available": False, "error": str(exc), "jobs": []}
    return {
        "enabled": bool(config.get("enabled")),
        "cron": config.get("cron"),
        "timezone": config.get("timezone"),
        "sources": config.get("sources"),
        "page_size": config.get("page_size"),
        "last_run": config.get("last_run"),
        "history": (config.get("history") or [])[:10],
        "scheduler": status_payload,
    }


def set_schedule(
    *,
    enabled: Optional[bool] = None,
    cron: Optional[str] = None,
    timezone_name: Optional[str] = None,
    sources: Optional[Iterable[str]] = None,
    page_size: Optional[int] = None,
) -> Dict[str, Any]:
    """Atualiza o agendamento (e recarrega os jobs do agendador)."""
    patch: Dict[str, Any] = {}
    if enabled is not None:
        patch["enabled"] = bool(enabled)
    if cron is not None:
        expression = str(cron).strip()
        if expression:
            validate_cron(expression)
        patch["cron"] = expression
    if timezone_name is not None:
        patch["timezone"] = str(timezone_name).strip() or "Europe/Lisbon"
    if sources is not None:
        selected = _select_sources(sources)
        patch["sources"] = [source["id"] for source in selected]
    if page_size is not None:
        patch["page_size"] = _clamp_page_size(page_size)
    config = save_config(patch)
    if config.get("enabled") and not (config.get("cron") or "").strip():
        raise ValueError("Para ativar a sincronização automática é preciso uma expressão cron.")
    try:
        from api import contribuintes_scheduler

        contribuintes_scheduler.reload_jobs()
    except Exception as exc:  # pragma: no cover
        logger.debug("Agendador de contribuintes não recarregou: %s", exc)
    return schedule()
