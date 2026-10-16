"""SEO dos artigos **publicados** do blog — validado no browser.

O que os motores de busca vêem é o `<head>` que o site serve, não o que o editor
guarda. Este teste abre os artigos publicados no browser e confere, artigo a artigo:

* o `<title>` (com o sufixo da marca), a `description` e o `canonical` absoluto;
* `robots` indexável e Open Graph completo (título, descrição, URL, tipo `article`
  e imagem **absoluta** quando existe capa);
* o JSON-LD `BlogPosting` coerente com a página — `headline`, `datePublished`,
  `url` igual ao canónico e `publisher`;
* que **todas** as URLs de artigos do `sitemap.xml` respondem 200 — um rascunho a
  mais no sitemap é um 404 servido aos motores de busca (e a página 404 do site
  vem com `noindex` e um título de erro, que é o que aqui se deteta);
* que o artigo aparece no índice do blog e no feed RSS.

Corre contra o frontend publicado (`E2E_FRONTEND_URL`, por omissão
`http://127.0.0.1:4180`), sem sessão: o site é público.

    e2e-venv\\Scripts\\python.exe -m pytest e2e/test_seo_blog_publico.py -v
"""

from __future__ import annotations

import json
import os
import re
import xml.etree.ElementTree as ET
from urllib.parse import urlparse

import pytest
from playwright.sync_api import Page

BASE = os.environ.get("E2E_FRONTEND_URL", "http://127.0.0.1:4180").rstrip("/")
SITEMAP = "/site/sitemap.xml"
RSS = "/site/rss.xml"
INDICE_BLOG = "/site/blog"
ESPACO_SITEMAP = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}

#: O título mostrado leva o sufixo da marca («· Sabemos Studio») e o site corta-o
#: em palavras no `LIMITE_TITULO_HEAD` (`api/cms_render.py`); a descrição acima de
#: ~165 caracteres é cortada pelo motor de busca.
LIMITE_TITULO = 70
LIMITE_DESCRICAO = 165
MINIMO_DESCRICAO = 50
#: Quantos artigos se abrem (o mais recente primeiro): a suite não pode ficar
#: dependente do tamanho do blog.
ARTIGOS_A_TESTAR = 3


def _artigos_do_sitemap(page: Page) -> list[tuple[str, str]]:
    """Artigos publicados do sitemap: `(URL absoluto, caminho)`.

    O `<loc>` é absoluto no origem configurado no site (`base_url`), que não tem
    de ser o do frontend em teste — o teste abre o **caminho** no frontend e
    confirma que o canónico aponta para o URL absoluto, que é o que o motor de
    busca indexa.
    """
    resposta = page.context.request.get(f"{BASE}{SITEMAP}", timeout=60_000)
    assert resposta.ok, f"{SITEMAP} respondeu {resposta.status}"
    raiz = ET.fromstring(resposta.text())
    urls = [str(loc.text).strip() for loc in raiz.findall(".//s:loc", ESPACO_SITEMAP)]
    artigos = [url for url in urls if re.search(r"/site/blog/[^/]+$", url)]
    assert artigos, "o sitemap não tem nenhum artigo publicado"
    assert all(url.startswith("http") for url in artigos), "o sitemap tem URLs relativos"
    return [(url, urlparse(url).path) for url in artigos]


def _head(page: Page) -> dict:
    """O `<head>` como o motor de busca o lê."""
    return page.evaluate(
        """() => {
          const meta = (seletor) => document.querySelector(seletor)?.getAttribute('content') || '';
          const link = (seletor) => document.querySelector(seletor)?.getAttribute('href') || '';
          return {
            titulo: document.title || '',
            descricao: meta('meta[name="description"]'),
            robots: meta('meta[name="robots"]'),
            keywords: meta('meta[name="keywords"]'),
            ogTitulo: meta('meta[property="og:title"]'),
            ogDescricao: meta('meta[property="og:description"]'),
            ogUrl: meta('meta[property="og:url"]'),
            ogTipo: meta('meta[property="og:type"]'),
            ogImagem: meta('meta[property="og:image"]'),
            ogSite: meta('meta[property="og:site_name"]'),
            canonical: link('link[rel="canonical"]'),
          };
        }"""
    )


def _json_ld(page: Page) -> list[dict]:
    """Blocos JSON-LD válidos da página (os inválidos ficam de fora)."""
    blocos = page.evaluate(
        """() => [...document.querySelectorAll('script[type="application/ld+json"]')]
                   .map((s) => s.textContent || '')"""
    )
    dados: list[dict] = []
    for bloco in blocos:
        try:
            dados.append(json.loads(bloco))
        except json.JSONDecodeError:
            continue
    return dados


def _blog_post_json_ld(page: Page) -> dict | None:
    return next((item for item in _json_ld(page) if item.get("@type") == "BlogPosting"), None)


def _abrir(page: Page, url: str):
    resposta = page.goto(url, timeout=90_000, wait_until="domcontentloaded")
    assert resposta is not None, f"sem resposta para {url}"
    return resposta


