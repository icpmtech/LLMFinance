"""Webhooks de pagamento (Stripe e PayPal).

O que se testa aqui é o que faltava: os webhooks são endpoints **públicos e sem
sessão**, e por isso a única coisa que os pode autorizar a ativar uma subscrição
é a assinatura do fornecedor. Sem esta verificação, um `POST` com o corpo certo
dava Enterprise de graça; com a verificação mal ligada, o webhook morria com
`KeyError` e nunca ativava nada — os dois casos estão cobertos abaixo.
"""
from __future__ import annotations

import hashlib
import hmac
import time

import pytest

from api import billing_service, paypal_payments, service_keys, stripe_payments


class _ClienteFalso:
    def __init__(self) -> None:
        self.documentos: dict = {}

    def exists(self, *, index: str, id: str) -> bool:  # noqa: A002 - API do Elasticsearch
        return id in self.documentos

    def get(self, *, index: str, id: str):  # noqa: A002
        return {"_source": self.documentos[id]}

    def index(self, *, index: str, id: str, document: dict, refresh: bool = False):  # noqa: A002
        self.documentos[id] = document
        return {"result": "created"}


def _sem_chaves_no_indice(monkeypatch) -> None:
    monkeypatch.setattr(service_keys, "_client", lambda: _ClienteFalso())
    monkeypatch.setattr(service_keys, "_do_env_file", lambda nomes: None)


# --------------------------------------------------------------------- Stripe


def _assinatura(secret: str, corpo: bytes, *, quando: int | None = None) -> str:
    instante = int(time.time()) if quando is None else quando
    mac = hmac.new(secret.encode(), f"{instante}.".encode() + corpo, hashlib.sha256).hexdigest()
    return f"t={instante},v1={mac}"


def test_stripe_webhook_recusa_sem_segredo_configurado(monkeypatch):
    """Sem `whsec_`, a plataforma recusa em vez de ativar por um pedido anónimo."""
    _sem_chaves_no_indice(monkeypatch)
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)

    resultado = billing_service.webhook_stripe(
        {"type": "checkout.session.completed", "data": {"object": {"metadata": {"payment_id": "p1", "user_id": "u1"}}}},
        b"{}",
        "t=1,v1=abc",
    )

    assert resultado["ok"] is False
    assert resultado["verified"] is False
    assert "segredo" in resultado["error"]


def test_stripe_webhook_recusa_assinatura_invalida(monkeypatch):
    _sem_chaves_no_indice(monkeypatch)
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_teste_local_nao_real")
    corpo = b'{"type":"checkout.session.completed"}'

    assert stripe_payments.verify_webhook(corpo, "t=1,v1=deadbeef") is not None
    assert stripe_payments.verify_webhook(corpo, None) is not None

    quando = int(time.time())
    valida = _assinatura("whsec_teste_local_nao_real", corpo, quando=quando)
    assert stripe_payments.verify_webhook(corpo, valida) is None


def test_stripe_webhook_recusa_assinatura_fora_do_prazo(monkeypatch):
    _sem_chaves_no_indice(monkeypatch)
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_teste_local_nao_real")
    corpo = b"{}"
    antiga = _assinatura("whsec_teste_local_nao_real", corpo, quando=int(time.time()) - 3600)

    erro = stripe_payments.verify_webhook(corpo, antiga)

    assert erro is not None
    assert "prazo" in erro


def test_stripe_webhook_verificado_ativa_subscricao(monkeypatch):
    """Com assinatura válida e pagamento conhecido, o webhook ativa a subscrição."""
    _sem_chaves_no_indice(monkeypatch)
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_teste_local_nao_real")
    corpo = b'{"type":"checkout.session.completed"}'

    confirmados: list = []
    monkeypatch.setattr(
        billing_service,
        "confirm_payment",
        lambda user_id, payment_id, **_: confirmados.append((user_id, payment_id)),
    )
    monkeypatch.setattr(
        stripe_payments,
        "handle_webhook",
        lambda payload: {"ok": True, "payment_id": "p1", "user_id": "u1"},
    )

    resultado = billing_service.webhook_stripe(
        {"type": "checkout.session.completed"}, corpo, _assinatura("whsec_teste_local_nao_real", corpo)
    )

    assert resultado == {"ok": True, "verified": True, "payment_id": "p1"}
    assert confirmados == [("u1", "p1")]


# --------------------------------------------------------------------- PayPal


