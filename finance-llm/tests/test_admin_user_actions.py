from __future__ import annotations

from datetime import datetime, timezone

import pytest

from api import auth_service as auth
from api import billing_service
from api import admin_routes
from api.auth_routes import CurrentSession, UserResponse
from api.admin_routes import _generate_temporary_password


def _admin_session() -> CurrentSession:
    user = auth.public_user(
        {
            "id": "admin-1",
            "email": "admin@example.test",
            "name": "Admin",
            "role": "admin",
            "status": auth.USER_STATUS_ACTIVE,
        }
    )
    return CurrentSession(user=UserResponse(**user), session_id="session-1", token="token")


def test_admin_temporary_password_meets_account_policy() -> None:
    password = _generate_temporary_password()

    assert len(password) == 20
    assert any(character.isalpha() for character in password)
    assert any(character.isdigit() for character in password)
    assert auth.validate_password_strength(password) is None


def test_admin_password_reset_returns_secret_once_and_revokes_sessions(monkeypatch) -> None:
    target = {"id": "user-1", "email": "user@example.test"}
    saved_passwords: list[tuple[str, str]] = []
    events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(admin_routes.auth, "get_user_by_id", lambda _user_id: target)
    monkeypatch.setattr(
        admin_routes.auth,
        "set_password",
        lambda user_id, password: saved_passwords.append((user_id, password)),
    )
    monkeypatch.setattr(admin_routes.auth, "revoke_all_sessions", lambda _user_id: 3)
    monkeypatch.setattr(
        admin_routes.events,
        "log_event",
        lambda *args, **kwargs: events.append((args, kwargs)),
    )

    result = admin_routes.admin_reset_user_password("user-1", _admin_session())

    assert result["ok"] is True
    assert result["revoked_sessions"] == 3
    assert saved_passwords == [("user-1", result["temporary_password"])]
    assert result["temporary_password"] not in repr(events)


def test_admin_manual_plan_activation_sets_subscription_and_reactivates_user(monkeypatch) -> None:
    user = {
        "id": "user-1",
        "email": "user@example.test",
        "name": "Utilizador",
        "status": auth.USER_STATUS_SUSPENDED,
        "subscription": {},
    }
    state = dict(user)
    saved_subscription: dict = {}

    def update_user(_user_id: str, patch: dict, **_: object) -> dict:
        state.update(patch)
        return auth.public_user(state)

    def upsert_subscription(_user_id: str, patch: dict) -> dict:
        saved_subscription.update(patch)
        state["subscription"] = dict(saved_subscription)
        return auth.public_user(state)

    monkeypatch.setattr(auth, "get_user_by_id", lambda _user_id: dict(state))
    monkeypatch.setattr(auth, "update_user", update_user)
    monkeypatch.setattr(billing_service, "_upsert_subscription", upsert_subscription)
    monkeypatch.setattr(billing_service.notification_email, "send_subscription_activated_email", lambda **_: None)
    monkeypatch.setattr(billing_service.events, "log_event", lambda *_, **__: None)

    result = billing_service.activate_subscription_manually("user-1", plan_id="pro", interval="monthly")

    assert result["status"] == auth.USER_STATUS_ACTIVE
    assert result["subscription"]["plan_id"] == "pro"
    assert result["subscription"]["payment_method"] == "admin"
    assert result["subscription"]["last_payment_id"] is None
    assert datetime.fromisoformat(result["subscription"]["current_period_end"]) > datetime.now(timezone.utc)


@pytest.mark.parametrize(
    ("plan_id", "interval"),
    [("unknown", "monthly"), ("basic", "weekly")],
)
def test_admin_manual_plan_activation_rejects_invalid_plan_or_interval(plan_id: str, interval: str) -> None:
    with pytest.raises(auth.AuthError) as error:
        billing_service.activate_subscription_manually("user-1", plan_id=plan_id, interval=interval)

    assert error.value.status_code == 422
