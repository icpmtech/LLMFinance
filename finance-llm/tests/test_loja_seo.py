"""SEO da loja: campos das definições e de cada produto/categoria a chegar ao HTML.

O que se fixa aqui é o que estava a faltar: os campos de SEO **eram guardados e
ignorados** — o editor da loja gravava `seo.title`, `seo.description`,
`seo.keywords` e `seo.noindex` (nas definições, em cada produto e em cada
categoria) e a montra continuava a usar o nome do produto e a descrição da loja.

Testa-se também o que os motores de busca exigem e o que o Google usa para os
resultados: `og:image` e os URLs do JSON-LD (`Store`, `Product`, `ItemList`)
**absolutos**, `BreadcrumbList` nas fichas e nas categorias, `lastmod` no
sitemap, e o `noindex` de um produto a tirá-lo do sitemap.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from xml.etree import ElementTree

import pytest

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from api import cms_render  # noqa: E402
from api import cms_store  # noqa: E402
from api import shop_render as render  # noqa: E402
from api import shop_store as store  # noqa: E402

NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"

SEO_LOJA = {
    "title": "Sabemos — relatórios e dados de contratação pública",
    "description": "Relatórios, dossiês de empresa e de mercado, dados e formação sobre contratação pública.",
    "keywords": ["contratação pública", "relatórios", "benchmark de preços"],
}


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
    store.reset_seed()
    return store


def _meta(html: str, padrao: str) -> str:
    achado = re.search(padrao, html, re.I | re.S)
    return achado.group(1).strip() if achado else ""


def _json_ld(html: str) -> list[dict]:
    blocos = re.findall(r'(?is)<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html)
    return [json.loads(bloco) for bloco in blocos]


def _tipos(html: str) -> list[str]:
    return [str(item.get("@type")) for item in _json_ld(html)]


def _produto(slug: str) -> dict:
    itens = store.list_items("products")["items"]
    alvo = next(item for item in itens if item.get("slug") == slug)
    return store.get_item("products", alvo["id"])


# ----------------------------------------------------------------- definições
def test_definicoes_de_seo_da_loja_chegam_a_home(loja) -> None:
    loja.save_settings({"seo": SEO_LOJA}, "qa")

    html = render.render_home(settings=loja.get_settings())

    assert SEO_LOJA["title"] in _meta(html, r"<title[^>]*>(.*?)</title>")
    assert _meta(html, r'<meta name="description" content="([^"]*)"') == SEO_LOJA["description"]
    assert "contratação pública" in _meta(html, r'<meta name="keywords" content="([^"]*)"')


def test_home_sem_seo_proprio_mantem_o_nome_da_loja(loja) -> None:
    html = render.render_home(settings=loja.get_settings())

    assert _meta(html, r"<title[^>]*>(.*?)</title>") == loja.get_settings()["store_name"]


def test_json_ld_da_loja_tem_urls_absolutos(loja) -> None:
    """`url`/`image` relativos não servem para a ficha da loja nos resultados."""
    html = render.render_home(settings=loja.get_settings())
    loja_ld = next(item for item in _json_ld(html) if item.get("@type") == "Store")

    assert loja_ld["url"] == f"{render.DEFAULT_BASE_URL}/loja"
    assert loja_ld["image"].startswith(f"{render.DEFAULT_BASE_URL}/loja/pwa/")
    assert loja_ld["image"].endswith(".png")


def test_base_url_configurado_e_o_que_aparece(loja) -> None:
    html = render.render_home(settings={**loja.get_settings(), "base_url": "https://loja.exemplo.pt/"})
    loja_ld = next(item for item in _json_ld(html) if item.get("@type") == "Store")

    assert loja_ld["url"] == "https://loja.exemplo.pt/loja"
    assert '<link rel="canonical" href="https://loja.exemplo.pt/loja">' in html


# ------------------------------------------------------------------ cabeçalho
def test_home_tem_um_so_h1(loja) -> None:
    html = render.render_home(settings=loja.get_settings())

    assert html.count("<h1") == 1
    assert "<h1>Inteligência financeira, pronta a usar</h1>" in html  # o título do «hero»


def test_home_sem_hero_com_titulo_nao_fica_sem_h1(loja) -> None:
    """O `<h1>` da vitrine vinha **só** do «hero».

    Com as secções todas sem título, a loja saía sem cabeçalho nenhum — o erro
    «H1 tag missing» dos relatórios de SEO. Nesse caso o nome da loja passa a
    ser o cabeçalho.
    """
    tema = loja.get_theme()
    tema["sections"] = [{"id": "sec_texto", "type": "texto", "markdown": "Texto corrido."}]
    loja.save_theme(tema)

    html = render.render_home(settings=loja.get_settings())

    assert html.count("<h1") == 1
    assert f'<h1>{loja.get_settings()["store_name"]}</h1>' in html


# --------------------------------------------------------------------- produto
def test_seo_do_produto_substitui_o_gerado(loja) -> None:
    produto = _produto("assinatura-analista")
    loja.save_item(
        "products",
        {**produto, "seo": {"title": "Assinatura Analista — acesso mensal", "description": "Pesquisa 360 e dossiês.", "keywords": ["assinatura", "plataforma"]}},
        "qa",
    )

    html = render.render_product(_produto("assinatura-analista"), settings=loja.get_settings())

    assert _meta(html, r"<title[^>]*>(.*?)</title>").startswith("Assinatura Analista — acesso mensal")
    assert _meta(html, r'<meta name="description" content="([^"]*)"') == "Pesquisa 360 e dossiês."
    assert "assinatura, plataforma" in _meta(html, r'<meta name="keywords" content="([^"]*)"')


def test_produto_com_noindex_sai_do_indice_e_do_sitemap(loja) -> None:
    produto = _produto("dossie-de-mercado")
    assert f'{render.DEFAULT_BASE_URL}/loja/produto/dossie-de-mercado' in render.render_sitemap(settings=loja.get_settings())

    loja.save_item("products", {**produto, "seo": {"noindex": True}}, "qa")

    html = render.render_product(_produto("dossie-de-mercado"), settings=loja.get_settings())
    assert 'name="robots" content="noindex, nofollow"' in html
    assert "/loja/produto/dossie-de-mercado" not in render.render_sitemap(settings=loja.get_settings())


def test_json_ld_do_produto_com_imagens_e_urls_absolutos(loja) -> None:
    html = render.render_product(_produto("assinatura-analista"), settings=loja.get_settings())
    produto_ld = next(item for item in _json_ld(html) if item.get("@type") == "Product")

    assert produto_ld["image"], "o produto tem de levar imagens"
    assert all(url.startswith("https://") for url in produto_ld["image"]), produto_ld["image"]
    assert produto_ld["offers"]["url"].startswith(f"{render.DEFAULT_BASE_URL}/loja/produto/")
    assert produto_ld["offers"]["price"], "sem preço não há resultado de produto"
    assert produto_ld["brand"]["name"] == loja.get_settings()["store_name"]
    assert _meta(html, r'<meta property="og:image" content="([^"]*)"').startswith("https://")


def test_ficha_de_produto_tem_migalhas(loja) -> None:
    html = render.render_product(_produto("assinatura-analista"), settings=loja.get_settings())
    migalhas = next(item for item in _json_ld(html) if item.get("@type") == "BreadcrumbList")
    niveis = [elemento["name"] for elemento in migalhas["itemListElement"]]

    assert niveis == ["Loja", "Produtos", "Assinatura IQ OS — Analista (mensal)"]
    assert migalhas["itemListElement"][0]["item"] == f"{render.DEFAULT_BASE_URL}/loja"
    # O último nível vai sem `item`, como a Google recomenda.
    assert "item" not in migalhas["itemListElement"][-1]


# ------------------------------------------------------------------- categoria
def test_categoria_usa_o_proprio_seo_e_migalhas(loja) -> None:
    categoria = next(item for item in store.list_items("categories")["items"] if item.get("slug") == "relatorios")
    loja.save_item("categories", {**categoria, "seo": {"title": "Relatórios de contratação pública", "description": "Prontos a usar."}}, "qa")
    categoria = next(item for item in store.list_items("categories")["items"] if item.get("slug") == "relatorios")

    html = render.render_catalogue([], settings=loja.get_settings(), current_category=categoria, title="Relatórios")

    assert _meta(html, r"<title[^>]*>(.*?)</title>").startswith("Relatórios de contratação pública")
    assert _meta(html, r'<meta name="description" content="([^"]*)"') == "Prontos a usar."
    assert "BreadcrumbList" in _tipos(html)


# ---------------------------------------------------------------------- sitemap
def test_sitemap_da_loja_leva_lastmod(loja) -> None:
    sitemap = render.render_sitemap(settings=loja.get_settings())
    raiz = ElementTree.fromstring(sitemap)
    produtos = [url for url in raiz.iter(f"{NS}url") if "/loja/produto/" in (url.find(f"{NS}loc").text or "")]

    assert produtos, "o catálogo tem produtos publicados"
    assert all(url.find(f"{NS}lastmod") is not None for url in produtos), "sem lastmod o rastreador não sabe o que mudou"
    assert all(re.fullmatch(r"\d{4}-\d{2}-\d{2}", url.find(f"{NS}lastmod").text or "") for url in produtos)


def test_url_absoluto_completa_o_que_e_relativo(loja) -> None:
    assert render._url_absoluto("/cms/media/med_1/raw", "https://x.pt") == "https://x.pt/cms/media/med_1/raw"
    assert render._url_absoluto("https://outro.pt/a.png", "https://x.pt") == "https://outro.pt/a.png"
    assert render._url_absoluto("", "https://x.pt") == ""
