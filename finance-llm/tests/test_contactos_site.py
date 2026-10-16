"""Testes do formulário e da página de contactos do site.

A página de contactos tem uma função só: levar a um pedido concreto. A abertura
aponta ao formulário pela âncora `#pedido`, os quatro temas vão em cartões (que
se leem antes do texto corrido) e cada campo obrigatório diz que o é sem
depender do asterisco — quem usa leitor de ecrã ouve «obrigatório» pelo próprio
campo. Estes testes fixam isso, o caminho de erro (que é onde se perde quem
escreve) e o aviso à caixa de apoio, que é o que evita que um pedido fique
fechado na plataforma sem ninguém saber.
"""

from __future__ import annotations

from typing import Any, Dict, Iterator, List, Optional

import pytest
from fastapi.testclient import TestClient

from api import captcha
from api import cms_editorial as editorial
from api import cms_render as render
from api import cms_store as store
from api import notification_email

#: O que uma pessoa lê na pergunta do desafio anti-robô. Escrito de novo de
#: propósito: o teste resolve o captcha como quem o lê, e não a perguntar a
#: resposta a quem o fez.
_NUMEROS = {
    "um": 1, "dois": 2, "três": 3, "quatro": 4, "cinco": 5, "seis": 6, "sete": 7, "oito": 8, "nove": 9,
    "dez": 10, "onze": 11, "doze": 12, "treze": 13, "catorze": 14, "quinze": 15, "dezasseis": 16,
    "dezassete": 17, "dezoito": 18,
}


def _desafio_resolvido() -> Dict[str, str]:
    """Um desafio novo, já respondido (como uma pessoa o responderia)."""
    desafio = captcha.desafio()
    palavras = desafio["pergunta"].rstrip("?").split()
    primeiro, operacao, segundo = _NUMEROS[palavras[2]], palavras[3], _NUMEROS[palavras[4]]
    conta = primeiro + segundo if operacao == "mais" else primeiro - segundo
    return {captcha.CAMPO_RESPOSTA: str(conta), captcha.CAMPO_TESTEMUNHO: desafio["token"]}


