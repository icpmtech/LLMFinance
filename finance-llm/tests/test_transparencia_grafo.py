"""Grafo da Transparência: construção a partir das declarações e leitura.

Os testes não dependem de rede nem de Elasticsearch: escrevem declarações
normalizadas sintéticas (a mesma forma do JSONL do módulo EPT) numa pasta
temporária, constroem o grafo e verificam os nós, as relações, a geocodificação
da sede e as vistas (grafo, ficha do nó, empresas e mapa).
"""
from __future__ import annotations

import json

import pytest

from api import transparencia_geo as geo
from api import transparencia_grafo_service as svc


def _declaracao(
    *,
    declaracao_id: str,
    titular_id: str,
    titular: str,
    ano: int,
    cargo_id: str = "3",
    cargo: str = "Primeiro-Ministro",
    entidade_id: str = "4216",
    entidade: str = "Governo",
    nif_entidade: str = "176738371",
    interesses: list[dict] | None = None,
) -> dict:
    return {
        "declaracao_id": declaracao_id,
        "titular_id": titular_id,
        "titular": titular,
        "ano": ano,
        "natureza_codigo": 4,
        "natureza": "Inicial",
        "estado": "Publicada",
        "entidade": entidade,
        "orgao": "Governo da República",
        "cargo": cargo,
        "inicio": "2024-01-01T00:00:00",
        "fim": None,
        "entrega": "2024-06-03T16:28:58",
        "entidade_id": entidade_id,
        "orgao_id": "3",
        "cargo_id": cargo_id,
        "nif_entidade": nif_entidade,
        "interesses": interesses or [],
        "tem_registo_interesses": bool(interesses),
        "fonte": "entidade-transparencia",
        "url_publica": "https://entidadetransparencia.pt/#/consultardeclaracaopublica",
    }


def _atividade(nome: str, nif: str, local: str, natureza: str = "Setor privado", funcao: str = "Gerente") -> dict:
    return {
        "tipo": "Atividades profissionais, cargos e funções",
        "valores": {
            "Cargo/Função/Atividade": funcao,
            "Entidade": nome,
            "Natureza e área de atuação da entidade": natureza,
            "Local da sede": local,
            "Remuneração (se aplicável)": "Sim",
            "Data de início": "2020-01-01T00:00:00Z",
            "Data de termo": None,
            "NIF/NIPC": nif,
        },
    }


