"""Testes do captcha nos formulários públicos da vitrine.

A vitrine não funciona sem JavaScript (o carrinho vive no browser) e foi por
isso que o desafio da loja se liga por `GET /loja/desafio`: a página pede-o,
resolve-o e devolve `captcha` + `captcha_token` no corpo do pedido. O que aqui
se fixa é que, sem essa resposta, **nada é criado** — encomenda, avaliação ou
registo de novidades —, e que a página traz o lugar do desafio e o pedido dele.
"""

from __future__ import annotations

from typing import Any, Dict, Iterator, List

import pytest
from fastapi.testclient import TestClient

from api import cms_store as cms
from api import shop_store as store

# O leitor da pergunta e o compasso de espera vêm do teste do módulo: são a
# mesma coisa vista do outro lado (aqui as perguntas chegam por HTTP).
from test_captcha import resolver, sem_espera  # noqa: F401 - `sem_espera` é uma fixture


@pytest.fixture()
def loja(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """Loja e CMS isolados em `tmp_path` (sem tocar em `data/`)."""
    monkeypatch.setattr(store, "SHOP_DIR", tmp_path / "shop")
    monkeypatch.setattr(store, "SHOP_PATH", tmp_path / "shop" / "shop.json")
    monkeypatch.setattr(store, "FILES_DIR", tmp_path / "shop" / "files")
    monkeypatch.setattr(store, "_cache", None)
    monkeypatch.setattr(store, "_cache_mtime", None)

    armazem = tmp_path / "cms"
    monkeypatch.setattr(cms, "CMS_DIR", armazem)
    monkeypatch.setattr(cms, "CMS_PATH", armazem / "cms.json")
    monkeypatch.setattr(cms, "MEDIA_DIR", armazem / "media")
    monkeypatch.setattr(cms, "_cache", None)
    monkeypatch.setattr(cms, "_cache_mtime", None)
    store.reset_seed()
    yield store


def _cliente() -> TestClient:
    from api import main as api_main

    return TestClient(api_main.app, base_url="http://prova")


def _resolvido(loja: Any, cliente: TestClient) -> Dict[str, str]:
    """Um desafio novo da loja, já respondido como uma pessoa o responderia."""
    dados = cliente.get("/loja/desafio").json()
    return {dados["campo"]: resolver(dados["pergunta"]), dados["testemunho"]: dados["token"]}


def _digital(loja: Any) -> Dict[str, Any]:
    return next(item for item in loja.list_items("products")["items"] if item.get("type") == "digital")


# ------------------------------------------------------------------ o desafio
def test_desafio_da_vitrine_explica_se_e_nao_se_guarda(sem_espera: None) -> None:
    resposta = _cliente().get("/loja/desafio")

    assert resposta.status_code == 200
    assert resposta.headers["cache-control"] == "no-store, must-revalidate"
    dados = resposta.json()
    assert dados["pergunta"].startswith("Quanto dá ")
    assert dados["campo"] == "captcha" and dados["testemunho"] == "captcha_token"
    assert dados["token"] and "." in dados["token"]
    # A pergunta é texto legível — não há imagem nem widget de terceiros.
    assert resolver(dados["pergunta"]).isdigit()


# ------------------------------------------------------------------ novidades
def test_novidades_sem_desafio_nao_registam_nada(loja: Any, sem_espera: None) -> None:
    cliente = _cliente()
    before = len(loja.list_items("customers")["items"])

    resposta = cliente.post("/loja/newsletter", json={"email": "ana@exemplo.pt"})

    assert resposta.status_code == 422
    assert "desafio" in resposta.json()["detail"].lower()
    assert len(loja.list_items("customers")["items"]) == before


def test_novidades_com_desafio_entram(loja: Any, sem_espera: None) -> None:
    cliente = _cliente()
    before = len(loja.list_items("customers")["items"])

    resposta = cliente.post(
        "/loja/newsletter",
        json={"email": "ana.novidades@exemplo.pt", **_resolvido(loja, cliente)},
    )

    assert resposta.status_code == 200 and resposta.json()["subscribed"] is True
    clientes = loja.list_items("customers")["items"]
    assert len(clientes) == before + 1
    novo = next(item for item in clientes if item["email"] == "ana.novidades@exemplo.pt")
    assert novo["marketing"] is True
    # O desafio fica no pedido, não no registo.
    assert "captcha" not in novo and "captcha_token" not in novo


# ---------------------------------------------------------------- avaliações
def test_avaliacao_sem_desafio_nao_entra(loja: Any, sem_espera: None) -> None:
    cliente = _cliente()
    produto = _digital(loja)
    before = len(loja.list_items("reviews")["items"])

    resposta = cliente.post(
        "/loja/avaliacoes",
        json={"product_id": produto["id"], "customer_name": "Ana", "rating": 5, "title": "Boa", "body": "Muito boa."},
    )

    assert resposta.status_code == 422
    assert len(loja.list_items("reviews")["items"]) == before


def test_avaliacao_com_desafio_entra_pendente(loja: Any, sem_espera: None) -> None:
    cliente = _cliente()
    produto = _digital(loja)
    before = len(loja.list_items("reviews")["items"])

    resposta = cliente.post(
        "/loja/avaliacoes",
        json={
            "product_id": produto["id"],
            "customer_name": "Ana Verificação",
            "rating": 5,
            "title": "Boa",
            "body": "Muito boa.",
            **_resolvido(loja, cliente),
        },
    )

    assert resposta.status_code == 200 and resposta.json()["saved"] is True
    avaliacoes = loja.list_items("reviews")["items"]
    assert len(avaliacoes) == before + 1
    nova = next(item for item in avaliacoes if item["customer_name"] == "Ana Verificação")
    assert nova["status"] == "pendente"


# ------------------------------------------------------------------ encomenda
def test_encomenda_sem_desafio_nao_e_criada(loja: Any, sem_espera: None) -> None:
    cliente = _cliente()
    produto = _digital(loja)
    before = len(loja.list_items("orders")["items"])

    resposta = cliente.post(
        "/loja/encomendas",
        json={"items": [{"product_id": produto["id"], "quantity": 1}], "customer": {"name": "Ana", "email": "ana@exemplo.pt"}},
    )

    assert resposta.status_code == 422
    assert len(loja.list_items("orders")["items"]) == before


def test_encomenda_com_desafio_e_criada(loja: Any, sem_espera: None) -> None:
    cliente = _cliente()
    produto = _digital(loja)
    before = len(loja.list_items("orders")["items"])

    resposta = cliente.post(
        "/loja/encomendas",
        json={
            "items": [{"product_id": produto["id"], "quantity": 1}],
            "customer": {"name": "Ana Verificação", "email": "ana.encomenda@exemplo.pt"},
            **_resolvido(loja, cliente),
        },
    )

    assert resposta.status_code == 200
    encomenda = resposta.json()["order"]
    assert encomenda["number"].startswith("EN") and encomenda["totals"]["total"] > 0
    assert len(loja.list_items("orders")["items"]) == before + 1


# -------------------------------------------------------------------- a página
def test_formularios_da_vitrine_trazem_o_lugar_do_desafio(loja: Any, sem_espera: None) -> None:
    """O servidor deixa o espaço e o JavaScript pede-o — sem desafio não há resposta."""
    cliente = _cliente()
    produto = _digital(loja)

    carrinho = cliente.get("/loja/carrinho")
    ficha = cliente.get(f"/loja/produto/{produto['slug']}")

    for pagina in (carrinho, ficha):
        assert pagina.status_code == 200
        assert 'data-captcha' in pagina.text
        assert '"/loja/desafio"' in pagina.text
    # O bloco nasce escondido: quem não tem JavaScript não vê um campo vazio.
    assert 'class="wide captcha" data-captcha hidden' in carrinho.text
