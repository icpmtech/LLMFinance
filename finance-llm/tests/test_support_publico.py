"""Widget de apoio ao cliente nas superfícies públicas.

O widget tem de chegar a todas as superfícies que um visitante anónimo vê: o
site do CMS (`/site/...`), a loja (`/loja/...`) e a SPA (landing, login e
registo). No servidor o snippet entra no `<head>` das páginas públicas e fica de
fora das pré-visualizações; na SPA o mesmo script é instalado por
`SupportChat.tsx`.

A consola de operadores vive na Administração (`AdminPage` → **Suporte**).
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from api import cms_render  # noqa: E402
from api import cms_store  # noqa: E402
from api import shop_render  # noqa: E402
from api import shop_store  # noqa: E402
from api import support_widget  # noqa: E402


@pytest.fixture()
def instalacao_limpa(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Site e loja isolados em `tmp_path` (sem ler nem escrever em `data/`)."""
    monkeypatch.setattr(cms_store, "CMS_DIR", tmp_path / "cms")
    monkeypatch.setattr(cms_store, "CMS_PATH", tmp_path / "cms" / "cms.json")
    monkeypatch.setattr(cms_store, "MEDIA_DIR", tmp_path / "cms" / "media")
    monkeypatch.setattr(cms_store, "_cache", None)
    monkeypatch.setattr(cms_store, "_cache_mtime", None)

    monkeypatch.setattr(shop_store, "SHOP_DIR", tmp_path / "shop")
    monkeypatch.setattr(shop_store, "SHOP_PATH", tmp_path / "shop" / "shop.json")
    monkeypatch.setattr(shop_store, "FILES_DIR", tmp_path / "shop" / "files")
    monkeypatch.setattr(shop_store, "_cache", None)
    monkeypatch.setattr(shop_store, "_cache_mtime", None)
    shop_store.reset_seed()
    return shop_store


def _layout_do_site(*, preview: bool = False) -> str:
    return cms_render._layout(
        title="Página",
        description="Descrição",
        body="<p>Conteúdo</p>",
        current_path="/site/pagina",
        settings={"site_name": "Sabemos Studio", "base_url": "https://sabemos.studio"},
        preview=preview,
    )


def test_site_publico_leva_o_widget() -> None:
    html = _layout_do_site()

    assert support_widget.SUPPORT_SNIPPET in html
    assert support_widget.WIDGET_PATH in html
    assert "data-iqos-support" in html


def test_pre_visualizacao_do_site_nao_leva_o_widget() -> None:
    html = _layout_do_site(preview=True)

    assert support_widget.SUPPORT_SNIPPET not in html


def test_loja_publica_leva_o_widget(instalacao_limpa: Any) -> None:
    html = shop_render.render_home(settings=instalacao_limpa.get_settings())

    assert support_widget.SUPPORT_SNIPPET in html


def test_pre_visualizacao_da_loja_nao_leva_o_widget(instalacao_limpa: Any) -> None:
    html = shop_render.render_home(settings=instalacao_limpa.get_settings(), preview=True)

    assert support_widget.SUPPORT_SNIPPET not in html


def test_widget_js_tem_conversa_tempo_real_e_tickets() -> None:
    script = (RAIZ / "api" / "support_widget.js").read_text(encoding="utf-8")

    assert "attachShadow" in script
    assert "/support/visitors" in script
    assert "/support/sessions" in script
    assert "/support/ws" in script
    assert "X-Support-Token" in script
    assert "WebSocket" in script
    assert "/ticket" in script
    assert "pageContext" in script


@pytest.mark.parametrize("pagina", ["LandingPage.tsx", "LoginPage.tsx"])
def test_spa_monta_o_widget_nas_paginas_publicas(pagina: str) -> None:
    fonte = (RAIZ / "chat-ui" / "src" / "pages" / pagina).read_text(encoding="utf-8")

    assert 'from "../components/SupportChat"' in fonte
    assert "<SupportChat />" in fonte


def test_spa_instala_o_mesmo_widget_do_servidor() -> None:
    componente = (RAIZ / "chat-ui" / "src" / "components" / "SupportChat.tsx").read_text(encoding="utf-8")

    assert "/support/widget.js" in componente
    assert "data-iqos-support" in componente
    assert "__IQOS_SUPPORT_API__" in componente


def test_administracao_tem_aba_de_suporte() -> None:
    fonte = (RAIZ / "chat-ui" / "src" / "pages" / "AdminPage.tsx").read_text(encoding="utf-8")
    consola = (RAIZ / "chat-ui" / "src" / "components" / "AdminSupportPanel.tsx").read_text(encoding="utf-8")

    assert 'id: "support"' in fonte
    assert "<AdminSupportPanel" in fonte
    assert "/support/ws" in (RAIZ / "chat-ui" / "src" / "supportApi.ts").read_text(encoding="utf-8")
    assert "Tickets" in consola
    assert "Páginas por onde passou" in consola


def test_nao_resta_integracao_com_tawk() -> None:
    """A substituição é completa: nem o snippet nem a consola antiga ficam."""
    assert not (RAIZ / "api" / "tawk.py").exists()
    assert not (RAIZ / "chat-ui" / "src" / "components" / "TawkChat.tsx").exists()
    for caminho in ("api/cms_render.py", "api/shop_render.py"):
        fonte = (RAIZ / caminho).read_text(encoding="utf-8")
        assert "tawk" not in fonte.lower()
