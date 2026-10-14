"""Testes do Correio da plataforma (`/admin/mail/*`).

Cobrem o que é arriscado neste módulo: a composição das mensagens (assinatura,
anexos, encadeamento), a leitura do documento que vai para o índice (assunto,
participantes, anexos, direção), a identificação de uma mensagem no índice
(incluindo pastas com `/` e `::`) e — sobretudo — a **porta**: sem sessão é 401,
com sessão de membro é 403 e só o papel `admin` entra.

Nada aqui fala com um servidor de correio: o IMAP e o SMTP ficam fora, e as
funções que os usam são substituídas. Testa-se o que o módulo decide, que é onde
estavam os erros possíveis.
"""
from __future__ import annotations

import base64
import sys
from email import message_from_bytes
from pathlib import Path
from typing import Any, Dict, List

import pytest
from fastapi.testclient import TestClient

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import api.main as api_main  # noqa: E402
from api import email_service  # noqa: E402
from api import platform_mail_service as service  # noqa: E402
from api.admin_routes import require_admin  # noqa: E402
from api.auth_routes import CurrentSession, UserResponse, require_session  # noqa: E402

CRU = (
    b"From: Maria Silva <maria@fornecedor.pt>\r\n"
    b"To: IQ OS <no-reply@sabemos.studio>\r\n"
    b"Cc: financeiro@fornecedor.pt\r\n"
    b"Subject: =?utf-8?q?Fatura_2026=2F0042_=E2=80=94_maio?=\r\n"
    b"Date: Tue, 05 May 2026 09:31:00 +0100\r\n"
    b"Message-ID: <fatura-42@fornecedor.pt>\r\n"
    b"In-Reply-To: <pedido-7@sabemos.studio>\r\n"
    b"References: <pedido-1@sabemos.studio> <pedido-7@sabemos.studio>\r\n"
    b"MIME-Version: 1.0\r\n"
    b'Content-Type: multipart/mixed; boundary="limite"\r\n'
    b"\r\n"
    b"--limite\r\n"
    b"Content-Type: text/plain; charset=utf-8\r\n"
    b"\r\n"
    b"Segue a fatura de maio.\r\n"
    b"\r\n"
    b"--limite\r\n"
    b"Content-Type: text/html; charset=utf-8\r\n"
    b"\r\n"
    b"<p>Segue a <b>fatura</b> de maio.</p>\r\n"
    b"\r\n"
    b"--limite\r\n"
    b"Content-Type: application/pdf; name=fatura.pdf\r\n"
    b"Content-Disposition: attachment; filename=fatura.pdf\r\n"
    b"Content-Transfer-Encoding: base64\r\n"
    b"\r\n"
    b"JVBERi0xLjQK\r\n"
    b"--limite--\r\n"
)


def _conta(**extra: Any) -> Dict[str, Any]:
    conta = {
        "id": "plataforma",
        "label": "Correio da plataforma",
        "email_address": "no-reply@sabemos.studio",
        "display_name": "IQ OS",
        "username": "no-reply@sabemos.studio",
        "password": "segredo",
        "imap_host": "mail.sabemos.studio",
        "imap_port": 993,
        "imap_security": "ssl",
        "smtp_host": "mail.sabemos.studio",
        "smtp_port": 587,
        "smtp_security": "starttls",
        "signature": "",
        "folders": ["INBOX", "Sent"],
        "enabled": True,
        "source": "env",
    }
    conta.update(extra)
    return conta


# ------------------------------------------------------------------ utilidades
def test_assunto_sem_prefixos_de_resposta() -> None:
    assert service._subject_key("Re: Fwd: Re[2]: Fatura de maio") == "Fatura de maio"
    assert service._subject_key("Fatura de maio") == "Fatura de maio"


def test_fio_da_conversa_prefere_a_raiz_das_referencias() -> None:
    """A resposta entra no mesmo fio da primeira mensagem, não no da última."""
    assert (
        service._thread_key("<fatura-42@x.pt>", "<pedido-7@sabemos.studio>", "<pedido-1@sabemos.studio> <pedido-7@sabemos.studio>", "Re: Fatura")
        == "<pedido-1@sabemos.studio>"
    )
    # Sem referências, o fio é a própria mensagem.
    assert service._thread_key("<nova@x.pt>", "", "", "Olá") == "<nova@x.pt>"
    # Sem identificadores, resta o assunto sem os prefixos.
    assert service._thread_key("", "", "", "Re: Olá") == "assunto:olá"
    assert service._thread_key("", "", "", "   ") == ""


