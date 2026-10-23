"""Partilhar e favoritos no site, e a lista de estudos em `/site/benchmarks`.

O que se prova aqui:

* a barra de ações (blog e estudo) traz o menu de partilha, o botão de guardar
  e a ligação para a lista — e o script uma só vez por página;
* o menu de partilha traz o catálogo das redes (TikTok, YouTube, Reddit, …) e
  respeita as que o CMS escolher;
* os cartões do blog levam a estrela e a partilha, e o topo do blog a barra —
  desligáveis nas definições;
* a estrela dos cartões guarda o produto com o preço e a loja (é o que a lista
  de favoritos mostra);
* `/site/favoritos` existe, é `noindex` e desenha a moldura que o script usa;
* os modelos de configuração da partilha: os de origem, os que se criam e os
  que não se apagam;
* a página-mãe dos estudos ganha os cartões dos benchmarks publicados, com
  imagem, «desde» e ligação — sem ninguém editar a página do CMS.
"""
from __future__ import annotations

from typing import Any, Dict, List

import pytest
from fastapi.testclient import TestClient

from api import benchmarks_store
from api import cms_render as render
from api import cms_store as cms_store
from api import elasticsearch_client as esc
from api import site_acoes


def _app() -> Any:
    from api import main as api_main

    return api_main.app


