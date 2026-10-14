"""Integração PayPal para pagamentos de subscrição.

Cria ordens e captura pagamentos. As credenciais PayPal são lidas das
definições geridas pela administração (service_keys).
"""
from __future__ import annotations

import base64
import logging
from typing import Any, Dict, Optional

import requests

from api import service_keys

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api-m.sandbox.paypal.com"


def _client_id() -> Optional[str]:
    return service_keys.resolver("paypal_client_id")


def _client_secret() -> Optional[str]:
    return service_keys.resolver("paypal_client_secret")


def _base_url() -> str:
    return service_keys.resolver("paypal_base_url") or DEFAULT_BASE_URL


def _access_token() -> Optional[str]:
    client_id = _client_id()
    secret = _client_secret()
    if not client_id or not secret:
        return None
    try:
        response = requests.post(
            f"{_base_url()}/v1/oauth2/token",
            headers={"Accept": "application/json", "Accept-Language": "en_US"},
            data={"grant_type": "client_credentials"},
            auth=(client_id, secret),
            timeout=20,
        )
        response.raise_for_status()
        return response.json().get("access_token")
    except Exception as exc:  # noqa: BLE001
        logger.warning("PayPal token falhou: %s", exc)
        return None


def create_order(payment_id: str, amount: float) -> Dict[str, Any]:
    """Cria uma ordem PayPal e devolve o id para o frontend capturar."""
    token = _access_token()
    if not token:
        return {"ok": False, "error": "PayPal não configurado."}
    try:
        response = requests.post(
            f"{_base_url()}/v2/checkout/orders",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
            },
            json={
                "intent": "CAPTURE",
                "purchase_units": [
                    {
                        "reference_id": payment_id,
                        "amount": {"currency_code": "EUR", "value": f"{float(amount):.2f}"},
                    }
                ],
            },
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()
        return {"ok": True, "id": data.get("id")}
    except Exception as exc:  # noqa: BLE001
        logger.warning("PayPal create order falhou: %s", exc)
        return {"ok": False, "error": str(exc)}


def capture_order(order_id: str) -> Dict[str, Any]:
    """Captura uma ordem PayPal."""
    token = _access_token()
    if not token:
        return {"ok": False, "error": "PayPal não configurado."}
    try:
        response = requests.post(
            f"{_base_url()}/v2/checkout/orders/{order_id}/capture",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
            },
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()
        purchase = (data.get("purchase_units") or [{}])[0]
        payment_id = purchase.get("reference_id")
        return {"ok": True, "id": order_id, "payment_id": payment_id, "status": data.get("status")}
    except Exception as exc:  # noqa: BLE001
        logger.warning("PayPal capture falhou: %s", exc)
        return {"ok": False, "error": str(exc)}


def handle_webhook(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Processa webhook PayPal (evento CAPTURE.COMPLETED)."""
    try:
        event_type = payload.get("event_type")
        if event_type != "CAPTURE.COMPLETED":
            return {"ok": False, "error": "Evento ignorado."}
        resource = payload.get("resource", {})
        purchase = (resource.get("purchase_units") or [{}])[0]
        return {"ok": True, "payment_id": purchase.get("reference_id")}
    except Exception as exc:  # noqa: BLE001
        logger.warning("Webhook PayPal inválido: %s", exc)
        return {"ok": False, "error": str(exc)}
