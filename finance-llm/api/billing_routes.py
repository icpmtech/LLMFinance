"""Rotas de billing e subscrições (`/billing/*`)."""
from __future__ import annotations

import logging
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from api import auth_service as auth
from api import billing_service as billing
from api.auth_routes import CurrentSession, require_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/billing", tags=["billing"])

Session = Annotated[CurrentSession, Depends(require_session)]


class SubscribePayload(BaseModel):
    plan_id: str = Field(..., description="basic | pro | enterprise")
    interval: str = Field("monthly", description="monthly | yearly")
    method: str = Field(..., description="mbway | transfer | stripe | paypal")


class PhonePayload(BaseModel):
    payment_id: str
    phone: str


class ConfirmPayload(BaseModel):
    payment_id: str


class CapturePayload(BaseModel):
    order_id: str


@router.get("/plans")
def list_plans() -> Dict[str, Any]:
    """Lista os planos disponíveis."""
    return {"plans": billing.list_plans()}


@router.get("/subscription")
def get_subscription(session: Session) -> Dict[str, Any]:
    """Subscrição e histórico de pagamentos do utilizador autenticado."""
    user = auth.get_user_by_id(session.user.id)
    if not user:
        raise HTTPException(status_code=404, detail="Conta não encontrada.")
    return {
        "subscription": billing.get_user_subscription(user),
        "payments": billing.list_payments(session.user.id),
    }


@router.post("/subscribe")
def subscribe(payload: SubscribePayload, session: Session) -> Dict[str, Any]:
    """Inicia um pagamento para subscrever/renovar um plano."""
    try:
        result = billing.create_payment(
            session.user.id,
            plan_id=payload.plan_id,
            interval=payload.interval,
            method=payload.method,
        )
    except auth.AuthError as error:
        raise HTTPException(status_code=error.status_code, detail=error.message) from error
    return result


@router.post("/mbway/request")
def mbway_request(payload: PhonePayload, session: Session) -> Dict[str, Any]:
    """Envia pedido MB Way para um pagamento pendente."""
    try:
        return billing.mbway_payment_request(session.user.id, payload.payment_id, payload.phone)
    except auth.AuthError as error:
        raise HTTPException(status_code=error.status_code, detail=error.message) from error


@router.post("/mbway/status")
def mbway_status(payload: ConfirmPayload, session: Session) -> Dict[str, Any]:
    """Consulta estado MB Way e ativa a subscrição se pago."""
    try:
        return billing.mbway_payment_status(session.user.id, payload.payment_id)
    except auth.AuthError as error:
        raise HTTPException(status_code=error.status_code, detail=error.message) from error


@router.post("/paypal/capture")
def paypal_capture(payload: CapturePayload, session: Session) -> Dict[str, Any]:
    """Captura uma ordem PayPal e ativa a subscrição."""
    try:
        from api import paypal_payments

        result = paypal_payments.capture_order(payload.order_id)
        if result.get("ok") and result.get("payment_id"):
            billing.confirm_payment(session.user.id, result["payment_id"])
        return result
    except auth.AuthError as error:
        raise HTTPException(status_code=error.status_code, detail=error.message) from error


@router.post("/confirm")
def confirm(payload: ConfirmPayload, session: Session) -> Dict[str, Any]:
    """Confirma manualmente um pagamento (admin ou transferência confirmada)."""
    try:
        return billing.confirm_payment(session.user.id, payload.payment_id, admin_confirmed=True)
    except auth.AuthError as error:
        raise HTTPException(status_code=error.status_code, detail=error.message) from error


@router.post("/webhooks/stripe")
async def stripe_webhook(request: Request) -> Dict[str, Any]:
    """Webhook assíncrono do Stripe."""
    try:
        payload = dict(await request.json())
    except Exception:
        raise HTTPException(status_code=400, detail="Payload inválido.")
    return billing.webhook_stripe(payload)


@router.post("/webhooks/paypal")
async def paypal_webhook(request: Request) -> Dict[str, Any]:
    """Webhook assíncrono do PayPal."""
    try:
        payload = dict(await request.json())
    except Exception:
        raise HTTPException(status_code=400, detail="Payload inválido.")
    return billing.webhook_paypal(payload)
