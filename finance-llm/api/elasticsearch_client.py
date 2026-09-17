"""Cliente Elasticsearch para ingestão e pesquisa de dados financeiros.

Índices utilizados:
- finance_prices: histórico de preços de ações (OHLCV) por ticker.
- finance_news: notícias/sociais de ações por ticker.

Ambos suportam pesquisa por ticker, data e texto.
"""
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]

# Índice único para contratos públicos normalizados
CONTRACTS_INDEX = "contratos"

# Grupo usado para contratos sem valor no campo (ex.: sem NUTs): mantém estes
# contratos visíveis nos grafos em vez de os descartar silenciosamente.
UNSPECIFIED_LABEL = "Não especificado"
_UNSPECIFIED_KEYS = {"nao especificado", "não especificado", "unspecified", "n/a", "na"}


def is_unspecified(value: Optional[str]) -> bool:
    """Indica se um valor representa o grupo "sem informação" (aceita acentos/maiúsculas)."""
    if not value:
        return False
    normalized = value.strip().lower()
    normalized = normalized.replace("ã", "a").replace("á", "a")
    return normalized in _UNSPECIFIED_KEYS

# Índice para marcas do INPI indexadas por entidade
TRADEMARKS_INDEX = "finance_trademarks"

# Índice para firmas/nomes comerciais do RNPC (Pesquisa de Nomes Existentes)
FIRMAS_INDEX = "finance_firmas"

# Índice para o cadastro de entidades do portal base (data/entidades-gov-portal-base/entidades.json)
ENTITIES_INDEX = "finance_entities"

# Índice para preferências do utilizador (favoritos, pastas do dossier e histórico do EmpresasIQ).
# Evita depender do localStorage do browser, que se perde ao mudar de origem/porta ou ao limpar dados.
USER_STATE_INDEX = "finance_user_state"

# Índice de contas de utilizador (autenticação). O `_id` do documento é o email
# normalizado, o que garante unicidade sem necessitar de transações.
AUTH_USERS_INDEX = "finance_users"

# Índice de sessões (uma por início de sessão). Guarda a validade e a revogação,
# para que o "terminar sessão" seja imediato e auditável.
AUTH_SESSIONS_INDEX = "finance_sessions"

# Registo de eventos do sistema (autenticação, pedidos à API, tarefas, erros) —
# alimenta o visualizador de eventos da área de administração.
EVENTS_INDEX = "finance_events"

# Chaves de API dos fornecedores de IA (uma linha por utilizador; `_id` = user id).
PROVIDER_KEYS_INDEX = "finance_provider_keys"

# Módulo de CRM: contas, contactos, oportunidades e atividades num único índice.
# O campo `kind` distingue o tipo de registo e `owner_id` o utilizador dono
# (os administradores veem todos os registos).
CRM_INDEX = "finance_crm"

# Definições (settings) específicas de determinados índices — nomeadamente
# analisadores usados em subcampos de pesquisa por prefixo.
INDEX_SETTINGS: Dict[str, Dict[str, Any]] = {
    ENTITIES_INDEX: {
        "analysis": {
            "tokenizer": {
                # Permite pesquisa incremental: "SONAE" encontra "SONAECOM".
                "entity_edge_ngram": {
                    "type": "edge_ngram",
                    "min_gram": 2,
                    "max_gram": 20,
                    "token_chars": ["letter", "digit"],
                }
            },
            "analyzer": {
                "entity_index_analyzer": {
                    "type": "custom",
                    "tokenizer": "entity_edge_ngram",
                    "filter": ["lowercase", "asciifolding"],
                },
                "entity_search_analyzer": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                },
            },
        }
    }
}


def _get_es_url() -> str:
    return os.getenv("ELASTICSEARCH_URL", "http://127.0.0.1:9200")


def get_es_client() -> Optional[Elasticsearch]:
    """Devolve cliente Elasticsearch ou None se não estiver disponível."""
    try:
        es = Elasticsearch([_get_es_url()], request_timeout=30)
        if not es.ping():
            return None
        return es
    except Exception:
        return None


def ensure_indices(es: Optional[Elasticsearch] = None) -> bool:
    """Cria/atualiza os índices necessários, caso ainda não existam."""
    client = es or get_es_client()
    if not client:
        return False

    prices_mappings = {
        "properties": {
            "ticker": {"type": "keyword"},
            "date": {"type": "date"},
            "open": {"type": "float"},
            "high": {"type": "float"},
            "low": {"type": "float"},
            "close": {"type": "float"},
            "volume": {"type": "long"},
            "period": {"type": "keyword"},
            "ingested_at": {"type": "date"},
        }
    }

    news_mappings = {
        "properties": {
            "ticker": {"type": "keyword"},
            "title": {"type": "text"},
            "summary": {"type": "text"},
            "publisher": {"type": "keyword"},
            "published": {"type": "date"},
            "url": {"type": "keyword"},
            "source": {"type": "keyword"},
            "ingested_at": {"type": "date"},
            "analyzed_at": {"type": "date"},
            "sentiment": {"type": "keyword"},
            "language": {"type": "keyword"},
            "translated_title": {"type": "text"},
            "translated_summary": {"type": "text"},
            "summary_pt": {"type": "text"},
            "topics": {"type": "keyword"},
            "entities": {
                "type": "nested",
                "properties": {
                    "name": {"type": "keyword"},
                    "type": {"type": "keyword"},
                },
            },
        }
    }

    sentiment_mappings = {
        "properties": {
            "ticker": {"type": "keyword"},
            "date": {"type": "date"},
            "news_count": {"type": "integer"},
            "sentiment_mean": {"type": "float"},
            "sentiment_std": {"type": "float"},
            "positive_count": {"type": "integer"},
            "negative_count": {"type": "integer"},
            "positive_ratio": {"type": "float"},
            "negative_ratio": {"type": "float"},
            "updated_at": {"type": "date"},
        }
    }

    macro_mappings = {
        "properties": {
            "name": {"type": "keyword"},
            "date": {"type": "date"},
            "value": {"type": "float"},
            "updated_at": {"type": "date"},
        }
    }

    earnings_mappings = {
        "properties": {
            "ticker": {"type": "keyword"},
            "date": {"type": "date"},
            "eps_estimate": {"type": "float"},
            "reported_eps": {"type": "float"},
            "surprise_pct": {"type": "float"},
            "updated_at": {"type": "date"},
        }
    }

    contracts_mappings = {
        "properties": {
            "idcontrato": {"type": "keyword"},
            "nAnuncio": {"type": "keyword"},
            "TipoAnuncio": {"type": "keyword"},
            "idINCM": {"type": "keyword"},
            "tipoContrato": {"type": "keyword"},
            "idprocedimento": {"type": "keyword"},
            "tipoprocedimento": {"type": "text"},
            "objectoContrato": {"type": "text"},
            "descContrato": {"type": "text"},
            "adjudicantes": {
                "type": "nested",
                "properties": {
                    "raw": {"type": "keyword"},
                    "parsed": {
                        "type": "nested",
                        "properties": {
                            "nif": {"type": "keyword"},
                            "nome": {
                                "type": "text",
                                "fields": {
                                    "keyword": {"type": "keyword", "ignore_above": 512}
                                }
                            },
                        },
                    },
                },
            },
            "adjudicatarios": {
                "type": "nested",
                "properties": {
                    "raw": {"type": "keyword"},
                    "parsed": {
                        "type": "nested",
                        "properties": {
                            "nif": {"type": "keyword"},
                            "nome": {
                                "type": "text",
                                "fields": {
                                    "keyword": {"type": "keyword", "ignore_above": 512}
                                }
                            },
                        },
                    },
                },
            },
            "dataPublicacao": {"type": "date", "format": "yyyy-MM-dd||yyyy/MM/dd HH:mm:ss||epoch_millis"},
            "dataCelebracaoContrato": {"type": "date", "format": "yyyy-MM-dd||yyyy/MM/dd HH:mm:ss||epoch_millis"},
            "dataDecisaoAdjudicacao": {"type": "date", "format": "yyyy-MM-dd||yyyy/MM/dd HH:mm:ss||epoch_millis"},
            "dataFechoContrato": {"type": "date", "format": "yyyy-MM-dd||yyyy/MM/dd HH:mm:ss||epoch_millis"},
            "precoContratual": {"type": "float"},
            "cpv": {
                "type": "nested",
                "properties": {
                    "code": {"type": "keyword"},
                    "description": {"type": "text"},
                },
            },
            "prazoExecucao": {"type": "float"},
            "localExecucao": {"type": "keyword"},
            "fundamentacao": {"type": "text"},
            "ProcedimentoCentralizado": {"type": "keyword"},
            "numAcordoQuadro": {"type": "keyword"},
            "DescrAcordoQuadro": {"type": "text"},
            "precoBaseProcedimento": {"type": "float"},
            "PrecoTotalEfetivo": {"type": "float"},
            "regime": {"type": "text"},
            "justifNReducEscrContrato": {"type": "text"},
            "tipoFimContrato": {"type": "keyword"},
            "CritMateriais": {"type": "keyword"},
            "concorrentes": {"type": "text"},
            "linkPecasProc": {"type": "keyword"},
            "Observacoes": {"type": "text"},
            "ContratEcologico": {"type": "keyword"},
            "Ano": {"type": "integer"},
            "fundamentAjusteDireto": {"type": "text"},
            "adjudicatarioPMEs": {"type": "keyword"},
            "NUTs": {"type": "keyword"},
            "Lotes": {"type": "text"},
            "TipoCriterioAdjudicacao": {"type": "keyword"},
            "ingested_at": {"type": "date"},
            "search_text": {"type": "text"},
            "entities": {
                "type": "nested",
                "properties": {
                    "name": {"type": "text"},
                    "type": {"type": "keyword"},
                    "nif": {"type": "keyword"},
                    "code": {"type": "keyword"},
                },
            },
        }
    }

    trademarks_mappings = {
        "properties": {
            "nord": {"type": "long"},
            "process_number": {"type": "keyword"},
            "mark_name": {
                "type": "text",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 512}},
            },
            "mark_type": {"type": "keyword"},
            "modality": {"type": "keyword"},
            "holder_name": {
                "type": "text",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 512}},
            },
            "holder_nif": {"type": "keyword"},
            "company_nif": {"type": "keyword"},
            "application_date": {"type": "date", "format": "yyyy-MM-dd"},
            "current_phase": {"type": "keyword"},
            "phase_start_date": {"type": "date", "format": "yyyy-MM-dd"},
            "phase_end_date": {"type": "date", "format": "yyyy-MM-dd"},
            "nice_classes": {"type": "keyword"},
            "entities": {
                "type": "nested",
                "properties": {
                    "name": {"type": "text"},
                    "nif": {"type": "keyword"},
                    "role": {"type": "keyword"},
                },
            },
            "phases": {
                "type": "nested",
                "properties": {
                    "phase": {"type": "text"},
                    "start_date": {"type": "date", "format": "yyyy-MM-dd"},
                    "end_date": {"type": "date", "format": "yyyy-MM-dd"},
                },
            },
            "documents": {
                "type": "nested",
                "properties": {
                    "doc_id": {"type": "keyword"},
                    "type": {"type": "text"},
                    "description": {"type": "text"},
                    "url": {"type": "keyword"},
                },
            },
            "ingested_at": {"type": "date"},
            "source_query": {"type": "keyword"},
            "holder_similarity": {"type": "float"},
        }
    }

    firmas_mappings = {
        "properties": {
            "nome": {
                "type": "text",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 512}},
            },
            "nipc": {"type": "keyword"},
            "company_nif": {"type": "keyword"},
            "numero_certificado": {"type": "keyword"},
            "certificado_admissibilidade": {"type": "keyword"},
            "concelho": {"type": "keyword"},
            "concelho_sede": {"type": "keyword"},
            "situacao": {"type": "keyword"},
            "situacao_detalhe": {"type": "keyword"},
            "cae_principal": {"type": "keyword"},
            "score": {"type": "float"},
            "search_query": {"type": "keyword"},
            "source": {"type": "keyword"},
            "name_similarity": {"type": "float"},
            "ingested_at": {"type": "date"},
        }
    }

    entities_mappings = {
        "properties": {
            "nif": {"type": "keyword"},
            "name": {
                "type": "text",
                "fields": {
                    "keyword": {"type": "keyword", "ignore_above": 512},
                    "autocomplete": {
                        "type": "text",
                        "analyzer": "entity_index_analyzer",
                        "search_analyzer": "entity_search_analyzer",
                    },
                },
            },
            "country": {"type": "keyword"},
            "country_code": {"type": "keyword"},
            "has_nif": {"type": "boolean"},
            "contracts_count": {"type": "integer"},
            "as_adjudicante_count": {"type": "integer"},
            "as_adjudicatario_count": {"type": "integer"},
            "total_value": {"type": "float"},
            "as_adjudicante_value": {"type": "float"},
            "source": {"type": "keyword"},
            "ingested_at": {"type": "date"},
        }
    }

    user_state_mappings = {
        "properties": {
            "kind": {"type": "keyword"},
            "entry_kind": {"type": "keyword"},
            "id": {"type": "keyword"},
            "folder_id": {"type": "keyword"},
            "name": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
            "label": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
            "sublabel": {"type": "keyword"},
            "value": {"type": "float"},
            "parties": {
                "type": "nested",
                "properties": {
                    "nif": {"type": "keyword"},
                    "label": {"type": "text"},
                    "role": {"type": "keyword"},
                },
            },
            "items": {"type": "object", "enabled": False},
            "added_at": {"type": "date"},
            "created_at": {"type": "date"},
            "updated_at": {"type": "date"},
        }
    }

    auth_users_mappings = {
        "properties": {
            "id": {"type": "keyword"},
            "email": {"type": "keyword"},
            "name": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 256}}},
            "initials": {"type": "keyword"},
            "title": {"type": "keyword"},
            "organization": {"type": "keyword"},
            "phone": {"type": "keyword"},
            "role": {"type": "keyword"},
            "status": {"type": "keyword"},
            "locale": {"type": "keyword"},
            "timezone": {"type": "keyword"},
            # O hash nunca é pesquisado: fica como objeto opaco.
            "password": {"type": "object", "enabled": False},
            "preferences": {"type": "object", "enabled": False},
            "created_at": {"type": "date"},
            "updated_at": {"type": "date"},
            "last_login_at": {"type": "date"},
            "login_count": {"type": "integer"},
        }
    }

    auth_sessions_mappings = {
        "properties": {
            "session_id": {"type": "keyword"},
            "user_id": {"type": "keyword"},
            "email": {"type": "keyword"},
            "created_at": {"type": "date"},
            "last_seen_at": {"type": "date"},
            "expires_at": {"type": "date"},
            "revoked": {"type": "boolean"},
            "revoked_at": {"type": "date"},
            "user_agent": {"type": "keyword", "ignore_above": 512},
            "ip": {"type": "keyword"},
        }
    }

    events_mappings = {
        "properties": {
            "timestamp": {"type": "date"},
            "level": {"type": "keyword"},
            "source": {"type": "keyword"},
            "message": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
            "data": {"type": "object", "enabled": False},
            "user_id": {"type": "keyword"},
            "user_email": {"type": "keyword"},
            "method": {"type": "keyword"},
            "path": {"type": "keyword"},
            "status": {"type": "integer"},
            "duration_ms": {"type": "float"},
            "ip": {"type": "keyword"},
            "user_agent": {"type": "keyword", "ignore_above": 512},
            "host": {"type": "keyword"},
            "pid": {"type": "integer"},
        }
    }

    provider_keys_mappings = {
        "properties": {
            "user_id": {"type": "keyword"},
            "keys": {"type": "object", "enabled": False},
            "defaults": {
                "properties": {
                    "provider": {"type": "keyword"},
                    "model": {"type": "keyword"},
                }
            },
            "updated_at": {"type": "date"},
        }
    }

    # CRM: um único índice para os quatro tipos de registo (`kind`), porque as
    # suas propriedades não colidem e assim as pesquisas cruzadas (timeline de
    # uma conta) fazem-se sem consultas a vários índices.
    crm_mappings = {
        "properties": {
            "kind": {"type": "keyword"},
            "id": {"type": "keyword"},
            "owner_id": {"type": "keyword"},
            "owner_email": {"type": "keyword"},
            # --- conta (empresa) ---
            "name": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
            "nif": {"type": "keyword"},
            "sector": {"type": "keyword"},
            "status": {"type": "keyword"},
            "website": {"type": "keyword", "ignore_above": 512},
            "email": {"type": "keyword"},
            "phone": {"type": "keyword"},
            "mobile": {"type": "keyword"},
            "address": {"type": "text"},
            "city": {"type": "keyword"},
            "country": {"type": "keyword"},
            "postal_code": {"type": "keyword"},
            "employees": {"type": "integer"},
            "annual_revenue": {"type": "float"},
            # --- contacto ---
            "account_id": {"type": "keyword"},
            "contact_id": {"type": "keyword"},
            "deal_id": {"type": "keyword"},
            "title": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
            "role": {"type": "keyword"},
            "linkedin": {"type": "keyword", "ignore_above": 512},
            "is_primary": {"type": "boolean"},
            # --- oportunidade ---
            "amount": {"type": "float"},
            "weighted_amount": {"type": "float"},
            "currency": {"type": "keyword"},
            "stage": {"type": "keyword"},
            "probability": {"type": "integer"},
            "expected_close_date": {"type": "date"},
            "closed_at": {"type": "date"},
            "loss_reason": {"type": "keyword"},
            "source": {"type": "keyword"},
            # --- atividade ---
            "type": {"type": "keyword"},
            "subject": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
            "notes": {"type": "text"},
            "due_at": {"type": "date"},
            "done": {"type": "boolean"},
            "done_at": {"type": "date"},
            "priority": {"type": "keyword"},
            # --- comuns ---
            "tags": {"type": "keyword"},
            # Dados externos (ex.: snapshot do EmpresasIQ na conta) ficam opacos.
            "entity": {"type": "object", "enabled": False},
            "created_at": {"type": "date"},
            "updated_at": {"type": "date"},
        }
    }

    for name, mappings in [
        ("finance_prices", prices_mappings),
        ("finance_news", news_mappings),
        ("finance_sentiment_daily", sentiment_mappings),
        ("finance_macro", macro_mappings),
        ("finance_earnings", earnings_mappings),
        (CONTRACTS_INDEX, contracts_mappings),
        (TRADEMARKS_INDEX, trademarks_mappings),
        (FIRMAS_INDEX, firmas_mappings),
        (ENTITIES_INDEX, entities_mappings),
        (USER_STATE_INDEX, user_state_mappings),
        (AUTH_USERS_INDEX, auth_users_mappings),
        (AUTH_SESSIONS_INDEX, auth_sessions_mappings),
        (EVENTS_INDEX, events_mappings),
        (PROVIDER_KEYS_INDEX, provider_keys_mappings),
        (CRM_INDEX, crm_mappings),
    ]:
        if not client.indices.exists(index=name):
            settings: Dict[str, Any] = {"number_of_shards": 1, "number_of_replicas": 0}
            settings.update(INDEX_SETTINGS.get(name, {}))
            client.indices.create(index=name, body={"mappings": mappings, "settings": settings})
        else:
            # Elasticsearch permite acrescentar campos novos a um índice existente
            # (não permite alterar/remover os já definidos). Enviamos apenas os campos
            # em falta, para manter índices antigos compatíveis com o código atual.
            try:
                existing = client.indices.get_mapping(index=name)[name]["mappings"].get("properties", {})
                missing = {
                    field: spec
                    for field, spec in (mappings.get("properties") or {}).items()
                    if field not in existing
                }
                if missing:
                    client.indices.put_mapping(index=name, body={"properties": missing})
            except Exception as exc:
                logger.debug("put_mapping ignorado para %s: %s", name, exc)
    return True


def _today() -> str:
    return datetime.utcnow().isoformat()


