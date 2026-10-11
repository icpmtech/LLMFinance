"""Testes do módulo de **benchmarks de produtos** (`api/benchmarks_*`).

Cobrem as partes que decidem resultados e que já falharam uma vez:

- leitura de preços em formatos portugueses/internacionais;
- normalização de uma oferta (chave de produto, desconto, stock);
- `field_map` a sobrepor-se à deteção por nome de campo;
- normalização/validação da definição (slug, lojas obrigatórias, chave de comparação);
- atualização da definição sem perder o slug (o slug é o id do índice).

Não tocam no Elasticsearch nem no scraper: testam as funções puras.
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
