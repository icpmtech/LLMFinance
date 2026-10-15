"""Testes end-to-end dos submenus do menu público.

Cobrem os três lados da funcionalidade:

* o **editor** do CMS (Aparência) acrescenta e guarda um subitem;
* o **site público no computador** mostra o submenu ao rato e ao teclado, abre o
  submenu de segundo nível ao lado e mantém-no dentro do ecrã;
* o **site público no telemóvel** mostra os submenus à vista e indentados, sem
  estouro horizontal, e os links navegam.

Os testes correm contra a instalação real (`E2E_FRONTEND_URL`), não contra um
ambiente isolado: o menu do cabeçalho e do rodapé é reconfigurado para o teste e
**reposto no fim** (ficam registadas as revisões e a atividade das alterações,
como em qualquer gravação feita no CMS).

    e2e-venv\\Scripts\\python.exe -m pytest e2e/test_cms_menu_submenus.py -v
"""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import expect

TELEMOVEL = {"width": 390, "height": 844}
COMPUTADOR = {"width": 1280, "height": 800}


# ------------------------------------------------------------------ utilitários
def _item(id_: str, label: str, href: str = "", children: list | None = None) -> dict:
    item = {"id": id_, "label": label, "href": href, "page_id": None, "new_tab": False}
    if children:
        item["children"] = children
    return item


def _menu_com_submenus() -> list[dict]:
    """Menu do cabeçalho com um submenu de dois níveis e um grupo sem destino."""
    return [
        _item("e2e_1", "Início", "/site/"),
        _item(
            "e2e_2",
            "Soluções",
            "/site/solucoes",
            children=[
                _item("e2e_2a", "Blog", "/site/blog"),
                _item("e2e_2b", "Contactos", "/site/contactos"),
                # Um item sem página nem URL é rótulo de grupo: agrupa, não navega.
                _item("e2e_2c", "Mais", children=[_item("e2e_2c1", "Fontes", "/site/fontes")]),
            ],
        ),
        _item("e2e_3", "Sobre", "/site/sobre"),
    ]


@pytest.fixture
def menus(api):
    """Reconfigura e repõe os menus do site (a instalação é a real).

    Escrever no CMS é de `admin`/`manager`: com uma conta `member` (a que a suite
    provisiona por omissão) os testes que mexem no menu são saltados, com a
    indicação do que fazer para os poder correr.
    """
    papel = str((api("/api/auth/me") or {}).get("role") or "member")
    if papel not in ("admin", "manager"):
        pytest.skip(
            f"A conta da suite é «{papel}» e só pode consultar dados. Escrever no CMS exige «admin» ou "
            "«manager»: promova a conta E2E na Administração ou defina E2E_TOKEN de uma conta gestora."
        )

    def ler() -> dict:
        return {
            menu["location"]: menu
            for menu in api("/api/cms/menus")["items"]
            if menu["location"] in ("header", "footer")
        }

    inicial = ler()

    def corpo(menu: dict, itens: list[dict]) -> dict:
        return {
            "name": menu.get("name"),
            "location": menu.get("location"),
            "menu_theme": menu.get("menu_theme"),
            "menu_template": menu.get("menu_template"),
            "items": itens,
        }

    def definir(location: str, itens: list[dict]) -> dict:
        menu = inicial[location]
        return api(f"/api/cms/menus/{menu['id']}", corpo(menu, itens), method="PATCH")

    def atual(location: str) -> dict:
        return next(menu for menu in api("/api/cms/menus")["items"] if menu["location"] == location)

    yield type("Menus", (), {"definir": staticmethod(definir), "atual": staticmethod(atual)})

    for location, menu in inicial.items():
        api(f"/api/cms/menus/{menu['id']}", corpo(menu, menu["items"]), method="PATCH")


def _submenu_do_cabecalho(page):
    """O submenu do item «Soluções» no site público."""
    pai = page.locator("nav.main .menu-item > .menu-pai", has_text="Soluções")
    return pai, page.locator("nav.main > .menu-item > .submenu")


# ------------------------------------------------------------------- editor CMS
def test_editor_do_cms_acrescenta_subitem(app, api, menus):
    """Acrescentar um subitem no painel Aparência e guardá-lo chega ao servidor."""
    page = app("/cms/aparencia")

    linhas = page.get_by_test_id("cms-menu-item")
    expect(linhas.first).to_be_visible()
    antes = page.get_by_test_id("cms-menu-subitem").count()

    linhas.first.get_by_role("button", name="Acrescentar subitem").click()
    expect(page.get_by_test_id("cms-menu-subitem")).to_have_count(antes + 1)

    subitem = page.get_by_test_id("cms-menu-subitem").last
    expect(subitem.get_by_text("Subitem", exact=True)).to_be_visible()
    subitem.get_by_label("Texto").fill("Blog E2E")
    subitem.get_by_label("…ou URL").fill("/site/blog")

    page.get_by_role("button", name="Guardar menu").first.click()
    expect(page.get_by_text("Menu guardado.")).to_be_visible(timeout=30000)

    guardado = menus.atual("header")
    filhos = [filho for item in guardado["items"] for filho in item.get("children") or []]
    assert any(filho["label"] == "Blog E2E" and filho["href"] == "/site/blog" for filho in filhos), filhos


