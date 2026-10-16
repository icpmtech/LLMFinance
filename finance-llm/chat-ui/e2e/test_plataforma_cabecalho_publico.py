"""Testes de browser do cabeçalho e rodapé das páginas públicas da plataforma.

As páginas de **entrada** — `/login`, `/register` e a página inicial `/` — levam
um cabeçalho e um rodapé próprios da plataforma (marca, navegação, botões e
rodapé), editáveis no backoffice (Administração → Plataforma). Não precisam de
sessão: quem chega vê-as antes de entrar.

O que aqui se fixa:

- o que a página mostra é o que `/api/app-shell` responde (marca, botões,
  rodapé e redes sociais) — o texto não é copiado para o teste, é lido da API;
- a entrada e a página inicial usam o **mesmo** cabeçalho e rodapé;
- a entrada abre **mesmo com a API do cabeçalho em falta** (pedido abortado): o
  visitante vê a marca por omissão, não um ecrã vazio;
- no telemóvel o que não cabe no cabeçalho não se perde: a navegação **e os dois
  botões** («Entrar» e «Criar conta») passam para dentro do menu — e uma ligação
  configurada no backoffice acompanha-os (ao lado, no computador);
- sem navegação e sem botões não há menu nenhum (o botão só existe quando há o
  que abrir);
- o cabeçalho fica no topo, o rodapé no fim do documento, e nada estoura na
  horizontal — no computador e no telemóvel, com o menu fechado e aberto.

    e2e-venv\\Scripts\\python.exe -m pytest e2e/test_plataforma_cabecalho_publico.py -v
"""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any, Dict, Iterator

import pytest
from playwright.sync_api import Browser, Page, expect

BASE = os.environ.get("E2E_FRONTEND_URL", "http://127.0.0.1:4180").rstrip("/")
COMPUTADOR = {"width": 1280, "height": 900}
TELEMOVEL = {"width": 390, "height": 844}

#: Páginas públicas da plataforma (as que se veem sem sessão).
ENTRADA = "/login"
INICIAL = "/"

#: Terceiros que o `conftest.py` também bloqueia: o banner de consentimento da
#: iubenda mete-se à frente dos elementos (e traz um `<footer>` que disputa o
#: seletor do rodapé), e os scripts de medição não interessam a testes.
BLOQUEADOS = ("iubenda.com", "googletagmanager.com", "google-analytics.com")

REMOVER_CONSENTIMENTO = """
() => {
  document
    .querySelectorAll('[class*="iubenda"], [id*="iubenda"], [id*="onetrust"], .cc-window')
    .forEach((no) => no.remove());
  document.documentElement.style.removeProperty('overflow');
}
"""


@pytest.fixture
def pagina_publica(browser: Browser) -> Iterator[Page]:
    """Contexto **sem sessão** e sem o banner de consentimento.

    O `context` do `conftest.py` injeta o token da conta E2E (é o que as páginas
    da plataforma precisam) e o `page` do Playwright nasce desse contexto. Aqui
    é o contrário: as páginas de entrada são para quem ainda não entrou, e com
    sessão a `/login` abre a aplicação em vez do formulário.
    """
    contexto = browser.new_context()
    contexto.route(
        "**/*",
        lambda rota: rota.abort() if any(host in rota.request.url for host in BLOQUEADOS) else rota.continue_(),
    )
    pagina = contexto.new_page()
    try:
        yield pagina
    finally:
        contexto.close()


def _shell_publico() -> Dict[str, Any]:
    """O cabeçalho que a API serve agora (o mesmo que a página deve desenhar)."""
    with urllib.request.urlopen(f"{BASE}/api/app-shell", timeout=30) as resposta:
        return json.loads(resposta.read().decode("utf-8"))


def _abrir(pagina: Page, caminho: str, tamanho: Dict[str, int] | None = None) -> None:
    if tamanho:
        pagina.set_viewport_size(tamanho)
    pagina.goto(f"{BASE}{caminho}", wait_until="networkidle", timeout=120_000)
    # Rede de segurança: se algum nó do banner de consentimento sobreviver.
    pagina.evaluate(REMOVER_CONSENTIMENTO)


def _sem_estouro(pagina: Page) -> None:
    estouro = pagina.evaluate("() => document.documentElement.scrollWidth - window.innerWidth")
    assert estouro <= 1, f"a página estoura {estouro}px na horizontal"