def index_price_points(ticker: str, points: List[Dict[str, Any]], period: str = "1y", es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Indexa pontos de preço no Elasticsearch.

    Args:
        ticker: símbolo normalizado do ticker.
        points: lista de dicts com date, open, high, low, close, volume.
        period: período de onde os dados vieram.
        es: cliente Elasticsearch opcional.

    Returns:
        dict com ticker, indexed_count, total_points.
    """
    client = es or get_es_client()
    if not client:
        return {"ticker": ticker, "error": "Elasticsearch indisponível", "indexed_count": 0}

    ensure_indices(client)
    ticker = ticker.upper()
    actions = []
    for p in points:
        doc = {
            "_op_type": "index",
            "_index": "finance_prices",
            "_id": f"{ticker}-{p.get('date')}",
            "ticker": ticker,
            "date": p.get("date"),
            "open": _as_float(p.get("open")),
            "high": _as_float(p.get("high")),
            "low": _as_float(p.get("low")),
            "close": _as_float(p.get("close")),
            "volume": _as_int(p.get("volume")),
            "period": period,
            "ingested_at": _today(),
        }
        actions.append(doc)

    if not actions:
        return {"ticker": ticker, "indexed_count": 0, "total_points": 0}

    try:
        success, errors = bulk(client, actions, raise_on_error=False, refresh=True)
        return {"ticker": ticker, "indexed_count": success, "total_points": len(actions), "errors": len(errors)}
    except Exception as e:
        return {"ticker": ticker, "error": str(e), "indexed_count": 0, "total_points": len(actions)}


def index_news_items(ticker: str, items: List[Dict[str, Any]], es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Indexa notícias no Elasticsearch.

    Args:
        ticker: símbolo normalizado do ticker.
        items: lista de notícias com title, summary, publisher, published, url.
        es: cliente Elasticsearch opcional.

    Returns:
        dict com ticker, indexed_count, total_items.
    """
    client = es or get_es_client()
    if not client:
        return {"ticker": ticker, "error": "Elasticsearch indisponível", "indexed_count": 0}

    ensure_indices(client)
    ticker = ticker.upper()
    actions = []
    for i, item in enumerate(items):
        published = item.get("published") or item.get("pubDate")
        if published and isinstance(published, datetime):
            published = published.isoformat()
        doc_id = f"{ticker}-{_news_id(item, i)}"
        doc = {
            "_op_type": "index",
            "_index": "finance_news",
            "_id": doc_id,
            "ticker": ticker,
            "title": item.get("title") or item.get("summary"),
            "summary": item.get("summary") or item.get("title"),
            "publisher": item.get("publisher") or item.get("provider"),
            "published": published,
            "url": item.get("url") or item.get("link"),
            "source": item.get("source", "yfinance"),
            "ingested_at": _today(),
        }
        actions.append(doc)

    if not actions:
        return {"ticker": ticker, "indexed_count": 0, "total_items": 0}

    try:
        success, errors = bulk(client, actions, raise_on_error=False, refresh=True)
        return {"ticker": ticker, "indexed_count": success, "total_items": len(actions), "errors": len(errors)}
    except Exception as e:
        return {"ticker": ticker, "error": str(e), "indexed_count": 0, "total_items": len(actions)}


def _news_id(item: Dict[str, Any], index: int) -> str:
    """Gera ID estável para uma notícia baseada no URL ou no conteúdo."""
    import hashlib
    url = item.get("url") or item.get("link") or ""
    if url:
        return hashlib.md5(url.encode("utf-8")).hexdigest()[:20]
    content = (item.get("title") or "") + (item.get("summary") or "") + str(index)
    return hashlib.md5(content.encode("utf-8")).hexdigest()[:20]


def search_prices(
    ticker: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    size: int = 1000,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Pesquisa preços de um ticker por intervalo de datas."""
    client = es or get_es_client()
    if not client:
        return {"ticker": ticker, "error": "Elasticsearch indisponível", "points": []}

    query: Dict[str, Any] = {"bool": {"must": [{"term": {"ticker": ticker.upper()}}]}}
    range_filter = {}
    if start_date:
        range_filter["gte"] = start_date
    if end_date:
        range_filter["lte"] = end_date
    if range_filter:
        query["bool"]["filter"] = [{"range": {"date": range_filter}}]

    try:
        resp = client.search(
            index="finance_prices",
            body={
                "query": query,
                "sort": [{"date": {"order": "asc"}}],
                "size": size,
            },
        )
        points = [hit["_source"] for hit in resp["hits"]["hits"]]
        return {
            "ticker": ticker.upper(),
            "total": resp["hits"]["total"]["value"],
            "points": points,
            "start_date": start_date,
            "end_date": end_date,
        }
    except Exception as e:
        return {"ticker": ticker.upper(), "error": str(e), "points": []}


def search_news(
    ticker: str,
    q: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    size: int = 50,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Pesquisa notícias por ticker e texto opcional."""
    client = es or get_es_client()
    if not client:
        return {"ticker": ticker, "error": "Elasticsearch indisponível", "items": []}

    must: List[Dict[str, Any]] = [{"term": {"ticker": ticker.upper()}}]
    if q:
        must.append({
            "multi_match": {
                "query": q,
                "fields": ["title^2", "summary", "publisher"],
                "type": "best_fields",
            }
        })

    query: Dict[str, Any] = {"bool": {"must": must}}
    range_filter = {}
    if start_date:
        range_filter["gte"] = start_date
    if end_date:
        range_filter["lte"] = end_date
    if range_filter:
        query["bool"]["filter"] = [{"range": {"published": range_filter}}]

    try:
        resp = client.search(
            index="finance_news",
            body={
                "query": query,
                "sort": [{"published": {"order": "desc"}}, "_score"],
                "size": size,
            },
        )
        items = [hit["_source"] for hit in resp["hits"]["hits"]]
        return {
            "ticker": ticker.upper(),
            "total": resp["hits"]["total"]["value"],
            "items": items,
        }
    except Exception as e:
        return {"ticker": ticker.upper(), "error": str(e), "items": []}


def index_analyzed_news_items(
    ticker: str,
    items: List[Dict[str, Any]],
    analyses: List[Any],
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Indexa notícias enriquecidas com análise NLP no Elasticsearch."""
    client = es or get_es_client()
    if not client:
        return {"ticker": ticker, "error": "Elasticsearch indisponível", "indexed_count": 0}

    ensure_indices(client)
    ticker = ticker.upper()
    actions = []
    now = _today()
    for i, (item, analysis) in enumerate(zip(items, analyses)):
        published = item.get("published") or item.get("pubDate")
        if published and isinstance(published, datetime):
            published = published.isoformat()
        doc_id = f"{ticker}-{_news_id(item, i)}"
        doc = {
            "_op_type": "index",
            "_index": "finance_news",
            "_id": doc_id,
            "ticker": ticker,
            "title": item.get("title") or item.get("summary"),
            "summary": item.get("summary") or item.get("title"),
            "publisher": item.get("publisher") or item.get("provider"),
            "published": published,
            "url": item.get("url") or item.get("link"),
            "source": item.get("source", "yfinance"),
            "ingested_at": now,
            "analyzed_at": now,
            "sentiment": analysis.sentiment,
            "language": analysis.language,
            "translated_title": analysis.translated_title,
            "translated_summary": analysis.translated_summary,
            "summary_pt": analysis.summary_pt,
            "topics": analysis.topics,
            "entities": analysis.entities,
        }
        actions.append(doc)

    if not actions:
        return {"ticker": ticker, "indexed_count": 0, "total_items": 0}

    try:
        success, errors = bulk(client, actions, raise_on_error=False, refresh=True)
        return {"ticker": ticker, "indexed_count": success, "total_items": len(actions), "errors": len(errors)}
    except Exception as e:
        return {"ticker": ticker, "error": str(e), "indexed_count": 0, "total_items": len(actions)}


def fetch_news_for_analysis(
    ticker: str,
    q: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    size: int = 100,
    es: Optional[Elasticsearch] = None,
) -> List[Dict[str, Any]]:
    """Recupera notícias indexadas para serem (re)analisadas."""
    result = search_news(ticker, q, start_date, end_date, size, es)
    return result.get("items", [])


def save_news_graph(
    ticker: str,
    graph: Dict[str, Any],
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Persiste grafo de notícias/entidades num índice dedicado."""
    client = es or get_es_client()
    if not client:
        return {"ticker": ticker, "error": "Elasticsearch indisponível"}

    graph_mappings = {
        "properties": {
            "ticker": {"type": "keyword"},
            "graph_type": {"type": "keyword"},
            "nodes": {"type": "object"},
            "edges": {"type": "object"},
            "created_at": {"type": "date"},
        }
    }
    if not client.indices.exists(index="finance_graphs"):
        client.indices.create(
            index="finance_graphs",
            body={"mappings": graph_mappings, "settings": {"number_of_shards": 1, "number_of_replicas": 0}},
        )

    try:
        client.index(
            index="finance_graphs",
            id=f"{ticker.upper()}-news",
            body={
                "ticker": ticker.upper(),
                "graph_type": "news_entities",
                "nodes": graph.get("nodes", []),
                "edges": graph.get("edges", []),
                "created_at": _today(),
            },
        )
        return {"ticker": ticker.upper(), "saved": True, "node_count": len(graph.get("nodes", [])), "edge_count": len(graph.get("edges", []))}
    except Exception as e:
        return {"ticker": ticker.upper(), "error": str(e)}


def load_news_graph(ticker: str, es: Optional[Elasticsearch] = None) -> Optional[Dict[str, Any]]:
    """Carrega grafo de notícias/entidades persistido."""
    client = es or get_es_client()
    if not client:
        return None
    try:
        resp = client.get(index="finance_graphs", id=f"{ticker.upper()}-news")
        return resp.get("_source")
    except Exception:
        return None


def search_all_tickers(
    q: str,
    from_: int = 0,
    size: int = 50,
    source: Optional[str] = None,
    sentiment: Optional[str] = None,
    topic: Optional[str] = None,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Pesquisa notícias de todos os tickers por texto, com filtros e paginação."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "items": []}

    must = {
        "multi_match": {
            "query": q,
            "fields": ["ticker^3", "title^2", "summary", "publisher"],
            "type": "best_fields",
        }
    }
    filters = []
    if source:
        filters.append({"wildcard": {"publisher": f"*{source.lower()}*"}})
    if sentiment:
        filters.append({"term": {"sentiment": sentiment.lower()}})
    if topic:
        filters.append({"wildcard": {"topics": f"*{topic.lower()}*"}})

    query: Dict[str, Any] = {"bool": {"must": [must], "filter": filters}}

    try:
        resp = client.search(
            index="finance_news",
            body={
                "query": query,
                "sort": [{"published": {"order": "desc"}}, "_score"],
                "from": from_,
                "size": size,
                "track_scores": True,
                "track_total_hits": True,
            },
        )
        items = []
        for hit in resp["hits"]["hits"]:
            source = hit["_source"]
            source["score"] = hit.get("_score")
            items.append(source)
        return {"total": resp["hits"]["total"]["value"], "items": items}
    except Exception as e:
        return {"error": str(e), "items": []}


def autocomplete_suggestions(q: str, size: int = 12, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Gera sugestões de autocomplete a partir de tickers, títulos, publishers e tópicos indexados."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "suggestions": []}

    q = q.strip()
    if not q:
        return {"suggestions": []}

    lower_q = q.lower()
    upper_q = q.upper()

    try:
        resp = client.search(
            index="finance_news",
            body={
                "size": 0,
                "query": {
                    "bool": {
                        "should": [
                            {"wildcard": {"ticker": f"{upper_q}*"}},
                            {"match_phrase_prefix": {"title": q}},
                            {"wildcard": {"publisher": f"*{lower_q}*"}},
                            {"wildcard": {"topics": f"*{lower_q}*"}},
                        ],
                        "minimum_should_match": 1,
                    }
                },
                "aggs": {
                    "tickers": {
                        "terms": {
                            "field": "ticker",
                            "size": 5,
                            "include": f"{upper_q}.*",
                            "order": {"_count": "desc"},
                        }
                    },
                    "publishers": {
                        "terms": {
                            "field": "publisher",
                            "size": 5,
                            "include": f".*{lower_q}.*",
                            "order": {"_count": "desc"},
                        }
                    },
                    "topics": {
                        "terms": {
                            "field": "topics",
                            "size": 5,
                            "include": f".*{lower_q}.*",
                            "order": {"_count": "desc"},
                        }
                    },
                    "title_hits": {
                        "terms": {
                            "field": "title.keyword",
                            "size": 5,
                            "include": f".*{lower_q}.*",
                            "order": {"_count": "desc"},
                        }
                    },
                },
            },
        )

        suggestions = []
        seen = set()

        for bucket in resp["aggregations"]["tickers"]["buckets"]:
            text = bucket["key"]
            if text not in seen:
                seen.add(text)
                suggestions.append({"text": text, "type": "ticker", "count": bucket["doc_count"]})

        for bucket in resp["aggregations"]["publishers"]["buckets"]:
            text = bucket["key"]
            if text and text not in seen:
                seen.add(text)
                suggestions.append({"text": text, "type": "publisher", "count": bucket["doc_count"]})

        for bucket in resp["aggregations"]["topics"]["buckets"]:
            text = bucket["key"]
            if text and text not in seen:
                seen.add(text)
                suggestions.append({"text": text, "type": "topic", "count": bucket["doc_count"]})

        for bucket in resp["aggregations"]["title_hits"]["buckets"]:
            text = bucket["key"]
            if text and text not in seen:
                seen.add(text)
                suggestions.append({"text": text, "type": "title", "count": bucket["doc_count"]})

        suggestions = suggestions[:size]
        return {"suggestions": suggestions}
    except Exception as e:
        return {"error": str(e), "suggestions": []}


def delete_ticker_data(ticker: str, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Apaga todos os dados de preços e notícias de um ticker."""
    client = es or get_es_client()
    if not client:
        return {"ticker": ticker, "error": "Elasticsearch indisponível"}

    ticker = ticker.upper()
    try:
        prices_resp = client.delete_by_query(
            index="finance_prices",
            body={"query": {"term": {"ticker": ticker}}},
        )
        news_resp = client.delete_by_query(
            index="finance_news",
            body={"query": {"term": {"ticker": ticker}}},
        )
        return {
            "ticker": ticker,
            "prices_deleted": prices_resp.get("deleted", 0),
            "news_deleted": news_resp.get("deleted", 0),
        }
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}


def list_indexed_tickers(es: Optional[Elasticsearch] = None) -> List[str]:
    """Devolve a lista de tickers que já têm dados indexados."""
    client = es or get_es_client()
    if not client:
        return []

    try:
        resp = client.search(
            index="finance_prices",
            body={
                "size": 0,
                "aggs": {"tickers": {"terms": {"field": "ticker", "size": 1000}}},
            },
        )
        return [bucket["key"] for bucket in resp["aggregations"]["tickers"]["buckets"]]
    except Exception:
        return []


def _as_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _as_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return None


# --- Contratos públicos ---

def index_contracts(
    docs: List[Dict[str, Any]],
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Indexa documentos de contratos no índice finance_contracts."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "indexed_count": 0}

    ensure_indices(client)
    actions = []
    for doc in docs:
        doc_id = str(doc.get("idcontrato") or doc.get("idprocedimento"))
        actions.append({
            "_op_type": "index",
            "_index": CONTRACTS_INDEX,
            "_id": doc_id,
            **doc,
        })

    if not actions:
        return {"indexed_count": 0, "total": 0}

    try:
        success, errors = bulk(client, actions, raise_on_error=False, refresh=True)
        return {"indexed_count": success, "total": len(actions), "errors": len(errors)}
    except Exception as e:
        return {"error": str(e), "indexed_count": 0, "total": len(actions)}


def bulk_index_contracts_from_jsonl(
    jsonl_path: Path,
    chunk_size: int = 1000,
    max_records: Optional[int] = None,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Indexa um ficheiro JSONL de contratos em chunks."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "indexed_count": 0}

    ensure_indices(client)
    total = 0
    success_total = 0
    error_total = 0
    chunk: List[Dict[str, Any]] = []

    try:
        resolved_path = Path(jsonl_path) if not isinstance(jsonl_path, Path) else jsonl_path
        print(f"[bulk_index_contracts] path={resolved_path} exists={resolved_path.exists()} chunk_size={chunk_size} max_records={max_records}")
        with open(resolved_path, "r", encoding="utf-8") as fh:
            for line in fh:
                if max_records and total >= max_records:
                    print(f"[bulk_index_contracts] max_records reached {total}")
                    break
                try:
                    doc = json.loads(line)
                except Exception:
                    continue
                chunk.append(doc)
                total += 1
                if len(chunk) >= chunk_size:
                    res = index_contracts(chunk, client)
                    print(f"[bulk_index_contracts] chunk indexed={res.get('indexed_count')} errors={res.get('errors')} error={res.get('error')}")
                    success_total += res.get("indexed_count", 0)
                    error_total += res.get("errors", 0) or (0 if not res.get("error") else len(chunk))
                    chunk = []
        if chunk:
            res = index_contracts(chunk, client)
            print(f"[bulk_index_contracts] final chunk indexed={res.get('indexed_count')} errors={res.get('errors')} error={res.get('error')}")
            success_total += res.get("indexed_count", 0)
            error_total += res.get("errors", 0) or (0 if not res.get("error") else len(chunk))
        print(f"[bulk_index_contracts] done total={total} success={success_total} errors={error_total}")
        return {"indexed_count": success_total, "total": total, "errors": error_total}
    except Exception as e:
        print(f"[bulk_index_contracts] exception {e}")
        return {"error": str(e), "indexed_count": success_total, "total": total}


def find_contract_ids_by_idcontrato(
    idcontratos: Iterable[str],
    es: Optional[Elasticsearch] = None,
) -> List[str]:
    """Devolve os _id de documentos existentes no índice finance_contracts cujo idcontrato corresponde aos valores fornecidos."""
    client = es or get_es_client()
    if not client or not idcontratos:
        return []

    ids = [str(v).strip() for v in idcontratos if v is not None and str(v).strip()]
    if not ids:
        return []

    existing: set = set()
    batch_size = 1000
    try:
        for i in range(0, len(ids), batch_size):
            batch = ids[i : i + batch_size]
            resp = client.search(
                index=CONTRACTS_INDEX,
                body={
                    "query": {"terms": {"idcontrato": batch}},
                    "_source": False,
                    "size": len(batch),
                },
            )
            for hit in resp.get("hits", {}).get("hits", []):
                existing.add(hit.get("_id"))
    except Exception as e:
        print(f"[find_contract_ids_by_idcontrato] error: {e}")
        return []
    return sorted(existing)


def delete_contracts_by_ids(
    doc_ids: Iterable[str],
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Apaga documentos do índice finance_contracts pelos respetivos _id."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "deleted_count": 0}

    ids = [str(v).strip() for v in doc_ids if v is not None and str(v).strip()]
    if not ids:
        return {"deleted_count": 0, "total": 0}

    try:
        resp = client.delete_by_query(
            index=CONTRACTS_INDEX,
            body={"query": {"terms": {"_id": ids}}},
            refresh=True,
        )
        return {"deleted_count": resp.get("deleted", 0), "total": len(ids)}
    except Exception as e:
        return {"error": str(e), "deleted_count": 0, "total": len(ids)}


def _contract_to_flat_dict(source: Dict[str, Any]) -> Dict[str, Any]:
    """Converte documento de contrato num dicionário plano para exportação."""
    def party_str(parties: Any) -> str:
        if not parties:
            return ""
        if isinstance(parties, dict):
            parties = [parties]
        names = []
        for p in parties:
            parsed = p.get("parsed") if isinstance(p, dict) else None
            if isinstance(parsed, list):
                names.extend([x.get("nome", "") for x in parsed if x.get("nome")])
            raw = p.get("raw") if isinstance(p, dict) else None
            if isinstance(raw, list):
                names.extend([str(r) for r in raw])
            elif isinstance(raw, str):
                names.append(raw)
        return "; ".join(names)

    def nif_str(parties: Any) -> str:
        if not parties:
            return ""
        if isinstance(parties, dict):
            parties = [parties]
        nifs = []
        for p in parties:
            parsed = p.get("parsed") if isinstance(p, dict) else None
            if isinstance(parsed, list):
                nifs.extend([x.get("nif", "") for x in parsed if x.get("nif")])
        return "; ".join(nifs)

    def cpv_str(cpv: Any) -> str:
        if not cpv:
            return ""
        if isinstance(cpv, dict):
            cpv = [cpv]
        return "; ".join([f"{x.get('code','')} {x.get('description','')}".strip() for x in cpv])

    return {
        "idcontrato": source.get("idcontrato"),
        "nAnuncio": source.get("nAnuncio"),
        "tipoContrato": source.get("tipoContrato"),
        "tipoprocedimento": source.get("tipoprocedimento"),
        "objectoContrato": source.get("objectoContrato"),
        "descContrato": source.get("descContrato"),
        "adjudicante": party_str(source.get("adjudicantes")),
        "nif_adjudicante": nif_str(source.get("adjudicantes")),
        "adjudicatario": party_str(source.get("adjudicatarios")),
        "nif_adjudicatario": nif_str(source.get("adjudicatarios")),
        "dataPublicacao": source.get("dataPublicacao"),
        "dataCelebracaoContrato": source.get("dataCelebracaoContrato"),
        "precoContratual": source.get("precoContratual"),
        "PrecoTotalEfetivo": source.get("PrecoTotalEfetivo"),
        "precoBaseProcedimento": source.get("precoBaseProcedimento"),
        "cpv": cpv_str(source.get("cpv")),
        "localExecucao": source.get("localExecucao"),
        "Ano": source.get("Ano"),
        "NUTs": source.get("NUTs"),
        "regime": source.get("regime"),
    }


def export_contracts_to_excel(
    q: Optional[str] = None,
    year: Optional[int] = None,
    entity: Optional[str] = None,
    nif: Optional[str] = None,
    cpv_code: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    max_records: int = 10000,
    es: Optional[Elasticsearch] = None,
) -> bytes:
    """Exporta contratos filtrados para Excel (bytes)."""
    try:
        import openpyxl
        from openpyxl.styles import Font
    except ImportError as e:
        raise RuntimeError("openpyxl não instalado") from e

    client = es or get_es_client()
    if not client:
        raise RuntimeError("Elasticsearch indisponível")

    query = _build_contract_query(q, year, entity, nif, cpv_code, min_price, max_price, start_date, end_date)
    resp = client.search(
        index=CONTRACTS_INDEX,
        body={
            "query": query,
            "sort": [{"dataPublicacao": {"order": "desc"}}, "_score"],
            "size": min(max_records, 10000),
            "track_scores": False,
        },
    )

    rows = [_contract_to_flat_dict(hit["_source"]) for hit in resp["hits"]["hits"]]
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Contratos"
    headers = list(rows[0].keys()) if rows else [
        "idcontrato", "nAnuncio", "tipoContrato", "tipoprocedimento", "objectoContrato",
        "descContrato", "adjudicante", "nif_adjudicante", "adjudicatario", "nif_adjudicatario",
        "dataPublicacao", "dataCelebracaoContrato", "precoContratual", "PrecoTotalEfetivo",
        "precoBaseProcedimento", "cpv", "localExecucao", "Ano", "NUTs", "regime",
    ]
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    def value_to_excel(v: Any) -> Any:
        if isinstance(v, (list, dict)):
            return json.dumps(v, ensure_ascii=False)
        return v

    for row in rows:
        ws.append([value_to_excel(row.get(h)) for h in headers])
    for column in ws.columns:
        max_length = 0
        column_letter = column[0].column_letter
        for cell in column:
            try:
                val_len = len(str(cell.value))
                if val_len > max_length:
                    max_length = val_length
            except Exception:
                pass
        ws.column_dimensions[column_letter].width = min(max_length + 2, 60)

    from io import BytesIO
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.read()


def export_contracts_to_pdf(
    q: Optional[str] = None,
    year: Optional[int] = None,
    entity: Optional[str] = None,
    nif: Optional[str] = None,
    cpv_code: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    max_records: int = 500,
    es: Optional[Elasticsearch] = None,
) -> bytes:
    """Exporta contratos filtrados para PDF (bytes)."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet
    except ImportError as e:
        raise RuntimeError("reportlab não instalado") from e

    client = es or get_es_client()
    if not client:
        raise RuntimeError("Elasticsearch indisponível")

    query = _build_contract_query(q, year, entity, nif, cpv_code, min_price, max_price, start_date, end_date)
    resp = client.search(
        index=CONTRACTS_INDEX,
        body={
            "query": query,
            "sort": [{"dataPublicacao": {"order": "desc"}}, "_score"],
            "size": min(max_records, 1000),
            "track_scores": False,
        },
    )

    rows = [_contract_to_flat_dict(hit["_source"]) for hit in resp["hits"]["hits"]]
    headers = ["ID", "Ano", "Tipo", "Objecto", "Adjudicante", "Adjudicatário", "Valor", "Publicação"]
    data = [headers]
    for r in rows:
        data.append([
            str(r.get("idcontrato") or ""),
            str(r.get("Ano") or ""),
            str(r.get("tipoContrato") or ""),
            str(r.get("objectoContrato") or "")[:80],
            str(r.get("adjudicante") or "")[:50],
            str(r.get("adjudicatario") or "")[:50],
            f"{r.get('precoContratual') or 0:.2f} €",
            str(r.get("dataPublicacao") or ""),
        ])

    from io import BytesIO
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), rightMargin=20, leftMargin=20, topMargin=20, bottomMargin=20)
    elements = []
    styles = getSampleStyleSheet()
    elements.append(Paragraph("Relatório de Contratos Públicos", styles["Title"]))
    elements.append(Paragraph(f"Total exportado: {len(rows)} contratos", styles["Normal"]))
    elements.append(Spacer(1, 12))
    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#10a37f")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
        ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#f8f9fa")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("WORDWRAP", (0, 0), (-1, -1), True),
    ]))
    elements.append(table)
    doc.build(elements)
    buf.seek(0)
    return buf.read()


def search_contracts(
    q: Optional[str] = None,
    year: Optional[int] = None,
    entity: Optional[str] = None,
    nif: Optional[str] = None,
    counterparty_nif: Optional[str] = None,
    region: Optional[str] = None,
    cpv_code: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    size: int = 20,
    from_: int = 0,
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = None,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Pesquisa contratos por texto, entidades, datas e valores."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "items": []}

    query = _build_contract_query(q, year, entity, nif, counterparty_nif, region, cpv_code, min_price, max_price, start_date, end_date)
    sort = _build_contract_sort(sort_by, sort_order)

    try:
        resp = client.search(
            index=CONTRACTS_INDEX,
            body={
                "query": query,
                "sort": sort,
                "from": from_,
                "size": size,
                "track_scores": True,
                "track_total_hits": True,
            },
        )
        items = []
        for hit in resp["hits"]["hits"]:
            source = hit["_source"]
            source["score"] = hit.get("_score")
            source["doc_id"] = hit.get("_id")
            items.append(source)
        return {
            "query": q,
            "total": resp["hits"]["total"]["value"],
            "items": items,
            "from": from_,
            "size": size,
        }
    except Exception as e:
        return {"error": str(e), "items": []}


def _build_contract_sort(
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = None,
) -> List[Dict[str, Any]]:
    order = sort_order if sort_order in ("asc", "desc") else "desc"
    field = sort_by or "dataPublicacao"
    if field == "relevance":
        return ["_score"]
    if field == "adjudicantes":
        return [{"adjudicantes.parsed.nome.keyword": {"order": order, "nested": {"path": "adjudicantes.parsed"}}}, "_score"]
    if field == "adjudicatarios":
        return [{"adjudicatarios.parsed.nome.keyword": {"order": order, "nested": {"path": "adjudicatarios.parsed"}}}, "_score"]
    if field == "tipoContrato":
        return [{"tipoContrato.keyword": {"order": order}}, "_score"]
    if field == "objectoContrato":
        return [{"objectoContrato.keyword": {"order": order}}, "_score"]
    if field in ("dataPublicacao", "dataCelebracaoContrato"):
        return [{field: {"order": order, "missing": "_last", "unmapped_type": "date"}}, "_score"]
    if field == "precoContratual":
        return [{field: {"order": order, "missing": "_last", "unmapped_type": "float"}}, "_score"]
    return [{"dataPublicacao": {"order": "desc"}}, "_score"]


def contracts_autocomplete(
    q: str,
    size: int = 12,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Sugestões de autocomplete para entidades e CPV."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "suggestions": []}

    q = q.strip()
    if not q:
        return {"suggestions": []}

    lower_q = q.lower()

    try:
        resp = client.search(
            index=CONTRACTS_INDEX,
            body={
                "size": 0,
                "query": {
                    "bool": {
                        "should": [
                            {"match_phrase_prefix": {"objectoContrato": q}},
                            {"match_phrase_prefix": {"descContrato": q}},
                            {
                                "bool": {
                                    "should": [
                                        {
                                            "nested": {
                                                "path": "adjudicantes.parsed",
                                                "query": {"match_phrase_prefix": {"adjudicantes.parsed.nome": q}},
                                            }
                                        },
                                        {
                                            "nested": {
                                                "path": "adjudicatarios.parsed",
                                                "query": {"match_phrase_prefix": {"adjudicatarios.parsed.nome": q}},
                                            }
                                        },
                                    ],
                                    "minimum_should_match": 1,
                                }
                            },
                        ],
                        "minimum_should_match": 1,
                    }
                },
                "aggs": {
                    "adjudicantes": {
                        "nested": {"path": "adjudicantes.parsed"},
                        "aggs": {
                            "names": {
                                "terms": {
                                    "field": "adjudicantes.parsed.nome.keyword",
                                    "size": size,
                                    "include": f".*{lower_q}.*",
                                    "order": {"_count": "desc"},
                                }
                            }
                        }
                    },
                    "adjudicatarios": {
                        "nested": {"path": "adjudicatarios.parsed"},
                        "aggs": {
                            "names": {
                                "terms": {
                                    "field": "adjudicatarios.parsed.nome.keyword",
                                    "size": size,
                                    "include": f".*{lower_q}.*",
                                    "order": {"_count": "desc"},
                                }
                            }
                        }
                    },
                    "cpv_codes": {
                        "nested": {"path": "cpv"},
                        "aggs": {
                            "codes": {
                                "terms": {
                                    "field": "cpv.code",
                                    "size": 5,
                                    "include": f"{lower_q}.*",
                                    "order": {"_count": "desc"},
                                }
                            }
                        }
                    },
                },
            },
        )

        suggestions = []
        seen = set()
        for agg_key in ("adjudicantes", "adjudicatarios"):
            for bucket in resp["aggregations"][agg_key]["names"]["buckets"]:
                text = bucket["key"]
                if text and text not in seen:
                    seen.add(text)
                    suggestions.append({"text": text, "type": "entity", "count": bucket["doc_count"]})
        for bucket in resp["aggregations"]["cpv_codes"]["codes"]["buckets"]:
            text = bucket["key"]
            if text and text not in seen:
                seen.add(text)
                suggestions.append({"text": text, "type": "cpv", "count": bucket["doc_count"]})

        return {"suggestions": suggestions[:size]}
    except Exception as e:
        return {"error": str(e), "suggestions": []}


def contracts_status(es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Devolve contagem total de contratos indexados e anos conhecidos."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "total": 0, "years": []}

    ensure_indices(client)
    try:
        total = client.count(index=CONTRACTS_INDEX).get("count", 0)
        resp = client.search(
            index=CONTRACTS_INDEX,
            body={
                "size": 0,
                "aggs": {"years": {"terms": {"field": "Ano", "size": 50, "order": {"_key": "desc"}}}},
            },
        )
        years = [int(bucket["key"]) for bucket in resp["aggregations"]["years"]["buckets"]]
        return {"total": total, "years": years}
    except Exception as e:
        return {"error": str(e), "total": 0, "years": []}


def contract_years_available() -> List[int]:
    """Anos de contratos com JSONL normalizado disponível."""
    years = []
    if not (ROOT / "data" / "processed" / "contratos").exists():
        return years
    for path in sorted((ROOT / "data" / "processed" / "contratos").glob("contratos_*.jsonl")):
        m = re.search(r"(\d{4})", path.stem)
        if m:
            years.append(int(m.group(1)))
    return sorted(years)


def _build_contract_query(
    q: Optional[str] = None,
    year: Optional[int] = None,
    entity: Optional[str] = None,
    nif: Optional[str] = None,
    counterparty_nif: Optional[str] = None,
    region: Optional[str] = None,
    cpv_code: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> Dict[str, Any]:
    must: List[Dict[str, Any]] = []
    filters: List[Dict[str, Any]] = []

    if q:
        must.append({
            "multi_match": {
                "query": q,
                "fields": [
                    "objectoContrato^3",
                    "descContrato^2",
                    "search_text",
                    "adjudicantes.parsed.nome",
                    "adjudicatarios.parsed.nome",
                    "cpv.description",
                    "localExecucao",
                ],
                "type": "best_fields",
            }
        })

    if year:
        filters.append({"term": {"Ano": year}})
    if entity:
        filters.append({
            "bool": {
                "should": [
                    {
                        "nested": {
                            "path": "adjudicantes.parsed",
                            "query": {"match": {"adjudicantes.parsed.nome": entity}},
                        }
                    },
                    {
                        "nested": {
                            "path": "adjudicatarios.parsed",
                            "query": {"match": {"adjudicatarios.parsed.nome": entity}},
                        }
                    },
                ],
                "minimum_should_match": 1,
            }
        })
    if nif and not counterparty_nif:
        filters.append({
            "bool": {
                "should": [
                    {
                        "nested": {
                            "path": "adjudicantes.parsed",
                            "query": {"term": {"adjudicantes.parsed.nif": nif}},
                        }
                    },
                    {
                        "nested": {
                            "path": "adjudicatarios.parsed",
                            "query": {"term": {"adjudicatarios.parsed.nif": nif}},
                        }
                    },
                ],
                "minimum_should_match": 1,
            }
        })
    elif nif and counterparty_nif:
        filters.append({
            "bool": {
                "must": [
                    {
                        "nested": {
                            "path": "adjudicantes.parsed",
                            "query": {"term": {"adjudicantes.parsed.nif": nif}},
                        }
                    },
                    {
                        "nested": {
                            "path": "adjudicatarios.parsed",
                            "query": {"term": {"adjudicatarios.parsed.nif": counterparty_nif}},
                        }
                    },
                ]
            }
        })
    if region:
        filters.append(_region_filter(region))
    if cpv_code:
        filters.append({
            "nested": {
                "path": "cpv",
                "query": {"wildcard": {"cpv.code": f"{cpv_code}*"}},
            }
        })

    price_range = {}
    if min_price is not None:
        price_range["gte"] = min_price
    if max_price is not None:
        price_range["lte"] = max_price
    if price_range:
        filters.append({
            "bool": {
                "should": [
                    {"range": {"precoContratual": price_range}},
                    {"range": {"PrecoTotalEfetivo": price_range}},
                ],
                "minimum_should_match": 1,
            }
        })

    date_range = {}
    if start_date:
        date_range["gte"] = start_date
    if end_date:
        date_range["lte"] = end_date
    if date_range:
        filters.append({
            "bool": {
                "should": [
                    {"range": {"dataPublicacao": date_range}},
                    {"range": {"dataCelebracaoContrato": date_range}},
                ],
                "minimum_should_match": 1,
            }
        })

    if not must and not filters:
        return {"match_all": {}}

    query: Dict[str, Any] = {"bool": {}}
    if must:
        query["bool"]["must"] = must
    if filters:
        query["bool"]["filter"] = filters
    return query


_AGG_FIELD_CACHE: Dict[str, Dict[str, Any]] = {}


def _resolve_agg_target(client: Elasticsearch, field: str) -> Dict[str, Any]:
    """Descobre como agregar um campo textual: campo direto, subcampo `.keyword` ou campo de execução.

    O mapeamento real do índice manda: alguns campos declarados como `text` acabam
    indexados como `keyword` (e vice-versa), pelo que agregar `campo.keyword` às cegas
    produzia agregações vazias ("N/A" em todos os contratos).
    """
    cached = _AGG_FIELD_CACHE.get(field)
    if cached:
        return cached

    spec: Dict[str, Any] = {}
    try:
        mapping = client.indices.get_mapping(index=CONTRACTS_INDEX)
        props = list(mapping.values())[0].get("mappings", {}).get("properties", {})
        spec = props.get(field) or {}
    except Exception:
        spec = {}

    if spec.get("type") == "keyword":
        resolved = {"field": field, "runtime": None}
    elif (spec.get("fields") or {}).get("keyword"):
        resolved = {"field": f"{field}.keyword", "runtime": None}
    else:
        runtime_name = f"{field}_kw"
        resolved = {
            "field": runtime_name,
            "runtime": {
                runtime_name: {
                    "type": "keyword",
                    "script": {
                        "source": (
                            "def v = params._source == null ? null : params._source.get('"
                            + field
                            + "'); if (v == null) { return; }"
                            " if (v instanceof List) { for (def item : v) { if (item != null) { emit(item); } } }"
                            " else { emit(v); }"
                        )
                    },
                }
            },
        }

    _AGG_FIELD_CACHE[field] = resolved
    return resolved


def get_contract_analytics(
    q: Optional[str] = None,
    year: Optional[int] = None,
    entity: Optional[str] = None,
    nif: Optional[str] = None,
    cpv_code: Optional[str] = None,
    region: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    top_entities: int = 8,
    top_cpv: int = 8,
    value_buckets: int = 7,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Devolve agregações analíticas para o dashboard de contratos."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}

    base_query = _build_contract_query(
        q, year, entity, nif, region=region, cpv_code=cpv_code,
        min_price=min_price, max_price=max_price, start_date=start_date, end_date=end_date,
    )

    procedure_agg = _resolve_agg_target(client, "tipoprocedimento")
    contract_agg = _resolve_agg_target(client, "tipoContrato")
    runtime_mappings: Dict[str, Any] = {}
    for resolved in (procedure_agg, contract_agg):
        if resolved.get("runtime"):
            runtime_mappings.update(resolved["runtime"])

    analytics_body: Dict[str, Any] = {
        "size": 0,
        "track_total_hits": True,
        "query": base_query,
        "aggs": {
                    "total_value": {"sum": {"field": "precoContratual"}},
                    "avg_value": {"avg": {"field": "precoContratual"}},
                    "max_value": {"max": {"field": "precoContratual"}},
                    "by_year": {
                        "terms": {"field": "Ano", "size": 50, "order": {"_key": "desc"}},
                        "aggs": {"total_value": {"sum": {"field": "precoContratual"}}},
                    },
                    "by_month": {
                        "date_histogram": {
                            "field": "dataPublicacao",
                            "calendar_interval": "month",
                            "format": "yyyy-MM",
                            "min_doc_count": 1,
                        }
                    },
                    "value_distribution": {
                        "histogram": {
                            "field": "precoContratual",
                            "interval": 50000,
                            "min_doc_count": 1,
                        }
                    },
                    "top_adjudicantes": {
                        "nested": {"path": "adjudicantes.parsed"},
                        "aggs": {
                            "names": {
                                "terms": {
                                    "field": "adjudicantes.parsed.nif",
                                    "size": top_entities,
                                    "order": {"total_value": "desc"},
                                },
                                "aggs": {
                                    # `*.parsed.nome` é `keyword` e não pode ser agregado;
                                    # os `top_hits` trazem o nome legível de cada NIF.
                                    "name": {"top_hits": {"size": 1, "_source": ["adjudicantes.parsed.nome"]}},
                                    "total_value": {
                                        "reverse_nested": {},
                                        "aggs": {"value": {"sum": {"field": "precoContratual"}}},
                                    },
                                },
                            }
                        },
                    },
                    "top_adjudicatarios": {
                        "nested": {"path": "adjudicatarios.parsed"},
                        "aggs": {
                            "names": {
                                "terms": {
                                    "field": "adjudicatarios.parsed.nif",
                                    "size": top_entities,
                                    "order": {"total_value": "desc"},
                                },
                                "aggs": {
                                    "name": {"top_hits": {"size": 1, "_source": ["adjudicatarios.parsed.nome"]}},
                                    "total_value": {
                                        "reverse_nested": {},
                                        "aggs": {"value": {"sum": {"field": "precoContratual"}}},
                                    },
                                },
                            }
                        },
                    },
                    "top_cpv": {
                        "nested": {"path": "cpv"},
                        "aggs": {
                            "codes": {
                                "terms": {
                                    "field": "cpv.code",
                                    "size": top_cpv,
                                    "order": {"_count": "desc"},
                                },
                                "aggs": {
                                    # `cpv.description` é `text` (sem `.keyword`): os `top_hits`
                                    # devolvem a descrição legível de cada documento.
                                    "description": {"top_hits": {"size": 1, "_source": ["cpv"]}},
                                    "total_value": {
                                        "reverse_nested": {},
                                        "aggs": {"value": {"sum": {"field": "precoContratual"}}},
                                    },
                                },
                            }
                        },
                    },
                    "procedure_types": {
                        "terms": {"field": procedure_agg["field"], "size": 20, "missing": "N/A"}
                    },
                    "contract_types": {
                        "terms": {"field": contract_agg["field"], "size": 20, "missing": "N/A"}
                    },
        },
    }
    if runtime_mappings:
        analytics_body["runtime_mappings"] = runtime_mappings

    try:
        resp = client.search(index=CONTRACTS_INDEX, body=analytics_body)

        aggs = resp["aggregations"]

        def fmt_money(v):
            return round(v, 2) if v is not None else None

        entity_rows: List[Dict[str, Any]] = []
        seen_entities: set = set()
        for agg_key in ("top_adjudicantes", "top_adjudicatarios"):
            for b in aggs.get(agg_key, {}).get("names", {}).get("buckets", []):
                key = b["key"]
                if not key or key in seen_entities:
                    continue
                seen_entities.add(key)
                total_value_obj = b.get("total_value", {})
                value = total_value_obj.get("value", {}).get("value") if isinstance(total_value_obj.get("value"), dict) else total_value_obj.get("value")
                entity_rows.append({
                    "key": key,
                    "count": b["doc_count"],
                    "total_value": fmt_money(value),
                    "description": _top_hit_name(b.get("name")),
                })
        entity_rows.sort(key=lambda x: (x.get("total_value") or 0, x.get("count") or 0), reverse=True)
        entity_rows = entity_rows[:top_entities]

        cpv_rows = []
        for b in aggs.get("top_cpv", {}).get("codes", {}).get("buckets", []):
            total_value_obj = b.get("total_value", {})
            value = total_value_obj.get("value", {}).get("value") if isinstance(total_value_obj.get("value"), dict) else total_value_obj.get("value")
            cpv_rows.append({
                "key": b["key"],
                "count": b["doc_count"],
                "total_value": fmt_money(value),
                "description": _cpv_description_from_hits(b.get("description"), b["key"]),
            })

        return {
            "total_contracts": resp["hits"]["total"]["value"],
            "total_value": fmt_money(aggs["total_value"].get("value")),
            "avg_value": fmt_money(aggs["avg_value"].get("value")),
            "max_value": fmt_money(aggs["max_value"].get("value")),
            "by_year": [{"key": str(b["key"]), "count": b["doc_count"], "total_value": fmt_money(b.get("total_value", {}).get("value"))} for b in aggs["by_year"]["buckets"]],
            "by_month": [{"key": b["key_as_string"], "count": b["doc_count"]} for b in aggs["by_month"]["buckets"]],
            # `precoContratual` tem valores negativos (correções/notas de crédito) que
            # caíam nos primeiros escalões do histograma; ignoram-se aqui.
            "value_distribution": [
                {"key": f"{int(b['key'])} - {int(b['key']) + 50000}", "count": b["doc_count"]}
                for b in aggs["value_distribution"]["buckets"]
                if b.get("key") is not None and b["key"] >= 0
            ][:value_buckets],
            "top_entities": entity_rows,
            "top_cpv": cpv_rows,
            "procedure_types": [{"key": b["key"], "count": b["doc_count"]} for b in aggs["procedure_types"]["buckets"]],
            "contract_types": [{"key": b["key"], "count": b["doc_count"]} for b in aggs["contract_types"]["buckets"]],
            "year": year,
        }
    except Exception as e:
        return {"error": str(e)}


# --- Diretório de empresas (entidades) ---

def _entity_lookup_by_nif_query(nif: str) -> Dict[str, Any]:
    """Devolve uma query nested que procura uma entidade por NIF em ambos os papéis."""
    return {
        "bool": {
            "should": [
                {"nested": {"path": "adjudicantes.parsed", "query": {"term": {"adjudicantes.parsed.nif": nif}}}},
                {"nested": {"path": "adjudicatarios.parsed", "query": {"term": {"adjudicatarios.parsed.nif": nif}}}},
            ],
            "minimum_should_match": 1,
        }
    }


def get_company_by_nif(
    nif: str,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Devolve resumo de uma entidade específica pelo NIF.

    Faz uma pesquisa nested com agregações por papel, devolvendo a estrutura
    CompanySummary (nif, name, total_value, adjudicante/adjudicatario, etc.).
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}

    ensure_indices(client)

    try:
        resp = client.search(
            index=CONTRACTS_INDEX,
            body={
                "size": 0,
                "query": _entity_lookup_by_nif_query(nif),
                "aggs": {
                    "adjudicantes": {
                        "nested": {"path": "adjudicantes.parsed"},
                        "aggs": {
                            "filtered": {
                                "filter": {"term": {"adjudicantes.parsed.nif": nif}},
                                "aggs": {
                                    "name": {"top_hits": {"size": 1, "_source": ["adjudicantes.parsed.nome"]}},
                                    "total_value": {
                                        "reverse_nested": {},
                                        "aggs": {"value": {"sum": {"field": "precoContratual"}}},
                                    },
                                    "years": {
                                        "reverse_nested": {},
                                        "aggs": {"stats": {"stats": {"field": "Ano"}}},
                                    },
                                    "count": {"reverse_nested": {}},
                                },
                            }
                        },
                    },
                    "adjudicatarios": {
                        "nested": {"path": "adjudicatarios.parsed"},
                        "aggs": {
                            "filtered": {
                                "filter": {"term": {"adjudicatarios.parsed.nif": nif}},
                                "aggs": {
                                    "name": {"top_hits": {"size": 1, "_source": ["adjudicatarios.parsed.nome"]}},
                                    "total_value": {
                                        "reverse_nested": {},
                                        "aggs": {"value": {"sum": {"field": "precoContratual"}}},
                                    },
                                    "years": {
                                        "reverse_nested": {},
                                        "aggs": {"stats": {"stats": {"field": "Ano"}}},
                                    },
                                    "count": {"reverse_nested": {}},
                                },
                            }
                        },
                    },
                },
            },
        )

        aggs = resp["aggregations"]

        def fmt_money(v):
            return round(v, 2) if v is not None else None

        def build_role_summary(agg_key: str) -> Optional[Dict[str, Any]]:
            bucket = aggs.get(agg_key, {}).get("filtered", {})
            doc_count = bucket.get("doc_count", 0)
            if not doc_count:
                return None
            name_hits = bucket.get("name", {}).get("hits", {}).get("hits", [])
            name_from_hit: Optional[str] = None
            if name_hits:
                src = name_hits[0].get("_source", {})
                if isinstance(src, dict):
                    name_from_hit = src.get("nome")
            total_value_obj = bucket.get("total_value", {})
            value = total_value_obj.get("value", {}).get("value") if isinstance(total_value_obj.get("value"), dict) else total_value_obj.get("value")
            years_stats = bucket.get("years", {}).get("stats", {})
            first_year = years_stats.get("min")
            last_year = years_stats.get("max")
            return {
                "contracts_count": doc_count,
                "total_value": fmt_money(value) or 0.0,
                "avg_value": fmt_money(value / doc_count) if value and doc_count else None,
                "first_year": int(first_year) if first_year is not None else None,
                "last_year": int(last_year) if last_year is not None else None,
                "name": name_from_hit,
            }

        adjudicante = build_role_summary("adjudicantes")
        adjudicatario = build_role_summary("adjudicatarios")
        contracts_total = (adjudicante["contracts_count"] if adjudicante else 0) + (adjudicatario["contracts_count"] if adjudicatario else 0)
        total_value = (adjudicante["total_value"] if adjudicante else 0.0) + (adjudicatario["total_value"] if adjudicatario else 0.0)

        # Escolhe o nome mais comum entre os papéis
        names: List[str] = []
        for key in ("adjudicantes", "adjudicatarios"):
            role_summary = adjudicante if key == "adjudicantes" else adjudicatario
            if role_summary and role_summary.get("name"):
                names.append(role_summary["name"])
        name = names[0] if names else nif

        return {
            "nif": nif,
            "name": name,
            "normalized_name": name,
            "contracts_total": contracts_total,
            "total_value": fmt_money(total_value) or 0.0,
            "adjudicante": adjudicante,
            "adjudicatario": adjudicatario,
        }
    except Exception as e:
        return {"error": str(e)}


def _company_role_filter(role: Optional[str]) -> Optional[List[Dict[str, Any]]]:
    """Devolve filtro de caminho nested conforme o papel pretendido."""
    if role == "adjudicante":
        return [{"nested": {"path": "adjudicantes.parsed", "query": {"exists": {"field": "adjudicantes.parsed.nif"}}}}]
    if role == "adjudicatario":
        return [{"nested": {"path": "adjudicatarios.parsed", "query": {"exists": {"field": "adjudicatarios.parsed.nif"}}}}]
    return None


def _company_name_query(q: Optional[str]) -> Optional[Dict[str, Any]]:
    """Query de texto para nome ou NIF de empresa em qualquer um dos papéis.

    O nome em `*.parsed.nome` é um campo `keyword` (só corresponde a nomes
    exatos), pelo que a pesquisa por nome parcial usa o campo de texto
    `*.raw` (ex.: ``"503933813 - Infraestruturas de Portugal"``), insensível a
    maiúsculas e a palavras parciais.
    """
    if not q:
        return None
    q_clean = q.strip()
    if not q_clean:
        return None
    should_clauses: List[Dict[str, Any]] = []
    for role_path in ("adjudicantes", "adjudicatarios"):
        should_clauses.append(
            {"match": {f"{role_path}.raw": {"query": q_clean, "operator": "and"}}}
        )
        should_clauses.append(
            {
                "nested": {
                    "path": f"{role_path}.parsed",
                    "query": {"match": {f"{role_path}.parsed.nome": {"query": q_clean, "operator": "and"}}},
                }
            }
        )
        should_clauses.append(
            {
                "nested": {
                    "path": f"{role_path}.parsed",
                    "query": {"term": {f"{role_path}.parsed.nif": q_clean}},
                }
            }
        )
    return {
        "bool": {
            "should": should_clauses,
            "minimum_should_match": 1,
        }
    }


def search_companies(
    q: Optional[str] = None,
    role: Optional[str] = "all",
    region: Optional[str] = None,
    min_contracts: int = 1,
    min_value: Optional[float] = None,
    max_value: Optional[float] = None,
    year: Optional[int] = None,
    size: int = 20,
    from_: int = 0,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Pesquisa entidades únicas derivadas dos contratos indexados.

    Utiliza duas agregações nested por NIF (adjudicantes/adjudicatarios) e depois
    combina os resultados em memória para devolver uma lista paginada de empresas.
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "total": 0, "items": []}

    ensure_indices(client)

    base_filters: List[Dict[str, Any]] = []
    if year:
        base_filters.append({"term": {"Ano": year}})
    if region:
        base_filters.append(_region_filter(region))
    role_filter = _company_role_filter(role)
    if role_filter:
        base_filters.extend(role_filter)

    name_query = _company_name_query(q)

    base_query: Dict[str, Any] = {"bool": {}}
    if base_filters:
        base_query["bool"]["filter"] = base_filters
    if name_query:
        base_query["bool"]["must"] = name_query
    if not base_query["bool"]:
        base_query = {"match_all": {}}

    try:
        resp = client.search(
            index=CONTRACTS_INDEX,
            body={
                "size": 0,
                "query": base_query,
                "aggs": {
                    "adjudicantes": {
                        "nested": {"path": "adjudicantes.parsed"},
                        "aggs": {
                            "by_nif": {
                                "terms": {
                                    "field": "adjudicantes.parsed.nif",
                                    "size": 2000,
                                    "order": {"total_value": "desc"},
                                },
                                "aggs": {
                                    "name": {
                                        "top_hits": {"size": 1, "_source": ["adjudicantes.parsed.nome"]}
                                    },
                                    "total_value": {
                                        "reverse_nested": {},
                                        "aggs": {"value": {"sum": {"field": "precoContratual"}}},
                                    },
                                    "years": {
                                        "reverse_nested": {},
                                        "aggs": {"stats": {"stats": {"field": "Ano"}}},
                                    },
                                },
                            }
                        },
                    },
                    "adjudicatarios": {
                        "nested": {"path": "adjudicatarios.parsed"},
                        "aggs": {
                            "by_nif": {
                                "terms": {
                                    "field": "adjudicatarios.parsed.nif",
                                    "size": 2000,
                                    "order": {"total_value": "desc"},
                                },
                                "aggs": {
                                    "name": {
                                        "top_hits": {"size": 1, "_source": ["adjudicatarios.parsed.nome"]}
                                    },
                                    "total_value": {
                                        "reverse_nested": {},
                                        "aggs": {"value": {"sum": {"field": "precoContratual"}}},
                                    },
                                    "years": {
                                        "reverse_nested": {},
                                        "aggs": {"stats": {"stats": {"field": "Ano"}}},
                                    },
                                },
                            }
                        },
                    },
                    # Contagens reais de NIF distintos (a lista acima é limitada aos
                    # 2000 maiores por papel, pelo que `total` é sempre um limite
                    # inferior do universo de entidades).
                    "unique_adjudicantes": {
                        "nested": {"path": "adjudicantes.parsed"},
                        "aggs": {
                            "nifs": {
                                "cardinality": {
                                    "field": "adjudicantes.parsed.nif",
                                    "precision_threshold": 40000,
                                }
                            }
                        },
                    },
                    "unique_adjudicatarios": {
                        "nested": {"path": "adjudicatarios.parsed"},
                        "aggs": {
                            "nifs": {
                                "cardinality": {
                                    "field": "adjudicatarios.parsed.nif",
                                    "precision_threshold": 40000,
                                }
                            }
                        },
                    },
                },
            },
        )

        companies: Dict[str, Dict[str, Any]] = {}

        def fmt_money(v):
            return round(v, 2) if v is not None else None

        for agg_key in ("adjudicantes", "adjudicatarios"):
            role_name = "adjudicante" if agg_key == "adjudicantes" else "adjudicatario"
            for b in resp["aggregations"][agg_key]["by_nif"]["buckets"]:
                nif = b["key"]
                name_hits = b.get("name", {}).get("hits", {}).get("hits", [])
                name = nif or "Nome desconhecido"
                if name_hits:
                    src = name_hits[0].get("_source", {})
                    if isinstance(src, dict):
                        name = src.get("nome") or name
                total_value_obj = b.get("total_value", {})
                value = total_value_obj.get("value", {}).get("value") if isinstance(total_value_obj.get("value"), dict) else total_value_obj.get("value")
                total_value = value or 0.0
                years_stats = b.get("years", {}).get("stats", {})
                first_year = years_stats.get("min")
                last_year = years_stats.get("max")
                count = b["doc_count"]

                if count < min_contracts:
                    continue
                if min_value is not None and total_value < min_value:
                    continue
                if max_value is not None and total_value > max_value:
                    continue

                if nif and nif not in companies:
                    companies[nif] = {
                        "nif": nif,
                        "name": name,
                        "normalized_name": name,
                        "contracts_total": 0,
                        "total_value": 0.0,
                        "adjudicante": None,
                        "adjudicatario": None,
                    }
                if not nif:
                    key = f"__no_nif__{name.lower().strip()}"
                    if key not in companies:
                        companies[key] = {
                            "nif": None,
                            "name": name,
                            "normalized_name": name,
                            "contracts_total": 0,
                            "total_value": 0.0,
                            "adjudicante": None,
                            "adjudicatario": None,
                        }

                entry = companies[nif if nif else key]
                role_summary = {
                    "contracts_count": count,
                    "total_value": fmt_money(total_value) or 0.0,
                    "avg_value": fmt_money(total_value / count) if count else None,
                    "first_year": int(first_year) if first_year is not None else None,
                    "last_year": int(last_year) if last_year is not None else None,
                }
                entry[role_name] = role_summary
                entry["contracts_total"] = (entry["contracts_total"] or 0) + count
                entry["total_value"] = (entry["total_value"] or 0.0) + total_value

        items = sorted(companies.values(), key=lambda x: (x.get("total_value") or 0, x.get("contracts_total") or 0), reverse=True)
        total = len(items)
        page = items[from_: from_ + size]
        for it in page:
            it["total_value"] = fmt_money(it["total_value"]) or 0.0

        unique_adjudicantes = resp["aggregations"].get("unique_adjudicantes", {}).get("nifs", {}).get("value", 0)
        unique_adjudicatarios = resp["aggregations"].get("unique_adjudicatarios", {}).get("nifs", {}).get("value", 0)

        return {
            "query": q,
            "total": total,
            "items": page,
            "from": from_,
            "size": size,
            "unique_adjudicantes": int(unique_adjudicantes or 0),
            "unique_adjudicatarios": int(unique_adjudicatarios or 0),
        }
    except Exception as e:
        return {"query": q, "total": 0, "items": [], "error": str(e)}


def get_company_contracts(
    nif: Optional[str] = None,
    name: Optional[str] = None,
    role: Optional[str] = "all",
    size: int = 20,
    from_: int = 0,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Devolve contratos onde a entidade aparece como adjudicante/adjudicatário."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "total": 0, "items": []}

    should: List[Dict[str, Any]] = []
    if nif:
        if role in ("all", "adjudicante", None):
            should.append({
                "nested": {
                    "path": "adjudicantes.parsed",
                    "query": {"term": {"adjudicantes.parsed.nif": nif}},
                }
            })
        if role in ("all", "adjudicatario", None):
            should.append({
                "nested": {
                    "path": "adjudicatarios.parsed",
                    "query": {"term": {"adjudicatarios.parsed.nif": nif}},
                }
            })
    if name:
        if role in ("all", "adjudicante", None):
            should.append({
                "nested": {
                    "path": "adjudicantes.parsed",
                    "query": {"match": {"adjudicantes.parsed.nome": name}},
                }
            })
        if role in ("all", "adjudicatario", None):
            should.append({
                "nested": {
                    "path": "adjudicatarios.parsed",
                    "query": {"match": {"adjudicatarios.parsed.nome": name}},
                }
            })

    if not should:
        return {"error": "É necessário indicar NIF ou nome", "total": 0, "items": []}

    query = {
        "bool": {
            "should": should,
            "minimum_should_match": 1,
        }
    }

    try:
        resp = client.search(
            index=CONTRACTS_INDEX,
            body={
                "size": size,
                "from": from_,
                "query": query,
                "sort": [{"dataPublicacao": {"order": "desc"}}, "_score"],
                "track_total_hits": True,
            },
        )
        items = []
        for hit in resp["hits"]["hits"]:
            src = hit["_source"]
            src["doc_id"] = hit["_id"]
            src["score"] = hit.get("_score")
            items.append(src)

        return {
            "nif": nif,
            "name": name,
            "role": role,
            "total": resp["hits"]["total"]["value"],
            "items": items,
            "from": from_,
            "size": size,
        }
    except Exception as e:
        return {"error": str(e), "total": 0, "items": []}


def _top_hit_name(agg: Optional[Dict[str, Any]]) -> str:
    """Nome legível de um bucket a partir de uma agregação `top_hits`.

    `*.parsed.nome` é `keyword` (não agregável), pelo que o nome vem dos
    documentos; o `_source` pode trazer só o campo pedido ou o objeto completo.
    """
    hits = (agg or {}).get("hits", {}).get("hits", []) or []
    for hit in hits:
        source = hit.get("_source") if isinstance(hit, dict) else None
        if not isinstance(source, dict):
            continue
        name = source.get("nome")
        if isinstance(name, str) and name.strip():
            return name.strip()
        parsed = source.get("parsed")
        if isinstance(parsed, dict):
            nested_name = parsed.get("nome")
            if isinstance(nested_name, str) and nested_name.strip():
                return nested_name.strip()
    return ""


def _cpv_description_from_hits(agg: Optional[Dict[str, Any]], code: Any) -> str:
    """Lê a descrição legível de um CPV a partir de uma agregação `top_hits`.

    `cpv.description` está mapeado como `text` (sem `.keyword`), pelo que não
    pode ser agregado. Os `top_hits` trazem `_source.cpv` — que pode vir como a
    lista completa do documento ou já como o próprio objeto do CPV visitado —
    e aqui escolhe-se a entrada cujo `code` corresponde ao do bucket.
    """
    hits = (agg or {}).get("hits", {}).get("hits", []) or []
    fallback = ""
    for hit in hits:
        source = hit.get("_source") if isinstance(hit, dict) else None
        if not isinstance(source, dict):
            continue
        entries = source.get("cpv")
        if entries is None:
            entries = source
        if isinstance(entries, dict):
            entries = [entries]
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            description = entry.get("description")
            if not description:
                continue
            if code is None or entry.get("code") == code:
                return description
            if not fallback:
                fallback = description
    return fallback


def get_company_analytics(
    nif: Optional[str] = None,
    name: Optional[str] = None,
    role: Optional[str] = "all",
    year: Optional[int] = None,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Devolve analytics para uma empresa específica."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}

    should: List[Dict[str, Any]] = []
    if nif:
        if role in ("all", "adjudicante", None):
            should.append({
                "nested": {
                    "path": "adjudicantes.parsed",
                    "query": {"term": {"adjudicantes.parsed.nif": nif}},
                }
            })
        if role in ("all", "adjudicatario", None):
            should.append({
                "nested": {
                    "path": "adjudicatarios.parsed",
                    "query": {"term": {"adjudicatarios.parsed.nif": nif}},
                }
            })
    if name:
        if role in ("all", "adjudicante", None):
            should.append({
                "nested": {
                    "path": "adjudicantes.parsed",
                    "query": {"match": {"adjudicantes.parsed.nome": name}},
                }
            })
        if role in ("all", "adjudicatario", None):
            should.append({
                "nested": {
                    "path": "adjudicatarios.parsed",
                    "query": {"match": {"adjudicatarios.parsed.nome": name}},
                }
            })

    if not should:
        return {"error": "É necessário indicar NIF ou nome"}

    filters: List[Dict[str, Any]] = []
    if year:
        filters.append({"term": {"Ano": year}})

    query = {"bool": {"should": should, "minimum_should_match": 1}}
    if filters:
        query["bool"]["filter"] = filters

    try:
        resp = client.search(
            index=CONTRACTS_INDEX,
            body={
                "size": 0,
                "track_total_hits": True,
                "query": query,
                "aggs": {
                    "total_value": {"sum": {"field": "precoContratual"}},
                    "avg_value": {"avg": {"field": "precoContratual"}},
                    "max_value": {"max": {"field": "precoContratual"}},
                    "by_year": {
                        "terms": {"field": "Ano", "size": 50, "order": {"_key": "desc"}},
                        "aggs": {"total_value": {"sum": {"field": "precoContratual"}}},
                    },
                    "by_month": {
                        "date_histogram": {
                            "field": "dataPublicacao",
                            "calendar_interval": "month",
                            "format": "yyyy-MM",
                            "min_doc_count": 1,
                        }
                    },
                    "by_cpv": {
                        "nested": {"path": "cpv"},
                        "aggs": {
                            "codes": {
                                "terms": {"field": "cpv.code", "size": 10, "order": {"total_value": "desc"}},
                                "aggs": {
                                    # `cpv.description` é `text` sem subcampo `.keyword`, pelo que
                                    # uma agregação `terms` devolvia sempre vazio; os `top_hits`
                                    # trazem a descrição real do documento.
                                    "description": {"top_hits": {"size": 1, "_source": ["cpv"]}},
                                    "total_value": {
                                        "reverse_nested": {},
                                        "aggs": {"value": {"sum": {"field": "precoContratual"}}},
                                    },
                                },
                            }
                        },
                    },
                    "top_partners": {
                        "nested": {"path": "adjudicatarios.parsed"},
                        "aggs": {
                            "by_nif": {
                                "terms": {"field": "adjudicatarios.parsed.nif", "size": 8, "order": {"total_value": "desc"}},
                                "aggs": {
                                    "name": {"top_hits": {"size": 1, "_source": ["adjudicatarios.parsed.nome"]}},
                                    "total_value": {
                                        "reverse_nested": {},
                                        "aggs": {"value": {"sum": {"field": "precoContratual"}}},
                                    },
                                },
                            }
                        },
                    },
                    "procedure_types": {
                        "terms": {"field": "tipoprocedimento.keyword", "size": 20, "missing": "N/A"}
                    },
                    "contract_types": {
                        "terms": {"field": "tipoContrato.keyword", "size": 20, "missing": "N/A"}
                    },
                    "by_value_range": {
                        "histogram": {"field": "precoContratual", "interval": 25000, "min_doc_count": 1}
                    },
                },
            },
        )

        aggs = resp["aggregations"]

        def fmt_money(v):
            return round(v, 2) if v is not None else None

        def extract_value(total_value_obj):
            if isinstance(total_value_obj.get("value"), dict):
                return total_value_obj["value"].get("value")
            return total_value_obj.get("value")

        cpv_rows = []
        for b in aggs.get("by_cpv", {}).get("codes", {}).get("buckets", []):
            cpv_rows.append({
                "key": b["key"],
                "count": b["doc_count"],
                "total_value": fmt_money(extract_value(b.get("total_value", {}))),
                "description": _cpv_description_from_hits(b.get("description"), b["key"]),
            })

        partner_rows = []
        for b in aggs.get("top_partners", {}).get("by_nif", {}).get("buckets", []):
            if b["key"] == nif:
                continue
            partner_name_hits = b.get("name", {}).get("hits", {}).get("hits", [])
            partner_name = ""
            if partner_name_hits:
                partner_src = partner_name_hits[0].get("_source", {})
                if isinstance(partner_src, dict):
                    partner_name = partner_src.get("nome", "")
            partner_rows.append({
                "key": b["key"],
                "count": b["doc_count"],
                "total_value": fmt_money(extract_value(b.get("total_value", {}))),
                "description": partner_name,
            })

        company_summary = None
        if nif:
            company_summary = get_company_by_nif(nif, es=client)
            if "error" in company_summary:
                company_summary = None

        return {
            "company": company_summary,
            "total_contracts": resp["hits"]["total"]["value"],
            "total_value": fmt_money(aggs["total_value"].get("value")),
            "avg_value": fmt_money(aggs["avg_value"].get("value")),
            "max_value": fmt_money(aggs["max_value"].get("value")),
            "by_year": [{"key": str(b["key"]), "count": b["doc_count"], "total_value": fmt_money(b.get("total_value", {}).get("value"))} for b in aggs["by_year"]["buckets"]],
            "by_month": [{"key": b["key_as_string"], "count": b["doc_count"]} for b in aggs["by_month"]["buckets"]],
            "by_cpv": cpv_rows,
            "top_partners": partner_rows,
            "by_procedure_type": [{"key": b["key"], "count": b["doc_count"]} for b in aggs["procedure_types"]["buckets"]],
            "by_contract_type": [{"key": b["key"], "count": b["doc_count"]} for b in aggs["contract_types"]["buckets"]],
            "by_value_range": [{"key": f"{int(b['key'])} - {int(b['key']) + 25000}", "count": b["doc_count"]} for b in aggs["by_value_range"]["buckets"][:10]],
            "year": year,
        }
    except Exception as e:
        return {"error": str(e)}


def list_contract_years(es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Devolve anos disponíveis e total indexado por ano."""
    client = es or get_es_client()
    available = contract_years_available()
    if not client:
        return {"available": available, "indexed": []}
    try:
        resp = client.search(
            index=CONTRACTS_INDEX,
            body={
                "size": 0,
                "aggs": {
                    "by_year": {
                        "terms": {"field": "Ano", "size": 50, "order": {"_key": "desc"}},
                    }
                },
            },
        )
        indexed = [{"year": int(bucket["key"]), "count": bucket["doc_count"]} for bucket in resp["aggregations"]["by_year"]["buckets"]]
        return {"available": available, "indexed": indexed}
    except Exception as e:
        return {"available": available, "indexed": [], "error": str(e)}


def get_contract_by_id(idcontrato: str, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Devolve um contrato pelo identificador publicado no portal."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}
    try:
        response = client.search(
            index=CONTRACTS_INDEX,
            body={"size": 1, "query": {"term": {"idcontrato": idcontrato}}},
        )
        hits = response.get("hits", {}).get("hits", [])
        if not hits:
            return {"error": "Contrato não encontrado", "status_code": 404}
        source = dict(hits[0].get("_source", {}))
        source["doc_id"] = hits[0].get("_id")
        return source
    except Exception as exc:
        return {"error": str(exc)}


def get_contract_regional_analytics(year: Optional[int] = None, size: int = 30, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Agrega volume e valor contratual por NUTS."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "regions": []}
    query: Dict[str, Any] = {"match_all": {}}
    if year:
        query = {"term": {"Ano": year}}
    try:
        response = client.search(
            index=CONTRACTS_INDEX,
            body={
                "track_total_hits": True,
                "size": 0,
                "query": query,
                "aggs": {
                    "regions": {
                        "terms": {"field": "NUTs", "size": size, "missing": "Não especificado"},
                        "aggs": {"total_value": {"sum": {"field": "precoContratual"}}},
                    },
                    "total_value": {"sum": {"field": "precoContratual"}},
                },
            },
        )
        aggs = response.get("aggregations", {})
        return {
            "total_contracts": response.get("hits", {}).get("total", {}).get("value", 0),
            "total_value": aggs.get("total_value", {}).get("value"),
            "regions": [
                {"key": bucket["key"], "count": bucket["doc_count"], "total_value": bucket.get("total_value", {}).get("value")}
                for bucket in aggs.get("regions", {}).get("buckets", [])
            ],
        }
    except Exception as exc:
        return {"error": str(exc), "regions": []}


def _region_filter(region: Optional[str] = None) -> Dict[str, Any]:
    """Filtro de região. Aceita código curto (ex: PT11A) ou string completa NUTS.

    ES armazena NUTs como strings completas (ex: "PT11A - Área Metropolitana do Porto"),
    por isso usamos wildcard/prefixo quando a região fornecida não contém o separador.
    O grupo "Não especificado" corresponde aos contratos sem NUTs (campo ausente ou vazio).
    """
    if not region:
        return None
    if is_unspecified(region):
        return {
            "bool": {
                "should": [
                    {"bool": {"must_not": {"exists": {"field": "NUTs"}}}},
                    {"term": {"NUTs": ""}},
                ],
                "minimum_should_match": 1,
            }
        }
    if " - " in region:
        return {"term": {"NUTs": region}}
    return {"wildcard": {"NUTs": f"{region}*"}}


def _match_pair_query(nif: Optional[str] = None, counterparty_nif: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Returns nested must query for adjudicante/adjudicatario pair when both provided."""
    if nif and counterparty_nif:
        return {
            "bool": {
                "must": [
                    {
                        "nested": {
                            "path": "adjudicantes.parsed",
                            "query": {"term": {"adjudicantes.parsed.nif": nif}},
                        }
                    },
                    {
                        "nested": {
                            "path": "adjudicatarios.parsed",
                            "query": {"term": {"adjudicatarios.parsed.nif": counterparty_nif}},
                        }
                    },
                ]
            }
        }
    return None


def get_contract_relationships(
    limit: int = 1000,
    region: Optional[str] = None,
    nif: Optional[str] = None,
    counterparty_nif: Optional[str] = None,
    role: Optional[str] = "all",
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Constrói relações adjudicante -> adjudicatário a partir dos contratos recentes."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "relations": []}
    filters: List[Dict[str, Any]] = []
    if region:
        filters.append(_region_filter(region))
    pair_query = _match_pair_query(nif, counterparty_nif)
    if pair_query:
        filters.append(pair_query)
    elif nif:
        # Include any contract where this NIF appears (adjudicante or adjudicatario)
        filters.append({
            "bool": {
                "should": [
                    {"nested": {"path": "adjudicantes.parsed", "query": {"term": {"adjudicantes.parsed.nif": nif}}}},
                    {"nested": {"path": "adjudicatarios.parsed", "query": {"term": {"adjudicatarios.parsed.nif": nif}}}},
                ],
                "minimum_should_match": 1,
            }
        })
    query: Dict[str, Any] = {"bool": {"filter": filters}} if filters else {"match_all": {}}
    try:
        response = client.search(
            index=CONTRACTS_INDEX,
            body={
                "size": limit,
                "_source": ["adjudicantes.parsed", "adjudicatarios.parsed", "precoContratual", "Ano"],
                "query": query,
                "sort": [{"Ano": {"order": "desc", "unmapped_type": "integer"}}],
            },
        )
        pairs: Dict[str, Dict[str, Any]] = {}
        for hit in response.get("hits", {}).get("hits", []):
            source = hit.get("_source", {})
            buyers = source.get("adjudicantes", {}).get("parsed", [])
            suppliers = source.get("adjudicatarios", {}).get("parsed", [])
            value = source.get("precoContratual") or 0
            for buyer in buyers:
                for supplier in suppliers:
                    buyer_id = buyer.get("nif") or buyer.get("nome")
                    supplier_id = supplier.get("nif") or supplier.get("nome")
                    if not buyer_id or not supplier_id:
                        continue
                    # Apply role filter after the fact when only one NIF provided
                    if nif and not pair_query:
                        if role == "adjudicante" and buyer_id != nif:
                            continue
                        if role == "adjudicatario" and supplier_id != nif:
                            continue
                    key = f"{buyer_id}|{supplier_id}"
                    pair = pairs.setdefault(key, {
                        "source": buyer_id, "source_name": buyer.get("nome") or buyer_id,
                        "target": supplier_id, "target_name": supplier.get("nome") or supplier_id,
                        "count": 0, "total_value": 0.0,
                    })
                    pair["count"] += 1
                    pair["total_value"] += value
        relations = sorted(pairs.values(), key=lambda item: item["total_value"], reverse=True)[:100]
        for relation in relations:
            relation["total_value"] = round(relation["total_value"], 2)
        return {"relations": relations}
    except Exception as exc:
        return {"error": str(exc), "relations": []}


def get_contract_network(
    limit: int = 500,
    region: Optional[str] = None,
    nif: Optional[str] = None,
    role: Optional[str] = "all",
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Devolve nós e ligações para uma visualização de rede de entidades."""
    result = get_contract_relationships(limit=limit, region=region, nif=nif, role=role, es=es)
    if result.get("error"):
        return result
    nodes: Dict[str, Dict[str, Any]] = {}
    edges = []
    for relation in result.get("relations", []):
        for node_id, name, node_type in (
            (relation["source"], relation["source_name"], "adjudicante"),
            (relation["target"], relation["target_name"], "adjudicatario"),
        ):
            nodes.setdefault(node_id, {"id": node_id, "label": name, "type": node_type})
        edges.append({"source": relation["source"], "target": relation["target"], "count": relation["count"], "value": relation["total_value"]})
    return {"nodes": list(nodes.values()), "edges": edges}


# --- Marcas INPI (por entidade) e firmas RNPC (Pesquisa de Nomes Existentes) ---

def _enrich_docs_with_company(
    docs: List[Dict[str, Any]],
    company_nif: Optional[str] = None,
    company_name: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Acrescenta company_nif/company_name a cada documento antes de indexar."""
    enriched = []
    for doc in docs:
        item = dict(doc)
        if company_nif:
            item["company_nif"] = str(company_nif)
        if company_name:
            item["company_name"] = company_name
        enriched.append(item)
    return enriched


def _bulk_index_docs(
    index: str,
    docs: List[Dict[str, Any]],
    id_field: str,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Indexa documentos num índice, usando id_field para o _id (idempotente)."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "indexed_count": 0}

    ensure_indices(client)
    if not docs:
        return {"index": index, "indexed_count": 0, "total": 0}

    actions = []
    for doc in docs:
        doc_id = doc.get(id_field)
        action: Dict[str, Any] = {"_index": index, "_source": doc}
        if doc_id not in (None, ""):
            action["_id"] = f"{index}:{doc_id}"
        actions.append(action)

    try:
        success, errors = bulk(client, actions, raise_on_error=False, stats_only=False)
        error_count = len(errors) if isinstance(errors, list) else 0
        # Elasticsearch é near-real-time: refrescar garante que os dados ficam
        # imediatamente visíveis na ficha da empresa após o enriquecimento.
        try:
            client.indices.refresh(index=index)
        except Exception:
            pass
        return {
            "index": index,
            "indexed_count": success,
            "errors": error_count,
            "total": len(docs),
            "error_details": [str(e)[:300] for e in errors[:5]] if error_count else [],
        }
    except Exception as exc:
        return {"index": index, "error": str(exc), "indexed_count": 0, "total": len(docs)}


def _delete_stale_company_docs(
    index: str,
    company_nif: str,
    keep_ids: List[str],
    es: Optional[Elasticsearch] = None,
) -> int:
    """Remove documentos de uma empresa que já não constam do resultado atual.

    Evita acumular registos obsoletos quando a ficha é reenriquecida com um
    conjunto de resultados diferente (ex.: marcas entretanto expiradas).
    """
    client = es or get_es_client()
    if not client or not company_nif:
        return 0
    try:
        body: Dict[str, Any] = {
            "query": {
                "bool": {
                    "filter": [{"term": {"company_nif": str(company_nif)}}],
                }
            }
        }
        if keep_ids:
            # Só apaga os que não estão na lista de ids a manter.
            body["query"]["bool"]["must_not"] = [{"ids": {"values": keep_ids}}]
        resp = client.delete_by_query(index=index, body=body, refresh=True, conflicts="proceed")
        return resp.get("deleted", 0)
    except Exception as exc:
        logger.warning("Falha a remover documentos obsoletos de %s em %s: %s", company_nif, index, exc)
        return 0


def index_company_trademarks(
    company_nif: Optional[str],
    company_name: str,
    trademarks: List[Dict[str, Any]],
    replace_existing: bool = True,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Indexa as marcas INPI de uma empresa no índice TRADEMARKS_INDEX."""
    docs = _enrich_docs_with_company(trademarks, company_nif=company_nif, company_name=company_name)
    result = _bulk_index_docs(TRADEMARKS_INDEX, docs, id_field="nord", es=es)
    if replace_existing and company_nif:
        keep_ids = [f"{TRADEMARKS_INDEX}:{d.get('nord')}" for d in docs if d.get("nord") is not None]
        result["deleted_stale"] = _delete_stale_company_docs(TRADEMARKS_INDEX, str(company_nif), keep_ids, es=es)
    result["company_nif"] = company_nif
    result["company_name"] = company_name
    return result


def index_company_firmas(
    company_nif: Optional[str],
    company_name: str,
    firmas: List[Dict[str, Any]],
    replace_existing: bool = True,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Indexa firmas/nomes comerciais (RNPC/PNS) de uma empresa no índice FIRMAS_INDEX."""
    docs = _enrich_docs_with_company(firmas, company_nif=company_nif, company_name=company_name)
    # Usar NIPC quando existe; caso contrário o nome pesquisado + nome da firma.
    for doc in docs:
        doc.setdefault("_doc_key", doc.get("nipc") or f"{doc.get('search_query', '')}|{doc.get('nome', '')}")
    for doc in docs:
        doc["_source_id"] = doc.pop("_doc_key", None)
    result = _bulk_index_docs(FIRMAS_INDEX, docs, id_field="_source_id", es=es)
    if replace_existing and company_nif:
        keep_ids = [f"{FIRMAS_INDEX}:{d.get('_source_id')}" for d in docs if d.get("_source_id")]
        result["deleted_stale"] = _delete_stale_company_docs(FIRMAS_INDEX, str(company_nif), keep_ids, es=es)
    for doc in docs:
        doc.pop("_source_id", None)
    result["company_nif"] = company_nif
    result["company_name"] = company_name
    return result


# --- Construtor genérico de grafos de contratos ---------------------------------
#
# Cada dimensão descreve uma forma de agrupar contratos em nós. O construtor
# agrega uma amostra de contratos (por valor ou por data) em nós/arestas,
# devolvendo sempre `count` e `total_value`/`value` para a UI poder alternar
# entre a métrica de contratos e a métrica de valor sem novo pedido.

GRAPH_DIMENSIONS: Dict[str, Dict[str, str]] = {
    "adjudicante": {"label": "Entidade adjudicante", "type": "entidade"},
    "adjudicatario": {"label": "Entidade adjudicatária", "type": "entidade"},
    "entidade": {"label": "Entidade (qualquer papel)", "type": "entidade"},
    "concorrente": {"label": "Concorrente", "type": "concorrente"},
    "regiao": {"label": "Região (NUTS)", "type": "regiao"},
    "local_execucao": {"label": "Local de execução", "type": "regiao"},
    "cpv_divisao": {"label": "CPV — divisão (2 dígitos)", "type": "cpv"},
    "cpv_classe": {"label": "CPV — classe (4 dígitos)", "type": "cpv"},
    "procedimento": {"label": "Tipo de procedimento", "type": "processo"},
    "tipo_contrato": {"label": "Tipo de contrato", "type": "processo"},
    "pme": {"label": "Adjudicatário PME", "type": "processo"},
    "ano": {"label": "Ano", "type": "tempo"},
}

_GRAPH_SOURCE_FIELDS = [
    "idcontrato",
    "precoContratual",
    "PrecoTotalEfetivo",
    "Ano",
    "NUTs",
    "localExecucao",
    "tipoprocedimento",
    "tipoContrato",
    "adjudicatarioPMEs",
    "concorrentes",
    "cpv",
    "adjudicantes.parsed",
    "adjudicatarios.parsed",
]

# Separa "500233810-NOME, LDA., 502540249-OUTRA, LDA." em pares NIF/nome.
# O NIF pode vir mascarado como "--" em alguns contratos, daí a alternância.
_COMPETITOR_SPLIT_RE = re.compile(r",?\s*(?=(?:\d{9}|--)\s*-)")
_COMPETITOR_RE = re.compile(r"^(\d{9})\s*-\s*(.+)$")

# Máximo de valores considerados por contrato e por lado (evita explosão combinatória).
_GRAPH_MAX_VALUES_PER_DOC = 10

# Tetos de segurança do servidor. O cliente pode pedir "sem limite" (0), ficando
# sujeito a estes valores — devolvidos em `meta` para serem visíveis na UI.
GRAPH_MAX_SCAN = 400_000
GRAPH_MAX_NODES = 10_000
GRAPH_MAX_EDGES = 30_000
GRAPH_MAX_AGG_BUCKETS = 10_000
# Orçamento de buckets por pedido de agregação (o Elasticsearch falha acima de ~65 mil).
GRAPH_AGG_BUCKET_BUDGET = 20_000

# Dimensões agregáveis por termos (as restantes exigem varredura por documento,
# como `concorrente`, cujo campo textual tem vários valores por contrato).
_GRAPH_AGG_FIELDS: Dict[str, Dict[str, Optional[str]]] = {
    "adjudicante": {
        "nested": "adjudicantes.parsed",
        "field": "adjudicantes.parsed.nif",
        "label": "adjudicantes.parsed.nome",
    },
    "adjudicatario": {
        "nested": "adjudicatarios.parsed",
        "field": "adjudicatarios.parsed.nif",
        "label": "adjudicatarios.parsed.nome",
    },
    "regiao": {"nested": None, "field": "NUTs", "label": None, "missing": True},
    "local_execucao": {"nested": None, "field": "localExecucao", "label": None, "missing": True},
    "cpv_classe": {"nested": "cpv", "field": "cpv.code", "label": None},
    "cpv_divisao": {"nested": "cpv", "field": "cpv.code", "label": None},
    "procedimento": {"nested": None, "field": "tipoprocedimento", "label": None, "missing": True},
    "tipo_contrato": {"nested": None, "field": "tipoContrato", "label": None, "missing": True},
    "pme": {"nested": None, "field": "adjudicatarioPMEs", "label": None, "missing": True},
    "ano": {"nested": None, "field": "Ano", "label": None},
}


def _as_list(value: Any) -> List[Any]:
    """Normaliza valores que o Elasticsearch pode devolver como escalar ou lista."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _graph_parties(source: Dict[str, Any], key: str) -> List[Dict[str, str]]:
    """Extrai as entidades de `adjudicantes`/`adjudicatarios` (nested parsed)."""
    block = source.get(key) or {}
    if not isinstance(block, dict):
        return []
    out: List[Dict[str, str]] = []
    for party in _as_list(block.get("parsed")):
        if not isinstance(party, dict):
            continue
        nif = str(party.get("nif") or "").strip()
        nome = str(party.get("nome") or "").strip()
        if not nif and not nome:
            continue
        out.append({"id": nif or nome, "label": nome or nif})
    return out


def _graph_competitors(source: Dict[str, Any]) -> List[Dict[str, str]]:
    """Extrai os concorrentes do campo textual `concorrentes`."""
    raw = source.get("concorrentes")
    if not raw:
        return []
    chunks: List[str] = []
    for part in _as_list(raw):
        chunks.extend(_COMPETITOR_SPLIT_RE.split(str(part)))
    out: List[Dict[str, str]] = []
    seen: set = set()
    for chunk in chunks:
        text = chunk.strip().strip(",").strip()
        if not text:
            continue
        # Alguns contratos mascaram o NIF como "--"; nesses casos só há nome.
        if text.startswith("--"):
            text = text.lstrip("-").strip()
        match = _COMPETITOR_RE.match(text)
        if match:
            nif, nome = match.group(1), match.group(2).strip()
        else:
            nif, nome = "", text
        node_id = nif or nome
        if not node_id or node_id in seen:
            continue
        seen.add(node_id)
        out.append({"id": node_id, "label": nome or node_id})
    return out


def _dimension_values(source: Dict[str, Any], dimension: str) -> List[Dict[str, Any]]:
    """Devolve os valores de uma dimensão para um contrato: [{id, label, description?}]."""
    if dimension in ("adjudicante", "adjudicatario", "entidade"):
        values: List[Dict[str, Any]] = []
        if dimension in ("adjudicante", "entidade"):
            values.extend(_graph_parties(source, "adjudicantes"))
        if dimension in ("adjudicatario", "entidade"):
            values.extend(_graph_parties(source, "adjudicatarios"))
        return values

    if dimension == "concorrente":
        return _graph_competitors(source)

    if dimension == "regiao":
        out = []
        for nuts in _as_list(source.get("NUTs")):
            text = str(nuts or "").strip()
            if not text:
                continue
            code = text.split(" - ")[0].strip() or text
            out.append({"id": code, "label": text})
        # Contratos sem NUTs entram como "Não especificado" (em vez de desaparecerem).
        return out or [{"id": UNSPECIFIED_LABEL, "label": UNSPECIFIED_LABEL}]

    if dimension == "local_execucao":
        out = []
        for local in _as_list(source.get("localExecucao")):
            text = str(local or "").strip()
            if text:
                out.append({"id": text, "label": text})
        return out or [{"id": UNSPECIFIED_LABEL, "label": UNSPECIFIED_LABEL}]

    if dimension in ("cpv_divisao", "cpv_classe"):
        size = 2 if dimension == "cpv_divisao" else 4
        out = []
        seen_codes: set = set()
        for entry in _as_list(source.get("cpv")):
            if not isinstance(entry, dict):
                continue
            digits = re.sub(r"\D", "", str(entry.get("code") or ""))
            if len(digits) < size:
                continue
            prefix = digits[:size]
            if prefix in seen_codes:
                continue
            seen_codes.add(prefix)
            description = str(entry.get("description") or "").strip()
            if dimension == "cpv_divisao":
                # A descrição ao nível da divisão não é representativa (varia por classe).
                out.append({"id": prefix, "label": f"CPV {prefix}"})
            else:
                out.append({
                    "id": prefix,
                    "label": f"{prefix} — {description}" if description else prefix,
                    "description": description,
                })
        return out

    if dimension == "ano":
        ano = source.get("Ano")
        return [{"id": str(ano), "label": str(ano)}] if ano not in (None, "") else []

    if dimension == "procedimento":
        out = []
        for value in _as_list(source.get("tipoprocedimento")):
            text = str(value or "").strip()
            if text:
                out.append({"id": text, "label": text})
        return out or [{"id": UNSPECIFIED_LABEL, "label": UNSPECIFIED_LABEL}]

    if dimension == "tipo_contrato":
        out = []
        for value in _as_list(source.get("tipoContrato")):
            text = str(value or "").strip()
            if text:
                out.append({"id": text, "label": text})
        return out or [{"id": UNSPECIFIED_LABEL, "label": UNSPECIFIED_LABEL}]

    if dimension == "pme":
        out = []
        for value in _as_list(source.get("adjudicatarioPMEs")):
            text = str(value or "").strip()
            if text:
                out.append({"id": text, "label": text})
        return out or [{"id": UNSPECIFIED_LABEL, "label": UNSPECIFIED_LABEL}]

    return []


def _graph_add_node(
    nodes: Dict[str, Dict[str, Any]],
    descriptions: Dict[str, Dict[str, int]],
    dimension: str,
    item: Dict[str, Any],
    value: float,
) -> str:
    """Acumula um nó (contagem + valor) e devolve o seu id único."""
    node_id = f"{dimension}|{item['id']}"
    node = nodes.get(node_id)
    if node is None:
        node = nodes[node_id] = {
            "id": node_id,
            "key": item["id"],
            "label": item.get("label") or item["id"],
            "dimension": dimension,
            "type": GRAPH_DIMENSIONS[dimension]["type"],
            "role": GRAPH_DIMENSIONS[dimension]["label"],
            "count": 0,
            "total_value": 0.0,
        }
    node["count"] += 1
    node["total_value"] += value
    description = item.get("description")
    if description:
        bucket = descriptions.setdefault(node_id, {})
        bucket[description] = bucket.get(description, 0) + 1
    return node_id


def _graph_add_edge(
    edges: Dict[str, Dict[str, Any]],
    source: str,
    target: str,
    value: float,
    directed: bool,
) -> None:
    """Acumula uma aresta; em grafos não dirigidos os extremos são normalizados."""
    if not directed and target < source:
        source, target = target, source
    key = f"{source}->{target}"
    edge = edges.get(key)
    if edge is None:
        edge = edges[key] = {"source": source, "target": target, "count": 0, "value": 0.0}
    edge["count"] += 1
    edge["value"] += value


def _aggregate_dimension_buckets(
    client: Elasticsearch,
    query: Dict[str, Any],
    target: str,
    metric: str,
    size: int,
    with_description: bool,
) -> Optional[Dict[str, Any]]:
    """Agrega uma dimensão em termos (exato sobre todos os contratos filtrados)."""
    spec = _GRAPH_AGG_FIELDS.get(target)
    if not spec:
        return None

    field = spec["field"] or ""
    runtime: Optional[Dict[str, Any]] = None
    if spec["nested"] is None:
        resolved = _resolve_agg_target(client, field)
        field = resolved["field"]
        runtime = resolved.get("runtime")

    order: Dict[str, Any] = {"valor": "desc"} if metric == "valor" else {"_count": "desc"}
    bucket_aggs: Dict[str, Any] = {}
    if spec["nested"]:
        bucket_aggs["valor"] = {
            "reverse_nested": {},
            "aggs": {"total": {"sum": {"field": "precoContratual"}}},
        }
    else:
        bucket_aggs["valor"] = {"sum": {"field": "precoContratual"}}
    if spec["label"]:
        bucket_aggs["rotulo"] = {"terms": {"field": spec["label"], "size": 1}}
    if with_description and spec["nested"] == "cpv":
        # `cpv.description` é texto (fielddata desativada): só é recolhido quando há
        # poucos buckets, para não devolver milhares de documentos.
        bucket_aggs["amostra"] = {"top_hits": {"size": 1, "_source": ["cpv"]}}

    terms_agg: Dict[str, Any] = {
        "terms": {"field": field, "size": size, "order": order},
        "aggs": bucket_aggs,
    }
    if spec.get("missing"):
        # Contratos sem valor no campo formam o grupo "Não especificado".
        terms_agg["terms"]["missing"] = UNSPECIFIED_LABEL
    agg_body: Dict[str, Any] = (
        {"nested": {"path": spec["nested"]}, "aggs": {"buckets": terms_agg}}
        if spec["nested"]
        else terms_agg
    )

    body: Dict[str, Any] = {
        "size": 0,
        "track_total_hits": True,
        "query": query,
        "aggs": {"dim": agg_body, "total_value": {"sum": {"field": "precoContratual"}}},
    }
    if runtime:
        body["runtime_mappings"] = runtime

    resp = client.search(index=CONTRACTS_INDEX, body=body)
    node = resp["aggregations"]["dim"]
    if spec["nested"]:
        node = node["buckets"]
    total_block = resp.get("hits", {}).get("total") or {}
    return {
        "buckets": node.get("buckets", []),
        "other_doc_count": node.get("sum_other_doc_count", 0),
        "documents_matching": total_block.get("value", 0) if isinstance(total_block, dict) else 0,
        "documents_value": resp["aggregations"]["total_value"].get("value") or 0.0,
    }


def aggregate_graph_nodes(
    client: Elasticsearch,
    query: Dict[str, Any],
    dimension: str,
    metric: str,
    limit: int,
    max_buckets: int = GRAPH_MAX_AGG_BUCKETS,
) -> Optional[Dict[str, Any]]:
    """Grafo de um nível calculado por agregações: exato sobre TODOS os contratos.

    Devolve `None` quando a dimensão não é agregável (ex.: concorrentes), para o
    chamador fazer a varredura por documento.
    """
    targets = ["adjudicante", "adjudicatario"] if dimension == "entidade" else [dimension]
    if not targets or any(target not in _GRAPH_AGG_FIELDS for target in targets):
        return None

    requested = limit if limit else max_buckets
    size = max(10, min(requested * (2 if len(targets) > 1 else 1), max_buckets))
    with_description = size <= 400
    use_prefix = dimension in ("cpv_classe", "cpv_divisao")
    prefix_size = 4 if dimension == "cpv_classe" else 2

    aggregated: Dict[str, Dict[str, Any]] = {}
    other_doc_count = 0
    documents_matching = 0
    documents_value = 0.0

    for target in targets:
        result = _aggregate_dimension_buckets(client, query, target, metric, size, with_description)
        if result is None:
            return None
        other_doc_count += result["other_doc_count"]
        documents_matching = max(documents_matching, result["documents_matching"])
        documents_value = max(documents_value, result["documents_value"])

        for bucket in result["buckets"]:
            raw_key = str(bucket["key"])
            if not raw_key:
                if not spec.get("missing"):
                    continue
                raw_key = UNSPECIFIED_LABEL
            if raw_key == "N/A":
                continue
            label = raw_key
            description = ""
            rotulo = bucket.get("rotulo", {}).get("buckets") or []
            if rotulo:
                label = str(rotulo[0]["key"])
            if use_prefix:
                digits = re.sub(r"\D", "", raw_key)
                if len(digits) < prefix_size:
                    continue
                key = digits[:prefix_size]
                label = f"CPV {key}"
                samples = (bucket.get("amostra", {}).get("hits", {}).get("hits") or [])
                if samples:
                    for entry in _as_list((samples[0].get("_source") or {}).get("cpv")):
                        if not isinstance(entry, dict):
                            continue
                        code = re.sub(r"\D", "", str(entry.get("code") or ""))
                        if code.startswith(key):
                            description = str(entry.get("description") or "").strip()
                            if description:
                                break
            elif dimension == "regiao":
                key = raw_key.split(" - ")[0].strip() or raw_key
                label = raw_key
            elif dimension == "ano":
                key = raw_key
                label = raw_key
            else:
                key = raw_key

            value = bucket.get("valor")
            value = value.get("total", {}).get("value") if isinstance(value, dict) and "total" in value else value
            value = value.get("value") if isinstance(value, dict) else value
            entry = aggregated.get(key)
            if entry is None:
                entry = aggregated[key] = {
                    "id": f"{dimension}|{key}",
                    "key": key,
                    "label": label,
                    "dimension": dimension,
                    "type": GRAPH_DIMENSIONS[dimension]["type"],
                    "role": GRAPH_DIMENSIONS[dimension]["label"],
                    "count": 0,
                    "total_value": 0.0,
                }
            entry["count"] += int(bucket.get("doc_count") or 0)
            entry["total_value"] += float(value or 0)
            if use_prefix and description and " — " not in entry["label"]:
                entry["label"] = f"{key} — {description}"

    metric_key = "total_value" if metric == "valor" else "count"
    ordered = sorted(aggregated.values(), key=lambda node: node.get(metric_key) or 0, reverse=True)
    kept = ordered[:limit] if limit else ordered
    kept_value = sum(node["total_value"] for node in kept)
    kept_count = sum(node["count"] for node in kept)

    notes = ["Valores exatos para todos os contratos que correspondem aos filtros (sem amostragem)."]
    if len(ordered) > len(kept):
        notes.append(f"Mostrados {len(kept)} de {len(ordered)} nós agregados.")
    if other_doc_count:
        notes.append("Existem agrupamentos além dos apresentados (limite de buckets do Elasticsearch).")
    if use_prefix and not with_description and len(kept) > 400:
        notes.append("Descrições CPV omitidas acima de 400 nós.")

    return {
        "nodes": kept,
        "edges": [],
        "meta": {
            "dimension_a": dimension,
            "dimension_b": None,
            "metric": metric,
            "mode": "exato",
            "complete": len(ordered) <= len(kept) and other_doc_count == 0,
            "sample_order": "exato",
            "sample_limit": None,
            "documents_scanned": documents_matching,
            "documents_matching": documents_matching,
            "scanned_value": round(documents_value, 2),
            "nodes_total": len(ordered),
            "edges_total": 0,
            "kept_nodes": len(kept),
            "kept_edges": 0,
            "omitted_edges": 0,
            "coverage_value_share": round(kept_value / documents_value, 4) if documents_value else None,
            "coverage_count_share": None if not documents_matching else round(kept_count / max(documents_matching, 1), 4),
            "directed": False,
            "limits": {
                "max_scan": GRAPH_MAX_SCAN,
                "max_nodes": GRAPH_MAX_NODES,
                "max_edges": GRAPH_MAX_EDGES,
                "max_buckets": max_buckets,
            },
            "notes": notes,
            "filters": {"query": None},
        },
    }


def _resolve_dimension_spec(client: Elasticsearch, dimension: str) -> Optional[Dict[str, Any]]:
    """Resolve o campo agregável de uma dimensão (campo/subcampo/runtime) ou None."""
    spec = _GRAPH_AGG_FIELDS.get(dimension)
    if not spec:
        return None
    resolved = dict(spec)
    if spec["nested"] is None:
        target = _resolve_agg_target(client, spec["field"] or "")
        resolved["field"] = target["field"]
        resolved["runtime"] = target.get("runtime")
    return resolved


def _terms_block(spec: Dict[str, Any], metric: str, size: int, with_label: bool) -> Dict[str, Any]:
    """Bloco de agregação de termos com contagem de contratos e soma de valor."""
    order: Dict[str, Any] = {"valor": "desc"} if metric == "valor" else {"_count": "desc"}
    aggs: Dict[str, Any] = {}
    if spec["nested"]:
        aggs["valor"] = {"reverse_nested": {}, "aggs": {"total": {"sum": {"field": "precoContratual"}}}}
    else:
        aggs["valor"] = {"sum": {"field": "precoContratual"}}
    if with_label and spec.get("label"):
        aggs["rotulo"] = {"terms": {"field": spec["label"], "size": 1}}
    if with_label and spec.get("nested") == "cpv" and size <= 400:
        # `cpv.description` é texto (fielddata desativada): recolhido só com poucos buckets.
        aggs["amostra"] = {"top_hits": {"size": 1, "_source": ["cpv"]}}
    block: Dict[str, Any] = {
        "terms": {"field": spec["field"], "size": size, "order": order},
        "aggs": aggs,
    }
    if spec.get("missing"):
        # Contratos sem valor no campo passam a formar o grupo "Não especificado".
        block["terms"]["missing"] = UNSPECIFIED_LABEL
    if spec["nested"]:
        return {"nested": {"path": spec["nested"]}, "aggs": {"buckets": block}}
    return block


def _graph_key_for(dimension: str, raw_key: str) -> Optional[str]:
    """Normaliza a chave de um valor agregado (prefixo CPV, código NUTS) — igual em nós e arestas."""
    if dimension in ("cpv_classe", "cpv_divisao"):
        size = 4 if dimension == "cpv_classe" else 2
        digits = re.sub(r"\D", "", raw_key)
        return digits[:size] if len(digits) >= size else None
    if dimension == "regiao":
        return raw_key.split(" - ")[0].strip() or raw_key
    return raw_key


def _descriptions_from_bucket(bucket: Dict[str, Any], key: str) -> str:
    """Extrai a descrição CPV (top_hits) correspondente ao prefixo do bucket."""
    samples = bucket.get("amostra", {}).get("hits", {}).get("hits") or []
    for sample in samples:
        for entry in _as_list((sample.get("_source") or {}).get("cpv")):
            if not isinstance(entry, dict):
                continue
            code = re.sub(r"\D", "", str(entry.get("code") or ""))
            if code.startswith(key):
                description = str(entry.get("description") or "").strip()
                if description:
                    return description
    return ""


def _extract_buckets(node: Any) -> List[Dict[str, Any]]:
    """Extrai a lista de buckets de um bloco de termos (aceita wrappers de `nested`)."""
    for _hop in range(3):
        if isinstance(node, dict) and isinstance(node.get("buckets"), dict):
            node = node["buckets"]
            continue
        break
    if isinstance(node, dict):
        node = node.get("buckets")
    return node if isinstance(node, list) else []


def _bucket_value(bucket: Dict[str, Any]) -> float:
    value = bucket.get("valor")
    if isinstance(value, dict) and "total" in value and isinstance(value["total"], dict):
        value = value["total"].get("value")
    elif isinstance(value, dict):
        value = value.get("value")
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _nodes_from_buckets(
    block: Dict[str, Any],
    dimension: str,
    spec: Dict[str, Any],
    total: Dict[str, Dict[str, Any]],
) -> None:
    """Acumula buckets de termos no dicionário de nós (chave, rótulo, contagem, valor)."""
    buckets = block.get("buckets") if spec.get("nested") else block
    buckets = _extract_buckets(buckets)
    use_prefix = dimension in ("cpv_classe", "cpv_divisao")
    prefix_size = 4 if dimension == "cpv_classe" else 2

    for bucket in buckets:
        raw_key = str(bucket.get("key"))
        if raw_key == "N/A":
            continue
        if not raw_key:
            # Campo presente mas vazio: conta como "Não especificado".
            if not spec.get("missing"):
                continue
            raw_key = UNSPECIFIED_LABEL
        key = _graph_key_for(dimension, raw_key)
        if not key:
            continue
        label = raw_key
        rotulo = (bucket.get("rotulo") or {}).get("buckets") or []
        if rotulo:
            label = str(rotulo[0]["key"])
        if use_prefix:
            label = f"CPV {key}" if dimension == "cpv_divisao" else key
            description = _descriptions_from_bucket(bucket, key)
            if description and dimension == "cpv_classe":
                label = f"{key} — {description}"
        elif dimension == "regiao":
            label = raw_key

        node = total.get(key)
        if node is None:
            node = total[key] = {
                "id": f"{dimension}|{key}",
                "key": key,
                "label": label,
                "dimension": dimension,
                "type": GRAPH_DIMENSIONS[dimension]["type"],
                "role": GRAPH_DIMENSIONS[dimension]["label"],
                "count": 0,
                "total_value": 0.0,
            }
        node["count"] += int(bucket.get("doc_count") or 0)
        node["total_value"] += _bucket_value(bucket)


def aggregate_graph_edges(
    client: Elasticsearch,
    query: Dict[str, Any],
    dimension_a: str,
    dimension_b: str,
    metric: str,
    limit: int,
    edge_limit: int,
) -> Optional[Dict[str, Any]]:
    """Grafo de dois níveis exato (todos os contratos) por agregações.

    Corre três agregações no mesmo pedido: nós do lado A, nós do lado B (ambas
    exatas) e os pares A→B. Devolve `None` quando alguma dimensão não é agregável.
    """
    spec_a = _resolve_dimension_spec(client, dimension_a)
    spec_b = _resolve_dimension_spec(client, dimension_b)
    if not spec_a or not spec_b:
        return None

    node_size = min(limit or GRAPH_MAX_AGG_BUCKETS, GRAPH_MAX_AGG_BUCKETS)
    pair_budget = max(5, GRAPH_AGG_BUCKET_BUDGET // max(node_size, 1))
    pair_size = max(5, min(edge_limit or 200, pair_budget))

    edges_agg = _terms_block(spec_a, metric, node_size, with_label=False)
    inner = _terms_block(spec_b, metric, pair_size, with_label=False)
    if spec_a["nested"]:
        # `reverse_nested` volta ao documento pai: é aí que a dimensão B tem de viver.
        edges_agg["aggs"]["buckets"]["aggs"]["valor"]["aggs"]["links"] = inner
    else:
        edges_agg["aggs"]["links"] = inner

    runtime_mappings: Dict[str, Any] = {}
    for spec in (spec_a, spec_b):
        if spec.get("runtime"):
            runtime_mappings.update(spec["runtime"])

    body: Dict[str, Any] = {
        "size": 0,
        "track_total_hits": True,
        "query": query,
        "aggs": {
            "nodes_a": _terms_block(spec_a, metric, node_size, with_label=True),
            "nodes_b": _terms_block(spec_b, metric, node_size, with_label=True),
            "edges": edges_agg,
            "total_value": {"sum": {"field": "precoContratual"}},
        },
    }
    if runtime_mappings:
        body["runtime_mappings"] = runtime_mappings

    try:
        resp = client.search(index=CONTRACTS_INDEX, body=body)
    except Exception:
        # Por exemplo, acima do teto de buckets: o chamador cai para a varredura.
        return None
    aggregations = resp["aggregations"]

    nodes_a: Dict[str, Dict[str, Any]] = {}
    nodes_b: Dict[str, Dict[str, Any]] = {}
    _nodes_from_buckets(aggregations["nodes_a"], dimension_a, spec_a, nodes_a)
    _nodes_from_buckets(aggregations["nodes_b"], dimension_b, spec_b, nodes_b)

    metric_key = "total_value" if metric == "valor" else "count"
    ordered_a = sorted(nodes_a.values(), key=lambda node: node.get(metric_key) or 0, reverse=True)
    ordered_b = sorted(nodes_b.values(), key=lambda node: node.get(metric_key) or 0, reverse=True)
    kept_a = ordered_a[:limit] if limit else ordered_a
    kept_b = ordered_b[:limit] if limit else ordered_b
    kept_ids = {node["id"] for node in kept_a} | {node["id"] for node in kept_b}

    edges: Dict[str, Dict[str, Any]] = {}
    edges_block = aggregations["edges"]
    a_buckets = _extract_buckets(edges_block.get("buckets") if spec_a["nested"] else edges_block)
    for a_bucket in a_buckets:
        a_key = _graph_key_for(dimension_a, str(a_bucket.get("key")))
        if not a_key:
            continue
        a_id = f"{dimension_a}|{a_key}"
        if a_id not in kept_ids:
            continue
        links = a_bucket["valor"].get("links") if spec_a["nested"] else a_bucket.get("links")
        if not links:
            continue
        for b_bucket in _extract_buckets(links):
            b_key = _graph_key_for(dimension_b, str(b_bucket.get("key")))
            if not b_key:
                continue
            b_id = f"{dimension_b}|{b_key}"
            if b_id not in kept_ids:
                continue
            key = f"{a_id}->{b_id}"
            edge = edges.get(key)
            if edge is None:
                edge = edges[key] = {"source": a_id, "target": b_id, "count": 0, "value": 0.0}
            edge["count"] += int(b_bucket.get("doc_count") or 0)
            edge["value"] += _bucket_value(b_bucket)

    edge_metric = "value" if metric == "valor" else "count"
    ordered_edges = sorted(edges.values(), key=lambda edge: edge.get(edge_metric) or 0, reverse=True)
    dropped_edges = max(0, len(ordered_edges) - edge_limit) if edge_limit else 0
    kept_edges = ordered_edges[:edge_limit] if edge_limit else ordered_edges

    total_value = aggregations["total_value"].get("value") or 0.0
    total_block = resp.get("hits", {}).get("total") or {}
    documents_matching = total_block.get("value", 0) if isinstance(total_block, dict) else 0
    kept_value = sum(node["total_value"] for node in kept_a)
    kept_count = sum(node["count"] for node in kept_a)

    notes = ["Valores exatos para todos os contratos que correspondem aos filtros (sem amostragem)."]
    if len(ordered_a) > len(kept_a) or len(ordered_b) > len(kept_b):
        notes.append(
            f"Mostrados {len(kept_a)} nós de {len(ordered_a)} no lado A e "
            f"{len(kept_b)} de {len(ordered_b)} no lado B."
        )
    if pair_size < (edge_limit or 200):
        notes.append(
            f"Cada nó mostra até {pair_size} ligações por pedido de agregação "
            "(aumente as arestas ou reduza os nós para ver pares adicionais)."
        )
    if dropped_edges:
        notes.append(f"{dropped_edges} arestas omitidas por limite (aumente 'arestas' ou reduza os nós).")

    return {
        "nodes": kept_a + kept_b,
        "edges": kept_edges,
        "meta": {
            "dimension_a": dimension_a,
            "dimension_b": dimension_b,
            "metric": metric,
            "mode": "exato",
            "complete": len(ordered_a) <= len(kept_a) and len(ordered_b) <= len(kept_b) and not dropped_edges,
            "sample_order": "exato",
            "sample_limit": None,
            "documents_scanned": documents_matching,
            "documents_matching": documents_matching,
            "scanned_value": round(total_value, 2),
            "nodes_total": len(ordered_a) + len(ordered_b),
            "edges_total": len(ordered_edges),
            "kept_nodes": len(kept_a) + len(kept_b),
            "kept_edges": len(kept_edges),
            "omitted_edges": dropped_edges,
            "coverage_value_share": round(kept_value / total_value, 4) if total_value else None,
            "coverage_count_share": round(kept_count / max(documents_matching, 1), 4) if documents_matching else None,
            "directed": True,
            "limits": {
                "max_scan": GRAPH_MAX_SCAN,
                "max_nodes": GRAPH_MAX_NODES,
                "max_edges": GRAPH_MAX_EDGES,
                "max_buckets": GRAPH_MAX_AGG_BUCKETS,
            },
            "notes": notes,
            "filters": {"query": None},
        },
    }


def build_contract_graph(
    dimension_a: str,
    dimension_b: Optional[str] = None,
    metric: str = "valor",
    mode: str = "auto",
    q: Optional[str] = None,
    year: Optional[int] = None,
    region: Optional[str] = None,
    cpv_code: Optional[str] = None,
    min_value: Optional[float] = None,
    max_value: Optional[float] = None,
    limit: int = 60,
    edge_limit: int = 400,
    sample: int = 3000,
    sample_order: str = "valor",
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Constrói um grafo de contratos segundo duas dimensões (nós e arestas).

    - `dimension_b` igual a `dimension_a` → rede de co-ocorrência (ex.: concorrentes
      que participam nos mesmos contratos).
    - `dimension_b` nulo → apenas nós (para treemaps, rankings e mapas).
    - `metric` decide que nós/arestas são mantidos nos limites pedidos; os dois
      valores (contratos e valor) são sempre devolvidos.
    - `mode`:
      - `exato`: sem amostragem. Com uma só dimensão usa agregações do Elasticsearch
        (todos os contratos que correspondem aos filtros); com arestas percorre todos
        os contratos até ao teto do servidor.
      - `amostra`: percorre apenas `sample` contratos (ordem `sample_order`).
      - `auto` (por omissão): `exato` quando não há dimensão B.
    - `limit`, `edge_limit` e `sample` aceitam 0 = "todos" (sujeito aos tetos
      `GRAPH_MAX_NODES`, `GRAPH_MAX_EDGES` e `GRAPH_MAX_SCAN`, devolvidos em `meta`).
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "nodes": [], "edges": []}
    if dimension_a not in GRAPH_DIMENSIONS:
        return {"error": f"Dimensão desconhecida: {dimension_a}", "nodes": [], "edges": []}
    if dimension_b and dimension_b not in GRAPH_DIMENSIONS:
        return {"error": f"Dimensão desconhecida: {dimension_b}", "nodes": [], "edges": []}

    dimension_b = dimension_b or None
    metric = metric if metric in ("valor", "contratos") else "valor"
    mode = mode if mode in ("auto", "exato", "amostra") else "auto"
    same_dimension = dimension_b == dimension_a

    query = _build_contract_query(
        q=q,
        year=year,
        region=region,
        cpv_code=cpv_code,
        min_price=min_value,
        max_price=max_value,
    )

    # Caminho exato (sem amostragem) para grafos de um só nível.
    if mode in ("auto", "exato") and not dimension_b:
        exact = aggregate_graph_nodes(
            client,
            query,
            dimension_a,
            metric,
            limit=0 if int(limit) <= 0 else max(2, min(int(limit), GRAPH_MAX_NODES)),
        )
        if exact is not None:
            exact["meta"]["filters"] = {
                "q": q,
                "year": year,
                "region": region,
                "cpv_code": cpv_code,
                "min_value": min_value,
                "max_value": max_value,
            }
            return exact

    # Caminho exato com arestas: agregações de dois níveis (todos os contratos).
    if mode in ("auto", "exato") and dimension_b and not same_dimension:
        exact_edges = aggregate_graph_edges(
            client,
            query,
            dimension_a,
            dimension_b,
            metric,
            limit=0 if int(limit) <= 0 else max(2, min(int(limit), GRAPH_MAX_NODES)),
            edge_limit=0 if int(edge_limit) <= 0 else max(0, min(int(edge_limit), GRAPH_MAX_EDGES)),
        )
        if exact_edges is not None:
            exact_edges["meta"]["filters"] = {
                "q": q,
                "year": year,
                "region": region,
                "cpv_code": cpv_code,
                "min_value": min_value,
                "max_value": max_value,
            }
            return exact_edges

    all_documents = int(sample) <= 0
    scan_ceiling = GRAPH_MAX_SCAN
    sample = scan_ceiling if all_documents else max(100, min(int(sample), scan_ceiling))
    limit = 0 if int(limit) <= 0 else max(2, min(int(limit), GRAPH_MAX_NODES))
    edge_limit = 0 if int(edge_limit) <= 0 else max(0, min(int(edge_limit), GRAPH_MAX_EDGES))
    page_size = 5000 if all_documents else min(1000, sample)

    if sample_order == "recentes":
        sort: List[Any] = [
            {"dataPublicacao": {"order": "desc", "unmapped_type": "date"}},
            {"idcontrato": {"order": "asc"}},
        ]
    else:
        sort = [
            {"precoContratual": {"order": "desc", "unmapped_type": "float"}},
            {"idcontrato": {"order": "asc"}},
        ]

    nodes: Dict[str, Dict[str, Any]] = {}
    edges: Dict[str, Dict[str, Any]] = {}
    descriptions: Dict[str, Dict[str, int]] = {}
    scanned = 0
    scanned_value = 0.0
    total_hits = 0
    scan_capped = False

    try:
        search_after: Optional[List[Any]] = None
        while all_documents or scanned < sample:
            remaining = scan_ceiling - scanned
            if remaining <= 0:
                scan_capped = True
                break
            page = min(page_size, remaining)
            body: Dict[str, Any] = {
                "size": page,
                "query": query,
                "sort": sort,
                "_source": _GRAPH_SOURCE_FIELDS,
                "track_total_hits": True,
            }
            if search_after:
                body["search_after"] = search_after
            resp = client.search(index=CONTRACTS_INDEX, body=body)
            hits = resp.get("hits", {}).get("hits", [])
            total_block = resp.get("hits", {}).get("total") or {}
            total_hits = total_block.get("value", total_hits) if isinstance(total_block, dict) else total_hits
            if not hits:
                break

            for hit in hits:
                source = hit.get("_source") or {}
                scanned += 1
                raw_value = source.get("precoContratual") or source.get("PrecoTotalEfetivo") or 0
                try:
                    value = float(raw_value)
                except (TypeError, ValueError):
                    value = 0.0
                scanned_value += value

                values_a = _dimension_values(source, dimension_a)
                if not values_a:
                    continue
                ids_a = list(
                    dict.fromkeys(
                        _graph_add_node(nodes, descriptions, dimension_a, item, value)
                        for item in values_a[:_GRAPH_MAX_VALUES_PER_DOC]
                    )
                )
                if not dimension_b:
                    continue
                if same_dimension:
                    # Co-ocorrência: liga todos os pares presentes no mesmo contrato.
                    for index, left in enumerate(ids_a):
                        for right in ids_a[index + 1:]:
                            _graph_add_edge(edges, left, right, value, directed=False)
                    continue
                values_b = _dimension_values(source, dimension_b)
                ids_b = list(
                    dict.fromkeys(
                        _graph_add_node(nodes, descriptions, dimension_b, item, value)
                        for item in values_b[:_GRAPH_MAX_VALUES_PER_DOC]
                    )
                )
                for left in ids_a:
                    for right in ids_b:
                        _graph_add_edge(edges, left, right, value, directed=True)

            if len(hits) < page:
                break
            last_sort = hits[-1].get("sort")
            if not last_sort:
                break
            search_after = last_sort
    except Exception as exc:
        return {"error": str(exc), "nodes": [], "edges": []}

    # Rótulo descritivo mais frequente (ex.: classe CPV "4521 — Construção de edifícios").
    for node_id, bucket in descriptions.items():
        node = nodes.get(node_id)
        if not node or not bucket:
            continue
        best = max(bucket.items(), key=lambda kv: kv[1])[0]
        if best:
            node["label"] = f"{node['key']} — {best}"

    metric_key = "total_value" if metric == "valor" else "count"
    scored_nodes = sorted(nodes.values(), key=lambda node: (node.get(metric_key) or 0), reverse=True)
    kept_nodes = scored_nodes[:limit] if limit else scored_nodes
    kept_ids = {node["id"] for node in kept_nodes}
    kept_edges = [
        edge for edge in edges.values() if edge["source"] in kept_ids and edge["target"] in kept_ids
    ]
    edge_metric = "value" if metric == "valor" else "count"
    kept_edges.sort(key=lambda edge: (edge.get(edge_metric) or 0), reverse=True)
    dropped_edges = max(0, len(kept_edges) - edge_limit) if edge_limit else 0
    if edge_limit:
        kept_edges = kept_edges[:edge_limit]

    # Cobertura: independentemente do lado, usa os nós do lado A para reportar
    # quanto do valor/contratos ficou representado.
    side_a = [node for node in nodes.values() if node["dimension"] == dimension_a]
    side_a_total_count = sum(node["count"] for node in side_a) or 0
    side_a_total_value = sum(node["total_value"] for node in side_a) or 0.0
    kept_a = [node for node in kept_nodes if node["dimension"] == dimension_a]
    kept_a_count = sum(node["count"] for node in kept_a)
    kept_a_value = sum(node["total_value"] for node in kept_a)

    sampled = scanned < total_hits or scan_capped
    complete = not sampled and len(kept_nodes) == len(nodes) and not dropped_edges

    notes = []
    if scan_capped:
        notes.append(
            f"Varredura limitada a {scanned} de {total_hits} contratos (teto do servidor: "
            f"{GRAPH_MAX_SCAN}). Aplique filtros (ano, região, valor mínimo) para reduzir o conjunto."
        )
    elif sampled:
        notes.append(
            f"Amostra de {scanned} de {total_hits} contratos "
            f"({'maior valor' if sample_order == 'valor' else 'mais recentes'}). "
            "Use o modo exato ou 'todos os contratos' para valores completos."
        )
    else:
        notes.append(f"Todos os {total_hits} contratos do filtro foram analisados (sem amostragem).")
    if len(nodes) > len(kept_nodes):
        notes.append(f"Mostrados {len(kept_nodes)} de {len(nodes)} nós agregados.")
    if dropped_edges:
        notes.append(f"{dropped_edges} arestas omitidas por limite.")
    if same_dimension:
        notes.append("Arestas representam co-ocorrência no mesmo contrato; o valor é o total desses contratos.")

    return {
        "nodes": kept_nodes,
        "edges": kept_edges,
        "meta": {
            "dimension_a": dimension_a,
            "dimension_b": dimension_b,
            "metric": metric,
            "mode": "varredura-total" if all_documents else "amostra",
            "complete": complete,
            "scan_capped": scan_capped,
            "sample_order": sample_order,
            "sample_limit": None if all_documents else sample,
            "documents_scanned": scanned,
            "documents_matching": total_hits,
            "scanned_value": round(scanned_value, 2),
            "nodes_total": len(nodes),
            "edges_total": len(edges),
            "kept_nodes": len(kept_nodes),
            "kept_edges": len(kept_edges),
            "omitted_edges": dropped_edges,
            "coverage_value_share": round(kept_a_value / side_a_total_value, 4) if side_a_total_value else None,
            "coverage_count_share": round(kept_a_count / side_a_total_count, 4) if side_a_total_count else None,
            "directed": bool(dimension_b) and not same_dimension,
            "limits": {
                "max_scan": GRAPH_MAX_SCAN,
                "max_nodes": GRAPH_MAX_NODES,
                "max_edges": GRAPH_MAX_EDGES,
            },
            "notes": notes,
            "filters": {
                "q": q,
                "year": year,
                "region": region,
                "cpv_code": cpv_code,
                "min_value": min_value,
                "max_value": max_value,
            },
        },
    }


def get_company_trademarks(
    company_nif: Optional[str] = None,
    company_name: Optional[str] = None,
    holder_name: Optional[str] = None,
    q: Optional[str] = None,
    size: int = 100,
    from_: int = 0,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Lê as marcas indexadas de uma empresa (por NIF, nome de empresa ou titular)."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "items": [], "total": 0}

    ensure_indices(client)

    should: List[Dict[str, Any]] = []
    if company_nif:
        should.append({"term": {"company_nif": str(company_nif)}})
    if company_name:
        should.append({"match_phrase": {"holder_name": company_name}})
        should.append({"match": {"company_name": company_name}})
    if holder_name:
        should.append({"match_phrase": {"holder_name": holder_name}})
    if q:
        should.append({"match": {"mark_name": q}})

    if not should:
        query: Dict[str, Any] = {"match_all": {}}
    else:
        query = {"bool": {"should": should, "minimum_should_match": 1}}

    try:
        resp = client.search(
            index=TRADEMARKS_INDEX,
            body={
                "query": query,
                "from": from_,
                "size": size,
                "track_total_hits": True,
                # Semelhança do titular primeiro (docs antigos ficam no fim), depois data.
                "sort": [
                    {"holder_similarity": {"order": "desc", "missing": "_last"}},
                    {"application_date": {"order": "desc", "missing": "_last"}},
                ],
            },
        )
        items = [{**hit["_source"], "doc_id": hit["_id"]} for hit in resp["hits"]["hits"]]
        return {
            "company_nif": company_nif,
            "company_name": company_name,
            "total": resp["hits"]["total"]["value"],
            "items": items,
            "from": from_,
            "size": size,
        }
    except Exception as exc:
        return {"error": str(exc), "items": [], "total": 0}


def search_trademarks(
    q: Optional[str] = None,
    holder_name: Optional[str] = None,
    nice_class: Optional[str] = None,
    mark_type: Optional[str] = None,
    current_phase: Optional[str] = None,
    size: int = 20,
    from_: int = 0,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Pesquisa global de marcas indexadas no Elasticsearch."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "items": [], "total": 0}

    ensure_indices(client)

    must: List[Dict[str, Any]] = []
    filters: List[Dict[str, Any]] = []
    if q:
        must.append({
            "multi_match": {
                "query": q,
                "fields": ["mark_name^3", "holder_name^2", "process_number"],
                "operator": "and",
            }
        })
    if holder_name:
        must.append({"match_phrase": {"holder_name": holder_name}})
    if nice_class:
        filters.append({"term": {"nice_classes": nice_class}})
    if mark_type:
        filters.append({"term": {"mark_type": mark_type}})
    if current_phase:
        filters.append({"term": {"current_phase": current_phase}})

    query: Dict[str, Any]
    if must or filters:
        query = {"bool": {}}
        if must:
            query["bool"]["must"] = must
        if filters:
            query["bool"]["filter"] = filters
    else:
        query = {"match_all": {}}

    try:
        resp = client.search(
            index=TRADEMARKS_INDEX,
            body={
                "query": query,
                "from": from_,
                "size": size,
                "track_total_hits": True,
                "sort": [
                    {"application_date": {"order": "desc", "missing": "_last"}},
                    "_score",
                ],
            },
        )
        items = [{**hit["_source"], "doc_id": hit["_id"], "relevance": hit.get("_score")} for hit in resp["hits"]["hits"]]
        return {"query": q, "total": resp["hits"]["total"]["value"], "items": items, "from": from_, "size": size}
    except Exception as exc:
        return {"error": str(exc), "items": [], "total": 0}


def get_company_firmas(
    company_nif: Optional[str] = None,
    company_name: Optional[str] = None,
    q: Optional[str] = None,
    size: int = 100,
    from_: int = 0,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Lê as firmas/nomes comerciais indexados de uma empresa (RNPC/PNS)."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "items": [], "total": 0}

    ensure_indices(client)

    should: List[Dict[str, Any]] = []
    if company_nif:
        should.append({"term": {"company_nif": str(company_nif)}})
        should.append({"term": {"nipc": str(company_nif)}})
    if company_name:
        should.append({"match": {"nome": company_name}})
        should.append({"term": {"search_query": company_name}})
    if q:
        should.append({"match": {"nome": q}})

    if not should:
        query: Dict[str, Any] = {"match_all": {}}
    else:
        query = {"bool": {"should": should, "minimum_should_match": 1}}

    try:
        resp = client.search(
            index=FIRMAS_INDEX,
            body={
                "query": query,
                "from": from_,
                "size": size,
                "track_total_hits": True,
                # Semelhança do nome primeiro, depois o score de confundibilidade do RNPC.
                "sort": [
                    {"name_similarity": {"order": "desc", "missing": "_last"}},
                    {"score": {"order": "desc", "missing": "_last"}},
                ],
            },
        )
        items = [{**hit["_source"], "doc_id": hit["_id"]} for hit in resp["hits"]["hits"]]
        return {
            "company_nif": company_nif,
            "company_name": company_name,
            "total": resp["hits"]["total"]["value"],
            "items": items,
            "from": from_,
            "size": size,
        }
    except Exception as exc:
        return {"error": str(exc), "items": [], "total": 0}


def search_firmas(
    q: Optional[str] = None,
    concelho: Optional[str] = None,
    cae: Optional[str] = None,
    situacao: Optional[str] = None,
    min_score: Optional[float] = None,
    size: int = 20,
    from_: int = 0,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Pesquisa firmas/nomes comerciais (RNPC) indexados no Elasticsearch."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "items": [], "total": 0}

    ensure_indices(client)

    must: List[Dict[str, Any]] = []
    filters: List[Dict[str, Any]] = []
    if q:
        must.append({"match": {"nome": {"query": q, "operator": "and"}}})
    if concelho:
        filters.append({"term": {"concelho": concelho}})
    if cae:
        filters.append({"term": {"cae_principal": cae}})
    if situacao:
        filters.append({"term": {"situacao": situacao}})
    if min_score is not None:
        filters.append({"range": {"score": {"gte": min_score}}})

    query: Dict[str, Any]
    if must or filters:
        query = {"bool": {}}
        if must:
            query["bool"]["must"] = must
        if filters:
            query["bool"]["filter"] = filters
    else:
        query = {"match_all": {}}

    try:
        resp = client.search(
            index=FIRMAS_INDEX,
            body={
                "query": query,
                "from": from_,
                "size": size,
                "track_total_hits": True,
                "sort": [{"score": {"order": "desc", "missing": "_last"}}, "_score"],
            },
        )
        items = [{**hit["_source"], "doc_id": hit["_id"]} for hit in resp["hits"]["hits"]]
        return {"query": q, "total": resp["hits"]["total"]["value"], "items": items, "from": from_, "size": size}
    except Exception as exc:
        return {"error": str(exc), "items": [], "total": 0}


# --- Cadastro de entidades do portal base (finance_entities) ---

def index_entities(
    docs: Iterable[Dict[str, Any]],
    chunk_size: int = 2000,
    max_records: Optional[int] = None,
    refresh: bool = False,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Indexa entidades normalizadas no índice ENTITIES_INDEX.

    Aceita qualquer iterável (por exemplo o gerador de ``iter_normalized_entities``),
    pelo que não é necessário carregar o ficheiro todo em memória. O ``_id`` é o NIF
    ou um hash do nome, garantindo reingestões idempotentes.
    """
    from api.entities_service import entity_doc_id

    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "indexed_count": 0, "total": 0}

    ensure_indices(client)

    indexed = 0
    errors = 0
    seen = 0
    buffer: List[Dict[str, Any]] = []

    try:
        for doc in docs:
            if max_records is not None and seen >= max_records:
                break
            seen += 1
            source = {k: v for k, v in doc.items() if not k.startswith("_")}
            source["ingested_at"] = _today()
            buffer.append({"_index": ENTITIES_INDEX, "_id": f"{ENTITIES_INDEX}:{entity_doc_id(doc)}", "_source": source})

            if len(buffer) >= chunk_size:
                success, errs = bulk(client, buffer, raise_on_error=False, stats_only=False)
                indexed += success
                errors += len(errs) if isinstance(errs, list) else 0
                buffer = []

        if buffer:
            success, errs = bulk(client, buffer, raise_on_error=False, stats_only=False)
            indexed += success
            errors += len(errs) if isinstance(errs, list) else 0

        if refresh:
            try:
                client.indices.refresh(index=ENTITIES_INDEX)
            except Exception:
                pass

        return {
            "index": ENTITIES_INDEX,
            "indexed_count": indexed,
            "total": seen,
            "errors": errors,
            "message": f"{indexed} entidades indexadas de {seen}",
        }
    except Exception as exc:
        return {"index": ENTITIES_INDEX, "error": str(exc), "indexed_count": indexed, "total": seen}


def search_entities(
    q: Optional[str] = None,
    country: Optional[str] = None,
    only_with_nif: Optional[bool] = None,
    min_contracts: Optional[int] = None,
    max_contracts: Optional[int] = None,
    min_value: Optional[float] = None,
    max_value: Optional[float] = None,
    role: Optional[str] = "all",
    sort_by: Optional[str] = "total_value",
    sort_order: Optional[str] = "desc",
    size: int = 20,
    from_: int = 0,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Pesquisa o cadastro de entidades com filtros e ordenação.

    ``role`` permite restringir a entidades que aparecem como adjudicante
    (``totAdjudicante``), adjudicatário (``totAdjudicatario``) ou ambos.
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "items": [], "total": 0}

    ensure_indices(client)

    must: List[Dict[str, Any]] = []
    filters: List[Dict[str, Any]] = []
    text_query: Optional[Dict[str, Any]] = None

    if q:
        term = q.strip()
        if term:
            # Combina: NIF exato, nome exato (frase) e correspondência incremental
            # por prefixo (edge-ngram), para que "SONAE" encontre "SONAECOM".
            text_query = {
                "bool": {
                    "should": [
                        {"term": {"nif": term}},
                        {"match_phrase": {"name": {"query": term, "boost": 5}}},
                        {"multi_match": {"query": term, "fields": ["name^3"], "operator": "and", "boost": 3}},
                        {"match": {"name.autocomplete": {"query": term, "boost": 1}}},
                    ],
                    "minimum_should_match": 1,
                }
            }
    if country:
        filters.append({"term": {"country": country}})
    if only_with_nif:
        filters.append({"term": {"has_nif": True}})
    if min_contracts is not None:
        filters.append({"range": {"contracts_count": {"gte": min_contracts}}})
    if max_contracts is not None:
        filters.append({"range": {"contracts_count": {"lte": max_contracts}}})
    if min_value is not None:
        filters.append({"range": {"total_value": {"gte": min_value}}})
    if max_value is not None:
        filters.append({"range": {"total_value": {"lte": max_value}}})
    if role == "adjudicante":
        filters.append({"range": {"as_adjudicante_count": {"gte": 1}}})
    elif role == "adjudicatario":
        filters.append({"range": {"as_adjudicatario_count": {"gte": 1}}})

    query: Dict[str, Any]
    if text_query or filters:
        query = {"bool": {}}
        if text_query:
            query["bool"]["must"] = [text_query]
        if filters:
            query["bool"]["filter"] = filters
    else:
        query = {"match_all": {}}

    allowed_sort = {
        "name", "contracts_count", "total_value", "as_adjudicante_value",
        "as_adjudicante_count", "as_adjudicatario_count",
    }
    sort_field = sort_by if sort_by in allowed_sort else "total_value"
    order = "asc" if (sort_order or "desc").lower() == "asc" else "desc"
    # Em empates ordena por nome para garantir paginação estável.
    sort_spec: List[Any] = [{sort_field: {"order": order}}, {"name.keyword": {"order": "asc"}}]

    try:
        resp = client.search(
            index=ENTITIES_INDEX,
            body={
                "query": query,
                "from": from_,
                "size": size,
                "track_total_hits": True,
                "sort": sort_spec,
            },
        )
        items = [{**hit["_source"], "doc_id": hit["_id"]} for hit in resp["hits"]["hits"]]
        return {
            "query": q,
            "total": resp["hits"]["total"]["value"],
            "items": items,
            "from": from_,
            "size": size,
        }
    except Exception as exc:
        return {"error": str(exc), "items": [], "total": 0}


def get_entity_stats(es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Estatísticas agregadas do cadastro de entidades (totais, países, com/sem NIF)."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}

    ensure_indices(client)

    try:
        resp = client.search(
            index=ENTITIES_INDEX,
            body={
                "size": 0,
                "track_total_hits": True,
                "aggs": {
                    "with_nif": {"filter": {"term": {"has_nif": True}}},
                    "without_nif": {"filter": {"term": {"has_nif": False}}},
                    "countries": {
                        "terms": {"field": "country", "size": 15, "order": {"_count": "desc"}},
                        "aggs": {"value": {"sum": {"field": "total_value"}}},
                    },
                    "total_value": {"sum": {"field": "total_value"}},
                    "total_contracts": {"sum": {"field": "contracts_count"}},
                    "as_adjudicante": {"filter": {"range": {"as_adjudicante_count": {"gte": 1}}}},
                    "as_adjudicatario": {"filter": {"range": {"as_adjudicatario_count": {"gte": 1}}}},
                },
            },
        )
        aggs = resp["aggregations"]
        countries = [
            {
                "country": b["key"],
                "count": b["doc_count"],
                "total_value": round(b.get("value", {}).get("value") or 0.0, 2),
            }
            for b in aggs.get("countries", {}).get("buckets", [])
        ]
        return {
            "total": resp["hits"]["total"]["value"],
            "with_nif": aggs.get("with_nif", {}).get("doc_count", 0),
            "without_nif": aggs.get("without_nif", {}).get("doc_count", 0),
            "total_value": round(aggs.get("total_value", {}).get("value") or 0.0, 2),
            "total_contracts": int(aggs.get("total_contracts", {}).get("value") or 0),
            "adjudicante_count": aggs.get("as_adjudicante", {}).get("doc_count", 0),
            "adjudicatario_count": aggs.get("as_adjudicatario", {}).get("doc_count", 0),
            "countries": countries,
        }
    except Exception as exc:
        return {"error": str(exc)}


def get_entity_by_nif(nif: str, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Devolve o registo do cadastro de entidades para um NIF."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}

    ensure_indices(client)

    try:
        resp = client.search(
            index=ENTITIES_INDEX,
            body={"query": {"bool": {"should": [{"term": {"nif": nif}}, {"term": {"_id": f"{ENTITIES_INDEX}:{nif}"}}], "minimum_should_match": 1}}, "size": 1},
        )
        hits = resp["hits"]["hits"]
        if not hits:
            return {"nif": nif, "error": "Entidade não encontrada no cadastro"}
        return {"nif": nif, **hits[0]["_source"], "doc_id": hits[0]["_id"]}
    except Exception as exc:
        return {"error": str(exc)}


def list_entity_countries(es: Optional[Elasticsearch] = None) -> List[Dict[str, Any]]:
    """Lista os países presentes no cadastro de entidades, com contagem."""
    client = es or get_es_client()
    if not client:
        return []

    ensure_indices(client)

    try:
        resp = client.search(
            index=ENTITIES_INDEX,
            body={"size": 0, "aggs": {"countries": {"terms": {"field": "country", "size": 300, "order": {"_key": "asc"}}}}},
        )
        return [
            {"country": b["key"], "count": b["doc_count"]}
            for b in resp["aggregations"]["countries"]["buckets"]
            if b["key"]
        ]
    except Exception:
        return []

# --- Preferências do utilizador (favoritos, pastas e histórico do EmpresasIQ) ---
# Um único índice guarda o estado que antes vivia apenas no browser. Favoritos e pastas
# têm um documento por item (permite marcar/remover de forma isolada); o histórico é
# um documento único com a lista completa.

def _user_state_index() -> str:
    return USER_STATE_INDEX


def list_favorites(es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Lista os favoritos guardados no Elasticsearch (mais recentes primeiro)."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "items": []}

    ensure_indices(client)
    try:
        resp = client.search(
            index=USER_STATE_INDEX,
            body={
                "query": {"term": {"kind": "favorite"}},
                "size": 1000,
                "sort": [{"added_at": {"order": "desc", "missing": "_last"}}],
            },
        )
        items = []
        for hit in resp["hits"]["hits"]:
            src = hit["_source"]
            # No índice `kind` identifica o tipo de documento ("favorite"/"folder"/"history");
            # na resposta o campo `kind` é o tipo de ficha ("entity"/"contract").
            items.append(
                {
                    "kind": src.get("entry_kind"),
                    "id": src.get("id"),
                    "label": src.get("label") or src.get("id"),
                    "sublabel": src.get("sublabel"),
                    "value": src.get("value"),
                    "parties": src.get("parties") or [],
                    "added_at": src.get("added_at"),
                    "doc_id": hit["_id"],
                }
            )
        return {"items": items, "total": len(items)}
    except Exception as exc:
        return {"error": str(exc), "items": []}


def save_favorite(doc: Dict[str, Any], es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Guarda (ou substitui) um favorito. O id do documento é ``kind:id``."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}

    ensure_indices(client)
    kind = str(doc.get("kind") or "").strip()
    item_id = str(doc.get("id") or "").strip()
    if kind not in {"entity", "contract"} or not item_id:
        return {"error": "Favorito inválido: precisa de kind ('entity'|'contract') e id"}

    source = {
        "kind": "favorite",
        "entry_kind": kind,
        "id": item_id,
        "label": doc.get("label") or item_id,
        "sublabel": doc.get("sublabel"),
        "value": doc.get("value"),
        "parties": doc.get("parties") or [],
        "added_at": doc.get("added_at") or _today(),
    }
    try:
        client.index(index=USER_STATE_INDEX, id=f"favorite:{kind}:{item_id}", document=source, refresh=True)
        return {"ok": True, "id": item_id, "kind": kind}
    except Exception as exc:
        return {"error": str(exc)}


def delete_favorite(kind: str, item_id: str, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Remove um favorito."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}

    ensure_indices(client)
    try:
        client.delete(index=USER_STATE_INDEX, id=f"favorite:{kind}:{item_id}", ignore=[404], refresh=True)
        return {"ok": True}
    except Exception as exc:
        return {"error": str(exc)}


def clear_favorites(es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Remove todos os favoritos."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}

    ensure_indices(client)
    try:
        resp = client.delete_by_query(
            index=USER_STATE_INDEX,
            body={"query": {"term": {"kind": "favorite"}}},
            refresh=True,
            conflicts="proceed",
        )
        return {"ok": True, "deleted": resp.get("deleted", 0)}
    except Exception as exc:
        return {"error": str(exc)}


def get_workspace(es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Devolve o dossier (pastas) e o histórico guardados."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "folders": [], "history": []}

    ensure_indices(client)
    try:
        resp = client.search(
            index=USER_STATE_INDEX,
            body={"query": {"terms": {"kind": ["folder", "history"]}}, "size": 1000},
        )
        folders = []
        history = []
        for hit in resp["hits"]["hits"]:
            src = hit["_source"]
            if src.get("kind") == "folder":
                folders.append(
                    {
                        "id": src.get("folder_id") or hit["_id"],
                        "name": src.get("name") or "Pasta",
                        "createdAt": src.get("created_at"),
                        "items": src.get("items") or [],
                    }
                )
            elif src.get("kind") == "history":
                history = src.get("items") or []
        folders.sort(key=lambda folder: folder.get("createdAt") or "")
        return {"folders": folders, "history": history}
    except Exception as exc:
        return {"error": str(exc), "folders": [], "history": []}


def save_folder(folder: Dict[str, Any], es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Guarda (ou substitui) uma pasta do dossier com as suas fichas."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}

    ensure_indices(client)
    folder_id = str(folder.get("id") or "").strip()
    if not folder_id:
        return {"error": "Pasta inválida: falta o id"}

    source = {
        "kind": "folder",
        "folder_id": folder_id,
        "name": folder.get("name") or "Pasta",
        "created_at": folder.get("createdAt") or _today(),
        "items": folder.get("items") or [],
        "updated_at": _today(),
    }
    try:
        client.index(index=USER_STATE_INDEX, id=f"folder:{folder_id}", document=source, refresh=True)
        return {"ok": True, "id": folder_id}
    except Exception as exc:
        return {"error": str(exc)}


def delete_folder(folder_id: str, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Remove uma pasta do dossier."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}

    ensure_indices(client)
    try:
        client.delete(index=USER_STATE_INDEX, id=f"folder:{folder_id}", ignore=[404], refresh=True)
        return {"ok": True}
    except Exception as exc:
        return {"error": str(exc)}


def save_history(items: List[Dict[str, Any]], es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Guarda o histórico de fichas consultadas (documento único)."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}

    ensure_indices(client)
    try:
        client.index(
            index=USER_STATE_INDEX,
            id="history",
            document={"kind": "history", "items": items, "updated_at": _today()},
            refresh=True,
        )
        return {"ok": True, "count": len(items)}
    except Exception as exc:
        return {"error": str(exc)}
