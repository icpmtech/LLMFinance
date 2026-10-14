"""Chaves de serviços externos, guardadas no Elasticsearch e editáveis na administração.

A plataforma usa serviços pagos que precisam de credenciais (a **2captcha**
resolve o reCAPTCHA da recolha societária do Ministério da Justiça). Essas chaves
vinham de variáveis de ambiente — exportadas pelo lançador — ou do `.env` do
projeto; como o ambiente depende de *como* a API foi arrancada, reiniciá-la por
outro caminho deixava-a sem chave e a recolha falhava com «API key da 2captcha em
falta».

Passam a viver (também) no Elasticsearch, num único documento de
`finance_settings` (`id = service-keys`), editável em
**Administração → Chaves e integrações**:

* o valor é gravado no índice e nunca devolvido em claro pela API (só mascarado);
* a resolução de uma chave é **parâmetro → índice → variável de ambiente → `.env`**,
  pelo que alterar a chave na interface passa a valer imediatamente, sem reiniciar
  o backend, e o `.env`/ambiente continuam a servir de fallback.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)

DOC_ID = "service-keys"
KIND = "service-keys"

#: `.env` do projeto (fallback final, tal como o resto da solução).
_ENV_FILES = (
    Path(__file__).resolve().parents[1] / ".env",
    Path(__file__).resolve().parents[2] / ".env",
)

#: Catálogo das chaves que a administração pode gerir.
CHAVES: List[Dict[str, Any]] = [
    {
        "id": "twocaptcha_api_key",
        "label": "2captcha — API key",
        "grupo": "Recolha societária (MJ)",
        "descricao": (
            "Resolve o reCAPTCHA v2 do portal das publicações de atos societários do Ministério da Justiça. "
            "Sem chave, a recolha societária (e as passagens que dependem dela) falha."
        ),
        "env": ["TWOCAPTCHA_API_KEY", "TWOCAPTCHA_KEY"],
        "onde": "2captcha.com → Painel → «API key»",
        "secreto": True,
        "exemplo": "32 caracteres (ex.: 6032…1d6c)",
        "testavel": True,
    },
    {
        "id": "twocaptcha_proxy",
        "label": "2captcha / portal MJ — proxy (opcional)",
        "grupo": "Recolha societária (MJ)",
        "descricao": (
            "Proxy HTTP(S) usado nos pedidos ao portal do MJ e à 2captcha quando o trabalho não indica outro."
        ),
        "env": ["TWOCAPTCHA_PROXY", "SOCIAL_PROXY"],
        "onde": "Fornecedor de proxy (ex.: http://utilizador:password@host:porta)",
        "secreto": True,
        "exemplo": "http://utilizador:password@host:porta",
        "testavel": False,
    },
    {
        "id": "smtp_host",
        "label": "Servidor SMTP — hostname",
        "grupo": "Email transacional (registos e trial)",
        "descricao": (
            "Servidor de envio de email transacional. Necessário para enviar a confirmação de aprovação "
            "e o aviso de início do trial de 5 dias. Sem este valor, os emails não são enviados."
        ),
        "env": ["SMTP_HOST"],
        "onde": "Servidor de email (ex.: smtp.gmail.com, smtp.office365.com, mail.sapo.pt)",
        "secreto": False,
        "exemplo": "smtp.gmail.com",
        "testavel": False,
    },
    {
        "id": "smtp_port",
        "label": "Servidor SMTP — porta",
        "grupo": "Email transacional (registos e trial)",
        "descricao": "Porta do servidor SMTP. Padrão: 587 (STARTTLS) ou 465 (SSL).",
        "env": ["SMTP_PORT"],
        "onde": "Porta do servidor SMTP",
        "secreto": False,
        "exemplo": "587",
        "default": "587",
        "testavel": False,
    },
    {
        "id": "smtp_security",
        "label": "Servidor SMTP — segurança",
        "grupo": "Email transacional (registos e trial)",
        "descricao": "starttls | ssl | plain. Padrão: starttls.",
        "env": ["SMTP_SECURITY"],
        "onde": "starttls | ssl | plain",
        "secreto": False,
        "exemplo": "starttls",
        "default": "starttls",
        "testavel": False,
    },
    {
        "id": "smtp_user",
        "label": "Servidor SMTP — utilizador",
        "grupo": "Email transacional (registos e trial)",
        "descricao": "Endereço de email ou nome de utilizador para autenticar no SMTP.",
        "env": ["SMTP_USER"],
        "onde": "Conta de email de envio",
        "secreto": True,
        "exemplo": "noreply@sabemos.studio",
        "testavel": False,
    },
    {
        "id": "smtp_password",
        "label": "Servidor SMTP — palavra-passe",
        "grupo": "Email transacional (registos e trial)",
        "descricao": "Palavra-passe ou palavra-passe de aplicação do utilizador SMTP.",
        "env": ["SMTP_PASSWORD", "SMTP_PASS"],
        "onde": "Palavra-passe da conta de envio",
        "secreto": True,
        "exemplo": "••••••••",
        "testavel": False,
    },
    {
        "id": "smtp_from",
        "label": "Servidor SMTP — remetente (From)",
        "grupo": "Email transacional (registos e trial)",
        "descricao": "Endereço de remetente dos emails transacionais. Padrão: SMTP_USER.",
        "env": ["SMTP_FROM"],
        "onde": "Endereço remetente",
        "secreto": False,
        "exemplo": "IQ OS <noreply@sabemos.studio>",
        "testavel": False,
    },
    {
        "id": "mbway_api_key",
        "label": "MB Way — API key (IFTThenPay)",
        "grupo": "Pagamentos e subscrições",
        "descricao": "Chave de API do IFTThenPay para pedidos MB Way automáticos. Sem valor, o pagamento por MB Way fica em modo manual.",
        "env": ["MBWAY_API_KEY"],
        "onde": "ifthenpay.com → Área cliente → MB Way Key",
        "secreto": True,
        "exemplo": "32 caracteres",
        "testavel": False,
    },
    {
        "id": "mbway_api_url",
        "label": "MB Way — URL da API",
        "grupo": "Pagamentos e subscrições",
        "descricao": "URL base do serviço IFTThenPay MB Way. Padrão: https://mbway.ifthenpay.com/ifthenpaymbw.ashx",
        "env": ["MBWAY_API_URL"],
        "onde": "URL fornecida pelo IFTThenPay",
        "secreto": False,
        "exemplo": "https://mbway.ifthenpay.com/ifthenpaymbw.ashx",
        "default": "https://mbway.ifthenpay.com/ifthenpaymbw.ashx",
        "testavel": False,
    },
    {
        "id": "mbway_number",
        "label": "MB Way / Transferência — número de telemóvel",
        "grupo": "Pagamentos e subscrições",
        "descricao": "Teclado associado à conta para transferências MB Way manuais.",
        "env": ["MBWAY_NUMBER"],
        "onde": "Número de telemóvel para MB Way",
        "secreto": False,
        "exemplo": "919520386",
        "testavel": False,
    },
    {
        "id": "transfer_iban",
        "label": "Transferência — IBAN",
        "grupo": "Pagamentos e subscrições",
        "descricao": "IBAN para onde os clientes devem transferir o valor da subscrição.",
        "env": ["TRANSFER_IBAN"],
        "onde": "IBAN da conta da empresa",
        "secreto": False,
        "exemplo": "PT50 0002 0123 1234 5678 9015 4",
        "testavel": False,
    },
    {
        "id": "stripe_secret_key",
        "label": "Stripe — secret key",
        "grupo": "Pagamentos e subscrições",
        "descricao": "Chave secreta da conta Stripe (começa por sk_live_ ou sk_test_).",
        "env": ["STRIPE_SECRET_KEY"],
        "onde": "Stripe Dashboard → Developers → API keys",
        "secreto": True,
        "exemplo": "sk_test_...",
        "testavel": False,
    },
    {
        "id": "paypal_client_id",
        "label": "PayPal — client ID",
        "grupo": "Pagamentos e subscrições",
        "descricao": "Client ID da aplicação PayPal (modo sandbox ou live).",
        "env": ["PAYPAL_CLIENT_ID"],
        "onde": "PayPal Developer Dashboard → App credentials",
        "secreto": True,
        "exemplo": "AaBbCc...",
        "testavel": False,
    },
    {
        "id": "paypal_client_secret",
        "label": "PayPal — client secret",
        "grupo": "Pagamentos e subscrições",
        "descricao": "Client secret da aplicação PayPal.",
        "env": ["PAYPAL_CLIENT_SECRET"],
        "onde": "PayPal Developer Dashboard → App credentials",
        "secreto": True,
        "exemplo": "••••••••",
        "testavel": False,
    },
    {
        "id": "paypal_base_url",
        "label": "PayPal — URL base",
        "grupo": "Pagamentos e subscrições",
        "descricao": "https://api-m.sandbox.paypal.com (testes) ou https://api-m.paypal.com (produção).",
        "env": ["PAYPAL_BASE_URL"],
        "onde": "Sandbox ou produção PayPal",
        "secreto": False,
        "exemplo": "https://api-m.sandbox.paypal.com",
        "default": "https://api-m.sandbox.paypal.com",
        "testavel": False,
    },
    {
        "id": "paypal_webhook_id",
        "label": "PayPal — id do webhook",
        "grupo": "Pagamentos e subscrições",
        "descricao": (
            "Identificador do webhook criado na aplicação PayPal (ex.: 8PT597110X687430LKGECATA). "
            "Sem ele, o PayPal não consegue notificar a plataforma e os webhooks são recusados — os "
            "pagamentos continuam a ser confirmados pela captura no regresso do cliente."
        ),
        "env": ["PAYPAL_WEBHOOK_ID"],
        "onde": "PayPal Developer → aplicação → Webhooks → Webhook ID",
        "secreto": False,
        "exemplo": "8PT597110X687430LKGECATA",
        "testavel": False,
    },
    {
        "id": "stripe_webhook_secret",
        "label": "Stripe — segredo de assinatura do webhook",
        "grupo": "Pagamentos e subscrições",
        "descricao": (
            "Segredo `whsec_…` que valida a assinatura dos eventos do Stripe. É obrigatório para aceitar "
            "webhooks: sem ele a plataforma recusa-os, em vez de ativar subscrições com base em pedidos "
            "não verificados."
        ),
        "env": ["STRIPE_WEBHOOK_SECRET"],
        "onde": "Stripe Dashboard → Developers → Webhooks → Signing secret",
        "secreto": True,
        "exemplo": "whsec_…",
        "testavel": False,
    },
    {
        "id": "mail_imap_host",
        "label": "Correio da plataforma — servidor IMAP",
        "grupo": "Correio da plataforma (Administração → Correio)",
        "descricao": (
            "Servidor onde a aplicação Correio da plataforma lê as caixas do domínio "
            "(no-reply@, postmaster@, dmarc@…). Por omissão é o mesmo servidor do email "
            "transacional — o Docker Mailserver serve SMTP e IMAP na mesma máquina."
        ),
        "env": ["MAIL_IMAP_HOST", "PLATFORM_MAIL_IMAP_HOST"],
        "onde": "Servidor de correio da plataforma (ex.: mail.exemplo.pt)",
        "secreto": False,
        "exemplo": "mail.exemplo.pt",
        "testavel": False,
    },
    {
        "id": "mail_imap_port",
        "label": "Correio da plataforma — porta IMAP",
        "grupo": "Correio da plataforma (Administração → Correio)",
        "descricao": "Porta do IMAP. Padrão: 993 (SSL) ou 143 (STARTTLS).",
        "env": ["MAIL_IMAP_PORT", "PLATFORM_MAIL_IMAP_PORT"],
        "onde": "Porta do servidor IMAP",
        "secreto": False,
        "exemplo": "993",
        "default": "993",
        "testavel": False,
    },
    {
        "id": "mail_imap_security",
        "label": "Correio da plataforma — segurança do IMAP",
        "grupo": "Correio da plataforma (Administração → Correio)",
        "descricao": "ssl | starttls | plain. Padrão: ssl (porta 993).",
        "env": ["MAIL_IMAP_SECURITY", "PLATFORM_MAIL_IMAP_SECURITY"],
        "onde": "ssl | starttls | plain",
        "secreto": False,
        "exemplo": "ssl",
        "default": "ssl",
        "testavel": False,
    },
]

CHAVE_BY_ID: Dict[str, Dict[str, Any]] = {chave["id"]: chave for chave in CHAVES}


# ---------------------------------------------------------------------------
# Acesso ao índice
# ---------------------------------------------------------------------------

def _client() -> Any:
    """Cliente Elasticsearch, criando o índice de definições se for preciso."""
    from api.elasticsearch_client import ensure_indices, get_es_client

    cliente = get_es_client()
    if cliente is None:
        raise RuntimeError("Elasticsearch indisponível: não é possível ler/gravar as chaves.")
    ensure_indices(cliente)
    return cliente


def _ler_documento() -> Dict[str, Any]:
    from api.elasticsearch_client import SETTINGS_INDEX

    cliente = _client()
    if not cliente.exists(index=SETTINGS_INDEX, id=DOC_ID):
        return {}
    try:
        return cliente.get(index=SETTINGS_INDEX, id=DOC_ID).get("_source") or {}
    except Exception as exc:  # noqa: BLE001 - documento ilegível não pode travar o arranque
        logger.warning("Chaves de serviços ilegíveis no índice: %s", exc)
        return {}


def valores_guardados() -> Dict[str, str]:
    """Valores guardados no índice (só as chaves conhecidas e não vazias)."""
    payload = _ler_documento().get("payload") or {}
    chaves = payload.get("keys") if isinstance(payload.get("keys"), dict) else payload
    if not isinstance(chaves, dict):
        return {}
    return {str(k): str(v) for k, v in chaves.items() if str(k) in CHAVE_BY_ID and str(v).strip()}


def guardar(valores: Dict[str, Optional[str]], *, utilizador: Optional[str] = None) -> Dict[str, Any]:
    """Grava (ou remove, com valor vazio) chaves no índice.

    Só as chaves do catálogo são aceites; um valor vazio **remove** a chave, o que
    devolve o serviço ao fallback (ambiente/`.env`).
    """
    from api.elasticsearch_client import SETTINGS_INDEX

    atuais = valores_guardados()
    alteradas: List[str] = []
    removidas: List[str] = []
    for chave, valor in (valores or {}).items():
        if chave not in CHAVE_BY_ID:
            raise ValueError(f"Chave desconhecida: {chave}")
        limpo = (valor or "").strip()
        if limpo:
            if atuais.get(chave) != limpo:
                alteradas.append(chave)
            atuais[chave] = limpo
        elif chave in atuais:
            atuais.pop(chave)
            removidas.append(chave)

    cliente = _client()
    documento = {
        "kind": KIND,
        "id": DOC_ID,
        "payload": {"keys": atuais},
        "updated_at": _agora(),
        "updated_by": utilizador or "administração",
    }
    cliente.index(index=SETTINGS_INDEX, id=DOC_ID, document=documento, refresh=True)
    return {
        "alteradas": alteradas,
        "removidas": removidas,
        "total": len(atuais),
        "updated_at": documento["updated_at"],
        "updated_by": documento["updated_by"],
    }


# ---------------------------------------------------------------------------
# Resolução de chaves
# ---------------------------------------------------------------------------

def _do_env_file(nomes: Iterable[str]) -> Optional[str]:
    for caminho in _ENV_FILES:
        if not caminho.exists():
            continue
        try:
            for linha in caminho.read_text(encoding="utf-8", errors="ignore").splitlines():
                limpa = linha.strip()
                if not limpa or limpa.startswith("#") or "=" not in limpa:
                    continue
                chave, _, valor = limpa.partition("=")
                if chave.strip() in tuple(nomes):
                    valor = valor.strip().strip("'\"")
                    if valor:
                        return valor
        except OSError:  # pragma: no cover - ficheiro ilegível não pode travar
            continue
    return None


def origem(chave_id: str) -> Dict[str, Any]:
    """Onde está a chave neste momento: índice, ambiente, `.env`, padrão ou lado nenhum."""
    chave = CHAVE_BY_ID.get(chave_id)
    if not chave:
        raise ValueError(f"Chave desconhecida: {chave_id}")

    guardado = valores_guardados().get(chave_id)
    if guardado:
        return {"origem": "indice", "valor": guardado}
    for nome in chave.get("env") or []:
        valor = (os.environ.get(nome) or "").strip()
        if valor:
            return {"origem": "ambiente", "valor": valor, "variavel": nome}
    valor = _do_env_file(chave.get("env") or [])
    if valor:
        return {"origem": "env_file", "valor": valor}
    # Há chaves cujo valor por omissão já é o correto (porta, segurança, URL base):
    # a integração funciona sem configuração, por isso não podem aparecer como por definir.
    if chave.get("default"):
        return {"origem": "padrao", "valor": chave["default"]}
    return {"origem": "ausente", "valor": None}


def resolver(chave_id: str, valor_explicito: Optional[str] = None) -> Optional[str]:
    """Valor efetivo de uma chave: parâmetro → índice → ambiente → `.env`."""
    if valor_explicito and str(valor_explicito).strip():
        return str(valor_explicito).strip()
    if chave_id not in CHAVE_BY_ID:
        return None
    try:
        encontrado = origem(chave_id)
    except Exception as exc:  # noqa: BLE001 - sem Elasticsearch ainda há ambiente/`.env`
        logger.debug("Resolução da chave %s pelo índice falhou: %s", chave_id, exc)
        encontrado = {}
    return encontrado.get("valor")


def _mascarar(valor: Optional[str]) -> Optional[str]:
    if not valor:
        return None
    if len(valor) <= 6:
        return "•" * len(valor)
    return f"{valor[:4]}…{valor[-4:]} ({len(valor)} caracteres)"


def estado() -> Dict[str, Any]:
    """Estado (mascarado) de todas as chaves, para a página de administração."""
    documento = _ler_documento()
    itens: List[Dict[str, Any]] = []
    for chave in CHAVES:
        try:
            encontrado = origem(chave["id"])
        except Exception as exc:  # noqa: BLE001
            encontrado = {"origem": "indisponivel", "valor": None, "erro": str(exc)}
        itens.append(
            {
                **{k: v for k, v in chave.items()},
                "definida": bool(encontrado.get("valor")),
                "origem": encontrado.get("origem"),
                "variavel": encontrado.get("variavel"),
                "valor_mascarado": _mascarar(encontrado.get("valor")) if chave.get("secreto") else encontrado.get("valor"),
                "erro": encontrado.get("erro"),
            }
        )
    return {
        "index": "finance_settings",
        "doc_id": DOC_ID,
        "chaves": itens,
        "atualizado_em": documento.get("updated_at"),
        "atualizado_por": documento.get("updated_by"),
        "notas": (
            "As chaves ficam guardadas no Elasticsearch (documento `service-keys` de `finance_settings`) e são "
            "usadas imediatamente pela recolha; o ambiente, o `.env` de `finance-llm/` e o valor por omissão da "
            "aplicação servem de fallback, por essa ordem."
        ),
    }


# ---------------------------------------------------------------------------
# Teste de uma chave
# ---------------------------------------------------------------------------

def testar(chave_id: str) -> Dict[str, Any]:
    """Testa a chave junto do fornecedor (hoje: saldo da conta 2captcha)."""
    if chave_id != "twocaptcha_api_key":
        return {"ok": False, "mensagem": "Esta chave não tem teste automático."}
    api_key = resolver(chave_id)
    if not api_key:
        return {"ok": False, "mensagem": "Chave não definida (índice, ambiente ou `.env`)."}

    import requests

    try:
        resposta = requests.get(
            "https://2captcha.com/res.php",
            params={"key": api_key, "action": "getbalance", "json": 1},
            timeout=30,
        )
        dados = resposta.json() if resposta.headers.get("content-type", "").startswith("application/json") else {}
    except Exception as exc:  # noqa: BLE001 - falha de rede não é chave inválida
        return {"ok": False, "mensagem": f"Sem resposta da 2captcha: {exc}"}

    if dados.get("status") == 1:
        return {
            "ok": True,
            "mensagem": f"Chave válida. Saldo da conta: {dados.get('request')} USD.",
            "saldo": dados.get("request"),
        }
    return {"ok": False, "mensagem": f"A 2captcha recusou a chave: {dados.get('request') or resposta.text[:120]}"}


def _agora() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
