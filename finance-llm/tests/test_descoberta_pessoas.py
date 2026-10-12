"""Testes da descoberta de **pessoas** (`api/descoberta_pessoas.py`).

Sem Elasticsearch: a ficha de empresa no PessoasIQ, os processos do CIRE e as
listas de devedores são substituídos por versões sintéticas. Testa-se o que é
nosso — a fusão das empresas numa lista de pessoas, a classificação dos cargos,
a ordem de leitura, os pontos de atenção, a síntese, o grafo e a validação dos
pedidos.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from api import descoberta_pessoas as dp  # noqa: E402


def _cargo(role: str, *, role_org: str = "", data: str = "2024-01-10", quota: float | None = None) -> dict:
    return {
        "role": role,
        "role_org": role_org,
        "event": "designacao",
        "date": data,
        "acto": "Designação de membro(s) de órgão(s) social(ais)",
        "publication_id": f"pub-{role}-{data}",
        "quota": quota,
        "causa": None,
        "tribunal": None,
        "nacionalidade": None,
    }


def _pessoa(
    nif: str,
    nome: str,
    cargos: list[dict],
    *,
    is_company: bool = False,
    roles_total: int | None = None,
    companies_total: int = 1,
    outras: list[dict] | None = None,
) -> dict:
    return {
        "nif": nif,
        "name": nome,
        "is_company": is_company,
        "cargos_empresa": len(cargos),
        "cargo": cargos[0]["role"] if cargos else "",
        "role_org": cargos[0]["role_org"] if cargos else "",
        "event": cargos[0]["event"] if cargos else "",
        "date": cargos[0]["date"] if cargos else "",
        "acto": cargos[0]["acto"] if cargos else "",
        "roles_total": roles_total if roles_total is not None else len(cargos),
        "companies_total": companies_total,
        "origin": "publicacoes_mj",
        "origens": ["publicacoes_mj"],
        "outras_empresas": outras or [],
        "roles": cargos,
    }


def _ficha_empresa(nif: str, nome: str, pessoas: list[dict]) -> dict:
    return {"nif": nif, "name": nome, "total": len(pessoas), "people": pessoas}


#: Duas empresas que partilham um gerente (o caso que só existe com duas).
FICHAS = {
    "111111111": _ficha_empresa(
        "111111111",
        "Alfa, S.A.",
        [
            _pessoa(
                "200000001",
                "Ana Silva",
                [_cargo("Gerente", role_org="Gerência"), _cargo("Sócia", role_org="Sócios e Quotas", quota=60000.0)],
                roles_total=7,
                companies_total=3,
                outras=[{"nif": "999999999", "nome": "Delta, Lda."}],
            ),
            _pessoa("200000002", "Bruno Costa", [_cargo("Vogal", role_org="Conselho De Administração")]),
        ],
    ),
    "222222222": _ficha_empresa(
        "222222222",
        "Beta, Lda.",
        [
            _pessoa("200000001", "Ana Silva", [_cargo("Gerente", role_org="Gerência")], roles_total=7, companies_total=3),
            _pessoa("200000003", "Carla Dias", [_cargo("Credor")], roles_total=1),
            _pessoa("200000004", "Revisores & Associados, Lda.", [_cargo("Fiscal Único")], is_company=True),
        ],
    ),
    "333333333": _ficha_empresa("333333333", "Gama, Lda.", []),
}


@pytest.fixture()
def descoberta(monkeypatch):
    """`descobrir()` com as fontes substituídas por dados sintéticos."""

    def fake_empresa(nif, *, size=0, es=None):
        return FICHAS.get(str(nif), {"nif": str(nif), "total": 0, "people": [], "name": ""})

    def fake_cire(*, nif=None, size=0, **kwargs):
        if str(nif) == "222222222":
            return {
                "total": 2,
                "items": [
                    {
                        "processo_numero": "123/24.0T8ABC",
                        "especie": "Insolvência",
                        "ato": "Sentença de declaração de insolvência",
                        "tribunal": "Tribunal Judicial da Comarca de Lisboa",
                        "data_publicacao": "2024-05-02",
                        "insolvente": "Beta, Lda.",
                        "intervenientes": [
                            {"papel": "Insolvente", "nome": "Beta, Lda.", "nif": "222222222"},
                            {"papel": "Credor", "nome": "Carla Dias", "nif": "200000003"},
                            {"papel": "Administrador Insolvência", "nome": "Rui Nunes", "nif": "200000009"},
                        ],
                    }
                ],
            }
        return {"total": 0, "items": []}

    def fake_devedores(nif, *, es=None):
        if str(nif) == "200000003":
            return {
                "nif": str(nif),
                "total": 2,
                "devedor": True,
                "entidades": ["Finanças", "Segurança Social"],
                "escaloes": ["mais de 50.000 €"],
                "maior_valor_min": 50000.0,
            }
        return {"nif": str(nif), "total": 0, "devedor": False, "entidades": [], "escaloes": []}

    def fake_contratos(*, nif=None, size=0, **kwargs):
        # Alfa vende à Delta (fora do pedido) e à Beta (dentro do pedido).
        if str(nif) == "111111111":
            return {
                "total": 2,
                "items": [
                    {
                        "precoContratual": 100000.0,
                        "adjudicantes": {"parsed": [{"nif": "999999999", "nome": "Delta, Lda."}]},
                        "adjudicatarios": {"parsed": [{"nif": "111111111", "nome": "Alfa, S.A."}]},
                    },
                    {
                        "precoContratual": 5000.0,
                        "adjudicantes": {"parsed": [{"nif": "222222222", "nome": "Beta, Lda."}]},
                        "adjudicatarios": {"parsed": [{"nif": "111111111", "nome": "Alfa, S.A."}]},
                    },
                ],
            }
        return {"total": 0, "items": []}

    def fake_resolver(texto, *, size=8):
        return {"query": texto, "items": [{"nif": "222222222", "nome": "Beta, Lda."}], "candidatos": []}

    monkeypatch.setattr(dp.es_client, "company_people_from_index", fake_empresa)
    monkeypatch.setattr(dp.es_client, "get_es_client", lambda: None)
    monkeypatch.setattr(dp.es_client, "search_contracts", fake_contratos)
    monkeypatch.setattr(dp.cire_service, "search", fake_cire)
    monkeypatch.setattr(dp.devedores_service, "por_nif", fake_devedores)
    monkeypatch.setattr(dp.service, "resolver", fake_resolver)
    return dp.descobrir(nifs=["111111111", "222222222", "333333333"])


def test_funde_as_pessoas_das_empresas(descoberta):
    pessoas = {pessoa["nome"]: pessoa for pessoa in descoberta["pessoas"]}
    ana = pessoas["Ana Silva"]
    assert ana["empresas_pedido"] == 2
    assert ana["ligacao"] is True
    assert ana["cargos_pedido"] == 3
    assert ana["empresas_universo"] == 3
    assert [empresa["nome"] for empresa in ana["empresas"]] == ["Alfa, S.A.", "Beta, Lda."]
    assert ana["outras_empresas"] == [{"nif": "999999999", "nome": "Delta, Lda."}]
    assert descoberta["kpis"]["pessoas"] == 4
    assert descoberta["kpis"]["em_varias"] == 1


def test_ordem_e_classes_por_pessoa(descoberta):
    # Gestão primeiro (e quem liga empresas antes de quem só aparece numa).
    assert descoberta["pessoas"][0]["nome"] == "Ana Silva"
    classes = {pessoa["nome"]: pessoa["classe"] for pessoa in descoberta["pessoas"]}
    assert classes["Ana Silva"] == "gestao"
    assert classes["Bruno Costa"] == "gestao"
    assert classes["Carla Dias"] == "processo"
    assert classes["Revisores & Associados, Lda."] == "outro"


def test_classificacao_dos_cargos():
    assert dp._classe_cargo(_cargo("Gerente", role_org="Gerência")) == "gestao"
    assert dp._classe_cargo(_cargo("Sócia", role_org="Sócios e Quotas", quota=1000.0)) == "capital"
    # «Administrador da insolvência» contém «administrador», mas é processo.
    assert dp._classe_cargo(_cargo("Administrador da insolvência")) == "processo"
    assert dp._classe_cargo(_cargo("Credor")) == "processo"
    assert dp._classe_cargo(_cargo("Fiscal Único")) == "outro"


def test_titulo_limpa_o_ruido_da_publicacao():
    # A publicação cola a causa e a data ao cargo: o título acaba antes disso.
    assert dp._titulo(_cargo("Vogal Causa: renúncia Data: 2022.04.30", role_org="Gerência")) == "Vogal"
    assert dp._titulo(_cargo("Presidente NIF/NIPC: 211835900 Causa: Renúncia")) == "Presidente"
    assert dp._titulo(_cargo("Gerente", role_org="Gerência")) == "Gerente"
    # Sem cargo, o órgão é o que resta para dizer.
    assert dp._titulo(_cargo("", role_org="Conselho De Administração")) == "Conselho De Administração"
    assert dp._titulo({}) == ""


def test_titulos_por_pessoa(descoberta):
    ana = next(pessoa for pessoa in descoberta["pessoas"] if pessoa["nome"] == "Ana Silva")
    assert ana["titulo"] == "Gerente"
    assert ana["titulos"] == ["Gerente", "Sócia"]
    alfa = next(empresa for empresa in ana["empresas"] if empresa["nif"] == "111111111")
    assert alfa["titulo"] == "Gerente"
    assert alfa["cargos"][0]["titulo"] == "Gerente"


def test_titulos_nao_contam_a_mesma_grafia_duas_vezes():
    # As publicações escrevem o mesmo cargo de formas diferentes («Vogal», «VOGAL»).
    pessoa = {
        "empresas": [
            {"cargos": [{"titulo": "Vogal"}, {"titulo": "VOGAL"}, {"titulo": "vogal"}]},
            {"cargos": [{"titulo": "Presidente"}]},
        ]
    }
    assert dp._titulos(pessoa) == ["Vogal", "Presidente"]


def test_quota_marca_o_capital(descoberta):
    ana = next(pessoa for pessoa in descoberta["pessoas"] if pessoa["nome"] == "Ana Silva")
    assert ana["quota"] == 60000.0
    assert ana["capital"] is True
    assert descoberta["kpis"]["capital"] == 1
    fontes = {fonte["id"]: fonte for fonte in descoberta["fontes"]}
    assert fontes["quotas"]["estado"] == "ok"
    assert fontes["quotas"]["total"] == 1


def test_ligacoes_dizem_quem_liga_as_empresas(descoberta):
    ligacoes = descoberta["ligacoes"]
    assert len(ligacoes) == 1
    assert ligacoes[0]["nome"] == "Ana Silva"
    assert [empresa["nome"] for empresa in ligacoes[0]["empresas"]] == ["Alfa, S.A.", "Beta, Lda."]
    assert ligacoes[0]["empresas_pedido"] == 2


def test_cire_anota_quem_e_nomeado_nos_processos(descoberta):
    carla = next(pessoa for pessoa in descoberta["pessoas"] if pessoa["nome"] == "Carla Dias")
    assert [item["papel"] for item in carla["cire"]] == ["Credor"]
    assert carla["cire"][0]["processo"] == "123/24.0T8ABC"
    assert carla["cire"][0]["empresa"] == "Beta, Lda."
    # O insolvente é a própria empresa: não entra como pessoa da lista.
    assert all(item["papel"] != "Insolvente" or item["nome"] != "Beta, Lda." for item in carla["cire"])


def test_devedores_geram_alerta_e_fonte(descoberta):
    carla = next(pessoa for pessoa in descoberta["pessoas"] if pessoa["nome"] == "Carla Dias")
    assert carla["devedores"]["devedor"] is True
    assert descoberta["kpis"]["devedores"] == 1
    alertas = [item for item in descoberta["atencao"] if item["severidade"] == "alerta"]
    assert any("listas de devedores" in item["titulo"] for item in alertas)
    fontes = {fonte["id"]: fonte for fonte in descoberta["fontes"]}
    assert fontes["devedores"]["estado"] == "ok"
    assert fontes["devedores"]["nota"]


def test_atencao_avisa_empresa_sem_cargos(descoberta):
    titulos = [item["titulo"] for item in descoberta["atencao"]]
    assert any("Sem cargos registados em Gama, Lda." in titulo for titulo in titulos)
    ordem = [dp.SEVERIDADE_ORDEM[item["severidade"]] for item in descoberta["atencao"]]
    assert ordem == sorted(ordem)


def test_grafo_liga_empresas_a_pessoas(descoberta):
    grafo = descoberta["grafo"]
    assert grafo["meta"]["dimension_a"] == "empresa"
    assert grafo["meta"]["dimension_b"] == "pessoa"
    ids = {node["id"] for node in grafo["nodes"]}
    assert "empresa:111111111" in ids
    assert "pessoa:200000001" in ids
    ana = next(node for node in grafo["nodes"] if node["id"] == "pessoa:200000001")
    assert ana["type"] == "pessoa"
    assert ana["count"] == 3
    assert ana["total_value"] == 60000.0
    # O nó da pessoa leva o título (os cargos), não o nome da publicação.
    assert ana["role"] == "Gerente · Sócia"
    arestas = [edge for edge in grafo["edges"] if edge["target"] == "pessoa:200000001"]
    assert {edge["source"] for edge in arestas} == {"empresa:111111111", "empresa:222222222"}
    # Cada ligação diz o título com que a pessoa está naquela empresa.
    assert all(edge["relation"] == "tem como Gerente" for edge in arestas)


def test_cargos_distribuicao(descoberta):
    cargos = {item["cargo"]: item for item in descoberta["cargos"]}
    assert cargos["Gerente"]["pessoas"] == 1
    assert cargos["Gerente"]["empresas"] == 2
    assert cargos["Credor"]["classe"] == "processo"


def test_leitura_resume_a_descoberta(descoberta):
    leitura = descoberta["leitura"]
    assert "3 empresa(s) analisada(s)" in leitura
    assert "4 pessoa(s) com cargos registados" in leitura
    assert "quem liga o conjunto: Ana Silva" in leitura
    assert not leitura.endswith("..")


def test_avisos_e_empresas_sem_pessoas(descoberta):
    empresas = {empresa["nif"]: empresa for empresa in descoberta["empresas"]}
    assert empresas["333333333"]["pessoas"] == 0
    assert empresas["333333333"]["estado"] == "vazio"
    assert descoberta["kpis"]["empresas_sem_pessoas"] == 1
    assert descoberta["grafo"]["meta"]["complete"] is True


def test_recolha_sobrevive_a_empresa_em_falha(monkeypatch):
    def fake_empresa(nif, *, size=0, es=None):
        if str(nif) == "222222222":
            raise RuntimeError("Elasticsearch indisponível")
        return FICHAS["111111111"]

    monkeypatch.setattr(dp.es_client, "company_people_from_index", fake_empresa)
    monkeypatch.setattr(dp.cire_service, "search", lambda **kwargs: {"total": 0, "items": []})
    monkeypatch.setattr(dp.devedores_service, "por_nif", lambda nif, es=None: {"devedor": False, "total": 0})
    resultado = dp.descobrir(nifs=["111111111", "222222222"], incluir_devedores=False)
    falhada = next(empresa for empresa in resultado["empresas"] if empresa["nif"] == "222222222")
    assert "Elasticsearch indisponível" in falhada["erro"]
    assert falhada["estado"] == "erro"
    assert any("222222222" in aviso for aviso in resultado["avisos"])
    # A empresa que respondeu continua a produzir pessoas.
    assert resultado["kpis"]["pessoas"] == 2


def test_valida_o_pedido(monkeypatch):
    with pytest.raises(ValueError, match="País não suportado"):
        dp.descobrir(nifs=["111111111"], pais="XX")
    with pytest.raises(ValueError, match="Fontes desconhecidas"):
        dp.descobrir(nifs=["111111111"], fontes=["cargos", "inventada"])
    monkeypatch.setattr(dp.service, "resolver", lambda texto, size=8: {"items": []})
    with pytest.raises(ValueError, match="nenhuma empresa"):
        dp.descobrir(nomes=["Empresa Que Não Existe"])


def test_corta_o_pedido_ao_limite(monkeypatch):
    pedidos: list[str] = []

    def fake_empresa(nif, *, size=0, es=None):
        pedidos.append(str(nif))
        return {"nif": str(nif), "name": f"Empresa {nif}", "total": 0, "people": []}

    monkeypatch.setattr(dp.es_client, "company_people_from_index", fake_empresa)
    monkeypatch.setattr(dp.cire_service, "search", lambda **kwargs: {"total": 0, "items": []})
    oito = [f"10000000{digito}" for digito in range(1, 9)]
    resultado = dp.descobrir(nifs=oito, max_empresas=99, incluir_devedores=False)
    assert resultado["pedido"]["max_empresas"] == dp.MAX_EMPRESAS
    assert resultado["pedido"]["empresas"] == dp.MAX_EMPRESAS
    assert len(resultado["empresas"]) == dp.MAX_EMPRESAS
    assert len(pedidos) == dp.MAX_EMPRESAS


def test_fontes_pedidas_ficam_de_fora_quando_nao_sao_pedidas(monkeypatch):
    monkeypatch.setattr(
        dp.es_client,
        "company_people_from_index",
        lambda nif, size=0, es=None: FICHAS["111111111"],
    )
    monkeypatch.setattr(dp.service, "resolver", lambda texto, size=8: {"items": []})
    resultado = dp.descobrir(nifs=["111111111"], fontes=["cargos"], incluir_devedores=False)
    assert [fonte["id"] for fonte in resultado["fontes"]] == ["cargos"]
    assert resultado["pedido"]["fontes"] == ["cargos"]
    assert all(pessoa["cire"] == [] for pessoa in resultado["pessoas"])


def test_meta_publica_as_fontes_e_os_limites():
    meta = dp.meta()
    assert {fonte["id"] for fonte in meta["fontes"]} == set(dp.FONTE_IDS)
    assert meta["limites"]["empresas"] == dp.MAX_EMPRESAS
    assert {classe["id"] for classe in meta["classes"]} == set(dp.CLASSES)
    assert meta["orgaos_gestao"]
    assert {item["id"] for item in meta["risco"]["componentes"]} == {spec["id"] for spec in dp.COMPONENTES_RISCO}
    assert round(sum(spec["peso"] for spec in dp.COMPONENTES_RISCO), 6) == 1.0


def _pessoa_para_risco(**extra) -> dict:
    base = {
        "nif": "200000001",
        "nome": "Ana Silva",
        "empresas_universo": 5,
        "ultimo": "2026-09-01",
        "cargos_pedido": 2,
        "empresas": [
            {
                "nif": "111111111",
                "nome": "Alfa, S.A.",
                "cargos": [
                    {"role": "Gerente", "role_org": "Gerência", "data": "2026-09-01", "causa": "", "classe": "gestao"},
                    {"role": "Vogal", "role_org": "", "data": "2024-01-01", "causa": "renúncia", "classe": "gestao"},
                ],
            }
        ],
        "cire": [],
        "devedores": {"devedor": False, "total": 0, "entidades": []},
    }
    base.update(extra)
    return base


def test_risco_da_pessoa_sobe_com_os_sinais():
    limpa = dp.risco_da_pessoa(_pessoa_para_risco())
    assert limpa["score"] is not None
    assert limpa["nivel"] in {nivel["id"] for nivel in __import__("api.risco_service", fromlist=["NIVEIS"]).NIVEIS}
    assert limpa["cobertura"] == 1.0

    suja = dp.risco_da_pessoa(
        _pessoa_para_risco(
            cire=[{"papel": "Insolvente", "processo": "1/24", "especie": "Insolvência", "data": "2024-03-01"}],
            devedores={"devedor": True, "total": 2, "entidades": ["Finanças"], "maior_valor_min": 90000.0},
        )
    )
    assert suja["score"] > limpa["score"]
    assert suja["fatores"]
    assert any("Insolvente" in linha for linha in suja["componentes"][1]["evidencia"])


def test_risco_sem_dados_nao_inventa_score():
    risco = dp.risco_da_pessoa({"nif": "1", "nome": "X", "empresas": [], "cire": [], "devedores": None})
    assert risco["score"] is None
    assert risco["nivel_label"] == "Sem dados"
    assert risco["cobertura"] == 0.0


def test_conflitos_detetam_titulares_dos_dois_lados(descoberta):
    conflitos = descoberta["conflitos"]
    nomes = {item["contraparte"]["nome"] for item in conflitos}
    assert "Delta, Lda." in nomes
    assert descoberta["kpis"]["conflitos"] >= 1
    dentro = [item for item in conflitos if item["contraparte"]["dentro_do_pedido"]]
    assert dentro, "uma empresa do pedido que contrata com a outra tem de contar"
    assert any(item["severidade"] == "alerta" for item in conflitos)
    assert any("dois lados" in item["titulo"] for item in descoberta["atencao"])


def test_grafo_pessoas_liga_quem_partilha_empresa(descoberta):
    grafo = descoberta["grafo_pessoas"]
    assert grafo["meta"]["dimension_a"] == "pessoa"
    assert grafo["meta"]["dimension_b"] == "pessoa"
    ids = {node["id"] for node in grafo["nodes"]}
    assert "pessoa:200000001" in ids
    relacoes = {edge["relation"] for edge in grafo["edges"]}
    assert "juntos em Alfa, S.A." in relacoes
    assert all(edge["source"].startswith("pessoa:") and edge["target"].startswith("pessoa:") for edge in grafo["edges"])


def test_pergunta_padrao_ancora_nos_numeros(descoberta):
    pergunta = dp.pergunta_padrao(descoberta)
    assert "quem manda" in pergunta
    assert f"pessoas com cargos: {descoberta['kpis']['pessoas']}" in pergunta
    assert "titulares: " in pergunta


def test_pergunta_padrao_nomeia_titulares_com_titulo(descoberta):
    pergunta = dp.pergunta_padrao(descoberta)
    pessoa = descoberta["pessoas"][0]
    assert f"{pessoa['nome']} — {pessoa['titulo']}" in pergunta
    assert pessoa["empresas"][0]["nome"] in pergunta
    assert pergunta.count(" | ") + 1 <= dp.MAX_TITULARES_PEDIDO


def test_analise_pede_ao_hermes(monkeypatch, descoberta):
    import asyncio

    from api import hermes_service

    pedidos: dict = {}

    async def fake_ask(pergunta, **kwargs):
        pedidos["pergunta"] = pergunta
        pedidos["kwargs"] = kwargs
        return {"text": "Resposta citada [1].", "mode": "ai", "evidence": [{"id": 1}], "metrics": [], "steps": []}

    monkeypatch.setattr(hermes_service, "ask", fake_ask)
    resultado = asyncio.run(dp.analisar(descoberta, pergunta="Quem manda nestas empresas?"))
    assert resultado["text"] == "Resposta citada [1]."
    assert resultado["pergunta"] == "Quem manda nestas empresas?"
    assert pedidos["kwargs"]["country"] == "PRT"
    assert resultado["empresas"]


def test_ficha_junta_todos_os_cargos_da_pessoa(monkeypatch):
    documento = {
        "nif": "200000001",
        "name": "Ana Silva",
        "roles_count": 3,
        "companies_count": 2,
        "first_seen": "2019-03-04",
        "last_seen": "2024-01-10",
        "sources": ["publicacoes_mj"],
        "metadata": {"party": "Independente", "office": "Deputada"},
        "roles": [
            {**_cargo("Gerente", role_org="Gerência"), "company_nif": "111111111", "company_name": "Alfa, S.A."},
            {**_cargo("Gerente", role_org="Gerência"), "company_nif": "222222222", "company_name": "Beta, Lda."},
            {
                **_cargo("Sócia", role_org="Sócios e Quotas", quota=10000.0),
                "company_nif": "111111111",
                "company_name": "Alfa, S.A.",
            },
        ],
    }
    monkeypatch.setattr(dp.es_client, "get_person_by_nif", lambda nif, es=None: documento)
    resultado = dp.ficha("200000001", empresas=["222222222"])
    assert resultado["encontrada"] is True
    assert resultado["nome"] == "Ana Silva"
    assert resultado["classe"] == "gestao"
    assert resultado["cargos_total"] == 3
    assert resultado["nas_empresas_pedido"] == ["222222222"]
    # A empresa do pedido vem primeiro (é o que se está a analisar).
    assert resultado["empresas"][0]["nif"] == "222222222"
    assert resultado["empresas"][0]["no_pedido"] is True
    assert resultado["quotas"][0]["quota"] == 10000.0
    assert resultado["perfil"]["cargo_publico"] == "Deputada"


def test_ficha_de_pessoa_desconhecida(monkeypatch):
    monkeypatch.setattr(dp.es_client, "get_person_by_nif", lambda nif, es=None: {"nif": nif, "error": "não encontrada"})
    resultado = dp.ficha("200000999")
    assert resultado["encontrada"] is False
    assert resultado["erro"] == "não encontrada"
    assert resultado["avisos"]
