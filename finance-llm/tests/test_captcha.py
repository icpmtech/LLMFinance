"""Testes do captcha dos formulários públicos.

O captcha é próprio (sem serviço externo) e sem estado: o testemunho é uma
assinatura **sobre a resposta**, por isso o que aqui se fixa é que a resposta
certa passa, a errada não, o testemunho não diz a resposta, e que nada disto
depende de JavaScript — o mesmo desafio serve uma página HTML e um `fetch`.
"""

from __future__ import annotations

import base64
import json
import time

import pytest

from api import captcha

#: O que uma pessoa lê na pergunta. Deliberadamente escrito aqui de novo: o
#: teste resolve o desafio como quem lê, em vez de perguntar a resposta ao
#: próprio módulo.
_NUMEROS = {
    "um": 1,
    "dois": 2,
    "três": 3,
    "quatro": 4,
    "cinco": 5,
    "seis": 6,
    "sete": 7,
    "oito": 8,
    "nove": 9,
    "dez": 10,
    "onze": 11,
    "doze": 12,
    "treze": 13,
    "catorze": 14,
    "quinze": 15,
    "dezasseis": 16,
    "dezassete": 17,
    "dezoito": 18,
}


def resolver(pergunta: str) -> str:
    """Resolve o desafio como uma pessoa: lê a pergunta e faz a conta."""
    palavras = pergunta.rstrip("?").split()
    assert palavras[0] == "Quanto" and palavras[1] == "dá", pergunta
    primeiro, operacao, segundo = palavras[2], palavras[3], palavras[4]
    conta = _NUMEROS[primeiro] + _NUMEROS[segundo] if operacao == "mais" else _NUMEROS[primeiro] - _NUMEROS[segundo]
    return str(conta)


def corpo_do_testemunho(token: str) -> dict:
    """O que vai dentro do testemunho (e o que lá **não** vai)."""
    corpo = token.split(".", 1)[0]
    return json.loads(base64.urlsafe_b64decode(corpo + "=" * (-len(corpo) % 4)).decode("utf-8"))


@pytest.fixture()
def sem_espera(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sem o compasso de dois segundos: um teste não deve dormir para responder."""
    monkeypatch.setattr(captcha, "DEMORA_MINIMA_SEGUNDOS", 0)


def test_resposta_certa_passa(sem_espera: None) -> None:
    desafio = captcha.desafio()

    assert captcha.erro(resolver(desafio["pergunta"]), desafio["token"]) is None
    assert captcha.verificar(resolver(desafio["pergunta"]), desafio["token"]) is True


def test_resposta_certa_por_extenso_tambem_passa(sem_espera: None) -> None:
    """Quem escreve «doze» respondeu certo (e é o que um leitor de ecrã sugere)."""
    desafio = captcha.desafio()
    conta = int(resolver(desafio["pergunta"]))

    assert captcha.verificar(captcha._EXTENSO[conta], desafio["token"]) is True


def test_resposta_errada_nao_passa_e_explica_se(sem_espera: None) -> None:
    desafio = captcha.desafio()
    errada = str(int(resolver(desafio["pergunta"])) + 1)

    assert captcha.verificar(errada, desafio["token"]) is False
    assert captcha.erro(errada, desafio["token"]) == "A resposta ao desafio não confere. Responda outra vez."
    assert captcha.erro("", desafio["token"]) == "Responda ao desafio, para confirmarmos que é uma pessoa."


def test_testemunho_nao_guarda_a_resposta(sem_espera: None) -> None:
    """O testemunho é público: se a resposta lá estivesse, não valia nada."""
    desafio = captcha.desafio()
    conta = resolver(desafio["pergunta"])

    dados = corpo_do_testemunho(desafio["token"])

    assert set(dados) == {"n", "iat", "exp"}
    assert dados["n"] and dados["exp"] > dados["iat"]
    assert conta not in json.dumps(dados)


def test_testemunho_de_outro_desafio_nao_serve(sem_espera: None) -> None:
    """Trocar a resposta sem trocar o testemunho: a assinatura denuncia."""
    primeiro = captcha.desafio()
    segundo = captcha.desafio()

    assert captcha.verificar(resolver(segundo["pergunta"]), primeiro["token"]) is False
    assert captcha.verificar("12", "isto-não-é-um-testemunho") is False
    assert captcha.verificar("12", "") is False


def test_testemunho_fora_do_prazo_nao_serve(sem_espera: None) -> None:
    desafio = captcha.desafio()
    # Um testemunho assinado por nós, mas emitido há mais tempo do que a validade.
    antigo = captcha.desafio()
    corpo = antigo["token"].split(".", 1)[0]
    dados = json.loads(base64.urlsafe_b64decode(corpo + "=" * (-len(corpo) % 4)).decode("utf-8"))
    dados["exp"] = int(time.time()) - 1
    novos_dados = base64.urlsafe_b64encode(json.dumps(dados, separators=(",", ":")).encode("utf-8")).decode("ascii").rstrip("=")
    resposta = resolver(antigo["pergunta"])
    assinatura = captcha._assinar(novos_dados, resposta)

    assert captcha.verificar(resposta, f"{novos_dados}.{assinatura}") is False
    # E o desafio novo continua a servir.
    assert captcha.verificar(resolver(desafio["pergunta"]), desafio["token"]) is True


def test_resposta_instantanea_e_recusada(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ninguém lê e responde num instante: é robô (o compasso mínimo é real)."""
    monkeypatch.setattr(captcha, "DEMORA_MINIMA_SEGUNDOS", 2)
    desafio = captcha.desafio()

    assert captcha.verificar(resolver(desafio["pergunta"]), desafio["token"]) is False


def test_dois_desafios_seguidos_sao_diferentes() -> None:
    """Cada pedido tem o seu nonce: a mesma pergunta não repete o testemunho."""
    tokens = {captcha.desafio()["token"] for _ in range(20)}

    assert len(tokens) == 20
