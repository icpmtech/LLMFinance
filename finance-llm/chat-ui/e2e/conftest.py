"""Fixtures da suite end-to-end do EmpresasIQ.

Os testes correm contra o frontend publicado (`E2E_FRONTEND_URL`, por omissão
`http://127.0.0.1:4180`) e comparam o que a UI mostra com o que a mesma API
devolve, para que os números esperados venham do Elasticsearch em vez de estarem
escritos à mão.

Duas particularidades do ambiente são neutralizadas aqui:

1. a aplicação exige sessão — o token é injetado em `localStorage`
   (`finance-llm-token`) antes de o bundle arrancar. As credenciais vêm de
   `E2E_EMAIL`/`E2E_PASSWORD`; com `E2E_TOKEN` o login é dispensado. Sem nenhuma
   destas variáveis é provisionada uma conta dedicada
   (`e2e-empresas-iq@example.com`) através de `/api/auth/register`;
2. o banner de consentimento da iubenda flutua sobre as abas do módulo e engole
   os cliques (o Playwright considera o clique bem-sucedido, mas o botão nunca o
   recebe). Os scripts de terceiros são bloqueados e qualquer nó do banner que
   sobreviva é removido depois de cada navegação.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

import pytest

DEFAULT_FRONTEND_URL = "http://127.0.0.1:4180"
TOKEN_STORAGE_KEY = "finance-llm-token"
E2E_ACCOUNT = {
    "name": "E2E Entidades",
    "email": "e2e-empresas-iq@example.com",
    "password": "E2eEmpresasIQ123",
    "title": "QA",
    "organization": "E2E",
}

BLOCKED_HOSTS = ("iubenda.com", "googletagmanager.com", "google-analytics.com")

REMOVE_CONSENT_OVERLAYS = """
() => {
  document
    .querySelectorAll('[class*="iubenda"], [id*="iubenda"], [id*="onetrust"], .cc-window')
    .forEach((node) => node.remove());
  document.documentElement.style.removeProperty('overflow');
}
"""


def frontend_url() -> str:
    """URL base do frontend em teste."""
    return os.environ.get("E2E_FRONTEND_URL", DEFAULT_FRONTEND_URL).rstrip("/")


def _post_json(url: str, payload: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8", "replace") or "{}"
        try:
            return error.code, json.loads(raw)
        except json.JSONDecodeError:
            return error.code, {"detail": raw}


@pytest.fixture(scope="session")
def auth_token() -> str:
    """Token de sessão usado pelos testes (login ou registo de conta E2E)."""
    token = (os.environ.get("E2E_TOKEN") or "").strip()
    if token:
        return token

    base = frontend_url()
    email = os.environ.get("E2E_EMAIL", E2E_ACCOUNT["email"])
    password = os.environ.get("E2E_PASSWORD", E2E_ACCOUNT["password"])

    status, body = _post_json(f"{base}/api/auth/login", {"email": email, "password": password, "remember": True})
    if status == 200 and body.get("token"):
        return body["token"]

    status, body = _post_json(f"{base}/api/auth/register", {**E2E_ACCOUNT, "email": email, "password": password})
    if status == 201 and body.get("token"):
        return body["token"]

    pytest.skip(
        f"Sem sessão em {base} (HTTP {status}: {body.get('detail')}). "
        "Defina E2E_TOKEN ou E2E_EMAIL/E2E_PASSWORD."
    )
    raise AssertionError("unreachable")


def _block_third_party(route) -> None:
    url = route.request.url
    if any(host in url for host in BLOCKED_HOSTS):
        route.abort()
    else:
        route.continue_()


@pytest.fixture
def context(new_context, auth_token):
    """Contexto com sessão injetada e sem scripts de consentimento/analytics."""
    context = new_context()
    context.add_init_script(
        f"window.localStorage.setItem({json.dumps(TOKEN_STORAGE_KEY)}, {json.dumps(auth_token)});"
        # O service worker serve assets em cache: nos testes queremos sempre o
        # bundle publicado.
        "if (navigator.serviceWorker) {"
        "  navigator.serviceWorker.getRegistrations().then((rs) => rs.forEach((r) => r.unregister()));"
        "}"
    )
    context.route("**/*", _block_third_party)
    yield context
    context.close()


@pytest.fixture
def app(page):
    """Página autenticada, com o banner de consentimento já removido."""

    def _open(path: str = "/empresas-iq"):
        # Limites folgados: o bundle é grande e a máquina pode estar carregada
        # (Elasticsearch + contentores + browser), pelo que os 30 s por omissão
        # do Playwright não chegam para a primeira pintura nem para a rede parar.
        page.goto(f"{frontend_url()}{path}", timeout=120_000)
        page.wait_for_load_state("networkidle", timeout=90_000)
        page.evaluate(REMOVE_CONSENT_OVERLAYS)
        return page

    return _open


@pytest.fixture
def api(context, auth_token):
    """Cliente mínimo da API (mesmos endpoints do browser) para valores esperados."""

    def _call(path: str, payload: dict | None = None, method: str | None = None) -> dict:
        verb = method or ("POST" if payload is not None else "GET")
        response = context.request.fetch(
            f"{frontend_url()}{path}",
            method=verb,
            headers={
                "Authorization": f"Bearer {auth_token}",
                "Content-Type": "application/json",
            },
            data=json.dumps(payload) if payload is not None else None,
            # As agregações de entidades/contratos são pesadas: numa máquina
            # carregada passam folgadamente dos 30 s por omissão do Playwright.
            timeout=180_000,
        )
        assert response.ok, f"{verb} {path} falhou com HTTP {response.status}"
        return response.json()

    return _call


@pytest.fixture
def tracked_requests(page):
    """Payloads dos pedidos que a UI envia para a API de entidades."""
    captured: list[dict] = []

    def _on_request(request) -> None:
        if "/api/companies/search" in request.url and request.method == "POST":
            try:
                captured.append(json.loads(request.post_data or "{}"))
            except json.JSONDecodeError:
                captured.append({})

    page.on("request", _on_request)
    return captured
