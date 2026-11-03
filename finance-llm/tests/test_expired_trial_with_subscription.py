from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from api import auth_service, billing_service
from api import auth_routes


def _expired_trial_user(*, subscription: dict | None = None) -> dict:
    return {
        "id": "user-1",
        "email": "user@example.test",
        "status": auth_service.USER_STATUS_ACTIVE,
        "trial_expires_at": "2020-01-01T00:00:00+00:00",
        "subscription": subscription or {},
    }


def test_trial_expiry_does_not_block_active_subscription(monkeypatch) -> None:
    user = _expired_trial_user(
        subscription={
            "plan_id": "enterprise",
            "status": "active",
            "current_period_end": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
        }
    )
    monkeypatch.setattr(auth_service, "get_user_by_email", lambda _email: user)
    monkeypatch.setattr(auth_service, "verify_password", lambda _password, _stored: True)

    assert auth_service.authenticate(user["email"], "password") == user
    auth_routes._require_user_active(user)


@pytest.mark.parametrize(
    "subscription",
    [
        {},
        {"plan_id": "enterprise", "status": "active"},
        {
            "plan_id": "enterprise",
            "status": "active",
            "current_period_end": "2020-01-02T00:00:00+00:00",
        },
        {
            "plan_id": "unknown",
            "status": "active",
            "current_period_end": "2099-01-01T00:00:00+00:00",
        },
    ],
)
def test_expired_trial_without_valid_subscription_stays_blocked(subscription: dict, monkeypatch) -> None:
    user = _expired_trial_user(subscription=subscription)
    monkeypatch.setattr(auth_service, "get_user_by_email", lambda _email: user)
    monkeypatch.setattr(auth_service, "verify_password", lambda _password, _stored: True)

    assert billing_service.has_active_subscription(user) is False
    with pytest.raises(auth_service.AuthError, match="trial de 5 dias expirou"):
        auth_service.authenticate(user["email"], "password")
    with pytest.raises(HTTPException) as error:
        auth_routes._require_user_active(user)
    assert error.value.status_code == 403
