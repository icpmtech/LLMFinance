"""Resolução do reCAPTCHA do MJ via 2captcha.

Regressão de 2026-10-22: a recolha falhou com
«2captcha não conseguiu resolver o reCAPTCHA: ('Connection aborted.',
RemoteDisconnected(...))». O pacote opcional `2captcha-python` falava `http://`
sem timeout nem novas tentativas, pelo que uma ligação cortada perdia a recolha.

O cliente passou a ser próprio (API JSON, HTTPS) e testa-se aqui: as novas
tentativas em erros de rede, os códigos de erro da 2captcha traduzidos para uma
mensagem útil e o caminho feliz (tarefa criada → token).
"""
from __future__ import annotations

from typing import Any, Dict, List

import pytest
import requests

from collectors import publicacoes_mj_captcha as captcha
from collectors.publicacoes_mj import CaptchaRequiredError

CHAVE = "0" * 32


class RespostaFalsa:
    def __init__(self, dados: Dict[str, Any], status: int = 200) -> None:
        self._dados = dados
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")

    def json(self) -> Dict[str, Any]:
        return self._dados


def test_rede_a_falhar_e_repetida(monkeypatch: pytest.MonkeyPatch) -> None:
    """Um corte de ligação não perde a recolha: a chamada é repetida."""
    chamadas: List[str] = []

    def post(url: str, json: Dict[str, Any], timeout: float) -> RespostaFalsa:
        chamadas.append(url)
        if len(chamadas) == 1:
            raise requests.exceptions.ConnectionError(
                "('Connection aborted.', RemoteDisconnected('Remote end closed connection without response'))"
            )
        return RespostaFalsa({"errorId": 0, "balance": 1.5})

    monkeypatch.setattr(captcha.requests, "post", post)
    monkeypatch.setattr(captcha.time, "sleep", lambda *_: None)

    assert captcha.TwoCaptchaDireto(CHAVE).saldo() == 1.5
    assert len(chamadas) == 2


def test_rede_sempre_a_falhar_da_erro_explicito(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        captcha.requests,
        "post",
        lambda *_, **__: (_ for _ in ()).throw(requests.exceptions.ConnectionError("RemoteDisconnected")),
    )
    monkeypatch.setattr(captcha.time, "sleep", lambda *_: None)

    with pytest.raises(CaptchaRequiredError) as erro:
        captcha._post_2captcha("/getBalance", {"clientKey": CHAVE}, tentativas=2)
    assert "2captcha indisponível" in str(erro.value)


def test_tarefa_recusada_mostra_o_codigo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        captcha.requests,
        "post",
        lambda *_, **__: RespostaFalsa(
            {"errorId": 12, "errorCode": "ERROR_WRONG_USER_KEY", "errorDescription": "chave inválida"}
        ),
    )

    with pytest.raises(CaptchaRequiredError) as erro:
        captcha.TwoCaptchaDireto(CHAVE).resolver_recaptcha(sitekey="site", page_url="https://exemplo.pt/")
    assert "ERROR_WRONG_USER_KEY" in str(erro.value)


def test_resolve_a_tarefa_e_devolve_o_token(monkeypatch: pytest.MonkeyPatch) -> None:
    respostas = [
        RespostaFalsa({"errorId": 0, "taskId": 4242}),
        RespostaFalsa({"errorId": 0, "status": "processing"}),
        RespostaFalsa({"errorId": 0, "status": "ready", "solution": {"gRecaptchaResponse": "TOKEN-VALIDO"}}),
    ]
    pedidos: List[Dict[str, Any]] = []

    def post(url: str, json: Dict[str, Any], timeout: float) -> RespostaFalsa:
        pedidos.append({"url": url, "corpo": json})
        return respostas.pop(0)

    monkeypatch.setattr(captcha.requests, "post", post)
    monkeypatch.setattr(captcha.time, "sleep", lambda *_: None)

    token = captcha.TwoCaptchaDireto(CHAVE).resolver_recaptcha(sitekey="site", page_url="https://exemplo.pt/")

    assert token == "TOKEN-VALIDO"
    assert pedidos[0]["url"].startswith("https://")
    assert pedidos[0]["corpo"]["task"]["type"] == "RecaptchaV2TaskProxyless"
    assert pedidos[0]["corpo"]["task"]["websiteKey"] == "site"
    assert pedidos[-1]["corpo"] == {"clientKey": CHAVE, "taskId": 4242}


def test_tarefa_pendente_termina_em_erro(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        captcha.requests, "post", lambda *_, **__: RespostaFalsa({"errorId": 0, "taskId": 1, "status": "processing"})
    )
    monkeypatch.setattr(captcha.time, "sleep", lambda *_: None)
    # Relógio que avança sozinho: sem isto o teste esperaria os 30s reais.
    instantes = iter(range(0, 10_000, 60))
    monkeypatch.setattr(captcha.time, "monotonic", lambda: next(instantes))

    with pytest.raises(CaptchaRequiredError) as erro:
        captcha.TwoCaptchaDireto(CHAVE).resolver_recaptcha(
            sitekey="site", page_url="https://exemplo.pt/", limite=30
        )
    assert "não resolveu o reCAPTCHA" in str(erro.value)

