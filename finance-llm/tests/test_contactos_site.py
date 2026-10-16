"""Testes do formulário e da página de contactos do site.

A página de contactos tem uma função só: levar a um pedido concreto. A abertura
aponta ao formulário pela âncora `#pedido`, os quatro temas vão em cartões (que
se leem antes do texto corrido) e cada campo obrigatório diz que o é sem
depender do asterisco — quem usa leitor de ecrã ouve «obrigatório» pelo próprio
campo. Estes testes fixam isso e o caminho de erro, que é onde se perde quem
escreve.
"""

from __future__ import annotations

from typing import Any, Dict, Iterator

import pytest
from fastapi.testclient import TestClient

from api import cms_editorial as editorial
from api import cms_render as render
from api import cms_store as store


@pytest.fixture()
def cms_limpo(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> Iterator[Any]:
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


@pytest.fixture()
def media_de_marca(cms_limpo: Any) -> Dict[str, str]:
    """O CMS vazio com as imagens de marca instaladas (`{ficheiro: id}`).

    Sem isto, os ícones e as ilustrações não resolvem e a página sai sem eles —
    que é precisamente o que se quer verificar.
    """
    return store.instalar_media_de_marca()


# ------------------------------------------------------------------ formulário
def test_formulario_tem_grelha_ancora_e_os_limites_do_servidor() -> None:
    html = render.formulario_contacto(
        {
            "title": "Pedido de contacto",
            "intro": "Quanto mais concreta for a pergunta, mais rápida é a resposta.",
            "anchor": "pedido",
            "note": "Se preferir, use [geral@iqos.pt](mailto:geral@iqos.pt).",
        }
    )

    # A âncora é o que o botão da abertura tem de encontrar (`#pedido`).
    assert 'class="section formulario" id="pedido"' in html
    # Campos em grelha; a mensagem ocupa a largura toda (duas colunas no CSS).
    assert '<div class="campos">' in html
    assert '<div class="campo larga">' in html and 'id="contacto-mensagem"' in html
    # Obrigatório pelos atributos e pela marca, que não é lida em voz alta.
    assert 'required aria-required="true"' in html
    assert '<span class="marca" aria-hidden="true">*</span>' in html
    # Os limites do servidor vão no próprio campo (ver `store.CONTACTO_LIMITES`).
    assert 'maxlength="120"' in html and 'maxlength="160"' in html and 'maxlength="4000"' in html
    # Assunto: sugestões dos temas que tratamos, sem fechar a porta a outros.
    assert 'list="contacto-assunto-sugestoes"' in html
    for assunto in ("Análise à medida", "Correção de um número", "Dados e cobertura", "Imprensa"):
        assert f'<option value="{assunto}"></option>' in html
    # A linha de apoio fica ligada ao campo que a explica.
    assert 'aria-describedby="contacto-mensagem-ajuda"' in html
    assert 'Diga o que quer saber, para quando' in html
    # O que acontece depois do envio fica na linha do botão, não depois dele.
    assert '<div class="acao">' in html and '<div class="nota-formulario">' in html
    assert 'mailto:geral@iqos.pt' in html
    # O campo-armadilha continua fora do ecrã e fora da ordem de tabulação.
    assert 'name="website"' in html and 'tabindex="-1"' in html


def test_erros_do_formulario_ficam_assinalados_no_campo() -> None:
    html = render.formulario_contacto(
        {"title": "Fale connosco", "intro": "Corrija o que falta e volte a enviar."},
        valores={"email": "quem-escreve@exemplo.pt"},
        erros={"nome": "Indique o seu nome.", "consentimento": "Precisa de autorizar o contacto para enviar."},
        aviso="Confira os campos assinalados.",
    )

    assert '<div class="aviso red">Confira os campos assinalados.</div>' in html
    assert '<small class="erro" role="alert">Indique o seu nome.</small>' in html
    assert "Precisa de autorizar o contacto para enviar." in html
    # O que já estava escrito não se perde ao voltar atrás.
    assert 'value="quem-escreve@exemplo.pt"' in html


# ------------------------------------------------------------------- a página
def test_pagina_de_contactos_leva_ao_formulario(media_de_marca: Dict[str, str]) -> None:
    paginas = {str(pagina["path"]): pagina for pagina in editorial.paginas_do_site(media_de_marca)}
    blocos = paginas["contactos"]["blocks"]
    html = render.blocks_to_html(blocos)

    # A abertura aponta ao formulário e traz a ilustração da página.
    abertura = blocos[0]["data"]
    assert abertura["cta_href"] == "#pedido" and abertura["cta_label"]
    assert abertura["image_id"] == media_de_marca["ilustracao-contactos.svg"]
    assert 'href="#pedido"' in html and '<figure class="cover">' in html
    # Os quatro temas, cada um no seu cartão com ícone.
    assert html.count('<div class="tile">') == 4
    assert html.count('class="tile-icon"') == 4
    for tema in ("Análise à medida", "Correções", "Dados", "Imprensa"):
        assert f"<h3>{tema}</h3>" in html
    # O formulário é o destino da âncora e diz o que acontece a seguir ao envio.
    assert 'id="pedido"' in html
    assert 'class="nota-formulario"' in html
    assert "<h2>O que acontece a seguir</h2>" in html
    assert html.count('<div class="step">') == 3
    # Fecha com o convite ao que já está publicado, antes de alguém escrever.
    assert 'class="section cta"' in html and 'href="/site/relatorios-gratuitos"' in html


# ------------------------------------------------------------------ os envios
def test_pedido_incompleto_volta_com_os_erros(cms_limpo: Any) -> None:
    from api import main as api_main

    cliente = TestClient(api_main.app, base_url="http://prova")
    resposta = cliente.post(
        "/site/contacto",
        data={"nome": "", "email": "sem-arroba", "organizacao": "Imprensa", "mensagem": ""},
    )

    assert resposta.status_code == 422
    assert "Indique o seu nome." in resposta.text
    assert "Esse email não parece válido." in resposta.text
    assert "Escreva a mensagem." in resposta.text
    assert "Precisa de autorizar o contacto para enviar." in resposta.text
    # O que já estava escrito fica à espera de ser corrigido.
    assert 'value="Imprensa"' in resposta.text
    assert store.list_items("contactos")["items"] == []


def test_campo_armadilha_recebe_agradecimento_e_nao_guarda_nada(cms_limpo: Any) -> None:
    from api import main as api_main

    cliente = TestClient(api_main.app, base_url="http://prova")
    resposta = cliente.post(
        "/site/contacto",
        data={
            "nome": "Robô",
            "email": "robo@exemplo.pt",
            "mensagem": "compra de links",
            "consentimento": "sim",
            "website": "http://spam.exemplo",
        },
    )

    assert resposta.status_code == 200
    assert "Mensagem recebida" in resposta.text
    assert store.list_items("contactos")["items"] == []
