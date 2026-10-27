"""Testes da verificação em dois passos (MFA por email).

O que aqui se fixa é o contrato do processo, sem Elasticsearch nem SMTP reais:

* a política decide **quem** é desafiado e a preferência da conta é respeitada;
* o código nunca é guardado em claro (só o HMAC), serve uma vez e expira;
* as tentativas erradas são contadas e o reenvio respeita o intervalo mínimo;
* o login por palavras-passe continua a funcionar sem MFA (é opcional).
"""

from __future__ import annotations

import pytest

from api import auth_service as auth
from api import mfa_service as mfa
from api import notification_email


class FakeES:
    """Cliente mínimo: só os métodos que o `mfa_service` usa."""

    def __init__(self) -> None:
        self.docs: dict[tuple[str, str], dict] = {}
        self.sent: dict[str, str] = {}

    def exists(self, index: str, id: str) -> bool:  # noqa: A002 - assinatura do cliente real
        return (index, id) in self.docs

    def get(self, index: str, id: str) -> dict:  # noqa: A002
        key = (index, id)
        if key not in self.docs:
            raise KeyError(f"{index}/{id}")
        return {"_source": dict(self.docs[key])}

    def index(self, index: str, id: str, document: dict, refresh: bool = True) -> dict:  # noqa: A002
        self.docs[(index, id)] = dict(document)
        return {"result": "created"}

    def update(self, index: str, id: str, doc: dict, refresh: bool = True) -> dict:  # noqa: A002
        key = (index, id)
        if key not in self.docs:
            raise KeyError(key)
        self.docs[key].update(doc)
        return {"result": "updated"}

    def delete_by_query(self, index: str, body: dict, **_: object) -> dict:
        filters = body["query"]["bool"]["filter"]
        removed = 0
        for key in self._matching(index, filters):
            del self.docs[key]
            removed += 1
        return {"deleted": removed}

    def search(self, index: str, body: dict) -> dict:
        query = body["query"]["bool"]
        excluded = [
            term["term"]["verified"]
            for term in query.get("must_not") or []
            if "verified" in (term.get("term") or {})
        ]
        hits = [
            {"_id": key[1], "_source": dict(self.docs[key])}
            for key in self._matching(index, query["filter"])
            if not (excluded and self.docs[key].get("verified") is True)
        ]
        return {"hits": {"total": {"value": len(hits)}, "hits": hits[: int(body.get("size") or 10)]}}

    def _matching(self, index: str, filters: list) -> list:
        """Filtros suportados: `term` em user_id/used e `range` em created_at."""
        user_id = None
        only_open = False
        after = None
        before = None
        for item in filters:
            term = item.get("term") or {}
            if "user_id" in term:
                user_id = term["user_id"]
            if "used" in term:
                only_open = True
            window = (item.get("range") or {}).get("created_at") or {}
            after = window.get("gte", after)
            before = window.get("lt", before)

        matches = []
        for key, document in self.docs.items():
            if key[0] != index:
                continue
            if user_id is not None and document.get("user_id") != user_id:
                continue
            if only_open and document.get("used") is not False:
                continue
            created = str(document.get("created_at") or "")
            if after and created < str(after):
                continue
            if before and created >= str(before):
                continue
            matches.append(key)
        return matches


@pytest.fixture()
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeES:
    """Elasticsearch falso + captura do código enviado por email."""
    client = FakeES()
    monkeypatch.setattr(mfa, "_client", lambda: client)
    monkeypatch.setattr(mfa.auth_service, "signing_secret", lambda: b"segredo-de-teste")
    monkeypatch.setattr(notification_email, "is_configured", lambda: True)

    def fake_send(to: str, name: str, code: str, **kwargs: object) -> dict:
        client.sent["to"] = to
        client.sent["name"] = name
        client.sent["code"] = code
        client.sent["ip"] = str(kwargs.get("ip") or "")
        return {"ok": True, "configured": True, "message": "Email enviado."}

    monkeypatch.setattr(notification_email, "send_login_code_email", fake_send)
    return client


def _user(**extra: object) -> dict:
    user = {
        "id": "u-1",
        "email": "ana.ribeiro@empresa.pt",
        "name": "Ana Ribeiro",
        "role": auth.ROLE_MEMBER,
        "status": auth.USER_STATUS_ACTIVE,
    }
    user.update(extra)
    return user


# ---------------------------------------------------------------- preferência
def test_public_user_expoe_mfa_desativado_por_omissao(fake: FakeES) -> None:
    assert auth.public_user(_user())["mfa_enabled"] is False
    assert auth.public_user(_user(mfa={"enabled": True}))["mfa_enabled"] is True


