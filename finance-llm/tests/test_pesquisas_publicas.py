"""Páginas de pesquisa do CMS: filtros congelados, fotografia dos números e SEO.

Testa-se o que não depende da rede nem do Elasticsearch:

* a normalização dos filtros (tipos, limites e campos desconhecidos);
* a frase legível dos filtros, que serve de resumo e de `meta description`;
* a fotografia da pesquisa montada a partir da lista de municípios;
* a página no CMS: criar, endereço público, publicação, sitemap e SEO, com a
  marca própria (capa, logótipo e cor de destaque).
"""
from __future__ import annotations

from typing import Any, Dict

import pytest

from api import cms_render
from api import cms_store as store
from api import pesquisas_publicas as pesquisas


# ---------------------------------------------------------------------------
# Filtros
# ---------------------------------------------------------------------------

def test_normalizar_filtros_tipa_e_limita() -> None:
    limpos = store.normalizar_filtros(
        {
            "q": "  porto ",
            "distrito": "Porto",
            "ano_contratos": "2024",
            "ordenar": "contratos",
            "ordem": "ASC",
            "min_despesas": "1000",
            "limite": "500",
            "campo_desconhecido": "ignorado",
        }
    )

    assert limpos == {
        "q": "porto",
        "distrito": "Porto",
        "nuts": "",
        "ano_contratos": 2024,
        "ordenar": "contratos",
        "ordem": "asc",
        "min_despesas": 1000,
        "limite": 200,  # o máximo aceite
    }


def test_normalizar_filtros_com_lixo_nao_rebenta() -> None:
    limpos = store.normalizar_filtros({"ano_contratos": "abc", "limite": None, "ordem": "qualquer"})

    assert limpos["ano_contratos"] is None
    assert limpos["limite"] == 25
    assert limpos["ordem"] == "desc"


def test_descricao_dos_filtros_em_portugues() -> None:
    texto = pesquisas.descricao_dos_filtros(
        {"distrito": "Porto", "ano_contratos": 2024, "ordenar": "contratos"}
    )

    assert texto == "distrito de Porto, contratação de 2024, ordenado por valor contratado (decrescente)"


def test_descricao_dos_filtros_sem_filtros_diz_a_ordenacao() -> None:
    assert pesquisas.descricao_dos_filtros({}) == "ordenado por despesa total (decrescente)"


# ---------------------------------------------------------------------------
# Fotografia dos números
# ---------------------------------------------------------------------------

def _resposta(monkeypatch: pytest.MonkeyPatch) -> None:
    def falso_listar(**_kwargs: Any) -> Dict[str, Any]:
        return {
            "total": 18,
            "origem": "json-local",
            "ano_contratos": 2024,
            "items": [
                {
                    "nome": "Porto",
                    "geocod": "131202",
                    "distrito": "Porto",
                    "ano_despesas": 2023,
                    "despesas_total": 317_577_000.0,
                    "despesas_pessoal": 120_000_000.0,
                    "despesas_por_ano": {
                        "2021": {"D": 280_000_000.0},
                        "2022": {"D": 300_000_000.0},
                        "2023": {"D": 317_577_000.0},
                    },
                    "adjudicantes": ["Município do Porto"],
                    "contratos_total": 5375,
                    "contratos_valor": 429_200_000.0,
                    "contratos_ano_total": 1468,
                    "contratos_ano_valor": 140_360_316.0,
                    "contratos_recentes": [
                        {"ano": "2026", "contratos": 425, "valor": 105_197_241.0},
                        {"ano": "2025", "contratos": 556, "valor": 113_903_101.0},
                    ],
                }
            ],
            "despesas_somadas": 1_590_878_000.0,
            "contratos_somados": 6_256_580_851.0,
            "contratos_ano_somados": 868_817_792.0,
            "contratos_ano_total_somados": 7200,
            "distritos": [{"key": "Porto", "count": 18}],
        }

    def falso_fornecedores(*_args: Any, **_kwargs: Any) -> Dict[str, Any]:
        return {
            "total": 3892,
            "valor": 888_105_537.0,
            "ano": 2024,
            "itens": [
                {"nome": "Edilages", "contratos": 42, "valor": 48_737_249.0},
                {"nome": "GERTAL", "contratos": 1, "valor": 38_355_621.0},
            ],
        }

    monkeypatch.setattr(pesquisas.municipios, "listar", falso_listar)
    monkeypatch.setattr(pesquisas.municipios, "fornecedores_de_varios", falso_fornecedores)


