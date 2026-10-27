"""Email transacional do IQ OS.

Envio de mensagens transacionais (aprovação de conta, início de trial,
lembrete de pagamento) através de um servidor SMTP configurável na
administração ou em variáveis de ambiente.

Todas as mensagens terminam com a **assinatura de marca** (`api/email_signature`):
logótipo, «Sabemos Studio» e a ligação para o site. É aplicada num só sítio
(`build_message`), pelo que nenhum envio se esquece dela nem a repete.

A configuração segue a mesma hierarquia do resto da plataforma:
parâmetro → índice (`finance_settings/service-keys`) → ambiente → `.env`.
Se não houver servidor configurado, o envio falha silenciosamente e regista
um aviso nos logs — nunca bloqueia a aprovação ou o login.
"""
from __future__ import annotations

import logging
import smtplib
import ssl
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formataddr, formatdate
from typing import Any, Dict, Optional

from api import email_service
from api import email_signature
from api import service_keys

logger = logging.getLogger(__name__)

DEFAULT_SMTP_PORT = 587
DEFAULT_SMTP_SECURITY = "starttls"


def _smtp_config() -> Dict[str, Any]:
    """Lê a configuração SMTP efetiva."""
    host = (service_keys.resolver("smtp_host") or "").strip()
    port_raw = service_keys.resolver("smtp_port") or "587"
    try:
        port = int(port_raw)
    except ValueError:
        port = DEFAULT_SMTP_PORT
    security = (service_keys.resolver("smtp_security") or "starttls").strip().lower()
    if security not in {"starttls", "ssl", "plain"}:
        security = DEFAULT_SMTP_SECURITY
    user = (service_keys.resolver("smtp_user") or "").strip()
    password = service_keys.resolver("smtp_password") or ""
    from_ = (service_keys.resolver("smtp_from") or user or "").strip()
    return {
        "host": host,
        "port": port,
        "security": security,
        "user": user,
        "password": password,
        "from": from_,
    }


def is_configured() -> bool:
    """True quando há remetente e servidor SMTP prontos a usar."""
    cfg = _smtp_config()
    return bool(cfg["host"] and cfg["from"])


def _parse_from(raw: str) -> tuple[str, str]:
    """Interpreta 'Nome <email@example.com>' ou apenas 'email@example.com'."""
    raw = (raw or "").strip()
    if raw.endswith(">") and "<" in raw:
        name, _, address = raw.rpartition("<")
        return name.strip(), address.rstrip(">").strip()
    return "", raw


def build_message(
    *,
    sender_name: str,
    sender_address: str,
    to: str,
    subject: str,
    text: str,
    html: Optional[str] = None,
    reply_to: str = "",
) -> EmailMessage:
    """Compõe a mensagem transacional, com a assinatura de marca já aplicada.

    Está separado do envio para se poder verificar (em teste) o que sai daqui sem
    precisar de um servidor de correio. O `reply_to` é o endereço de quem pediu o
    contacto: responder ao aviso responde ao pedido, sem copiar endereços à mão.
    """
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((sender_name, sender_address)) if sender_name else sender_address
    msg["To"] = to.strip()
    if reply_to.strip():
        msg["Reply-To"] = reply_to.strip()
    # `Date` e `Message-ID` não são opcionais na prática: um `EmailMessage` do
    # `smtplib` não os acrescenta sozinho, e a falta deles é pontuação de spam em
    # qualquer filtro (o RFC 5322 exige a data). O domínio do `Message-ID` sai do
    # remetente, e não do nome do contentor — a regra é a mesma para todo o
    # correio da plataforma (`email_service.make_message_id`).
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = email_service.make_message_id(sender_address)
    msg.set_content(email_signature.append_to_text(text))
    if html:
        msg.add_alternative(email_signature.append_to_html(html), subtype="html")
    return msg