def test_identificador_de_mensagem_aguenta_pastas_com_barras() -> None:
    """O id do índice atravessa `::` e `/` (pastas aninhadas) sem se perder."""
    doc_id = service._doc_id("plataforma", "INBOX/Fornecedores::2026", "42")
    assert doc_id == "plataforma::42::INBOX/Fornecedores::2026"
    assert service._parse_doc_id(doc_id) == ("plataforma", "42", "INBOX/Fornecedores::2026")
    with pytest.raises(service.MailError):
        service._parse_doc_id("sem-separadores")


# --------------------------------------------------------------------- índice
def test_documento_da_mensagem_traz_o_que_a_lista_mostra() -> None:
    documento = service.message_document(_conta(), "INBOX", "42", CRU, b"", "2026-05-05T08:31:00+00:00")

    assert documento["uid"] == "42"
    assert documento["folder"] == "INBOX"
    assert documento["subject"] == "Fatura 2026/0042 — maio"
    assert documento["from_email"] == "maria@fornecedor.pt"
    assert documento["from_name"] == "Maria Silva"
    assert [item["email"] for item in documento["to"]] == ["no-reply@sabemos.studio"]
    assert [item["email"] for item in documento["cc"]] == ["financeiro@fornecedor.pt"]
    assert documento["message_id"] == "<fatura-42@fornecedor.pt>"
    assert documento["thread_key"] == "<pedido-1@sabemos.studio>"
    assert documento["direction"] == "in"
    assert documento["unseen"] is True
    assert documento["has_attachments"] is True
    assert documento["attachments_count"] == 1
    assert documento["attachments"][0]["filename"] == "fatura.pdf"
    assert documento["attachments"][0]["content_type"] == "application/pdf"
    assert "fatura de maio" in documento["snippet"].lower()
    assert "<b>fatura</b>" in documento["body_html"]
    # A data é a do cabeçalho `Date`, não a da chegada ao servidor.
    assert documento["date"].startswith("2026-05-05T0")


def test_documento_marca_saida_e_lida() -> None:
    documento = service.message_document(
        _conta(),
        "Sent",
        "7",
        CRU,
        b"\\Seen \\Answered",
        None,
    )
    assert documento["direction"] == "out"
    assert documento["unseen"] is False
    assert documento["answered"] is True
    assert documento["draft"] is False


def test_resolve_a_pasta_de_enviados_por_alias() -> None:
    disponiveis = [
        {"name": "INBOX", "selectable": True, "sent": False},
        {"name": "Sent Items", "selectable": True, "sent": True},
        {"name": "Trash", "selectable": True},
        {"name": "SemSelecao", "selectable": False, "sent": True},
    ]
    assert service._resolve_folder(disponiveis, "INBOX") == "INBOX"
    assert service._resolve_folder(disponiveis, "Sent") == "Sent Items"
    assert service._resolve_folder(disponiveis, "Junk") is None


def test_anexos_da_mensagem_crua_batem_com_a_lista() -> None:
    """O índice da lista é o índice do descarregamento: saem da mesma leitura."""
    anexos = service._attachment_parts(message_from_bytes(CRU))
    assert len(anexos) == 1
    nome, tipo, conteudo = anexos[0]
    assert nome == "fatura.pdf"
    assert tipo == "application/pdf"
    assert conteudo == b"%PDF-1.4\n"


# ----------------------------------------------------------------------- envio
def test_compor_mensagem_com_assinatura_anexo_e_encadeamento() -> None:
    conta = _conta(signature="IQ OS — Inteligência Financeira")
    mensagem = service.build_message(
        conta,
        {
            "subject": "Re: Fatura 2026/0042",
            "in_reply_to": "<fatura-42@fornecedor.pt>",
            "attachments": [
                {
                    "filename": "recibo.txt",
                    "content_type": "text/plain",
                    "data": base64.b64encode("recebido".encode("utf-8")).decode("ascii"),
                }
            ],
        },
        ["maria@fornecedor.pt"],
        ["financeiro@fornecedor.pt"],
        "Recebido, obrigado.",
        "<p>Recebido, obrigado.</p>",
    )

    assert mensagem["From"] == "IQ OS <no-reply@sabemos.studio>"
    assert mensagem["To"] == "maria@fornecedor.pt"
    assert mensagem["Cc"] == "financeiro@fornecedor.pt"
    assert mensagem["In-Reply-To"] == "<fatura-42@fornecedor.pt>"
    assert mensagem["References"] == "<fatura-42@fornecedor.pt>"
    assert mensagem["Date"] and mensagem["Message-ID"].startswith("<")
    # O domínio sai do remetente, e não do nome do contentor (`<…@34b8cc2b8e02>`),
    # que é o que o `make_msgid` sem domínio escrevia.
    assert mensagem["Message-ID"].endswith("@sabemos.studio>")

    texto = mensagem.get_body(("plain")).get_content()
    assert "Recebido, obrigado." in texto
    assert "IQ OS — Inteligência Financeira" in texto
    html = mensagem.get_body(("html")).get_content()
    assert "<p>Recebido, obrigado.</p>" in html

    anexos = list(mensagem.iter_attachments())
    assert len(anexos) == 1
    assert anexos[0].get_filename() == "recibo.txt"
    assert anexos[0].get_payload(decode=True) == b"recebido"
    # O que se envia é o que se arquiva em Sent: a mensagem tem de ser reconstruível.
    assert message_from_bytes(mensagem.as_bytes())["Subject"] == "Re: Fatura 2026/0042"


