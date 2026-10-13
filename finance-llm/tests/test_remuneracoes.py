"""Remunerações dos eleitos locais (Lei n.º 11/96).

Testa-se o que **não** depende da rede nem do Elasticsearch:

* o escalão em que cai um território pelo número de eleitores — incluindo os
  limites de cada escalão, que é onde um erro de comparação (`<` por `<=`) daria
  um valor errado a milhares de freguesias;
* as verbas e os valores publicados, conferidos contra a aritmética do próprio
  despacho (a remuneração do presidente da junta é uma percentagem da remuneração
  do Presidente da República);
* o casamento dos nomes entre o MAI e a Wikidata, que é o que permite pôr a
  freguesia no sítio certo do mapa;
* as vistas de leitura (concelhos, ficha do município, mapa, estatísticas) e a
  importação de uma tabela nova, sobre uma árvore territorial sintética.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict

import pytest

from api import remuneracoes_service as remuneracoes

TABELA_REAL = (
    Path(__file__).resolve().parents[1] / "data" / "remuneracoes" / remuneracoes.TABELA_FILE
)


# ---------------------------------------------------------------------------
# Dados sintéticos
# ---------------------------------------------------------------------------

def _tabela_minima() -> Dict[str, Any]:
    return {
        "fonte": {"documento": "Tabela de teste", "base_legal": "Lei n.º 11/96"},
        "referencias": {"remuneracao_presidente_republica": 8550.10},
        "tabelas": [
            {
                "ano": 2026,
                "nivel": "freguesia",
                "titulo": "FREGUESIA - 2026",
                "escaloes": [
                    {"id": "grande", "designacao": "20 mil ou mais", "min_eleitores": 20000},
                    {"id": "media", "designacao": "10 mil a 20 mil", "min_eleitores": 10000, "max_eleitores": 20000},
                    {"id": "pequena", "designacao": "Menos de 5 mil", "max_eleitores": 5000},
                ],
                "rubricas": [
                    {
                        "id": "rem",
                        "regime": "Tempo Inteiro",
                        "grupo": "Remuneração mensal",
                        "cargo": "Presidentes",
                        "modalidade": "Exclusividade",
                        "natureza": "remuneracao",
                        "valores": {"grande": 2137.53, "media": 1881.02, "pequena": 1368.02},
                    },
                    {
                        "id": "rem-nao",
                        "regime": "Tempo Inteiro",
                        "grupo": "Remuneração mensal",
                        "cargo": "Presidentes",
                        "modalidade": "Não exclusividade (50%)",
                        "natureza": "remuneracao",
                        "valores": {"grande": 1068.77, "media": 940.51, "pequena": 684.01},
                    },
                ],
            },
            {
                "ano": 2026,
                "nivel": "municipio",
                "titulo": "MUNICÍPIO - 2026",
                "escaloes": [
                    {
                        "id": "mun-lisboa-porto",
                        "designacao": "Lisboa e Porto",
                        "municipios": ["Lisboa", "Porto"],
                        "percentagem_pr": 55.0,
                    },
                    {"id": "mun-grande", "designacao": "40 mil ou mais", "min_eleitores": 40000, "percentagem_pr": 50.0},
                    {
                        "id": "mun-medio",
                        "designacao": "Mais de 10 mil e menos de 40 mil",
                        "min_eleitores": 10001,
                        "max_eleitores": 40000,
                        "percentagem_pr": 45.0,
                    },
                    {"id": "mun-pequeno", "designacao": "10 mil ou menos", "max_eleitores": 10001, "percentagem_pr": 40.0},
                ],
                "rubricas": [
                    {
                        "id": "mun-rem",
                        "regime": "Tempo Inteiro",
                        "grupo": "Remuneração mensal",
                        "cargo": "Presidentes da Câmara Municipal",
                        "modalidade": "Permanência (exclusividade)",
                        "natureza": "remuneracao",
                        "percentagens": {
                            "mun-lisboa-porto": 55.0,
                            "mun-grande": 50.0,
                            "mun-medio": 45.0,
                            "mun-pequeno": 40.0,
                        },
                        "valores": {
                            "mun-lisboa-porto": 4703.0,
                            "mun-grande": 4276.0,
                            "mun-medio": 3848.0,
                            "mun-pequeno": 3421.0,
                        },
                    },
                ],
            },
        ],
    }


def _territorios() -> Dict[str, Any]:
    freguesias = [
        {"id": 11, "nome": "Sé", "eleitores": 25000, "concelho": "Teste", "concelho_id": 10, "distrito": "Porto"},
        {"id": 12, "nome": "União das freguesias de Aldeia e Souto", "eleitores": 8000, "concelho": "Teste", "concelho_id": 10, "distrito": "Porto"},
        {"id": 13, "nome": "Freguesia Pequena", "eleitores": 4000, "concelho": "Teste", "concelho_id": 10, "distrito": "Porto"},
    ]
    concelhos = [
        {
            "id": 10,
            "nome": "Teste",
            "distrito": "Porto",
            "eleitores": 37000,
            "votantes": 20000,
            "mandatos": 7,
            "freguesias": freguesias,
        },
        {"id": 20, "nome": "Outro", "distrito": "Faro", "eleitores": 9000, "votantes": 5000, "mandatos": 5, "freguesias": []},
    ]
    return {
        "cached_at": "2026-01-01T00:00:00Z",
        "fonte": "MAI (teste)",
        "fonte_url": "https://example.invalid",
        "distritos": [{"id": 1, "nome": "Porto", "concelhos": []}],
        "concelhos": concelhos,
        "freguesias": freguesias,
    }


def _geo() -> Dict[str, Any]:
    """Índice já **normalizado**, como o que `scripts/georreferenciar_remuneracoes.py` escreve.

    As chaves são nomes dobrados (minúsculas, sem acentos, sem prefixos), não os
    nomes de origem — é o serviço que as produz ao procurar.
    """
    return {
        "fonte": "Wikidata (teste)",
        "concelhos": {
            "por_nome": {"teste": {"nome": "Teste", "lat": 41.0, "lon": -8.0, "wikidata": "Q1"}},
            "por_nome_concelho": {},
        },
        "freguesias": {
            "por_nome": {
                # A Wikidata não usa o prefixo «União das freguesias de».
                "aldeia e souto": {"nome": "Aldeia e Souto", "lat": 41.1, "lon": -8.1, "wikidata": "Q2"},
            },
            "por_nome_concelho": {
                # «Sé» existe em muitos concelhos: só casa com o concelho certo.
                "se|teste": {"nome": "Sé", "lat": 41.15, "lon": -8.6, "wikidata": "Q4"},
            },
        },
    }


@pytest.fixture
def pasta(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Pasta de dados temporária, já com tabela, territórios e georreferenciação."""
    (tmp_path / remuneracoes.TABELA_FILE).write_text(
        json.dumps(_tabela_minima(), ensure_ascii=False), encoding="utf-8"
    )
    (tmp_path / remuneracoes.TERRITORIOS_FILE).write_text(
        json.dumps(_territorios(), ensure_ascii=False), encoding="utf-8"
    )
    (tmp_path / remuneracoes.GEO_FILE).write_text(
        json.dumps(_geo(), ensure_ascii=False), encoding="utf-8"
    )
    monkeypatch.setenv(remuneracoes.DATA_DIR_ENV, str(tmp_path))
    remuneracoes.limpar_cache()
    yield tmp_path
    remuneracoes.limpar_cache()


