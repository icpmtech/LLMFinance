"""Integração Stripe para pagamentos de subscrição.

Cria sessões de checkout e valida webhooks. As chaves Stripe são lidas das
mesmas definições geridas pela administração (service_keys).

Sem chave configurada, as funções devolvem erro limpo sem levantar exceções
que derrubem a API.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import time
from typing import Any, Dict, List, Optional

from api import service_keys

logger = logging.getLogger(__name__)

# O Stripe considera um evento expirado passados 5 minutos; a mesma janela evita
# que uma assinatura capturada há muito tempo continue a valer.
WEBHOOK_TOLERANCE_SECONDS = 300


def _app_url() -> str:
    from api.billing_service import PUBLIC_APP_URL

    return PUBLIC_APP_URL


def _api_key() -> Optional[str]:
    return service_keys.resolver("stripe_secret_key")


def _webhook_secret() -> Optional[str]:
    return service_keys.resolver("stripe_webhook_secret")


def _parse_signature(header: str) -> tuple[Optional[int], List[str]]:
    """Separa `t=…,v1=…,v1=…` no timestamp e nas assinaturas."""
    timestamp: Optional[int] = None
    assinaturas: List[str] = []
    for parte in (header or "").split(","):
        chave, _, valor = parte.strip().partition("=")
        if chave == "t":
            try:
                timestamp = int(valor)
            except ValueError:
                timestamp = None
        elif chave == "v1" and valor:
            assinaturas.append(valor)
    return timestamp, assinaturas


def verify_webhook(raw_body: bytes, signature_header: Optional[str], *, agora: Optional[int] = None) -> Optional[str]:
    """Valida a assinatura `Stripe-Signature` do corpo cru. `None` se for autêntica.

    Sem a verificação, qualquer pedido HTTP com o `payment_id` certo ativava uma
    subscrição sem pagamento — o webhook é um endpoint público e não tem sessão.
    """
    secret = _webhook_secret()
    if not secret:
        return (
            "Webhook do Stripe recusado: o segredo de assinatura não está configurado "
            "(Stripe — segredo de assinatura do webhook, na administração)."
        )
    if not signature_header:
        return "Webhook do Stripe recusado: falta o cabeçalho Stripe-Signature."

    timestamp, assinaturas = _parse_signature(signature_header)
    if timestamp is None or not assinaturas:
        return "Webhook do Stripe recusado: cabeçalho Stripe-Signature malformado."

    instante = int(time.time()) if agora is None else int(agora)
    if abs(instante - timestamp) > WEBHOOK_TOLERANCE_SECONDS:
        return "Webhook do Stripe recusado: assinatura fora do prazo de validade."

    esperado = hmac.new(secret.encode(), f"{timestamp}.".encode() + raw_body, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(esperado, candidata) for candidata in assinaturas):
        return "Webhook do Stripe recusado: assinatura inválida."
    return None


def create_checkout_session(
    payment_id: str,
    amount: float,
    plan_id: str,
    interval: str,
    user_id: str = "",
) -> Dict[str, Any]:
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
            metadata={"payment_id": payment_id, "plan_id": plan_id, "interval": interval, "user_id": user_id},
        )
        return {"ok": True, "configured": True, "id": session.id, "url": session.url}
    except Exception as exc:  # noqa: BLE001
        logger.warning("Stripe checkout falhou: %s", exc)
        return {"ok": False, "configured": True, "error": f"Stripe recusou o pedido: {exc}"}


def handle_webhook(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Extrai os identificadores de um evento `checkout.session.completed`.

    Não valida nada — quem chama tem de confirmar a assinatura primeiro
    (`verify_webhook`).
    """
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