def test_compor_mensagem_sem_assinatura_quando_pedido() -> None:
    mensagem = service.build_message(
        _conta(signature="Assinatura"),
        {"subject": "Sem assinatura", "include_signature": False},
        ["a@b.pt"],
        [],
        "Corpo.",
        "",
    )
    assert "Assinatura" not in mensagem.get_body(("plain")).get_content()


def test_enderecos_ignoram_texto_sem_email() -> None:
    assert service._addresses("a@b.pt; c@d.pt ,lixo") == ["a@b.pt", "c@d.pt"]
    assert service._addresses(["a@b.pt", "sem-arroba"]) == ["a@b.pt"]
    assert service._addresses(None) == []


# ----------------------------------------------------------------------- caixas
def test_conta_publica_nunca_devolve_a_palavra_passe() -> None:
    publica = service.public_account(_conta())
    assert "password" not in publica
    assert publica["has_password"] is True
    assert service.public_account(_conta(password=""))["has_password"] is False


def test_normalizar_conta_herda_os_servidores_da_plataforma(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        service,
        "_imap_defaults",
        lambda: {
            "host": "mail.sabemos.studio",
            "port": 993,
            "security": "ssl",
            "smtp": {"host": "mail.sabemos.studio", "port": 587, "security": "starttls", "user": "no-reply@sabemos.studio"},
        },
    )
    conta = service._normalize_account({"email_address": "postmaster@sabemos.studio", "password": "p"})
    assert conta["imap_host"] == "mail.sabemos.studio"
    assert conta["imap_port"] == 993
    assert conta["imap_security"] == "ssl"
    assert conta["smtp_host"] == "mail.sabemos.studio"
    assert conta["folders"] == ["INBOX", "Sent"]
    assert conta["enabled"] is True

    with pytest.raises(service.MailError):
        service._normalize_account({"email_address": "sem-arroba", "password": "p"})
    with pytest.raises(service.MailError):
        service._normalize_account({"email_address": "a@b.pt"})
    with pytest.raises(service.MailError):
        service._normalize_account({"email_address": "a@b.pt", "password": "p", "imap_security": "rasca"})