# ---------------------------------------------------------------------------
# Escalões
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("eleitores", "esperado"),
    [
        (0, "pequena"),
        (4999, "pequena"),
        (5000, "sem-escalao"),  # fora de todos: o mínimo é 10 mil, o máximo 5 mil
        (10000, "media"),
        (19999, "media"),
        (20000, "grande"),
        (500000, "grande"),
    ],
)
def test_escalao_por_eleitores(pasta: Path, eleitores: int, esperado: str) -> None:
    escalao = remuneracoes.escalao_por_eleitores("freguesia", eleitores)
    assert (escalao or {}).get("id", "sem-escalao") == esperado


def test_escalao_sem_eleitores(pasta: Path) -> None:
    assert remuneracoes.escalao_por_eleitores("freguesia", None) is None


def test_remuneracao_mensal_usa_a_exclusividade(pasta: Path) -> None:
    """A remuneração mensal é a do regime de exclusividade, não a de 50 %."""
    assert remuneracoes._remuneracao_mensal("freguesia", 25000) == 2137.53
    assert remuneracoes._remuneracao_mensal("freguesia", 8000) is None  # sem escalão


# ---------------------------------------------------------------------------
# Escalões dos municípios
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("eleitores", "esperado"),
    [
        (2981, "mun-pequeno"),
        (10000, "mun-pequeno"),   # «10 mil ou menos» é inclusivo
        (10001, "mun-medio"),     # «mais de 10 mil» começa em 10 001
        (39999, "mun-medio"),
        (40000, "mun-grande"),    # «40 mil ou mais» é inclusivo
        (168147, "mun-grande"),
    ],
)
def test_escalao_municipal_por_eleitores(pasta: Path, eleitores: int, esperado: str) -> None:
    """Os escalões dos municípios não são os das freguesias (10 mil / 40 mil)."""
    escalao = remuneracoes.escalao_por_eleitores("municipio", eleitores)
    assert (escalao or {}).get("id") == esperado


