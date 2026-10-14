"""Billing e subscrições do IQ OS.

Define 3 planos incrementais (Básico, Profissional, Enterprise), cada um com
um conjunto de módulos incluídos. Guarda a subscrição ativa no documento do
utilizador (Elasticsearch) e fornece helpers para:

- listar planos e o plano atual;
- iniciar pagamentos (MB Way, transferência, Stripe, PayPal);
- registar pagamentos e ativar/renovar subscrições;
- verificar se um utilizador tem acesso a um módulo.

A cobrança funciona em ciclos mensais. Quando o pagamento é confirmado,
a subscrição fica ativa até `current_period_end`. Se o trial expirar sem
pagamento, a conta passa a `suspended` e só volta a `active` após pagamento.
"""
from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set

from api import auth_service as auth
from api import events_service as events
from api import notification_email
from api import reports_payments
from api import service_keys
from api.elasticsearch_client import AUTH_USERS_INDEX, get_es_client

logger = logging.getLogger(__name__)

PLAN_BASIC = "basic"
PLAN_PRO = "pro"
PLAN_ENTERPRISE = "enterprise"

CURRENCY = "EUR"

#: URL público da aplicação, usado nos retornos dos gateways (Stripe/PayPal).
PUBLIC_APP_URL = (os.getenv("PUBLIC_APP_URL") or "http://127.0.0.1:4180").rstrip("/")

PLANS: List[Dict[str, Any]] = [
    {
        "id": PLAN_BASIC,
        "name": "Básico",
        "price_monthly": 9.0,
        "price_yearly": 90.0,
        "modules": [
            "dashboard",
            "finder",
            "contracts",
            "contracts-es",
            "contracts-fr",
            "empresas",
            "pessoas",
            "search360",
        ],
        "description": "Acesso essencial a contratos, empresas e pesquisa.",
    },
    {
        "id": PLAN_PRO,
        "name": "Profissional",
        "price_monthly": 29.0,
        "price_yearly": 290.0,
        "modules": [
            "dashboard",
            "finder",
            "contracts",
            "contracts-es",
            "contracts-fr",
            "empresas",
            "pessoas",
            "search360",
            "mercado",
            "sentiment",
            "benchmark",
            "reports",
            "email",
            "rss",
        ],
        "description": "Inclui mercados, sentimento, benchmark e relatórios a pedido.",
    },
    {
        "id": PLAN_ENTERPRISE,
        "name": "Enterprise",
        "price_monthly": 79.0,
        "price_yearly": 790.0,
        "modules": [
            "dashboard",
            "finder",
            "contracts",
            "contracts-es",
            "contracts-fr",
            "empresas",
            "pessoas",
            "search360",
            "mercado",
            "sentiment",
            "benchmark",
            "reports",
            "email",
            "rss",
            "crm",
            "scraper",
            "social",
            "hermes",
            "jarvis",
            "world",
            "ontology",
            "gleif",
        ],
        "description": "Acesso total: IA, CRM, recolha automática e módulos avançados.",
    },
]

PLAN_BY_ID: Dict[str, Dict[str, Any]] = {plan["id"]: plan for plan in PLANS}

