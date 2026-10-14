"""Loja: o Relatório de Benchmark é gerado e entregue na própria encomenda.

O «Relatório de Benchmark — Portugal, Espanha e França» (14,90 €) é um PDF que
ninguém produz à mão: o que se testa aqui é o percurso todo — o produto existe na
vitrine, a encomenda é paga, o PDF fica anexado à encomenda, o comprador
descarrega-o no recibo (número + email) e uma segunda confirmação de pagamento
não duplica o ficheiro. O bug que isto previne é o cliente pagar 14,90 € e ficar
sem relatório nenhum, ou o PDF de um relatório sair para quem não é o comprador.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List

import pytest
from fastapi import HTTPException

from api import benchmark_report
from api import shop_render as render
from api import shop_routes
from api import shop_store as store

SLUG = "relatorio-benchmark-portugal-espanha-franca"
EMAIL = "cliente@exemplo.pt"


@pytest.fixture()
def loja(tmp_path, monkeypatch):
    """Loja isolada em `tmp_path` (sem tocar em `data/`)."""
    monkeypatch.setattr(store, "SHOP_DIR", tmp_path / "shop")
    monkeypatch.setattr(store, "SHOP_PATH", tmp_path / "shop" / "shop.json")
    monkeypatch.setattr(store, "FILES_DIR", tmp_path / "shop" / "files")
    monkeypatch.setattr(store, "_cache", None)
    monkeypatch.setattr(store, "_cache_mtime", None)
    yield store


@pytest.fixture()
def pdf(monkeypatch) -> List[Dict[str, Any]]:
    """Troca o gerador real (que consulta o Elasticsearch) por um PDF de prova."""
    chamadas: List[Dict[str, Any]] = []

    def falso(params: Dict[str, Any], *, reference: str = "", requester: str = "", es: Any = None):
        chamadas.append({"params": params, "reference": reference, "requester": requester})
        return (f"benchmark-{reference or 'loja'}.pdf", b"%PDF-1.4 benchmark", "application/pdf")

    monkeypatch.setattr(benchmark_report, "render", falso)
    return chamadas


def _comprar(email: str = EMAIL) -> Dict[str, Any]:
    produto = store.product_by_slug(SLUG)
    return store.checkout(
        {
            "items": [{"product_id": produto["id"], "quantity": 1}],
            "customer": {"name": "Cliente Exemplo", "email": email},
            "shipping_method_id": store.digital_shipping_method()["id"],
        }
    )


def _pagar(encomenda: Dict[str, Any]) -> Dict[str, Any]:
    return store.register_payment(encomenda["id"], {"method": "mbway", "status": "pago"})


# ------------------------------------------------------------------- catálogo
def test_produto_do_benchmark_publicado_na_loja(loja):
    """O produto anunciado na vitrine, a 14,90 €, ligado ao gerador do relatório."""
    produto = store.product_by_slug(SLUG)
    assert produto is not None
    assert produto["status"] == "publicado"
    assert produto["type"] == "digital"
    assert produto["price"] == 14.9
    assert produto["auto_report"] == "benchmark"
    # Um produto publicado e digital aparece na vitrine e não pede portes.
    assert SLUG in {item["slug"] for item in store.public_products(sort="destaque")}


def test_so_relatorios_conhecidos_sao_automaticos(loja):
    """`auto_report` vale o que estiver no registo; o resto é um produto normal."""
    doc = store.save_item(
        "products",
        {"name": "Relatório inventado", "price": 9.9, "auto_report": "inventado"},
        author="prova",
    )
    assert doc["auto_report"] == ""
    assert store.has_auto_report({"items": [{"product_id": doc["id"]}]}) is False


# ------------------------------------------------------------------ geração
def test_pagamento_gera_o_pdf_da_encomenda(loja, pdf):
    """Pagar a encomenda produz o PDF, grava-o em disco e anexa-o à encomenda."""
    encomenda = _comprar()
    assert encomenda["files"] == []
    # Ainda não pago: nada foi gerado.
    assert pdf == []

    paga = _pagar(encomenda)
    assert paga["payment"]["status"] == "pago"
    assert len(paga["files"]) == 1
    ficheiro = paga["files"][0]
    assert ficheiro["name"].endswith(".pdf")
    assert ficheiro["mime"] == "application/pdf"
    assert ficheiro["label"].startswith("Relatório de Benchmark")
    assert ficheiro["size"] == len(b"%PDF-1.4 benchmark")

    # O relatório é o dos três países, identificado pela encomenda e pelo comprador.
    assert len(pdf) == 1
    assert pdf[0]["params"]["mode"] == "mercado"
    assert pdf[0]["params"]["countries"] == ["pt", "es", "fr"]
    assert pdf[0]["reference"] == encomenda["number"]
    assert pdf[0]["requester"] == "Cliente Exemplo"

    # O ficheiro existe no disco e pode ser lido pelo id.
    caminho, ficha = store.order_file_of(encomenda["id"], ficheiro["id"])
    assert caminho.read_bytes() == b"%PDF-1.4 benchmark"
    assert ficha["id"] == ficheiro["id"]


def test_confirmar_o_pagamento_duas_vezes_nao_duplica(loja, pdf):
    """Repetir o pagamento (ou avançar o estado) não volta a gerar o mesmo PDF."""
    encomenda = _comprar()
    _pagar(encomenda)
    store.register_payment(encomenda["id"], {"method": "mbway", "status": "pago"})
    store.set_order_status(encomenda["id"], "em_preparacao")
    final = store.get_item("orders", encomenda["id"])
    assert len(final["files"]) == 1
    assert len(pdf) == 1


def test_estado_pago_gera_o_relatorio(loja, pdf):
    """Marcar a encomenda como paga basta (há quem registe só o estado)."""
    encomenda = _comprar()
    atualizada = store.set_order_status(encomenda["id"], "pago")
    assert len(atualizada["files"]) == 1
    assert len(pdf) == 1


def test_geracao_falhada_fica_a_nota_e_recupera_depois(loja, monkeypatch):
    """Sem Elasticsearch o pedido não fica preso: gera-se mais tarde, sem novo pagamento."""
    def rebenta(*_args, **_kwargs):
        raise RuntimeError("Elasticsearch indisponível")

    monkeypatch.setattr(benchmark_report, "render", rebenta)
    encomenda = _comprar()
    paga = _pagar(encomenda)
    assert paga["files"] == []
    # A nota é interna: existe para o backoffice, não para o comprador.
    interna = store.get_item("orders", encomenda["id"])
    assert "Elasticsearch indisponível" in interna["internal_notes"]
    assert "internal_notes" not in store.public_order_view(interna)
    # E fica gravada em disco, não só na memória do processo.
    store._cache = None
    assert "Elasticsearch indisponível" in store.get_item("orders", encomenda["id"])["internal_notes"]

    def funciona(params, *, reference="", requester="", es=None):
        return (f"benchmark-{reference}.pdf", b"%PDF-1.4 benchmark", "application/pdf")

    monkeypatch.setattr(benchmark_report, "render", funciona)
    gerados = store.gerar_relatorios_pendentes()
    assert len(gerados) == 1
    assert len(store.get_item("orders", encomenda["id"])["files"]) == 1


# ------------------------------------------------------------------- entrega
def test_recibo_mostra_o_relatorio(loja, pdf):
    """O recibo do comprador traz o link de download do relatório."""
    encomenda = _comprar()
    paga = _pagar(encomenda)
    ficheiro = paga["files"][0]
    html = render.render_order(store.get_item("orders", encomenda["id"]))
    assert "Os seus relatórios" in html
    assert ficheiro["name"] in html
    assert f"/loja/encomenda/{encomenda['number']}/ficheiros/{ficheiro['id']}?email=cliente%40exemplo.pt" in html


def test_download_exige_o_email_da_compra(loja, pdf):
    """O PDF sai para o número da encomenda **e** o email usado na compra."""
    encomenda = _comprar()
    paga = _pagar(encomenda)
    ficheiro = paga["files"][0]

    with pytest.raises(HTTPException) as erro:
        shop_routes.loja_order_file(encomenda["number"], ficheiro["id"], email="outro@exemplo.pt")
    assert erro.value.status_code == 404
    with pytest.raises(HTTPException) as erro:
        shop_routes.loja_order_file(encomenda["number"], ficheiro["id"], email="")
    assert erro.value.status_code == 404

    resposta = shop_routes.loja_order_file(encomenda["number"], ficheiro["id"], email=EMAIL)
    assert resposta.status_code == 200
    assert resposta.media_type == "application/pdf"
    assert resposta.body == b"%PDF-1.4 benchmark"
    assert ficheiro["name"] in resposta.headers["content-disposition"]


def test_ficheiro_de_outra_encomenda_nao_sai(loja, pdf):
    """O link de uma encomenda não serve para descarregar o de outra."""
    primeira = _pagar(_comprar())
    segunda = _pagar(_comprar(email="outro@exemplo.pt"))
    with pytest.raises(HTTPException) as erro:
        shop_routes.loja_order_file(
            segunda["number"],
            primeira["files"][0]["id"],
            email="outro@exemplo.pt",
        )
    assert erro.value.status_code == 404


# ------------------------------------------------------------------ backoffice
def test_backoffice_repete_a_geracao(loja, pdf):
    """A rota do backoffice (re)gera o que falta e exige sessão."""
    sessao = SimpleNamespace(user=SimpleNamespace(email="gestor@exemplo.pt"))
    encomenda = _comprar()
    _pagar(encomenda)

    with pytest.raises(HTTPException) as erro:
        shop_routes.shop_order_reports(encomenda["id"], session=None)
    assert erro.value.status_code == 401

    repetido = shop_routes.shop_order_reports(encomenda["id"], session=sessao)
    assert repetido["generated"] == 0
    assert len(repetido["order"]["files"]) == 1
    assert len(pdf) == 1


def test_backoffice_recupera_a_encomenda_paga_sem_ficheiro(loja, monkeypatch):
    """Se o PDF falhou no pagamento, o backoffice gera-o pela rota, sem novo pagamento."""
    def rebenta(*_args, **_kwargs):
        raise RuntimeError("Elasticsearch indisponível")

    monkeypatch.setattr(benchmark_report, "render", rebenta)
    encomenda = _comprar()
    _pagar(encomenda)
    assert store.get_item("orders", encomenda["id"])["files"] == []

    monkeypatch.setattr(
        benchmark_report,
        "render",
        lambda params, *, reference="", requester="", es=None: (
            f"benchmark-{reference}.pdf",
            b"%PDF-1.4 benchmark",
            "application/pdf",
        ),
    )
    sessao = SimpleNamespace(user=SimpleNamespace(email="gestor@exemplo.pt"))
    resposta = shop_routes.shop_order_reports(encomenda["id"], session=sessao)
    assert resposta["generated"] == 1
    assert len(resposta["order"]["files"]) == 1