def test_escalao_municipal_de_lisboa_e_porto(pasta: Path) -> None:
    """Lisboa e Porto têm escalão próprio: 55 %, mesmo com muitos mais eleitores."""
    for nome in ("Lisboa", "Porto", "Município de Lisboa"):
        escalao = remuneracoes.escalao_por_eleitores("municipio", 500000, nome)
        assert (escalao or {}).get("id") == "mun-lisboa-porto"

    assert remuneracoes._remuneracao_mensal("municipio", 500000, None, "Lisboa") == 4703.0
    # Sem o nome não se adivinha: cai no escalão geral dos 40 mil ou mais.
    assert remuneracoes.escalao_por_eleitores("municipio", 500000)["id"] == "mun-grande"
    assert remuneracoes._remuneracao_mensal("municipio", 500000) == 4276.0


def test_abono_do_municipio_esta_preenchido(pasta: Path) -> None:
    """O abono mensal do presidente da câmara aparece na ficha do município."""
    resumo = remuneracoes.resumo_territorio("municipio", 37000)

    assert resumo["escalao_id"] == "mun-medio"
    assert resumo["percentagem_pr"] == 45.0
    assert resumo["remuneracao_mensal"] == 3848.0
    assert any(v["natureza"] == "remuneracao" for v in resumo["verbas"])


# ---------------------------------------------------------------------------
# Casamento de nomes (MAI ↔ Wikidata)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("nome", "chave"),
    [
        ("União das freguesias de Aldeia e Souto", "aldeia e souto"),
        ("Freguesia de Bemposta", "bemposta"),
        ("Região Autónoma dos Açores", "acores"),
        ("Município de Lisboa", "lisboa"),
        ("  Águeda  ", "agueda"),
    ],
)
def test_chave_territorio(nome: str, chave: str) -> None:
    assert remuneracoes.chave_territorio(nome) == chave


def test_variantes_territorio_cobre_parenteses_e_hifenes() -> None:
    variantes = remuneracoes.variantes_territorio("Funchal (Sé) (Funchal)")
    assert "funchal (se)" in variantes
    assert "funchal" in variantes
    assert "a dos francos" in remuneracoes.variantes_territorio("A-dos-Francos")


def test_variantes_territorio_tem_alias_do_mai() -> None:
    """O MAI usa a designação oficial; a Wikidata, a corrente."""
    assert "praia da vitoria" in remuneracoes.variantes_territorio("Vila da Praia da Vitória")


def test_coordenadas_usa_o_contexto_para_desfazer_homonimos(pasta: Path) -> None:
    """Há muitas freguesias «Sé»: o concelho é que decide qual é."""
    ponto = remuneracoes.coordenadas("freguesia", "Sé", "Teste")
    assert ponto and ponto["lat"] == 41.15
    # Com o concelho errado não se responde — nem se cai no nome solto.
    assert remuneracoes.coordenadas("freguesia", "Sé", "Outro") is None
    assert remuneracoes.coordenadas("freguesia", "Sé") is None


def test_coordenadas_tira_o_prefixo_de_uniao(pasta: Path) -> None:
    ponto = remuneracoes.coordenadas(
        "freguesia", "União das freguesias de Aldeia e Souto", "Teste"
    )
    assert ponto and ponto["wikidata"] == "Q2"


def test_coordenadas_de_concelho(pasta: Path) -> None:
    ponto = remuneracoes.coordenadas("municipio", "Teste", "Porto")
    assert ponto and ponto["lat"] == 41.0


# ---------------------------------------------------------------------------
# Vistas de leitura
# ---------------------------------------------------------------------------

def test_listar_concelhos_traz_escalao_e_coordenadas(pasta: Path) -> None:
    resposta = remuneracoes.listar_concelhos()
    assert resposta["total"] == 2
    teste = next(item for item in resposta["items"] if item["nome"] == "Teste")
    assert teste["eleitores"] == 37000
    assert teste["escalao"] == "Mais de 10 mil e menos de 40 mil"
    assert teste["remuneracao_mensal"] == 3848.0
    assert teste["lat"] == 41.0
    assert teste["total_freguesias"] == 3
    assert resposta["facets"]["distritos"] == ["Faro", "Porto"]


def test_listar_concelhos_filtra_por_eleitores_e_texto(pasta: Path) -> None:
    assert remuneracoes.listar_concelhos(min_eleitores=10000)["total"] == 1
    assert remuneracoes.listar_concelhos(q="faro")["total"] == 1
    assert remuneracoes.listar_concelhos(distrito="Porto")["total"] == 1


