"""Testes da **comparação de várias empresas** — puros, sem Elasticsearch.

O que aqui se protege:

- a **linha comparável** de cada empresa (números alinhados e severidade);
- os **cruzamentos**: só conta o que toca duas ou mais empresas (um adjudicante
  de uma só não é um cruzamento);
- a **rede do conjunto**: empresas ligadas pelo comprador, pelo mercado, pelo
  gerente e pelo processo, com os limites de nós;
- o **relatório** da comparação nos três formatos;
- as degradações (sem ES, país errado, nada para comparar).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api import padroes_report as report  # noqa: E402
from api import padroes_service as padroes  # noqa: E402

try:
    import openpyxl  # noqa: F401

    TEM_XLSX = True
except Exception:  # noqa: BLE001
    TEM_XLSX = False
try:
    import reportlab  # noqa: F401

    TEM_PDF = True
except Exception:  # noqa: BLE001
    TEM_PDF = False


def _analise(nif: str, nome: str, *, valor: float = 100_000.0, sinais=(), adjudicantes=(), cargos=(), processos=(), cpvs=()):
    return {
        "pais": "PT",
        "pais_label": "Portugal (Portal BASE)",
        "nif": nif,
        "nome": nome,
        "ficha": {"nome": nome, "papeis": ["adjudicatario"]},
        "anos": [2020, 2025],
        "contratos_total": 500,
        "contratos_analisados": 120,
        "resumo": {
            "contratos": 120,
            "valor_total": valor,
            "valor_mediano": 5_000.0,
            "desvio_mediano": 1.0,
            "taxa_ajuste_direto": 0.2,
            "taxa_aditivo": 0.1,
            "adjudicantes_distintos": 8,
            "contratos_com_sinais": len(sinais),
            "contratos_atipicos_cpv": 3,
            "insolvente": bool(processos),
            "concentracao_adjudicante": 0.4,
        },
        "sinais": [
            {
                "padrao": padrao,
                "label": f"Regra {padrao}",
                "severidade": severidade,
                "contratos": contratos,
                "taxa": 0.1,
                "exemplos": [{"id": "1", "objeto": "Contrato X", "ano": 2024, "valor": 1.0, "detalhe": "detalhe"}],
            }
            for padrao, severidade, contratos in sinais
        ],
        "adjudicantes": [{"nif": nif_adj, "nome": nome_adj, "contratos": 5, "valor": 50_000.0} for nif_adj, nome_adj in adjudicantes],
        "por_cpv": [{"cpv": cpv, "descricao": f"Mercado {cpv}", "contratos": 10, "valor": 20_000.0} for cpv in cpvs],
        "por_procedimento": [{"procedimento": "Concurso público", "contratos": 100, "valor": valor}],
        "por_ano": [{"ano": 2024, "contratos": 60, "valor": valor / 2}],
        "relacoes": {
            "cargos_sociais": [{"nif": nif_p, "nome": nome_p, "cargos": [{"role_org": "Gerência"}]} for nif_p, nome_p in cargos],
            "insolvencias": [
                {"especie": "Insolvência", "processo": processo, "tribunal": "T. X", "data": "2021-01-01"}
                for processo in processos
            ],
            "noticias": [],
            "empresas": [],
        },
        "aviso": "Amostra.",
    }


ADJ_COMUM = ("500000001", "Município A")
PESSOA_COMUM = ("123456789", "Ana Silva")
PROCESSO_COMUM = "123/20.1T8MRA"
CPV_COMUM = "45"


def _duas_empresas():
    primeira = _analise(
        "503439800",
        "ACME, Lda",
        sinais=[("aditivo_valor", "alerta", 12), ("baixa_concorrencia", "info", 30)],
        adjudicantes=[ADJ_COMUM, ("500000002", "Município B")],
        cargos=[PESSOA_COMUM],
        processos=[PROCESSO_COMUM],
        cpvs=[CPV_COMUM, "31"],
    )
    segunda = _analise(
        "509999999",
        "Beta, SA",
        valor=50_000.0,
        sinais=[("valor_atipico", "aviso", 4)],
        adjudicantes=[ADJ_COMUM, ("500000003", "Município C")],
        cargos=[PESSOA_COMUM],
        processos=[PROCESSO_COMUM],
        cpvs=[CPV_COMUM, "79"],
    )
    return [padroes._linha_conjunto(primeira), padroes._linha_conjunto(segunda)]


# ---------------------------------------------------------------------------
# Linha comparável
# ---------------------------------------------------------------------------
def test_linha_conjunto_alinha_os_numeros() -> None:
    linha = padroes._linha_conjunto(_analise("503439800", "ACME, Lda", sinais=[("aditivo_valor", "alerta", 3)]))
    assert linha["nif"] == "503439800"
    assert linha["resumo"]["contratos"] == 120
    assert linha["resumo"]["valor_total"] == 100_000.0
    assert linha["severidade"] == "alerta"
    # O sinal fica compacto: sem a lista de contratos de exemplo.
    assert linha["sinais"][0]["padrao"] == "aditivo_valor"
    assert linha["sinais"][0]["exemplo"] == "Contrato X"
    assert "exemplos" not in linha["sinais"][0]


def test_linha_conjunto_sem_sinais_nao_tem_severidade() -> None:
    linha = padroes._linha_conjunto(_analise("503439800", "ACME, Lda"))
    assert linha["severidade"] is None
    assert linha["sinais"] == []


# ---------------------------------------------------------------------------
# Cruzamentos
# ---------------------------------------------------------------------------
def test_cruzamentos_encontram_o_que_e_partilhado() -> None:
    cruz = padroes._cruzamentos(_duas_empresas())

    adjudicantes = cruz["adjudicantes"]
    assert len(adjudicantes) == 1  # os Municípios B e C só aparecem numa empresa
    assert adjudicantes[0]["nif"] == ADJ_COMUM[0]
    assert adjudicantes[0]["n_empresas"] == 2
    assert adjudicantes[0]["empresas_nome"] == ["ACME, Lda", "Beta, SA"]
    assert adjudicantes[0]["contratos"] == 10

    pessoas = cruz["pessoas"]
    assert len(pessoas) == 1
    assert pessoas[0]["nome"] == "Ana Silva"
    assert pessoas[0]["cargos"] == ["Gerência"]
    assert pessoas[0]["n_empresas"] == 2

    processos = cruz["processos"]
    assert len(processos) == 1
    assert processos[0]["processo"] == PROCESSO_COMUM
    assert processos[0]["empresas"] == ["503439800", "509999999"]

    cpvs = cruz["cpvs"]
    assert [item["cpv"] for item in cpvs] == [CPV_COMUM]
    assert cpvs[0]["n_empresas"] == 2
    assert cpvs[0]["contratos"] == 20


def test_cruzamentos_sem_partilha_ficam_vazios() -> None:
    linha = padroes._linha_conjunto(_analise("503439800", "ACME, Lda", adjudicantes=[ADJ_COMUM], cpvs=["45"]))
    cruz = padroes._cruzamentos([linha])
    assert cruz == {"adjudicantes": [], "pessoas": [], "processos": [], "cpvs": []}


# ---------------------------------------------------------------------------
# Rede do conjunto
# ---------------------------------------------------------------------------
def test_grafo_conjunto_liga_empresas_pelo_que_partilham() -> None:
    linhas = _duas_empresas()
    grafo = padroes._grafo_conjunto(linhas, padroes._cruzamentos(linhas))
    ids = {no["id"] for no in grafo["nodes"]}
    assert {"empresa:503439800", "empresa:509999999"} <= ids
    assert f"adjudicante:{ADJ_COMUM[0]}" in ids  # comprador comum
    assert f"pessoa:{PESSOA_COMUM[0]}" in ids
    assert f"cire:{PROCESSO_COMUM}" in ids
    assert f"cpv:{CPV_COMUM}" in ids  # mercado partilhado

    ligacoes = {(aresta["source"], aresta["target"]) for aresta in grafo["edges"]}
    assert ("empresa:503439800", f"adjudicante:{ADJ_COMUM[0]}") in ligacoes
    assert (f"pessoa:{PESSOA_COMUM[0]}", "empresa:509999999") in ligacoes  # pessoa → empresa
    assert ("empresa:503439800", f"cire:{PROCESSO_COMUM}") in ligacoes
    assert ("empresa:509999999", f"cpv:{CPV_COMUM}") in ligacoes

    tipos = {no["id"]: no["type"] for no in grafo["nodes"]}
    assert tipos[f"cpv:{CPV_COMUM}"] == "cpv"
    assert tipos[f"pessoa:{PESSOA_COMUM[0]}"] == "pessoa"
    assert tipos[f"cire:{PROCESSO_COMUM}"] == "processo"
    assert grafo["meta"]["dimension_a"] == "empresa"
    assert grafo["meta"]["dimension_b"] is None


def test_grafo_conjunto_mostra_compradores_de_cada_empresa() -> None:
    # Sem nada em comum, a rede mostra na mesma os maiores compradores de cada uma.
    primeira = padroes._linha_conjunto(
        _analise("503439800", "ACME, Lda", adjudicantes=[("500000002", "Município B"), ("500000003", "Município C")])
    )
    segunda = padroes._linha_conjunto(_analise("509999999", "Beta, SA", adjudicantes=[("500000004", "Município D")]))
    grafo = padroes._grafo_conjunto([primeira, segunda], padroes._cruzamentos([primeira, segunda]))
    rotulos = {no["id"]: no["role"] for no in grafo["nodes"]}
    assert rotulos["adjudicante:500000002"] == "comprador"
    assert len(grafo["edges"]) == 3  # um comprador por empresa + um segundo da primeira


def test_grafo_conjunto_respeita_os_limites() -> None:
    empresas = [
        padroes._linha_conjunto(
            _analise(
                f"50343980{i}",
                f"Empresa {i}",
                adjudicantes=[(f"5000000{i}{j:02d}", f"Comprador {i}-{j}") for j in range(8)],
                cargos=[(f"12345678{j}", f"Pessoa {j}") for j in range(8)],
                processos=[f"{j}/20" for j in range(6)],
                cpvs=["45", "31", "79"],
            )
        )
        for i in range(4)
    ]
    grafo = padroes._grafo_conjunto(empresas, padroes._cruzamentos(empresas), max_adjudicantes=6, max_pessoas=3, max_processos=2, max_cpvs=2)
    por_tipo: dict = {}
    for no in grafo["nodes"]:
        por_tipo[no["type"]] = por_tipo.get(no["type"], 0) + 1
    assert por_tipo.get("pessoa", 0) == 3
    assert por_tipo.get("processo", 0) == 2
    assert por_tipo.get("cpv", 0) == 2
    assert por_tipo.get("entidade", 0) == 4 + 6  # empresas + compradores no limite


# ---------------------------------------------------------------------------
# Degradações
# ---------------------------------------------------------------------------
def test_analise_empresas_sem_es(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(padroes, "get_es_client", lambda *args, **kwargs: None)
    assert padroes.analise_empresas(nifs=["503439800", "509999999"])["error"] == "Elasticsearch indisponível"


def test_analise_empresas_pais_desconhecido() -> None:
    resposta = padroes.analise_empresas(nifs=["1", "2"], pais="FR")
    assert "país desconhecido" in resposta["error"]


def test_analise_empresas_sem_pedidos(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeClient:
        pass

    monkeypatch.setattr(padroes, "get_es_client", lambda *args, **kwargs: _FakeClient())
    assert padroes.analise_empresas(nifs=[], nomes=["", "  "])["error"] == "sem empresas para comparar"


def test_analise_empresas_ignora_quem_falha(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeClient:
        pass

    monkeypatch.setattr(padroes, "get_es_client", lambda *args, **kwargs: _FakeClient())

    def fake(nif=None, nome=None, **kwargs):
        if nome:
            return {"error": "sem empresa para essa pesquisa"}
        return _analise(str(nif), f"Empresa {nif}", adjudicantes=[("500000002", "Município B")], cpvs=["45"])

    monkeypatch.setattr(padroes, "analise_empresa", fake)
    resposta = padroes.analise_empresas(nifs=["503439800"], nomes=["zzz"], pais="PT")
    assert [linha["nif"] for linha in resposta["empresas"]] == ["503439800"]
    assert resposta["avisos"] == ["zzz: sem empresa para essa pesquisa"]
    assert resposta["totais"]["empresas"] == 1


def test_analise_empresas_corta_no_limite(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeClient:
        pass

    monkeypatch.setattr(padroes, "get_es_client", lambda *args, **kwargs: _FakeClient())
    pedidos: list = []

    def fake(nif=None, nome=None, **kwargs):
        pedidos.append(nif or nome)
        return _analise(str(nif or nome), f"Empresa {nif or nome}")

    monkeypatch.setattr(padroes, "analise_empresa", fake)
    padroes.analise_empresas(nifs=[f"50343980{i}" for i in range(20)], max_empresas=4, pais="PT")
    assert len(pedidos) == 4


# ---------------------------------------------------------------------------
# Relatório da comparação
# ---------------------------------------------------------------------------
def _conjunto() -> dict:
    linhas = _duas_empresas()
    cruz = padroes._cruzamentos(linhas)
    return {
        "pais": "PT",
        "pais_label": "Portugal (Portal BASE)",
        "filtros": {"max_contratos": 120, "ano_from": None, "ano_to": None},
        "empresas": linhas,
        "totais": {
            "empresas": 2,
            "empresas_pedidas": 3,
            "contratos": 240,
            "contratos_total_portal": 1000,
            "valor_total": 150_000.0,
            "valor_mediano": 75_000.0,
            "insolventes": 2,
            "com_sinais": 2,
            "adjudicantes_comuns": len(cruz["adjudicantes"]),
            "pessoas_comuns": len(cruz["pessoas"]),
            "processos_comuns": len(cruz["processos"]),
            "cpvs_comuns": len(cruz["cpvs"]),
        },
        "cruzamentos": cruz,
        "por_cpv": [{"cpv": "45", "descricao": "Construção", "contratos": 20, "valor": 40_000.0, "empresas": 2}],
        "grafo": padroes._grafo_conjunto(linhas, cruz),
        "avisos": ["zzz: sem empresa para essa pesquisa"],
        "aviso": "Comparação a partir de uma amostra.",
    }


def test_empresas_sections_cobre_comparacao_e_cruzamentos() -> None:
    titulos = [secao["title"] for secao in report.empresas_sections(_conjunto())]
    for esperado in (
        "Identificação do conjunto",
        "Comparação das empresas",
        "Sinais por empresa",
        "Adjudicantes comuns (concorrência no mesmo cliente)",
        "Pessoas comuns (órgãos sociais partilhados)",
        "Processos do CIRE partilhados",
        "CPV comuns (mesmo mercado)",
        "Distribuição por CPV (conjunto)",
        "Fontes e limitações",
    ):
        assert esperado in titulos, esperado

    comparacao = next(secao for secao in report.empresas_sections(_conjunto()) if secao["title"] == "Comparação das empresas")
    assert len(comparacao["rows"]) == 2
    assert comparacao["rows"][0][1] == "503439800"
    fontes = report.empresas_sections(_conjunto())[-1]["rows"]
    assert any("zzz" in linha[1] for linha in fontes)


def test_relatorio_conjunto_csv_xlsx_pdf() -> None:
    csv = report.empresas_report(_conjunto(), format="csv")
    assert csv.get("error") is None
    texto = csv["content"].decode("utf-8")
    assert texto.startswith("\ufeff")
    assert "ACME, Lda" in texto
    assert "Comparação das empresas" in texto
    assert "Adjudicantes comuns" in texto
    assert csv["filename"].endswith(".csv") and "2-empresas" in csv["filename"]

    if TEM_XLSX:
        xlsx = report.empresas_report(_conjunto(), format="xlsx")
        assert xlsx["content"][:2] == b"PK"
    if TEM_PDF:
        pdf = report.empresas_report(_conjunto(), format="pdf")
        assert pdf["content"].startswith(b"%PDF")


def test_relatorio_conjunto_erros() -> None:
    assert "não está disponível" in report.empresas_report({"error": "sem empresas"}, format="csv")["error"]
    assert "Sem empresas" in report.empresas_report({"empresas": []}, format="csv")["error"]
    assert "Formato não suportado" in report.empresas_report(_conjunto(), format="docx")["error"]


# ---------------------------------------------------------------------------
# Rotas
# ---------------------------------------------------------------------------
def test_rotas_da_comparacao_registadas() -> None:
    from api import padroes_routes  # noqa: PLC0415

    caminhos = {route.path for route in padroes_routes.router.routes}
    assert {"/padroes/empresas/analise-multipla", "/padroes/empresas/multipla/relatorio"} <= caminhos
