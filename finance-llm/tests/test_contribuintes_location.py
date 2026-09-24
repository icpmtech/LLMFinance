"""Testes da localização dos contribuintes (campos da raiz nas fontes aninhadas).

A localização das empresas vem sobretudo do `localExecucao` dos contratos
(«Portugal, Lisboa, Cascais»). Esse campo vive na **raiz** do documento, mas a
agregação que o lê é `nested` (sobre `adjudicantes.parsed`), e um `top_hits`
dentro de uma agregação `nested` devolve apenas o objeto aninhado. Sem
`reverse_nested` a localização vinha sempre vazia.

Inclui também testes da montagem do documento (`_build_doc`) — designações
repetidas, que davam chaves duplicadas na interface.

São testes de unidade: não precisam de Elasticsearch nem da API.
"""
from __future__ import annotations

import pytest

from api import contribuintes_service as service


def test_spec_top_hits_prefere_os_campos_aninhados() -> None:
    spec = service.SOURCE_BY_ID["contratos"]["specs"][0]
    fields = service._spec_top_hits(spec)

    # Dentro da agregação aninhada o `top_hits` devolve o objeto aninhado e o
    # filtro `_source` tem de usar o caminho completo.
    assert fields == ["adjudicantes.parsed.nome"]
    # O campo da raiz **não** entra aqui: vem pelo `reverse_nested` (teste abaixo),
    # porque com o prefixo a resposta vinha vazia e não havia localização nenhuma.
    assert "localExecucao" not in fields


def test_aggs_aninhadas_trazem_a_raiz_por_reverse_nested() -> None:
    spec = service.SOURCE_BY_ID["contratos"]["specs"][0]
    body = service._spec_aggs(spec, 500, None)
    node = body["n"]["aggs"]["c"]

    assert body["n"]["nested"]["path"] == "adjudicantes.parsed"
    back = node["aggs"]["back"]
    assert back["reverse_nested"] == {}
    assert back["aggs"]["root"]["top_hits"]["_source"] == ["localExecucao"]
    assert {"value", "first", "last"} <= set(back["aggs"])


def test_aggs_sem_top_hits_nao_pedem_a_raiz() -> None:
    spec = service.SOURCE_BY_ID["contratos"]["specs"][0]
    body = service._spec_aggs(spec, 400, None, with_top=False)
    back = body["n"]["aggs"]["c"]["aggs"]["back"]

    assert "top" not in body["n"]["aggs"]["c"]["aggs"]
    assert "root" not in back["aggs"]
    assert "value" in back["aggs"]


def test_specs_planas_levam_o_campo_da_raiz_no_top_hits() -> None:
    spec = {"key": "x", "field": "nif", "name_fields": ["name"], "root_detail": ["city"]}
    assert service._spec_top_hits(spec) == ["name", "city"]
    body = service._spec_aggs(spec, 100, None)
    assert "back" not in body["c"]["aggs"]


def test_bucket_com_a_raiz_preenche_o_detail() -> None:
    spec = service.SOURCE_BY_ID["contratos"]["specs"][0]
    spec = {**spec, "top_hits": service._spec_top_hits(spec)}
    # Forma real da resposta: o `top_hits` aninhado devolve os campos com o nome
    # simples e o `reverse_nested` devolve o documento pai.
    bucket = {
        "key": {"value": "500189412"},
        "doc_count": 7,
        "top": {"hits": {"hits": [{"_source": {"nome": "ACME"}}]}},
        "back": {"root": {"hits": {"hits": [{"_source": {"localExecucao": ["Portugal, Lisboa, Cascais"]}}]}}},
    }
    payload = service._bucket_payload("contratos", spec, bucket)

    assert payload is not None
    assert payload["names"] == ["ACME"]
    assert payload["detail"]["localExecucao"] == ["Portugal, Lisboa, Cascais"]
    assert service._location_from_local_execucao(payload["detail"]["localExecucao"]) == {
        "pais": "Portugal",
        "distrito": "Lisboa",
        "concelho": "Cascais",
    }


def test_bucket_plano_sem_raiz_nao_rebenta() -> None:
    spec = {"key": "x", "field": "nif", "name_fields": ["name"], "root_detail": ["city"]}
    spec = {**spec, "top_hits": service._spec_top_hits(spec)}
    bucket = {"key": {"value": "500189412"}, "doc_count": 1, "top": {"hits": {"hits": []}}}
    payload = service._bucket_payload("crm", spec, bucket)

    assert payload is not None
    assert payload["detail"] == {}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (["Portugal, Lisboa, Cascais"], {"pais": "Portugal", "distrito": "Lisboa", "concelho": "Cascais"}),
        ("Portugal, Porto, Porto", {"pais": "Portugal", "distrito": "Porto", "concelho": "Porto"}),
        (["Portugal"], {"pais": "Portugal"}),
        (["Portugal", "Portugal, Braga, Braga"], {"pais": "Portugal", "distrito": "Braga", "concelho": "Braga"}),
        (["Portugal", "Portugal, Guarda, Fig. Castelo Rodrigo"], {"pais": "Portugal", "distrito": "Guarda", "concelho": "Fig. Castelo Rodrigo"}),
        ([], {}),
        (None, {}),
        ("", {}),
        (["  ", ""], {}),
    ],
)
def test_local_execucao_em_partes(raw: object, expected: dict) -> None:
    assert service._location_from_local_execucao(raw) == expected


def test_sede_tem_prioridade_sobre_o_local_de_execucao() -> None:
    blocks = {
        "contratos": {
            "count": 3,
            "names": ["ACME"],
            "roles": ["adjudicatario"],
            "detail": {"localExecucao": ["Portugal, Lisboa, Cascais"]},
        },
        "societario": {
            "count": 1,
            "names": ["ACME"],
            "roles": ["societario"],
            "detail": {"distrito": "Braga", "concelho": "Guimarães", "codigo_postal": "4810-000"},
        },
    }
    doc = service._build_doc("500189412", blocks, "run-1")

    assert doc["location"]["distrito"] == "Braga"
    assert doc["location"]["concelho"] == "Guimarães"
    # O país, que a sede não traz, é preenchido pelo local de execução.
    assert doc["location"]["pais"] == "Portugal"


def test_local_de_execucao_preenche_o_que_a_sede_nao_tem() -> None:
    blocks = {
        "contratos": {
            "count": 1,
            "names": ["ACME"],
            "roles": ["adjudicante"],
            "detail": {"localExecucao": ["Portugal", "Portugal, Setúbal, Almada"]},
        }
    }
    doc = service._build_doc("500189412", blocks, "run-1")

    assert doc["location"] == {"pais": "Portugal", "distrito": "Setúbal", "concelho": "Almada"}


def test_designacoes_repetidas_entram_uma_so_vez() -> None:
    """A mesma designação em fontes diferentes não pode repetir-se (chaves na UI)."""
    blocks = {
        "entidades": {"count": 1, "names": ["Infraestruturas de Portugal "], "roles": ["cadastro"]},
        "contratos": {"count": 4, "names": ["INFRAESTRUTURAS DE PORTUGAL", "IP, S.A."], "roles": ["adjudicante"]},
    }
    doc = service._build_doc("503933813", blocks, "run-1")

    assert doc["names"] == ["Infraestruturas de Portugal", "IP, S.A."]
    assert doc["name"] == "Infraestruturas de Portugal"