PAYMENT_METHODS = ["mbway", "transfer", "stripe", "paypal"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _plan_end(start: datetime, interval: str) -> datetime:
    if interval == "yearly":
        return start + timedelta(days=365)
    return start + timedelta(days=30)


def list_plans() -> List[Dict[str, Any]]:
    """Lista os planos disponíveis (sem dados sensíveis)."""
    return [
        {
            "id": plan["id"],
            "name": plan["name"],
            "price_monthly": plan["price_monthly"],
            "price_yearly": plan["price_yearly"],
            "modules": plan["modules"],
            "description": plan["description"],
        }
        for plan in PLANS
    ]


def get_user_subscription(user: Dict[str, Any]) -> Dict[str, Any]:
    """Devolve a subscrição atual de um utilizador."""
    subscription = user.get("subscription") or {}
    plan_id = subscription.get("plan_id") or PLAN_BASIC
    plan = PLAN_BY_ID.get(plan_id) or PLANS[0]
    now = datetime.now(timezone.utc)
    expires_at = subscription.get("current_period_end")
    is_active = user.get("status") == auth.USER_STATUS_ACTIVE
    try:
        expired = bool(expires_at) and datetime.fromisoformat(str(expires_at).replace("Z", "+00:00")) <= now
    except ValueError:
        expired = False
    return {
        "plan_id": plan_id,
        "plan": {
            "id": plan["id"],
            "name": plan["name"],
            "modules": plan["modules"],
        },
        "status": subscription.get("status") or ("active" if is_active else "inactive"),
        "current_period_start": subscription.get("current_period_start") or None,
        "current_period_end": expires_at,
        "trial_expires_at": user.get("trial_expires_at") or None,
        "is_active": is_active and not expired,
        "expired": expired,
        "payment_method": subscription.get("payment_method") or None,
    }


def _public_payment(payment: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": payment.get("id"),
        "plan_id": payment.get("plan_id"),
        "interval": payment.get("interval"),
        "amount": payment.get("amount"),
        "currency": payment.get("currency"),
        "method": payment.get("method"),
        "status": payment.get("status"),
        "created_at": payment.get("created_at"),
        "paid_at": payment.get("paid_at") or None,
    }


def list_payments(user_id: str) -> List[Dict[str, Any]]:
    """Histórico de pagamentos de um utilizador."""
    user = auth.get_user_by_id(user_id)
    if not user:
        return []
    payments = user.get("payments") or []
    if not isinstance(payments, list):
        return []
    return [_public_payment(payment) for payment in payments]


def list_pending_payments(limit: int = 100) -> List[Dict[str, Any]]:
    """Pagamentos por confirmar de todos os utilizadores (para a administração)."""
    es = get_es_client()
    if not es:
        return []
    try:
        resp = es.search(
            index=AUTH_USERS_INDEX,
            body={
                "query": {"exists": {"field": "payments"}},
                "size": max(1, min(limit, 500)),
                "_source": ["id", "email", "name", "status", "payments"],
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Não foi possível listar pagamentos pendentes: %s", exc)
        return []

    pending: List[Dict[str, Any]] = []
    for hit in resp.get("hits", {}).get("hits", []):
        source = hit.get("_source") or {}
        for payment in source.get("payments") or []:
            if not isinstance(payment, dict) or payment.get("status") != "pending":
                continue
            entry = _public_payment(payment)
            entry["user_id"] = source.get("id")
            entry["user_email"] = source.get("email")
            entry["user_name"] = source.get("name")
            entry["user_status"] = source.get("status")
            entry["reference_id"] = (payment.get("metadata") or {}).get("mbway_request_id")
            pending.append(entry)
    pending.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return pending[:limit]


def can_access_module(user: Dict[str, Any], module_id: str) -> bool:
    """True se o utilizador tiver um plano ativo que inclua o módulo.

    Os administradores têm sempre acesso a tudo — gerem a plataforma e não
    podem ficar bloqueados pelo próprio plano.
    """
    if (user.get("role") or "member") == "admin":
        return True
    status = user.get("status") or auth.USER_STATUS_ACTIVE
    if status != auth.USER_STATUS_ACTIVE:
        return False
    subscription = user.get("subscription") or {}
    plan_id = subscription.get("plan_id") or PLAN_BASIC
    plan = PLAN_BY_ID.get(plan_id)
    if not plan:
        return False
    allowed: Set[str] = set(plan.get("modules") or [])
    return module_id in allowed or "*" in allowed


def _upsert_subscription(user_id: str, patch: Dict[str, Any]) -> Dict[str, Any]:
    user = auth.get_user_by_id(user_id)
    if not user:
        raise auth.AuthError("Conta não encontrada.", status_code=404, code="not_found")
    key = auth.normalize_email(user.get("email") or "")
    from api.elasticsearch_client import AUTH_USERS_INDEX, get_es_client

    es = get_es_client()
    if not es:
        raise auth.AuthError("Base de dados indisponível.", status_code=503, code="es_unavailable")
    try:
        es.update(index=AUTH_USERS_INDEX, id=key, doc={"subscription": {**(user.get("subscription") or {}), **patch}, "updated_at": _now_iso()}, refresh=True)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Falha ao atualizar subscrição")
        raise auth.AuthError("Não foi possível guardar a subscrição.", status_code=502, code="es_error") from exc
    updated = {**user, "subscription": {**(user.get("subscription") or {}), **patch}}
    return auth.public_user(updated)


def _add_payment(user_id: str, payment: Dict[str, Any]) -> None:
    user = auth.get_user_by_id(user_id)
    if not user:
        return
    key = auth.normalize_email(user.get("email") or "")
    from api.elasticsearch_client import AUTH_USERS_INDEX, get_es_client

    es = get_es_client()
    if not es:
        return
    payments = list(user.get("payments") or [])
    payments.insert(0, payment)
    try:
        es.update(index=AUTH_USERS_INDEX, id=key, doc={"payments": payments, "updated_at": _now_iso()}, refresh=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Não foi possível registar pagamento: %s", exc)


def create_payment(user_id: str, *, plan_id: str, interval: str, method: str) -> Dict[str, Any]:
    """Inicia um pagamento. Devolve instruções/URLs para o frontend."""
    if plan_id not in PLAN_BY_ID:
        raise auth.AuthError("Plano inválido.", status_code=422, code="invalid_input")
    if interval not in {"monthly", "yearly"}:
        raise auth.AuthError("Intervalo inválido (use monthly ou yearly).", status_code=422, code="invalid_input")
    if method not in PAYMENT_METHODS:
        raise auth.AuthError("Método de pagamento inválido.", status_code=422, code="invalid_input")

    plan = PLAN_BY_ID[plan_id]
    amount = plan["price_yearly"] if interval == "yearly" else plan["price_monthly"]
    payment_id = f"pay_{secrets.token_hex(12)}"
    payment = {
        "id": payment_id,
        "user_id": user_id,
        "plan_id": plan_id,
        "interval": interval,
        "amount": amount,
        "currency": CURRENCY,
        "method": method,
        "status": "pending",
        "created_at": _now_iso(),
        "paid_at": None,
        "metadata": {},
    }
    _add_payment(user_id, payment)

    if method == "mbway":
        return {
            "ok": True,
            "payment_id": payment_id,
            "method": method,
            "amount": amount,
            "currency": CURRENCY,
            "instructions": "Indique o telemóvel para receber o pedido MB Way e confirme na app.",
        }
    if method == "transfer":
        iban = service_keys.resolver("transfer_iban") or ""
        return {
            "ok": True,
            "payment_id": payment_id,
            "method": method,
            "amount": amount,
            "currency": CURRENCY,
            "instructions": f"Transfira {amount:.2f} € para o IBAN {iban or '—'} com a referência {payment_id}. O acesso é ativado após confirmação manual.",
            "reference": payment_id,
            "iban": iban,
        }
    if method == "stripe":
        try:
            from api import stripe_payments

            session = stripe_payments.create_checkout_session(payment_id, amount, plan_id, interval)
            if not session.get("ok"):
                return {
                    "ok": False,
                    "payment_id": payment_id,
                    "method": method,
                    "configured": bool(session.get("configured", False)),
                    "error": session.get("error") or "Não foi possível iniciar o pagamento com cartão.",
                }
            payment["metadata"] = {"stripe_session_id": session.get("id")}
            _add_payment(user_id, payment)
            return {
                "ok": True,
                "payment_id": payment_id,
                "method": method,
                "checkout_url": session.get("url"),
                "amount": amount,
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("Stripe checkout falhou: %s", exc)
            return {"ok": False, "payment_id": payment_id, "method": method, "error": str(exc)}
    if method == "paypal":
        try:
            from api import paypal_payments

            order = paypal_payments.create_order(
                payment_id,
                amount,
                return_url=f"{PUBLIC_APP_URL}/settings?billing=paypal&payment_id={payment_id}",
                cancel_url=f"{PUBLIC_APP_URL}/settings?billing=cancel&payment_id={payment_id}",
            )
            if not order.get("ok"):
                return {
                    "ok": False,
                    "payment_id": payment_id,
                    "method": method,
                    "configured": bool(order.get("configured", False)),
                    "error": order.get("error") or "Não foi possível criar a ordem PayPal.",
                }
            payment["metadata"] = {"paypal_order_id": order.get("id")}
            _add_payment(user_id, payment)
            return {
                "ok": True,
                "payment_id": payment_id,
                "method": method,
                "order_id": order.get("id"),
                "approval_url": order.get("approval_url"),
                "amount": amount,
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("PayPal order falhou: %s", exc)
            return {"ok": False, "payment_id": payment_id, "method": method, "error": str(exc)}
    return {"ok": False, "payment_id": payment_id, "error": "Método não implementado."}


def _activate_subscription(user_id: str, payment: Dict[str, Any]) -> Dict[str, Any]:
    plan_id = payment.get("plan_id") or PLAN_BASIC
    interval = payment.get("interval") or "monthly"
    now = datetime.now(timezone.utc)
    period_end = _plan_end(now, interval)
    subscription = {
        "plan_id": plan_id,
        "status": "active",
        "interval": interval,
        "payment_method": payment.get("method"),
        "current_period_start": now.isoformat(),
        "current_period_end": period_end.isoformat(),
        "last_payment_id": payment.get("id"),
        "updated_at": _now_iso(),
    }
    user = _upsert_subscription(user_id, subscription)
    # Se estava suspensa por falta de pagamento, reativa.
    if user.get("status") != auth.USER_STATUS_ACTIVE:
        auth.update_user(user_id, {"status": auth.USER_STATUS_ACTIVE}, admin_fields=True)
        user = auth.get_user_by_id(user_id) or user
        user = auth.public_user(user)
    notification_email.send_subscription_activated_email(
        to=user.get("email") or "",
        name=user.get("name") or user.get("email") or "",
        plan_name=(PLAN_BY_ID.get(plan_id) or {}).get("name") or plan_id,
        period_end=subscription["current_period_end"],
    )
    events.log_event(
        "info",
        "billing",
        f"Subscrição ativada: {user.get('email')} → {plan_id} ({interval})",
        data={"plan_id": plan_id, "interval": interval, "payment_id": payment.get("id")},
        user_id=user_id,
        user_email=user.get("email"),
    )
    return user


def confirm_payment(user_id: str, payment_id: str, *, admin_confirmed: bool = False) -> Dict[str, Any]:
    """Marca um pagamento como pago e ativa/renova a subscrição."""
    user = auth.get_user_by_id(user_id)
    if not user:
        raise auth.AuthError("Conta não encontrada.", status_code=404, code="not_found")
    payments = list(user.get("payments") or [])
    payment = None
    for item in payments:
        if item.get("id") == payment_id:
            payment = item
            break
    if not payment:
        raise auth.AuthError("Pagamento não encontrado.", status_code=404, code="not_found")
    if payment.get("status") == "paid":
        return {"ok": True, "already_paid": True, "user": auth.public_user(user)}
    payment["status"] = "paid"
    payment["paid_at"] = _now_iso()
    if admin_confirmed:
        payment["metadata"] = {**(payment.get("metadata") or {}), "confirmed_by": "admin"}
    _add_payment(user_id, payment)
    updated_user = _activate_subscription(user_id, payment)
    return {"ok": True, "payment_id": payment_id, "user": updated_user}


def mbway_payment_request(user_id: str, payment_id: str, phone: str) -> Dict[str, Any]:
    """Cria pedido MB Way para um pagamento pendente."""
    user = auth.get_user_by_id(user_id)
    if not user:
        raise auth.AuthError("Conta não encontrada.", status_code=404, code="not_found")
    payments = list(user.get("payments") or [])
    payment = next((p for p in payments if p.get("id") == payment_id), None)
    if not payment:
        raise auth.AuthError("Pagamento não encontrado.", status_code=404, code="not_found")
    settings = _billing_settings()
    result = reports_payments.create_payment_request(
        settings,
        phone=phone,
        amount=payment.get("amount") or 0,
        reference=payment_id,
        description=f"Subscrição IQ OS {payment.get('plan_id')}",
    )
    if result.get("ok") and result.get("request_id"):
        payment["metadata"] = {**(payment.get("metadata") or {}), "mbway_request_id": result["request_id"]}
        _add_payment(user_id, payment)
    return result


def mbway_payment_status(user_id: str, payment_id: str) -> Dict[str, Any]:
    """Consulta estado MB Way e ativa subscrição se pago."""
    user = auth.get_user_by_id(user_id)
    if not user:
        raise auth.AuthError("Conta não encontrada.", status_code=404, code="not_found")
    payments = list(user.get("payments") or [])
    payment = next((p for p in payments if p.get("id") == payment_id), None)
    if not payment:
        raise auth.AuthError("Pagamento não encontrado.", status_code=404, code="not_found")
    request_id = (payment.get("metadata") or {}).get("mbway_request_id")
    if not request_id:
        return {"ok": False, "message": "Sem pedido MB Way ativo."}
    settings = _billing_settings()
    result = reports_payments.fetch_payment_status(settings, request_id=request_id)
    if result.get("paid"):
        confirm_payment(user_id, payment_id)
    return result


def _billing_settings() -> Dict[str, Any]:
    """Devolve as definições de pagamento efetivas."""
    return {
        "mbway_provider": "ifthenpay",
        "mbway_api_key": service_keys.resolver("mbway_api_key") or "",
        "mbway_api_url": service_keys.resolver("mbway_api_url") or "",
        "mbway_number": service_keys.resolver("mbway_number") or "",
    }


def capture_paypal_payment(user_id: str, payment_id: str) -> Dict[str, Any]:
    """Captura a ordem PayPal associada a um pagamento e ativa a subscrição."""
    from api import paypal_payments

    user = auth.get_user_by_id(user_id)
    if not user:
        raise auth.AuthError("Conta não encontrada.", status_code=404, code="not_found")
    payments = list(user.get("payments") or [])
    payment = next((item for item in payments if item.get("id") == payment_id), None)
    if not payment:
        raise auth.AuthError("Pagamento não encontrado.", status_code=404, code="not_found")
    order_id = (payment.get("metadata") or {}).get("paypal_order_id")
    if not order_id:
        raise auth.AuthError("Este pagamento não tem uma ordem PayPal associada.", status_code=422, code="no_order")

    result = paypal_payments.capture_order(str(order_id))
    if not result.get("ok"):
        return {
            "ok": False,
            "error": result.get("error") or "Não foi possível capturar o pagamento PayPal.",
            "status": result.get("status"),
        }
    confirmed = confirm_payment(user_id, payment_id)
    return {"ok": True, "payment_id": payment_id, "status": result.get("status"), "user": confirmed.get("user")}


def webhook_stripe(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Processa evento checkout.session.completed do Stripe."""
    try:
        from api import stripe_payments

        result = stripe_payments.handle_webhook(payload)
        if result.get("payment_id"):
            confirm_payment(result["user_id"], result["payment_id"])
        return {"ok": True}
    except Exception as exc:  # noqa: BLE001
        logger.warning("Webhook Stripe falhou: %s", exc)
        return {"ok": False, "error": str(exc)}


def webhook_paypal(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Processa captura do PayPal."""
    try:
        from api import paypal_payments

        result = paypal_payments.handle_webhook(payload)
        if result.get("payment_id"):
            confirm_payment(result["user_id"], result["payment_id"])
        return {"ok": True}
    except Exception as exc:  # noqa: BLE001
        logger.warning("Webhook PayPal falhou: %s", exc)
        return {"ok": False, "error": str(exc)}