def test_dados_da_pesquisa_monta_a_fotografia(monkeypatch: pytest.MonkeyPatch) -> None:
    _resposta(monkeypatch)

    dados = pesquisas.dados_da_pesquisa(
        {"distrito": "Porto", "ano_contratos": 2024, "ordenar": "contratos", "limite": 5}
    )

    assert dados["total"] == 18
    assert dados["linhas"] == 1
    assert dados["ano_contratos"] == 2024
    assert dados["ano_despesas"] == 2023
    assert dados["contratos_ano_total_somados"] == 7200
    assert dados["itens"][0]["nome"] == "Porto"
    assert dados["itens"][0]["anos_recentes"][0]["ano"] == "2026"
    assert dados["descricao"].startswith("distrito de Porto")
    assert [fonte["documento"] for fonte in dados["fontes"]]


def test_dados_da_pesquisa_traz_graficos_e_adjudicatarios(monkeypatch: pytest.MonkeyPatch) -> None:
    _resposta(monkeypatch)

    dados = pesquisas.dados_da_pesquisa({"distrito": "Porto", "ano_contratos": 2024, "ordenar": "contratos"})

    municipios_grafico = next(g for g in dados["graficos"] if g["id"] == "municipios")
    assert municipios_grafico["subtitulo"] == "Valor contratado em 2024"
    assert municipios_grafico["unidade"] == "euros"
    assert municipios_grafico["itens"][0]["rotulo"] == "Porto"
    assert municipios_grafico["itens"][0]["valor"] == 140_360_316.0

    anos = next(g for g in dados["graficos"] if g["id"] == "anos_contratos")
    assert [linha["rotulo"] for linha in anos["itens"]] == ["2025", "2026"]
    assert anos["itens"][0]["contratos"] == 556

    despesas = next(g for g in dados["graficos"] if g["id"] == "anos_despesas")
    assert [linha["rotulo"] for linha in despesas["itens"]] == ["2021", "2022", "2023"]
    assert despesas["itens"][-1]["valor"] == 317_577_000.0

    assert dados["adjudicatarios"]["total"] == 3892
    assert dados["adjudicatarios"]["ano"] == 2024
    assert dados["adjudicatarios"]["itens"][0]["nome"] == "Edilages"
    assert "adjudicatários" in pesquisas.resumo_dos_dados(dados)


def test_resumo_dos_dados_fala_do_filtro_e_do_ano(monkeypatch: pytest.MonkeyPatch) -> None:
    _resposta(monkeypatch)

    resumo = pesquisas.resumo_dos_dados(pesquisas.dados_da_pesquisa({"ano_contratos": 2024}))

    assert "18 municípios" in resumo
    assert "em 2024" in resumo
    assert "7 200 contratos" in resumo


def test_opcoes_tem_distritos_e_anos() -> None:
    escolhas = pesquisas.opcoes()

    assert escolhas["limite_maximo"] == pesquisas.LIMITE_MAXIMO
    assert any(item["id"] == "contratos" for item in escolhas["ordenacoes"])
    assert all(distrito and distrito != "—" for distrito in escolhas["distritos"])


# ---------------------------------------------------------------------------
# Página no CMS: publicação, endereço, SEO e marca
# ---------------------------------------------------------------------------

