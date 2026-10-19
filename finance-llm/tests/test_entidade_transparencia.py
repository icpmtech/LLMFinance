"""Entidade para a Transparência: normalização e pesquisa em disco.

O que se testa aqui não depende da rede nem do Elasticsearch: a leitura da
árvore `{key, value}` da API pública (secções, subsecções, campos e tabelas), os
rótulos do modelo oficial (natureza, estado civil, remuneração sim/não), a
extração do **registo de interesses** e a pesquisa de recurso no JSONL.

A árvore sintética segue a forma real da resposta de `/publicquery/getdeclaration`
(ex.: `358af850-…` facto determinante, `7df770a3-…` dados pessoais,
`1483a8d1-…` registo de interesses).
"""
from __future__ import annotations

import json

import pytest

from api import elasticsearch_client as esc
from api import entidade_transparencia_service as svc
from collectors import entidade_transparencia as ept


def _no(chave: str, valor=None, *, visivel: bool = True) -> dict:
    return {"key": chave, "value": valor, "isVisible": visivel}


def _linha(tabela: str, valores: dict[str, object], indice: int = 0) -> dict:
    return {
        "key": f"{tabela}_{indice}",
        "value": [{"key": f"{tabela}-{coluna}", "value": valor, "isVisible": True} for coluna, valor in valores.items()],
        "isVisible": True,
    }


def _declaracao() -> dict:
    """Declaração de exemplo com dados pessoais, interesses e campos ocultos."""
    facto = _no(
        "29e3c9b0-8881-4dbd-b96b-6ab967edbb7c",
        [
            _no("f649defc-e001-4866-9c2b-01ed9fa80eef", "Inicial"),
            _no("418cdc5e-7f77-4922-b0b7-3ab6b2f84c6f", "2024-01-02T00:00:00Z"),
            _no("5783eba6-4662-4e01-a1ab-14dbe7bb693c", "2024-12-31T00:00:00Z"),
        ],
    )
    pessoais = _no(
        "56786e7c-a8bb-43aa-9250-eaf8fa82002f",
        [
            _no("c0a2f813-fb84-4923-b7a1-55cef0c5fc1b", "Maria de Sousa Example"),
            _no("54854c64-5845-40bb-a536-8c03da55420a", "F"),
            _no("a5bf96eb-8af0-4c05-bb76-a15f57f8490d", "Portuguesa"),
            _no("ed9a8413-b9f0-4d32-89bd-03593c826211", 2),
            _no("d155af2b-21e9-475f-be81-8e42bc5a5641", "123456789", visivel=False),
        ],
    )
    interesses = _no(
        "88ff2a6e-3702-4687-9f05-2738f70ccbd0",
        [
            _no(
                "2c6d9562-dea5-488b-9afe-42519c636daf",
                [
                    _linha(
                        "2c6d9562-dea5-488b-9afe-42519c636daf",
                        {
                            "col1": "Presidente",
                            "col2": "Fundação Exemplo",
                            "col3": "Setor público",
                            "col4": "Lisboa",
                            "col5": 1,
                            "col6": "2020-01-01T00:00:00Z",
                            "col7": "2024-01-01T00:00:00Z",
                            "col9": "500000000",
                        },
                    )
                ],
            )
        ],
    )
    raiz = {
        "key": "dab5b2ca-921a-4c8a-950a-5413e46625ab",
        "value": [
            _no("358af850-b811-494a-8a38-81eadaf9d695", [facto]),
            _no("7df770a3-e06b-4448-b5ac-c1b162c80fcc", [pessoais]),
            _no("1483a8d1-adca-4f39-8038-98cc6f728fcb", [interesses]),
            _no("a8dbe47f-c740-4edb-8605-451ed9fe6c87", 1),
        ],
        "isVisible": True,
    }
    return {
        "id": 123,
        "natureType": 1,
        "stateType": 8,
        "year": 2024,
        "entity": "Entidade Exemplo",
        "board": "Conselho de Administração",
        "role": "Presidente",
        "holder": "Maria de Sousa Example",
        "entityId": 10,
        "boardId": 20,
        "roleId": 30,
        "holderId": 40,
        "nif": "500000000",
        "startDate": "2024-01-02T00:00:00Z",
        "endDate": "2024-12-31T00:00:00Z",
        "submitedDate": "2024-01-10T10:00:00Z",
        "data": raiz,
    }


