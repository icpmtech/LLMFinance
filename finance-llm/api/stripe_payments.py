"""Integração Stripe para pagamentos de subscrição.

Cria sessões de checkout e valida webhooks. As chaves Stripe são lidas das
mesmas definições geridas pela administração (service_keys).

Sem chave configurada, as funções devolvem erro limpo sem levantar exceções
que derrubem a API.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from api import service_keys

logger = logging.getLogger(__name__)


def _app_url() -> str:
    from api.billing_service import PUBLIC_APP_URL

    return PUBLIC_APP_URL


def _api_key() -> Optional[str]:
    return service_keys.resolver("stripe_secret_key")


def create_checkout_session(payment_id: str, amount: float, plan_id: str, interval: str) -> Dict[str, Any]:
    """Cria uma sessão Stripe Checkout para a subscrição."""
    key = _api_key()
    if not key:
        return {"ok": False, "configured": False, "error": "Stripe não configurado. Defina a secret key na administração."}
    try:
        import stripe  # type: ignore

        stripe.api_key = key
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[
                {
                    "price_data": {
                        "currency": "eur",
                        "product_data": {"name": f"IQ OS — Subscrição {plan_id} ({interval})"},
                        "unit_amount": int(round(float(amount) * 100)),
                    },
                    "quantity": 1,
                }
            ],
            mode="payment",
            success_url=f"{_app_url()}/settings?billing=success&payment_id={payment_id}",
            cancel_url=f"{_app_url()}/settings?billing=cancel&payment_id={payment_id}",
            metadata={"payment_id": payment_id, "plan_id": plan_id, "interval": interval},
        )
        return {"ok": True, "configured": True, "id": session.id, "url": session.url}
    except Exception as exc:  # noqa: BLE001
        logger.warning("Stripe checkout falhou: %s", exc)
        return {"ok": False, "configured": True, "error": f"Stripe recusou o pedido: {exc}"}


def handle_webhook(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Extrai o payment_id de um evento checkout.session.completed."""
    try:
        event_type = payload.get("type")
        if event_type != "checkout.session.completed":
            return {"ok": False, "error": "Evento ignorado."}
        session = payload.get("data", {}).get("object", {})
        metadata = session.get("metadata", {})
        return {
            "ok": True,
            "payment_id": metadata.get("payment_id"),
            "user_id": metadata.get("user_id"),
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("Webhook Stripe inválido: %s", exc)
        return {"ok": False, "error": str(exc)}
