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
    """Onde está a chave neste momento: índice, ambiente, `.env` ou lado nenhum."""
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
            "usadas imediatamente pela recolha; o ambiente e o `.env` de `finance-llm/` servem de fallback."
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