def test_paypal_webhook_recusa_sem_id_de_webhook(monkeypatch):
    _sem_chaves_no_indice(monkeypatch)
    monkeypatch.delenv("PAYPAL_WEBHOOK_ID", raising=False)

    resultado = billing_service.webhook_paypal({"event_type": "PAYMENT.CAPTURE.COMPLETED"}, {})

    assert resultado["ok"] is False
    assert resultado["verified"] is False
    assert "webhook" in resultado["error"].lower()


def test_paypal_webhook_recusa_sem_cabecalhos_de_autenticacao(monkeypatch):
    _sem_chaves_no_indice(monkeypatch)
    monkeypatch.setenv("PAYPAL_WEBHOOK_ID", "WH-1")

    erro = paypal_payments.verify_webhook({"event_type": "PAYMENT.CAPTURE.COMPLETED"}, {})

    assert erro is not None
    assert "cabeçalhos" in erro


def test_paypal_webhook_le_o_id_da_ordem_da_captura():
    """O evento real é `PAYMENT.CAPTURE.COMPLETED` e o id vem em `related_ids`."""
    payload = {
        "event_type": "PAYMENT.CAPTURE.COMPLETED",
        "resource": {
            "id": "CAPTURE-1",
            "supplementary_data": {"related_ids": {"order_id": "ORDER-9"}},
        },
    }

    resultado = paypal_payments.handle_webhook(payload)

    assert resultado["ok"] is True
    assert resultado["order_id"] == "ORDER-9"

    assert paypal_payments.handle_webhook({"event_type": "CHECKOUT.ORDER.APPROVED"})["ok"] is False


def test_paypal_webhook_verificado_ativa_o_pagamento_da_ordem(monkeypatch):
    """O webhook não traz sessão: o dono do pagamento descobre-se pela ordem guardada."""
    monkeypatch.setattr(paypal_payments, "verify_webhook", lambda payload, headers: None)
    monkeypatch.setattr(
        paypal_payments,
        "handle_webhook",
        lambda payload: {"ok": True, "order_id": "ORDER-9"},
    )
    monkeypatch.setattr(
        billing_service,
        "_find_payment_by_order_id",
        lambda order_id, **_: {"user_id": "u7", "payment_id": "p7", "status": "pending"},
    )

    confirmados: list = []
    monkeypatch.setattr(
        billing_service,
        "confirm_payment",
        lambda user_id, payment_id, **_: confirmados.append((user_id, payment_id)),
    )

    resultado = billing_service.webhook_paypal({"event_type": "PAYMENT.CAPTURE.COMPLETED"}, {})

    assert resultado == {"ok": True, "verified": True, "payment_id": "p7"}
    assert confirmados == [("u7", "p7")]


def test_paypal_webhook_ignora_ordem_desconhecida(monkeypatch):
    """Uma ordem que não é nossa não ativa nada, mesmo com assinatura válida."""
    monkeypatch.setattr(paypal_payments, "verify_webhook", lambda payload, headers: None)
    monkeypatch.setattr(paypal_payments, "handle_webhook", lambda payload: {"ok": True, "order_id": "ALHEIA"})
    monkeypatch.setattr(billing_service, "_find_payment_by_order_id", lambda order_id, **_: None)

    chamado: list = []
    monkeypatch.setattr(
        billing_service, "confirm_payment", lambda *a, **k: chamado.append((a, k))
    )

    resultado = billing_service.webhook_paypal({"event_type": "PAYMENT.CAPTURE.COMPLETED"}, {})

    assert resultado["ok"] is True
    assert resultado["ignored"] is True
    assert chamado == []


def test_assinatura_do_stripe_aceita_varias_v1(monkeypatch):
    """Durante a rotação do segredo o Stripe manda mais do que uma assinatura."""
    _sem_chaves_no_indice(monkeypatch)
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_teste_local_nao_real")
    corpo = b'{"a":1}'
    instante = int(time.time())
    boa = hmac.new(b"whsec_teste_local_nao_real", f"{instante}.".encode() + corpo, hashlib.sha256).hexdigest()

    cabecalho = f"t={instante},v1=deadbeef,v1={boa}"

    assert stripe_payments.verify_webhook(corpo, cabecalho) is None


@pytest.mark.parametrize("cabecalho", ["", "lixo", "t=abc,v1=x", "v1=sem-timestamp"])
def test_assinatura_do_stripe_aceita_cabecalhos_malformados_com_erro(monkeypatch, cabecalho):
    _sem_chaves_no_indice(monkeypatch)
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_teste_local_nao_real")

    assert stripe_payments.verify_webhook(b"{}", cabecalho) is not None
