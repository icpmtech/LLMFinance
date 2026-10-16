"""Testes das páginas de sistema do site público.

São as páginas que aparecem quando algo corre mal: o endereço não existe (404),
o serviço falhou (500) e não há rede (`/site/offline`, mostrada pelo service
worker). Todas dizem o mesmo em três tempos — o que aconteceu, o que se pode
fazer agora e o que é a plataforma — com uma nota de humor seco e uma ilustração
embutida no HTML (sem pedido externo, para funcionarem sem rede).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from api import cms_render as cms_render
from api import cms_store as store


@pytest.fixture()
def cms_limpo(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> Any:
    """Um CMS vazio em disco, para os testes não tocarem no CMS real."""
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


DESTINOS = ("/site/solucoes", "/site/relatorios-gratuitos", "/site/fontes", "/site/blog", "/site/contactos")


def _pedido(caminho: str, accept: str) -> Request:
    """Pedido mínimo para exercitar o tratador de erros sem levantar o servidor."""
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": caminho,
            "raw_path": caminho.encode(),
            "query_string": b"",
            "root_path": "",
            "headers": [(b"accept", accept.encode()), (b"host", b"prova")],
            "server": ("prova", 80),
            "client": ("127.0.0.1", 1234),
        }
    )


# ------------------------------------------------------------------ 404
def test_endereco_inexistente_tem_plataforma_humor_e_ilustracao(cms_limpo: Any) -> None:
    html = cms_render.render_not_found()

    assert "Erro 404" in html
    assert "<h1>Este endereço não consta do cadastro</h1>" in html
    # Humor com o vocabulário da casa, sem troçar de quem chegou aqui.
    assert 'class="sistema-nota"' in html
    assert "aditivos" in html and "links se perdem" in html
    # Ilustração informativa embutida: sem `src`, sem nome de ficheiro no HTML.
    assert 'class="sistema-imagem"' in html
    assert '<svg xmlns="http://www.w3.org/2000/svg"' in html
    assert 'aria-label="Uma ficha de registo aberta' in html
    assert "ilustracao-pagina-nao-encontrada.svg" not in html
    # Plataforma e destinos úteis.
    assert "<h2>O que é o Sabemos Studio</h2>" in html
    for destino in DESTINOS:
        assert f'href="{destino}"' in html
    # Pesquisa (o caminho alternativo a escrever o endereço) e trilha de navegação.
    assert 'action="/site/pesquisa"' in html and 'name="q"' in html
    assert 'aria-label="Caminho"' in html and 'aria-current="page">Página não encontrada' in html
    assert '<meta name="robots" content="noindex, nofollow">' in html


# ------------------------------------------------------------------ 500
def test_erro_do_servico_diz_que_a_falha_e_nossa(cms_limpo: Any) -> None:
    html = cms_render.render_erro_interno()

    assert "Erro 500" in html
    assert "<h1>Falhou do nosso lado, não do seu</h1>" in html
    assert "Os números continuam guardados" in html
    assert 'aria-label="Um painel de indicadores com uma peça solta' in html
    assert "ilustracao-erro-interno.svg" not in html
    for destino in DESTINOS:
        assert f'href="{destino}"' in html


# ------------------------------------------------------------------ sem ligação
def test_pagina_sem_ligacao_nao_precisa_de_rede(cms_limpo: Any) -> None:
    html = cms_render.render_offline()

    assert "Sem ligação" in html
    assert "continuam a abrir" in html
    # Nada que obrigue a um pedido de rede: a ilustração vai no HTML da página.
    assert 'class="sistema-imagem"' in html
    assert '<svg xmlns="http://www.w3.org/2000/svg"' in html
    assert 'aria-label="Ligação interrompida' in html
    assert "ilustracao-sem-ligacao.svg" not in html
    assert 'href="/site/relatorios-gratuitos"' in html
    assert 'aria-current="page">Sem ligação' in html


# ------------------------------------------------------------------ rotas
def test_rota_de_endereco_inexistente_responde_404_com_a_pagina(cms_limpo: Any) -> None:
    from api import main as api_main

    cliente = TestClient(api_main.app, base_url="http://prova")
    resposta = cliente.get("/site/nao-existe-mesmo", headers={"accept": "text/html"})

    assert resposta.status_code == 404
    assert "não consta do cadastro" in resposta.text
    assert "O que é o Sabemos Studio" in resposta.text


def test_rota_offline_responde_com_a_pagina(cms_limpo: Any) -> None:
    from api import main as api_main

    cliente = TestClient(api_main.app, base_url="http://prova")
    resposta = cliente.get("/site/offline")

    assert resposta.status_code == 200
    assert "Sem ligação" in resposta.text
    assert resposta.headers["cache-control"] == "no-cache"


def test_falha_no_site_responde_com_a_pagina_de_erro(cms_limpo: Any) -> None:
    """Uma exceção a servir uma página do site dá a página, não o texto do Starlette."""
    from api import main as api_main

    def rebenta(*_args: Any, **_kwargs: Any) -> str:
        raise RuntimeError("falha propositada")

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(cms_render, "render_not_found", rebenta)
    try:
        cliente = TestClient(api_main.app, base_url="http://prova", raise_server_exceptions=False)
        resposta = cliente.get("/site/nao-existe-mesmo", headers={"accept": "text/html"})
    finally:
        monkeypatch.undo()

    assert resposta.status_code == 500
    assert "Falhou do nosso lado" in resposta.text
    assert resposta.headers["cache-control"] == "no-store"


def test_falha_na_api_responde_json(cms_limpo: Any) -> None:
    """Fora do site, o tratador mantém a resposta JSON (a SPA depende dela)."""
    from api import main as api_main

    resposta = asyncio.run(
        api_main._erro_nao_tratado(_pedido("/api/contratos", "application/json"), RuntimeError("x"))  # noqa: SLF001 - comportamento a fixar
    )

    assert resposta.status_code == 500
    assert json.loads(resposta.body)["detail"] == "Erro interno do servidor."


def test_falha_no_site_com_pedido_de_json_mantem_json(cms_limpo: Any) -> None:
    """Um `fetch` a /site/... (sem `Accept: text/html`) não recebe uma página."""
    from api import main as api_main

    resposta = asyncio.run(
        api_main._erro_nao_tratado(_pedido("/site/blog", "*/*"), RuntimeError("x"))  # noqa: SLF001 - comportamento a fixar
    )

    assert resposta.status_code == 500
    assert resposta.headers["content-type"].startswith("application/json")