@pytest.fixture()
def grafo(tmp_path, monkeypatch):
    ept_dir = tmp_path / "entidade-transparencia"
    (ept_dir / "_normalized").mkdir(parents=True)
    (ept_dir / "catalogo").mkdir(parents=True)
    grafo_dir = tmp_path / "transparencia-grafo"

    declaracoes = [
        _declaracao(
            declaracao_id="1",
            titular_id="10",
            titular="Maria de Sousa Exemplo",
            ano=2024,
            interesses=[
                _atividade("Vanguard Asset Management", "514114215", "Lisboa"),
                _atividade("Estrutura de Gestão do IFRRU", "600086739", "Avenida da Liberdade, 180A", "Setor público"),
                {
                    "tipo": "Sociedades",
                    "valores": {
                        "Coluna col1": "Frucar Comércio de Fruta, Lda.",
                        "Coluna col2": "Comércio de fruta",
                        "Coluna col3": "Porto",
                        "Coluna col4": "6259901",
                        "Coluna col5": "0.5",
                        "Coluna col6": "2",
                        "Coluna col7": "502839619",
                        "Coluna col8": "3",
                    },
                },
                {
                    "tipo": "Apoios ou benefícios",
                    "valores": {
                        "Coluna col1": "Bolsa",
                        "Coluna col2": "Fundação para a Ciência e a Tecnologia",
                        "Coluna col3": "Setor público",
                        "Coluna col4": "Bolsa de doutoramento",
                        "Coluna col5": "2023-01-01T00:00:00Z",
                        "Coluna col6": "503904040",
                    },
                },
                {
                    "tipo": "Serviços prestados",
                    "valores": {
                        "Coluna col1": "Júri de bolsas",
                        "Coluna col2": "Universidade de Coimbra",
                        "Coluna col3": "Membro do júri",
                        "Coluna col4": "Coimbra",
                        "Coluna col6": "501617960",
                    },
                },
            ],
        ),
        _declaracao(
            declaracao_id="2",
            titular_id="11",
            titular="João Pereira Exemplo",
            ano=2025,
            cargo_id="12",
            cargo="Presidente",
            entidade_id="908",
            entidade="Águas do Baixo Mondego, S.A.",
            nif_entidade="502000000",
            interesses=[_atividade("Estrutura de Gestão do IFRRU", "600086739", "Bruxelas", "Setor público")],
        ),
    ]
    with (ept_dir / "_normalized" / "declaracoes.jsonl").open("w", encoding="utf-8") as ficheiro:
        for declaracao in declaracoes:
            ficheiro.write(json.dumps(declaracao, ensure_ascii=False) + "\n")

    titularidades = [
        {
            "titularidade_id": "1",
            "titular_id": "10",
            "titular": "Maria de Sousa Exemplo",
            "entidade_id": "4216",
            "entidade": "Governo",
            "cargo_id": "3",
            "cargo": "Primeiro-Ministro",
            "inicio": "2024-01-01T00:00:00",
            "fim": "2024-12-31T00:00:00",
        },
        {
            "titularidade_id": "2",
            "titular_id": "11",
            "titular": "João Pereira Exemplo",
            "entidade_id": "908",
            "entidade": "Águas do Baixo Mondego, S.A.",
            "cargo_id": "12",
            "cargo": "Presidente",
            "inicio": "2025-01-01T00:00:00",
            "fim": None,
        },
    ]
    with (ept_dir / "catalogo" / "titularidades.jsonl").open("w", encoding="utf-8") as ficheiro:
        for linha in titularidades:
            ficheiro.write(json.dumps(linha, ensure_ascii=False) + "\n")

    monkeypatch.setenv("ENTIDADE_TRANSPARENCIA_DATA_DIR", str(ept_dir))
    monkeypatch.setenv("TRANSPARENCIA_GRAFO_DATA_DIR", str(grafo_dir))
    svc._invalidar_cache()
    resultado = svc.construir(indexar_es=False, forcar=True)
    assert resultado.get("error") is None
    return resultado


def test_construir_cria_os_quatro_tipos_de_no(grafo):
    totais = grafo["manifesto"]["totais"]
    assert totais["pessoas"] == 2
    assert totais["cargos"] == 2
    assert totais["entidades"] >= 2
    assert totais["empresas"] >= 2
    assert totais["nos"] == totais["pessoas"] + totais["cargos"] + totais["entidades"] + totais["empresas"]
    relacoes = grafo["manifesto"]["relacoes"]
    assert {"EXERCE", "CARGO_EM", "ATIVIDADE", "PARTICIPACAO", "BENEFICIO", "SERVICO"} <= set(relacoes)


def test_geocodifica_a_sede_e_exclui_o_que_nao_e_lugar(grafo):
    lista = svc.empresas(tipo="empresa,entidade", limit=0)
    por_nome = {item["nome"]: item for item in lista["items"]}
    vanguard = por_nome["Vanguard Asset Management"]
    assert vanguard["concelho"] == "Lisboa"
    assert vanguard["lat"] == pytest.approx(38.72509, abs=0.01)
    assert vanguard["precisao_geo"] in {"cidade", "alias"}

    # O mesmo NIF tem de ser o mesmo nó, mesmo que a natureza mude entre linhas.
    ifruu = por_nome["Estrutura de Gestão do IFRRU"]
    assert ifruu["tipo"] == "empresa"
    assert ifruu["lat"] is None or ifruu["concelho"] != "Avenida"

    # Sede estrangeira continua a entrar no mapa.
    assert svc.mapa(limite_pontos=10)["total"] >= 1


def test_filtra_o_grafo_por_tipo_relacao_e_foco(grafo):
    pessoas = svc.grafo(tipo="pessoa", limit=10)
    assert pessoas["nodes"]
    assert {no["type"] for no in pessoas["nodes"]} == {"pessoa"}
    assert all(edge["relacao"] in {"EXERCE", "ATIVIDADE", "PARTICIPACAO", "BENEFICIO", "SERVICO"} for edge in pessoas["edges"])

    so_cargos = svc.grafo(relacao="EXERCE", limit=10)
    assert so_cargos["nodes"]
    assert {edge["relacao"] for edge in so_cargos["edges"]} == {"EXERCE"}

    empresa = next(no for no in svc.empresas(limit=0)["items"] if no["nome"] == "Vanguard Asset Management")
    foco = svc.grafo(foco=empresa["no_id"], limit=20)
    assert foco["nodes"]
    assert empresa["no_id"] in {no["id"] for no in foco["nodes"]}


