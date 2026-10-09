"""Testes end-to-end da secção «Entidades» do EmpresasIQ.

Cobrem a lista (cards/tabela/mapa), a pesquisa, os filtros, a paginação, a
exportação e o painel de contratos por região. Os valores esperados são lidos da
mesma API que a UI usa (`/api/companies/search`), pelo que os testes confirmam o
que o Elasticsearch devolve e não números fixos no código.

Pré-requisitos: frontend a correr (`E2E_FRONTEND_URL`, por omissão
`http://127.0.0.1:4180`) e as credenciais descritas em `conftest.py`.

    e2e-venv\\Scripts\\python.exe -m pytest e2e/test_entities_filters.py -v
"""

from __future__ import annotations

import re
import time
import unicodedata

import pytest

PAGE_SIZE = 15
DEFAULT_FILTERS = {"from": 0, "size": PAGE_SIZE}


# ------------------------------------------------------------------ utilitários
def _norm(text: str) -> str:
    """Normaliza espaços não separáveis usados pelo `Intl.NumberFormat` pt-PT."""
    return re.sub(r"[\u00a0\u202f]", " ", text).strip()


def _searchable(value: str) -> str:
    """Texto comparável: sem acentos, minúsculas e pontuação reduzida a espaços."""
    texto = unicodedata.normalize("NFKD", value or "")
    texto = "".join(char for char in texto if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", texto.casefold()).strip()


def _name_matches(name: str, query: str) -> bool:
    """A entidade casa a pesquisa se cada termo iniciar uma palavra do nome."""
    palavras = _searchable(name).split()
    return all(any(palavra.startswith(termo) for palavra in palavras) for termo in _searchable(query).split())


def _to_int(text: str) -> int:
    return int(re.sub(r"[^\d]", "", text))


def _poll(read, predicate, timeout: float = 45.0, interval: float = 0.3, describe: str = "valor"):
    """Espera até `read()` satisfazer `predicate` (as listas recarregam por filtro)."""
    deadline = time.monotonic() + timeout
    last: object = None
    while time.monotonic() < deadline:
        try:
            last = read()
        except (AssertionError, ValueError):
            last = None
        else:
            if predicate(last):
                return last
        time.sleep(interval)
    raise AssertionError(f"{describe} não convergiu em {timeout:.0f}s (último valor: {last!r})")


def _open_entities(app):
    page = app("/empresas-iq")
    page.get_by_test_id("empresas-iq-tab-entities").click()
    # O primeiro carregamento do universo é pesado e a máquina pode estar ocupada
    # (Elasticsearch frio, contentores acabados de arrancar): limite folgado.
    page.get_by_test_id("entities-summary").wait_for(timeout=90000)
    return page


def _universe(page) -> int:
    """Total de entidades anunciado no cabeçalho da secção."""
    text = _norm(page.get_by_test_id("entities-total").inner_text())
    match = re.search(r"([\d ]+)\s+entidades no universo", text)
    assert match, f"Cabeçalho inesperado: {text!r}"
    return _to_int(match.group(1))


def _summary(page) -> tuple[int, int, int]:
    """(primeiro, último, total) da linha «Mostrando X–Y de Z»."""
    text = _norm(page.get_by_test_id("entities-summary").inner_text())
    match = re.search(r"Mostrando (\d+)–(\d+) de ([\d ]+)", text)
    assert match, f"Linha de paginação inesperada: {text!r}"
    return int(match.group(1)), int(match.group(2)), _to_int(match.group(3))


def _search(page, term: str):
    page.get_by_test_id("entities-query").fill(term)
    page.get_by_test_id("entities-filters").press("Enter")


def _pick_role(page, role: str):
    page.get_by_test_id("entities-role").select_option(role)


def _card_names(page) -> list[str]:
    return [_norm(name) for name in page.get_by_test_id("entity-card-name").all_inner_texts()]


def _open_map(page):
    """Abre a vista de mapa e devolve as bolhas de região já visíveis."""
    page.get_by_test_id("entities-view-map").click()
    regions = page.locator("[data-region]")
    _poll(lambda: regions.count(), lambda count: count > 0, timeout=40, describe="regiões no mapa")
    regions.first.scroll_into_view_if_needed()
    return regions


def _card_roles(page) -> list[str]:
    return [_norm(role) for role in page.get_by_test_id("entity-card-role").all_inner_texts()]


def _top_region(page) -> str | None:
    """Região cuja bolha está mesmo no topo (as bolhas do mapa sobrepõem-se)."""
    return page.evaluate(
        """() => {
            for (const bubble of document.querySelectorAll('[data-region]')) {
                const rect = bubble.getBoundingClientRect();
                if (rect.width === 0 || rect.height === 0) continue;
                const top = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
                if (top && bubble.contains(top)) return bubble.dataset.region;
            }
            return null;
        }"""
    )


def _wait_universe(page, expected: int) -> int:
    return _poll(lambda: _universe(page), lambda value: value == expected, describe="total no cabeçalho")


def _wait_summary(page, first: int, last: int, total: int) -> tuple[int, int, int]:
    return _poll(
        lambda: _summary(page),
        lambda value: value == (first, last, total),
        describe="linha de paginação",
    )


def _wait_role(page, role: str) -> None:
    _poll(
        lambda: page.get_by_test_id("entities-role").input_value(),
        lambda value: value == role,
        describe="filtro de função aplicado",
    )


# ----------------------------------------------------------------------- testes
def test_default_list_matches_elastic(app, api):
    """A primeira página e o total do cabeçalho vêm da pesquisa sem filtros."""
    page = _open_entities(app)
    expected = api("/api/companies/search", DEFAULT_FILTERS)["total"]

    assert _wait_universe(page, expected) == expected
    assert _wait_summary(page, 1, PAGE_SIZE, expected) == (1, PAGE_SIZE, expected)
    assert len(_card_names(page)) == PAGE_SIZE


def test_search_api_echoes_the_requested_offset(app, api):
    """A API confirma o offset recebido (a paginação da UI depende deste eco)."""
    for offset in (0, PAGE_SIZE, PAGE_SIZE * 3):
        response = api("/api/companies/search", {"from": offset, "size": PAGE_SIZE})
        assert response["from"] == offset, f"offset pedido {offset} não voltou na resposta"


def test_name_search_returns_only_entities_with_that_name(app, api, tracked_requests):
    """A pesquisa por nome devolve entidades com esse nome — não as contrapartes."""
    page = _open_entities(app)
    unfiltered = api("/api/companies/search", DEFAULT_FILTERS)["total"]

    _search(page, "mota")
    response = api("/api/companies/search", {**DEFAULT_FILTERS, "q": "mota"})

    assert _poll(
        lambda: tracked_requests and tracked_requests[-1].get("q"),
        lambda value: value == "mota",
        describe="filtro q enviado para /companies/search",
    ) == "mota"

    total = _wait_universe(page, response["total"])
    assert total < unfiltered, "a pesquisa devia reduzir o universo de entidades"
    assert _wait_summary(page, 1, PAGE_SIZE, total)[2] == total

    expected_names = {item["name"] for item in response["items"]}
    assert set(_card_names(page)) == expected_names
    # Nem uma contraparte: todos os nomes mostrados casam a pesquisa.
    assert all(_name_matches(name, "mota") for name in expected_names), sorted(expected_names)[:5]


def test_topbar_search_filters_the_entity_list(app, api):
    """O botão «Pesquisar» do topo aplica o termo à lista de entidades."""
    page = _open_entities(app)

    page.get_by_test_id("topbar-search-input").fill("mota")
    page.get_by_test_id("topbar-search-button").click()

    esperado = api("/api/companies/search", {**DEFAULT_FILTERS, "q": "mota"})
    assert _wait_universe(page, esperado["total"]) == esperado["total"]
    assert set(_card_names(page)) == {item["name"] for item in esperado["items"]}
    # O campo de filtros do separador fica a refletir a pesquisa ativa.
    assert page.get_by_test_id("entities-query").input_value() == "mota"


def test_name_search_ignores_accents_and_words_order(app, api):
    """A pesquisa casa sem acentos e com os termos por qualquer ordem."""
    sem_acentos = api("/api/companies/search", {**DEFAULT_FILTERS, "q": "construcoes"})
    invertido = api("/api/companies/search", {**DEFAULT_FILTERS, "q": "engil mota"})

    assert sem_acentos["total"] > 0
    assert all(_name_matches(item["name"], "construcoes") for item in sem_acentos["items"])
    assert invertido["total"] > 0
    assert all(_name_matches(item["name"], "engil mota") for item in invertido["items"])


def test_name_search_by_nif_returns_the_entity(app, api):
    """Pesquisar um NIF devolve essa entidade, não os contratos em que aparece."""
    mota = api("/api/companies/search", {**DEFAULT_FILTERS, "q": "mota", "role": "adjudicatario"})
    nif = next(item["nif"] for item in mota["items"] if item["nif"])

    resposta = api("/api/companies/search", {**DEFAULT_FILTERS, "q": nif})

    assert resposta["total"] == 1
    assert resposta["items"][0]["nif"] == nif


def test_role_filter_returns_only_entities_with_that_role(app, api, tracked_requests):
    """Filtrar por função devolve apenas entidades com esse papel, com o total certo."""
    page = _open_entities(app)

    # Nenhuma entidade chamada «mota» é adjudicante; são todas adjudicatárias.
    adjudicatario = api("/api/companies/search", {**DEFAULT_FILTERS, "q": "mota", "role": "adjudicatario"})
    assert adjudicatario["total"] == adjudicatario["unique_adjudicatarios"]
    _search(page, "mota")
    _pick_role(page, "adjudicatario")
    _wait_role(page, "adjudicatario")
    _poll(
        lambda: tracked_requests[-1].get("role") if tracked_requests else None,
        lambda value: value == "adjudicatario",
        describe="filtro role enviado para /companies/search",
    )
    assert _wait_universe(page, adjudicatario["total"]) == adjudicatario["total"]
    assert set(_card_roles(page)) <= {"Adjudicatário", "Ambos"}

    # Com esse papel não há correspondências: a lista fica vazia (sem entidades
    # de outro papel a preencher o ecrã).
    vazio = api("/api/companies/search", {**DEFAULT_FILTERS, "q": "mota", "role": "adjudicante"})
    assert vazio["total"] == 0
    _pick_role(page, "adjudicante")
    _wait_role(page, "adjudicante")
    assert _wait_universe(page, 0) == 0
    assert page.get_by_test_id("entities-empty").is_visible()
    assert page.get_by_test_id("entity-card").count() == 0

    adjudicante = api("/api/companies/search", {**DEFAULT_FILTERS, "q": "lisboa", "role": "adjudicante"})
    _search(page, "lisboa")
    assert _wait_universe(page, adjudicante["total"]) == adjudicante["total"]
    # «Ambos» é legítimo: a entidade tem o papel pedido e também o outro.
    assert set(_card_roles(page)) <= {"Adjudicante", "Ambos"}

    # Sem papel escolhido voltam as entidades correspondentes de ambos os papéis.
    _pick_role(page, "all")
    todos = api("/api/companies/search", {**DEFAULT_FILTERS, "q": "lisboa"})
    assert _wait_universe(page, todos["total"]) == todos["total"]
    assert set(_card_roles(page)) <= {"Adjudicante", "Adjudicatário", "Ambos"}


def test_pagination_walks_forward_and_back(app, api):
    """A paginação avança e recua 15 entidades por página."""
    page = _open_entities(app)
    _search(page, "mota")
    total = api("/api/companies/search", {**DEFAULT_FILTERS, "q": "mota"})["total"]
    _wait_summary(page, 1, PAGE_SIZE, total)
    first_page = set(_card_names(page))

    page.get_by_label("Página seguinte").click()
    assert _wait_summary(page, PAGE_SIZE + 1, PAGE_SIZE * 2, total) == (PAGE_SIZE + 1, PAGE_SIZE * 2, total)
    assert set(_card_names(page)) != first_page

    page.get_by_label("Página anterior").click()
    assert _wait_summary(page, 1, PAGE_SIZE, total) == (1, PAGE_SIZE, total)
    assert set(_card_names(page)) == first_page


def test_clear_filters_restores_the_universe(app, api):
    """O botão de limpar filtros devolve a lista inicial."""
    page = _open_entities(app)
    unfiltered = api("/api/companies/search", DEFAULT_FILTERS)["total"]
    filtered = api("/api/companies/search", {**DEFAULT_FILTERS, "q": "mota", "role": "adjudicatario"})

    _search(page, "mota")
    _pick_role(page, "adjudicatario")
    _wait_summary(page, 1, PAGE_SIZE, filtered["total"])

    page.get_by_title("Limpar filtros").click()

    assert _poll(
        lambda: page.get_by_test_id("entities-query").input_value(),
        lambda value: value == "",
        describe="campo de pesquisa limpo",
    ) == ""
    _wait_role(page, "all")
    assert _wait_universe(page, unfiltered) == unfiltered


def test_table_and_map_views_render_entities(app, api):
    """As vistas de tabela e de mapa mostram os mesmos dados da lista."""
    page = _open_entities(app)
    expected = api("/api/companies/search", DEFAULT_FILTERS)["total"]
    _wait_universe(page, expected)

    page.get_by_test_id("entities-view-table").click()
    rows = page.locator("table tbody tr")
    assert _poll(lambda: rows.count(), lambda count: count == PAGE_SIZE, describe="linhas da tabela") == PAGE_SIZE
    headers = _norm(page.locator("table thead").first.inner_text()).lower()
    assert "entidade" in headers and "nif" in headers

    page.get_by_test_id("entities-view-map").click()
    regions = page.locator("[data-region]")
    assert _poll(lambda: regions.count(), lambda count: count > 0, timeout=40, describe="regiões no mapa") > 0


def test_map_region_context_menu_opens_the_contracts_panel(app, api):
    """O menu de contexto de uma região abre o painel de contratos dessa região."""
    page = _open_entities(app)
    _open_map(page)

    region = _poll(lambda: _top_region(page), lambda value: bool(value), timeout=30, describe="região clicável")
    page.locator(f'[data-region="{region}"]').click(button="right")

    menu_item = page.get_by_role("button", name="Ver contratos da região")
    menu_item.wait_for(timeout=10000)
    menu_item.click()

    panel = page.locator("div").filter(has=page.get_by_role("heading", name="Contratos da região")).last
    assert _poll(
        lambda: _norm(panel.inner_text()),
        lambda text: region in text,
        timeout=30,
        describe="painel de contratos da região",
    )

    expected = api("/api/contracts/search", {"region": region, "from": 0, "size": PAGE_SIZE})
    assert _poll(
        lambda: _contracts_total(panel),
        lambda value: value == expected["total"],
        timeout=30,
        describe="total de contratos da região",
    ) == expected["total"]


def _contracts_total(panel) -> int:
    text = _norm(panel.inner_text())
    match = re.search(r"·\s*([\d ]+)\s+contratos", text)
    assert match, f"Cabeçalho do painel inesperado: {text[:120]!r}"
    return _to_int(match.group(1))


@pytest.mark.parametrize(
    ("button_title", "extension", "timeout"),
    [
        ("Exportar para Excel", ".xlsx", 60_000),
        # O PDF é rasterizado no browser (html2canvas + jsPDF): numa máquina
        # carregada passa dos 90 s, pelo que o limite é folgado de propósito.
        ("Exportar para PDF", ".pdf", 300_000),
    ],
)
def test_entity_exports_download_files(app, button_title, extension, timeout):
    """As exportações de Excel e PDF geram um ficheiro com conteúdo."""
    page = _open_entities(app)
    page.get_by_test_id("entities-summary").wait_for(timeout=25000)

    with page.expect_download(timeout=timeout) as download_info:
        page.get_by_title(button_title).click()

    download = download_info.value
    assert download.suggested_filename.endswith(extension)
    path = download.path()
    assert path and path.stat().st_size > 0, "o ficheiro exportado ficou vazio"