def test_politica_por_omissao_esta_desligada(fake: FakeES) -> None:
    current = mfa.policy()
    assert current["policy"] == mfa.POLICY_OFF
    assert current["code_ttl_seconds"] == mfa.DEFAULT_TTL_SECONDS


@pytest.mark.parametrize(
    ("policy", "role", "preferencia", "esperado"),
    [
        (mfa.POLICY_OFF, auth.ROLE_ADMIN, False, False),
        (mfa.POLICY_OFF, auth.ROLE_MEMBER, False, False),
        (mfa.POLICY_OFF, auth.ROLE_MEMBER, True, True),
        (mfa.POLICY_ADMINS, auth.ROLE_ADMIN, False, True),
        (mfa.POLICY_ADMINS, auth.ROLE_MEMBER, False, False),
        (mfa.POLICY_ADMINS, auth.ROLE_MEMBER, True, True),
        (mfa.POLICY_ALL, auth.ROLE_MEMBER, False, True),
        (mfa.POLICY_ALL, auth.ROLE_ADMIN, False, True),
    ],
)
def test_quem_e_desafiado(
    fake: FakeES, policy: str, role: str, preferencia: bool, esperado: bool
) -> None:
    user = _user(role=role, mfa={"enabled": preferencia})
    settings = mfa._clean_policy({"policy": policy}, updated_at=None, updated_by="")
    assert mfa.required_for(user, settings) is esperado


def test_politica_normaliza_valores_fora_dos_limites(fake: FakeES) -> None:
    saved = mfa.save_policy(
        {"policy": " ALL ", "code_ttl_seconds": 5, "max_attempts": 999, "resend_cooldown_seconds": 0},
        actor_email="admin@empresa.pt",
    )
    assert saved["policy"] == mfa.POLICY_ALL
    assert saved["code_ttl_seconds"] == mfa.MIN_TTL_SECONDS
    assert saved["max_attempts"] == mfa.MAX_MAX_ATTEMPTS
    assert saved["resend_cooldown_seconds"] == mfa.MIN_RESEND_SECONDS
    assert mfa.policy()["updated_by"] == "admin@empresa.pt"


def test_politica_invalida_e_recusada(fake: FakeES) -> None:
    with pytest.raises(mfa.MfaError):
        mfa.save_policy({"policy": "as-vezes"}, actor_email="admin@empresa.pt")


def test_mascara_do_email(fake: FakeES) -> None:
    assert mfa.mask_email("ana.ribeiro@empresa.pt") == "an***@empresa.pt"
    assert mfa.mask_email("a@b.pt") == "a***@b.pt"


# ------------------------------------------------------------------- desafios
def test_codigo_nao_e_guardado_em_claro(fake: FakeES) -> None:
    challenge = mfa.create_challenge(_user(), ip="10.0.0.1", user_agent="pytest")
    stored = next(iter(fake.docs.values()))
    code = fake.sent["code"]

    assert len(code) == mfa.CODE_DIGITS and code.isdigit()
    assert stored["code_hash"] != code
    assert code not in str(stored.values())
    assert fake.sent["to"] == "ana.ribeiro@empresa.pt"
    assert challenge["email"] == "an***@empresa.pt"
    assert challenge["mfa_required"] is True


def test_codigo_correto_abre_a_sessao_e_so_serve_uma_vez(fake: FakeES) -> None:
    challenge = mfa.create_challenge(_user())
    verified = mfa.verify(challenge["challenge_id"], fake.sent["code"])

    assert verified["user_id"] == "u-1"
    with pytest.raises(mfa.MfaError) as caught:
        mfa.verify(challenge["challenge_id"], fake.sent["code"])
    assert caught.value.code == "mfa_used"


def test_codigo_errado_conta_tentativas(fake: FakeES) -> None:
    fake.docs[("finance_settings", mfa.DOC_ID)] = {
        "payload": {"policy": mfa.POLICY_ALL, "max_attempts": 3}
    }
    challenge = mfa.create_challenge(_user())
    correct = fake.sent["code"]
    wrong = "000000" if correct != "000000" else "111111"

    with pytest.raises(mfa.MfaError) as first:
        mfa.verify(challenge["challenge_id"], wrong)
    assert first.value.code == "mfa_invalid"
    assert "Restam 2" in first.value.message

    with pytest.raises(mfa.MfaError):
        mfa.verify(challenge["challenge_id"], wrong)
    with pytest.raises(mfa.MfaError) as third:
        mfa.verify(challenge["challenge_id"], wrong)
    assert third.value.code == "mfa_locked"

    # Já bloqueado, o código certo também não passa: é preciso um login novo.
    with pytest.raises(mfa.MfaError) as blocked:
        mfa.verify(challenge["challenge_id"], correct)
    assert blocked.value.code == "mfa_used"


