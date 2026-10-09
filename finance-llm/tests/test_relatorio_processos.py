"""Relatório de processos e dados da empresa (modelo «Relatório de Processos»).

Regressão de 2026-10-09: a ficha da entidade passou a ter um segundo relatório,
com indicadores de risco (insolvências/PER, processos judiciais, situação fiscal
e contributiva), atos societários e contratos — inspirado nos relatórios de
processos usados na avaliação de risco de crédito.

O que se protege aqui é a montagem das secções (`_processos_blocks`): a tabela
de insolvências não pode repetir o mesmo processo (cada processo tem várias
publicações), os indicadores têm de trazer os números certos e o PDF tem de sair
com as notas legais.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from api.entity_enrichment_service import (
    NOTAS_LEGAIS_PROCESSOS,
    _banda_idade,
    _generate_pdf_report,
    _nomes,
    _papeis_no_cire,
    _processos_blocks,
)

NIF = "504615947"


def _dados() -> Dict[str, Any]:
    return {
        "nif": NIF,
        "name": "EMPRESA EXEMPLO, S.A.",
        "status": "Ativa",
        "cae": "46380",
        "cae_description": "Comércio por grosso de produtos alimentares",
        "constituicao": "2016-05-13",
        "contracts_total": 10,
        "contracts_value": 1234.5,
        "contratos_total": 10,
        "cadastro": {
            "adjudicatario": {"first_year": 2016, "last_year": 2026},
        },
        "contratos": [
            {
                "dataCelebracaoContrato": "2026-01-31",
                "adjudicantes": {"parsed": [{"nome": "Município de Aveiro", "nif": "506775870"}]},
                "objectoContrato": "Aquisição de géneros alimentícios",
                "precoContratual": 1500.0,
            }
        ],
        "by_cpv": [{"key": "15800000", "description": "Produtos alimentares", "total_value": 1000.0, "count": 4}],
        "societario": [
            {"data_publicacao": "2025-03-20", "tipo_label": "Designação de órgãos sociais", "firma": "EMPRESA EXEMPLO, S.A."}
        ],
        "societario_total": 1,
        "cire": {
            "total": 3,
            "items": [
                {
                    "pub_id": "a",
                    "data_publicacao": "2026-01-10",
                    "tribunal": "Comarca de Aveiro",
                    "processo": "100/26.0T8AVR",
                    "tipo": "Insolvência",
                    "intervenientes": [{"papel": "Insolvente", "nome": "Outra, Lda", "nif": "500000000"}],
                },
                {
                    "pub_id": "b",
                    "data_publicacao": "2026-02-10",
                    "tribunal": "Comarca de Aveiro",
                    "processo": "100/26.0T8AVR",  # mesmo processo, publicação mais recente
                    "tipo": "Insolvência",
                    "intervenientes": [{"papel": "Credor", "nome": "EMPRESA EXEMPLO, S.A.", "nif": NIF}],
                },
                {
                    "pub_id": "c",
                    "data_publicacao": "2025-12-01",
                    "tribunal": "Comarca do Porto",
                    "processo": "200/25.1T8PRT",
                    "especie": "PER",
                    "intervenientes": [{"papel": "Credor", "nome": "EMPRESA EXEMPLO, S.A.", "nif": NIF}],
                },
            ],
        },
        "citacoes": {"total": 0, "items": []},
        "devedores": {"devedor": False, "total": 0, "items": [], "entidades": [], "escaloes": []},
    }


def _bloco(blocos: list, titulo: str) -> Dict[str, Any]:
    return next(b for b in blocos if str(b.get("title") or "").startswith(titulo))


def test_indicadores_trazem_contratos_insolvencias_e_situacao_fiscal() -> None:
    blocos = _processos_blocks(_dados())
    indicadores = dict(_bloco(blocos, "Indicadores")["rows"])

    assert indicadores["Contratos públicos"].startswith("10 contratos")
    assert "1 234,50 €" in indicadores["Contratos públicos"]
    assert indicadores["Insolvências / PER"].startswith("3 publicações")
    assert "Credor: 2" in indicadores["Insolvências / PER"]
    assert indicadores["Processos judiciais (éditos)"] == "Nada encontrado"
    assert "Sem registo" in indicadores["Situação fiscal e contributiva"]


def test_resumo_da_entidade_usa_cae_e_banda_de_idade() -> None:
    resumo = dict(_bloco(_processos_blocks(_dados()), "Resumo da entidade")["rows"])
    assert resumo["NIF/NIPC"] == NIF
    assert resumo["Situação"] == "Ativa"
    assert resumo["CAE"].startswith("46380")
    assert resumo["Idade"] == _banda_idade(2026 - 2016)


def test_tabela_de_insolvencias_nao_repete_processos() -> None:
    tabela = _bloco(_processos_blocks(_dados()), "Insolvências / PER")
    processos = [linha[2] for linha in tabela["rows"]]
    assert len(processos) == 2, processos
    assert len(set(processos)) == 2
    # A publicação mais recente do processo 100/26 é a segunda (papel «Credor»).
    linha_100 = next(linha for linha in tabela["rows"] if linha[2].startswith("100/26"))
    assert linha_100[0] == "2026-02-10"
    assert linha_100[4] == "Credor"


def test_papeis_no_cire_por_entidade() -> None:
    assert _papeis_no_cire(_dados()) == {"Credor": 2}


def test_nomes_de_partes_aceitam_dict_lista_e_texto() -> None:
    assert _nomes({"parsed": [{"nome": "A, Lda"}]}) == ["A, Lda"]
    assert _nomes({"raw": ["B - S.A."]}) == ["B - S.A."]
    assert _nomes([{"parsed": [{"nome": "C"}]}, "D"]) == ["C", "D"]
    assert _nomes(None) == []


def test_pdf_do_relatorio_de_processos_sai_com_as_notas_legais() -> None:
    caminho = _generate_pdf_report(
        NIF,
        "EMPRESA EXEMPLO, S.A.",
        {},
        titulo="Relatório de processos e dados da empresa",
        notas=NOTAS_LEGAIS_PROCESSOS,
        prefixo="processos_teste",
        blocos=_processos_blocks(_dados()),
    )
    assert caminho, "o PDF não foi gerado"
    ficheiro = Path(caminho)
    try:
        assert ficheiro.exists()
        assert ficheiro.read_bytes()[:4] == b"%PDF"
        assert ficheiro.stat().st_size > 3000
    finally:
        ficheiro.unlink(missing_ok=True)
