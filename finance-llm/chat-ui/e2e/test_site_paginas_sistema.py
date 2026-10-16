"""Testes de browser das páginas de sistema do site público.

As páginas de sistema são as que aparecem quando algo corre mal: endereço que não
existe (404), falha do serviço (500) e falta de rede (`/site/offline`, servida
pelo service worker). Também o `/erro.html` do nginx, que substitui o 502 cru
quando o backend não responde.

Cada teste navega a sério (o browser faz o pedido, o service worker entra em
jogo quando é preciso) e valida o que se vê — não só o texto: as caixas dos
elementos, a proporção da ilustração, o alinhamento com a trilha de navegação e
a ausência de estouro horizontal. De cada página fica uma captura em PNG no
diretório temporário do teste (`tmp_path`), para quem quiser confirmar a olho.

    e2e-venv\\Scripts\\python.exe -m pytest e2e/test_site_paginas_sistema.py -v
"""

from __future__ import annotations

import os
import re

import pytest
from playwright.sync_api import Page, expect

BASE = os.environ.get("E2E_FRONTEND_URL", "http://127.0.0.1:4180").rstrip("/")
COMPUTADOR = {"width": 1280, "height": 900}
TELEMOVEL = {"width": 390, "height": 844}

ENDERECO_QUE_NAO_EXISTE = "/site/endereco-que-nao-existe-e2e"
DESTINOS = ("/site/solucoes", "/site/relatorios-gratuitos", "/site/fontes", "/site/blog", "/site/contactos")


def _caixa(locator) -> dict:
    caixa = locator.bounding_box()
    assert caixa, "elemento sem caixa: não está visível"
    return caixa


def _texto_esquerda(locator) -> int:
    """Coordenada do início do texto (e não da caixa, que pode ter recuo)."""
    return int(
        locator.evaluate(
            """(e) => {
          const r = document.createRange();
          r.selectNodeContents(e);
          const caixas = [...r.getClientRects()].filter((c) => c.width > 1 && c.height > 1);
          return caixas.length ? Math.min(...caixas.map((c) => c.left)) : e.getBoundingClientRect().left;
        }"""
        )
    )


def _sem_estouro(page: Page) -> None:
    estouro = page.evaluate("() => document.documentElement.scrollWidth - window.innerWidth")
    assert estouro <= 1, f"a página estoura {estouro}px na horizontal"


def _sem_corte(locator, nome: str) -> None:
    """O conteúdo cabe na caixa (a folga cobre o arredondamento da caixa de linha)."""
    cortado = locator.evaluate("(e) => e.scrollHeight - e.clientHeight")
    assert cortado <= 4, f"{nome} está cortado ({cortado}px a mais)"


def _captura(page: Page, tmp_path, nome: str) -> None:
    """Guarda uma captura da página inteira para inspeção (não compara pixels)."""
    page.screenshot(path=str(tmp_path / f"{nome}.png"), full_page=True)


# --------------------------------------------------------------------------- 404
def test_pagina_404_traz_plataforma_humor_e_ilustracao(page: Page, tmp_path) -> None:
    resposta = page.goto(f"{BASE}{ENDERECO_QUE_NAO_EXISTE}")
    assert resposta is not None and resposta.status == 404, "o endereço inexistente tem de responder 404"

    expect(page.locator("main h1")).to_have_text("Este endereço não consta do cadastro")
    expect(page.locator(".sistema-nota")).to_contain_text("aditivos")

    # A ilustração é uma imagem a sério: tem texto alternativo, tamanho e proporção.
    imagem = page.locator(".sistema-imagem svg")
    expect(imagem).to_be_visible()
    assert imagem.get_attribute("role") == "img"
    assert "registo" in (imagem.get_attribute("aria-label") or ""), "a ilustração tem de ser informativa"
    caixa = _caixa(imagem)
    assert caixa["width"] > 360 and caixa["height"] > 200, caixa
    assert abs(caixa["width"] / caixa["height"] - 800 / 480) < 0.04, f"a ilustração perdeu a proporção: {caixa}"
    expect(page.locator(".sistema-imagem figcaption")).to_be_visible()

    # A plataforma e os destinos úteis estão à vista.
    expect(page.get_by_role("heading", name="O que é o Sabemos Studio")).to_be_visible()
    for destino in DESTINOS:
        expect(page.locator(f'.sistema-links a[href="{destino}"]')).to_be_visible()

    # Trilha de navegação: dois passos, o último marcado como atual.
    caminho = page.locator('nav[aria-label="Caminho"]')
    expect(caminho).to_be_visible()
    expect(caminho.locator("li")).to_have_count(2)
    expect(caminho.locator('li:last-child [aria-current="page"]')).to_have_text("Página não encontrada")

    _sem_corte(page.locator("main h1"), "o título")
    _sem_estouro(page)
    _captura(page, tmp_path, "404-computador")


def test_pagina_404_alinhada_e_sem_estouro_nos_dois_ecras(page: Page, tmp_path) -> None:
    # Computador: texto e ilustração lado a lado, título alinhado com a trilha.
    page.set_viewport_size(COMPUTADOR)
    page.goto(f"{BASE}{ENDERECO_QUE_NAO_EXISTE}")
    texto = _caixa(page.locator(".sistema-texto"))
    imagem = _caixa(page.locator(".sistema-imagem"))
    assert imagem["x"] > texto["x"] + texto["width"] - 40, f"as colunas sobrepõem-se: {texto} · {imagem}"
    assert abs(_texto_esquerda(page.locator("main h1")) - _texto_esquerda(page.locator(".breadcrumb"))) <= 1, (
        "o título não está alinhado com a trilha de navegação"
    )
    _captura(page, tmp_path, "404-computador-alinhamento")

    # Telemóvel: empilha (imagem por baixo do texto) e nada estoura.
    page.set_viewport_size(TELEMOVEL)
    page.goto(f"{BASE}{ENDERECO_QUE_NAO_EXISTE}")
    texto = _caixa(page.locator(".sistema-texto"))
    imagem = _caixa(page.locator(".sistema-imagem"))
    assert imagem["y"] > texto["y"] + texto["height"] - 40, f"no telemóvel devia empilhar: {texto} · {imagem}"
    assert imagem["width"] <= TELEMOVEL["width"], imagem
    _sem_estouro(page)
    _captura(page, tmp_path, "404-telemovel")


