"""A folha de estilo do site: compilada pelo Tailwind, servida como ficheiro.

O que se prova aqui:

* a rota `/site/site.css` serve a folha compilada, com tipo, cache e `ETag` (e
  responde `304` quando o browser já tem a versão atual);
* as páginas públicas ligam a folha e guardam **em linha** só as variáveis do
  tema (que vêm das definições do CMS) e o CSS próprio da página;
* as regras que o site contava receber do browser e o preflight do Tailwind
  apaga — peso dos títulos, marcadores e indentação das listas — voltam a estar
  lá (ver `site-css/src/site.css`);
* nenhuma classe do site tem o nome de um utilitário do Tailwind: os utilitários
  vivem na camada `utilities`, que ganha à camada `components`, e uma classe com
  o mesmo nome (`grid`, `block`, `flex`) ficava silenciosamente trocada;
* o service worker guarda a folha, para as páginas sem rede continuarem vestidas.

O CSS é lido do ficheiro que o browser descarrega: não há aqui CSS escrito à mão
que possa divergir do que é servido.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict

import pytest
from fastapi.testclient import TestClient

from api import cms_render as render
from api import cms_store as store

CSS_PATH = store.SITE_ASSETS_DIR / "site.css"


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


@pytest.fixture(scope="module")
def css() -> str:
    """A folha compilada, como o browser a lê: sem os espaços que não contam."""
    assert CSS_PATH.is_file(), f"falta {CSS_PATH} — compilar com `cd site-css && npm run build`"
    texto = re.sub(r"\s+", " ", CSS_PATH.read_text(encoding="utf-8"))
    return re.sub(r"\s*([{};:,>~+])\s*", r"\1", texto)


def _cliente() -> TestClient:
    from api import main as api_main

    return TestClient(api_main.app, base_url="http://prova")


def _camada(texto: str, nome: str) -> str:
    """O conteúdo de um `@layer nome{…}`, contando as chavetas por dentro."""
    inicio = texto.find(f"@layer {nome}{{")
    if inicio < 0:
        return ""
    i = inicio + len(f"@layer {nome}{{")
    profundidade = 1
    while i < len(texto) and profundidade:
        if texto[i] == "{":
            profundidade += 1
        elif texto[i] == "}":
            profundidade -= 1
        i += 1
    return texto[inicio:i]


def _classes(texto: str) -> set[str]:
    return set(re.findall(r"(?<![\w-])\.([A-Za-z_][-\w]*)", texto))


# ------------------------------------------------------------------- rota
def test_rota_serve_a_folha_com_tipo_cache_e_etag(cms_limpo: Any) -> None:
    resposta = _cliente().get("/site/site.css")
    assert resposta.status_code == 200
    assert resposta.headers["content-type"].startswith("text/css")
    assert "public, max-age=600" in resposta.headers["cache-control"]
    assert "must-revalidate" in resposta.headers["cache-control"]
    etiqueta = resposta.headers["etag"]
    assert etiqueta and len(etiqueta) > 8
    # O corpo é a folha compilada: traz o preflight do Tailwind e as regras do site.
    assert "box-sizing:border-box" in resposta.text
    assert ".menu-botao" in resposta.text

    # Com o ETag atual, o browser leva um 304 sem corpo (não volta a descarregar).
    repetido = _cliente().get("/site/site.css", headers={"If-None-Match": etiqueta})
    assert repetido.status_code == 304
    assert not repetido.content

    # Sem o ETag (ou com outro), vem a folha inteira outra vez.
    renovado = _cliente().get("/site/site.css", headers={"If-None-Match": '"outro"'})
    assert renovado.status_code == 200
    assert renovado.text == resposta.text


def test_servico_sem_folha_compilada_responde_404(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Sem ficheiro compilado (checkout sem `npm run build`) a rota diz que falta."""
    monkeypatch.setattr(store, "SITE_ASSETS_DIR", tmp_path)
    resposta = _cliente().get("/site/site.css")
    assert resposta.status_code == 404


# ---------------------------------------------------------------- paginas
def test_pagina_liga_a_folha_e_guarda_so_o_tema_em_linha(cms_limpo: Any) -> None:
    """O que fica em linha é o tema (do CMS); o resto é ficheiro."""
    html = render.render_index(settings=store.get_settings())
    assert '<link rel="stylesheet" href="/site/site.css">' in html

    estilo = re.search(r"<style>(.*?)</style>", html, re.S).group(1)
    assert estilo.startswith(":root{--bg:")
    assert "--accent:" in estilo and "--radius:" in estilo
    # Nada das regras do site fica no HTML: era o que fazia cada página 36 KB maior.
    assert ".menu-botao" not in estilo
    assert ".post-card" not in estilo
    assert len(estilo) < 600


def test_o_tema_do_cms_chega_as_cores_da_folha(cms_limpo: Any) -> None:
    """As definições do CMS entram pelas variáveis que a folha usa."""
    settings: Dict[str, Any] = {**store.get_settings(), "accent": "#123456", "radius": 22}
    html = render.render_index(settings=settings)
    assert "--accent:#123456" in html
    assert "--radius:22px" in html
    assert "var(--accent)" in CSS_PATH.read_text(encoding="utf-8")


# --------------------------------------------------- compensacoes e colisoes
def test_compensacoes_do_preflight_do_tailwind(css: str) -> None:
    """O que o browser dava e o preflight tirava: títulos e listas."""
    assert "h1,h2,h3,h4,h5,h6{font-weight:700}" in css
    assert "h4{font-size:1rem}" in css
    assert "ul,ol{margin:1em 0;padding-left:40px;list-style-type:disc}" in css
    assert "ol{list-style-type:decimal}" in css


def test_nenhuma_classe_do_site_tem_nome_de_utilitario(css: str) -> None:
    """Os utilitários ganham à camada do site: nomes iguais trocavam o desenho."""
    componentes = _classes(_camada(css, "components"))
    utilitarios = _classes(_camada(css, "utilities"))
    assert componentes, "sem camada `components`: a folha não é a do site"
    colisoes = sorted(componentes & utilitarios)
    assert not colisoes, f"classes do site com nome de utilitário do Tailwind: {colisoes}"


# ------------------------------------------------------------ service worker
def test_service_worker_guarda_a_folha(cms_limpo: Any) -> None:
    """Sem rede, a folha vem da cache: as páginas guardadas continuam vestidas."""
    worker = render.render_service_worker(store.get_settings())
    assert '"/site/site.css"' in worker