def test_estado_de_sincronizacao_nao_grava_objetos_em_folders(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regressão: `folders` é `keyword` no índice — o mapa das pastas vai em `state`.

    Guardar o mapa em `folders` fazia o Elasticsearch recusar o documento
    (`failed to parse field [folders] of type [keyword]`) e o marcador
    `last_uid` nunca era gravado: cada sincronização recomeçava do início.
    """
    gravados: List[Dict[str, Any]] = []

    class _Cliente:
        def index(self, **kwargs: Any) -> Dict[str, Any]:
            gravados.append(kwargs["document"])
            return {"result": "created"}

    monkeypatch.setattr(service, "_client", lambda: _Cliente())
    service._save_sync_state("plataforma", folders={"INBOX": {"folder": "INBOX", "last_uid": "42"}})

    assert gravados and gravados[0]["state"]["INBOX"]["last_uid"] == "42"
    assert "folders" not in gravados[0]

    monkeypatch.setattr(
        service,
        "_sync_states",
        lambda: {"plataforma": {"account": "plataforma", "state": {"INBOX": {"last_uid": "42"}}, "last_sync_at": "2026-05-05T08:00:00Z"}},
    )
    estado = service.sync_state("plataforma")
    assert estado["folders"]["INBOX"]["last_uid"] == "42"
    assert estado["last_sync_at"] == "2026-05-05T08:00:00Z"
    assert service.sync_state("outra")["folders"] == {}


# ------------------------------------------------------------------------ rotas
def _sessao(email: str = "prova@exemplo.pt", role: str = "member") -> CurrentSession:
    return CurrentSession(
        user=UserResponse(
            id=f"u-{email}",
            email=email,
            name=email.split("@")[0],
            role=role,
            initials="PR",
            status="active",
            locale="pt-PT",
            timezone="Europe/Lisbon",
        ),
        session_id="s-prova",
        token="t-prova",
    )


def _cliente() -> TestClient:
    return TestClient(api_main.app, base_url="http://prova")


def test_correio_da_plataforma_exige_sessao() -> None:
    resposta = _cliente().get("/admin/mail/meta")
    assert resposta.status_code == 401


def test_correio_da_plataforma_exige_papel_admin() -> None:
    """Um membro autenticado não entra no correio da plataforma."""
    api_main.app.dependency_overrides[require_session] = _sessao
    try:
        resposta = _cliente().get("/admin/mail/meta")
    finally:
        api_main.app.dependency_overrides.pop(require_session, None)
    assert resposta.status_code == 403


@pytest.fixture
def admin() -> Any:
    """Sessão de administrador, injectada por cima do `require_admin`."""
    api_main.app.dependency_overrides[require_admin] = lambda: _sessao("admin@exemplo.pt", role="admin")
    try:
        yield _cliente()
    finally:
        api_main.app.dependency_overrides.pop(require_admin, None)


def test_meta_para_administrador(admin: TestClient) -> None:
    resposta = admin.get("/admin/mail/meta")
    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert "defaults" in corpo and "imap_host" in corpo["defaults"]
    assert corpo["limits"]["initial_batch"] > 0
    assert isinstance(corpo["es"]["available"], bool)


def test_lista_de_caixas_sem_segredos(admin: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "accounts", lambda: [_conta(), _conta(id="dmarc", email_address="dmarc@sabemos.studio")])
    resposta = admin.get("/admin/mail/accounts")
    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["total"] == 2
    assert all("password" not in item for item in corpo["items"])
    assert corpo["items"][0]["has_password"] is True


def test_lista_de_mensagens_entrega_os_filtros(admin: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    recebidos: List[Dict[str, Any]] = []

    def _lista(params: Dict[str, Any]) -> Dict[str, Any]:
        recebidos.append(params)
        return {"source": "elasticsearch", "total": 0, "items": [], "facets": {}}

    monkeypatch.setattr(service, "list_messages", _lista)
    resposta = admin.get(
        "/admin/mail/messages",
        params={"account": "plataforma", "folder": "INBOX", "q": "fatura", "unseen": "true", "limit": 25, "offset": 50},
    )
    assert resposta.status_code == 200, resposta.text
    assert recebidos and recebidos[0]["q"] == "fatura"
    assert recebidos[0]["account"] == "plataforma"
    assert recebidos[0]["unseen"] is True
    assert recebidos[0]["limit"] == 25
    assert recebidos[0]["offset"] == 50
    assert recebidos[0]["exclude_drafts"] is True


def test_abrir_mensagem_com_pasta_aninhada(admin: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """O identificador com `/` e `::` chega inteiro à rota (conversor `path`).

    As operações são simuladas: o que se prova aqui é que o identificador não se
    parte no caminho do URL — o resto é IMAP, que não pertence a este teste.
    """
    vistos: Dict[str, List[Any]] = {"abrir": [], "flags": [], "mover": [], "apagar": []}

    def _abrir(doc_id: str, *, mark_read: bool = True) -> Dict[str, Any]:
        vistos["abrir"].append(doc_id)
        return {"message": {"subject": "Fatura"}, "account": {"id": "plataforma"}, "source": "imap", "stale": False}

    monkeypatch.setattr(service, "get_message", _abrir)
    monkeypatch.setattr(service, "set_flags", lambda doc_id, action: vistos["flags"].append((doc_id, action)) or {"updated": True})
    monkeypatch.setattr(service, "move_message", lambda doc_id, target: vistos["mover"].append((doc_id, target)) or {"moved": True})
    monkeypatch.setattr(service, "delete_message", lambda doc_id: vistos["apagar"].append(doc_id) or {"deleted": True})

    doc_id = service._doc_id("plataforma", "INBOX/Fornecedores", "42")
    resposta = admin.get(f"/admin/mail/messages/{doc_id}", params={"mark_read": "false"})
    assert resposta.status_code == 200, resposta.text
    assert vistos["abrir"] == [doc_id]
    assert resposta.json()["message"]["subject"] == "Fatura"

    assert admin.post(f"/admin/mail/messages/{doc_id}/flags", json={"action": "unread"}).status_code == 200
    assert admin.post(f"/admin/mail/messages/{doc_id}/move", json={"target": "Archive"}).status_code == 200
    assert admin.delete(f"/admin/mail/messages/{doc_id}").status_code == 200

    assert vistos["flags"] == [(doc_id, "unread")]
    assert vistos["mover"] == [(doc_id, "Archive")]
    assert vistos["apagar"] == [doc_id]


def test_anexo_descarregado_com_nome_acentuado(admin: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    vistos: List[Any] = []

    def _anexo(doc_id: str, index: int) -> Any:
        vistos.append((doc_id, index))
        return ("fatura — maio.pdf", "application/pdf", b"%PDF-1.4\n")

    monkeypatch.setattr(service, "attachment", _anexo)
    doc_id = service._doc_id("plataforma", "INBOX", "42")
    resposta = admin.get(f"/admin/mail/messages/{doc_id}/attachments/0")

    assert resposta.status_code == 200, resposta.text
    assert vistos == [(doc_id, 0)]
    assert resposta.content == b"%PDF-1.4\n"
    assert resposta.headers["content-type"].startswith("application/pdf")
    # Nome não-ASCII: vai também em `filename*`, que é o que o browser respeita.
    assert "filename*=UTF-8''" in resposta.headers["content-disposition"]


def test_mover_sem_destino_e_recusado(admin: TestClient) -> None:
    doc_id = service._doc_id("plataforma", "INBOX", "1")
    resposta = admin.post(f"/admin/mail/messages/{doc_id}/move", json={})
    assert resposta.status_code == 422


def test_sincronizacao_em_curso_devolve_conflito(admin: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def _sync(account_id: Any = None, *, full: bool = False) -> Dict[str, Any]:
        raise service.MailError("Já está uma sincronização a decorrer.", status=409)

    monkeypatch.setattr(service, "sync", _sync)
    resposta = admin.post("/admin/mail/sync", json={})
    assert resposta.status_code == 409


def test_sincronizacao_devolve_contagens(admin: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        service,
        "sync",
        lambda account_id=None, *, full=False: {"indexed": 3, "accounts": [{"id": "plataforma", "indexed": 3}], "errors": []},
    )
    resposta = admin.post("/admin/mail/sync", json={"full": True})
    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["indexed"] == 3


def test_envio_devolve_recibo_e_erro_tratado(admin: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        service,
        "send",
        lambda payload: {
            "sent": True,
            "account": {"id": "plataforma"},
            "message_id": "<abc@x>",
            "subject": payload.get("subject"),
            "to": payload.get("to"),
            "appended_to_sent": True,
            "indexed": True,
        },
    )
    resposta = admin.post("/admin/mail/send", json={"subject": "Olá", "to": ["a@b.pt"], "body_text": "Corpo"})
    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["sent"] is True

    def _falha(payload: Dict[str, Any]) -> Dict[str, Any]:
        raise service.MailError("O envio falhou: servidor recusou.", status=502)

    monkeypatch.setattr(service, "send", _falha)
    resposta = admin.post("/admin/mail/send", json={"subject": "Olá", "to": ["a@b.pt"], "body_text": "Corpo"})
    assert resposta.status_code == 502
    assert "recusou" in resposta.json()["detail"]


def test_apagar_conta_da_plataforma_e_recusado(admin: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def _apagar(account_id: str) -> Dict[str, Any]:
        raise service.MailError("A caixa da plataforma é derivada do SMTP e não se apaga.", status=409)

    monkeypatch.setattr(service, "delete_account", _apagar)
    resposta = admin.delete("/admin/mail/accounts/plataforma")
    assert resposta.status_code == 409


def test_identificador_de_mensagem_no_dominio_do_remetente() -> None:
    """O `make_msgid` sem domínio escrevia o nome do contentor (`<…@34b8cc2b8e02>`).

    É o mesmo identificador para todo o correio da plataforma (email transacional,
    Correio da plataforma e caixas do webmail): uma só regra, num só sítio.
    """
    assert email_service.make_message_id("suporte@sabemos.studio").endswith("@sabemos.studio>")
    assert email_service.make_message_id("Suporte <suporte@sabemos.studio>").endswith("@sabemos.studio>")
    assert email_service.make_message_id("  no-reply@sabemos.studio  ").endswith("@sabemos.studio>")
    # Sem domínio utilizável, o cabeçalho sai na mesma: o RFC 5322 exige-o, e a
    # falta dele é pontuação de spam — pior do que o nome da máquina.
    for invalido in ("", "sem-dominio", "a@localhost", "...@.", "a@b.pt>"):
        assert email_service.make_message_id(invalido).startswith("<")