def test_pesquisa_da_pagina_404_leva_aos_resultados(page: Page) -> None:
    """Quem chega a um endereço errado pode procurar em vez de o corrigir."""
    page.goto(f"{BASE}{ENDERECO_QUE_NAO_EXISTE}")

    page.locator('.sistema-texto input[name="q"]').fill("contratos")
    page.locator('.sistema-texto button[type="submit"]').click()

    page.wait_for_url(re.compile(r"/site/pesquisa\?q=contratos"), timeout=30000)
    expect(page.locator("main h1")).to_contain_text("Pesquisar no site")
    assert page.locator("article.card").count() >= 1, "a pesquisa não devolveu resultados"


def test_acoes_da_pagina_404_navegam(page: Page) -> None:
    page.goto(f"{BASE}{ENDERECO_QUE_NAO_EXISTE}")

    page.get_by_role("link", name="Reportar o link").click()
    expect(page).to_have_url(re.compile(r"/site/contactos/?$"), timeout=30000)

    page.go_back()
    page.get_by_role("link", name="Ir para o início").click()
    expect(page).to_have_url(re.compile(r"/site/$"), timeout=30000)


# --------------------------------------------------------------- sem ligação
@pytest.fixture()
def contexto_sem_atalhos(browser):
    """Contexto próprio: o fixture `context` da suite desliga o service worker."""
    contexto = browser.new_context(viewport=COMPUTADOR)
    yield contexto
    contexto.close()


def _preparar_service_worker(page: Page) -> None:
    page.goto(f"{BASE}/site/", wait_until="domcontentloaded")
    page.evaluate("() => navigator.serviceWorker.ready")
    # O `install` precisa de um instante para guardar a página de recurso.
    page.wait_for_function(
        """async () => {
          const nomes = await caches.keys();
          const paginas = nomes.filter((n) => n.includes("paginas"));
          if (!paginas.length) return false;
          const cache = await caches.open(paginas[0]);
          const chaves = await cache.keys();
          return chaves.some((c) => c.url.endsWith("/site/offline"));
        }""",
        timeout=30000,
    )


def test_pagina_sem_ligacao_aparece_com_a_rede_desligada(contexto_sem_atalhos, tmp_path) -> None:
    page = contexto_sem_atalhos.new_page()
    _preparar_service_worker(page)

    contexto_sem_atalhos.set_offline(True)
    page.goto(f"{BASE}/site/endereco-nunca-visitado-e2e", wait_until="domcontentloaded")

    expect(page.locator("main h1")).to_contain_text("Sem rede")
    expect(page.locator(".sistema-nota")).to_contain_text("arquivo")
    imagem = page.locator(".sistema-imagem svg")
    expect(imagem).to_be_visible()
    assert "Ligação interrompida" in (imagem.get_attribute("aria-label") or "")
    caixa = _caixa(imagem)
    assert caixa["width"] > 360, "a ilustração da página sem ligação não apareceu"
    _sem_estouro(page)
    _captura(page, tmp_path, "sem-ligacao")


def test_pagina_ja_visitada_volta_a_abrir_sem_rede(contexto_sem_atalhos) -> None:
    """Sem rede, o que já foi visitado abre da cache (e não a página de recurso)."""
    page = contexto_sem_atalhos.new_page()
    _preparar_service_worker(page)

    page.goto(f"{BASE}/site/blog", wait_until="domcontentloaded")
    expect(page.locator("main h1")).to_have_text("Blog")

    contexto_sem_atalhos.set_offline(True)
    page.goto(f"{BASE}/site/blog", wait_until="domcontentloaded")

    expect(page.locator("main h1")).to_have_text("Blog", timeout=30000)
    assert page.locator(".sistema-imagem").count() == 0, "mostrou a página de recurso em vez da guardada"


# ------------------------------------------------------- página do proxy (nginx)
def test_pagina_de_erro_do_proxy_explica_e_da_saida(page: Page, tmp_path) -> None:
    resposta = page.goto(f"{BASE}/erro.html")
    if resposta is not None and resposta.status == 404:
        pytest.skip("esta instalação não serve o nginx de front-end (sem /erro.html)")
    assert resposta is not None and resposta.status == 200
    assert resposta.headers.get("cache-control") == "no-store", "a página de erro não pode ficar em cache"

    expect(page.locator("h1")).to_have_text("O servidor esta a responder devagar")
    expect(page.locator(".nota")).to_contain_text("aditivos")
    expect(page.get_by_role("button", name="Tentar outra vez")).to_be_visible()
    expect(page.get_by_role("link", name="Voltar ao inicio")).to_be_visible()
    for destino in ("/site/solucoes", "/site/relatorios-gratuitos", "/site/fontes", "/site/contactos"):
        expect(page.locator(f'a[href="{destino}"]')).to_be_visible()

    _sem_estouro(page)
    page.set_viewport_size(TELEMOVEL)
    _sem_estouro(page)
    _captura(page, tmp_path, "erro-proxy")
