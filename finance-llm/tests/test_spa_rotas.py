"""Rotas da interface: o que se indexa, o que sai com `noindex` e o que é 404.

Três garantias, todas com o mesmo objectivo — o Google só deve encontrar páginas
que existem e que valem a pena:

* **classificação** (`api/spa_routes.py`): páginas públicas com meta própria,
  rotas da aplicação (casca em JavaScript → `noindex`) e o resto (404);
* **sem divergência com o frontend**: o primeiro segmento de todas as rotas
  declaradas em `chat-ui/src/App.tsx` tem de estar em `SEGMENTOS_DA_APP`. Uma
  rota em falta aqui dava 404 ao recarregar a página — o teste é o que impede
  esse erro de passar;
* **sitemap e `ROTAS_INDEXAVEIS` são a mesma lista**: anunciar ao motor de busca
  uma rota que sai com `noindex` é dizer-lhe duas coisas contrárias.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import api.main as api_main  # noqa: E402
from api import openapi_meta  # noqa: E402
from api import spa_routes  # noqa: E402

APP_TSX = RAIZ / "chat-ui" / "src" / "App.tsx"
SITEMAP_APP = RAIZ / "chat-ui" / "public" / "sitemap-app.xml"
TEM_BUILD = (RAIZ / "chat-ui" / "dist" / "index.html").is_file()


def _caminhos_do_frontend() -> set[str]:
    """Caminhos declarados em `App.tsx` (literais e `template strings`)."""
    texto = APP_TSX.read_text(encoding="utf-8")
    literais = (
        re.findall(r'"(/[^"]*)"', texto)
        + re.findall(r"'(/[^']*)'", texto)
        + re.findall(r"`(/[^`]*)`", texto)
    )
    return {literal.split("${")[0].rstrip("/") or "/" for literal in literais}


def _segmentos_do_frontend() -> set[str]:
    return {caminho.split("/")[1] for caminho in _caminhos_do_frontend() if caminho != "/"}


def _locs_do_sitemap() -> list[str]:
    conteudo = SITEMAP_APP.read_text(encoding="utf-8")
    return [loc.split("sabemos.studio", 1)[1] or "/" for loc in re.findall(r"<loc>([^<]+)</loc>", conteudo)]


# ------------------------------------------------------------------ classificação
def test_home_e_paginas_de_entrada_sao_indexaveis() -> None:
    for caminho in ("/", "/benchmark", "/benchmark/portugal", "/contracts/search", "/administracao-central"):
        assert spa_routes.classificar(caminho) == spa_routes.INDEXAVEL, caminho


def test_rotas_da_aplicacao_nao_se_indexam() -> None:
    for caminho in ("/descoberta", "/tickers", "/tickers/EDP", "/admin/correio", "/chat", "/settings"):
        assert spa_routes.classificar(caminho) == spa_routes.APP, caminho


def test_caminho_dentro_de_area_conhecida_continua_a_ser_aplicacao() -> None:
    """A comparação é por primeiro segmento: um detalhe novo não pode dar 404."""
    assert spa_routes.classificar("/tickers/EDP/grafico") == spa_routes.APP
    assert spa_routes.classificar("/contracts/region/PT/1A") == spa_routes.APP


def test_endereco_que_nao_e_rota_nenhuma_e_desconhecido() -> None:
    for caminho in ("/rota-inexistente-9f3a", "/qualquer/coisa", "/benchmark-inexistente"):
        assert spa_routes.classificar(caminho) == spa_routes.DESCONHECIDA, caminho


def test_barra_final_nao_muda_a_classificacao() -> None:
    assert spa_routes.classificar("/benchmark/") == spa_routes.INDEXAVEL
    assert spa_routes.classificar("/descoberta/") == spa_routes.APP


# -------------------------------------------------------------- divergência com o frontend
def test_todas_as_rotas_do_frontend_estao_em_segmentos_da_app() -> None:
    em_falta = _segmentos_do_frontend() - spa_routes.SEGMENTOS_DA_APP
    assert not em_falta, f"rotas da interface fora de SEGMENTOS_DA_APP (dariam 404): {sorted(em_falta)}"


def test_segmentos_da_app_nao_tem_entradas_a_mais_do_que_o_necessario() -> None:
    """O contrário do teste anterior: uma entrada morta é uma rota que já não existe
    e que continua a responder 200 em vez de 404."""
    usadas = _segmentos_do_frontend() | {
        caminho.split("/")[1] for caminho in openapi_meta.SPA_PATHS if caminho.count("/") >= 1
    }
    a_mais = spa_routes.SEGMENTOS_DA_APP - usadas
    assert not a_mais, f"segmentos em SEGMENTOS_DA_APP que o frontend já não usa: {sorted(a_mais)}"


def test_segmentos_da_app_cobrem_as_rotas_documentadas() -> None:
    """A lista do OpenAPI (`SPA_PATHS`) é outra vista das mesmas rotas: se uma
    delas não estiver em `SEGMENTOS_DA_APP`, é sinal de que a lista ficou para trás."""
    em_falta = {caminho.split("/")[1] for caminho in openapi_meta.SPA_PATHS if caminho.count("/") >= 1} - spa_routes.SEGMENTOS_DA_APP
    assert not em_falta, f"rotas documentadas fora de SEGMENTOS_DA_APP: {sorted(em_falta)}"


# ------------------------------------------------------------------- meta e sitemap
def test_cada_rota_indexavel_tem_meta_propria_no_backend() -> None:
    """`ROTAS_INDEXAVEIS` e o mapa de SEO do `main.py` têm de dizer o mesmo —
    uma rota indexável sem meta própria sai com o título genérico da home."""
    generico = api_main._seo_meta_for_path("/")["title"]
    for caminho in sorted(spa_routes.ROTAS_INDEXAVEIS - {"/"}):
        assert api_main._seo_meta_for_path(caminho)["title"] != generico, caminho


def test_sitemap_da_aplicacao_e_exactamente_o_conjunto_indexavel() -> None:
    assert set(_locs_do_sitemap()) == set(spa_routes.ROTAS_INDEXAVEIS)


def test_rotas_indexaveis_existem_no_frontend() -> None:
    for caminho in sorted(spa_routes.ROTAS_INDEXAVEIS - {"/"}):
        assert caminho in _caminhos_do_frontend(), caminho


# ------------------------------------------------------------------- comportamento
def test_endereco_inexistente_responde_404_com_noindex() -> None:
    resposta = api_main.spa_not_found_response()
    assert resposta.status_code == 404
    assert b'name="robots" content="noindex' in resposta.body


@pytest.mark.skipif(not TEM_BUILD, reason="a SPA não está construída (`chat-ui/dist`)")
def test_endereco_inexistente_pelo_catch_all_responde_404() -> None:
    from fastapi.testclient import TestClient

    cliente = TestClient(api_main.app)
    resposta = cliente.get("/rota-inexistente-9f3a", headers={"Accept": "text/html"})
    assert resposta.status_code == 404


@pytest.mark.skipif(not TEM_BUILD, reason="a SPA não está construída (`chat-ui/dist`)")
def test_rota_publica_sai_com_meta_propria_e_sem_noindex() -> None:
    from fastapi.testclient import TestClient

    cliente = TestClient(api_main.app)
    resposta = cliente.get("/benchmark/portugal", headers={"Accept": "text/html"})
    assert resposta.status_code == 200
    assert "Benchmark Portugal" in resposta.text
    assert 'name="robots" content="index, follow"' in resposta.text
    assert '<link rel="canonical" href="https://sabemos.studio/benchmark/portugal" />' in resposta.text


@pytest.mark.skipif(not TEM_BUILD, reason="a SPA não está construída (`chat-ui/dist`)")
def test_rota_da_aplicacao_sai_com_noindex() -> None:
    from fastapi.testclient import TestClient

    cliente = TestClient(api_main.app)
    resposta = cliente.get("/descoberta", headers={"Accept": "text/html"})
    assert resposta.status_code == 200
    assert 'name="robots" content="noindex, follow"' in resposta.text