def _send(
    to: str,
    subject: str,
    text: str,
    html: Optional[str] = None,
    reply_to: str = "",
) -> Dict[str, Any]:
    """Envia um email transacional. Devolve {"ok": bool, ...}."""
    cfg = _smtp_config()
    if not cfg["host"] or not cfg["from"]:
        logger.warning("Email transacional não enviado: SMTP não configurado.")
        return {"ok": False, "configured": False, "message": "SMTP não configurado."}
    if not to.strip():
        return {"ok": False, "configured": True, "message": "Destinatário em falta."}

    from_name, from_address = _parse_from(cfg["from"])
    if not from_address:
        return {"ok": False, "configured": True, "message": "Remetente inválido."}

    msg = build_message(
        sender_name=from_name,
        sender_address=from_address,
        to=to,
        subject=subject,
        text=text,
        html=html,
        reply_to=reply_to,
    )

    try:
        if cfg["security"] == "ssl":
            server = smtplib.SMTP_SSL(cfg["host"], cfg["port"], timeout=20, context=ssl.create_default_context())
        else:
            server = smtplib.SMTP(cfg["host"], cfg["port"], timeout=20)
        if cfg["security"] == "starttls":
            server.starttls(context=ssl.create_default_context())
        if cfg["user"]:
            server.login(cfg["user"], cfg["password"])
        server.send_message(msg)
        server.quit()
        return {"ok": True, "configured": True, "message": "Email enviado."}
    except Exception as exc:  # noqa: BLE001 - envio nunca deve travar a aprovação
        logger.warning("Falha ao enviar email transacional para %s: %s", to, exc)
        return {"ok": False, "configured": True, "message": f"Falha de envio: {exc}"}


def _format_date(iso: Optional[str]) -> str:
    if not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).strftime("%d/%m/%Y às %H:%M")
    except ValueError:
        return str(iso)


def send_login_code_email(to: str, name: str, code: str, *, ttl_minutes: int = 10, ip: str = "") -> Dict[str, Any]:
    """Código de verificação em dois passos (login).

    O código é de uso único e expira; a mensagem não revela a palavra-passe nem
    qualquer outro dado da conta. Quando o login vem de um IP conhecido, aparece
    na mensagem — é o sinal mais simples de «não fui eu».
    """
    subject = "Código de verificação IQ OS"
    minutes = max(1, int(ttl_minutes))
    origem = f"\nPedido a partir do IP {ip}.\n" if ip else ""
    text = f"""Olá {name},

O seu código de verificação é:

    {code}

Introduza-o na página de entrada para concluir o início de sessão. O código
expira em {minutes} minutos e só pode ser usado uma vez.{origem}
Se não tentou entrar na sua conta, ignore esta mensagem e altere a palavra-passe.
"""
    digits = "".join(ch for ch in code if ch.isdigit()) or code
    html = f"""\
<html>
<body style="font-family: sans-serif; color: #111;">
<p>Olá {name},</p>
<p>O seu código de verificação é:</p>
<p style="font-size: 28px; font-weight: 700; letter-spacing: 8px; margin: 18px 0;">{digits}</p>
<p>Introduza-o na página de entrada para concluir o início de sessão. O código expira em
<strong>{minutes} minutos</strong> e só pode ser usado uma vez.</p>
{f'<p>Pedido a partir do IP <strong>{ip}</strong>.</p>' if ip else ''}
<p>Se não tentou entrar na sua conta, ignore esta mensagem e altere a palavra-passe.</p>
</body>
</html>
"""
    return _send(to, subject, text, html)