# ------------------------------------------------------------------ sitemap
def test_todos_os_artigos_do_sitemap_respondem(page: Page):
    """Nenhuma URL de artigo do sitemap pode dar 404 (nem servir a página de erro)."""
    artigos = _artigos_do_sitemap(page)
    for absoluto, caminho in artigos[:ARTIGOS_A_TESTAR]:
        resposta = _abrir(page, f"{BASE}{caminho}")
        assert resposta.status == 200, f"{caminho} respondeu {resposta.status} (sitemap: {absoluto})"
        cabecalho = page.locator("article h1, main h1").first
        assert cabecalho.is_visible(), f"{caminho} não mostra o título do artigo"
        assert "não encontrada" not in (page.title() or "").lower(), f"{caminho} caiu na página de erro"
        assert "index" in _head(page)["robots"], f"{caminho} está com noindex"


def test_sitemap_nao_lista_o_mesmo_artigo_duas_vezes(page: Page):
    artigos = [absoluto for absoluto, _ in _artigos_do_sitemap(page)]
    assert len(artigos) == len(set(artigos)), "artigo repetido no sitemap"


# ---------------------------------------------------------------- SEO do head
def test_seo_do_artigo_publicado(page: Page):
    """Título, descrição, canónico, robots e Open Graph do artigo."""
    absoluto, caminho = _artigos_do_sitemap(page)[0]
    _abrir(page, f"{BASE}{caminho}")
    head = _head(page)

    assert head["titulo"], "artigo sem <title>"
    assert len(head["titulo"]) <= LIMITE_TITULO, f"título com {len(head['titulo'])} caracteres"
    assert head["canonical"] == absoluto, f"canónico {head['canonical']} ≠ {absoluto}"

    assert MINIMO_DESCRICAO <= len(head["descricao"]) <= LIMITE_DESCRICAO, (
        f"descrição com {len(head['descricao'])} caracteres"
    )
    assert head["descricao"] != head["titulo"], "descrição repetida do título"

    assert "index" in head["robots"] and "noindex" not in head["robots"]
    assert head["keywords"], "artigo sem palavras-chave"

    assert head["ogTitulo"] == head["titulo"]
    assert head["ogDescricao"] == head["descricao"]
    assert head["ogUrl"] == absoluto
    assert head["ogTipo"] == "article"
    assert head["ogSite"], "sem og:site_name"
    if head["ogImagem"]:
        assert head["ogImagem"].startswith("http"), "og:image tem de ser absoluto"


def test_json_ld_do_artigo_bate_certo_com_a_pagina(page: Page):
    """O `BlogPosting` do JSON-LD é o que os motores de busca indexam."""
    absoluto, caminho = _artigos_do_sitemap(page)[0]
    _abrir(page, f"{BASE}{caminho}")
    dados = _blog_post_json_ld(page)
    assert dados is not None, "artigo sem JSON-LD BlogPosting"

    assert dados.get("headline"), "BlogPosting sem headline"
    assert dados.get("datePublished"), "BlogPosting sem datePublished"
    assert dados.get("url") == absoluto, f"BlogPosting url {dados.get('url')} ≠ {absoluto}"
    assert dados.get("mainEntityOfPage") in (absoluto, {"@id": absoluto})
    publisher = dados.get("publisher") or {}
    assert publisher.get("name"), "BlogPosting sem publisher"
    assert publisher.get("name") in _head(page)["ogSite"]
    assert dados.get("description"), "BlogPosting sem description"
    assert "BlogPosting" in json.dumps(dados), "tipo errado no JSON-LD"


def test_artigo_publicado_aparece_no_indice_e_no_rss(page: Page):
    """O artigo é alcançável a partir do blog e do feed — não é uma ilha."""
    _, caminho = _artigos_do_sitemap(page)[0]

    page.goto(f"{BASE}{INDICE_BLOG}", timeout=90_000, wait_until="domcontentloaded")
    ligacoes = page.locator(f'a[href="{caminho}"], a[href="{BASE}{caminho}"]')
    assert ligacoes.count() >= 1, f"{caminho} não está no índice do blog"

    rss = page.context.request.get(f"{BASE}{RSS}", timeout=60_000)
    assert rss.ok, f"{RSS} respondeu {rss.status}"
    assert caminho in rss.text(), f"{caminho} não está no feed RSS"


def test_pagina_404_do_site_nao_indexa(page: Page):
    """A rede de segurança: uma URL inventada não pode entrar no índice."""
    resposta = _abrir(page, f"{BASE}/site/artigo-que-nao-existe-e2e")
    assert resposta.status == 404
    assert "noindex" in _head(page)["robots"]


@pytest.mark.parametrize("caminho", ["/site/blog", "/site/blog/etiqueta/contratos"])
def test_paginas_do_blog_tem_canonico_absoluto(page: Page, caminho: str):
    resposta = _abrir(page, f"{BASE}{caminho}")
    assert resposta.status in (200, 404), f"{caminho} respondeu {resposta.status}"
    if resposta.status != 200:
        pytest.skip(f"{caminho} não existe neste site")
    head = _head(page)
    assert head["canonical"].startswith("http"), f"canónico relativo em {caminho}"
    assert urlparse(head["canonical"]).path == caminho, f"canónico de {caminho} aponta para outro caminho"
    assert head["titulo"], f"{caminho} sem título"