def test_concelho_detail_soma_as_freguesias(pasta: Path) -> None:
    ficha = remuneracoes.concelho_detail("Teste")
    assert ficha["total_freguesias"] == 3
    assert ficha["total_eleitores_freguesias"] == 37000
    assert all(f.get("lat") for f in ficha["freguesias"] if f["nome"] != "Freguesia Pequena")

    agregado = ficha["remuneracoes_freguesias"]
    # «Sé» (25 mil eleitores) vale o escalão grande; «Freguesia Pequena» (4 mil)
    # vale o pequeno; «União das freguesias…» (8 mil) cai fora dos escalões desta
    # tabela de teste (mínimo 10 mil), pelo que não soma nada.
    assert agregado["total_mensal_presidentes"] == round(2137.53 + 1368.02, 2)
    por_escalao = {linha["escalao_id"]: linha for linha in agregado["por_escalao"]}
    assert por_escalao["grande"]["freguesias"] == 1
    assert por_escalao["pequena"]["freguesias"] == 1
    assert por_escalao["sem-escalao"]["freguesias"] == 1
    assert por_escalao["sem-escalao"]["remuneracao_mensal"] is None


def test_concelho_detail_por_id_e_inexistente(pasta: Path) -> None:
    assert remuneracoes.concelho_detail("10")["nome"] == "Teste"
    assert "error" in remuneracoes.concelho_detail("Lisboa")


def test_mapa_de_concelhos_e_de_freguesias(pasta: Path) -> None:
    pais = remuneracoes.mapa()
    assert pais["nivel"] == "concelho"
    assert pais["total"] == 2
    assert pais["sem_coordenadas"] == ["Outro"]
    teste = next(f for f in pais["features"] if f["nome"] == "Teste")
    assert (teste["lat"], teste["lon"]) == (41.0, -8.0)

    locais = remuneracoes.mapa(nivel="freguesia", concelho="Teste")
    assert locais["nivel"] == "freguesia"
    assert locais["total"] == 3
    assert "Freguesia Pequena" in locais["sem_coordenadas"]


def test_freguesias_nao_traz_verbas_nem_poligonos(pasta: Path) -> None:
    resposta = remuneracoes.freguesias(concelho="Teste")
    assert resposta["total"] == 3
    assert resposta["items"][0]["verbas"] == []
    assert "poligono" not in resposta["items"][0]


def test_stats_conta_a_cobertura_do_mapa(pasta: Path) -> None:
    resumo = remuneracoes.stats()
    assert resumo["total_concelhos"] == 2
    assert resumo["total_freguesias"] == 3
    assert resumo["total_eleitores_concelhos"] == 46000
    assert resumo["concelhos_com_coordenadas"] == 1
    assert resumo["freguesias_com_coordenadas"] == 2
    assert resumo["fonte_geo"] == "Wikidata (teste)"


def test_simular(pasta: Path) -> None:
    resumo = remuneracoes.resumo_territorio("freguesia", 25000)
    assert resumo["escalao_id"] == "grande"
    assert resumo["percentagem_pr"] is None  # a tabela de teste não a define
    # A verba vem com o valor do escalão; as restantes ficam a null.
    valores = {v["id"]: v["valor"] for v in resumo["verbas"]}
    assert valores["rem"] == 2137.53
    assert valores["rem-nao"] == 1068.77


# ---------------------------------------------------------------------------
# Importação da tabela
# ---------------------------------------------------------------------------

def test_importar_tabela_recusa_nivel_invalido(pasta: Path) -> None:
    assert "error" in remuneracoes.importar_tabela({"ano": 2026, "nivel": "distrito", "escaloes": [{"id": "a", "designacao": "A"}]})
    assert "error" in remuneracoes.importar_tabela({"ano": 2026, "nivel": "municipio", "escaloes": []})
    assert "error" in remuneracoes.importar_tabela({"nivel": "municipio", "escaloes": [{"id": "a", "designacao": "A"}]})