# --------------------------------------------------------- site no computador
def test_submenu_abre_com_o_rato(app, menus):
    menus.definir("header", _menu_com_submenus())
    page = app("/site/")

    _, submenu = _submenu_do_cabecalho(page)
    blog = submenu.get_by_role("link", name="Blog")
    assert not blog.is_visible(), "o submenu só deve aparecer quando o item é aberto"

    pai = page.locator("nav.main .menu-item > .menu-pai", has_text="Soluções")
    pai.hover()

    expect(blog).to_be_visible()
    expect(submenu.get_by_role("link", name="Contactos")).to_be_visible()
    assert submenu.get_by_role("link", name="Blog").get_attribute("href") == "/site/blog"


def test_submenu_abre_com_o_teclado(app, menus):
    menus.definir("header", _menu_com_submenus())
    page = app("/site/")

    _, submenu = _submenu_do_cabecalho(page)
    blog = submenu.get_by_role("link", name="Blog")
    assert not blog.is_visible()

    page.locator("nav.main .menu-item > .menu-pai", has_text="Soluções").focus()
    expect(blog).to_be_visible()


def test_grupo_sem_destino_e_rotulo_e_nao_link(app, menus):
    """Um item sem página nem URL agrupa o submenu, mas não navega."""
    menus.definir("header", _menu_com_submenus())
    page = app("/site/")

    pai, _ = _submenu_do_cabecalho(page)
    pai.hover()

    grupo = page.locator("nav.main .submenu > li.tem-submenu > .menu-pai")
    expect(grupo).to_be_visible()
    assert grupo.evaluate("elemento => elemento.tagName") == "SPAN"
    assert grupo.get_attribute("href") is None


def test_submenu_de_segundo_nivel_fica_dentro_do_ecra(app, menus):
    """O menu vive à direita: sem o desvio, o segundo nível saía do ecrã."""
    menus.definir("header", _menu_com_submenus())
    page = app("/site/")

    pai, submenu = _submenu_do_cabecalho(page)
    pai.hover()
    page.locator("nav.main .submenu > li.tem-submenu > .menu-pai").hover()

    aninhado = submenu.locator(".submenu")
    expect(aninhado.get_by_role("link", name="Fontes")).to_be_visible()

    caixa = aninhado.bounding_box()
    largura = page.viewport_size["width"]
    assert caixa["x"] >= 0, f"o submenu saiu pela esquerda: {caixa}"
    assert caixa["x"] + caixa["width"] <= largura + 1, f"o submenu saiu pela direita: {caixa} em {largura}px"


def test_rodape_mostra_os_submenus_ao_lado(app, menus):
    """No rodapé não há painéis: o submenu aparece ao lado do item que o abre."""
    menus.definir("footer", [_item("e2e_f1", "Recursos", children=[_item("e2e_f2", "Blog", "/site/blog")])])
    page = app("/site/")

    rodape = page.locator("footer.site-footer nav")
    expect(rodape.get_by_role("link", name="Blog")).to_be_visible()
    assert rodape.get_by_role("link", name="Blog").get_attribute("href") == "/site/blog"


# ----------------------------------------------------------- site no telemóvel
def test_submenu_no_telemovel_fica_a_vista_e_indentado(app, menus):
    menus.definir("header", _menu_com_submenus())
    page = app("/site/")
    page.set_viewport_size(TELEMOVEL)

    page.get_by_text("Menu", exact=True).click()
    expect(page.locator("nav.main")).to_be_visible()

    pai = page.locator("nav.main > .menu-item > .menu-pai", has_text="Soluções")
    submenu = page.locator("nav.main > .menu-item > .submenu")
    blog = submenu.get_by_role("link", name="Blog")

    # Sem rato: no telemóvel o submenu está logo à vista.
    expect(blog).to_be_visible()
    expect(submenu.locator(".submenu").get_by_role("link", name="Fontes")).to_be_visible()

    assert blog.bounding_box()["x"] > pai.bounding_box()["x"], "o subitem deve ficar indentado sob o item"

    estouro = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
    assert estouro <= 0, f"a página ganhou {estouro}px de scroll horizontal com o menu aberto"


def test_subitem_do_telemovel_navega(app, menus):
    menus.definir("header", _menu_com_submenus())
    page = app("/site/")
    page.set_viewport_size(TELEMOVEL)

    page.get_by_text("Menu", exact=True).click()
    page.locator("nav.main > .menu-item > .submenu").get_by_role("link", name="Blog").click()

    expect(page).to_have_url(re.compile(r"/site/blog/?$"), timeout=30000)