# ---------------------------------------------------------------------------
# Normalização
# ---------------------------------------------------------------------------


def test_declaracao_normalizada_tem_metadados_e_seccoes():
    documento = ept.normalize_declaration(_declaracao())
    assert documento["declaracao_id"] == "123"
    assert documento["titular"] == "Maria de Sousa Example"
    assert documento["natureza"] == "Inicial"
    assert documento["estado"] == "Publicada"
    assert documento["ano"] == 2024
    assert documento["doc_id"] == "ept:123"
    titulos = [secao["titulo"] for secao in documento["secoes"]]
    assert "Facto determinante da declaração" in titulos
    assert "Dados pessoais, morada e contactos" in titulos
    assert "Registo de interesses" in titulos


def test_campos_pessoais_ganham_rotulos_e_enums():
    documento = ept.normalize_declaration(_declaracao())
    dados = next(secao for secao in documento["secoes"] if secao["titulo"].startswith("Dados pessoais"))
    campos = {
        campo["rotulo"]: campo["valor"]
        for subsecao in dados["subsecoes"]
        for campo in subsecao["campos"]
    }
    assert campos["Nome completo"] == "Maria de Sousa Example"
    assert campos["Sexo"] == "Feminino"
    assert campos["Estado civil"] == "Divorciado(a)"


def test_campos_invisiveis_nao_saem_da_secao():
    documento = ept.normalize_declaration(_declaracao())
    texto = documento["texto"]
    assert "123456789" not in texto
    assert "Número de identificação fiscal" not in texto


def test_registo_de_interesses_extrai_tabela_rotulada():
    documento = ept.normalize_declaration(_declaracao())
    assert documento["tem_registo_interesses"] is True
    assert len(documento["interesses"]) == 1
    interesse = documento["interesses"][0]
    assert interesse["tipo"] == "Atividades profissionais, cargos e funções"
    assert interesse["valores"]["Cargo/Função/Atividade"] == "Presidente"
    assert interesse["valores"]["Entidade"] == "Fundação Exemplo"
    assert interesse["valores"]["Remuneração (se aplicável)"] == "Sim"
    assert interesse["valores"]["NIF/NIPC"] == "500000000"


def test_texto_agrega_rotulos_e_valores_sem_duplicar_caracteres():
    documento = ept.normalize_declaration(_declaracao())
    texto = documento["texto"]
    assert "Estado civil: Divorciado(a)" in texto
    assert "Fundação Exemplo" in texto
    assert "D\na\nd\no\ns" not in texto


def test_payload_completo_da_api_tambem_e_aceite():
    """`fetch_declaration` já devolve o interior; o envelope `{data: …}` também."""
    interior = _declaracao()
    envelope = {"code": 0, "description": "", "data": interior}
    documento = ept.normalize_declaration(envelope)
    assert documento["declaracao_id"] == "123"
    assert documento["titular"] == "Maria de Sousa Example"


def test_resumo_do_titular_agrega_anos_e_cargos():
    declaracoes = [
        {"ano": 2024, "natureza": "Inicial", "entidade": "E1", "cargo": "Presidente", "entrega": "2024-01-10"},
        {"ano": 2025, "natureza": "Cessação", "entidade": "E2", "cargo": "Vogal", "entrega": "2025-02-10"},
    ]
    documento = ept.titular_document("40", "Maria de Sousa Example", declaracoes)
    assert documento["titular_id"] == "40"
    assert documento["nome_normalizado"] == "maria de sousa example"
    assert documento["declaracoes_total"] == 2
    assert documento["anos"] == [2024, 2025]
    assert documento["entidades"] == ["E1", "E2"]
    assert documento["ultima_declaracao"] == "2025-02-10"


def test_normalize_name_ignora_acentos_e_pontuacao():
    assert ept.normalize_name("António Luís Santos da Costa") == "antonio luis santos da costa"
    assert ept.normalize_name("SILVA, José-Maria") == "silva jose maria"


