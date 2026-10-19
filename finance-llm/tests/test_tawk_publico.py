"""Widget de apoio ao cliente (Tawk.to) nas páginas públicas.

O widget tem de chegar a todas as superfícies que um visitante anónimo vê: o
site do CMS (`/site/...`), a loja (`/loja/...`) e a SPA (landing, login e
registo). Na SPA o widget é montado pelo React (`TawkChat.tsx`); aqui fixa-se o
lado servidor — o snippet entra no `<head>` das páginas públicas e fica de fora
das pré-visualizações.

A propriedade é a mesma nos dois lados (`api/tawk.py` e
`chat-ui/src/components/TawkChat.tsx`): se mudar, muda nos dois.
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
from api import tawk  # noqa: E402


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

    assert tawk.TAWK_SNIPPET in html
    assert f"https://embed.tawk.to/{tawk.TAWK_PROPERTY}" in html


def test_pre_visualizacao_do_site_nao_leva_o_widget() -> None:
    assert tawk.TAWK_SNIPPET not in _layout_do_site(preview=True)


def test_loja_publica_leva_o_widget(instalacao_limpa: Any) -> None:
    html = shop_render.render_home(settings=instalacao_limpa.get_settings())

    assert tawk.TAWK_SNIPPET in html


def test_pre_visualizacao_da_loja_nao_leva_o_widget(instalacao_limpa: Any) -> None:
    html = shop_render.render_home(settings=instalacao_limpa.get_settings(), preview=True)

    assert tawk.TAWK_SNIPPET not in html


@pytest.mark.parametrize("pagina", ["LandingPage.tsx", "LoginPage.tsx"])
def test_spa_monta_o_widget_nas_paginas_publicas(pagina: str) -> None:
    fonte = (RAIZ / "chat-ui" / "src" / "pages" / pagina).read_text(encoding="utf-8")

    assert 'from "../components/TawkChat"' in fonte
    assert "<TawkChat />" in fonte
