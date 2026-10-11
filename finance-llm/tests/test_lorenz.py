"""Testes do módulo Lorenz (dinâmica da contratação pública) — puros, sem ES.

Cobrem: matemática (Lorenz, Lyapunov, mapa discreto, divergência), hipóteses dos
cenários (prémio de atraso), dependências/propagação, alertas e a leitura das
agregações (com cliente Elasticsearch falso). Não há `pytest-asyncio` no projeto:
tudo aqui é síncrono.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api import lorenz_service as lz  # noqa: E402


# --------------------------------------------------------------------------- #
# Cliente Elasticsearch falso
# --------------------------------------------------------------------------- #
class _ClienteFalso:
    """Cliente mínimo: devolve respostas pré-programadas por ordem de pedido."""

    def __init__(self, buscas=None, mrespostas=None, total=0, mapping=None):
        self._buscas = list(buscas or [])
        self._mrespostas = list(mrespostas or [])
        self._total = total
        self._mapping = mapping or {"contratos": {"mappings": {"properties": {}}}}
        self.pedidos: list = []
        self.indices = self

    # índices
    def get_mapping(self, index=None):  # noqa: A002
        return self._mapping

    def exists(self, index=None):  # noqa: A002
        return True

    def create(self, **kwargs):
        return {"acknowledged": True}

    # pesquisa
    def search(self, **kwargs):
        self.pedidos.append(kwargs.get("body"))
        if not self._buscas:
            return {"hits": {"total": {"value": 0}, "hits": []}, "aggregations": {}}
        resposta = self._buscas.pop(0)
        if isinstance(resposta, Exception):
            raise resposta
        return resposta

    def msearch(self, body=None):
        self.pedidos.append(body)
        if not self._mrespostas:
            return {"responses": []}
        resposta = self._mrespostas.pop(0)
        if isinstance(resposta, Exception):
            raise resposta
        return resposta

    def count(self, **kwargs):
        return {"count": self._total}

    def index(self, **kwargs):
        self.pedidos.append(kwargs)
        return {"result": "created"}

    def get(self, **kwargs):
        return {"_source": {"run_id": kwargs.get("id"), "titulo": "x"}}


def _escopo_simples() -> dict:
    return lz.escopo(area="todas")


# --------------------------------------------------------------------------- #
# 1. Utilitários e CPV
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "codigo,classe,divisao",
    [
        ("33600000-6", "3360", "33"),
        ("3369", "3369", "33"),
        ("85110000-3", "8511", "85"),
        ("45", "45", "45"),
        (None, lz.UNSPECIFIED_LABEL, lz.UNSPECIFIED_LABEL),
        ("-", lz.UNSPECIFIED_LABEL, lz.UNSPECIFIED_LABEL),
    ],
)
def test_classe_e_divisao_cpv(codigo, classe, divisao):
    assert lz._classe_cpv(codigo) == classe
    assert lz._divisao_cpv(codigo) == divisao


def test_num_tolerante():
    assert lz._num(None) == 0.0
    assert lz._num("1 234,5") == 1234.5
    assert lz._num("abc", 7.0) == 7.0
    assert lz._num(float("nan"), 3.0) == 3.0


def test_nome_do_hit_nos_dois_formatos():
    # dentro de `nested` o `_source` é o objeto aninhado
    assert lz._nome_do_hit({"nif": "5", "nome": "ACME"}) == "ACME"
    # fora, é a raiz do documento
    assert lz._nome_do_hit({"adjudicatarios": {"parsed": [{"nif": "5", "nome": "ACME"}]}}) == "ACME"
    assert lz._nome_do_hit({}) == ""
    assert lz._nome_do_hit(None) == ""
    assert lz._nome_de_hits({"nome": {"hits": {"hits": [{"_source": {"nome": "X"}}]}}}) == "X"


# --------------------------------------------------------------------------- #
# 2. Escopo e áreas
# --------------------------------------------------------------------------- #
def test_escopo_area_saude_vira_prefixos_cpv():
    escopo = lz.escopo(area="saude")
    assert escopo["area"] == "saude"
    assert "33" in escopo["cpv_prefixos"] and "851" in escopo["cpv_prefixos"]
    filtros = escopo["query"]["bool"]["filter"]
    assert any("bool" in filtro and "should" in filtro["bool"] for filtro in filtros)


def test_escopo_cpv_sobrepoe_area_e_anos_entram_por_intervalo():
    escopo = lz.escopo(area="saude", cpv="45,302", ano_de=2023, ano_ate=2025)
    assert escopo["cpv_prefixos"] == ["45", "302"]
    intervalos = [filtro["range"]["Ano"] for filtro in escopo["query"]["bool"]["filter"] if "range" in filtro]
    assert intervalos == [{"gte": 2023, "lte": 2025}]


def test_escopo_todas_nao_tem_filtro_cpv():
    escopo = lz.escopo(area="todas")
    assert escopo["cpv_prefixos"] == []
    assert not [
        filtro
        for filtro in escopo["query"]["bool"]["filter"]
        if "bool" in filtro and any("nested" in item for item in filtro["bool"].get("should", []))
    ]


def test_escopo_nif_com_contraparte_usa_must():
    escopo = lz.escopo(nif="500000000", nif_contraparte="511111111")
    filtro = escopo["query"]["bool"]["filter"][0]["bool"]
    assert "must" in filtro and len(filtro["must"]) == 2


def test_guardar_areas_escreve_e_limpa(tmp_path, monkeypatch):
    destino = tmp_path / "config.json"
    monkeypatch.setattr(lz, "CONFIG_PATH", destino)
    monkeypatch.setattr(lz, "_config_cache", {"mtime": None, "dados": None})

    # ids repetidos e prefixos inválidos são limpos (nunca gravamos lixo)
    resultado = lz.guardar_areas(
        [
            {"id": "Saude", "label": "Saúde", "cpv_prefixos": ["33", "abc", " 851 "]},
            {"id": "saude", "label": "duplicado", "cpv_prefixos": ["45"]},
            {"id": "", "label": "sem id"},
        ]
    )
    assert [area["id"] for area in resultado["areas"]] == ["saude"]
    assert resultado["areas"][0]["cpv_prefixos"] == ["33", "851"]
    assert lz.areas()[0]["id"] == "saude"

    # ficheiro corrompido volta às predefinições (sem rebentar)
    destino.write_text("{isto não é json", encoding="utf-8")
    monkeypatch.setattr(lz, "_config_cache", {"mtime": None, "dados": None})
    assert any(area["id"] == "todas" for area in lz.areas())


def test_area_personalizada_por_prefixos():
    area = lz._area_por_id("45,302")
    assert area["cpv_prefixos"] == ["45", "302"]
    assert lz._area_por_id("inexistente")["id"] == "inexistente"


# --------------------------------------------------------------------------- #
# 3. Matemática de Lorenz
# --------------------------------------------------------------------------- #
def test_rho_critico_classico():
    # σ=10, β=8/3 ⇒ ρ_crit ≈ 24,74 (o valor conhecido da literatura)
    assert lz.rho_critico(10.0, 8.0 / 3.0) == pytest.approx(24.7368, abs=1e-3)
    assert lz.rho_critico(1.0, 8.0 / 3.0) == float("inf")  # σ ≤ β+1: sem fronteira


def test_campo_lorenz_valores_conhecidos():
    campo = lz.campo_lorenz([1.0, 2.0, 3.0], 10.0, 28.0, 8.0 / 3.0)
    assert campo[0] == pytest.approx(10.0)          # σ(y−x)
    assert campo[1] == pytest.approx(1 * 25 - 2)    # x(ρ−z) − y
    assert campo[2] == pytest.approx(2 - 8.0)       # xy − βz


def test_passo_rk4_aproxima_a_solucao():
    # Um passo muito pequeno tem de ficar perto da expansão de Euler de 1.ª ordem
    estado = [1.0, 1.0, 1.0]
    passo = lz.passo_rk4(estado, 10.0, 28.0, 8.0 / 3.0, 1e-6)
    esperado = [estado[i] + 1e-6 * valor for i, valor in enumerate(lz.campo_lorenz(estado, 10.0, 28.0, 8.0 / 3.0))]
    assert passo == pytest.approx(esperado, abs=1e-9)


def test_integrar_devolve_trajetoria_com_o_comprimento_pedido():
    trajetoria = lz.integrar([1.0, 1.0, 1.0], 10.0, 28.0, 8.0 / 3.0, passos=100, guardar_cada=10)
    assert len(trajetoria) == 11  # inicial + 10 amostras
    assert all(len(ponto) == 3 for ponto in trajetoria)
    # o sistema clássico fica limitado (não diverge para infinito)
    assert max(abs(valor) for ponto in trajetoria for valor in ponto) < 100


def test_lyapunov_classico_e_sensivel():
    resultado = lz.lyapunov_maximo([1.0, 1.0, 1.0], 10.0, 28.0, 8.0 / 3.0, perturbacao=1e-8, passos=20000, dt=0.01)
    # o valor de referência é ≈ 0,906
    assert 0.7 < resultado["lambda"] < 1.05
    assert resultado["regime"] == "sensivel"
    assert resultado["intervalos"] > 0


def test_lyapunov_subcritico_dissipa():
    resultado = lz.lyapunov_maximo([1.0, 1.0, 1.0], 10.0, 0.5, 8.0 / 3.0, perturbacao=1e-8, passos=20000, dt=0.01)
    assert resultado["lambda"] < 0
    assert resultado["regime"] == "dissipador"


def test_divergencia_euclidiana():
    assert lz.divergencia([0.0, 0.0, 0.0], [3.0, 4.0, 0.0]) == pytest.approx(5.0)


# --------------------------------------------------------------------------- #
# 4. Mapa discreto, estado e parâmetros
# --------------------------------------------------------------------------- #
def test_ajustar_mapa_recupera_transformacao_linear_conhecida():
    # x_{t+1} = A x_t + b, com A = [[0.9, 0], [0.1, 0.5]] e b = [1, -1]
    a = [[0.9, 0.0], [0.1, 0.5]]
    b = [1.0, -1.0]
    estados = [[0.0, 0.0]]
    for _ in range(12):
        estados.append(lz.aplicar_mapa(estados[-1], a, b))
    ajuste = lz.ajustar_mapa_linear(estados)
    assert ajuste["disponivel"] is True
    assert ajuste["r2"] == pytest.approx(1.0, abs=1e-6)
    assert ajuste["A"][0][0] == pytest.approx(0.9, abs=1e-6)
    assert ajuste["b"][0] == pytest.approx(1.0, abs=1e-6)
    assert ajuste["raio_espectral"] == pytest.approx(0.9, abs=1e-6)


def test_ajustar_mapa_serie_curta_indisponivel():
    assert lz.ajustar_mapa_linear([[0.0, 0.0], [1.0, 1.0]])["disponivel"] is False


def test_divergencia_mapa_cresce_e_estima_lyapunov():
    # A = 1,5·I ⇒ D_t ∝ 1,5^t e λ ≈ ln 1,5 ≈ 0,405
    ajuste = lz.divergencia_mapa([0.0, 0.0, 0.0], [[1.5, 0, 0], [0, 1.5, 0], [0, 0, 1.5]], [0.0, 0.0, 0.0], perturbacao=1e-3, passos=6)
    assert ajuste["lambda_empirico"] == pytest.approx(math.log(1.5), abs=0.05)
    assert ajuste["D_normalizada"][-1] > ajuste["D_normalizada"][0]
    assert ajuste["regime"] == "sensivel"


def test_divergencia_mapa_contrai():
    ajuste = lz.divergencia_mapa([0.0, 0.0, 0.0], [[0.5, 0, 0], [0, 0.5, 0], [0, 0, 0.5]], [0.0, 0.0, 0.0], perturbacao=1e-3, passos=6)
    assert ajuste["lambda_empirico"] < 0
    assert ajuste["regime"] == "dissipador"


def _periodos_falsos() -> list:
    return [
        {"periodo": "2020", "contratos": 100, "valor": 1_000_000.0, "p50": 5_000.0, "p95": 50_000.0, "p99": 90_000.0,
         "cauda": 17.0, "compradores": 10, "fornecedores": 30, "quota_top1": 0.10, "hhi_top": 0.05,
         "ajuste_direto": 30, "taxa_ajuste_direto": 0.3},
        {"periodo": "2021", "contratos": 120, "valor": 1_300_000.0, "p50": 5_200.0, "p95": 51_000.0, "p99": 95_000.0,
         "cauda": 17.3, "compradores": 11, "fornecedores": 33, "quota_top1": 0.14, "hhi_top": 0.07,
         "ajuste_direto": 40, "taxa_ajuste_direto": 0.33},
        {"periodo": "2022", "contratos": 90, "valor": 900_000.0, "p50": 4_900.0, "p95": 48_000.0, "p99": 88_000.0,
         "cauda": 17.1, "compradores": 9, "fornecedores": 28, "quota_top1": 0.09, "hhi_top": 0.04,
         "ajuste_direto": 25, "taxa_ajuste_direto": 0.28},
    ]


def test_estado_da_serie_normaliza_sem_nan_e_mantem_cardinalidade():
    estado = lz.estado_da_serie(_periodos_falsos())
    assert len(estado["coordenadas"]) == 3
    assert len(estado["coordenadas"][0]) == 3
    assert all(math.isfinite(valor) for linha in estado["coordenadas"] for valor in linha)
    # a normalização é robusta: cada coluna fica centrada perto de 0
    for coluna in range(3):
        coluna_valores = [linha[coluna] for linha in estado["coordenadas"]]
        assert abs(sorted(coluna_valores)[1]) < 1.0


def test_estado_da_serie_sem_periodos():
    estado = lz.estado_da_serie([])
    assert estado["coordenadas"] == [] and estado["periodos"] == []


def test_estimar_parametros_margem_acima_da_mediana():
    periodos = _periodos_falsos()
    # última dependência (0,09) está ABAIXO da mediana (0,10) ⇒ margem < 1
    params = lz.estimar_parametros(periodos)
    assert params["regime"] == "dissipador"
    assert params["margem"] < 1
    assert 6.0 <= params["sigma"] <= 20.0
    assert 2.2 <= params["beta"] <= 4.0
    assert params["rho"] == pytest.approx(params["rho_critico"] * params["margem"], rel=1e-6)

    # e com dependência acima da mediana fica amplificador
    fortes = [dict(periodo, quota_top1=0.05) for periodo in periodos]
    fortes[-1]["quota_top1"] = 0.40
    assert lz.estimar_parametros(fortes)["regime"] == "amplificador"


def test_estimar_parametros_sem_periodos():
    assert lz.estimar_parametros([])["disponivel"] is False


# --------------------------------------------------------------------------- #
# 5. Dependências, propagação e cenários
# --------------------------------------------------------------------------- #
def _dados_falsos() -> dict:
    """Dois compradores; o primeiro depende 70 % do fornecedor F1."""
    return {
        "compradores": [
            {
                "nif": "1", "nome": "Comprador Crítico", "valor": 1_000_000.0, "contratos": 10,
                "quota_top1": 0.70, "hhi_top": 0.50, "cobertura_top": 1.0, "taxa_ajuste_direto": 0.2,
                "fornecedores": [
                    {"nif": "F1", "nome": "Fornecedor F1", "valor": 700_000.0, "contratos": 7, "quota": 0.70},
                    {"nif": "F2", "nome": "Fornecedor F2", "valor": 300_000.0, "contratos": 3, "quota": 0.30},
                ],
                "cpvs": [{"codigo": "33600000-6", "classe": "3360", "divisao": "33", "valor": 1_000_000.0, "contratos": 10, "quota": 1.0}],
            },
            {
                "nif": "2", "nome": "Comprador Disperso", "valor": 500_000.0, "contratos": 8,
                "quota_top1": 0.20, "hhi_top": 0.08, "cobertura_top": 1.0, "taxa_ajuste_direto": 0.1,
                "fornecedores": [
                    {"nif": "F1", "nome": "Fornecedor F1", "valor": 100_000.0, "contratos": 2, "quota": 0.20},
                    {"nif": "F3", "nome": "Fornecedor F3", "valor": 400_000.0, "contratos": 6, "quota": 0.80},
                ],
                "cpvs": [{"codigo": "33600000-6", "classe": "3360", "divisao": "33", "valor": 500_000.0, "contratos": 8, "quota": 1.0}],
            },
        ],
        "arestas": [
            {"comprador_nif": "1", "comprador_nome": "Comprador Crítico", "fornecedor_nif": "F1", "fornecedor_nome": "Fornecedor F1", "valor": 700_000.0, "contratos": 7, "quota_no_comprador": 0.70},
            {"comprador_nif": "1", "comprador_nome": "Comprador Crítico", "fornecedor_nif": "F2", "fornecedor_nome": "Fornecedor F2", "valor": 300_000.0, "contratos": 3, "quota_no_comprador": 0.30},
            {"comprador_nif": "2", "comprador_nome": "Comprador Disperso", "fornecedor_nif": "F1", "fornecedor_nome": "Fornecedor F1", "valor": 100_000.0, "contratos": 2, "quota_no_comprador": 0.20},
            {"comprador_nif": "2", "comprador_nome": "Comprador Disperso", "fornecedor_nif": "F3", "fornecedor_nome": "Fornecedor F3", "valor": 400_000.0, "contratos": 6, "quota_no_comprador": 0.80},
        ],
    }


def _cpvs_falsos() -> dict:
    return {
        "classes": [
            {
                "classe": "3360", "divisao": "33", "valor": 1_500_000.0, "contratos": 18, "compradores": 2,
                "quota_top1": 0.60, "hhi": 0.4, "cobertura_top": 1.0,
                "fornecedores": [
                    {"nif": "F1", "nome": "Fornecedor F1", "valor": 900_000.0, "contratos": 9, "quota": 0.60},
                    {"nif": "F3", "nome": "Fornecedor F3", "valor": 600_000.0, "contratos": 6, "quota": 0.40},
                ],
            }
        ]
    }


def test_dependencias_calcula_quotas_e_alertas():
    dep = lz.dependencias(_dados_falsos())
    f1 = next(item for item in dep["fornecedores"] if item["nif"] == "F1")
    assert f1["valor"] == pytest.approx(800_000.0)
    assert f1["quota_max"] == pytest.approx(0.70)
    assert f1["n_compradores"] == 2
    assert [c["nome"] for c in f1["criticos"]] == ["Comprador Crítico"]

    critico = next(item for item in dep["compradores"] if item["nif"] == "1")
    # fragilidade = quota_top1 × (1 − alternativa) × (1 + ajuste direto)
    assert critico["fragilidade"] == pytest.approx(0.70 * (1 - 0.30) * 1.2, rel=1e-6)
    assert critico["critico"] is True
    assert any(alerta["tipo"] == "dependencia_extrema" for alerta in dep["alertas"])


def test_propagar_primeira_e_segunda_ordem():
    resultado = lz.propagar(_dados_falsos(), fornecedor_nif="F1", atraso_dias=30, cpvs=_cpvs_falsos())
    assert resultado["disponivel"] is True
    assert resultado["origem"]["nif"] == "F1"
    assert resultado["premio_urgencia"] == pytest.approx(0.07)

    # o comprador com 70 % aparece primeiro (criticidade), o outro atrás
    assert [linha["comprador_nif"] for linha in resultado["diretos"]] == ["1", "2"]
    primeiro = resultado["diretos"][0]
    # exposição base = valor da relação (700 000 = 1 000 000 × 0,70), agravada pela
    # perda de capacidade ponderada pela quota
    assert primeiro["exposto"] == pytest.approx(700_000.0 * (1 + 0.25 * 0.70))
    assert primeiro["dificuldade_substituicao"] == pytest.approx(1 - 0.60, abs=1e-9)
    assert primeiro["sobrecusto_estimado"] == pytest.approx(primeiro["exposto"] * 0.07 * (0.5 + 0.4), rel=1e-6)
    assert primeiro["alternativas"] and primeiro["alternativas"][0]["nif"] == "F3"

    # 2.ª ordem: a realocação vai para as alternativas observadas (F3)
    assert any(linha["nif"] == "F3" for linha in resultado["segunda_ordem"])
    assert resultado["impacto_total_estimado"] > 0
    assert resultado["mitigacoes"]
    assert any("Prémio de urgência" in hipotese for hipotese in resultado["hipoteses"])


def test_propagar_sem_fornecedores_indisponivel():
    resultado = lz.propagar({"compradores": [], "arestas": []}, fornecedor_nif="X")
    assert resultado["disponivel"] is False
    assert "motivo" in resultado


def test_propagar_por_nome_parcial_e_recuo_para_o_primeiro():
    por_nome = lz.propagar(_dados_falsos(), fornecedor_nome="f1", cpvs=_cpvs_falsos())
    assert por_nome["origem"]["nif"] == "F1"
    por_omissao = lz.propagar(_dados_falsos(), cpvs=_cpvs_falsos())
    assert por_omissao["origem"]["nif"] == "F1"  # o maior do escopo


def test_premio_atraso_interpola_e_satura():
    assert lz.premio_atraso(7) == pytest.approx(0.02)
    assert lz.premio_atraso(30) == pytest.approx(0.07)
    assert lz.premio_atraso(60) == pytest.approx(0.15)
    assert lz.premio_atraso(45) == pytest.approx(0.11, abs=1e-9)
    assert lz.premio_atraso(0) == pytest.approx(0.0)
    assert lz.premio_atraso(365) == pytest.approx(0.25)


def test_cenarios_atraso_crescem_com_o_atraso():
    cenarios = lz.cenarios_atraso(_dados_falsos(), fornecedor_nif="F1", cpvs=_cpvs_falsos())
    linhas = cenarios["cenarios"]
    assert [linha["atraso_dias"] for linha in linhas] == [7, 30, 60]
    assert linhas[0]["fator_vs_7d"] == pytest.approx(1.0)
    assert linhas[0]["impacto_total"] < linhas[1]["impacto_total"] < linhas[2]["impacto_total"]


def test_sensibilidade_inclinacao_positiva():
    resultado = lz.sensibilidade(_dados_falsos(), fornecedor_nif="F1", cpvs=_cpvs_falsos())
    assert len(resultado["pontos"]) == 3
    assert resultado["inclinacao"] > 0


def test_ranking_amplificadores_ordena_e_traz_contribuintes():
    linhas = lz.ranking_amplificadores(_dados_falsos(), cpvs=_cpvs_falsos(), topo=3)
    # F2 vem antes de F3: não aparece nas alternativas do CPV 3360, por isso a
    # dificuldade de substituição é máxima (1,0 contra 0,4).
    assert [linha["nif"] for linha in linhas] == ["F1", "F2", "F3"]
    f1 = linhas[0]
    assert f1["alcance"] == pytest.approx(1.0)          # toca os dois compradores
    assert f1["exposicao"] == pytest.approx(800_000.0 / 1_500_000.0)
    assert f1["contribuintes"][0]["nif"] == "1"          # a relação com mais peso
    assert linhas[0]["amplificacao"] > linhas[1]["amplificacao"] > linhas[2]["amplificacao"]


def test_alertas_combinados_tres_origens_e_ordem():
    dep = lz.dependencias(_dados_falsos())
    dep_cpvs = lz._dependencia_cpv(_cpvs_falsos())
    amplificadores = lz.ranking_amplificadores(_dados_falsos(), cpvs=_cpvs_falsos(), topo=3)
    alertas = lz._alertas_combinados(dep, dep_cpvs, amplificadores)
    origens = {alerta["origem"] for alerta in alertas}
    assert origens == {"dependencia", "cpv", "amplificacao"}
    severidades = [alerta["severidade"] for alerta in alertas]
    assert severidades == sorted(severidades, key=lambda valor: {"alta": 0, "média": 1, "baixa": 2}[valor])
    # o CPV a 60 % é «média» (limiar de 75 %) mas continua sinalizado
    cpv = next(alerta for alerta in alertas if alerta["origem"] == "cpv")
    assert cpv["severidade"] == "média"


def test_dependencia_cpv_marca_um_so_fornecedor():
    dep_cpvs = lz._dependencia_cpv(_cpvs_falsos())
    classe = dep_cpvs["classes"][0]
    assert classe["single_source"] is True
    assert dep_cpvs["single_source"] == 1
    assert classe["fragilidade"] == pytest.approx(0.60 * (1 - 0.40), rel=1e-6)


# --------------------------------------------------------------------------- #
# 6. Agregações (cliente falso)
# --------------------------------------------------------------------------- #
def _resposta_serie(anos: int = 3) -> dict:
    buckets = []
    for indice in range(anos):
        buckets.append(
            {
                "key": 2020 + indice,
                "doc_count": 100 + indice,
                "valor": {"value": 1_000_000.0 * (indice + 1)},
                "valor_efetivo": {"value": 900_000.0},
                # `keyed: True` devolve `{"values": {...}}` — regressão do defeito
                # em que a «cauda» vinha sempre a zero.
                "percentis": {"values": {"50.0": 5_000.0, "95.0": 50_000.0, "99.0": 95_000.0 + indice}},
                "compradores": {"n": {"value": 10 + indice}},
                "fornecedores": {"n": {"value": 30 + indice}},
                "top_fornecedores": {
                    "por_nif": {
                        "buckets": [
                            {"key": "F1", "doc_count": 10, "documento": {"valor": {"value": 300_000.0}}},
                            {"key": "F2", "doc_count": 5, "documento": {"valor": {"value": 100_000.0}}},
                        ]
                    }
                },
                "procedimentos": {"buckets": [{"key": "Ajuste Direto Regime Geral", "doc_count": 40}, {"key": "Concurso público", "doc_count": 60}]},
            }
        )
    return {"hits": {"total": {"value": sum(bucket["doc_count"] for bucket in buckets)}}, "aggregations": {"periodos": {"buckets": buckets}}}


def test_serie_extrai_periodos_percentis_e_ajuste_direto(monkeypatch):
    cliente = _ClienteFalso(buscas=[_resposta_serie(3)])
    monkeypatch.setattr(lz, "get_es_client", lambda *a, **k: cliente)
    dados = lz.serie(_escopo_simples())
    assert len(dados["periodos"]) == 3              # cardinalidade fixa (3 buckets = 3 períodos)
    assert [periodo["periodo"] for periodo in dados["periodos"]] == ["2020", "2021", "2022"]
    primeiro = dados["periodos"][0]
    assert primeiro["p50"] == 5_000.0 and primeiro["p99"] == 95_000.0
    assert primeiro["cauda"] == pytest.approx((95_000.0 - 5_000.0) / 5_000.0)
    assert primeiro["taxa_ajuste_direto"] == pytest.approx(0.4)
    assert primeiro["quota_top1"] == pytest.approx(0.3)
    assert primeiro["top_fornecedores"][0]["nif"] == "F1"
    # o campo de procedimento não resolve como keyword direto ⇒ runtime mapping
    assert "runtime_mappings" in cliente.pedidos[-1]


def test_serie_degrada_sem_elastico(monkeypatch):
    monkeypatch.setattr(lz, "get_es_client", lambda *a, **k: None)
    dados = lz.serie(_escopo_simples())
    assert dados["erro"] and dados["periodos"] == []


def test_matriz_dependencia_le_msearch_e_calcula_quotas(monkeypatch):
    topo = {
        "hits": {"total": {"value": 3}},
        "aggregations": {
            "partes": {
                "nested": {},
                "por_nif": {
                    "buckets": [
                        {"key": "1", "doc_count": 7, "nome": {"hits": {"hits": [{"_source": {"nif": "1", "nome": "Comprador Um"}}]}}, "documento": {"valor": {"value": 1_000_000.0}}},
                        {"key": "2", "doc_count": 3, "nome": {"hits": {"hits": [{"_source": {"nif": "2", "nome": "Comprador Dois"}}]}}, "documento": {"valor": {"value": 500_000.0}}},
                    ]
                },
            }
        },
    }
    resposta_comprador = {
        "hits": {"total": {"value": 7}},
        "aggregations": {
            "valor": {"value": 1_000_000.0},
            "contrapartes": {
                "por_nif": {
                    "buckets": [
                        {"key": "F1", "doc_count": 7, "nome": {"hits": {"hits": [{"_source": {"nif": "F1", "nome": "Fornecedor Um"}}]}}, "documento": {"valor": {"value": 700_000.0}}},
                        {"key": "F2", "doc_count": 1, "nome": {"hits": {"hits": [{"_source": {"nif": "F2", "nome": "Fornecedor Dois"}}]}}, "documento": {"valor": {"value": 100_000.0}}},
                    ]
                }
            },
            "cpvs": {"por_codigo": {"buckets": [{"key": "33600000-6", "doc_count": 7, "documento": {"valor": {"value": 1_000_000.0}}}]}},
            "procedimentos": {"buckets": [{"key": "Consulta Prévia", "doc_count": 7}]},
        },
    }
    cliente = _ClienteFalso(buscas=[topo], mrespostas=[{"responses": [resposta_comprador]}])
    monkeypatch.setattr(lz, "get_es_client", lambda *a, **k: cliente)

    dados = lz.matriz_dependencia(_escopo_simples())
    assert len(dados["compradores"]) == 1
    comprador = dados["compradores"][0]
    assert comprador["nome"] == "Comprador Um"
    assert comprador["valor"] == pytest.approx(1_000_000.0)
    assert comprador["quota_top1"] == pytest.approx(0.7)
    assert comprador["hhi_top"] == pytest.approx(0.49 + 0.01)
    assert comprador["cpvs"][0]["classe"] == "3360"
    assert comprador["taxa_ajuste_direto"] == pytest.approx(1.0)
    aresta = next(a for a in dados["arestas"] if a["fornecedor_nif"] == "F1")
    assert aresta["quota_no_comprador"] == pytest.approx(0.7)
    # F1 só aparece neste comprador analisado ⇒ 100 % do seu valor no escopo coberto
    assert aresta["quota_no_fornecedor"] == pytest.approx(1.0)


def test_matriz_cpv_agrega_por_classe_e_le_fornecedores(monkeypatch):
    principal = {
        "hits": {"total": {"value": 10}},
        "aggregations": {
            "cpvs": {
                "por_codigo": {
                    "buckets": [
                        {"key": "33600000-6", "doc_count": 6, "documento": {"valor": {"value": 600_000.0}}},
                        {"key": "33690000-3", "doc_count": 4, "documento": {"valor": {"value": 400_000.0}}},
                    ]
                }
            }
        },
    }
    classe = {
        "hits": {"total": {"value": 10}},
        "aggregations": {
            "valor": {"value": 1_000_000.0},
            "compradores": {"n": {"value": 4}},
            "fornecedores": {
                "por_nif": {
                    "buckets": [
                        {"key": "F1", "doc_count": 6, "nome": {"hits": {"hits": [{"_source": {"nif": "F1", "nome": "Dominante"}}]}}, "documento": {"valor": {"value": 800_000.0}}},
                        {"key": "F2", "doc_count": 4, "nome": {"hits": {"hits": [{"_source": {"nif": "F2", "nome": "Alternativa"}}]}}, "documento": {"valor": {"value": 200_000.0}}},
                    ]
                }
            },
        },
    }
    cliente = _ClienteFalso(buscas=[principal], mrespostas=[{"responses": [classe, classe]}])
    monkeypatch.setattr(lz, "get_es_client", lambda *a, **k: cliente)

    dados = lz.matriz_cpv(_escopo_simples(), top_cpvs=2)
    # 3360 e 3369 são classes **diferentes** (4 dígitos), cada uma com o seu valor
    assert [classe["classe"] for classe in dados["classes"]] == ["3360", "3369"]
    classe_dados = dados["classes"][0]
    assert classe_dados["valor"] == pytest.approx(600_000.0)
    assert classe_dados["contratos"] == 6
    assert classe_dados["quota_top1"] == pytest.approx(0.8)
    assert classe_dados["fornecedores"][0]["nome"] == "Dominante"
    assert dados["notas"]


def test_evidencias_limita_e_devolve_contratos(monkeypatch):
    resposta = {
        "hits": {
            "total": {"value": 42},
            "hits": [
                {
                    "_id": "abc",
                    "_source": {
                        "idcontrato": "14703959",
                        "objectoContrato": "Fornecimento de medicamentos",
                        "precoContratual": 1_000_000.0,
                        "dataCelebracaoContrato": "2025-03-01",
                        "Ano": 2025,
                        "tipoprocedimento": "Ajuste Direto Regime Geral",
                        "cpv": [{"code": "33600000-6"}],
                        "adjudicantes": {"parsed": [{"nif": "1", "nome": "ULS X"}]},
                        "adjudicatarios": {"parsed": [{"nif": "F1", "nome": "Farmacêutica Y"}]},
                    },
                }
            ],
        }
    }
    cliente = _ClienteFalso(buscas=[resposta])
    monkeypatch.setattr(lz, "get_es_client", lambda *a, **k: cliente)
    dados = lz.evidencias(_escopo_simples(), comprador_nif="1", fornecedor_nif="F1", limite=5)
    assert dados["total"] == 42
    item = dados["itens"][0]
    assert item["idcontrato"] == "14703959"
    assert item["cpv"] == "33600000-6"
    assert item["adjudicante"] == "ULS X"
    assert item["adjudicatario"] == "Farmacêutica Y"
    filtros = cliente.pedidos[-1]["query"]["bool"]["filter"]
    assert len(filtros) == 2  # comprador + fornecedor


# --------------------------------------------------------------------------- #
# 7. Orquestração
# --------------------------------------------------------------------------- #
def test_grafo_studio_liga_comprador_a_fornecedor():
    dados = _dados_falsos()
    dep = lz.dependencias(dados)
    grafo = lz._grafo_studio(dados, dep)
    assert len(grafo["nodes"]) == 5  # 2 compradores + 3 fornecedores
    assert len(grafo["edges"]) == 4
    aresta = next(a for a in grafo["edges"] if a["value"] == 700_000.0)
    assert aresta["quota"] == pytest.approx(0.70)
    assert grafo["meta"]["dimension_a"] == "comprador"


def test_meta_traz_areas_parametros_e_ambitos(monkeypatch):
    cliente = _ClienteFalso(total=1234)
    monkeypatch.setattr(lz, "get_es_client", lambda *a, **k: cliente)
    dados = lz.meta()
    assert dados["modulo"] == "lorenz"
    assert any(area["id"] == "saude" for area in dados["areas"])
    assert any(area["id"] == "construcao" for area in dados["areas"])  # não é só saúde
    assert dados["documentos"] == 1234
    assert dados["limites"]["top_compradores"] == lz.parametros()["top_compradores"]
    assert len(dados["arquitetura"]) == 5


def test_panorama_junta_tudo_e_respeita_os_tempos(monkeypatch):
    cliente = _ClienteFalso(
        buscas=[
            _resposta_serie(3),
            {  # topo de compradores
                "hits": {"total": {"value": 1}},
                "aggregations": {
                    "partes": {
                        "por_nif": {
                            "buckets": [
                                {"key": "1", "doc_count": 9, "nome": {"hits": {"hits": [{"_source": {"nif": "1", "nome": "Comprador Um"}}]}}, "documento": {"valor": {"value": 1_000_000.0}}}
                            ]
                        }
                    }
                },
            },
            {  # CPV principal
                "hits": {"total": {"value": 10}},
                "aggregations": {"cpvs": {"por_codigo": {"buckets": [{"key": "33600000-6", "doc_count": 10, "documento": {"valor": {"value": 1_000_000.0}}}]}}},
            },
        ],
        mrespostas=[
            {"responses": [  # detalhe do comprador
                {
                    "hits": {"total": {"value": 9}},
                    "aggregations": {
                        "valor": {"value": 1_000_000.0},
                        "contrapartes": {"por_nif": {"buckets": [
                            {"key": "F1", "doc_count": 6, "nome": {"hits": {"hits": [{"_source": {"nif": "F1", "nome": "Fornecedor Um"}}]}}, "documento": {"valor": {"value": 800_000.0}}},
                            {"key": "F2", "doc_count": 3, "nome": {"hits": {"hits": [{"_source": {"nif": "F2", "nome": "Fornecedor Dois"}}]}}, "documento": {"valor": {"value": 200_000.0}}},
                        ]}},
                        "cpvs": {"por_codigo": {"buckets": [{"key": "33600000-6", "doc_count": 9, "documento": {"valor": {"value": 1_000_000.0}}}]}},
                        "procedimentos": {"buckets": [{"key": "Ajuste Direto", "doc_count": 9}]},
                    },
                }
            ]},
            {"responses": [  # detalhe do CPV (SINGLE SOURCE: 80 %)
                {
                    "hits": {"total": {"value": 10}},
                    "aggregations": {
                        "valor": {"value": 1_000_000.0},
                        "compradores": {"n": {"value": 1}},
                        "fornecedores": {"por_nif": {"buckets": [
                            {"key": "F1", "doc_count": 8, "nome": {"hits": {"hits": [{"_source": {"nif": "F1", "nome": "Fornecedor Um"}}]}}, "documento": {"valor": {"value": 800_000.0}}},
                            {"key": "F2", "doc_count": 2, "nome": {"hits": {"hits": [{"_source": {"nif": "F2", "nome": "Fornecedor Dois"}}]}}, "documento": {"valor": {"value": 200_000.0}}},
                        ]}},
                    },
                }
            ]},
        ],
    )
    monkeypatch.setattr(lz, "get_es_client", lambda *a, **k: cliente)
    monkeypatch.setattr(lz, "parametros", lambda: {**lz.PARAMETROS_DEFAULT, "passos_lorenz": 400})

    resultado = lz.panorama(_escopo_simples(), incluir_grafo=True)
    assert resultado["kpis"]["contratos"] == 3 * 100 + 3  # 100+101+102
    assert resultado["kpis"]["compradores_analisados"] == 1
    assert resultado["kpis"]["cpvs_single_source"] == 1
    assert resultado["dependencias"]["alertas_por_origem"]["cpv"] == 1
    assert resultado["dinamica"]["lorenz"]["lyapunov"]["intervalos"] > 0
    assert resultado["grafo"]["edges"]
    assert set(resultado["tempos"]) >= {"serie", "dependencia", "cpv", "dinamica", "lorenz"}
    assert resultado["cobertura"]["documentos_escopo"] == 303
    assert resultado["hipoteses"]


def test_panorama_propaga_erro_do_elastico(monkeypatch):
    cliente = _ClienteFalso(buscas=[RuntimeError("ES em baixo")])
    monkeypatch.setattr(lz, "get_es_client", lambda *a, **k: cliente)
    resultado = lz.panorama(_escopo_simples())
    assert "erro" in resultado


def test_guardar_e_listar_execucoes_sem_elastico(monkeypatch):
    monkeypatch.setattr(lz, "get_es_client", lambda *a, **k: None)
    assert lz.guardar_execucao(_escopo_simples(), {})["erro"]
    assert lz.listar_execucoes() == []
    assert lz.obter_execucao("x") is None


def test_guardar_execucao_grava_com_id_proprio(monkeypatch):
    cliente = _ClienteFalso()
    monkeypatch.setattr(lz, "get_es_client", lambda *a, **k: cliente)
    resultado = lz.guardar_execucao(_escopo_simples(), {"kpis": {"contratos": 1}}, titulo="Teste")
    assert resultado["ok"] is True
    assert resultado["run_id"].startswith("lz-")
    assert cliente.pedidos[-1]["index"] == lz.LORENZ_RUNS_INDEX


# --------------------------------------------------------------------------- #
# 8. Regressões específicas
# --------------------------------------------------------------------------- #
def test_regressao_percentis_keyed_nao_devolvem_zero(monkeypatch):
    """O defeito real: `keyed: True` devolve `{"values": …}` e a cauda ficava 0."""
    resposta = {
        "hits": {"total": {"value": 2}},
        "aggregations": {
            "periodos": {
                "buckets": [
                    {
                        "key": 2024, "doc_count": 1, "valor": {"value": 100.0}, "valor_efetivo": {"value": 0.0},
                        "percentis": {"values": {"50.0": 10.0, "95.0": 20.0, "99.0": 40.0}},
                        "compradores": {"n": {"value": 1}}, "fornecedores": {"n": {"value": 1}},
                        "top_fornecedores": {"por_nif": {"buckets": []}}, "procedimentos": {"buckets": []},
                    }
                ]
            }
        },
    }
    cliente = _ClienteFalso(buscas=[resposta])
    monkeypatch.setattr(lz, "get_es_client", lambda *a, **k: cliente)
    periodo = lz.serie(_escopo_simples())["periodos"][0]
    assert periodo["p50"] == 10.0
    assert periodo["cauda"] == pytest.approx(3.0)


def test_regressao_terms_nao_ordena_por_agregacao_reverse_nested(monkeypatch):
    """Ordenar o `terms` pelo valor do `reverse_nested` dá 500 no Elasticsearch."""
    cliente = _ClienteFalso(buscas=[{"hits": {"total": {"value": 0}}, "aggregations": {"partes": {"por_nif": {"buckets": []}}}}])
    monkeypatch.setattr(lz, "get_es_client", lambda *a, **k: cliente)
    lz._topo_por_papel(_escopo_simples(), "adjudicante", 10)
    corpo = cliente.pedidos[-1]
    termos = corpo["aggs"]["partes"]["aggs"]["por_nif"]["terms"]
    assert "order" not in termos
    assert termos["size"] >= 40