@pytest.fixture()
def instalacao(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    """CMS isolado em `tmp_path` (sem ler nem escrever em `data/`)."""
    cms = tmp_path / "cms"
    monkeypatch.setattr(cms_store, "CMS_DIR", cms)
    monkeypatch.setattr(cms_store, "CMS_PATH", cms / "cms.json")
    monkeypatch.setattr(cms_store, "MEDIA_DIR", cms / "media")
    monkeypatch.setattr(cms_store, "_cache", None)
    monkeypatch.setattr(cms_store, "_cache_mtime", None)
    yield


# ------------------------------------------------------------------- ações
def test_barra_de_acoes_tem_partilha_guardar_e_lista() -> None:
    html = site_acoes.barra_acoes(
        url="https://sabemos.studio/site/blog/exemplo",
        titulo='Um artigo com "aspas"',
        tipo="artigo",
        chave="/site/blog/exemplo",
    )
    assert 'class="site-acoes"' in html
    # As redes levam o endereço e o título codificados (e o `&` escapado uma vez).
    assert "https://wa.me/?text=Um+artigo" in html
    assert "linkedin.com/sharing/share-offsite/?url=https%3A%2F%2Fsabemos.studio" in html
    assert "&amp;url=" in html and "&amp;amp;" not in html
    # A partilha do sistema nasce escondida; a cópia está sempre disponível.
    assert "data-partilhar hidden" in html
    assert 'data-copiar="https://sabemos.studio/site/blog/exemplo"' in html
    assert 'data-favoritar' in html and 'data-chave="/site/blog/exemplo"' in html
    assert 'href="/site/favoritos"' in html and "data-favoritos-ligacao hidden" in html
    # O script entra uma vez e sabe partilhar e copiar.
    assert html.count("<script>") == 1 and html.count("</script>") == 1
    assert "navigator.share" in html and "navigator.clipboard.writeText" in html


def test_estrela_do_cartao_leva_o_produto_para_os_favoritos() -> None:
    html = site_acoes.botao_favorito(
        chave="/site/benchmarks/x/pesquisa#abc",
        url="/site/benchmarks/x/pesquisa#p-abc",
        titulo="Sapatilhas Run",
        preco="36,33 €",
        nota="Amazon Espanha",
        imagem="https://loja.pt/foto.png",
    )
    assert "data-favoritar" in html
    assert 'data-tipo="produto"' in html
    assert 'data-preco="36,33 €"' in html and 'data-nota="Amazon Espanha"' in html
    assert 'data-imagem="https://loja.pt/foto.png"' in html
    assert 'aria-pressed="false"' in html
    # O script não se repete em cada cartão.
    assert "<script" not in html


#: Redes que o catálogo promete no menu (o texto do pedido: TikTok, YouTube,
#: Reddit «e todas as outras»).
REDES_DO_MENU = (
    ("WhatsApp", "wa.me/?text="),
    ("X", "x.com/intent/post?text="),
    ("Facebook", "facebook.com/sharer/sharer.php?u="),
    ("LinkedIn", "linkedin.com/sharing/share-offsite/?url="),
    ("Instagram", 'data-partilha-rede="Instagram"'),
    ("TikTok", 'data-partilha-rede="TikTok"'),
    ("YouTube", 'data-partilha-rede="YouTube"'),
    ("Reddit", "reddit.com/submit?url="),
    ("Telegram", "t.me/share/url?url="),
    ("Threads", "threads.net/intent/post?text="),
    ("Bluesky", "bsky.app/intent/compose?text="),
    ("Pinterest", "pinterest.com/pin/create/button/"),
    ("Tumblr", "tumblr.com/widgets/share/tool?canonicalUrl="),
    ("Email", "mailto:?subject="),
)


def test_o_menu_de_partilha_traz_todas_as_redes() -> None:
    html = site_acoes.barra_acoes(url="https://sabemos.studio/site/blog/x", titulo="Um artigo")
    for nome, marca in REDES_DO_MENU:
        assert marca in html, f"{nome} não está no menu de partilha"
        assert f">{nome}</a>" in html
    # As redes sem link de partilha copiam a ligação antes de abrir.
    assert 'data-partilha-copiar="https://sabemos.studio/site/blog/x"' in html
    # Com muitas redes o menu abre em duas colunas (senão saía do ecrã).
    assert "site-partilha-menu--redes" in html
    # E a cópia explícita continua a existir.
    assert 'data-copiar="https://sabemos.studio/site/blog/x"' in html


def test_o_cms_escolhe_as_redes_do_menu() -> None:
    html = site_acoes.barra_acoes(
        url="https://sabemos.studio/site/blog/x",
        titulo="Um artigo",
        redes=["whatsapp", "reddit", "inventada"],
    )
    assert "wa.me/?text=" in html and "reddit.com/submit" in html
    # O que não está no catálogo nunca entra no HTML.
    assert "inventada" not in html
    assert "linkedin.com/sharing" not in html and "tiktok.com" not in html
    # Com poucas redes o menu fica numa coluna.
    assert "site-partilha-menu--redes" not in html


def test_barra_sem_favoritos_esconde_a_estrela() -> None:
    html = site_acoes.barra_acoes(url="https://sabemos.studio/site/blog/x", titulo="Um artigo", guardar=False)
    assert "data-favoritar data-chave" not in html
    assert "wa.me/?text=" in html


def test_cartao_tem_estrela_e_partilha_e_nao_repete_o_script() -> None:
    html = site_acoes.acoes_do_cartao(
        chave="/site/blog/exemplo",
        url="https://sabemos.studio/site/blog/exemplo",
        titulo="Um artigo",
        redes=["whatsapp", "tiktok"],
    )
    assert "site-cartao-acoes" in html
    assert 'data-favoritar data-chave="/site/blog/exemplo"' in html
    assert 'data-tipo="artigo"' in html
    assert "site-fav-icone--partilha" in html and "wa.me/?text=" in html
    assert "<script" not in html


def test_cartao_sem_redes_nem_favoritos_nao_desenha_barra() -> None:
    assert site_acoes.acoes_do_cartao(chave="/x", url="/x", titulo="X", redes=[], guardar=False) == ""


def test_os_perfis_do_cabecalho_usam_o_catalogo() -> None:
    perfis = site_acoes.perfis_configurados(
        {"email": "geral@exemplo.pt", "tiktok": "https://www.tiktok.com/@exemplo", "x": "", "inventada": "https://x.pt"}
    )
    assert perfis == [
        ("tiktok", "TikTok", "https://www.tiktok.com/@exemplo"),
        ("email", "Email", "mailto:geral@exemplo.pt"),
    ]


# ------------------------------------------------------ cartões e topo do blog
def test_a_lista_do_blog_tem_acoes_nos_cartoes_e_no_topo(instalacao: Any) -> None:
    settings = cms_store.get_settings()
    cms_store.save_settings({"partilha": {"redes": ["whatsapp", "tiktok", "reddit"], "cartoes": True, "cabecalho": True}}, "prova")
    html = render.render_blog(settings=cms_store.get_settings())
    assert "blog-topo" in html and 'class="site-acoes"' in html
    # Um cartão por artigo, cada um com a sua estrela e o seu menu.
    cartoes = html.count('class="site-cartao-acoes"')
    assert cartoes >= 1 and html.count("site-fav-icone--partilha") == cartoes
    assert 'data-partilha-rede="TikTok"' in html
    # O script das ações entra uma vez, não em cada cartão.
    assert html.count("window.SabemosFavoritos = 1") == 1
    assert settings  # (leitura antes da gravação não pode falhar)


def test_as_definicoes_desligam_as_acoes_dos_cartoes_e_do_topo(instalacao: Any) -> None:
    cms_store.save_settings({"partilha": {"cartoes": False, "cabecalho": False}}, "prova")
    html = render.render_blog(settings=cms_store.get_settings())
    assert "site-cartao-acoes" not in html
    assert 'class="site-acoes"' not in html
    # O artigo continua na lista, só sem as ações.
    assert "post-card" in html


def test_o_topo_do_blog_respeita_os_favoritos_desligados(instalacao: Any) -> None:
    cms_store.save_settings({"partilha": {"cartoes": False, "cabecalho": True, "guardar": False}}, "prova")
    html = render.render_blog(settings=cms_store.get_settings())
    assert 'class="site-acoes"' in html
    assert "data-favoritar data-chave" not in html


def test_as_redes_do_cabecalho_so_aparecem_quando_configuradas(instalacao: Any) -> None:
    sem_redes = render.render_blog(settings=cms_store.get_settings())
    assert "site-redes" not in sem_redes

    cms_store.save_settings({"social": {"tiktok": "https://www.tiktok.com/@exemplo"}}, "prova")
    com_redes = render.render_blog(settings=cms_store.get_settings())
    assert 'class="site-redes"' in com_redes
    assert "https://www.tiktok.com/@exemplo" in com_redes


def test_o_bloco_de_partilha_so_aceita_redes_do_catalogo(instalacao: Any) -> None:
    settings = cms_store.save_settings(
        {"partilha": {"redes": ["reddit", "youtube", "inventada", "reddit"], "cartoes": "sim"}}, "prova"
    )
    assert settings["partilha"]["redes"] == ["youtube", "reddit"]
    assert settings["partilha"]["cartoes"] is True


def test_uma_alteracao_parcial_da_partilha_mantem_o_resto(instalacao: Any) -> None:
    cms_store.save_settings({"partilha": {"redes": ["whatsapp"], "cabecalho": False}}, "prova")
    settings = cms_store.save_settings({"partilha": {"cartoes": False}}, "prova")
    assert settings["partilha"]["redes"] == ["whatsapp"]
    assert settings["partilha"]["cabecalho"] is False
    assert settings["partilha"]["cartoes"] is False
    assert settings["partilha"]["guardar"] is True


# ------------------------------------------- modelos de configuração (admins)
def test_os_modelos_de_origem_estao_disponiveis(instalacao: Any) -> None:
    modelos = cms_store.partilha_modelos(cms_store.get_settings())
    ids = [modelo["id"] for modelo in modelos]
    assert ids[:5] == ["completo", "redes-sociais", "profissional", "minimo", "favoritos"]
    assert all(modelo["builtin"] for modelo in modelos)
    # «Redes sociais» traz mesmo TikTok, Instagram e YouTube.
    redes_sociais = next(modelo for modelo in modelos if modelo["id"] == "redes-sociais")
    assert {"tiktok", "youtube", "instagram"} <= set(redes_sociais["partilha"]["redes"])


def test_criar_e_apagar_modelos_de_configuracao(instalacao: Any) -> None:
    modelos = cms_store.save_partilha_modelo(
        {"name": "Campanha de outono", "description": "Só redes jovens", "partilha": {"redes": ["tiktok", "youtube"]}},
        "admin@exemplo.pt",
    )
    novo = next(modelo for modelo in modelos if modelo["name"] == "Campanha de outono")
    assert novo["builtin"] is False and novo["partilha"]["redes"] == ["tiktok", "youtube"]

    restantes = cms_store.delete_partilha_modelo(novo["id"], "admin@exemplo.pt")
    assert novo["id"] not in [modelo["id"] for modelo in restantes]
    # Os de origem não saem.
    assert len(restantes) == 5


def test_um_modelo_sem_nome_e_recusado(instalacao: Any) -> None:
    with pytest.raises(ValueError):
        cms_store.save_partilha_modelo({"name": "  "}, "admin@exemplo.pt")


def test_so_admin_muda_a_partilha_nas_definicoes(instalacao: Any) -> None:
    """O painel envia as definições todas: só a alteração da partilha é de admin."""
    from fastapi import HTTPException

    from api import cms_routes

    class Utilizador:
        def __init__(self, role: str) -> None:
            self.email = f"{role}@exemplo.pt"
            self.role = role

    class Sessao:
        def __init__(self, role: str) -> None:
            self.user = Utilizador(role)

    membro = Sessao("member")
    admin = Sessao("admin")
    atuais = cms_store.get_settings()

    # Um membro a gravar o nome do site com a partilha igual à que está guardada: passa.
    cms_routes.cms_put_settings({"site_name": "Outro nome", "partilha": atuais["partilha"]}, membro)
    assert cms_store.get_settings()["site_name"] == "Outro nome"

    # A mesma gravação com uma partilha diferente: recusada.
    with pytest.raises(HTTPException) as erro:
        cms_routes.cms_put_settings({"partilha": {"cartoes": False}}, membro)
    assert erro.value.status_code == 403

    # Um administrador muda.
    resposta = cms_routes.cms_put_settings({"partilha": {"redes": ["tiktok", "youtube"]}}, admin)
    assert resposta["settings"]["partilha"]["redes"] == ["tiktok", "youtube"]

    # Sem sessão não se escreve no CMS (como em qualquer escrita).
    with pytest.raises(HTTPException) as anonimo:
        cms_routes.cms_put_settings({"site_name": "X"}, None)
    assert anonimo.value.status_code == 401


def test_so_admin_cria_modelos_de_configuracao(instalacao: Any) -> None:
    from fastapi import HTTPException

    from api import cms_routes

    class Utilizador:
        email = "membro@exemplo.pt"
        role = "member"

    class Sessao:
        user = Utilizador()

    with pytest.raises(HTTPException) as erro:
        cms_routes.cms_create_partilha_modelo({"name": "Da equipa"}, Sessao())
    assert erro.value.status_code == 403
    with pytest.raises(HTTPException) as aplicar:
        cms_routes.cms_aplicar_partilha_modelo("completo", Sessao())
    assert aplicar.value.status_code == 403


def test_a_pagina_de_favoritos_desenha_a_moldura_da_lista(instalacao: Any) -> None:
    html = render.render_favoritos(settings=cms_store.get_settings())
    assert "<h1>Favoritos</h1>" in html
    assert 'data-favoritos-itens' in html
    assert 'data-favoritos-vazio' in html and 'data-favoritos-limpar' in html
    assert "window.SabemosFavoritos" in html
    assert 'content="noindex, nofollow"' in html
    assert 'href="/site/favoritos"' in html  # canónica

    resposta = TestClient(_app(), base_url="http://prova").get("/site/favoritos")
    assert resposta.status_code == 200
    assert "Ainda não guardou nada" in resposta.text


# ------------------------------------------------------- estudos na página-mãe
def _benchmark_publico() -> Dict[str, Any]:
    return {
        "slug": "sapatilhas-lojas",
        "name": "Sapatilhas — comparação entre lojas",
        "description": "O mesmo modelo comparado entre lojas.",
        "category": "Calçado",
        "currency": "EUR",
        "public": True,
        "stores": [{"id": "nike"}, {"id": "decathlon"}],
    }


def test_cartao_do_estudo_mostra_imagem_e_preco(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        esc,
        "benchmark_product_comparison",
        lambda *a, **k: {
            "items": [
                {
                    "product_name": "Sapatilhas Run",
                    "price_min": 36.33,
                    "stores": 2,
                    "best": {"image": "https://loja.pt/foto.png", "store_name": "Amazon"},
                }
            ],
            "total": 110,
        },
    )
    html = render._cartao_estudo(_benchmark_publico())  # noqa: SLF001 - o cartão é o objeto do teste
    assert "estudo-card" in html
    assert "https://loja.pt/foto.png" in html
    assert "desde 36,33 €" in html
    assert "2 lojas" in html and "110 produtos" in html
    assert 'href="/site/benchmarks/sapatilhas-lojas/pesquisa"' in html


def test_pagina_dos_benchmarks_ganha_a_lista_dos_estudos(
    instalacao: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(benchmarks_store, "publicos", lambda: [_benchmark_publico()])
    monkeypatch.setattr(
        esc,
        "benchmark_product_comparison",
        lambda *a, **k: {
            "items": [
                {
                    "product_name": "Sapatilhas Run",
                    "price_min": 36.33,
                    "stores": 2,
                    "best": {"image": "https://loja.pt/foto.png"},
                }
            ],
            "total": 20,
        },
    )
    pagina = {
        "id": "pagina-benchmarks",
        "slug": "benchmarks",
        "title": "Benchmarks de produtos",
        "path": "benchmarks",
        "status": "publicado",
        "blocks": [
            {"type": "hero", "data": {"title": "Benchmarks de produtos", "subtitle": "Comparações"}},
            {"type": "texto", "data": {"title": "Como ler", "markdown": "Texto de apoio."}},
        ],
    }
    html = render.render_page(pagina, settings=cms_store.get_settings())
    assert "Estudos publicados" in html
    assert 'href="/site/benchmarks/sapatilhas-lojas/pesquisa"' in html
    # A lista entra logo a seguir à abertura, antes do texto de apoio.
    assert html.index('data-bloco="hero"') < html.index("Estudos publicados") < html.index("Como ler")


def test_sem_estudos_publicados_a_seccao_nao_aparece(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(benchmarks_store, "publicos", lambda: [])
    assert render._seccao_estudos() == ""  # noqa: SLF001


def test_bloco_de_estudos_configura_desenho_e_colunas(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(benchmarks_store, "publicos", lambda: [_benchmark_publico()])
    monkeypatch.setattr(
        esc,
        "benchmark_product_comparison",
        lambda *a, **k: {
            "items": [
                {
                    "product_name": "Sapatilhas Run",
                    "price_min": 36.33,
                    "best": {"image": "https://loja.pt/foto.png"},
                }
            ],
            "total": 3,
        },
    )
    html = render._render_block(  # noqa: SLF001 - o bloco é o objeto do teste
        {
            "type": "estudos",
            "data": {
                "title": "Os nossos estudos",
                "intro": "Escolha um para comparar.",
                "layout": "lista",
                "columns": 2,
                "limit": 1,
                "show_image": False,
                "show_price": False,
            },
        }
    )
    assert "estudos--lista" in html and "estudos--cols-1" in html
    assert "Os nossos estudos" in html and "Escolha um para comparar." in html
    assert "estudo-figura--vazia" in html and "<img" not in html
    assert "desde " not in html
    assert "1 estudo" in html


def test_a_pagina_nao_duplica_a_lista_quando_o_bloco_esta_na_pagina(
    instalacao: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(benchmarks_store, "publicos", lambda: [_benchmark_publico()])
    monkeypatch.setattr(
        esc,
        "benchmark_product_comparison",
        lambda *a, **k: {"items": [{"product_name": "X", "price_min": 1.0, "best": {}}], "total": 1},
    )
    pagina = {
        "id": "pagina-benchmarks",
        "slug": "benchmarks",
        "title": "Benchmarks de produtos",
        "path": "benchmarks",
        "status": "publicado",
        "blocks": [
            {"type": "hero", "data": {"title": "Benchmarks de produtos"}},
            {"type": "estudos", "data": {"title": "Escolha um estudo"}},
        ],
    }
    html = render.render_page(pagina, settings=cms_store.get_settings())
    assert html.count("estudos-grid") == 1
    assert "Escolha um estudo" in html
