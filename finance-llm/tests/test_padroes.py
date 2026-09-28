"""Testes do módulo de **deteção de padrões** — puros, sem Elasticsearch.

Cobrem as peças que decidem o resultado e onde é fácil errar:

- leitura das partes (o Portal BASE guarda `adjudicatarios` como **objeto**
  `{"raw": [...], "parsed": [...]}` e não como lista — foi o primeiro bug);
- semântica real das datas (a publicação acontece **depois** da decisão);
- contagem de concorrentes a partir da lista de NIFs em texto;
- matriz de features (NaN onde não há dado) e imputação;
- ranks robustos (um valor em falta nunca pode virar «o mais anómalo»);
- regras interpretáveis, tabela por CPV e tabela por entidade;
- deteção não supervisionada (se o scikit-learn estiver instalado);
- modelo supervisionado **sem fuga de informação** (o rótulo não pode ser feature);
- degradação elegante sem Elasticsearch.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api import padroes_service as padroes  # noqa: E402

SKLEARN = padroes._sklearn() is not None


# ---------------------------------------------------------------------------
# Utilitários de leitura
# ---------------------------------------------------------------------------
def test_as_int_so_aceita_contagens_pequenas() -> None:
    assert padroes.as_int("3") == 3
    assert padroes.as_int("12 concorrentes") == 12
    assert padroes.as_int(7) == 7
    assert padroes.as_int("") is None
    assert padroes.as_int(None) is None
    # O campo `concorrentes` do BASE é texto com NIFs colados: 9 dígitos não são
    # uma contagem e seriam um valor absurdo na matriz de features.
    assert padroes.as_int("504663909-Real Milenium") is None
    assert padroes.as_int("12345678901234567890") is None


def test_as_date_aceita_iso_e_rejeita_lixo() -> None:
    assert padroes.as_date("2023-07-12").year == 2023
    assert padroes.as_date("2023-07-12T00:00:00.000Z").month == 7
    assert padroes.as_date("") is None
    assert padroes.as_date("não é data") is None


def test_fold_remove_acentos() -> None:
    assert padroes.fold("Ajuste Direto Regime Geral") == "ajuste direto regime geral"
    assert padroes.fold("Contratação Excluída") == "contratacao excluida"


def test_parties_le_a_estrutura_em_objeto_do_portal_base() -> None:
    source = {
        "adjudicatarios": {
            "raw": ["504663909 - Real Milenium Carmage - Construções S.A."],
            "parsed": [{"nif": "504663909", "nome": "Real Milenium Carmage - Construções S.A."}],
        },
        "adjudicantes": {
            "raw": ["505037700 - CMPH"],
            "parsed": [{"nif": "505037700", "nome": "CMPH - DomusSocial"}],
        },
    }
    parties = padroes._parties(source, "adjudicatarios.parsed", "adjudicatarios.parsed.nif", "adjudicatarios.parsed.nome")
    assert parties == [{"nif": "504663909", "nome": "Real Milenium Carmage - Construções S.A."}]
    assert len(padroes._parties(source, "adjudicantes.parsed", "", "")) == 1
    # Sem partes não pode rebentar.
    assert padroes._parties({}, "adjudicatarios.parsed", "", "") == []


def test_parties_le_a_estrutura_plana_de_espanha() -> None:
    source = {"adjudicatario_nif": "B56807126", "adjudicatario_nombre": "ML Informática"}
    parties = padroes._parties(source, "__flat__", "adjudicatario_nif", "adjudicatario_nombre")
    assert parties == [{"nif": "B56807126", "nome": "ML Informática"}]
    assert padroes._parties({}, "__flat__", "adjudicatario_nif", "adjudicatario_nombre") == []


def test_bidders_conta_nifs_distintos_em_portugal() -> None:
    source = {
        "concorrentes": (
            "504663909-Real Milenium, 513503773-PEMI Engenharia, 513204571-Cálculos e Títulos, "
            "504663909-Real Milenium"
        )
    }
    assert padroes._bidders(source, padroes.PT) == 3
    assert padroes._bidders({"concorrentes": ""}, padroes.PT) is None
    assert padroes._bidders({"num_ofertas": 5}, padroes.ES) == 5


# ---------------------------------------------------------------------------
# Normalização de um contrato
# ---------------------------------------------------------------------------
def _pt_hit() -> dict:
    return {
        "_id": "2022:9496917",
        "_source": {
            "idcontrato": "9496917",
            "Ano": 2022,
            "objectoContrato": "Aquisição de produtos de limpeza",
            "precoContratual": 15023.33,
            "precoBaseProcedimento": 17250.0,
            "PrecoTotalEfetivo": 34782.70,
            "prazoExecucao": 30,
            "dataPublicacao": "2022-06-01",
            "dataDecisaoAdjudicacao": "2022-08-01",
            "dataCelebracaoContrato": "2022-08-01",
            "tipoprocedimento": "Consulta Prévia",
            "concorrentes": "508808766-Falquimica, 501234567-Outra",
            "cpv": [{"code": "39800000-0", "description": "Produtos de limpeza"}],
            "adjudicantes": {"raw": [], "parsed": [{"nif": "600083292", "nome": "Agrupamento de Escolas"}]},
            "adjudicatarios": {"raw": [], "parsed": [{"nif": "508808766", "nome": "Falquimica Unipessoal"}]},
        },
    }


def test_row_from_hit_pt_normaliza_features() -> None:
    row = padroes._row_from_hit(padroes.PT, _pt_hit())
    assert row["pais"] == "PT"
    assert row["valor"] == pytest.approx(15023.33)
    assert row["ratio_base"] == pytest.approx(15023.33 / 17250.0, rel=1e-6)
    assert row["ratio_efetivo"] == pytest.approx(34782.70 / 15023.33, rel=1e-6)
    assert row["ajuste_direto"] == 1
    assert row["n_concorrentes"] == 2
    assert row["cpv_grupo"] == "39"
    assert row["adjudicatario_nif"] if "adjudicatario_nif" in row else row["adjudicatarios"][0]["nif"] == "508808766"
    # Semântica real: a decisão é **antes** da publicação (o portal publica
    # depois de adjudicar), pelo que `dias_decisao` é negativo.
    assert row["dias_decisao"] == 61
    assert row["dias_assinatura"] == 0
    assert row["dias_publicacao"] == -61


def test_row_from_hit_trata_valor_efetivo_zero_como_ausente() -> None:
    hit = _pt_hit()
    hit["_source"]["PrecoTotalEfetivo"] = 0.0
    row = padroes._row_from_hit(padroes.PT, hit)
    assert row["efetivo"] is None
    assert row["ratio_efetivo"] is None


def test_row_from_hit_ignora_datas_corrompidas() -> None:
    hit = _pt_hit()
    # Gralha real do PLACSP: um ano 0018 num documento em 4 milhões.
    hit["_source"]["dataCelebracaoContrato"] = "0018-03-02"
    row = padroes._row_from_hit(padroes.PT, hit)
    assert row["dias_assinatura"] is None
    assert row["dias_publicacao"] is None


def test_row_from_hit_es_usa_campos_planos() -> None:
    hit = {
        "_id": "abc",
        "_source": {
            "id_expediente": "2024/1",
            "ano": 2024,
            "objeto": "Suministro informático",
            "valor_adjudicado": 1000.0,
            "valor_base": 2000.0,
            "num_ofertas": 1,
            "fecha_publicacion": "2024-03-01",
            "fecha_adjudicacion": "2024-03-20",
            "procedimiento_label": "Contrato menor",
            "cpv": [{"code": "30200000", "nombre": "Equipo informático"}],
            "organo_id": "U01700001",
            "organo_nombre": "Rectorado",
            "adjudicatario_nif": "B56807126",
            "adjudicatario_nombre": "ML Informática",
        },
    }
    row = padroes._row_from_hit(padroes.ES, hit)
    assert row["ratio_base"] == pytest.approx(0.5)
    assert row["ratio_efetivo"] is None
    assert row["ajuste_direto"] == 1
    assert row["dias_decisao"] == 19
    assert row["dias_assinatura"] is None
    assert row["adjudicatarios"] == [{"nif": "B56807126", "nome": "ML Informática"}]
    assert row["cpv_grupo"] == "30"


# ---------------------------------------------------------------------------
# Features e deteção
# ---------------------------------------------------------------------------
def _rows(count: int = 200) -> list:
    rows = []
    for index in range(count):
        # 5 % de contratos «estranhos», o resto normal.
        outlier = index % 20 == 0
        rows.append(
            {
                "id": f"c{index}",
                "pais": "PT",
                "ano": 2022,
                "objeto": "objeto",
                "valor": 1_000_000.0 if outlier else 1000.0 + index,
                "base": 1000.0,
                "efetivo": 3000.0 if outlier else 1000.0,
                "ratio_base": 1000.0 if outlier else 1.0,
                "ratio_efetivo": 3.0 if outlier else 1.0,
                "prazo_execucao": 30,
                "dias_decisao": -20,
                "dias_assinatura": 400 if outlier else 5,
                "dias_publicacao": 200 if outlier else 10,
                "procedimento": "Consulta Prévia",
                "ajuste_direto": 1,
                "n_concorrentes": 1 if outlier else 4,
                "cpv": "45000000-7",
                "cpv_grupo": "45",
                "cpv_desc": "Construção",
                "adjudicante_nif": "600000001",
                "adjudicante_nome": "Município X",
                "adjudicatarios": [{"nif": "500000001", "nome": "Empresa A"}],
                "n_adjudicantes": 1,
            }
        )
    return rows


def test_feature_matrix_tem_uma_coluna_por_feature() -> None:
    matrix, names, cpvs = padroes._feature_matrix(_rows(10))
    assert matrix.shape == (10, len(padroes.FEATURE_NAMES))
    assert names == padroes.FEATURE_NAMES
    assert cpvs == ["45"] * 10


def test_feature_matrix_marca_ausencia_com_nan() -> None:
    row = _rows(1)[0]
    row["ratio_efetivo"] = None
    row["dias_assinatura"] = None
    matrix, names, _ = padroes._feature_matrix([row])
    indice = names.index("ratio_efetivo")
    assert np.isnan(matrix[0][indice])


def test_impute_preenche_com_a_mediana() -> None:
    matrix = np.array([[1.0, np.nan], [3.0, 2.0], [5.0, 4.0]])
    filled = padroes._impute(matrix)
    assert filled[0][1] == 3.0
    assert np.isfinite(filled).all()


def test_ranks_nao_premeia_valores_em_falta() -> None:
    ranks = padroes._ranks(np.array([1.0, 2.0, np.nan, 4.0]))
    assert ranks[2] == 0.0
    assert ranks[3] == 1.0
    assert ranks[0] == 0.0


def test_robust_z_identifica_o_desvio() -> None:
    values = np.array([10.0, 10.1, 9.9, 10.2, 10.05, 500.0])
    z = padroes._robust_z(values)
    assert z[-1] > 100
    assert abs(z[0]) < 1


def test_per_cpv_z_exige_grupo_minimo() -> None:
    matrix = np.zeros((30, 2))
    matrix[0, 0] = 1000.0
    z = padroes._per_cpv_z(matrix, ["45"] * 30, min_group=40)
    assert z.max() == 0.0  # grupo pequeno: não se conclui nada
    z = padroes._per_cpv_z(matrix, ["45"] * 30, min_group=20)
    assert z[0] > 0


@pytest.mark.skipif(not SKLEARN, reason="scikit-learn indisponível")
def test_detect_devolve_scores_normalizados() -> None:
    rows = _rows(200)
    matrix, _, cpvs = padroes._feature_matrix(rows)
    detection = padroes._detect(padroes._impute(matrix), cpvs, seed=1, contamination=0.05)
    assert detection["error"] is None
    assert detection["consensus"].shape[0] == 200
    assert detection["consensus"].min() >= 0.0
    assert detection["consensus"].max() <= 1.0
    assert detection["votes"].max() >= 1
    assert "isolation_forest" in detection["detectors"]


# ---------------------------------------------------------------------------
# Regras interpretáveis
# ---------------------------------------------------------------------------
def test_reasons_explicam_aditivo_e_tranparencia_tardia() -> None:
    row = _rows(1)[0]
    row["ratio_base"] = 1.5
    row["ratio_efetivo"] = 1.4
    row["dias_publicacao"] = 300
    row["dias_assinatura"] = 250
    row["n_concorrentes"] = 1
    reasons = {item["padrao"] for item in padroes._reasons(row, z=5.0, cpv_rate_ad=0.1, global_rate_ad=0.6)}
    assert {"desvio_preco_alto", "aditivo_valor", "publicacao_tardia", "assinatura_tardia", "baixa_concorrencia", "valor_atipico"} <= reasons
    detalhe = next(
        item["detalhe"]
        for item in padroes._reasons(row, z=0.0, cpv_rate_ad=None, global_rate_ad=None)
        if item["padrao"] == "aditivo_valor"
    )
    # O detalhe passa a ser gerado a partir da condição (campo, operador e valor).
    assert "Valor efetivo" in detalhe and ">" in detalhe and "1.4" in detalhe


def test_reasons_nao_sinaliza_preco_no_intervalo_normal() -> None:
    row = _rows(1)[0]
    row["ratio_base"] = 0.99
    row["ratio_efetivo"] = 1.0
    row["dias_publicacao"] = 15
    row["dias_assinatura"] = 5
    row["n_concorrentes"] = 5
    assert padroes._reasons(row, z=0.5, cpv_rate_ad=0.6, global_rate_ad=0.6) == []


def test_reasons_ajuste_direto_atipico_so_quando_o_cpv_e_de_concurso() -> None:
    row = _rows(1)[0]
    row["n_concorrentes"] = 5
    row["dias_publicacao"] = 10
    row["dias_assinatura"] = 5
    com_regra = padroes._reasons(row, z=0.0, cpv_rate_ad=0.1, global_rate_ad=0.6)
    sem_regra = padroes._reasons(row, z=0.0, cpv_rate_ad=0.6, global_rate_ad=0.6)
    assert any(item["padrao"] == "ajuste_direto_atipico" for item in com_regra)
    assert not any(item["padrao"] == "ajuste_direto_atipico" for item in sem_regra)


# ---------------------------------------------------------------------------
# Tabelas agregadas
# ---------------------------------------------------------------------------
def test_cpv_table_ordena_pela_relevancia() -> None:
    rows = _rows(60)
    for row in rows[33:]:
        row["cpv_grupo"] = "80"
        row["ajuste_direto"] = 0
        row["ratio_efetivo"] = 0.9
        row["ratio_base"] = 1.0
    table = padroes._cpv_table(rows, global_rate_ad=0.5)
    assert {item["cpv"] for item in table} == {"45", "80"}
    assert table[0]["relevancia"] >= table[1]["relevancia"]
    assert all(item["relevancia"] is not None for item in table)


def test_entity_table_agrega_por_adjudicatario() -> None:
    rows = _rows(10)
    anomalies = {0: {"score": 0.9}, 1: {"score": 0.95}}
    table = padroes._entity_table(rows, anomalies)
    assert len(table) == 1
    entity = table[0]
    assert entity["nif"] == "500000001"
    assert entity["nome"] == "Empresa A"
    assert entity["contratos"] == 10
    assert entity["contratos_sinalizados"] == 2
    assert entity["taxa_sinalizacao"] == pytest.approx(0.2)
    assert entity["adjudicantes_distintos"] == 1
    assert entity["parte_do_maior_adjudicante"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Modelo supervisionado
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not SKLEARN, reason="scikit-learn indisponível")
def test_risk_model_nao_usa_o_rotulo_como_feature() -> None:
    rows = []
    rng = np.random.default_rng(7)
    for index in range(1200):
        aditivo = index % 12 == 0
        valor = float(1000 + (50000 if aditivo else rng.integers(0, 5000)))
        row = {
            "id": f"r{index}",
            "objeto": "objeto",
            "ano": 2022,
            "valor": valor,
            "base": 1000.0,
            "efetivo": valor * 1.3 if aditivo else valor,
            "ratio_base": round(float(rng.uniform(0.8, 1.2)), 4),
            "ratio_efetivo": 1.3 if aditivo else 1.0,
            "prazo_execucao": 30,
            "dias_decisao": -20,
            "dias_assinatura": 5,
            "dias_publicacao": 10,
            "ajuste_direto": 1 if aditivo else 0,
            "n_concorrentes": 4,
            "cpv_grupo": "45" if aditivo else "30",
            "adjudicatarios": [{"nif": "500000001", "nome": "Empresa A"}],
        }
        rows.append(row)
    rows.append(rows[0])
    matrix, names, _ = padroes._feature_matrix(rows)
    imputed = padroes._impute(matrix)
    result = padroes._risk_model(rows, imputed, seed=3, feature_names=names)
    assert result["disponivel"] is True
    usadas = [item["feature"] for item in result["importancias"]]
    assert "ratio_efetivo" not in usadas
    assert 0.5 <= float(result["auc"]) <= 1.0


def test_risk_model_recusa_amostra_sem_aditivos() -> None:
    rows = _rows(500)
    for row in rows:
        row["ratio_efetivo"] = 1.0
    matrix, names, _ = padroes._feature_matrix(rows)
    result = padroes._risk_model(rows, padroes._impute(matrix), seed=1, feature_names=names)
    assert result["disponivel"] is False
    assert "desequilibrado" in result["motivo"] or "insuficiente" in result["motivo"]


# ---------------------------------------------------------------------------
# Sem Elasticsearch
# ---------------------------------------------------------------------------
def test_analyze_sem_es_devolve_erro(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(padroes, "get_es_client", lambda *args, **kwargs: None)
    result = padroes.analyze(pais="PT", use_cache=False)
    assert result["error"] == "Elasticsearch indisponível"


def test_analyze_com_pais_desconhecido(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(padroes, "get_es_client", lambda *args, **kwargs: None)
    result = padroes.analyze(pais="XX", use_cache=False)
    assert "país desconhecido" in result["error"]
    assert set(result["paises"]) == {"PT", "ES"}


def test_analyze_reutiliza_a_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    padroes.clear_cache()
    calls = {"n": 0}

    class _FakeClient:
        def count(self, **kwargs):  # noqa: ANN003
            return {"count": 0}

        def search(self, **kwargs):  # noqa: ANN003
            calls["n"] += 1
            return {"hits": {"hits": []}, "aggregations": {}}

    monkeypatch.setattr(padroes, "get_es_client", lambda *args, **kwargs: _FakeClient())
    first = padroes.analyze(pais="PT", ano_from=2022, ano_to=2022, use_cache=True)
    # Sem contratos o motor devolve um erro explícito (não rebenta).
    assert "sem contratos" in first["error"]
    assert padroes.clear_cache() >= 0


def test_meta_sem_es_nao_rebenta(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(padroes, "get_es_client", lambda *args, **kwargs: None)
    data = padroes.meta()
    assert len(data["padroes"]) >= 10
    assert {fonte["pais"] for fonte in data["fontes"]} == {"PT", "ES"}
    assert "sinais estatísticos" in data["aviso"]
    assert "prova" in data["aviso"]


def test_news_mentions_sem_es_le_rss(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(padroes, "get_es_client", lambda *args, **kwargs: None)
    monkeypatch.setattr(padroes, "_news_for", lambda client, names, per_name=5: [{"titulo": "x", "canal": "rss"}])
    items = padroes.news_mentions([("Empresa A", "Empresa A")])
    assert items == [{"titulo": "x", "canal": "rss"}]


def test_entity_dossier_sem_es_devolve_erro(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(padroes, "get_es_client", lambda *args, **kwargs: None)
    assert padroes.entity_dossier("500000001")["error"] == "Elasticsearch indisponível"


def test_entity_dossier_sem_nif(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeClient:
        pass

    monkeypatch.setattr(padroes, "get_es_client", lambda *args, **kwargs: _FakeClient())
    assert padroes.entity_dossier("")["error"] == "NIF em falta"


# ---------------------------------------------------------------------------
# Grafo do dossiê (empresa ↔ adjudicantes, pessoas e processos)
# ---------------------------------------------------------------------------
def test_parece_pessoa_pelo_prefixo_do_nif() -> None:
    assert padroes._parece_pessoa("123456789") is True  # pessoa singular
    assert padroes._parece_pessoa("250000000") is True
    assert padroes._parece_pessoa("503439800") is False  # pessoa coletiva
    assert padroes._parece_pessoa("A28791069") is False  # CIF espanhol
    assert padroes._parece_pessoa("") is False


def _grafo_fixture(**extra):
    contratos = [
        {"valor": 10_000.0, "adjudicante_nif": "500000001", "adjudicante": "Município A"},
        {"valor": 5_000.0, "adjudicante_nif": "500000001", "adjudicante": "Município A"},
        {"valor": 1_000.0, "adjudicante_nif": "500000002", "adjudicante": "Município B"},
    ]
    argumentos = {
        "nif": "503439800",
        "label": "ACME, Lda",
        "contracts": contratos,
        "adjudicantes": {"500000001": 15_000.0, "500000002": 1_000.0},
        "nomes_adjudicantes": {"500000001": "Município A", "500000002": "Município B"},
        "cargos_sociais": [
            {"nif": "123456789", "nome": "Ana Silva", "cargos": [{"role_org": "Gerência"}, {"role_org": "Gerência"}]}
        ],
        "intervenientes_cire": [{"nif": "234567890", "nome": "Credor X", "cargos": [{"role": "Credor"}]}],
        "cire": [{"especie": "Insolvência", "processo": "123/20.1T8MRA", "tribunal": "T. Moura", "data": "2021-02-03"}],
        "co_intervenientes": [
            {"processo": "123/20.1T8MRA", "nif": "509999999", "nome": "Outra, Lda", "papel": "Credor"}
        ],
    }
    argumentos.update(extra)
    return padroes._dossie_grafo(**argumentos)


def test_dossie_grafo_liga_empresa_adjudicantes_pessoas_e_processos() -> None:
    grafo = _grafo_fixture()
    ids = {no["id"] for no in grafo["nodes"]}
    assert {"empresa:503439800", "adjudicante:500000001", "adjudicante:500000002"} <= ids
    assert "pessoa:123456789" in ids
    assert "cire:123/20.1T8MRA" in ids
    assert "interveniente:509999999" in ids

    centro = next(no for no in grafo["nodes"] if no["id"] == "empresa:503439800")
    assert centro["count"] == 3
    assert centro["total_value"] == pytest.approx(16_000.0)

    ligacoes = {(aresta["source"], aresta["target"]) for aresta in grafo["edges"]}
    assert ("empresa:503439800", "adjudicante:500000001") in ligacoes
    # A direção pessoa→empresa é a que se lê como «quem gere esta empresa».
    assert ("pessoa:123456789", "empresa:503439800") in ligacoes
    assert ("empresa:503439800", "cire:123/20.1T8MRA") in ligacoes
    # Quem se cruza num processo fica ligado ao processo, não à empresa.
    assert ("cire:123/20.1T8MRA", "interveniente:509999999") in ligacoes

    valores = {aresta["target"]: aresta["value"] for aresta in grafo["edges"] if aresta["source"] == "empresa:503439800"}
    assert valores["adjudicante:500000001"] == pytest.approx(15_000.0)


def test_dossie_grafo_tipos_por_papel() -> None:
    grafo = _grafo_fixture()
    tipos = {no["id"]: no["type"] for no in grafo["nodes"]}
    assert tipos["empresa:503439800"] == "entidade"
    assert tipos["adjudicante:500000001"] == "entidade"
    assert tipos["pessoa:123456789"] == "pessoa"
    assert tipos["cire:123/20.1T8MRA"] == "processo"
    # A empresa credora no processo é uma entidade; uma pessoa singular seria "pessoa".
    assert tipos["interveniente:509999999"] == "entidade"


def test_dossie_grafo_meta_e_lacos() -> None:
    grafo = _grafo_fixture()
    meta = grafo["meta"]
    assert meta["dimension_a"] == "empresa"
    assert meta["dimension_b"] is None  # sem duas dimensões: a cor vem do tipo
    assert meta["nodes_total"] == len(grafo["nodes"]) == meta["kept_nodes"]
    assert meta["edges_total"] == len(grafo["edges"])
    assert meta["directed"] is True
    assert meta["limits"]["adjudicantes"] == 10

    laco = grafo["lacos"][0]
    assert laco["tipo"] == "processo_partilhado"
    assert laco["processo"] == "123/20.1T8MRA"
    assert "Outra, Lda" in laco["detalhe"]


def test_dossie_grafo_respeita_os_limites() -> None:
    contratos = [
        {"valor": 100.0, "adjudicante_nif": f"5000000{i:02d}", "adjudicante": f"Comprador {i}"} for i in range(40)
    ]
    grafo = padroes._dossie_grafo(
        nif="503439800",
        label="ACME",
        contracts=contratos,
        adjudicantes={f"5000000{i:02d}": float(100 - i) for i in range(40)},
        nomes_adjudicantes={f"5000000{i:02d}": f"Comprador {i}" for i in range(40)},
        cargos_sociais=[{"nif": f"12345678{i}", "nome": f"Pessoa {i}", "cargos": [{"role_org": "Gerência"}]} for i in range(30)],
        intervenientes_cire=[],
        cire=[{"especie": "Insolvência", "processo": f"{i}/20", "tribunal": "T", "data": "2020-01-01"} for i in range(30)],
        co_intervenientes=[],
    )
    # 1 (empresa) + 10 adjudicantes + 12 pessoas + 8 processos
    assert len(grafo["nodes"]) == 31
    assert len(grafo["edges"]) == 30
    assert grafo["meta"]["nodes_total"] == 31


def test_dossie_grafo_sem_relacoes_devolve_so_a_empresa() -> None:
    grafo = padroes._dossie_grafo(
        nif="503439800",
        label="ACME",
        contracts=[],
        adjudicantes={},
        nomes_adjudicantes={},
        cargos_sociais=[],
        intervenientes_cire=[],
        cire=[],
        co_intervenientes=[],
    )
    assert [no["id"] for no in grafo["nodes"]] == ["empresa:503439800"]
    assert grafo["edges"] == []
    assert grafo["lacos"] == []


def test_co_intervenientes_sem_processos_nao_consulta() -> None:
    # Sem números de processo não há consulta ao Elasticsearch (nem cliente).
    assert padroes._co_intervenientes_cire(None, [], "503439800") == []
    assert padroes._co_intervenientes_cire(None, ["", "  "], "503439800") == []


# ---------------------------------------------------------------------------
# Rotas
# ---------------------------------------------------------------------------
def test_rotas_registadas() -> None:
    from api import padroes_routes  # noqa: PLC0415

    caminhos = {route.path for route in padroes_routes.router.routes}
    assert {
        "/padroes/meta",
        "/padroes/analysis",
        "/padroes/anomalies",
        "/padroes/entities",
        "/padroes/relations",
        "/padroes/news",
        "/padroes/entity/{nif}",
        "/padroes/cache/clear",
    } <= caminhos


def test_catalogo_tem_ids_unicos_e_metodos() -> None:
    catalogo = padroes.catalogo_padroes()
    ids = [item["id"] for item in catalogo]
    assert len(ids) == len(set(ids))
    for item in catalogo:
        assert item["label"] and item["metodo"] and item["descricao"]
        assert isinstance(item["tipo"], str) and item["tipo"]
