"""Testes do módulo de **benchmarks de produtos** (`api/benchmarks_*`).

Cobrem as partes que decidem resultados e que já falharam uma vez:

- leitura de preços em formatos portugueses/internacionais;
- normalização de uma oferta (chave de produto, desconto, stock);
- `field_map` a sobrepor-se à deteção por nome de campo;
- normalização/validação da definição (slug, lojas obrigatórias, chave de comparação);
- atualização da definição sem perder o slug (o slug é o id do índice);
- publicação no CMS de uma definição migrada de outra instalação (o
  `cms_page_id` que veio no índice não existe aqui e não pode dar 500).

O Elasticsearch e o scraper estão sempre substituídos: testam-se as funções
puras e a ligação ao CMS, com o CMS isolado numa pasta temporária.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api import benchmarks_service as servico  # noqa: E402
from api import benchmarks_store as store  # noqa: E402


# ---------------------------------------------------------------------------
# Preços
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "entrada,esperado",
    [
        ("1.234,56 €", 1234.56),
        ("€ 12,50", 12.5),
        ("1234.56", 1234.56),
        ("1,299.00", 1299.0),
        ("15", 15.0),
        ("£51.77", 51.77),
        ("  ", None),
        ("sem preço", None),
        (None, None),
        ("-", None),
        (19.99, 19.99),
    ],
)
def test_preco_para_float(entrada, esperado):
    assert servico.preco_para_float(entrada) == esperado


@pytest.mark.parametrize(
    "entrada,esperado",
    [
        # Como a Worten devolve o preço: partido em elementos, com espaços, e com
        # o preço riscado no mesmo nó.
        ("€ 799 , 99 € 999 ,99", 799.99),
        ("799 , 99 €", 799.99),
        ("12,50 € 15,00 €", 12.5),
        ("1 299,00 €", 1299.0),
    ],
)
def test_preco_para_float_com_varios_precos_no_mesmo_texto(entrada, esperado):
    """Fica o **primeiro** preço (o que se paga), não a mistura dos dois."""
    assert servico.preco_para_float(entrada) == esperado


def test_oferta_guarda_descricao_e_absolutiza_urls():
    item = {
        "data": {
            "titulo": "Portátil XPTO",
            "preco": "799,99 €",
            "imagem": "/media/xpto.jpg",
            "descricao": "Portátil com 16 GB de RAM e 512 GB de SSD.",
        },
        "url": "/produtos/portatil-xpto",
        "item_id": "1",
    }
    oferta = servico.normalizar_oferta(item, loja=_loja(), benchmark=BENCHMARK_BASE)
    assert oferta is not None
    assert oferta["description"].startswith("Portátil com 16 GB")
    assert oferta["url"] == "https://exemplo.pt/produtos/portatil-xpto"
    assert oferta["image"] == "https://exemplo.pt/media/xpto.jpg"


# ---------------------------------------------------------------------------
# Normalização de ofertas
# ---------------------------------------------------------------------------
BENCHMARK_BASE = {
    "slug": "demo",
    "name": "Demo",
    "match_on": "nome",
    "currency": "EUR",
    "field_map": {},
}


def _loja(identificador: str = "loja-a") -> dict:
    return {"id": identificador, "name": f"Loja {identificador}", "url": "https://exemplo.pt"}


def test_oferta_usa_nomes_conhecidos_dos_campos():
    item = {
        "data": {"titulo": "Portátil XPTO 16GB", "preco": "1.299,00 €", "marca": "XPTO", "disponibilidade": "Em stock"},
        "url": "https://exemplo.pt/p/1",
        "item_id": "abc",
        "scraped_at": "2026-10-11T10:00:00Z",
    }
    oferta = servico.normalizar_oferta(item, loja=_loja(), benchmark=BENCHMARK_BASE)
    assert oferta is not None
    assert oferta["price"] == 1299.0
    assert oferta["product_name"] == "Portátil XPTO 16GB"
    assert oferta["brand"] == "XPTO"
    assert oferta["in_stock"] is True
    assert oferta["product_key"] == "nome:portatil xpto 16gb"
    assert oferta["store_id"] == "loja-a"


def test_oferta_field_map_manda_sobre_a_detetcao_por_nome():
    benchmark = {**BENCHMARK_BASE, "field_map": {"price": "valor_final", "product_name": "descricao_curta"}}
    item = {"data": {"preco": "9,99", "valor_final": "7,49", "titulo": "Errado", "descricao_curta": "Certo"}, "item_id": "x"}
    oferta = servico.normalizar_oferta(item, loja=_loja(), benchmark=benchmark)
    assert oferta is not None
    assert oferta["price"] == 7.49
    assert oferta["product_name"] == "Certo"


def test_oferta_sem_preco_e_descartada():
    item = {"data": {"titulo": "Sem preço"}, "item_id": "x"}
    assert servico.normalizar_oferta(item, loja=_loja(), benchmark=BENCHMARK_BASE) is None


def test_oferta_com_ean_usa_ean_como_chave():
    benchmark = {**BENCHMARK_BASE, "match_on": "ean"}
    item = {
        "data": {"titulo": "Livro", "preco": "10,00", "ean": "978-989-000-000-1"},
        "item_id": "x",
    }
    oferta = servico.normalizar_oferta(item, loja=_loja(), benchmark=benchmark)
    assert oferta is not None
    assert oferta["product_key"] == "ean:9789890000001"


def test_oferta_calcula_desconto_e_marca_esgotado():
    item = {
        "data": {"titulo": "Teclado", "preco": "30,00", "preco_antigo": "50,00", "disponibilidade": "Esgotado"},
        "item_id": "x",
    }
    oferta = servico.normalizar_oferta(item, loja=_loja(), benchmark=BENCHMARK_BASE)
    assert oferta is not None
    assert oferta["price_original"] == 50.0
    assert oferta["discount_pct"] == 40.0
    assert oferta["in_stock"] is False


# ---------------------------------------------------------------------------
# Definição do benchmark
# ---------------------------------------------------------------------------
def test_normalize_benchmark_gera_slug_e_loja():
    definicao = store.normalize_benchmark(
        {
            "name": "Portáteis 16 GB",
            "stores": [{"name": "Loja A", "url": "https://a.pt"}],
        }
    )
    assert definicao["slug"] == "portateis-16-gb"
    assert definicao["match_on"] == "nome"
    assert len(definicao["stores"]) == 1
    assert definicao["stores"][0]["id"] == "loja-a"


def test_normalize_benchmark_exige_loja_e_nome():
    with pytest.raises(ValueError):
        store.normalize_benchmark({"name": "Sem lojas"})
    with pytest.raises(ValueError):
        store.normalize_benchmark({"name": "", "stores": [{"name": "A", "url": "https://a.pt"}]})


def test_normalize_benchmark_normaliza_chave_de_comparacao():
    definicao = store.normalize_benchmark(
        {"name": "Teste", "match_on": "inventado", "stores": [{"name": "A", "url": "https://a.pt"}]}
    )
    assert definicao["match_on"] == "nome"


def test_atualizar_mantem_o_slug_do_indice():
    existente = store.normalize_benchmark(
        {"name": "Estudo inicial", "slug": "estudo-inicial", "stores": [{"name": "A", "url": "https://a.pt"}]}
    )
    atualizado = store.normalize_benchmark(
        {"name": "Nome novo", "slug": "outro-slug", "stores": [{"name": "A", "url": "https://a.pt"}]},
        existente,
    )
    # Mudar o slug apontaria para um índice que já não existe.
    assert atualizado["slug"] == "estudo-inicial"
    assert atualizado["name"] == "Nome novo"


def test_normalize_lofa_sem_id_deriva_do_dominio():
    definicao = store.normalize_benchmark(
        {"name": "Teste", "stores": [{"url": "https://www.loja-b.pt/categoria"}]}
    )
    loja = definicao["stores"][0]
    # Sem nome, o id vem do domínio e o nome fica a ser o próprio endereço.
    assert loja["id"] == "www-loja-b-pt"
    assert loja["name"] == "https://www.loja-b.pt/categoria"


def test_slugify_remove_acentos_e_pontuacao():
    assert store.slugify("Preços & Promoções (2026)") == "precos-promocoes-2026"


def test_indice_do_benchmark_por_slug():
    from api import elasticsearch_client as esc

    assert esc.benchmark_items_index("livros-demo") == "finance_bench_livros_demo"
    # O nome do índice perde acentos e pontuação (o slug lógico mantém-se).
    assert esc.benchmark_items_index("Acções/2026") == "finance_bench_ac_es_2026"


# ---------------------------------------------------------------------------
# Campos reconhecidos
# ---------------------------------------------------------------------------
def test_field_map_keys_inclui_o_essencial():
    for chave in ("price", "product_name", "url", "image", "description", "brand", "ean", "sku"):
        assert chave in store.FIELD_MAP_KEYS


# ---------------------------------------------------------------------------
# Sonda de produtos (análise determinística)
# ---------------------------------------------------------------------------
def test_preco_estruturado_ganha_ao_texto():
    """`data-*`/`itemprop` é a via fiável: o valor vem isolado e no formato certo."""
    from api import scraper_ai

    class _No:
        def __init__(self, atributos):
            self.attrib = atributos
            self.tag = "span"

    class _Item:
        def __init__(self, preco):
            self._preco = preco

        def css(self, _):
            return [_No({"itemprop": "price", "class": "preco", "content": self._preco})]

    encontrado = scraper_ai._preco_por_atributo([_Item("799.99"), _Item("1299.00")])
    assert encontrado is not None
    assert encontrado["sample"] == "799.99"
    assert encontrado["coverage"] == 1.0


def test_preco_por_atributo_ignora_valores_a_zero():
    from api import scraper_ai

    class _No:
        def __init__(self, valor):
            self.attrib = {"data-price": valor}
            self.tag = "span"

    class _Item:
        def __init__(self, valor):
            self._valor = valor

        def css(self, _):
            return [_No(self._valor)]

    assert scraper_ai._preco_por_atributo([_Item("0"), _Item("0.00")]) is None


def test_o_aviso_de_cookies_nao_e_confundido_com_a_lista_de_produtos():
    """O contentor do diálogo de cookies tinha 1086 «itens» e ganhava ao cartão."""
    from api import scraper_ai

    cookies = {
        "selector": "div.CybotCookiebotDialogBodyLevelButtonIABContainerCollapsed",
        "count": 1086,
        "link_ratio": 0.9,
        "text_ratio": 0.9,
        "title_ratio": 0.9,
        "image_ratio": 0.0,
        "price_ratio": 0.0,
    }
    produtos = {
        "selector": "article.product-card",
        "count": 48,
        "link_ratio": 1.0,
        "text_ratio": 1.0,
        "title_ratio": 1.0,
        "image_ratio": 1.0,
        "price_ratio": 1.0,
    }
    assert scraper_ai._product_score(produtos) > scraper_ai._product_score(cookies)
    assert scraper_ai._chrome_penalty(cookies["selector"]) < 1.0


def test_robots_da_sonda_pede_url_absoluto():
    resultado = servico.robots_permite("/sem-dominio")
    assert resultado["permitido"] is None


def test_seletor_do_no_le_o_atributo_tag_do_scrapling():
    """O `Selector` do Scrapling expõe `tag` — ler `tagname` devolvia '' e calava tudo."""
    from api import scraper_ai

    class _No:
        def __init__(self, tag=None, tagname=None, classes="price__numbers"):
            self.tag = tag
            if tagname is not None:
                self.tagname = tagname
            self.attrib = {"class": classes} if classes else {}

    assert scraper_ai._selector_do_no(_No(tag="span")) == "span.price__numbers"
    # Tolerância ao nome antigo, para não voltar a falhar em silêncio.
    assert scraper_ai._selector_do_no(_No(tagname="span")) == "span.price__numbers"
    # Sem tag nenhuma não há seletor: quem chama salta o valor (e não rebenta).
    assert scraper_ai._selector_do_no(_No()) == ""
    assert scraper_ai._selector_do_no(_No(tag="span", classes="")) == "span"


def test_precos_partidos_em_filhos_sao_lidos_pelo_texto_do_elemento():
    """`€<span>799</span><sup>,99</sup>`: o `::text` dá `','`; o texto do elemento dá o preço."""
    from api import scraper_ai

    class _Filho:
        def get_all_text(self):
            return "799"

    class _Preco:
        tag = "span"

        def __init__(self):
            self.attrib = {"class": "price__numbers"}

        def css(self, seletor):
            if "::text" in seletor:
                return type("_Lista", (), {"getall": lambda _self: [","]})()
            return [_Filho()]

        def get_all_text(self):
            return "€ 799 , 99"

    class _Item:
        def css(self, _):
            return [_Preco()]

    valores = scraper_ai._valores_do_seletor(_Item(), "[class*='price__numbers']")
    assert valores == ["€ 799 , 99"]
    encontrado = scraper_ai._melhor_seletor_com_valor(
        [_Item(), _Item()], ("[class*='price__numbers']",), aceita=scraper_ai._parece_preco
    )
    assert encontrado is not None
    assert encontrado["sample"] == "€ 799 , 99"
    assert encontrado["coverage"] == 1.0


@pytest.mark.parametrize(
    "preco,moeda",
    [
        ("£51.77", "GBP"),
        ("€ 799 , 99", "EUR"),
        ("R$ 1.299,00", "BRL"),
        ("US$ 99.00", "USD"),
        ("", None),
    ],
)
def test_moeda_da_amostra_le_o_simbolo_do_preco(preco, moeda):
    """Sem isto, uma loja inglesa aparecia como «51,77 EUR» (certo com moeda errada)."""
    previsao = {"items": [{"data": {"preco": preco, "titulo": "X"}}]}
    assert servico._moeda_da_amostra(previsao) == moeda


# ---------------------------------------------------------------------------
# Configuração do módulo e catálogo de lojas
# ---------------------------------------------------------------------------
def test_configuracao_rejeita_fetcher_desconhecido():
    config = store._normalizar_configuracao({"fetcher": "telepatia"})
    assert config["fetcher"] == "dynamic"
    assert config["use_ai"] is True
    assert config["limite_por_loja"] == store.CONFIG_FIELDS["limite_por_loja"]


def test_configuracao_limita_numeros_extremos():
    config = store._normalizar_configuracao({"limite_por_loja": 999999, "pausa_segundos": -5})
    assert config["limite_por_loja"] == 5000
    assert config["pausa_segundos"] == 0


def test_configuracao_mantem_o_que_nao_foi_enviado():
    existente = store._normalizar_configuracao({"fetcher": "stealth", "moeda": "GBP"})
    atualizada = store._normalizar_configuracao({"use_ai": False}, existente)
    assert atualizada["fetcher"] == "stealth"
    assert atualizada["moeda"] == "GBP"
    assert atualizada["use_ai"] is False


def test_o_documento_de_configuracao_nao_e_um_estudo():
    """A configuração vive no mesmo índice: não pode aparecer na lista nem ser aberta."""
    from api import benchmarks_store as store_modulo

    assert store_modulo.CONFIG_SLUG == "__config__"
    # `obter` filtra o documento de configuração e a lista também.
    assert isinstance(store_modulo.obter(store_modulo.CONFIG_SLUG), type(None))


def test_catalogo_de_lojas_tem_estado_e_endereco():
    from api import benchmarks_lojas

    lojas = benchmarks_lojas.lojas()
    assert len(lojas) >= 5
    for loja in lojas:
        assert loja["url"].startswith("http")
        assert loja["fetcher"] in store.FETCHERS_VALIDOS
        assert loja["estado"] in ("ok", "sem_preco", "bloqueado")
    resumo = benchmarks_lojas.resumo()
    assert resumo["total"] == len(lojas)
    assert sum(resumo["por_estado"].values()) == len(lojas)


def test_loja_da_sonda_guarda_o_fetcher_no_scraper():
    """A sonda devolve o fetcher no topo: tem de acabar dentro do `scraper` da loja."""
    loja = store.normalize_store(
        {
            "name": "Loja de teste",
            "url": "https://exemplo.pt/c",
            "fetcher": "stealth",
            "scraper": {"list": {"selector": "article"}, "fields": [{"name": "titulo", "selector": "h3"}]},
        }
    )
    assert loja["scraper"]["fetcher"] == "stealth"


def test_analise_de_lojas_calcula_indice_de_preco(monkeypatch):
    """O índice de preço é 100 para a média: 90 é 10% mais barato."""
    monkeypatch.setattr(servico.store, "obter", lambda slug: {"slug": slug, "name": "Demo", "stores": []})
    monkeypatch.setattr(
        servico.esc,
        "benchmark_store_stats",
        lambda slug: [
            {"store_id": "barata", "ofertas": 10, "produtos": 10, "preco_medio": 90.0},
            {"store_id": "cara", "ofertas": 10, "produtos": 10, "preco_medio": 110.0},
        ],
    )
    monkeypatch.setattr(servico.esc, "benchmark_product_comparison", lambda *a, **k: {"items": [], "total": 0})
    resultado = servico.analise("demo")
    lojas = {linha["store_id"]: linha for linha in resultado["stores"]}
    assert lojas["barata"]["indice_preco"] == 90.0
    assert lojas["cara"]["indice_preco"] == 110.0
    assert resultado["kpis"]["avg_price"] == 100.0


# ---------------------------------------------------------------------------
# Recolha
# ---------------------------------------------------------------------------
def test_recolha_sem_limite_explicito_usa_o_da_configuracao(monkeypatch):
    """Sem `limite_por_loja` na chamada, a recolha tem de usar o limite configurado.

    Já rebentava aqui: o limite resolvido (`limite`) era usado só na mensagem e a
    leitura dos itens ia buscar o argumento em bruto (`None`), pelo que cada loja
    falhava com `int(None)` e o resumo saía com 0 ofertas.
    """
    benchmark = {
        "slug": "demo",
        "name": "Demo",
        "match_on": "nome",
        "currency": "EUR",
        "field_map": {},
        "stores": [{"id": "loja", "name": "Loja", "url": "https://loja.pt", "enabled": True}],
    }
    item = {
        "data": {"titulo": "Casaco", "preco": "49,90 €"},
        "summary": "Casaco",
        "source_id": "fonte",
        "run_id": "r1",
    }
    lidos: dict = {}

    def _read_run_items(run_id, source_id, *, limit=100, offset=0):
        lidos["limit"] = limit
        return {"run_id": run_id, "total": 1, "items": [item]}

    monkeypatch.setattr(servico.store, "obter", lambda slug: benchmark)
    monkeypatch.setattr(
        servico.store, "obter_configuracao", lambda: {"limite_por_loja": 200, "pausa_segundos": 0}
    )
    monkeypatch.setattr(servico.store, "marcar_recolha", lambda slug, resumo: None)
    monkeypatch.setattr(servico.esc, "ensure_benchmark_items_index", lambda slug: None)
    monkeypatch.setattr(servico.esc, "delete_benchmark_items", lambda slug, store_id="": None)
    monkeypatch.setattr(servico.esc, "index_benchmark_items", lambda slug, ofertas: {"indexed": len(ofertas)})
    monkeypatch.setattr(servico, "_fonte_da_loja", lambda b, l: "fonte")
    monkeypatch.setattr(
        servico.scraper_service,
        "execute_run_sync",
        lambda source_id, trigger="", user_id=None: {"run_id": "r1", "items_count": 1, "status": "completed"},
    )
    monkeypatch.setattr(servico.scraper_service, "read_run_items", _read_run_items)

    resumo = servico.recolher("demo")

    assert lidos["limit"] == 200
    assert resumo["offers"] == 1
    assert resumo["indexed"] == 1
    assert resumo["stores"][0]["status"] == "ok"
    assert resumo["errors"] == []


def test_recolha_usa_o_limite_explicito_quando_indicado(monkeypatch):
    """Um limite explícito continua a mandar sobre o da configuração."""
    benchmark = {
        "slug": "demo",
        "name": "Demo",
        "match_on": "nome",
        "currency": "EUR",
        "field_map": {},
        "stores": [{"id": "loja", "name": "Loja", "url": "https://loja.pt", "enabled": True}],
    }
    lidos: dict = {}

    def _read_run_items(run_id, source_id, *, limit=100, offset=0):
        lidos["limit"] = limit
        return {"run_id": run_id, "total": 0, "items": []}

    monkeypatch.setattr(servico.store, "obter", lambda slug: benchmark)
    monkeypatch.setattr(
        servico.store, "obter_configuracao", lambda: {"limite_por_loja": 200, "pausa_segundos": 0}
    )
    monkeypatch.setattr(servico.store, "marcar_recolha", lambda slug, resumo: None)
    monkeypatch.setattr(servico.esc, "ensure_benchmark_items_index", lambda slug: None)
    monkeypatch.setattr(servico.esc, "delete_benchmark_items", lambda slug, store_id="": None)
    monkeypatch.setattr(servico.esc, "index_benchmark_items", lambda slug, ofertas: {"indexed": 0})
    monkeypatch.setattr(servico, "_fonte_da_loja", lambda b, l: "fonte")
    monkeypatch.setattr(
        servico.scraper_service,
        "execute_run_sync",
        lambda source_id, trigger="", user_id=None: {"run_id": "r2", "items_count": 0, "status": "completed"},
    )
    monkeypatch.setattr(servico.scraper_service, "read_run_items", _read_run_items)

    servico.recolher("demo", limite_por_loja=42)

    assert lidos["limit"] == 42


# ---------------------------------------------------------------------------
# Tipo de peça
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "nome,categoria,esperado",
    [
        ("Camisola de malha canelada", "", "Camisolas"),
        ("Sweatshirt com capuz", "", "Camisolas"),
        ("T-shirt básica de algodão", "", "T-shirts"),
        ("Camisa de popeline", "", "Camisas"),
        ("Blusa fluida", "", "Camisas"),
        ("Jeans wide leg", "", "Jeans"),
        ("Calças de fato", "", "Calças"),
        ("Calções de ganga", "", "Calções"),
        ("Saia plissada", "", "Saias"),
        ("Vestido midi", "", "Vestidos"),
        ("Casaco de lã", "", "Casacos"),
        ("Blazer oversize", "", "Casacos"),
        ("Sapatilhas running", "", "Sapatilhas"),
        ("Botins de pele estilo cowboy", "", "Botas"),
        ("Sandálias de salto", "", "Sandálias"),
        ("Mala de ombro", "", "Acessórios"),
        ("Fato de banho", "", "Fatos de banho"),
        ("Soutien sem aros", "", "Roupa interior"),
        ("Pijama de flanela", "", "Pijamas"),
        ("Macacão de alças", "", "Macacões"),
        # Sem pistas no nome, a categoria decide; sem nenhuma, fica «Outros».
        ("Peça 250562", "Vestidos", "Vestidos"),
        ("Peça 250562", "", "Outros"),
    ],
)
def test_tipo_de_peca(nome, categoria, esperado):
    assert servico.tipo_de_peca(nome, categoria) == esperado


def test_oferta_guarda_o_tipo_de_peca():
    """O tipo de peça é calculado na normalização — é o que o resumo agrega."""
    oferta = servico.normalizar_oferta(
        {"data": {"titulo": "Camisola de gola alta", "preco": "39,99 €"}},
        loja={"id": "loja", "name": "Loja", "url": "https://loja.pt"},
        benchmark={"slug": "demo", "match_on": "nome", "currency": "EUR", "field_map": {}},
    )
    assert oferta["garment_type"] == "Camisolas"


# ---------------------------------------------------------------------------
# Publicação no CMS
# ---------------------------------------------------------------------------
@pytest.fixture()
def cms_isolado(tmp_path, monkeypatch):
    """CMS numa pasta temporária: nada é lido nem escrito em `data/`."""
    from api import cms_store, indexnow

    pasta = tmp_path / "cms"
    monkeypatch.setattr(cms_store, "CMS_DIR", pasta)
    monkeypatch.setattr(cms_store, "CMS_PATH", pasta / "cms.json")
    monkeypatch.setattr(cms_store, "MEDIA_DIR", pasta / "media")
    monkeypatch.setattr(cms_store, "_cache", None)
    monkeypatch.setattr(cms_store, "_cache_mtime", None)
    # Uma escrita no CMS dispara o anúncio em fundo; aqui não sai daqui.
    monkeypatch.setattr(indexnow, "anunciar_em_fundo", lambda motivo: None)
    return cms_store


def _estudo_para_publicar(slug: str) -> dict:
    """O mínimo que o `publicar` consome do `analise`."""
    return {
        "benchmark": {
            "slug": slug,
            "name": "Sapatilhas",
            "category": "Desporto",
            "currency": "EUR",
            "match_on": "ean",
        },
        "kpis": {
            "products": 3,
            "stores": 2,
            "offers": 5,
            "comparable_products": 2,
            "avg_spread_pct": 12.0,
            "potential_saving_eur": 10.0,
        },
        "opportunities": [],
        "stores": [],
    }


def test_publicar_ignora_pagina_do_cms_de_outra_instalacao(cms_isolado, monkeypatch):
    """O `cms_page_id` que veio de outra instalação não pode rebentar a publicação.

    As definições chegam à VM pelo índice do Elasticsearch, com o id da página
    do CMS do PC. Aí não existe página nenhuma com esse id: antes disto, o
    `save_item` levantava `KeyError` e o painel mostrava 500 ao publicar.
    """
    monkeypatch.setattr(servico, "analise", _estudo_para_publicar)
    monkeypatch.setattr(
        servico.store,
        "obter",
        lambda slug: {"slug": slug, "cms_page_id": "pag_do_pc_que_nao_existe_aqui"},
    )
    guardado = {}
    monkeypatch.setattr(servico.store, "marcar_publicacao", lambda slug, **kw: guardado.update(kw) or {"slug": slug})

    resultado = servico.publicar("sapatilhas-lojas", autor="teste")

    assert resultado["public"] is True
    assert resultado["page_id"] != "pag_do_pc_que_nao_existe_aqui"
    pagina = cms_isolado.get_item("pages", resultado["page_id"])
    assert pagina["path"] == "benchmarks/sapatilhas-lojas"
    assert pagina["status"] == "publicado"
    # O id da página desta instalação fica guardado na definição.
    assert guardado["page_id"] == resultado["page_id"]


def test_publicar_reaproveita_a_pagina_que_ja_existe(cms_isolado, monkeypatch):
    """Ao republicar não se cria uma segunda página para o mesmo estudo."""
    monkeypatch.setattr(servico, "analise", _estudo_para_publicar)
    definicao = {"slug": "sapatilhas-lojas", "cms_page_id": ""}
    monkeypatch.setattr(servico.store, "obter", lambda slug: definicao)
    monkeypatch.setattr(servico.store, "marcar_publicacao", lambda slug, **kw: {"slug": slug})

    primeira = servico.publicar("sapatilhas-lojas", autor="teste")
    definicao["cms_page_id"] = primeira["page_id"]
    segunda = servico.publicar("sapatilhas-lojas", autor="teste")

    assert segunda["page_id"] == primeira["page_id"]
    paginas = cms_isolado.list_items("pages", limit=500)["items"]
    assert len([p for p in paginas if p["path"] == "benchmarks/sapatilhas-lojas"]) == 1


def test_despublicar_com_pagina_de_outra_instalacao_nao_rebenta(cms_isolado, monkeypatch):
    """Sem a página, retira-se só a marca de público (antes dava 500)."""
    monkeypatch.setattr(
        servico.store,
        "obter",
        lambda slug: {"slug": slug, "cms_page_id": "pag_do_pc_que_nao_existe_aqui"},
    )
    guardado = {}
    monkeypatch.setattr(servico.store, "marcar_publicacao", lambda slug, **kw: guardado.update(kw) or {"slug": slug})

    resultado = servico.despublicar("sapatilhas-lojas", autor="teste")

    assert resultado["public"] is False
    assert guardado["page_id"] == ""
    assert guardado["publico"] is False

