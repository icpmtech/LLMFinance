"""Testes das chamadas aos fornecedores externos (`api/cloud_chat.py`).

O foco é o que causou o erro «DeepSeek não respondeu a tempo»: o `httpx` cobre
quatro situações diferentes com a mesma exceção e a mensagem não as distinguia,
e uma falha de **ligação** (10 s) deitava fora a resposta toda sem uma única
tentativa extra.
"""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from api import cloud_chat

SPEC = {"id": "deepseek", "kind": "openai", "base_url": "https://api.deepseek.com/v1", "label": "DeepSeek"}


# --------------------------------------------------------------------- auxiliares

class _RespostaFalsa:
    def __init__(self, linhas, status: int = 200):
        self.status_code = status
        self._linhas = list(linhas)

    async def aread(self) -> bytes:
        return b'{"error": "detalhe"}'

    async def aiter_lines(self):
        for linha in self._linhas:
            yield linha


class _StreamFalso:
    """Contexto de `client.stream(...)`: ou devolve a resposta, ou rebenta."""

    def __init__(self, resposta=None, erro: Exception | None = None):
        self._resposta = resposta
        self._erro = erro

    async def __aenter__(self):
        if self._erro is not None:
            raise self._erro
        return self._resposta

    async def __aexit__(self, *args):
        return False


class _ClienteFalso:
    """Segue um «guião»: cada `stream()` consome o passo seguinte (o último repete)."""

    def __init__(self, guiao, estado):
        self._guiao = guiao
        self._estado = estado

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def stream(self, *args, **kwargs):
        indice = min(self._estado["n"], len(self._guiao) - 1)
        self._estado["n"] += 1
        return self._guiao[indice]


def _instalar(monkeypatch, guiao) -> dict:
    """Substitui o `httpx.AsyncClient` por um cliente com guião. Devolve o estado."""
    estado = {"n": 0, "chamadas": []}

    def fabrica(**kwargs):
        estado["chamadas"].append(kwargs)
        return _ClienteFalso(guiao, estado)

    monkeypatch.setattr(cloud_chat.httpx, "AsyncClient", fabrica)
    monkeypatch.setattr(cloud_chat, "TENTATIVA_ESPERA", 0.0)
    return estado


def _recolher(messages=None, **kwargs):
    """Percorre o stream e devolve `(pedaços, erro)`."""

    async def correr():
        partes = []
        try:
            async for chunk in cloud_chat.stream_answer(
                provider="deepseek",
                spec=SPEC,
                model="deepseek-chat",
                messages=messages or [{"role": "user", "content": "olá"}],
                api_key="chave",
                **kwargs,
            ):
                partes.append(chunk)
        except cloud_chat.CloudError as erro:
            return partes, erro
        return partes, None

    return asyncio.run(correr())


def _linhas(*textos: str):
    return [f"data: {json.dumps({'choices': [{'delta': {'content': t}}]})}" for t in textos] + ["data: [DONE]"]


# --------------------------------------------------------------------- mensagens

@pytest.mark.parametrize(
    "erro,esperado",
    [
        (httpx.ConnectTimeout("x"), "Não foi possível ligar a DeepSeek"),
        (httpx.PoolTimeout("x"), "não aceitou a ligação a tempo"),
        (httpx.WriteTimeout("x"), "ficou presa ao enviar o pedido"),
        (httpx.ReadTimeout("x"), "deixou de enviar dados"),
    ],
)
def test_mensagem_de_timeout_distingue_os_casos(erro, esperado):
    """Antes todas estas situações davam a mesma frase «não respondeu a tempo»."""
    assert esperado in cloud_chat._mensagem_de_timeout(erro, "DeepSeek")


def test_timeouts_do_cliente_sao_generosos_no_connect():
    assert cloud_chat.REQUEST_TIMEOUT.connect == cloud_chat.CONNECT_TIMEOUT >= 20.0
    assert cloud_chat.REQUEST_TIMEOUT.read >= 180.0
    assert cloud_chat.REQUEST_TIMEOUT.pool == cloud_chat.POOL_TIMEOUT >= 20.0


# --------------------------------------------------------------------- tentativas

def test_repetir_quando_a_ligacao_falha_sem_texto(monkeypatch):
    """O caso real: `ConnectTimeout` aos 10 s, sem um único pedaço."""
    estado = _instalar(
        monkeypatch,
        [
            _StreamFalso(erro=httpx.ConnectTimeout("ligação não estabelecida")),
            _StreamFalso(_RespostaFalsa(_linhas("Olá ", "mundo"))),
        ],
    )

    partes, erro = _recolher()

    assert erro is None
    assert "".join(partes) == "Olá mundo"
    assert estado["n"] == 2  # segunda tentativa


def test_falha_de_ligacao_persistente_explica_o_motivo(monkeypatch):
    estado = _instalar(monkeypatch, [_StreamFalso(erro=httpx.ConnectTimeout("sem rota"))])

    partes, erro = _recolher()

    assert partes == []
    assert erro is not None
    assert "Não foi possível ligar a DeepSeek" in str(erro)
    assert "responder a tempo" not in str(erro)
    # Tentou o número máximo de vezes.
    assert estado["n"] == cloud_chat.MAX_TENTATIVAS_LIGACAO


def test_nao_repetir_depois_de_ja_haver_texto(monkeypatch):
    """Repetir com texto já enviado duplicaria a resposta no ecrã."""
    estado = _instalar(
        monkeypatch,
        [_StreamFalso(_RespostaQueFalha(["Comecei a responder"], httpx.ReadTimeout("parou")))],
    )

    partes, erro = _recolher()

    assert partes == ["Comecei a responder"]
    assert erro is not None
    assert "deixou de enviar dados" in str(erro)
    assert estado["n"] == 1


class _RespostaQueFalha:
    """Resposta que emite algumas linhas e depois rebenta no meio do stream."""

    def __init__(self, textos, erro: Exception):
        self.status_code = 200
        self._textos = textos
        self._erro = erro

    async def aread(self) -> bytes:
        return b""

    async def aiter_lines(self):
        for linha in _linhas(*self._textos)[:-1]:
            yield linha
        raise self._erro


def test_erro_do_fornecedor_nao_e_convertido_em_timeout(monkeypatch):
    _instalar(monkeypatch, [_StreamFalso(_RespostaFalsa([], status=429))])

    partes, erro = _recolher()

    assert partes == []
    assert "Limite de utilização/plano excedido" in str(erro)
    assert erro.status == 429


def test_falha_de_rede_sem_texto_repete_e_depois_desiste(monkeypatch):
    estado = _instalar(monkeypatch, [_StreamFalso(erro=httpx.ConnectError("DNS"))])

    partes, erro = _recolher()

    assert partes == []
    assert "Falha de rede a contactar DeepSeek" in str(erro)
    assert estado["n"] == cloud_chat.MAX_TENTATIVAS_LIGACAO


def test_erro_de_conteudo_do_fornecedor_chega_ao_utilizador(monkeypatch):
    linhas = ['data: {"error": {"message": "modelo em manutenção"}}']
    _instalar(monkeypatch, [_StreamFalso(_RespostaFalsa(linhas))])

    partes, erro = _recolher()

    assert partes == []
    assert "modelo em manutenção" in str(erro)