def test_importar_tabela_substitui_a_mesma_combinacao(
    pasta: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A importação reindexa: sem isto, a tabela de teste iria para o índice a sério.
    import api.elasticsearch_client as es

    monkeypatch.setattr(es, "get_es_client", lambda: None)

    nova = {
        "ano": 2026,
        "nivel": "municipio",
        "titulo": "MUNICÍPIO - 2026",
        "escaloes": [{"id": "mun-grande", "designacao": "20 mil ou mais", "min_eleitores": 20000}],
        "rubricas": [
            {
                "id": "mun-rem",
                "regime": "Tempo Inteiro",
                "grupo": "Remuneração mensal",
                "cargo": "Presidente",
                "natureza": "remuneracao",
                "valores": {"mun-grande": 4300.0},
            }
        ],
    }
    resultado = remuneracoes.importar_tabela(nova)
    assert resultado["imported"] == 1 and resultado["total_rubricas"] == 1

    escrita = json.loads(
        (pasta / remuneracoes.TABELA_FILE).read_text(encoding="utf-8")
    )
    municipios = [t for t in escrita["tabelas"] if t["nivel"] == "municipio"]
    assert len(municipios) == 1, "importar o mesmo ano+nível deve substituir, não duplicar"
    assert municipios[0]["rubricas"][0]["id"] == "mun-rem"
    # A tabela das freguesias não é tocada.
    assert any(t["nivel"] == "freguesia" for t in escrita["tabelas"])


def test_importar_tabela_reindexa_so_a_tabela(pasta: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A importação indexa a tabela; não precisa de mexer nos territórios."""
    chamadas: Dict[str, Any] = {}

    import api.elasticsearch_client as es

    monkeypatch.setattr(es, "get_es_client", lambda: object())
    monkeypatch.setattr(
        es,
        "index_remuneracoes_bulk",
        lambda itens, es=None: chamadas.setdefault("tabela", len(list(itens))) and {"indexed": 1},
    )
    monkeypatch.setattr(
        es,
        "index_remuneracoes_territorios_bulk",
        lambda itens, es=None: chamadas.setdefault("territorios", True) and {"indexed": 1},
    )
    remuneracoes.importar_tabela({"ano": 2025, "nivel": "municipio", "escaloes": [{"id": "a", "designacao": "A"}]})
    assert "tabela" in chamadas
    assert "territorios" not in chamadas


# ---------------------------------------------------------------------------
# Documentos a indexar
# ---------------------------------------------------------------------------

def test_docs_da_tabela_uma_linha_por_rubrica(pasta: Path) -> None:
    documentos = {doc["doc_id"]: doc for doc in remuneracoes._docs_tabela()}
    assert set(documentos) == {"rem", "rem-nao", "mun-rem"}
    rem = documentos["rem"]
    assert rem["ano"] == 2026 and rem["nivel"] == "freguesia"
    assert len(rem["valores"]) == 3
    grande = next(v for v in rem["valores"] if v["escalao_id"] == "grande")
    assert grande["valor"] == 2137.53
    assert grande["max_eleitores"] is None
    # O escalão decidido pelo município leva os municípios no documento.
    municipio = documentos["mun-rem"]
    assert municipio["nivel"] == "municipio"
    lisboa = next(v for v in municipio["valores"] if v["escalao_id"] == "mun-lisboa-porto")
    assert lisboa["municipios"] == ["Lisboa", "Porto"]
    assert lisboa["valor"] == 4703.0


def test_docs_dos_territorios_trazem_localizacao(pasta: Path) -> None:
    documentos = {doc["doc_id"]: doc for doc in remuneracoes._docs_territorios()}
    assert "concelho-10" in documentos
    assert "freguesia-11" in documentos
    teste = documentos["concelho-10"]
    assert teste["localizacao"] == {"lat": 41.0, "lon": -8.0}
    # A freguesia «Sé» só tem coordenadas pelo contexto (o concelho).
    se = documentos["freguesia-11"]
    assert se["localizacao"] == {"lat": 41.15, "lon": -8.6}
    # Uma freguesia sem coordenadas não deve trazer um `localizacao` inválido.
    pequena = documentos["freguesia-13"]
    assert pequena["localizacao"] is None


def _eleitos() -> Dict[str, Any]:
    """Eleitos como os do MAI: presidente com nome e lista + câmara por partido."""
    return {
        "cached_at": "2026-01-02T00:00:00Z",
        "fonte": "MAI (teste)",
        "fonte_url": "https://example.invalid",
        "eleicao": "Autárquicas 2025",
        "nota": "O MAI não publica os nomes dos vereadores.",
        "total_concelhos": 2,
        "total_com_presidente": 2,
        "concelhos": {
            "10": {
                "id": 10,
                "nome": "Teste",
                "distrito": "Porto",
                "eleitores": 37000,
                "presidente": {"nome": "Ana Presidente", "sigla": "PS", "partido": "Partido Socialista"},
                "camara": [
                    {"sigla": "PS", "votos": 9000, "percentagem": 45.0, "mandatos": 4, "presidentes": 1, "vereadores": 3},
                    {"sigla": "PPD/PSD", "votos": 6000, "percentagem": 30.0, "mandatos": 3, "presidentes": 0, "vereadores": 3},
                    {"sigla": "CH", "votos": 2000, "percentagem": 10.0, "mandatos": 0, "presidentes": 0, "vereadores": 0},
                ],
            },
            "20": {
                "id": 20,
                "nome": "Outro",
                "distrito": "Faro",
                "eleitores": 9000,
                "presidente": {"nome": "Bruno Presidente", "sigla": "PPD/PSD", "partido": "Partido Social Democrata"},
                "camara": [
                    {"sigla": "PPD/PSD", "votos": 4000, "percentagem": 50.0, "mandatos": 5, "presidentes": 1, "vereadores": 4},
                ],
            },
        },
    }


@pytest.fixture
def pasta_eleitos(pasta: Path) -> Path:
    """A mesma pasta de dados, já com os eleitos recolhidos."""
    (pasta / remuneracoes.ELEITOS_FILE).write_text(
        json.dumps(_eleitos(), ensure_ascii=False), encoding="utf-8"
    )
    remuneracoes.limpar_cache()
    yield pasta
    remuneracoes.limpar_cache()


# ---------------------------------------------------------------------------
# Eleitos (Autárquicas 2025)
# ---------------------------------------------------------------------------

def test_camara_partidos_calcula_vereadores(monkeypatch: pytest.MonkeyPatch) -> None:
    """Os vereadores de cada força são os mandatos da lista menos a presidência."""
    payload = {
        "data": {
            "currentResults": {
                "totalMandates": 11,
                "resultsParty": [
                    {"id": 1, "acronym": "A", "votes": 100, "percentage": 40.0, "mandates": 4, "presidents": 1},
                    {"id": 2, "acronym": "B", "votes": 90, "percentage": 35.0, "mandates": 4, "presidents": 0},
                    {"id": 3, "acronym": "C", "votes": 10, "percentage": 5.0, "mandates": 0, "presidents": 0},
                ],
            }
        }
    }
    monkeypatch.setattr(remuneracoes, "_get_json", lambda *a, **k: payload)

    partidos = remuneracoes._camara_partidos(object(), 10)

    assert [p["sigla"] for p in partidos] == ["A", "B", "C"]
    assert [p["vereadores"] for p in partidos] == [3, 4, 0]
    # A soma continua a fechar com os mandatos da câmara.
    assert sum(p["mandatos"] for p in partidos) == 8


def test_presidentes_camara_percorre_as_paginas(monkeypatch: pytest.MonkeyPatch) -> None:
    """Os eleitos vêm em páginas nacionais; o serviço lê todas."""
    paginas = {
        1: {
            "data": {
                "numberOfPages": 2,
                "territories": [
                    {
                        "id": 2,
                        "description": "Aveiro",
                        "territories": [
                            {
                                "id": 10,
                                "description": "Teste",
                                "votingOptions": [
                                    {
                                        "votingOption": {"id": 5, "name": "PS", "description": "Partido Socialista"},
                                        "candidates": [
                                            {"position": 1, "name": "Ana Presidente", "state": "President"},
                                            {"position": 2, "name": "Um Vereador", "state": "Vereador"},
                                        ],
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        },
        2: {
            "data": {
                "numberOfPages": 2,
                "territories": [
                    {
                        "id": 9,
                        "description": "Faro",
                        "territories": [
                            {
                                "id": 20,
                                "description": "Outro",
                                "votingOptions": [
                                    {
                                        "votingOption": {"id": 6, "name": "PPD/PSD", "description": "PSD"},
                                        "candidates": [{"position": 1, "name": "Bruno Presidente", "state": "President"}],
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        },
    }

    def falso_get(client, url: str, *a, **k):
        for pagina, payload in paginas.items():
            if f"-page={pagina}.json" in url:
                return payload
        return None

    monkeypatch.setattr(remuneracoes, "_get_json", falso_get)

    presidentes = remuneracoes._presidentes_camara(object())

    assert set(presidentes) == {"10", "20"}
    assert presidentes["10"]["nome"] == "Ana Presidente"
    # Só o eleito para a presidência é considerado; os restantes ficam de fora.
    assert presidentes["10"]["sigla"] == "PS"
    assert presidentes["20"]["nome"] == "Bruno Presidente"


def test_eleitos_concelho_junta_os_votos_da_lista(pasta_eleitos: Path) -> None:
    """O nome vem do ficheiro dos eleitos; os votos, dos resultados da câmara."""
    detalhe = remuneracoes.eleitos_concelho(10)

    assert detalhe["presidente"]["nome"] == "Ana Presidente"
    assert detalhe["presidente"]["votos"] == 9000
    assert detalhe["presidente"]["percentagem"] == 45.0
    assert detalhe["presidente"]["vereadores"] == 3
    assert detalhe["vereadores"]["total"] == 6
    assert detalhe["vereadores"]["total_mandatos"] == 7
    # As listas sem mandato não fazem parte da composição da câmara.
    assert [p["sigla"] for p in detalhe["vereadores"]["por_partido"]] == ["PS", "PPD/PSD"]
    assert detalhe["eleicao"] == "Autárquicas 2025"
    assert remuneracoes.eleitos_concelho(9999) is None


def test_concelho_detail_traz_os_eleitos(pasta_eleitos: Path) -> None:
    detalhe = remuneracoes.concelho_detail("Teste")

    assert detalhe["eleitos"]["presidente"]["nome"] == "Ana Presidente"
    assert detalhe["eleitos"]["vereadores"]["total"] == 6


def test_listar_eleitos_filtra_e_pagina(pasta_eleitos: Path) -> None:
    todos = remuneracoes.listar_eleitos()
    assert todos["total"] == 2
    assert [item["concelho"] for item in todos["items"]] == ["Outro", "Teste"]
    assert todos["facets"]["partidos"] == ["PPD/PSD", "PS"]

    do_parto = remuneracoes.listar_eleitos(distrito="Porto")
    assert do_parto["total"] == 1
    assert do_parto["items"][0]["presidente"]["nome"] == "Ana Presidente"

    por_partido = remuneracoes.listar_eleitos(partido="PSD")
    assert por_partido["total"] == 1
    assert por_partido["items"][0]["concelho"] == "Outro"

    por_nome = remuneracoes.listar_eleitos(q="ana")
    assert por_nome["total"] == 1

    pagina = remuneracoes.listar_eleitos(page=2, size=1)
    assert pagina["total"] == 2
    assert len(pagina["items"]) == 1


def test_listar_eleitos_sem_recolha_explica_o_que_falta(pasta: Path) -> None:
    """Sem eleitos recolhidos a lista não rebenta: diz o que há a correr."""
    resposta = remuneracoes.listar_eleitos()

    assert resposta["total"] == 0
    assert resposta["items"] == []
    assert "eleitos/recolher" in resposta["aviso"]


def test_docs_dos_territorios_trazem_presidente(pasta_eleitos: Path) -> None:
    documentos = {doc["doc_id"]: doc for doc in remuneracoes._docs_territorios()}
    teste = documentos["concelho-10"]

    assert teste["presidente"] == "Ana Presidente"
    assert teste["partido"] == "PS"
    assert teste["vereadores"] == 6
    assert [linha["sigla"] for linha in teste["camara"]] == ["PS", "PPD/PSD"]
    # Nas freguesias não há eleitos: o município é que tem câmara.
    assert documentos["freguesia-11"]["presidente"] is None


def test_stats_contam_os_vereadores(pasta_eleitos: Path) -> None:
    stats = remuneracoes.stats()

    assert stats["eleitos"]["total_concelhos"] == 2
    assert stats["eleitos"]["com_presidente"] == 2
    assert stats["eleitos"]["total_vereadores"] == 10
    assert stats["eleitos"]["partidos_com_presidente"] == 2


# ---------------------------------------------------------------------------
# Recolha completa (refresh)
# ---------------------------------------------------------------------------

def _sem_rede(monkeypatch: pytest.MonkeyPatch) -> Dict[str, Any]:
    """Substitui a recolha do MAI e a indexação por versões em memória."""
    chamadas: Dict[str, Any] = {"indexar": 0}

    def falso_collect(incluir_freguesias: bool = True, forcar: bool = False) -> Dict[str, Any]:
        chamadas["collect"] = (incluir_freguesias, forcar)
        return _territorios()

    monkeypatch.setattr(remuneracoes, "collect_territories", falso_collect)
    monkeypatch.setattr(
        remuneracoes, "indexar", lambda apenas_tabelas=False: chamadas.__setitem__("indexar", chamadas["indexar"] + 1) or {}
    )
    return chamadas


def test_refresh_georreferencia_quando_nao_ha_coordenadas(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sem `geo_territorios.json` à vista, o refresh vai buscá-las."""
    monkeypatch.setenv(remuneracoes.DATA_DIR_ENV, str(tmp_path))
    remuneracoes.limpar_cache()
    chamadas = _sem_rede(monkeypatch)
    monkeypatch.setattr(remuneracoes, "georreferenciar", lambda: chamadas.__setitem__("geo", True) or _geo())

    resultado = remuneracoes.refresh()

    assert chamadas["geo"] is True
    assert resultado["total_concelhos"] == 2
    assert "geo" in resultado
    assert chamadas["indexar"] == 1
    remuneracoes.limpar_cache()


def test_refresh_nao_repete_a_georreferenciacao(pasta: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Com coordenadas já em disco, não se volta a incomodar a Wikidata."""
    chamadas = _sem_rede(monkeypatch)
    monkeypatch.setattr(remuneracoes, "georreferenciar", lambda: chamadas.__setitem__("geo", True) or {})

    resultado = remuneracoes.refresh(incluir_freguesias=False)

    assert "geo" not in chamadas
    assert "geo" not in resultado
    assert chamadas["collect"] == (False, False)


# ---------------------------------------------------------------------------
# A tabela oficial versionada
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not TABELA_REAL.exists(), reason="tabela oficial não está em disco")
def test_tabela_oficial_esta_completa() -> None:
    """A tabela de 2026 transcrita do despacho: 13 rubricas e 5 escalões."""
    remuneracoes.limpar_cache()
    tabela = remuneracoes.tabela("freguesia", 2026)
    assert tabela and tabela["estado"] == "verificada"
    assert len(tabela["escaloes"]) == 5
    assert len(tabela["rubricas"]) == 13

    escaloes = [e["designacao"] for e in tabela["escaloes"]]
    assert escaloes[0] == "20 mil ou mais eleitores"
    assert escaloes[-1] == "Menos de 5 mil eleitores"

    # A tabela dos municípios tem fonte e base legal próprias (ANMP / Lei n.º 29/87)
    # e escalões diferentes dos das freguesias: Lisboa e Porto primeiro.
    municipio = remuneracoes.tabela("municipio", 2026)
    assert municipio and municipio["estado"] == "verificada"
    assert len(municipio["escaloes"]) == 4
    assert municipio["escaloes"][0]["municipios"] == ["Lisboa", "Porto"]
    assert municipio["escaloes"][0]["percentagem_pr"] == 55.0
    assert municipio["escaloes"][-1]["percentagem_pr"] == 40.0
    assert "29/87" in municipio["fonte"]["base_legal"]
    assert len(municipio["rubricas"]) == 9


@pytest.mark.skipif(not TABELA_REAL.exists(), reason="tabela oficial não está em disco")
def test_municipios_batem_certo_com_as_percentagens() -> None:
    """A tabela dos municípios: % do PR arredondada para cima, ao euro."""
    remuneracoes.limpar_cache()
    municipio = remuneracoes.tabela("municipio", 2026)
    pr = remuneracoes.abonos()["referencias"]["remuneracao_presidente_republica"]
    assert pr == 8550.10

    presidentes = next(r for r in municipio["rubricas"] if r["id"] == "mun-ti-remuneracao-presidentes")
    for escalao in municipio["escaloes"]:
        escalao_id = escalao["id"]
        esperado = math.ceil(pr * escalao["percentagem_pr"] / 100)
        assert presidentes["valores"][escalao_id] == float(esperado)
        # A percentagem publicada é a do escalão; a calculada confere com o valor.
        assert presidentes["percentagens"][escalao_id] == escalao["percentagem_pr"]

    # Vereadores a tempo inteiro = 80 % do presidente; meio tempo = 50 % disso.
    vereadores = next(r for r in municipio["rubricas"] if r["id"] == "mun-ti-remuneracao-vereadores")
    meio_tempo = next(r for r in municipio["rubricas"] if r["id"] == "mun-mt-remuneracao-vereadores")
    for escalao in municipio["escaloes"]:
        escalao_id = escalao["id"]
        assert vereadores["valores"][escalao_id] == round(presidentes["valores"][escalao_id] * 0.8, 2)
        assert meio_tempo["valores"][escalao_id] == round(vereadores["valores"][escalao_id] * 0.5, 2)


@pytest.mark.skipif(not TABELA_REAL.exists(), reason="tabela oficial não está em disco")
def test_valores_da_tabela_batem_certo_com_as_percentagens() -> None:
    """A aritmética do despacho: a % do PR e a % do presidente de câmara."""
    remuneracoes.limpar_cache()
    tabela = remuneracoes.tabela("freguesia", 2026)
    pr = remuneracoes.abonos()["referencias"]["remuneracao_presidente_republica"]
    assert pr == 8550.10
    camara = remuneracoes.abonos()["referencias"][
        "remuneracao_presidente_camara_municipio_10mil_ou_menos_eleitores"
    ]
    assert camara == 3421.00

    for escalao in tabela["escaloes"]:
        valor = remuneracoes._remuneracao_mensal("freguesia", escalao["min_eleitores"] or 1000)
        esperado = round(pr * escalao["percentagem_pr"] / 100, 2)
        assert valor == esperado, f"{escalao['designacao']}: {valor} != {esperado}"

    # Compensação para encargos: 12 %, 10 % e 9 % da remuneração do presidente
    # da câmara de município com 10 mil ou menos eleitores.
    compensacao = next(
        r for r in tabela["rubricas"] if r["id"] == "freg-np-compensacao-presidentes"
    )
    for escalao_id, percentagem in compensacao["percentagens"].items():
        if percentagem is None:
            continue
        assert compensacao["valores"][escalao_id] == round(camara * percentagem / 100, 2)

    # Secretários e tesoureiros: 80 % da compensação do presidente.
    secretarios = next(
        r for r in tabela["rubricas"] if r["id"] == "freg-np-compensacao-secretarios-tesoureiros"
    )
    for escalao_id, valor in secretarios["valores"].items():
        if valor is None:
            continue
        assert valor == round(compensacao["valores"][escalao_id] * 0.8, 2)
