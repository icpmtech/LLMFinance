"""Assinatura de marca dos emails da plataforma.

Todos os emails que a plataforma envia terminam com a mesma assinatura: o
logótipo, a marca e o caminho de volta para o site.

- **Email transacional** (`api/notification_email.py`) — aprovação de conta, fim
  de trial, subscrição ativada. A assinatura entra num só sítio (`_send`), pelo
  que não se repete em cada mensagem.
- **Correio da plataforma** (`api/platform_mail_service.py`) — as mensagens
  escritas na aplicação; uma caixa sem assinatura própria usa esta.

O logótipo vai por **URL público**, e em **PNG**: os clientes de correio não
desenham SVG (o Gmail descarta-o) e um ficheiro local, ou um `cid:` sem a parte
`related` na mensagem, apareceria em branco. O PNG é o mesmo ícone de marca que
serve o PWA do site e da loja, servido pelo backend em `/site/pwa/`.

O HTML é uma tabela com estilos embutidos, como os clientes de correio exigem:
muitos descartam `<style>` e classes, e o Outlook não implementa flexbox.
"""
from __future__ import annotations

from typing import Optional

#: Logótipo (PNG 192px, servido pelo próprio backend). Ver o docstring do módulo
#: para o motivo de ser PNG e por URL.
LOGO_URL = "https://sabemos.studio/site/pwa/pwa-icone-192.png"
SITE_URL = "https://sabemos.studio"
BRAND = "Sabemos Studio"
PRODUCT = "IQ OS — inteligência financeira e contratual"

TEAL = "#0ea5a4"
SLATE = "#475569"
INK = "#0f172a"
LINK = "#1d4ed8"


def text_block() -> str:
    """Assinatura em texto simples (a que acompanha sempre o HTML)."""
    return f"--\n{BRAND}\n{PRODUCT}\n{SITE_URL}\n"


def html_block() -> str:
    """Assinatura em HTML: logótipo, marca, descrição e ligação para o site."""
    return f"""\
<table cellpadding="0" cellspacing="0" role="presentation" style="border-collapse:collapse;margin-top:20px;font-family:Arial,Helvetica,sans-serif;font-size:13px;color:{SLATE};">
  <tr>
    <td style="padding:0 14px 0 0;vertical-align:middle;">
      <img src="{LOGO_URL}" width="44" height="44" alt="{BRAND}" style="display:block;width:44px;height:44px;border:0;border-radius:11px;">
    </td>
    <td style="vertical-align:middle;border-left:2px solid {TEAL};padding-left:14px;">
      <div style="font-size:15px;font-weight:700;color:{INK};">{BRAND}</div>
      <div style="color:{SLATE};">{PRODUCT}</div>
      <div><a href="{SITE_URL}" style="color:{LINK};text-decoration:none;">sabemos.studio</a></div>
    </td>
  </tr>
</table>
"""


def append_to_text(text: Optional[str]) -> str:
    """Junta a assinatura ao corpo em texto (separada por uma linha em branco)."""
    corpo = (text or "").rstrip()
    bloco = text_block()
    return f"{corpo}\n\n{bloco}" if corpo else bloco


def append_to_html(html: Optional[str]) -> str:
    """Junta a assinatura ao corpo em HTML, antes de `</body>` quando existe.

    Inserir antes do fecho mantém o documento válido; um cliente que só leia até
    ao fim do `body` não perde a assinatura.
    """
    corpo = (html or "").rstrip()
    bloco = html_block()
    if not corpo:
        return bloco
    fecho = corpo.lower().rfind("</body>")
    if fecho == -1:
        return f"{corpo}\n{bloco}"
    return f"{corpo[:fecho]}{bloco}{corpo[fecho:]}"