@pytest.fixture()
def cms_limpo(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> Any:
    """Um CMS vazio em disco, para as páginas de teste não tocarem no real."""
    monkeypatch.setattr(store, "CMS_DIR", tmp_path)
    monkeypatch.setattr(store, "CMS_PATH", tmp_path / "cms.json")
    monkeypatch.setattr(store, "MEDIA_DIR", tmp_path / "media")
    with store._lock:
        store._cache = None
        store._cache_mtime = None
    yield store
    with store._lock:
        store._cache = None
        store._cache_mtime = None


def _pagina(**extra: Any) -> Dict[str, Any]:
    pagina: Dict[str, Any] = {
        "title": "Maiores contratações do distrito do Porto em 2024",
        "slug": "porto-2024",
        "status": "rascunho",
        "filtros": {"distrito": "Porto", "ano_contratos": 2024, "ordenar": "contratos", "limite": 10},
        "descricao_filtros": "distrito de Porto, contratação de 2024, ordenado por valor contratado (decrescente)",
        "intro": "## Onde se contrata mais\n\nRanking do distrito.",
        "cor": "#1d4ed8",
        "capa_id": "med_capa",
        "logo_id": "med_logo",
        "seo": {
            "title": "Contratos do Porto em 2024",
            "description": "Ranking dos municípios do distrito do Porto pela contratação de 2024.",
            "keywords": ["contratação", "porto", "2024"],
        },
        "dados": {
            "total": 18,
            "linhas": 1,
            "ano_contratos": 2024,
            "ano_despesas": 2023,
            "descricao": "distrito de Porto, contratação de 2024",
            "despesas_somadas": 1_590_878_000.0,
            "contratos_somados": 6_256_580_851.0,
            "contratos_ano_somados": 868_817_792.0,
            "contratos_ano_total_somados": 7200,
            "itens": [
                {
                    "nome": "Porto",
                    "distrito": "Porto",
                    "despesas_total": 317_577_000.0,
                    "contratos_ano_total": 1468,
                    "contratos_ano_valor": 140_360_316.0,
                    "anos_recentes": [{"ano": "2026", "contratos": 425, "valor": 1.0}],
                }
            ],
            "fontes": [{"documento": "INE · indicador 0013909", "url": "https://www.ine.pt"}],
            "graficos": [
                {
                    "id": "municipios",
                    "titulo": "Municípios do filtro",
                    "subtitulo": "Valor contratado em 2024",
                    "unidade": "euros",
                    "itens": [
                        {"rotulo": "Porto", "valor": 140_360_316.0, "nota": "1 468 contratos"},
                        {"rotulo": "Matosinhos", "valor": 70_000_000.0, "nota": None},
                    ],
                },
                {
                    "id": "anos_contratos",
                    "titulo": "Contratado por ano",
                    "subtitulo": "Portal BASE",
                    "unidade": "euros",
                    "itens": [
                        {"rotulo": "2025", "valor": 113_903_101.0, "contratos": 556},
                        {"rotulo": "2026", "valor": 105_197_241.0, "contratos": 425},
                    ],
                },
            ],
            "adjudicatarios": {
                "ano": 2024,
                "total": 3892,
                "valor": 888_105_537.0,
                "municipios": 18,
                "itens": [
                    {"nome": "Edilages", "contratos": 42, "valor": 48_737_249.0},
                    {"nome": "GERTAL", "contratos": 1, "valor": 38_355_621.0},
                ],
            },
            "gerado_em": "2026-10-13T21:30:00Z",
        },
    }
    pagina.update(extra)
    return pagina


def test_pagina_de_pesquisa_publica_e_tem_endereco(cms_limpo: Any) -> None:
    item = store.save_item("pesquisas", _pagina(), "qa@teste.pt")

    assert store.pesquisa_by_slug("porto-2024", published_only=True) is None  # ainda é rascunho
    assert store.pesquisa_by_slug("porto-2024", published_only=False) is not None

    store.publish_item("pesquisas", item["id"], "qa@teste.pt")

    publicada = store.pesquisa_by_slug("porto-2024")
    assert publicada is not None
    assert publicada["status"] == "publicado"
    assert store.pesquisa_path(publicada) == "/pesquisa/porto-2024"
    assert [entrada["slug"] for entrada in store.published_pesquisas()] == ["porto-2024"]
    assert "/site/pesquisa/porto-2024" in cms_render.render_sitemap()


def test_pagina_de_pesquisa_normaliza_filtros_ao_guardar(cms_limpo: Any) -> None:
    item = store.save_item("pesquisas", _pagina(filtros={"distrito": "Porto", "limite": "999"}), "qa@teste.pt")

    assert item["filtros"]["limite"] == 200
    assert item["id"].startswith("pes_")
    assert item["excerpt"]  # resumo gerado a partir do texto de entrada


def test_pagina_de_pesquisa_sem_titulo_falha(cms_limpo: Any) -> None:
    with pytest.raises(ValueError):
        store.save_item("pesquisas", {"title": "", "slug": "sem-titulo"}, "qa@teste.pt")


# ---------------------------------------------------------------------------
# Trilha de navegação (breadcrumbs)
# ---------------------------------------------------------------------------

def test_trilha_da_pagina_de_pesquisa(cms_limpo: Any) -> None:
    item = store.save_item("pesquisas", _pagina(), "qa@teste.pt")

    html = cms_render.render_pesquisa(item)

    assert 'class="breadcrumb"' in html
    assert '<a href="/site">Início</a>' in html
    assert ">Pesquisas</span>" in html
    assert 'aria-current="page">Maiores contratações do distrito do Porto em 2024</span>' in html
    assert '"@type": "BreadcrumbList"' in html
    assert '"position": 2' in html


def test_trilha_da_ficha_de_municipio(cms_limpo: Any) -> None:
    html = cms_render.render_municipio(
        {"title": "Despesas da Câmara Municipal de Braga", "slug": "braga", "municipio": "Braga"}
    )

    # «Municípios» tem índice próprio (a página da Solução): a trilha leva lá.
    assert '<a href="/site/solucoes/municipios">Municípios</a>' in html
    assert 'aria-current="page">Braga</span>' in html


def test_trilha_das_paginas_sobe_pelos_ascendentes(cms_limpo: Any) -> None:
    pai = store.save_item("pages", {"title": "Secção", "slug": "seccao"}, "qa@teste.pt")
    filho = store.save_item(
        "pages", {"title": "Página", "slug": "pagina", "parent_id": pai["id"]}, "qa@teste.pt"
    )

    html = cms_render.render_page(filho)

    assert '<a href="/site">Início</a>' in html
    assert '<a href="/site/seccao">Secção</a>' in html
    assert 'aria-current="page">Página</span>' in html


def test_pagina_inicial_nao_leva_trilha(cms_limpo: Any) -> None:
    inicial = store.save_item("pages", {"title": "Início do site", "slug": "home"}, "qa@teste.pt")
    store.save_settings({"home_page_id": inicial["id"]}, "qa@teste.pt")

    html = cms_render.render_page(store.get_item("pages", inicial["id"]))

    assert 'class="breadcrumb"' not in html


def test_render_da_pagina_tem_seo_marca_e_tabela(cms_limpo: Any) -> None:
    capa = store.save_media({"title": "Capa", "url": "https://exemplo.test/capa.jpg"}, "qa@teste.pt")
    logo = store.save_media({"title": "Logótipo", "url": "https://exemplo.test/logo.png"}, "qa@teste.pt")
    item = store.save_item(
        "pesquisas",
        _pagina(capa_id=capa["id"], logo_id=logo["id"]),
        "qa@teste.pt",
    )

    html = cms_render.render_pesquisa(item)

    assert "<title>Contratos do Porto em 2024" in html
    assert 'name="description" content="Ranking dos municípios' in html
    assert 'rel="canonical" href="' in html and "/site/pesquisa/porto-2024" in html
    assert '"@type": "Dataset"' in html
    assert "--accent: #1d4ed8" in html  # cor própria da página
    assert "https://exemplo.test/capa.jpg" in html  # imagem de capa
    assert "https://exemplo.test/logo.png" in html  # logótipo
    assert "Municípios do filtro" in html
    assert "Contratado em 2024" in html and "868,8 M€" in html
    assert "1 468" in html  # linha do Porto (contratos de 2024)
    assert "INE · indicador 0013909" in html  # proveniência


def test_render_da_pagina_tem_h1_com_o_titulo(cms_limpo: Any) -> None:
    """O `<h1>` vinha só do bloco «hero»: sem ele, a página saía sem cabeçalho.

    É o erro «H1 tag missing» dos relatórios de SEO — o título do documento
    passa a servir de cabeçalho quando mais nenhum existe.
    """
    item = store.save_item("pesquisas", _pagina(), "qa@teste.pt")

    html = cms_render.render_pesquisa(item)

    assert html.count("<h1") == 1
    assert "<h1>Contratos do Porto em 2024</h1>" in html  # o mesmo que no `<title>`


def test_pagina_com_hero_nao_ganha_um_segundo_h1(cms_limpo: Any) -> None:
    """Com bloco «hero» é o hero que dá o `<h1>`: não se acrescenta outro."""
    html = cms_render.render_page(
        {
            "title": "Sobre o projeto",
            "path": "sobre",
            "blocks": [{"type": "hero", "data": {"title": "Inteligência financeira"}}],
        }
    )

    assert html.count("<h1") == 1
    assert "<h1>Inteligência financeira</h1>" in html


@pytest.mark.parametrize("style", ["cartao", "destaque", "imagem", "lateral"])
def test_hero_configura_variante_e_cor(cms_limpo: Any, style: str) -> None:
    """O editor escolhe o formato e a cor sem mudar o `<h1>` da página."""
    html = cms_render.render_page(
        {
            "title": "Sobre o projeto",
            "path": "sobre",
            "blocks": [
                {
                    "type": "hero",
                    "data": {"title": "Inteligência financeira", "style": style, "tone": "azul"},
                }
            ],
        }
    )

    assert f"hero--{style}" in html
    assert "hero--tom-azul" in html
    assert html.count("<h1") == 1


def test_hero_com_variante_desconhecida_volta_ao_simples(cms_limpo: Any) -> None:
    html = cms_render.render_page(
        {
            "title": "Sobre o projeto",
            "path": "sobre",
            "blocks": [{"type": "hero", "data": {"title": "Inteligência financeira", "style": "inexistente", "tone": "inexistente"}}],
        }
    )

    assert "hero--simples" in html
    assert "hero--tom-acento" in html


def test_hero_imagem_usa_a_fotografia_como_fundo(cms_limpo: Any) -> None:
    capa = store.save_media({"title": "Capa", "url": "https://exemplo.test/capa.jpg"}, "qa@teste.pt")

    html = cms_render.render_page(
        {
            "title": "Sobre o projeto",
            "path": "sobre",
            "blocks": [{"type": "hero", "data": {"title": "Inteligência financeira", "style": "imagem", "image_id": capa["id"]}}],
        }
    )

    assert 'class="hero-bg"' in html
    assert "https://exemplo.test/capa.jpg" in html


def test_catalogo_expoe_e_guarda_as_variantes_do_hero(cms_limpo: Any) -> None:
    """O editor recebe as opções do servidor e o bloco guarda-as como estão."""
    catalogo = store.catalogue()

    assert {item["id"] for item in catalogo["hero_styles"]} == {"simples", "cartao", "destaque", "imagem", "lateral"}
    assert "azul" in {item["id"] for item in catalogo["hero_tones"]}

    pagina = store.save_item(
        "pages",
        {
            "title": "Sobre o projeto",
            "slug": "sobre",
            "blocks": [{"type": "hero", "data": {"title": "Inteligência financeira", "style": "cartao", "tone": "violeta"}}],
        },
        "qa@teste.pt",
    )

    assert pagina["blocks"][0]["data"]["style"] == "cartao"
    assert pagina["blocks"][0]["data"]["tone"] == "violeta"


def test_qualquer_bloco_aceita_a_aparencia_comum(cms_limpo: Any) -> None:
    """Fundo, cor, alinhamento e espaçamento valem para todos os blocos."""
    html = cms_render.render_page(
        {
            "title": "Sobre o projeto",
            "path": "sobre",
            "blocks": [
                {
                    "type": "texto",
                    "data": {
                        "markdown": "Texto corrido.",
                        "appearance": {"surface": "cartao", "tone": "azul", "align": "centro", "density": "amplo"},
                    },
                },
                {
                    "type": "cta",
                    "data": {"title": "Fale connosco", "appearance": {"surface": "destaque", "tone": "rosa"}},
                },
                {
                    "type": "citacao",
                    "data": {"quote": "Uma frase.", "appearance": {"surface": "suave", "density": "compacto"}},
                },
            ],
        }
    )

    assert 'class="section prose bloco bloco--cartao bloco--tom-azul bloco--centro bloco--amplo"' in html
    assert 'class="section cta bloco bloco--destaque bloco--tom-rosa"' in html
    assert '<blockquote class="bloco bloco--suave bloco--compacto">' in html


def test_aparencia_com_valores_desconhecidos_nao_estraga_o_bloco(cms_limpo: Any) -> None:
    html = cms_render.render_page(
        {
            "title": "Sobre o projeto",
            "path": "sobre",
            "blocks": [
                {
                    "type": "texto",
                    "data": {
                        "markdown": "Texto corrido.",
                        "appearance": {"surface": "inexistente", "tone": "inexistente", "density": "inexistente"},
                    },
                }
            ],
        }
    )

    assert 'class="section prose"' in html
    assert "bloco--" not in html


def test_hero_ignora_a_aparencia_generica(cms_limpo: Any) -> None:
    """O hero tem variantes próprias: a aparência comum não se sobrepõe."""
    html = cms_render.render_page(
        {
            "title": "Sobre o projeto",
            "path": "sobre",
            "blocks": [{"type": "hero", "data": {"title": "Inteligência financeira", "appearance": {"surface": "cartao"}}}],
        }
    )

    assert "bloco--cartao" not in html
    assert "hero--simples" in html


def test_pagina_sem_hero_tem_h1_com_o_titulo(cms_limpo: Any) -> None:
    html = cms_render.render_page(
        {
            "title": "Sobre o projeto",
            "path": "sobre",
            "blocks": [{"type": "texto", "data": {"markdown": "Texto corrido."}}],
        }
    )

    assert html.count("<h1") == 1
    assert "<h1>Sobre o projeto</h1>" in html


def test_render_da_pagina_tem_graficos_e_adjudicatarios(cms_limpo: Any) -> None:
    item = store.save_item("pesquisas", _pagina(), "qa@teste.pt")

    html = cms_render.render_pesquisa(item)

    assert '<ul class="barras">' in html
    assert '<i style="width:100%"></i>' in html  # a maior barra do gráfico
    assert "Valor contratado em 2024" in html
    assert "Contratado por ano" in html and "113,9 M€" in html

    assert "Principais adjudicatários" in html
    assert "3 892 adjudicatários" in html
    assert '<span class="rotulo">Edilages</span>' in html  # a barra leva o nome
    assert '<span class="rotulo">Porto</span>' in html  # e a dos municípios também
    assert "Edilages" in html and "48 737 249" not in html and "48,7 M€" in html
    assert "GERTAL" in html