def _verificar_cabecalho(pagina: Page, shell: Dict[str, Any]) -> None:
    """O cabeçalho (no computador) mostra a marca, a navegação e os botões da API."""
    cabecalho = pagina.locator("header").first
    expect(cabecalho).to_be_visible()

    marca = cabecalho.locator("a").first
    expect(marca).to_have_attribute("href", "/")
    expect(marca).to_contain_text(shell["brand"]["name"])
    if shell["brand"]["tagline"]:
        expect(marca).to_contain_text(shell["brand"]["tagline"])

    for item in shell["header"]["items"]:
        expect(cabecalho.get_by_role("link", name=item["label"], exact=True)).to_have_attribute("href", item["href"])

    for chave in ("cta", "secondary"):
        botao = shell["header"][chave]
        if not botao:
            continue
        expect(cabecalho.get_by_role("link", name=botao["label"], exact=True)).to_have_attribute("href", botao["href"])


def _verificar_rodape(pagina: Page, shell: Dict[str, Any]) -> None:
    """O rodapé mostra a frase, as ligações e as redes sociais que a API definiu."""
    rodape = pagina.locator("footer").first
    expect(rodape).to_be_visible()
    expect(rodape).to_contain_text(shell["footer"]["text"])

    for item in shell["footer"]["items"] + shell["footer"]["social"]:
        expect(rodape.get_by_role("link", name=item["label"], exact=True)).to_have_attribute("href", item["href"])


def _verificar_geometria(pagina: Page) -> None:
    """Cabeçalho no topo, conteúdo no meio, rodapé no fim — e nada a estourar."""
    _sem_estouro(pagina)
    caixa_cabecalho = pagina.locator("header").first.bounding_box()
    caixa_conteudo = pagina.locator("main").first.bounding_box()
    caixa_rodape = pagina.locator("footer").first.bounding_box()

    assert caixa_cabecalho and caixa_cabecalho["y"] <= 1, "o cabeçalho não está no topo"
    assert caixa_conteudo, "o conteúdo da página não está visível"
    assert caixa_rodape, "o rodapé não está visível"
    # A ordem na vertical é a que se lê: cabeçalho, conteúdo, rodapé.
    fim_cabecalho = caixa_cabecalho["y"] + caixa_cabecalho["height"]
    fim_conteudo = caixa_conteudo["y"] + caixa_conteudo["height"]
    assert fim_cabecalho <= caixa_conteudo["y"] + 1, "o conteúdo começa antes do fim do cabeçalho"
    assert caixa_rodape["y"] >= fim_conteudo - 1, "o rodapé não fica depois do conteúdo"

    # E o documento reserva espaço até ao fundo do rodapé (nada cortado).
    fundo_rodape = pagina.evaluate(
        "() => document.querySelector('footer').getBoundingClientRect().bottom + window.scrollY"
    )
    altura_documento = pagina.evaluate("() => document.documentElement.scrollHeight")
    assert fundo_rodape <= altura_documento + 1, "o rodapé sai fora do documento"


def test_entrada_mostra_o_cabecalho_e_o_rodape_da_api(pagina_publica: Page) -> None:
    shell = _shell_publico()
    _abrir(pagina_publica, ENTRADA, COMPUTADOR)
    # A entrada continua a ser a entrada (o formulário está lá).
    expect(pagina_publica.get_by_role("textbox", name="Email")).to_be_visible()

    _verificar_cabecalho(pagina_publica, shell)
    _verificar_rodape(pagina_publica, shell)
    _verificar_geometria(pagina_publica)


def test_pagina_inicial_usa_o_mesmo_cabecalho_e_rodape(pagina_publica: Page) -> None:
    shell = _shell_publico()
    _abrir(pagina_publica, INICIAL, COMPUTADOR)

    _verificar_cabecalho(pagina_publica, shell)
    _verificar_rodape(pagina_publica, shell)
    _verificar_geometria(pagina_publica)


def test_entrada_abre_mesmo_sem_a_api_do_cabecalho(pagina_publica: Page) -> None:
    """Sem resposta de `/api/app-shell`, a entrada abre com a marca por omissão."""
    pagina_publica.route("**/api/app-shell*", lambda rota: rota.abort())
    _abrir(pagina_publica, ENTRADA, COMPUTADOR)

    cabecalho = pagina_publica.locator("header").first
    expect(cabecalho).to_be_visible()
    expect(cabecalho.locator("a").first).to_contain_text("IQ OS")
    expect(pagina_publica.get_by_role("textbox", name="Email")).to_be_visible()
    expect(pagina_publica.locator("footer").first).to_be_visible()


