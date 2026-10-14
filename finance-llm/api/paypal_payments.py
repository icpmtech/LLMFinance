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

# A captura concluída é o que confirma o dinheiro; a ordem aprovada ainda não é pagamento.
_EVENTOS_RELEVANTES = ("PAYMENT.CAPTURE.COMPLETED",)


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
    """Extrai o id da ordem de uma notificação do PayPal.

    Não valida nada — quem chama tem de confirmar a assinatura primeiro
    (`verify_webhook`). O evento relevante é `PAYMENT.CAPTURE.COMPLETED`: a
    captura traz o id da ordem em `supplementary_data.related_ids.order_id`.
    """
    try:
        event_type = payload.get("event_type")
        if event_type not in _EVENTOS_RELEVANTES:
            return {"ok": False, "event_type": event_type, "error": "Evento ignorado."}
        resource = payload.get("resource") or {}
        relacionadas = (resource.get("supplementary_data") or {}).get("related_ids") or {}
        order_id = relacionadas.get("order_id") or resource.get("id")
        return {
            "ok": bool(order_id),
            "event_type": event_type,
            "order_id": order_id,
            "error": None if order_id else "A notificação não identifica a ordem.",
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("Notificação PayPal inválida: %s", exc)
        return {"ok": False, "error": str(exc)}


def verify_webhook(payload: Dict[str, Any], headers: Dict[str, str]) -> Optional[str]:
    """Confirma a autenticidade da notificação junto do PayPal. `None` se for autêntica.

    Sem isto, qualquer pedido HTTP que imitasse o corpo de uma notificação ativava
    uma subscrição sem pagamento — o webhook é público e não tem sessão.
    """
    webhook_id = (service_keys.resolver("paypal_webhook_id") or "").strip()
    if not webhook_id:
        return (
            "Webhook do PayPal recusado: o id do webhook não está configurado "
            "(PayPal — id do webhook, na administração)."
        )
    obrigatorios = (
        "paypal-transmission-id",
        "paypal-transmission-time",
        "paypal-cert-url",
        "paypal-auth-algo",
        "paypal-transmission-sig",
    )
    normalizados = {str(k).lower(): v for k, v in (headers or {}).items()}
    faltam = [nome for nome in obrigatorios if not normalizados.get(nome)]
    if faltam:
        return f"Webhook do PayPal recusado: faltam cabeçalhos de autenticação ({', '.join(faltam)})."

    token, error = _access_token()
    if not token:
        return f"Webhook do PayPal por verificar: {error}"
    try:
        response = requests.post(
            f"{_base_url()}/v1/notifications/verify-webhook-signature",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
            json={
                "transmission_id": normalizados["paypal-transmission-id"],
                "transmission_time": normalizados["paypal-transmission-time"],
                "cert_url": normalizados["paypal-cert-url"],
                "auth_algo": normalizados["paypal-auth-algo"],
                "transmission_sig": normalizados["paypal-transmission-sig"],
                "webhook_id": webhook_id,
                "webhook_event": payload,
            },
            timeout=20,
        )
        response.raise_for_status()
        estado = (response.json() or {}).get("verification_status")
        if estado != "SUCCESS":
            return f"Webhook do PayPal recusado: a assinatura não foi confirmada ({estado})."
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("Verificação de webhook PayPal falhou: %s", exc)
        return f"Webhook do PayPal por verificar: falha de comunicação ({exc})."