def test_ficha_do_no_traz_vizinhos(grafo):
    empresa = next(no for no in svc.empresas(limit=0)["items"] if no["nome"] == "Frucar Comércio de Fruta, Lda.")
    detalhe = svc.no_detail(empresa["no_id"])
    assert detalhe["no"]["tipo"] == "empresa"
    assert detalhe["total_vizinhos"] == 1
    vizinho = detalhe["vizinhos"][0]
    assert vizinho["relacao"] == "PARTICIPACAO"
    assert vizinho["no"]["type"] == "pessoa"
    assert svc.no_detail("empresa:inexistente").get("error")


def test_mapa_agrega_por_concelho(grafo):
    mapa = svc.mapa(limite_pontos=50)
    assert mapa["total"] >= 2
    assert mapa["com_geo"] == mapa["total"]
    assert mapa["concelhos"]
    assert mapa["concelhos"][0]["empresas"] >= 1
    assert all(ponto["lat"] is not None for ponto in mapa["pontos"])


def test_concelho_lista_empresas_com_relacoes_e_contratacao(grafo):
    dados = svc.concelho_detalhe("Lisboa", limite=10, incluir_contratacao=False)
    assert dados["concelho"] == "Lisboa"
    assert dados["total"] >= 1
    empresa = next(item for item in dados["empresas"] if item["nome"] == "Vanguard Asset Management")
    assert empresa["relacoes"].get("ATIVIDADE") == 1
    assert empresa["ligados"][0]["nome"] == "Maria de Sousa Exemplo"
    assert "contratacao" in empresa
    assert svc.concelho_detalhe("Concelho Inexistente").get("error")


def test_adjudicantes_da_amostra_aceita_raw_e_parsed():
    amostra = {
        "hits": {
            "hits": [
                {"_source": {"adjudicantes": {"raw": ["500000000 - Município A"], "parsed": [{"nome": "Município A"}]}}},
                {"_source": {"adjudicantes": ["500000001 - Município B"]}},
            ]
        }
    }
    assert svc._adjudicantes_da_amostra(amostra) == ["Município A", "Município B"]


def test_mapa_lista_entidades_sem_coordenadas(monkeypatch):
    com_geo = {
        "total": 1,
        "items": [
            {
                "no_id": "empresa:com-geo",
                "nome": "Com Geo",
                "concelho": "Lisboa",
                "lat": 38.7,
                "lon": -9.1,
                "ligacoes": 1,
            }
        ],
    }
    sem_geo = {
        "total": 1,
        "items": [{"no_id": "empresa:sem-geo", "nome": "Sem Geo", "lat": None, "lon": None}],
    }

    def fake_empresas(**kwargs):
        return com_geo if kwargs.get("com_geo") else sem_geo

    monkeypatch.setattr(svc, "empresas", fake_empresas)
    mapa = svc.mapa(limite_sem_geo=5)
    # As entidades sem coordenadas não vão ao mapa, mas são listadas para se
    # poderem abrir na ficha (não ficam escondidas atrás de um contador).
    assert mapa["sem_geo"] == len(mapa["sem_geo_itens"]) == 1
    assert mapa["sem_geo_itens"] == sem_geo["items"]
    assert all(item["lat"] is None for item in mapa["sem_geo_itens"])


def test_export_csv_inclui_as_empresas(grafo):
    conteudo = svc.csv_bytes(limit=100)
    texto = conteudo.decode("utf-8-sig")
    assert "nome;tipo;nif" in texto.replace("id;", "")
    assert "Vanguard Asset Management" in texto


def test_resolver_local_conhece_variantes():
    assert geo.resolver_local("Lisboa")["concelho"] == "Lisboa"
    assert geo.resolver_local("LISBOA")["concelho"] == "Lisboa"
    assert geo.resolver_local("1100-394 Lisboa")["precisao"] == "postal"
    assert geo.resolver_local("Palácio de S. Bento")["concelho"] == "Lisboa"
    assert geo.resolver_local("Bruxelas")["precisao"] == "estrangeiro"
    assert geo.resolver_local("sem local físico") is None
    assert geo.resolver_local("") is None