def _fixar_shell(pagina: Page, shell: Dict[str, Any]) -> None:
    """Serve um cabeçalho próprio, sem tocar no backoffice nem precisar de sessão."""
    pagina.route(
        "**/api/app-shell*",
        lambda rota: rota.fulfill(status=200, content_type="application/json", body=json.dumps(shell)),
    )


def _com_navegacao(shell: Dict[str, Any]) -> Dict[str, Any]:
    """O cabeçalho da API com duas ligações de navegação (como as do backoffice)."""
    shell["header"]["items"] = [
        {"label": "Blog", "href": "/site/blog"},
        {"label": "Fontes", "href": "/site/fontes"},
    ]
    return shell


def test_telemovel_leva_os_botoes_para_dentro_do_menu(pagina_publica: Page) -> None:
    """Abaixo de `sm` o «Entrar» sai do cabeçalho e passa a estar no menu."""
    shell = _shell_publico()
    _abrir(pagina_publica, ENTRADA, TELEMOVEL)
    _verificar_rodape(pagina_publica, shell)

    cabecalho = pagina_publica.locator("header").first
    # O «Entrar» já não cabe no cabeçalho…
    expect(cabecalho.locator(f'a[href="{shell["header"]["secondary"]["href"]}"]').first).to_be_hidden()
    # …por isso o menu existe e abre com ele e com o «Criar conta» dentro.
    botao = pagina_publica.locator("header button[aria-controls='menu-publico']")
    expect(botao).to_be_visible()
    botao.click()

    painel = pagina_publica.locator("#menu-publico")
    expect(painel).to_be_visible()
    for chave in ("secondary", "cta"):
        botao_cabecalho = shell["header"][chave]
        expect(painel.get_by_role("link", name=botao_cabecalho["label"], exact=True)).to_have_attribute(
            "href", botao_cabecalho["href"]
        )
    # Com o painel aberto a página continua sem estouro na horizontal.
    _sem_estouro(pagina_publica)


def test_navegacao_do_backoffice_entra_no_painel_do_telemovel(pagina_publica: Page) -> None:
    """Uma ligação configurada fica ao lado no computador e no menu no telemóvel."""
    shell = _com_navegacao(_shell_publico())
    _fixar_shell(pagina_publica, shell)

    _abrir(pagina_publica, ENTRADA, COMPUTADOR)
    cabecalho = pagina_publica.locator("header").first
    expect(cabecalho.get_by_role("link", name="Blog", exact=True)).to_be_visible()

    # No telemóvel a ligação sai do cabeçalho e aparece no menu, com os botões.
    pagina_publica.set_viewport_size(TELEMOVEL)
    expect(cabecalho.get_by_role("link", name="Blog", exact=True)).to_be_hidden()
    pagina_publica.locator("header button[aria-controls='menu-publico']").click()

    painel = pagina_publica.locator("#menu-publico")
    expect(painel.get_by_role("link", name="Blog", exact=True)).to_have_attribute("href", "/site/blog")
    expect(painel.get_by_role("link", name="Fontes", exact=True)).to_have_attribute("href", "/site/fontes")
    for chave in ("secondary", "cta"):
        botao_cabecalho = shell["header"][chave]
        expect(painel.get_by_role("link", name=botao_cabecalho["label"], exact=True)).to_have_attribute(
            "href", botao_cabecalho["href"]
        )
    _sem_estouro(pagina_publica)


def test_sem_navegacao_nem_botoes_nao_ha_menu(pagina_publica: Page) -> None:
    """Sem ligações e sem botões não há nada para abrir: o botão não aparece."""
    shell = _shell_publico()
    shell["header"] = {"items": [], "cta": None, "secondary": None}
    _fixar_shell(pagina_publica, shell)

    _abrir(pagina_publica, ENTRADA, TELEMOVEL)
    expect(pagina_publica.locator("header button[aria-controls='menu-publico']")).to_have_count(0)
    expect(pagina_publica.locator("#menu-publico")).to_have_count(0)
