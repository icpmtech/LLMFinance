"""Chaves de serviços externos (2captcha) guardadas no Elasticsearch.

O que se testa aqui é a **resolução** das chaves (índice → ambiente → `.env`) e a
gravação/estado no índice, porque foi isso que falhou: reiniciar a API por outro
lançador deixava o processo sem `TWOCAPTCHA_API_KEY` e a recolha societária
morria com «API key da 2captcha em falta».
"""
from __future__ import annotations

import pytest

from api import service_keys
from collectors import publicacoes_mj_captcha as captcha


class _ClienteFalso:
    """Cliente Elasticsearch mínimo para o `service_keys` (só o que ele usa)."""

    def __init__(self) -> None:
        self.documentos: dict = {}

    def exists(self, *, index: str, id: str) -> bool:  # noqa: A002 - API do Elasticsearch
        return id in self.documentos

    def get(self, *, index: str, id: str):  # noqa: A002
        return {"_source": self.documentos[id]}

    def index(self, *, index: str, id: str, document: dict, refresh: bool = False):  # noqa: A002
        self.documentos[id] = document
        return {"result": "created"}


def _cliente_falso(monkeypatch) -> _ClienteFalso:
    cliente = _ClienteFalso()
    monkeypatch.setattr(service_keys, "_client", lambda: cliente)
    return cliente


def test_guardar_e_ler_chaves_no_indice(monkeypatch):
    """Gravar uma chave escreve o documento `service-keys` de `finance_settings`."""
    _cliente_falso(monkeypatch)

    resultado = service_keys.guardar({"twocaptcha_api_key": "abc123"}, utilizador="admin@exemplo.pt")

    assert resultado["alteradas"] == ["twocaptcha_api_key"]
    assert resultado["updated_by"] == "admin@exemplo.pt"
    guardadas = service_keys.valores_guardados()
    assert guardadas == {"twocaptcha_api_key": "abc123"}


def test_valor_vazio_remove_a_chave(monkeypatch):
    """Limpar a chave devolve o serviço ao ambiente/`.env`."""
    _cliente_falso(monkeypatch)
    service_keys.guardar({"twocaptcha_api_key": "abc123"})

    resultado = service_keys.guardar({"twocaptcha_api_key": ""})

    assert resultado["removidas"] == ["twocaptcha_api_key"]
    assert service_keys.valores_guardados() == {}


def test_chave_desconhecida_e_recusada(monkeypatch):
    _cliente_falso(monkeypatch)
    with pytest.raises(ValueError):
        service_keys.guardar({"chave_inventada": "x"})


def test_resolucao_prefere_o_indice_depois_o_ambiente(monkeypatch):
    """Índice → ambiente: o que está na plataforma manda sobre o `.env`/ambiente."""
    _cliente_falso(monkeypatch)
    monkeypatch.setenv("TWOCAPTCHA_API_KEY", "do-ambiente")

    assert service_keys.resolver("twocaptcha_api_key") == "do-ambiente"
    service_keys.guardar({"twocaptcha_api_key": "do-indice"})
    assert service_keys.resolver("twocaptcha_api_key") == "do-indice"
    # O valor explícito (do pedido) tem prioridade sobre tudo.
    assert service_keys.resolver("twocaptcha_api_key", "do-pedido") == "do-pedido"


def test_estado_mascara_a_chave(monkeypatch):
    _cliente_falso(monkeypatch)
    monkeypatch.delenv("TWOCAPTCHA_API_KEY", raising=False)
    monkeypatch.delenv("TWOCAPTCHA_KEY", raising=False)
    monkeypatch.setattr(service_keys, "_do_env_file", lambda nomes: None)
    service_keys.guardar({"twocaptcha_api_key": "603223f68a8474f3a9531cddce3e1d6c"})

    estado = service_keys.estado()
    chave = next(item for item in estado["chaves"] if item["id"] == "twocaptcha_api_key")

    assert chave["definida"] is True
    assert chave["origem"] == "indice"
    assert chave["valor_mascarado"] == "6032…1d6c (32 caracteres)"
    assert "603223f68a8474f3a9531cddce3e1d6c" not in str(estado)
    assert estado["doc_id"] == "service-keys"


def test_cliente_do_mj_usa_a_chave_do_indice(monkeypatch):
    """Sem variáveis de ambiente, o cliente resolve a chave guardada no índice."""
    _cliente_falso(monkeypatch)
    monkeypatch.delenv("TWOCAPTCHA_API_KEY", raising=False)
    monkeypatch.delenv("TWOCAPTCHA_KEY", raising=False)
    monkeypatch.setattr(service_keys, "_do_env_file", lambda nomes: None)
    monkeypatch.setattr(captcha, "_chave_no_env_file", lambda nomes: None)
    service_keys.guardar({"twocaptcha_api_key": "chave-do-indice"})

    assert captcha.api_key_2captcha() == "chave-do-indice"
    cliente = captcha.PublicacoesMjCaptchaClient()
    assert cliente.api_key == "chave-do-indice"


def test_cliente_do_mj_sem_chave_explica_onde_a_por(monkeypatch):
    """Sem chave em lado nenhum, a mensagem diz onde a definir."""
    _cliente_falso(monkeypatch)
    monkeypatch.delenv("TWOCAPTCHA_API_KEY", raising=False)
    monkeypatch.delenv("TWOCAPTCHA_KEY", raising=False)
    monkeypatch.setattr(service_keys, "_do_env_file", lambda nomes: None)
    monkeypatch.setattr(captcha, "_chave_no_env_file", lambda nomes: None)

    with pytest.raises(ValueError) as erro:
        captcha.PublicacoesMjCaptchaClient()

    assert "TWOCAPTCHA_API_KEY" in str(erro.value)
    assert ".env" in str(erro.value)


def test_proxy_resolvido_do_indice(monkeypatch):
    _cliente_falso(monkeypatch)
    monkeypatch.delenv("TWOCAPTCHA_PROXY", raising=False)
    monkeypatch.delenv("SOCIAL_PROXY", raising=False)
    service_keys.guardar({"twocaptcha_proxy": "http://proxy.local:8080"})

    assert captcha.proxy_2captcha() == "http://proxy.local:8080"
    assert captcha.proxy_2captcha("http://outro:3128") == "http://outro:3128"


def test_testar_chave_sem_valor_nao_chama_o_fornecedor(monkeypatch):
    _cliente_falso(monkeypatch)
    monkeypatch.delenv("TWOCAPTCHA_API_KEY", raising=False)
    monkeypatch.delenv("TWOCAPTCHA_KEY", raising=False)
    monkeypatch.setattr(service_keys, "_do_env_file", lambda nomes: None)

    resultado = service_keys.testar("twocaptcha_api_key")

    assert resultado["ok"] is False
    assert "não definida" in resultado["mensagem"]
