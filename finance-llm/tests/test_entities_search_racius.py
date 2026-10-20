"""Testes da pesquisa combinada de entidades + Racius.

Foca-se na deduplicação, normalização e paginação, sem depender do
Elasticsearch estar disponível.
"""
from __future__ import annotations

from typing import Any, Dict, List

import pytest

from api import entities_service as service


def _entity(nif: str, name: str, **extra: Any) -> Dict[str, Any]:
    return {
        "nif": nif,
        "name": name,
        "country": "Portugal",
        "country_code": "PT",
        "has_nif": bool(nif),
        "contracts_count": 0,
        "as_adjudicante_count": 0,
        "as_adjudicatario_count": 0,
        "total_value": 0.0,
        "as_adjudicante_value": 0.0,
        "cae_principal": None,
        "caes_secundarios": [],
        "source": "entidades_gov_portal_base",
        **extra,
    }


def _racius(**fields: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "nome": "Racius Lda",
        "nif": "900000001",
        "concelho": "Lisboa",
        "distrito": "Lisboa",
        "forma_juridica": "Sociedade Unipessoal por Quotas",
        "capital_social_eur": 5000.0,
        "morada": "Rua A",
        "atividade": "Consultoria",
        "cae": "62010",
        "url": "https://racius.com/x",
        "ficha": {"telefone": "210000000"},
        "scraped_at": "2025-01-01T00:00:00Z",
        "source_id": "racius-diretorio",
        "source_name": "Racius · Diretório de empresas (PT)",
        "localizacao": "Lisboa, Lisboa",
    }
    defaults.update(fields)
    return defaults


class TestNormalizeRaciusItem:
    def test_normaliza_campos_canonicos(self):
        item = service._normalize_racius_item(_racius(nome="Acme, Lda", nif="123456789"))

        assert item["name"] == "Acme, Lda"
        assert item["nif"] == "123456789"
        assert item["country"] == "Portugal"
        assert item["country_code"] == "PT"
        assert item["source"] == "racius"
        assert item["has_nif"] is True
        assert item["cae_principal"] == "62010"
        assert item["racius_source_id"] == "racius-diretorio"
        assert item["racius_source_name"] == "Racius · Diretório de empresas (PT)"
        assert item["racius_ficha"] == {"telefone": "210000000"}

    def test_sem_nif_marca_has_nif_falso(self):
        item = service._normalize_racius_item(_racius(nif=""))

        assert item["has_nif"] is False
        assert item["nif"] == ""


class TestDeduplicateAndMerge:
    def test_preserva_entidades_e_adiciona_racius_novos(self):
        entities = [_entity("100000001", "Alpha, Lda")]
        racius = [_racius(nome="Beta, Lda", nif="100000002")]

        merged = service._deduplicate_and_merge(entities, racius)

        assert [it["nif"] for it in merged] == ["100000001", "100000002"]
        assert merged[1]["source"] == "racius"

    def test_descarta_racius_duplicado_por_nif(self):
        entities = [_entity("100000001", "Alpha, Lda")]
        racius = [_racius(nome="Outro nome, Lda", nif="100000001")]

        merged = service._deduplicate_and_merge(entities, racius)

        assert len(merged) == 1
        assert merged[0]["name"] == "Alpha, Lda"

    def test_enriquece_campos_vazios_do_cadastro(self):
        entities = [_entity("100000001", "Alpha, Lda", cae_principal=None, morada="")]
        racius = [_racius(nome="Alpha, Lda", nif="100000001", cae="62010", morada="Rua A", distrito="Lisboa")]

        merged = service._deduplicate_and_merge(entities, racius)

        assert merged[0]["cae_principal"] == "62010"
        assert merged[0]["morada"] == "Rua A"
        assert merged[0]["distrito"] == "Lisboa"

    def test_nao_substitui_valores_existentes(self):
        entities = [_entity("100000001", "Alpha, Lda", cae_principal="71120", distrito="Porto")]
        racius = [_racius(nome="Alpha, Lda", nif="100000001", cae="62010", distrito="Lisboa")]

        merged = service._deduplicate_and_merge(entities, racius)

        assert merged[0]["cae_principal"] == "71120"
        assert merged[0]["distrito"] == "Porto"

    def test_racius_sem_nif_e_adicionado(self):
        entities = [_entity("100000001", "Alpha, Lda")]
        racius = [_racius(nome="Beta sem NIF, Lda", nif="")]

        merged = service._deduplicate_and_merge(entities, racius)

        assert len(merged) == 2
        assert merged[1]["source"] == "racius"


class TestSearchEntitiesWithRacius:
    def test_propaga_erro_do_cadastro(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(
            service,
            "search_entities",
            lambda **_: {"error": "Elasticsearch indisponível", "items": [], "total": 0},
        )
        monkeypatch.setattr(service.racius_service, "available", lambda: False)

        res = service.search_entities_with_racius(q="alpha", size=10)

        assert res["error"] == "Elasticsearch indisponível"

    def test_pagina_lista_unificada(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(
            service,
            "search_entities",
            lambda **_: {
                "items": [_entity("100000001", "Alpha, Lda")],
                "total": 1,
                "notes": [],
            },
        )
        monkeypatch.setattr(service.racius_service, "available", lambda: True)

        racius_hits = [
            _racius(nome="Beta, Lda", nif="100000002"),
            _racius(nome="Gamma, Lda", nif="100000003"),
        ]

        def fake_search_directory(*_args, **_kwargs) -> Dict[str, Any]:
            return {"items": racius_hits, "total": 2}

        monkeypatch.setattr(service, "search_directory", fake_search_directory)

        res = service.search_entities_with_racius(q="alpha", size=2, from_=0)

        assert res["total"] == 3
        assert len(res["items"]) == 2
        assert res["items"][0]["nif"] == "100000001"
        assert res["items"][1]["nif"] == "100000002"
        assert any("Racius" in nota for nota in res["notes"])

        page2 = service.search_entities_with_racius(q="alpha", size=2, from_=2)
        assert len(page2["items"]) == 1
        assert page2["items"][0]["nif"] == "100000003"

    def test_racius_indisponivel_continua_com_entidades(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(
            service,
            "search_entities",
            lambda **_: {
                "items": [_entity("100000001", "Alpha, Lda")],
                "total": 1,
                "notes": [],
            },
        )
        monkeypatch.setattr(service.racius_service, "available", lambda: False)

        res = service.search_entities_with_racius(q="alpha", size=10)

        assert res["total"] == 1
        assert len(res["items"]) == 1
        assert not any("Racius" in nota for nota in res["notes"])
