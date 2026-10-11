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
    for chave in ("price", "product_name", "ean", "url"):
        assert chave in store.FIELD_MAP_KEYS


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