@pytest.fixture()
def sem_espera(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sem o compasso de dois segundos do desafio (um teste não deve dormir)."""
    monkeypatch.setattr(captcha, "DEMORA_MINIMA_SEGUNDOS", 0)


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
            "note": "Se preferir, use [suporte@sabemos.studio](mailto:suporte@sabemos.studio).",
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
    assert 'mailto:suporte@sabemos.studio' in html
    # Desafio anti-robô: a pergunta é o rótulo do campo e o testemunho vai escondido.
    assert '<div class="campo captcha">' in html
    assert 'id="contacto-captcha"' in html and 'name="captcha_token"' in html
    assert ">Quanto dá " in html and 'inputmode="numeric"' in html
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
    # O desafio em falta junta-se aos outros erros, na mesma resposta.
    assert "Responda ao desafio, para confirmarmos que é uma pessoa." in resposta.text
    # O que já estava escrito fica à espera de ser corrigido.
    assert 'value="Imprensa"' in resposta.text
    assert store.list_items("contactos")["items"] == []


def test_pedido_sem_desafio_nao_entra_nem_avisa(cms_limpo: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Sem responder ao captcha não há registo nem email — é o ponto dele."""
    from api import main as api_main

    avisos: List[Dict[str, Any]] = []
    monkeypatch.setattr(notification_email, "send_contact_email", lambda **campos: avisos.append(campos) or {"ok": True})
    monkeypatch.setattr(store, "_contactos_por_ip", {})

    cliente = TestClient(api_main.app, base_url="http://prova")
    base = {
        "nome": "Ana Silva",
        "email": "ana@exemplo.pt",
        "assunto": "Dados e cobertura",
        "mensagem": "Pedido sem resposta ao desafio.",
        "consentimento": "sim",
    }
    sem_resposta = cliente.post("/site/contacto", data=base)
    resposta_errada = cliente.post(
        "/site/contacto",
        data={**base, **{**_desafio_resolvido(), captcha.CAMPO_TESTEMUNHO: captcha.desafio()["token"]}},
    )

    assert sem_resposta.status_code == 422
    assert "Responda ao desafio, para confirmarmos que é uma pessoa." in sem_resposta.text
    assert "A resposta ao desafio não confere." in resposta_errada.text
    assert avisos == []
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


def test_pedido_valido_guarda_e_avisa_a_caixa_de_apoio(
    cms_limpo: Any, monkeypatch: pytest.MonkeyPatch, sem_espera: None
) -> None:
    """O pedido fica guardado no CMS **e** sai um aviso para a caixa de apoio."""
    from api import main as api_main
    from api import reports_store

    avisos: List[Dict[str, Any]] = []
    monkeypatch.setattr(notification_email, "send_contact_email", lambda **campos: avisos.append(campos) or {"ok": True})
    # O endereço de apoio é o configurado nos Relatórios; aqui fixa-se para o
    # teste não depender do que estiver gravado na instalação.
    monkeypatch.setattr(reports_store, "settings", lambda: {"support_email": "apoio@exemplo.pt"})
    monkeypatch.setattr(store, "_contactos_por_ip", {})

    cliente = TestClient(api_main.app, base_url="http://prova")
    resposta = cliente.post(
        "/site/contacto",
        data={
            "nome": "Ana Silva",
            "email": "ana@exemplo.pt",
            "organizacao": "Jornal do Norte",
            "assunto": "Correção de um número",
            "mensagem": "O valor do Porto não bate certo com o Portal BASE.",
            "consentimento": "sim",
            **_desafio_resolvido(),
        },
    )

    assert resposta.status_code == 200 and "Mensagem recebida" in resposta.text
    guardados = store.list_items("contactos")["items"]
    assert len(guardados) == 1 and guardados[0]["estado"] == "novo"
    # O desafio não se guarda no pedido (é da sessão, não do registo).
    assert "captcha" not in guardados[0] and "captcha_token" not in guardados[0]
    assert avisos and avisos[0]["to"] == "apoio@exemplo.pt"
    assert avisos[0]["email"] == "ana@exemplo.pt"
    assert avisos[0]["assunto"] == "Correção de um número"
    assert avisos[0]["organizacao"] == "Jornal do Norte"
    assert "Portal BASE" in avisos[0]["mensagem"]


def test_aviso_do_pedido_responde_a_quem_escreveu(monkeypatch: pytest.MonkeyPatch) -> None:
    """O aviso diz o que interessa e responde ao pedido: `Reply-To` do autor."""
    enviados: Dict[str, Any] = {}

    def falso(to: str, subject: str, text: str, html: Optional[str] = None, reply_to: str = "") -> Dict[str, Any]:
        enviados.update({"to": to, "subject": subject, "text": text, "reply_to": reply_to})
        return {"ok": True}

    monkeypatch.setattr(notification_email, "_send", falso)
    resultado = notification_email.send_contact_email(
        to="suporte@sabemos.studio",
        nome="Ana Silva",
        email="ana@exemplo.pt",
        organizacao="Jornal do Norte",
        assunto="Dados e cobertura",
        mensagem="Queria os ficheiros de 2025, por concelho.",
        registo_url="https://sabemos.studio/cms/contactos",
    )

    assert resultado == {"ok": True}
    assert enviados["to"] == "suporte@sabemos.studio"
    assert enviados["reply_to"] == "ana@exemplo.pt"
    assert "Dados e cobertura" in enviados["subject"] and "Ana Silva" in enviados["subject"]
    for pedaco in (
        "ana@exemplo.pt",
        "Jornal do Norte",
        "Queria os ficheiros de 2025, por concelho.",
        "https://sabemos.studio/cms/contactos",
    ):
        assert pedaco in enviados["text"]


def test_email_leva_reply_to_so_quando_e_pedido() -> None:
    """Sem `reply_to` (aprovações, avisos internos) o cabeçalho não sai."""
    sem_reply = notification_email.build_message(
        sender_name="IQ OS",
        sender_address="no-reply@sabemos.studio",
        to="alguem@exemplo.pt",
        subject="Conta aprovada",
        text="Corpo",
    )
    com_reply = notification_email.build_message(
        sender_name="IQ OS",
        sender_address="no-reply@sabemos.studio",
        to="suporte@sabemos.studio",
        subject="Pedido do site: Dados e cobertura — Ana Silva",
        text="Corpo",
        reply_to="ana@exemplo.pt",
    )

    assert sem_reply["Reply-To"] is None
    assert com_reply["Reply-To"] == "ana@exemplo.pt"
    assert com_reply["To"] == "suporte@sabemos.studio"
