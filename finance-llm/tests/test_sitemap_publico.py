"""Robots e sitemaps: as páginas públicas do domínio chegam todas aos motores de busca.

No mesmo domínio há **três** sítios com páginas públicas — a aplicação (a SPA), o
site do CMS (`/site/…`) e a loja (`/loja/…`) — e cada um gera o seu sitemap a
partir dos dados que tem. O que se testa aqui:

* o `robots.txt` da raiz (o único que os motores de busca lêem: os de
  `/site/robots.txt` e `/loja/robots.txt` não são consultados) aponta para o
  índice e deixa passar os dois, mantendo fora as áreas privadas;
* o `/sitemap.xml` é um **índice** e referencia os três sitemaps;
* o sitemap da aplicação não lista nenhuma página que o `robots.txt` proíbe —
  uma contradição que o motor de busca resolve sempre contra a página;
* o sitemap da loja e o do site saem com URLs absolutos mesmo sem `base_url`
  configurado: um `<loc>` relativo invalida o ficheiro inteiro, e o da loja saía
  assim (`<loc>/loja</loc>`, sem origem nenhuma).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from xml.etree import ElementTree

import pytest

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from api import benchmarks_store  # noqa: E402
from api import cms_render  # noqa: E402
from api import cms_store  # noqa: E402
from api import shop_render  # noqa: E402
from api import shop_store  # noqa: E402

PUBLIC = RAIZ / "chat-ui" / "public"
NS_SITEMAP = "{http://www.sitemaps.org/schemas/sitemap/0.9}"


@pytest.fixture()
def instalacao_limpa(tmp_path, monkeypatch):
    """Site e loja isolados em `tmp_path` (sem ler nem escrever em `data/`)."""
    cms = tmp_path / "cms"
    monkeypatch.setattr(cms_store, "CMS_DIR", cms)
    monkeypatch.setattr(cms_store, "CMS_PATH", cms / "cms.json")
    monkeypatch.setattr(cms_store, "MEDIA_DIR", cms / "media")
    monkeypatch.setattr(cms_store, "_cache", None)
    monkeypatch.setattr(cms_store, "_cache_mtime", None)

    loja = tmp_path / "shop"
    monkeypatch.setattr(shop_store, "SHOP_DIR", loja)
    monkeypatch.setattr(shop_store, "SHOP_PATH", loja / "shop.json")
    monkeypatch.setattr(shop_store, "FILES_DIR", loja / "files")
    monkeypatch.setattr(shop_store, "_cache", None)
    monkeypatch.setattr(shop_store, "_cache_mtime", None)
    yield


def _locs(xml: str) -> list[str]:
    raiz = ElementTree.fromstring(xml)
    return [elemento.text or "" for elemento in raiz.iter(f"{NS_SITEMAP}loc")]


def _proibidos(robots: str) -> list[str]:
    return [
        linha.split(":", 1)[1].strip()
        for linha in robots.splitlines()
        if linha.lower().startswith("disallow:")
    ]


# ------------------------------------------------------------- robots da raiz
def test_robots_da_raiz_aponta_para_o_indice_de_sitemaps() -> None:
    robots = (PUBLIC / "robots.txt").read_text(encoding="utf-8")
    assert "Sitemap: https://sabemos.studio/sitemap.xml" in robots


def test_robots_da_raiz_declara_tambem_os_tres_sitemaps() -> None:
    """O índice é o caminho principal, mas cada sitemap vai declarado: se o índice
    falhar, os motores ainda têm por onde encontrar as páginas."""
    robots = (PUBLIC / "robots.txt").read_text(encoding="utf-8")
    for sitemap in ("sitemap-app.xml", "site/sitemap.xml", "loja/sitemap.xml"):
        assert f"Sitemap: https://sabemos.studio/{sitemap}" in robots


def test_robots_da_raiz_deixa_passar_o_site_e_a_loja() -> None:
    robots = (PUBLIC / "robots.txt").read_text(encoding="utf-8")
    assert "Allow: /site/" in robots
    assert "Allow: /loja/" in robots


def test_robots_da_raiz_fecha_as_areas_privadas() -> None:
    robots = (PUBLIC / "robots.txt").read_text(encoding="utf-8")
    proibidos = _proibidos(robots)
    for caminho in (
        "/api/",
        "/admin/",
        "/cms/",
        "/chat",
        "/settings/",
        "/login",
        "/register",
        "/shop",
        "/loja/carrinho",
        "/loja/encomenda",
    ):
        assert caminho in proibidos, f"{caminho} ficou acessível aos motores de busca"


def test_robots_da_raiz_usa_regras_uma_por_linha() -> None:
    """Cada regra é um caminho absoluto (`/…`) numa linha própria — é o formato
    que todos os rastreadores lêem."""
    robots = (PUBLIC / "robots.txt").read_text(encoding="utf-8")
    regras = [linha for linha in robots.splitlines() if re.match(r"(?i)^(allow|disallow):", linha)]
    assert regras
    for linha in regras:
        valor = linha.split(":", 1)[1].strip()
        assert valor.startswith("/"), linha
        assert " " not in valor, linha


# ------------------------------------------------------------ índice e aplicação
def test_sitemap_da_raiz_e_um_indice_com_os_tres_sitemaps() -> None:
    indice = (PUBLIC / "sitemap.xml").read_text(encoding="utf-8")
    raiz = ElementTree.fromstring(indice)
    assert raiz.tag == f"{NS_SITEMAP}sitemapindex"
    assert _locs(indice) == [
        "https://sabemos.studio/sitemap-app.xml",
        "https://sabemos.studio/site/sitemap.xml",
        "https://sabemos.studio/loja/sitemap.xml",
    ]


def test_sitemap_da_aplicacao_tem_só_urls_absolutas() -> None:
    sitemap = (PUBLIC / "sitemap-app.xml").read_text(encoding="utf-8")
    locs = _locs(sitemap)
    assert locs
    for loc in locs:
        assert loc.startswith("https://sabemos.studio"), loc


def test_sitemap_da_aplicacao_nao_lista_paginas_proibidas() -> None:
    """Sitemap e robots a dizerem coisas diferentes só gasta orçamento de rastreio."""
    robots = (PUBLIC / "robots.txt").read_text(encoding="utf-8")
    proibidos = _proibidos(robots)
    for loc in _locs((PUBLIC / "sitemap-app.xml").read_text(encoding="utf-8")):
        caminho = loc.split("sabemos.studio", 1)[1] or "/"
        for regra in proibidos:
            assert not caminho.startswith(regra), f"{caminho} está no sitemap e no Disallow ({regra})"


def test_sitemap_da_aplicacao_tem_a_home_e_as_paginas_de_entrada() -> None:
    locs = _locs((PUBLIC / "sitemap-app.xml").read_text(encoding="utf-8"))
    for caminho in (
        "https://sabemos.studio/",
        "https://sabemos.studio/benchmark",
        "https://sabemos.studio/contracts/search",
        "https://sabemos.studio/companies/search",
        # Tem título e descrição próprios no índice da SPA: estava fora do sitemap.
        "https://sabemos.studio/administracao-central",
    ):
        assert caminho in locs


# ---------------------------------------------------------------------- loja
def test_sitemap_da_loja_e_absoluto_mesmo_sem_base_url(instalacao_limpa) -> None:
    sitemap = shop_render.render_sitemap(settings={})
    locs = _locs(sitemap)
    assert locs
    for loc in locs:
        assert loc.startswith(shop_render.DEFAULT_BASE_URL), loc
    assert f"{shop_render.DEFAULT_BASE_URL}/loja" in locs


def test_robots_da_loja_indica_o_sitemap_sem_base_url(instalacao_limpa) -> None:
    robots = shop_render.render_robots(settings={})
    assert "Sitemap: https://sabemos.studio/loja/sitemap.xml" in robots
    assert "Disallow: /loja/carrinho" in robots


def test_sitemap_da_loja_respeita_o_base_url_configurado(instalacao_limpa) -> None:
    sitemap = shop_render.render_sitemap(settings={"base_url": "https://loja.exemplo.pt/"})
    assert all(loc.startswith("https://loja.exemplo.pt/") for loc in _locs(sitemap))
    assert "https://loja.exemplo.pt/loja" in _locs(sitemap)


# ---------------------------------------------------------------------- site
def test_sitemap_do_site_e_absoluto_mesmo_sem_base_url(instalacao_limpa) -> None:
    sitemap = cms_render.render_sitemap({})
    locs = _locs(sitemap)
    assert locs
    for loc in locs:
        assert loc.startswith(cms_render.DEFAULT_BASE_URL), loc
    assert f"{cms_render.DEFAULT_BASE_URL}/site/blog" in locs


def test_robots_do_site_indica_o_sitemap_sem_base_url(instalacao_limpa) -> None:
    robots = cms_render.render_robots({})
    assert "Sitemap: https://sabemos.studio/site/sitemap.xml" in robots
    assert "Allow: /site/" in robots


def test_sitemap_do_site_nao_repete_enderecos(instalacao_limpa) -> None:
    """`/site/blog` é uma página do CMS **e** o índice do blog: duas regras, um
    `<loc>`. Repetido, o sitemap é um aviso no Search Console."""
    locs = _locs(cms_render.render_sitemap({}))
    assert f"{cms_render.DEFAULT_BASE_URL}/site/blog" in locs
    assert len(locs) == len(set(locs)), [loc for loc in locs if locs.count(loc) > 1]


def test_sitemap_do_site_inclui_os_benchmarks_publicados(instalacao_limpa, monkeypatch) -> None:
    """A página do estudo é uma página do CMS, mas a versão com a pesquisa
    agregada tem endereço próprio e tem de entrar no sitemap — estava de fora."""
    monkeypatch.setattr(
        benchmarks_store,
        "publicos",
        lambda: [{"slug": "portateis-lojas", "public": True, "public_at": "2026-10-01T10:00:00Z"}],
    )
    xml = cms_render.render_sitemap({})
    endereco = f"{cms_render.DEFAULT_BASE_URL}/site/benchmarks/portateis-lojas/pesquisa"
    assert endereco in _locs(xml)
    # O `lastmod` é o dia em que o estudo foi publicado no site.
    assert f"<loc>{endereco}</loc><lastmod>2026-10-01</lastmod>" in xml


def test_sitemap_do_site_ignora_benchmarks_nao_publicados(instalacao_limpa, monkeypatch) -> None:
    """O que não está publicado não entra: a lista sai do mesmo sítio que a
    página pública usa para decidir o que mostrar."""
    monkeypatch.setattr(benchmarks_store, "publicos", lambda: [])
    locs = _locs(cms_render.render_sitemap({}))
    assert not [loc for loc in locs if "benchmarks/" in loc and loc.endswith("/pesquisa")]


# ------------------------------------------------------- canónicas com origem
def test_pagina_da_loja_sai_com_canonica_e_og_url_absolutos(instalacao_limpa) -> None:
    """Sem `base_url`, a canónica e o `og:url` têm de sair absolutos na mesma —
    o Open Graph exige URL absoluto, e o valor tem de bater com o do sitemap."""
    shop_store.reset_seed()
    produto = shop_store.get_item("products", shop_store.list_items("products")["items"][0]["id"])

    pagina = shop_render.render_product(produto, settings={})

    assert f'<link rel="canonical" href="{shop_render.DEFAULT_BASE_URL}/loja/produto/' in pagina
    assert f'<meta property="og:url" content="{shop_render.DEFAULT_BASE_URL}/loja/produto/' in pagina
    assert 'content="/loja/produto/' not in pagina


def test_canonica_da_loja_respeita_o_base_url_configurado(instalacao_limpa) -> None:
    pagina = shop_render.render_home(settings={"base_url": "https://loja.exemplo.pt/"})
    assert '<link rel="canonical" href="https://loja.exemplo.pt/loja">' in pagina
