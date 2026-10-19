"""Testes da resolução de entidade do Hermes (`hermes_service._resolve_entity`).

O caso real que motivou isto: «Quem é a Ilídio da Silva Oliveira nos contratos
públicos?» não traz NIF. A pergunta caía em texto livre e a agregação por
palavras casou **72 685 contratos** (bastava o «silva») — o modelo contou-os como
sendo daquela pessoa, que tem 1. O cadastro de entidades responde por nome e já
traz os totais calculados, mesmo para quem não tem NIF.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from api import hermes_service as hermes  # noqa: E402
from api import search360_service as search360  # noqa: E402

# Ficha tal como sai do cadastro de entidades (`finance_entities`): sem NIF.
PESSOA = {
    "nif": None,
    "name": "Ilídio da Silva Oliveira",
    "contracts_count": 1,
    "total_value": 3810.0,
    "as_adjudicante_count": 0,
    "as_adjudicatario_count": 1,
}
EMPRESA = {
    "nif": "500000000",
    "name": "Galp Energia",
    "contracts_count": 900,
    "total_value": 1.5e9,
    "as_adjudicante_count": 0,
    "as_adjudicatario_count": 900,
}


def _diretorio(monkeypatch, cadastro, directorio=()):
    """Substitui o cadastro de entidades e o diretório de empresas pelos guiões."""
    from api import elasticsearch_client

    monkeypatch.setattr(
        elasticsearch_client, "search_entities", lambda **kwargs: {"items": list(cadastro), "total": len(cadastro)}
    )
    monkeypatch.setattr(
        elasticsearch_client,
        "search_companies",
        lambda **kwargs: {"items": list(directorio), "total": len(directorio)},
    )


def test_nome_proprio_vira_candidato_e_palavra_de_pergunta_nao() -> None:
    assert hermes._name_candidates("Quem é a Ilídio da Silva Oliveira nos contratos públicos?") == [
        "Ilídio da Silva Oliveira"
    ]
    assert hermes._name_candidates("Quais os maiores contratos de energia em 2025?") == []
    assert hermes._name_candidates("diz-me o total de contratos") == []


def test_resolve_o_nome_para_a_ficha_do_cadastro(monkeypatch) -> None:
    _diretorio(monkeypatch, [PESSOA])
    plano = search360.plan("quem e a ilidio da silva oliveira nos contratos publicos e que valores tem")

    ficha = hermes._resolve_entity("Quem é a Ilídio da Silva Oliveira nos contratos públicos?", plano)

    assert ficha is not None
    assert ficha["name"] == "Ilídio da Silva Oliveira"
    assert ficha["contracts_count"] == 1
    assert ficha["as_adjudicatario_count"] == 1
    assert ficha["nif"] == ""  # sem NIF no cadastro: não há agregação exacta
    assert ficha["origem"] == "cadastro"


def test_ficha_sem_nif_nao_inventa_agregacao(monkeypatch) -> None:
    """O prompt tem de dizer que não há NIF, senão o modelo soma o que não deve."""
    facts = hermes._entity_card_facts(hermes._normaliza_ficha(PESSOA, "cadastro"))

    texto = "\n".join(facts["facts"])
    assert "1 contrato" in texto
    assert "3.8 mil€" in texto
    assert "não tem NIF" in texto


def test_recorre_ao_diretorio_quando_o_cadastro_nao_tem(monkeypatch) -> None:
    _diretorio(monkeypatch, [], [{"nif": "500000000", "name": "Galp Energia", "contracts_total": 900}])
    plano = search360.plan("contratos da galp energia")

    ficha = hermes._resolve_entity("Contratos da Galp Energia em 2025", plano)

    assert ficha is not None
    assert ficha["nif"] == "500000000"
    assert ficha["origem"] == "diretório"


def test_nao_resolve_quando_o_nome_nao_esta_na_pergunta(monkeypatch) -> None:
    """Sem cobertura do nome na pergunta, mais vale texto livre do que inventar."""
    _diretorio(monkeypatch, [EMPRESA])
    plano = search360.plan("quem e a ilidio da silva oliveira")

    assert hermes._resolve_entity("Quem é a Ilídio da Silva Oliveira?", plano) is None


def test_nao_resolve_numa_pergunta_de_total_global(monkeypatch) -> None:
    _diretorio(monkeypatch, [PESSOA])
    plano = search360.plan("quantos contratos publicos existem em portugal")

    assert hermes._resolve_entity("Quantos contratos públicos existem em Portugal?", plano) is None


def test_valores_na_pergunta_nao_impede_resolver_a_entidade(monkeypatch) -> None:
    """«…e que valores tem?» traz «valores», mas a pergunta é sobre a pessoa."""
    _diretorio(monkeypatch, [PESSOA])
    pergunta = "Quem é a Ilídio da Silva Oliveira nos contratos públicos e que valores tem?"
    plano = search360.plan(pergunta.lower())

    assert hermes._resolve_entity(pergunta, plano)["name"] == "Ilídio da Silva Oliveira"


def test_palavra_comum_nao_vira_ticker() -> None:
    """«nos contratos» não é a operadora NOS — era o que desviava a resposta."""
    plano = search360.plan("Quem é a Ilídio da Silva Oliveira nos contratos públicos?")

    assert plano["tickers"] == []
    assert search360.plan("contratos da EDP em 2025")["tickers"] == ["EDP"]


def test_nao_resolve_quando_a_pergunta_ja_traz_nif(monkeypatch) -> None:
    _diretorio(monkeypatch, [PESSOA])
    plano = search360.plan("contratos do nif 509136826")

    assert hermes._resolve_entity("Contratos do NIF 509136826", plano) is None


def test_aceita_o_homonimo_com_mais_contratos(monkeypatch) -> None:
    _diretorio(
        monkeypatch,
        [
            {**PESSOA, "nif": "111111111", "contracts_count": 1},
            {**PESSOA, "nif": "222222222", "contracts_count": 40},
        ],
    )
    plano = search360.plan("ilidio da silva oliveira contratos")

    assert hermes._resolve_entity("Quem é a Ilídio da Silva Oliveira?", plano)["nif"] == "222222222"


def test_nif_invalido_no_cadastro_e_tratado_como_ausente() -> None:
    """«não especificado» e afins não podem virar filtro de agregação."""
    assert hermes._normaliza_ficha({**PESSOA, "nif": "não especificado"}, "cadastro")["nif"] == ""
    assert hermes._normaliza_ficha({**PESSOA, "nif": "12345"}, "cadastro")["nif"] == ""
