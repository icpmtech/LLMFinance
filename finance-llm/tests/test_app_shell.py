"""Testes do cabeçalho e rodapé das páginas públicas da plataforma.

Cobrem o que é arriscado nesta definição: o que as páginas de entrada mostram
sem ninguém ter configurado nada (predefinições), a diferença entre um campo
**ausente** (volta à predefinição) e um campo **vazio** (fica vazio), os
endereços que não podem entrar num `href`, e a porta do painel — sem sessão é
401, com sessão de membro é 403 e só o papel `admin` edita.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import api.main as api_main  # noqa: E402
from api import app_shell  # noqa: E402
from api.admin_routes import require_admin  # noqa: E402
from api.auth_routes import CurrentSession, UserResponse, require_session  # noqa: E402


@pytest.fixture()
def shell_limpo(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    """Um ficheiro de configuração vazio em disco, para não tocar no real."""
    monkeypatch.setattr(app_shell, "SHELL_DIR", tmp_path / "app")
    monkeypatch.setattr(app_shell, "SHELL_PATH", tmp_path / "app" / "shell.json")
    return app_shell


# --------------------------------------------------------------- predefinições
def test_sem_configuracao_mostra_as_predefinicoes(shell_limpo: Any) -> None:
    corpo = app_shell.public_payload()

    assert corpo["brand"]["name"] == "IQ OS"
    assert corpo["brand"]["tagline"] == "Plataforma de inteligência financeira"
    assert corpo["brand"]["logo_url"] == ""
    # O logótipo em falta traz o nome como texto alternativo (nunca vai vazio).
    assert corpo["brand"]["logo_alt"] == "IQ OS"
    assert corpo["header"]["items"] == []
    assert corpo["header"]["cta"] == {"label": "Criar conta", "href": "/register"}
    assert corpo["header"]["secondary"] == {"label": "Entrar", "href": "/login"}
    assert corpo["footer"]["text"].startswith("Sabemos Studio")
    assert [item["href"] for item in corpo["footer"]["items"]] == ["/login", "/register"]
    assert corpo["footer"]["social"] == []


def test_primeira_gravacao_deixa_ficheiro_no_disco(shell_limpo: Any) -> None:
    app_shell.save({"brand": {"name": "Sabemos Studio"}}, author="admin@exemplo.pt")

    guardado = json.loads((shell_limpo.SHELL_PATH).read_text(encoding="utf-8"))
    assert guardado["version"] == app_shell.SHELL_VERSION
    assert guardado["brand"]["name"] == "Sabemos Studio"
    assert guardado["updated_by"] == "admin@exemplo.pt"
    # O que não foi enviado continua nas predefinições.
    assert guardado["header"]["cta"]["href"] == "/register"


# ------------------------------------------------------- ausente vs. vazio
def test_campo_ausente_volta_a_predefinicao_e_vazio_fica_vazio(shell_limpo: Any) -> None:
    app_shell.save({"brand": {"name": "IQ OS"}, "header": {"items": [], "cta": {}, "secondary": None}})

    corpo = app_shell.public_payload()
    # «cta» e «secondary» vieram (vazios): o cabeçalho deixa de ter os botões.
    assert corpo["header"]["cta"] is None
    assert corpo["header"]["secondary"] is None
    # A marca não veio: a predefinição do rodapé mantém-se.
    assert corpo["footer"]["items"][0]["href"] == "/login"


def test_marca_sem_nome_cai_na_predefinicao(shell_limpo: Any) -> None:
    app_shell.save({"brand": {"name": "   "}})

    assert app_shell.public_payload()["brand"]["name"] == "IQ OS"


def test_rodape_nao_leva_botoes_do_cabecalho(shell_limpo: Any) -> None:
    """O documento gravado não mistura as chaves do cabeçalho no rodapé."""
    guardado = app_shell.save({"footer": {"text": "© 2026"}})

    assert "cta" not in guardado["footer"] and "secondary" not in guardado["footer"]
    assert set(guardado["footer"]) == {"items", "text", "social"}


def test_texto_do_rodape_vazio_esconde_a_frase(shell_limpo: Any) -> None:
    app_shell.save({"footer": {"text": ""}})

    assert app_shell.public_payload()["footer"]["text"] == ""


# ------------------------------------------------------------------- links
def test_link_sem_destino_ou_fora_dos_esquemas_e_ignorado(shell_limpo: Any) -> None:
    app_shell.save(
        {
            "header": {
                "items": [
                    {"label": "Blog", "href": "/site/blog"},
                    {"label": "Só etiqueta"},
                    {"href": "/site/fontes"},
                    {"label": "Mau", "href": "javascript:alert(1)"},
                    {"label": "Externo", "href": "https://sabemos.studio"},
                    {"label": "Repetido", "href": "/site/blog"},
                ]
            }
        }
    )

    itens = app_shell.public_payload()["header"]["items"]
    assert [(item["label"], item["href"]) for item in itens] == [
        ("Blog", "/site/blog"),
        ("Externo", "https://sabemos.studio"),
    ]


def test_navegacao_respeita_o_limite(shell_limpo: Any) -> None:
    itens = [{"label": f"Link {numero}", "href": f"/link-{numero}"} for numero in range(app_shell.MAX_LINKS + 5)]
    app_shell.save({"header": {"items": itens}})

    assert len(app_shell.public_payload()["header"]["items"]) == app_shell.MAX_LINKS


def test_email_do_rodape_ganha_mailto(shell_limpo: Any) -> None:
    app_shell.save({"footer": {"social": {"email": "geral@sabemos.studio", "linkedin": "https://linkedin.com/company/x", "x": "nada"}}})

    sociais = {item["key"]: item["href"] for item in app_shell.public_payload()["footer"]["social"]}
    assert sociais == {
        "email": "mailto:geral@sabemos.studio",
        "linkedin": "https://linkedin.com/company/x",
    }


def test_um_email_ja_com_mailto_nao_e_duplicado(shell_limpo: Any) -> None:
    app_shell.save({"footer": {"social": {"email": "mailto:geral@sabemos.studio"}}})

    assert app_shell.public_payload()["footer"]["social"] == [
        {"key": "email", "label": "Email", "href": "mailto:geral@sabemos.studio"}
    ]


def test_ficheiro_estragado_nao_derruba_as_paginas(shell_limpo: Any) -> None:
    shell_limpo.SHELL_PATH.parent.mkdir(parents=True, exist_ok=True)
    shell_limpo.SHELL_PATH.write_text("{isto não é json", encoding="utf-8")

    corpo = app_shell.public_payload()
    assert corpo["brand"]["name"] == "IQ OS"
    assert app_shell.document()["configured"] is False


def test_ficheiro_com_bom_e_lido(shell_limpo: Any) -> None:
    """Um BOM (ficheiro gravado no Notepad, por exemplo) não invalida a configuração."""
    shell_limpo.SHELL_PATH.parent.mkdir(parents=True, exist_ok=True)
    conteudo = json.dumps({"brand": {"name": "Sabemos Studio"}}, ensure_ascii=False)
    shell_limpo.SHELL_PATH.write_text(conteudo, encoding="utf-8-sig")

    assert app_shell.public_payload()["brand"]["name"] == "Sabemos Studio"
    assert app_shell.document()["configured"] is True


# -------------------------------------------------------------------- rotas
def _sessao(role: str = "admin") -> CurrentSession:
    return CurrentSession(
        user=UserResponse(
            id="u-admin",
            email="admin@exemplo.pt",
            name="admin",
            role=role,
            initials="AD",
            status="active",
            locale="pt-PT",
            timezone="Europe/Lisbon",
        ),
        session_id="s-prova",
        token="t-prova",
    )


def _cliente() -> TestClient:
    return TestClient(api_main.app, base_url="http://prova")


@pytest.fixture()
def admin() -> Any:
    """Sessão de administrador, injetada por cima do `require_admin`."""
    api_main.app.dependency_overrides[require_admin] = lambda: _sessao()
    try:
        yield _cliente()
    finally:
        api_main.app.dependency_overrides.pop(require_admin, None)


def test_rota_publica_responde_com_o_shell_e_cache(shell_limpo: Any) -> None:
    resposta = _cliente().get("/app-shell")

    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["brand"]["name"] == "IQ OS"
    assert corpo["header"]["cta"]["href"] == "/register"
    assert "max-age" in resposta.headers["cache-control"]


def test_painel_exige_sessao(shell_limpo: Any) -> None:
    assert _cliente().get("/admin/app-shell").status_code == 401


def test_painel_exige_papel_admin(shell_limpo: Any) -> None:
    api_main.app.dependency_overrides[require_session] = lambda: _sessao(role="member")
    try:
        resposta = _cliente().get("/admin/app-shell")
    finally:
        api_main.app.dependency_overrides.pop(require_session, None)

    assert resposta.status_code == 403


def test_painel_le_as_predefinicoes(shell_limpo: Any, admin: TestClient) -> None:
    resposta = admin.get("/admin/app-shell")

    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["shell"]["brand"]["name"] == "IQ OS"
    assert corpo["shell"]["configured"] is False
    assert corpo["defaults"]["brand"]["name"] == "IQ OS"
    assert corpo["limits"]["links"] == app_shell.MAX_LINKS
    assert [item["key"] for item in corpo["social"]] == ["email", "linkedin", "x", "github"]


def test_painel_grava_e_a_pagina_publica_ve(shell_limpo: Any, admin: TestClient) -> None:
    resposta = admin.put(
        "/admin/app-shell",
        json={
            "brand": {"name": "Sabemos Studio", "tagline": "Dados com origem à vista"},
            "header": {"items": [{"label": "Blog", "href": "/site/blog"}]},
            "footer": {"text": "© 2026 Sabemos Studio"},
        },
    )

    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["saved"] is True

    publico = _cliente().get("/app-shell").json()
    assert publico["brand"]["name"] == "Sabemos Studio"
    assert publico["brand"]["tagline"] == "Dados com origem à vista"
    assert publico["header"]["items"] == [{"label": "Blog", "href": "/site/blog"}]
    assert publico["footer"]["text"] == "© 2026 Sabemos Studio"
    # Os botões do cabeçalho não foram enviados: mantêm-se os de origem.
    assert publico["header"]["cta"] == {"label": "Criar conta", "href": "/register"}


def test_painel_devolve_quem_gravou(shell_limpo: Any, admin: TestClient) -> None:
    corpo = admin.put("/admin/app-shell", json={"brand": {"name": "IQ OS"}}).json()

    assert corpo["shell"]["updated_by"] == "admin@exemplo.pt"
    assert corpo["shell"]["updated_at"]
