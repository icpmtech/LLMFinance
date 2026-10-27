"""Apoio ao cliente: persistência da conversa e WebSocket do visitante.

Os testes usam o Elasticsearch local (o mesmo de `finance_users`). Sem ele
ficam *skip*; a validação do widget/HTML vive em `test_support_publico.py`.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Optional

import pytest

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from api import support_service as support  # noqa: E402
from api.elasticsearch_client import get_es_client  # noqa: E402


def _es_disponivel() -> bool:
    try:
        client = get_es_client()
        return bool(client and client.ping())
    except Exception:  # noqa: BLE001
        return False


pytestmark = pytest.mark.skipif(not _es_disponivel(), reason="Elasticsearch local indisponível")


def _limpar(visitor_id: str, session_id: Optional[str] = None) -> None:
    es = support._client()
    try:
        if session_id:
            for index, query in (
                (support.SUPPORT_MESSAGES_INDEX, {"term": {"session_id": session_id}}),
                (support.SUPPORT_TICKETS_INDEX, {"term": {"session_id": session_id}}),
                (support.SUPPORT_FORM_RESPONSES_INDEX, {"term": {"session_id": session_id}}),
                (support.SUPPORT_EVENTS_INDEX, {"term": {"session_id": session_id}}),
            ):
                try:
                    es.delete_by_query(index=index, query=query, refresh=True, conflicts="proceed")
                except Exception:  # noqa: BLE001
                    pass
            try:
                es.delete(index=support.SUPPORT_SESSIONS_INDEX, id=session_id, refresh=True)
            except Exception:  # noqa: BLE001
                pass
        try:
            es.delete(index=support.SUPPORT_VISITORS_INDEX, id=visitor_id, refresh=True)
        except Exception:  # noqa: BLE001
            pass
    finally:
        support.reset_rate_limits()


def test_conversa_completa_ate_ao_ticket() -> None:
    support.reset_schema_cache()
    support.reset_rate_limits()
    visitor_id = support.new_visitor_id()
    context = {"url": "https://sabemos.studio/precos", "title": "Preços", "ip": "203.0.113.9"}
    session_id: Optional[str] = None
    try:
        support.touch_visitor(
            visitor_id,
            profile={"name": "Ana Silva", "email": "ana@exemplo.pt", "organization": "Exemplo Lda"},
            context=context,
        )
        document, created = support.create_session(
            visitor_id,
            profile={"name": "Ana Silva", "email": "ana@exemplo.pt"},
            context=context,
        )
        session_id = document["session_id"]
        assert created is True
        assert document["status"] == support.STATUS_WAITING
        assert document["visitor_name"] == "Ana Silva"
        assert document["context"]["url"].endswith("/precos")
        assert document["pages"][0]["url"].endswith("/precos")

        again, created_again = support.create_session(visitor_id, context=context)
        assert created_again is False
        assert again["session_id"] == session_id

        support.add_message(
            session_id,
            author_type=support.AUTHOR_VISITOR,
            author_id=visitor_id,
            author_name="Ana Silva",
            body="Boa tarde, preciso de ajuda com o plano.",
        )
        current = support.get_session(session_id)
        assert current is not None
        assert current["unread_operator"] == 1
        assert current["message_count"] == 1

        claimed = support.claim_session(session_id, "op_1", "Operador")
        assert claimed["status"] == support.STATUS_ACTIVE
        assert claimed["assigned_operator_id"] == "op_1"

        support.add_message(
            session_id,
            author_type=support.AUTHOR_OPERATOR,
            author_id="op_1",
            author_name="Operador",
            body="Boa tarde! Em que posso ajudar?",
        )
        messages = support.list_messages(session_id)
        assert [message["author_type"] for message in messages] == ["visitor", "operator"]
        assert messages[1]["body"].startswith("Boa tarde!")

        support.mark_read(session_id, "operator")
        assert support.get_session(session_id)["unread_operator"] == 0  # type: ignore[index]

        note = support.add_message(
            session_id,
            author_type=support.AUTHOR_OPERATOR,
            author_id="op_1",
            author_name="Operador",
            body="Cliente elegível para desconto.",
            internal=True,
        )
        visible = support.list_messages(session_id, include_internal=False)
        assert note["id"] not in {message["id"] for message in visible}

        link = support.send_rich_message(
            session_id,
            kind=support.MESSAGE_LINK,
            payload={"url": "https://sabemos.studio/precos", "title": "Tabela de preços", "description": "Planos e condições."},
            author_id="op_1",
            author_name="Operador",
        )
        assert link["kind"] == support.MESSAGE_LINK
        assert link["payload"]["url"].endswith("/precos")
        with pytest.raises(support.SupportError):
            support.send_rich_message(
                session_id,
                kind=support.MESSAGE_LINK,
                payload={"url": "javascript:alert(1)", "title": "Mau"},
                author_id="op_1",
                author_name="Operador",
            )

        report = support.send_rich_message(
            session_id,
            kind=support.MESSAGE_REPORT,
            payload={
                "report_id": "abc123",
                "title": "Relatório de concorrência",
                "summary": "Resumo do setor.",
                "url": "/site/documento/abc123",
                "free": True,
            },
            author_id="op_1",
            author_name="Operador",
        )
        assert report["kind"] == support.MESSAGE_REPORT
        assert report["payload"]["report_id"] == "abc123"

        form = support.send_rich_message(
            session_id,
            kind=support.MESSAGE_FORM,
            payload={
                "title": "Dados de contacto",
                "description": "Para falarmos consigo.",
                "fields": [
                    {"label": "Nome", "type": "text", "required": True},
                    {"label": "Email", "type": "email", "required": True},
                    {"label": "Mensagem", "type": "textarea", "required": False},
                ],
            },
            author_id="op_1",
            author_name="Operador",
        )
        assert form["kind"] == support.MESSAGE_FORM
        assert form["payload"]["fields"][0]["key"] == "nome"
        with pytest.raises(support.SupportError):
            support.submit_form_response(session_id, form["id"], {"nome": "Ana"}, visitor_id=visitor_id)

        answered, response = support.submit_form_response(
            session_id,
            form["id"],
            {"nome": "Ana Silva", "email": "ana@exemplo.pt", "mensagem": "Quero o plano anual."},
            visitor_id=visitor_id,
            visitor_name="Ana Silva",
            visitor_email="ana@exemplo.pt",
        )
        assert response["values"]["nome"] == "Ana Silva"
        assert answered["form_response"]["response_id"] == response["id"]
        with pytest.raises(support.SupportError):
            support.submit_form_response(session_id, form["id"], {"nome": "Ana"}, visitor_id=visitor_id)
        assert support.list_form_responses(session_id)[0]["id"] == response["id"]

        ticket = support.create_ticket(
            session_id,
            subject="Alterar plano",
            description="Quero mudar para o plano anual.",
            category="Faturação",
            priority="high",
        )
        assert ticket["status"] == support.TICKET_OPEN
        assert ticket["priority"] == "high"
        assert support.list_session_tickets(session_id)[0]["id"] == ticket["id"]

        rated = support.rate_session(session_id, 5, "Rápido e claro")
        assert rated["rating"] == 5

        closed = support.close_session(
            session_id,
            actor_type=support.AUTHOR_OPERATOR,
            actor_id="op_1",
            actor_name="Operador",
            reason="Resolvido",
        )
        assert closed["status"] == support.STATUS_CLOSED

        found = support.list_sessions(q="Ana")
        assert any(item["session_id"] == session_id for item in found["items"])

        events = support.list_events(session_id=session_id, size=50)
        kinds = {event["kind"] for event in events["items"]}
        assert {"session.created", "session.claimed", "ticket.created", "session.rated", "session.closed"} <= kinds
    finally:
        _limpar(visitor_id, session_id)


def test_websocket_do_visitante_entrega_a_mensagem() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api.support_routes import admin_router, router

    support.reset_schema_cache()
    support.reset_rate_limits()

    app = FastAPI()
    app.include_router(router)
    app.include_router(admin_router)
    client = TestClient(app)

    bootstrap = client.post("/support/visitors", json={"profile": {"name": "Rui"}})
    assert bootstrap.status_code == 200, bootstrap.text
    token = bootstrap.json()["token"]
    visitor_id = bootstrap.json()["visitor_id"]

    started = client.post(
        "/support/sessions",
        headers={"X-Support-Token": token},
        json={"profile": {"name": "Rui"}, "context": {"url": "https://sabemos.studio/empresas"}},
    )
    assert started.status_code == 200, started.text
    session_id = started.json()["session"]["id"]

    try:
        with client.websocket_connect(
            f"/support/ws?role=visitor&token={token}&session_id={session_id}"
        ) as websocket:
            ready = websocket.receive_json()
            assert ready["type"] == "ready"
            assert ready["session"]["id"] == session_id

            websocket.send_json({"type": "message", "body": "Olá por WebSocket", "client_id": "c1"})
            event = websocket.receive_json()
            assert event["type"] == "message.created"
            assert event["message"]["body"] == "Olá por WebSocket"
            assert event["message"]["author_type"] == "visitor"

        stored = support.list_messages(session_id)
        assert any(message["body"] == "Olá por WebSocket" for message in stored)
    finally:
        _limpar(visitor_id, session_id)


def test_formulario_publico_guarda_resposta_no_elastic() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api.support_routes import admin_router, router

    support.reset_schema_cache()
    support.reset_rate_limits()
    app = FastAPI()
    app.include_router(router)
    app.include_router(admin_router)
    client = TestClient(app)

    bootstrap = client.post("/support/visitors", json={"profile": {"name": "Formulário"}})
    token = bootstrap.json()["token"]
    visitor_id = bootstrap.json()["visitor_id"]
    started = client.post(
        "/support/sessions",
        headers={"X-Support-Token": token},
        json={"context": {"url": "https://sabemos.studio/empresas"}},
    )
    session_id = started.json()["session"]["id"]
    try:
        form = support.send_rich_message(
            session_id,
            kind=support.MESSAGE_FORM,
            payload={
                "title": "Pedido de contacto",
                "fields": [
                    {"label": "Nome", "type": "text", "required": True},
                    {"label": "Email", "type": "email", "required": True},
                ],
            },
            author_id="op_1",
            author_name="Operador",
        )
        submitted = client.post(
            f"/support/sessions/{session_id}/forms/{form['id']}",
            headers={"X-Support-Token": token},
            json={"values": {"nome": "Rita", "email": "rita@exemplo.pt"}},
        )
        assert submitted.status_code == 200, submitted.text
        body = submitted.json()
        assert body["message"]["kind"] == support.MESSAGE_FORM
        assert body["message"]["form_response"]["values"]["nome"] == "Rita"
        assert body["response"]["form_id"] == form["payload"]["form_id"]

        stored = support.list_form_responses(session_id)
        assert stored and stored[0]["values"]["email"] == "rita@exemplo.pt"

        missing = client.post(
            f"/support/sessions/{session_id}/forms/{form['id']}",
            headers={"X-Support-Token": token},
            json={"values": {"nome": "Rita"}},
        )
        assert missing.status_code == 409
    finally:
        _limpar(visitor_id, session_id)


def test_config_do_widget_tem_limites_e_disponibilidade() -> None:
    config = support.widget_config(0)
    assert config["title"]
    assert config["quick_replies"]
    assert config["ticket_categories"]
    assert config["limits"]["message"] > 0
    assert isinstance(config["available"], bool)

    with_operator = support.widget_config(2)
    assert with_operator["available"] is True
    assert with_operator["operators_online"] == 2