def test_codigo_expirado_e_recusado(fake: FakeES) -> None:
    challenge = mfa.create_challenge(_user())
    key = (mfa.AUTH_CHALLENGES_INDEX, challenge["challenge_id"])
    fake.docs[key]["expires_at"] = "2020-01-01T00:00:00Z"

    with pytest.raises(mfa.MfaError) as caught:
        mfa.verify(challenge["challenge_id"], fake.sent["code"])
    assert caught.value.code == "mfa_expired"


def test_codigo_com_formato_invalido(fake: FakeES) -> None:
    challenge = mfa.create_challenge(_user())
    with pytest.raises(mfa.MfaError) as caught:
        mfa.verify(challenge["challenge_id"], "12ab")
    assert caught.value.status_code == 422


def test_novo_login_anula_o_codigo_anterior(fake: FakeES) -> None:
    first = mfa.create_challenge(_user())
    first_code = fake.sent["code"]
    mfa.create_challenge(_user())

    with pytest.raises(mfa.MfaError) as caught:
        mfa.verify(first["challenge_id"], first_code)
    assert caught.value.code in {"mfa_invalid", "mfa_used", "mfa_expired"}


def test_pedidos_em_serie_sao_travados(fake: FakeES) -> None:
    for _ in range(mfa.CHALLENGE_LIMIT_PER_WINDOW):
        mfa.create_challenge(_user())

    with pytest.raises(mfa.MfaError) as caught:
        mfa.create_challenge(_user())
    assert caught.value.code == "mfa_throttled"
    assert caught.value.retry_after > 0


def test_logins_concluidos_nao_contam_para_o_travao(fake: FakeES) -> None:
    """Quem entra várias vezes com sucesso não fica bloqueado."""
    for _ in range(mfa.CHALLENGE_LIMIT_PER_WINDOW + 2):
        challenge = mfa.create_challenge(_user())
        mfa.verify(challenge["challenge_id"], fake.sent["code"])


def test_reenvio_respeita_o_intervalo_minimo(fake: FakeES) -> None:
    challenge = mfa.create_challenge(_user())

    with pytest.raises(mfa.MfaError) as caught:
        mfa.resend(challenge["challenge_id"])
    assert caught.value.code == "mfa_cooldown"
    assert caught.value.retry_after > 0

    key = (mfa.AUTH_CHALLENGES_INDEX, challenge["challenge_id"])
    fake.docs[key]["last_sent_at"] = "2020-01-01T00:00:00Z"
    renewed = mfa.resend(challenge["challenge_id"])

    assert renewed["challenge_id"] == challenge["challenge_id"]
    assert fake.docs[key]["sends"] == 2
    assert mfa.verify(challenge["challenge_id"], fake.sent["code"])["user_id"] == "u-1"


def test_falha_de_envio_nao_deixa_desafio_aberto(fake: FakeES, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        notification_email,
        "send_login_code_email",
        lambda *_, **__: {"ok": False, "configured": True, "message": "Falha de envio."},
    )

    with pytest.raises(mfa.MfaError) as caught:
        mfa.create_challenge(_user())
    assert caught.value.code == "email_failed"
    assert not [doc for doc in fake.docs.values() if doc.get("used") is False]


def test_sem_smtp_o_erro_e_explicito(fake: FakeES, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        notification_email,
        "send_login_code_email",
        lambda *_, **__: {"ok": False, "configured": False, "message": "SMTP não configurado."},
    )

    with pytest.raises(mfa.MfaError) as caught:
        mfa.create_challenge(_user())
    assert caught.value.status_code == 503
    assert "SMTP" in caught.value.message


def test_estado_da_conta_reflete_politica_e_preferencia(fake: FakeES) -> None:
    mfa.save_policy({"policy": mfa.POLICY_ALL}, actor_email="admin@empresa.pt")
    status = mfa.status_for(_user())

    assert status["policy"] == mfa.POLICY_ALL
    assert status["enforced"] is True
    assert status["required"] is True
    assert status["can_change"] is False
    assert status["email_configured"] is True


def test_estado_da_conta_aceita_o_retrato_publico(fake: FakeES) -> None:
    """`PUT /auth/mfa` devolve o estado a partir do utilizador público da API."""
    public = auth.public_user(_user(mfa={"enabled": True}))

    assert "mfa" not in public
    assert mfa.user_enabled(public) is True
    assert mfa.status_for(public)["user_enabled"] is True
    assert mfa.status_for(public)["required"] is True


def test_overview_avisa_quando_falta_smtp(fake: FakeES, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(notification_email, "is_configured", lambda: False)
    mfa.save_policy({"policy": mfa.POLICY_ADMINS}, actor_email="admin@empresa.pt")

    state = mfa.overview()
    assert state["email_configured"] is False
    assert state["warning"] and "SMTP" in state["warning"]
