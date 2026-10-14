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


def _access_token() -> tuple[Optional[str], Optional[str]]:
    """Devolve (token, erro). O erro distingue falta de credenciais de credenciais inválidas."""
    client_id = _client_id()
    secret = _client_secret()
    if not client_id or not secret:
        return None, "PayPal não configurado. Defina o client ID e o secret na administração."
    try:
        response = requests.post(
            f"{_base_url()}/v1/oauth2/token",
            headers={"Accept": "application/json", "Accept-Language": "en_US"},
            data={"grant_type": "client_credentials"},
            auth=(client_id, secret),
            timeout=20,
        )
        if response.status_code == 401:
            return None, "Credenciais PayPal inválidas (client ID/secret recusados)."
        response.raise_for_status()
        token = response.json().get("access_token")
        if not token:
            return None, "O PayPal não devolveu um token de acesso."
        return token, None
    except Exception as exc:  # noqa: BLE001
        logger.warning("PayPal token falhou: %s", exc)
        return None, f"Falha de comunicação com o PayPal: {exc}"


def _first_link(data: Dict[str, Any], rel: str) -> Optional[str]:
    for link in data.get("links") or []:
        if str(link.get("rel")) == rel:
            href = link.get("href")
            if href:
                return str(href)
    return None


def create_order(payment_id: str, amount: float, return_url: str = "", cancel_url: str = "") -> Dict[str, Any]:
    """Cria uma ordem PayPal e devolve o id e a URL de aprovação.

    Usa o fluxo clássico de redirecionamento (sem SDK no browser): o cliente é
    enviado para `approval_url`, aprova no PayPal e regressa a `return_url`, onde
    a ordem é capturada.
    """
    token, error = _access_token()
    if not token:
        return {"ok": False, "configured": False, "error": error}
    payload: Dict[str, Any] = {
        "intent": "CAPTURE",
        "purchase_units": [
            {
                "reference_id": payment_id,
                "amount": {"currency_code": "EUR", "value": f"{float(amount):.2f}"},
            }
        ],
    }
    if return_url or cancel_url:
        context: Dict[str, Any] = {"brand_name": "IQ OS", "user_action": "PAY_NOW"}
        if return_url:
            context["return_url"] = return_url
        if cancel_url:
            context["cancel_url"] = cancel_url
        payload["application_context"] = context
    try:
        response = requests.post(
            f"{_base_url()}/v2/checkout/orders",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
            },
            json=payload,
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()
        order_id = data.get("id")
        if not order_id:
            return {"ok": False, "configured": True, "error": "O PayPal não devolveu o id da ordem."}
        return {
            "ok": True,
            "configured": True,
            "id": order_id,
            "approval_url": _first_link(data, "approve") or _first_link(data, "payer-action"),
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("PayPal create order falhou: %s", exc)
        return {"ok": False, "configured": True, "error": f"PayPal recusou a ordem: {exc}"}


def capture_order(order_id: str) -> Dict[str, Any]:
    """Captura uma ordem PayPal."""
    token, error = _access_token()
    if not token:
        return {"ok": False, "error": error}
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
