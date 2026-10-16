"""Captcha dos formulários públicos.

Sem serviço externo, sem JavaScript e sem guardar estado: o desafio é uma conta
curta escrita por palavras («Quanto dá sete mais cinco?») e a resposta viaja com
um **testemunho assinado**. O testemunho leva só um nonce e as datas; a
assinatura é feita *sobre a resposta*, por isso quem a não sabe não a pode
adivinhar a partir do testemunho — e o servidor confere-a recalculando a
assinatura com a resposta que recebeu.

Não é uma barreira forte (nada que se resolva a ler é) e não vale a pena
apresentá-la como tal: o que trava é a soma de três coisas — responder dentro do
prazo, não poder repetir o testemunho noutro sítio e, do lado de quem recebe, o
limite de pedidos por IP que já existe nos formulários.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from typing import Any, Callable, Dict, Optional, Tuple

from api import auth_service

logger = logging.getLogger(__name__)

#: Nome do campo da resposta. O testemunho vai em `captcha_token`.
CAMPO_RESPOSTA = "captcha"
CAMPO_TESTEMUNHO = "captcha_token"

#: Quanto tempo um desafio continua a valer (a pessoa pode demorar a escrever).
VALIDADE_SEGUNDOS = 45 * 60
#: Um desafio respondido num instante não foi lido por ninguém.
DEMORA_MINIMA_SEGUNDOS = 2

#: Operandos por extenso: a pergunta lê-se bem em voz alta (e num leitor de
#: ecrã) e não se resolve com a expressão regular que apanha «7 + 5».
_EXTENSO: Dict[int, str] = {
    1: "um",
    2: "dois",
    3: "três",
    4: "quatro",
    5: "cinco",
    6: "seis",
    7: "sete",
    8: "oito",
    9: "nove",
    10: "dez",
    11: "onze",
    12: "doze",
    13: "treze",
    14: "catorze",
    15: "quinze",
    16: "dezasseis",
    17: "dezassete",
    18: "dezoito",
}
_POR_EXTENSO = {palavra: numero for numero, palavra in _EXTENSO.items()}

#: Operações: (palavra, cálculo). Na subtração o primeiro operando é sempre
#: maior, para o resultado nunca ser negativo nem zero.
_OPERACOES: Tuple[Tuple[str, Callable[[int, int], int]], ...] = (
    ("mais", lambda a, b: a + b),
    ("menos", lambda a, b: a - b),
)


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(valor: str) -> bytes:
    return base64.urlsafe_b64decode(valor + "=" * (-len(valor) % 4))


def _assinar(corpo: str, resposta: str) -> str:
    """Assinatura do testemunho **com a resposta**: sem ela não se verifica nada."""
    chave = auth_service._auth_secret()  # noqa: SLF001 - segredo único da plataforma
    return _b64e(hmac.new(chave, f"{corpo}.{resposta}".encode("utf-8"), hashlib.sha256).digest())


def normalizar(valor: Any) -> str:
    """Resposta como número em algarismos: aceita «12», « 12 » ou «doze»."""
    texto = str(valor or "").strip().lower()
    if texto in _POR_EXTENSO:
        return str(_POR_EXTENSO[texto])
    return texto


def desafio() -> Dict[str, str]:
    """Novo desafio: a pergunta que se mostra e o testemunho que a acompanha."""
    agora = int(time.time())
    primeiro, segundo = secrets.randbelow(9) + 1, secrets.randbelow(9) + 1
    palavra, calcular = _OPERACOES[secrets.randbelow(len(_OPERACOES))]
    if palavra == "menos" and primeiro < segundo:
        primeiro, segundo = segundo, primeiro
    if palavra == "menos" and primeiro == segundo:
        segundo = max(1, primeiro - 1)
    corpo = _b64e(
        json.dumps(
            {"n": secrets.token_hex(8), "iat": agora, "exp": agora + VALIDADE_SEGUNDOS},
            separators=(",", ":"),
        ).encode("utf-8")
    )
    return {
        "pergunta": f"Quanto dá {_EXTENSO[primeiro]} {palavra} {_EXTENSO[segundo]}?",
        "token": f"{corpo}.{_assinar(corpo, str(calcular(primeiro, segundo)))}",
    }


def verificar(resposta: Any, token: Any) -> bool:
    """O testemunho é nosso, está no prazo e a resposta confere?"""
    texto = str(token or "")
    if texto.count(".") != 1:
        return False
    corpo, assinatura = texto.split(".", 1)
    try:
        dados = json.loads(_b64d(corpo).decode("utf-8"))
        emita = int(dados.get("iat") or 0)
        expira = int(dados.get("exp") or 0)
    except (ValueError, TypeError, UnicodeDecodeError, AttributeError):
        return False
    agora = time.time()
    if agora > expira or agora - emita < DEMORA_MINIMA_SEGUNDOS:
        return False
    numero = normalizar(resposta)
    if not numero.isdigit() or len(numero) > 4:
        return False
    # Assinatura refeita com a resposta recebida: só confere se for a certa.
    return hmac.compare_digest(_assinar(corpo, str(int(numero))), assinatura)


def erro(resposta: Any = None, token: Any = None) -> Optional[str]:
    """Mensagem de erro para quem falhou o desafio, ou `None` se passou.

    Devolve texto (e não um booleano) porque é isto que o formulário mostra ao
    lado do campo: a mesma frase que o `verificar` recusa explicada a quem lê.
    """
    if verificar(resposta, token):
        return None
    if not str(resposta or "").strip():
        return "Responda ao desafio, para confirmarmos que é uma pessoa."
    return "A resposta ao desafio não confere. Responda outra vez."
