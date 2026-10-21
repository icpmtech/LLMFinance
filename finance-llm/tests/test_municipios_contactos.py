"""Contactos das câmaras municipais: leitura do Excel e pesquisa por fragmento.

Testa-se o que não depende do Elasticsearch: a normalização de uma linha do
Excel (código INE com 4 dígitos, código postal separado da localidade, site com
esquema) e a pesquisa local, sobretudo a **pesquisa sem acentos** — «alcac»
tem de encontrar «Alcácer do Sal» e «evor» tem de encontrar «Évora», porque é
assim que as pessoas escrevem numa caixa de pesquisa.
"""
from __future__ import annotations

from typing import Any, Dict, List

import pytest

from api import municipios_contactos_service as contactos


# ---------------------------------------------------------------------------
# Dados sintéticos
# ---------------------------------------------------------------------------

def _docs() -> List[Dict[str, Any]]:
    return [
        {
            "doc_id": "1501",
            "distrito": "Setúbal",
            "municipio": "Alcácer do Sal",
            "codigo_ine": "1501",
            "nif": "502150319",
            "nome_presidente": "Clarisse Maria Gaudino Veredas Campos",
            "morada": "Praça Pedro Nunes",
            "codigo_postal": "7580-125",
            "localidade": "Alcácer do Sal",
            "email": "geral@m-alcacerdosal.pt",
            "telefone": "265610040",
            "site": "https://www.cm-alcacerdosal.pt",
        },
        {
            "doc_id": "0701",
            "distrito": "Évora",
            "municipio": "Évora",
            "codigo_ine": "0701",
            "nif": "506772527",
            "nome_presidente": "Carlos Manuel Rodrigues Pinto de Sá",
            "morada": "Praça do Sertório",
            "codigo_postal": "7004-506",
            "localidade": "Évora",
            "email": "geral@cm-evora.pt",
            "telefone": "266777100",
            "site": "https://www.cm-evora.pt",
        },
    ]


@pytest.fixture(autouse=True)
def _docs_locais(monkeypatch: pytest.MonkeyPatch) -> None:
    """A pesquisa local vê estes dois documentos, sem tocar em disco nem no ES."""
    monkeypatch.setattr(contactos, "_docs_disponiveis", lambda: _docs())


# ---------------------------------------------------------------------------
# Normalização
# ---------------------------------------------------------------------------

def test_codigo_ine_leva_quatro_digitos() -> None:
    assert contactos._codigo_ine_4_digitos("101") == "0101"
    assert contactos._codigo_ine_4_digitos("101 " ) == "0101"
    assert contactos._codigo_ine_4_digitos("1401") == "1401"
    assert contactos._codigo_ine_4_digitos("") == ""


def test_codigo_postal_separado_da_localidade() -> None:
    assert contactos._codigo_postal_localidade("2200-366 Abrantes") == ("2200-366", "Abrantes")
    assert contactos._codigo_postal_localidade("3670-250 Vouzela") == ("3670-250", "Vouzela")
    # Sem código postal reconhecível, o texto fica como localidade.
    assert contactos._codigo_postal_localidade("Lisboa") == ("", "Lisboa")


def test_site_ganha_esquema_e_perde_espacos() -> None:
    assert contactos._site_url("www.cm-stirso.pt ") == "https://www.cm-stirso.pt"
    assert contactos._site_url("http://www.cm-viseu.pt") == "http://www.cm-viseu.pt"
    assert contactos._site_url("https://www.cm-porto.pt/") == "https://www.cm-porto.pt"
    assert contactos._site_url("") == ""


def test_sem_acentos() -> None:
    assert contactos._sem_acentos("Alcácer do Sal") == "alcacer do sal"
    assert contactos._sem_acentos("ÉVORA") == "evora"
    assert contactos._sem_acentos("Sertã") == "serta"


# ---------------------------------------------------------------------------
# Pesquisa local
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "termo, esperado",
    [
        ("alcacer", "Alcácer do Sal"),
        ("alcac", "Alcácer do Sal"),
        ("evora", "Évora"),
        ("evor", "Évora"),
        ("Sá", "Évora"),
        ("265610040", "Alcácer do Sal"),
        ("geral@cm-evora.pt", "Évora"),
        ("Setúbal", "Alcácer do Sal"),
    ],
)
def test_pesquisa_sem_acentos_encontra(termo: str, esperado: str) -> None:
    resposta = contactos._pesquisar_local(q=termo, size=10)
    nomes = [item["municipio"] for item in resposta["items"]]
    assert esperado in nomes, f"«{termo}» devia encontrar «{esperado}», veio {nomes}"


def test_pesquisa_por_codigo_ine_exacto() -> None:
    resposta = contactos._pesquisar_local(codigo_ine="0701", size=10)
    assert resposta["total"] == 1
    assert resposta["items"][0]["municipio"] == "Évora"


def test_pesquisa_por_distrito_ignora_acentos() -> None:
    resposta = contactos._pesquisar_local(distrito="evora", size=10)
    assert [item["municipio"] for item in resposta["items"]] == ["Évora"]


def test_pesquisa_sem_resultados() -> None:
    resposta = contactos._pesquisar_local(q="zzzzzz", size=10)
    assert resposta["total"] == 0
    assert resposta["items"] == []


def test_paginacao() -> None:
    primeira = contactos._pesquisar_local(size=1, page=1)
    segunda = contactos._pesquisar_local(size=1, page=2)
    assert primeira["total"] == 2
    assert len(primeira["items"]) == 1
    assert primeira["items"][0]["municipio"] != segunda["items"][0]["municipio"]


# ---------------------------------------------------------------------------
# Campos sem acentos
# ---------------------------------------------------------------------------

def test_campos_normalizados_na_indexacao(monkeypatch: pytest.MonkeyPatch) -> None:
    """A indexação acrescenta `*_fold` mesmo a documentos de uma cache antiga."""
    capturado: Dict[str, Any] = {}

    class _BulkClient:
        class indices:  # noqa: N801 - imita a API do cliente
            @staticmethod
            def refresh(**_: Any) -> None:
                return None

    def _bulk(_client: Any, actions: Any, **_: Any) -> Any:
        capturado["actions"] = list(actions)
        return len(capturado["actions"]), []

    monkeypatch.setattr(contactos, "get_es_client", lambda: _BulkClient())
    monkeypatch.setattr(contactos, "ensure_indices", lambda *_: True)
    monkeypatch.setattr(contactos, "bulk", _bulk)

    contactos.indexar(_docs(), substituir=False)

    primeira = capturado["actions"][0]
    assert primeira["municipio_fold"] == "alcacer do sal"
    assert primeira["nome_presidente_fold"].startswith("clarisse")
    assert primeira["ingested_at"] and primeira["updated_at"]
