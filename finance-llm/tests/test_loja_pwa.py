"""Loja: imagens de marca dos produtos e loja instalável (PWA).

A montra (`/loja/…`) é HTML gerado pelo backend, sem passo de build de frontend.
O que se testa aqui é que:

* cada produto do catálogo fica com a imagem de marca que **viaja com o código**,
  ligada pela biblioteca de media do CMS (cujo id é aleatório em cada instalação)
  e copiada para o disco dessa instalação;
* a loja se instala como aplicação — manifesto, service worker, ícones e página
  sem rede — e usa caches próprias, para não apagar as caches do site público e
  da plataforma, que vivem no mesmo domínio.

O que isto previne é a montra nascer sem imagens (ou com a imagem trocada) numa
instalação nova, e um service worker da loja que, na ativação, apaga as caches
dos outros dois PWAs.
"""
from __future__ import annotations

import json

import pytest
from fastapi import HTTPException

from api import cms_render
from api import cms_store
from api import shop_render as render
from api import shop_routes as routes
from api import shop_store as store


@pytest.fixture()
def loja(tmp_path, monkeypatch):
    """Loja e biblioteca de media isoladas em `tmp_path` (sem tocar em `data/`)."""
    monkeypatch.setattr(store, "SHOP_DIR", tmp_path / "shop")
    monkeypatch.setattr(store, "SHOP_PATH", tmp_path / "shop" / "shop.json")
    monkeypatch.setattr(store, "FILES_DIR", tmp_path / "shop" / "files")
    monkeypatch.setattr(store, "_cache", None)
    monkeypatch.setattr(store, "_cache_mtime", None)

    cms = tmp_path / "cms"
    monkeypatch.setattr(cms_store, "CMS_DIR", cms)
    monkeypatch.setattr(cms_store, "CMS_PATH", cms / "cms.json")
    monkeypatch.setattr(cms_store, "MEDIA_DIR", cms / "media")
    monkeypatch.setattr(cms_store, "_cache", None)
    monkeypatch.setattr(cms_store, "_cache_mtime", None)
    yield store


def _produtos() -> dict:
    """Produtos por `slug`, com o documento completo (o índice não traz os ids das imagens)."""
    return {
        doc["slug"]: doc
        for doc in (store.get_item("products", item["id"]) for item in store.list_items("products")["items"])
    }


def _media_por_ficheiro() -> dict:
    itens = cms_store.list_items("media", limit=400)["items"]
    return {item["filename"]: item for item in itens}


def test_cada_produto_fica_com_a_sua_imagem_de_marca(loja):
    loja.reset_seed()
    produtos = _produtos()
    media = _media_por_ficheiro()
    assert store.IMAGENS_PRODUTO, "o catálogo de demonstração tem de ter imagens declaradas"
    for slug, ficheiro in store.IMAGENS_PRODUTO.items():
        assert ficheiro in media, f"{ficheiro} não foi instalado na biblioteca"
        assert produtos[slug]["image_ids"] == [media[ficheiro]["id"]], slug


def test_imagem_instalada_e_a_copia_do_asset_do_codigo(loja):
    loja.reset_seed()
    for ficheiro in store.IMAGENS_PRODUTO.values():
        media = _media_por_ficheiro()[ficheiro]
        assert media["width"] == 800 and media["height"] == 600, ficheiro
        copia = cms_store.MEDIA_DIR / f"{media['id']}{media['extension']}"
        assert copia.read_bytes() == (cms_store.SITE_ASSETS_DIR / ficheiro).read_bytes()