# ---------------------------------------------------------------------------
# Serviço (JSONL e pesquisa sem Elasticsearch)
# ---------------------------------------------------------------------------


@pytest.fixture()
def pasta(monkeypatch: pytest.MonkeyPatch, tmp_path):
    monkeypatch.setenv("ENTIDADE_TRANSPARENCIA_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(esc, "get_es_client", lambda *args, **kwargs: None)
    return tmp_path


def test_pesquisa_de_recurso_le_o_jsonl(pasta):
    documento = ept.normalize_declaration(_declaracao(), recolhido_em="2026-01-01T00:00:00+00:00")
    svc._append_jsonl(svc._declaracoes_jsonl(), [documento])
    svc._append_jsonl(svc._titulares_jsonl(), [ept.titular_document("40", "Maria de Sousa Example", [documento])])

    resultado = svc.search_declaracoes("Maria")
    assert resultado["fonte"] == "disco"
    assert resultado["total"] == 1
    assert resultado["items"][0]["declaracao_id"] == "123"

    por_entidade = svc.search_declaracoes(None, entidade="Entidade Exemplo")
    assert por_entidade["total"] == 1
    por_ano = svc.search_declaracoes(None, ano=2025)
    assert por_ano["total"] == 0


def test_ficha_do_titular_em_disco(pasta):
    documento = ept.normalize_declaration(_declaracao(), recolhido_em="2026-01-01T00:00:00+00:00")
    svc._append_jsonl(svc._declaracoes_jsonl(), [documento])
    svc._append_jsonl(svc._titulares_jsonl(), [ept.titular_document("40", "Maria de Sousa Example", [documento])])

    ficha = svc.titular_detail("40", ao_vivo=False)
    assert ficha["titular"]["nome"] == "Maria de Sousa Example"
    assert ficha["declaracoes"]["total"] == 1
    assert ficha["declaracoes"]["items"][0]["declaracao_id"] == "123"


def test_detalhe_da_declaracao_em_disco(pasta):
    documento = ept.normalize_declaration(_declaracao(), recolhido_em="2026-01-01T00:00:00+00:00")
    svc._append_jsonl(svc._declaracoes_jsonl(), [documento])
    detalhe = svc.declaracao_detail("123")
    assert detalhe["declaracao_id"] == "123"
    assert detalhe["secoes"]
    assert detalhe["interesses"][0]["valores"]["Entidade"] == "Fundação Exemplo"


def test_exportacao_por_entidade_gera_um_json_por_entidade(pasta):
    """Cada entidade fica num `.json` próprio, com titulares e declarações."""
    svc._guardar_cache("entidades", [{"id": "10", "nome": "Entidade Exemplo"}])
    documento = ept.normalize_declaration(_declaracao(), recolhido_em="2026-01-01T00:00:00+00:00")
    svc._append_jsonl(svc._declaracoes_jsonl(), [documento])
    svc._append_jsonl(
        svc._titularidades_jsonl(),
        [
            {
                "titularidade_id": "900",
                "titular_id": "40",
                "titular": "Maria de Sousa Example",
                "entidade_id": "10",
                "entidade": "Entidade Exemplo",
                "cargo_id": "30",
                "cargo": "Presidente",
                "inicio": "2024-01-02",
                "fim": "2024-12-31",
            }
        ],
    )

    resultado = svc.exportar_entidades_json()
    assert resultado["entidades"] == 1
    assert resultado["declaracoes"] == 1

    caminho = svc.entidades_json_dir() / "10.json"
    assert caminho.exists()
    exportado = json.loads(caminho.read_text(encoding="utf-8"))
    assert exportado["entidade"] == "Entidade Exemplo"
    assert exportado["totais"] == {"titulares": 1, "declaracoes": 1}
    assert exportado["titulares"][0]["nome"] == "Maria de Sousa Example"
    assert exportado["titulares"][0]["cargos"] == ["Presidente"]
    assert exportado["titulares"][0]["declaracoes"][0]["declaracao_id"] == "123"
    assert (svc.entidades_json_dir() / "_index.json").exists()


def test_start_job_recusa_tipo_desconhecido():
    with pytest.raises(ValueError):
        svc.start_job("apagar-tudo")
