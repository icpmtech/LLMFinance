"""Verifica a entrada de correio da VM, de fora, como faria outro servidor.

Corre no PC (nao precisa de ssh nem de VM): fala com a porta 25 publica, sem
autenticacao e sem TLS -- que e como os servidores de correio do mundo entregam
correio.

     python deploy\\kamatera\\_teste_correio.py
     python deploy\\kamatera\\_teste_correio.py --servidor 45.147.251.188 --dominio sabemos.studio

Confirma tres coisas:

  1. a porta 25 esta acessivel da Internet (firewall da Kamatera aberto);
  2. o Postfix aceita correio para a caixa local (`postmaster@<dominio>`);
  3. **nao** retransmite para fora sem autenticacao -- um servidor de correio
     publico que retransmita e um relay aberto, e a forma mais rapida de a VM
     entrar numa lista negra.

Corre depois de mexer no firewall, no DNS ou no `servicos/mailserver/compose.yml`.
"""
from __future__ import annotations

import argparse
import smtplib
from email.message import EmailMessage

MEU_ENDERECO = "mourao.martins@gmail.com"  # so para o envelope; nao ha entrega de volta


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--servidor", default="45.147.251.188", help="IP publico da VM")
    parser.add_argument("--dominio", default="sabemos.studio", help="dominio do correio")
    parser.add_argument("--caixa", default=None, help="caixa local a testar (por omissao: postmaster@<dominio>)")
    parser.add_argument("--helo", default="teste.sabemos.studio", help="nome no HELO")
    args = parser.parse_args()

    caixa = args.caixa or f"postmaster@{args.dominio}"

    print(f"1) entrega de fora para {caixa}")
    msg = EmailMessage()
    msg["Subject"] = "Teste de entrada no servidor de correio do IQ OS"
    msg["From"] = MEU_ENDERECO
    msg["To"] = caixa
    msg.set_content(
        "Mensagem entregue de fora, sem autenticacao, pela porta 25 da VM -- e o que\n"
        "faz um servidor de correio de outro sitio. Se chegou, a entrada funciona.\n"
    )
    with smtplib.SMTP(args.servidor, 25, timeout=30) as servidor:
        servidor.ehlo(args.helo)
        print("   aceite:", servidor.send_message(msg, from_addr=MEU_ENDERECO, to_addrs=[caixa]))

    print("2) retransmissao para fora sem autenticacao (tem de ser recusada)")
    with smtplib.SMTP(args.servidor, 25, timeout=30) as servidor:
        servidor.ehlo(args.helo)
        try:
            servidor.sendmail(MEU_ENDERECO, ["alguem@example.com"], "Subject: teste\n\nx")
            print("   FALHA: aceitou retransmitir -- relay aberto!")
            return 1
        except smtplib.SMTPRecipientsRefused as exc:
            print("   recusado, como deve ser:", list(exc.recipients.values())[0][1].decode())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