def test_instalar_imagens_nao_duplica_nem_troca_o_que_existe(loja):
    loja.reset_seed()
    antes = len(cms_store.list_items("media", limit=400)["items"])
    assert store.instalar_imagens_de_produto()["instalados"] == 0, "a semente já ligou todas as imagens"
    assert len(cms_store.list_items("media", limit=400)["items"]) == antes

    produto = next(item for item in loja.list_items("products")["items"] if item["slug"] == "dossie-de-empresa")
    doc = loja.get_item("products", produto["id"])
    loja.save_item("products", {**doc, "image_ids": ["med_proprio"]})
    store.instalar_imagens_de_produto()
    assert loja.get_item("products", produto["id"])["image_ids"] == ["med_proprio"], "não pode desfazer uma escolha da loja"


def test_manifesto_identifica_a_loja_e_o_que_se_instala(loja):
    loja.reset_seed()
    settings = loja.get_settings()
    manifest = json.loads(render.render_manifest(settings))
    assert manifest["name"] == settings["store_name"] == "Sabemos"
    assert manifest["short_name"] == "Sabemos"
    assert manifest["start_url"] == manifest["scope"] == "/loja/"
    assert manifest["id"] == "/loja/"
    assert manifest["theme_color"] == settings["accent"]
    assert {icone["src"] for icone in manifest["icons"]} == {
        "/loja/pwa/pwa-icone-192.png",
        "/loja/pwa/pwa-icone-512.png",
        "/loja/pwa/pwa-icone-maskable-512.png",
    }
    assert any(atalho["url"] == "/loja/carrinho" for atalho in manifest["shortcuts"])


def test_service_worker_da_loja_nao_mexe_nas_caches_dos_outros_pwa(loja):
    loja.reset_seed()
    js = render.render_service_worker(loja.get_settings())
    assert render.PWA_CACHE_PREFIX != cms_render.PWA_CACHE_PREFIX
    assert f'{render.PWA_CACHE_PREFIX}paginas-{render.PWA_SW_VERSION}' in js
    for marcador in ("__VERSAO__", "__CACHE_PAGINAS__", "__CACHE_RECURSOS__", "__PREFIXO__", "__OFFLINE__", "__SW__", "__MANIFEST__", "__RECURSOS__"):
        assert marcador not in js, marcador
    assert '"/loja/pwa/pwa-icone-512.png"' in js
    # O que tem estado (carrinho, recibos, gestão e API) nunca vem do cache.
    for caminho in ('"/loja/carrinho"', '"/loja/conta"', '"/shop/"', '"/api/"'):
        assert caminho in js, caminho


def test_vitrine_e_instalavel_e_o_desktop_e_que_e_o_acrescimo(loja):
    loja.reset_seed()
    html = render.render_home(settings=loja.get_settings())
    assert '<link rel="manifest" href="/loja/manifest.webmanifest">' in html
    assert 'content="width=device-width, initial-scale=1, viewport-fit=cover"' in html
    assert 'navigator.serviceWorker.register("/loja/sw.js")' in html
    css = render._css(loja.get_settings())
    # Mobile first: o que está fora das media queries é o desenho do telefone.
    assert "@media (max-width:" not in css
    assert "@media (min-width:900px)" in css
    assert "minmax(158px,1fr)" in css, "a grelha base tem de dar duas colunas num telefone"
    assert "buy-actions{display:grid" in css.replace(" ", "")


def test_pagina_sem_rede_existe_e_nao_se_indexa(loja):
    loja.reset_seed()
    html = render.render_offline(settings=loja.get_settings())
    assert "Sem ligação" in html
    assert 'content="noindex, nofollow"' in html


def test_icones_do_pwa_so_servem_os_nomes_conhecidos(loja):
    resposta = routes.loja_pwa_icon("pwa-icone-192.png")
    assert resposta.media_type == "image/png"
    with pytest.raises(HTTPException) as erro:
        routes.loja_pwa_icon("pwa-inexistente.png")
    assert erro.value.status_code == 404
    # Outros ficheiros da mesma pasta (o logótipo do site, por exemplo) não passam.
    with pytest.raises(HTTPException):
        routes.loja_pwa_icon("logo-sabemos-studio.svg")
