"""Índices e *mappings* do módulo de apoio ao cliente.

Fica separado de `api/es/mappings.py` para o serviço de apoio poder garantir
**só** os seus seis índices no primeiro pedido, sem verificar os restantes
(o arranque da conversa não pode esperar pela lista completa de índices).
"""
from __future__ import annotations

from typing import Any, Dict

from elasticsearch import Elasticsearch

from api.es.indices import (
    SUPPORT_EVENTS_INDEX,
    SUPPORT_FORM_RESPONSES_INDEX,
    SUPPORT_MESSAGES_INDEX,
    SUPPORT_OPERATORS_INDEX,
    SUPPORT_SESSIONS_INDEX,
    SUPPORT_TICKETS_INDEX,
    SUPPORT_VISITORS_INDEX,
)

SUPPORT_INDEX_MAPPINGS: Dict[str, Dict[str, Any]] = {
    SUPPORT_VISITORS_INDEX: {
        "properties": {
            "visitor_id": {"type": "keyword"},
            "user_id": {"type": "keyword"},
            "name": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 256}}},
            "email": {"type": "keyword"},
            "phone": {"type": "keyword"},
            "organization": {"type": "keyword"},
            "profile": {"type": "object", "enabled": False},
            "context": {"type": "object", "enabled": False},
            "first_page": {"type": "keyword", "ignore_above": 1024},
            "last_page": {"type": "keyword", "ignore_above": 1024},
            "sessions": {"type": "integer"},
            "created_at": {"type": "date"},
            "updated_at": {"type": "date"},
            "last_seen_at": {"type": "date"},
        }
    },
    SUPPORT_SESSIONS_INDEX: {
        "properties": {
            "session_id": {"type": "keyword"},
            "visitor_id": {"type": "keyword"},
            "user_id": {"type": "keyword"},
            "status": {"type": "keyword"},
            "visitor_name": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 256}}},
            "visitor_email": {"type": "keyword"},
            "assigned_operator_id": {"type": "keyword"},
            "assigned_operator_name": {"type": "keyword"},
            "subject": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 256}}},
            "tags": {"type": "keyword"},
            "visitor": {"type": "object", "enabled": False},
            "context": {"type": "object", "enabled": False},
            "pages": {"type": "object", "enabled": False},
            "unread_operator": {"type": "integer"},
            "unread_visitor": {"type": "integer"},
            "message_count": {"type": "integer"},
            "rating": {"type": "integer"},
            "rating_comment": {"type": "text"},
            "created_at": {"type": "date"},
            "updated_at": {"type": "date"},
            "last_message_at": {"type": "date"},
            "last_visitor_message_at": {"type": "date"},
            "last_operator_message_at": {"type": "date"},
            "last_seen_at": {"type": "date"},
            "closed_at": {"type": "date"},
        }
    },
    SUPPORT_MESSAGES_INDEX: {
        "properties": {
            "message_id": {"type": "keyword"},
            "session_id": {"type": "keyword"},
            "visitor_id": {"type": "keyword"},
            "author_type": {"type": "keyword"},
            "author_id": {"type": "keyword"},
            "author_name": {"type": "keyword"},
            "body": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
            "kind": {"type": "keyword"},
            "payload": {"type": "object", "enabled": False},
            "form_response": {"type": "object", "enabled": False},
            "client_id": {"type": "keyword"},
            "internal": {"type": "boolean"},
            "created_at": {"type": "date"},
        }
    },
    SUPPORT_FORM_RESPONSES_INDEX: {
        "properties": {
            "response_id": {"type": "keyword"},
            "form_id": {"type": "keyword"},
            "message_id": {"type": "keyword"},
            "session_id": {"type": "keyword"},
            "visitor_id": {"type": "keyword"},
            "visitor_name": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 256}}},
            "visitor_email": {"type": "keyword"},
            "title": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 256}}},
            "values": {"type": "object", "enabled": False},
            "submitted_at": {"type": "date"},
            "created_at": {"type": "date"},
        }
    },
    SUPPORT_TICKETS_INDEX: {
        "properties": {
            "ticket_id": {"type": "keyword"},
            "session_id": {"type": "keyword"},
            "visitor_id": {"type": "keyword"},
            "subject": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 256}}},
            "description": {"type": "text"},
            "status": {"type": "keyword"},
            "priority": {"type": "keyword"},
            "category": {"type": "keyword"},
            "requester": {"type": "object", "enabled": False},
            "assigned_operator_id": {"type": "keyword"},
            "assigned_operator_name": {"type": "keyword"},
            "notes": {"type": "object", "enabled": False},
            "created_at": {"type": "date"},
            "updated_at": {"type": "date"},
            "closed_at": {"type": "date"},
        }
    },
    SUPPORT_EVENTS_INDEX: {
        "properties": {
            "kind": {"type": "keyword"},
            "session_id": {"type": "keyword"},
            "ticket_id": {"type": "keyword"},
            "actor_type": {"type": "keyword"},
            "actor_id": {"type": "keyword"},
            "actor_name": {"type": "keyword"},
            "detail": {"type": "text"},
            "data": {"type": "object", "enabled": False},
            "created_at": {"type": "date"},
        }
    },
    SUPPORT_OPERATORS_INDEX: {
        "properties": {
            "operator_id": {"type": "keyword"},
            "name": {"type": "keyword"},
            "email": {"type": "keyword"},
            "status": {"type": "keyword"},
            "last_seen_at": {"type": "date"},
            "updated_at": {"type": "date"},
        }
    },
}


def ensure_support_indices(client: Elasticsearch) -> None:
    """Cria os índices do apoio que ainda não existam."""
    settings = {"number_of_shards": 1, "number_of_replicas": 0}
    for name, mappings in SUPPORT_INDEX_MAPPINGS.items():
        if client.indices.exists(index=name):
            continue
        try:
            client.indices.create(index=name, body={"mappings": mappings, "settings": settings})
        except Exception:  # noqa: BLE001 - outra instância pode ter criado entretanto
            pass