def send_approval_email(to: str, name: str, trial_expires_at: str) -> Dict[str, Any]:
    """Email enviado quando um administrador aprova uma conta."""
    expires = _format_date(trial_expires_at)
    subject = "A sua conta IQ OS foi aprovada — trial de 5 dias"
    text = f"""Olá {name},

A sua conta no IQ OS foi aprovada por um administrador.

Tem agora acesso a um trial de 5 dias, até {expires}.

Passado esse período, será necessário efetuar o pagamento para manter o acesso ativo.
"""
    html = f"""\
<html>
<body style="font-family: sans-serif; color: #111;">
<p>Olá {name},</p>
<p>A sua conta no IQ OS foi <strong>aprovada</strong> por um administrador.</p>
<p>Tem agora acesso a um <strong>trial de 5 dias</strong>, até <strong>{expires}</strong>.</p>
<p>Passado esse período, será necessário efetuar o pagamento para manter o acesso ativo.</p>
</body>
</html>
"""
    return _send(to, subject, text, html)


def send_trial_expiring_email(to: str, name: str, trial_expires_at: str) -> Dict[str, Any]:
    """Email de lembrete quando o trial está prestes a expirar."""
    expires = _format_date(trial_expires_at)
    subject = "O seu trial do IQ OS expira em breve"
    text = f"""Olá {name},

O seu período de trial no IQ OS termina {expires}.

Para continuar a usar a plataforma, efetue o pagamento antes do prazo em Definições → Perfil → Billing. Caso contrário, o acesso será desativado.
"""
    html = f"""\
<html>
<body style="font-family: sans-serif; color: #111;">
<p>Olá {name},</p>
<p>O seu período de trial no IQ OS termina <strong>{expires}</strong>.</p>
<p>Para continuar a usar a plataforma, efetue o pagamento antes do prazo em <strong>Definições → Perfil → Billing</strong>. Caso contrário, o acesso será <strong>desativado</strong>.</p>
</body>
</html>
"""
    return _send(to, subject, text, html)


def send_subscription_activated_email(to: str, name: str, plan_name: str, period_end: str) -> Dict[str, Any]:
    """Email enviado após confirmação de pagamento."""
    expires = _format_date(period_end)
    subject = f"Subscrição IQ OS {plan_name} ativada"
    text = f"""Olá {name},

A sua subscrição IQ OS {plan_name} foi ativada com sucesso e está válida até {expires}.

Pode consultar os detalhes em Definições → Perfil → Billing.
"""
    html = f"""\
<html>
<body style="font-family: sans-serif; color: #111;">
<p>Olá {name},</p>
<p>A sua subscrição IQ OS <strong>{plan_name}</strong> foi ativada com sucesso e está válida até <strong>{expires}</strong>.</p>
<p>Pode consultar os detalhes em <strong>Definições → Perfil → Billing</strong>.</p>
</body>
</html>
"""
    return _send(to, subject, text, html)


def send_contact_email(
    *,
    to: str,
    nome: str,
    email: str,
    organizacao: str = "",
    assunto: str = "",
    mensagem: str = "",
    registo_url: str = "",
) -> Dict[str, Any]:
    """Avisa a caixa de apoio de um pedido enviado pelo formulário do site.

    O pedido já ficou guardado no CMS («Contactos»); isto é só o aviso, para não
    ser preciso abrir a plataforma para saber que alguém escreveu. O `Reply-To` é
    o email de quem escreveu, para responder ao pedido a partir da caixa.
    """
    titulo = f"Pedido do site: {assunto.strip() or 'sem assunto'} — {nome.strip() or email.strip()}"
    linhas = [
        "Pedido enviado pelo formulário de contacto do site.",
        "",
        f"Nome: {nome}",
        f"Email: {email}",
    ]
    if organizacao.strip():
        linhas.append(f"Organização: {organizacao.strip()}")
    if assunto.strip():
        linhas.append(f"Assunto: {assunto.strip()}")
    linhas += ["", "Mensagem:", mensagem.strip() or "(sem texto)"]
    if registo_url.strip():
        linhas += ["", f"Ver o pedido na plataforma: {registo_url.strip()}"]
    linhas += ["", "Responda a este email para responder ao pedido."]
    return _send(to=to, subject=titulo, text="\n".join(linhas), reply_to=email)
