"""Testes da assinatura de marca dos emails (`api/email_signature.py`).

A assinatura é o que o destinatário vê em todos os emails da plataforma, por
isso o que aqui se fixa é sobretudo o que a torna **visível e legível no cliente
de correio**: o logótipo vai por URL absoluto em PNG (os clientes não desenham
SVG), o HTML é uma tabela com estilos embutidos (muitos clientes descartam
`<style>`) e o bloco entra antes do `</body>` para o documento continuar válido.

Verifica-se também a ligação às duas famílias de emails — o transacional
(`api/notification_email.py`) e o Correio da plataforma
(`api/platform_mail_service.py`) — e que a despedida antiga não voltou a juntar-
se à assinatura.

Nada aqui fala com um servidor de correio: o SMTP é substituído.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from api import email_signature  # noqa: E402
from api import notification_email  # noqa: E402
from api import platform_mail_service  # noqa: E402

HTML_COM_BODY = "<html><body><p>Olá.</p></body></html>"


# ------------------------------------------------------------------ a assinatura
def test_assinatura_em_texto_tem_marca_produto_e_site() -> None:
    bloco = email_signature.text_block()
    assert email_signature.BRAND in bloco
    assert email_signature.PRODUCT in bloco
    assert email_signature.SITE_URL in bloco


def test_assinatura_em_html_usa_logotipo_png_por_url_absoluta() -> None:
    """O logótipo tem de ser PNG e por URL: SVG o Gmail descarta, e um caminho
    relativo não existe em quem está a ler o email."""
    bloco = email_signature.html_block()
    assert email_signature.LOGO_URL.endswith(".png")
    assert email_signature.LOGO_URL.startswith("https://")
    assert f'src="{email_signature.LOGO_URL}"' in bloco
    # Os leitores que bloqueiam imagens mostram o `alt`.
    assert f'alt="{email_signature.BRAND}"' in bloco
    # Nada de folhas de estilo: os clientes de correio descartam-nas.
    assert "<style" not in bloco
    assert "style=" in bloco


def test_assinatura_em_html_aponta_para_o_site() -> None:
    bloco = email_signature.html_block()
    assert f'href="{email_signature.SITE_URL}"' in bloco


def test_juntar_assinatura_ao_texto_preserva_o_corpo() -> None:
    texto = email_signature.append_to_text("Bom dia.\n\nSegue o resumo.")
    assert texto.startswith("Bom dia.\n\nSegue o resumo.")
    assert texto.endswith(email_signature.text_block())


@pytest.mark.parametrize("vazio", ["", "   ", "\n", None])
def test_juntar_assinatura_a_texto_vazio_devolve_so_a_assinatura(vazio) -> None:
    assert email_signature.append_to_text(vazio) == email_signature.text_block()


def test_juntar_assinatura_ao_html_entra_antes_do_fecho_do_body() -> None:
    html = email_signature.append_to_html(HTML_COM_BODY)
    assert "<p>Olá.</p>" in html
    assert html.index(email_signature.LOGO_URL) < html.index("</body>")
    assert html.rstrip().endswith("</body></html>")


def test_juntar_assinatura_a_html_sem_body_fica_no_fim() -> None:
    html = email_signature.append_to_html("<p>Olá.</p>")
    assert html.startswith("<p>Olá.</p>")
    assert email_signature.LOGO_URL in html


def test_juntar_assinatura_a_html_vazio_devolve_so_a_assinatura() -> None:
    assert email_signature.append_to_html("") == email_signature.html_block()
    assert email_signature.append_to_html(None) == email_signature.html_block()


# --------------------------------------------------------------- email transacional
def test_email_transacional_sai_com_a_assinatura_nos_dois_formatos() -> None:
    mensagem = notification_email.build_message(
        sender_name="Sabemos Studio",
        sender_address="no-reply@sabemos.studio",
        to="membro@exemplo.pt  ",
        subject="Conta aprovada",
        text="Bom dia,\n\nA sua conta foi aprovada.",
        html=f"<html><body><p>A sua conta foi aprovada.</p></body></html>",
    )
    assert mensagem["To"] == "membro@exemplo.pt"
    assert mensagem["From"] == "Sabemos Studio <no-reply@sabemos.studio>"
    # Sem data nem Message-ID, o filtro de spam não perdoa (RFC 5322).
    assert mensagem["Date"]
    assert str(mensagem["Message-ID"]).endswith("@sabemos.studio>")

    texto = mensagem.get_body(("plain")).get_content()
    assert "A sua conta foi aprovada." in texto
    assert email_signature.text_block() in texto

    html = mensagem.get_body(("html")).get_content()
    assert email_signature.LOGO_URL in html
    assert html.index(email_signature.LOGO_URL) < html.index("</body>")


def test_email_transacional_sem_nome_de_remetente_usa_so_o_endereco() -> None:
    mensagem = notification_email.build_message(
        sender_name="",
        sender_address="no-reply@sabemos.studio",
        to="membro@exemplo.pt",
        subject="Aviso",
        text="Corpo.",
    )
    assert mensagem["From"] == "no-reply@sabemos.studio"


@pytest.mark.parametrize(
    "enviar",
    [
        lambda: notification_email.send_approval_email("membro@exemplo.pt", "Maria", ""),
        lambda: notification_email.send_trial_expiring_email("membro@exemplo.pt", "Maria", ""),
        lambda: notification_email.send_subscription_activated_email("membro@exemplo.pt", "Maria", "Pro", ""),
    ],
)
def test_emails_transacionais_nao_repetem_a_despedida(enviar, monkeypatch) -> None:
    """A despedida é agora a assinatura de marca: o texto não a repete."""
    capturado: dict = {}

    def falso_send(to, subject, text, html=None):
        capturado.update({"to": to, "subject": subject, "text": text, "html": html})
        return {"ok": True}

    monkeypatch.setattr(notification_email, "_send", falso_send)
    enviar()

    assert capturado["to"] == "membro@exemplo.pt"
    assert capturado["subject"]
    assert "A equipa IQ OS" not in capturado["text"]
    assert "A equipa IQ OS" not in (capturado["html"] or "")


# ------------------------------------------------------------ correio da plataforma
def _conta(**extra):
    conta = {
        "id": "plataforma",
        "label": "Correio da plataforma",
        "email_address": "no-reply@sabemos.studio",
        "display_name": "IQ OS",
        "signature": "",
    }
    conta.update(extra)
    return conta


def test_caixa_da_plataforma_usa_a_assinatura_de_marca_por_omissao() -> None:
    mensagem = platform_mail_service.build_message(
        _conta(),
        {"subject": "Olá"},
        ["membro@exemplo.pt"],
        [],
        "Bom dia.",
        "<p>Bom dia.</p>",
    )
    texto = mensagem.get_body(("plain")).get_content()
    assert email_signature.text_block() in texto

    html = mensagem.get_body(("html")).get_content()
    assert email_signature.LOGO_URL in html
    assert "<p>Bom dia.</p>" in html


def test_assinatura_propria_com_marcacao_entra_como_html() -> None:
    mensagem = platform_mail_service.build_message(
        _conta(signature='<p>Com os melhores cumprimentos,<br><b>Equipa</b></p>'),
        {"subject": "Olá"},
        ["membro@exemplo.pt"],
        [],
        "Bom dia.",
        "<p>Bom dia.</p>",
    )
    html = mensagem.get_body(("html")).get_content()
    assert "<b>Equipa</b>" in html
    assert "&lt;b&gt;" not in html

    # O corpo em texto não leva etiquetas.
    texto = mensagem.get_body(("plain")).get_content()
    assert "Com os melhores cumprimentos," in texto
    assert "<b>" not in texto


def test_assinatura_propria_simples_nao_e_interpretada_como_html() -> None:
    mensagem = platform_mail_service.build_message(
        _conta(signature="Maria & Associados"),
        {"subject": "Olá"},
        ["membro@exemplo.pt"],
        [],
        "Bom dia.",
        "<p>Bom dia.</p>",
    )
    texto = mensagem.get_body(("plain")).get_content()
    assert "Maria & Associados" in texto
    html = mensagem.get_body(("html")).get_content()
    assert "Maria & Associados" in html
    assert "<pre" in html


def test_sem_assinatura_pedida_nao_sai_nem_a_de_marca() -> None:
    mensagem = platform_mail_service.build_message(
        _conta(),
        {"subject": "Olá", "include_signature": False},
        ["membro@exemplo.pt"],
        [],
        "Bom dia.",
        "<p>Bom dia.</p>",
    )
    assert email_signature.BRAND not in mensagem.get_body(("plain")).get_content()
    assert email_signature.LOGO_URL not in mensagem.get_body(("html")).get_content()


def test_api_expoe_a_assinatura_para_a_aplicacao_mostrar() -> None:
    """Ao compor, a aplicação mostra o que vai sair: a assinatura vem da API,
    para não existir uma segunda cópia no frontend."""
    informacao = platform_mail_service.meta()
    assert informacao["signature"]["html"] == email_signature.html_block()
    assert informacao["signature"]["text"] == email_signature.text_block()
