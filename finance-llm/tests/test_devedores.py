"""Listas públicas de devedores (Finanças e Segurança Social).

O que se testa aqui é o que não depende da rede nem do Elasticsearch: a leitura
dos PDF oficiais (cabeçalhos repetidos por página, pares NIF/NIPC + nome, nomes
em duas linhas, NIF repetidos na mesma lista), a gravação do JSON **por
ficheiro** com a data da recolha e o catálogo das fontes.
"""
from __future__ import annotations

import json

import pymupdf
import pytest

from api import devedores_service as devedores

CABECALHO = [
    "Contribuintes Colectivos",
    "Devedores de 5.000.001 a 10.000.000 €",
    "Informação actualizada em 2026-09-28",
    "NIPC",
    "DESIGNAÇÃO",
]


def _pdf(paginas: list[list[str]]) -> bytes:
    """Gera um PDF de teste com as linhas indicadas, uma página por lista."""
    documento = pymupdf.open()
    for linhas in paginas:
        pagina = documento.new_page()
        y = 72.0
        for linha in linhas:
            pagina.insert_text((72, y), linha, fontsize=10)
            y += 14.0
    conteudo = documento.tobytes()
    documento.close()
    return conteudo


SPEC = {
    "ficheiro": "listaFC6.pdf",
    "entidade": "financas",
    "tipo": "coletivos",
    "escalao": "mais de 5.000.000 €",
    "valor_min": 5000000.01,
    "valor_max": None,
}


def test_parse_pdf_le_registos_ignora_cabecalhos_e_junta_nomes_partidos():
    """Cada página repete o cabeçalho; um nome comprido pode ocupar duas linhas."""
    conteudo = _pdf(
        [
            [*CABECALHO, "510960316", "ADIVINHABILITY UNIPESSOAL LDA", "507288718", "ANTONIO C MOREIRA", "IMPORT", "EXPORT, UNIPESSOAL LDA", "Página 1"],
            [*CABECALHO, "501637184", "ARTIPRATAS SOC COMERCIAL", "ARTIGOS PRATA LDA", "Página 2"],
        ]
    )

    analise = devedores.parse_pdf(conteudo, SPEC)

    assert analise["paginas"] == 2
    assert analise["lista_atualizada_em"] == "2026-09-28"
    assert "Devedores de 5.000.001 a 10.000.000" in (analise["escalao_pdf"] or "")
    nomes = [(item["nif"], item["nome"], item["pagina"]) for item in analise["registos"]]
    assert nomes == [
        ("510960316", "ADIVINHABILITY UNIPESSOAL LDA", 1),
        ("507288718", "ANTONIO C MOREIRA IMPORT EXPORT, UNIPESSOAL LDA", 1),
        ("501637184", "ARTIPRATAS SOC COMERCIAL ARTIGOS PRATA LDA", 2),
    ]


def test_parse_pdf_nao_repete_nif_da_mesma_lista():
    """O mesmo NIPC repetido na lista conta uma vez."""
    conteudo = _pdf([[*CABECALHO, "510960316", "ADIVINHABILITY", "510960316", "ADIVINHABILITY LDA"]])

    analise = devedores.parse_pdf(conteudo, SPEC)

    assert [item["nif"] for item in analise["registos"]] == ["510960316"]


def test_export_grava_json_pdf_e_manifesto(tmp_path, monkeypatch):
    """Um JSON por ficheiro (com a data da recolha) + registo no manifesto."""
    monkeypatch.setenv(devedores.EXPORT_DIR_ENV, str(tmp_path))
    registos = [
        {"nif": "510960316", "nome": "ADIVINHABILITY UNIPESSOAL LDA", "pagina": 1},
        {"nif": "501637184", "nome": "ARTIPRATAS SOC COMERCIAL", "pagina": 1},
    ]
    pdf = {
        "path": str(tmp_path / "pdf" / "listaFC6-2026-09-29.pdf"),
        "bytes": 5254,
        "sha256": "abc",
        "paginas": 1,
        "last_modified": "Mon, 28 Sep 2026 18:00:32 GMT",
    }

    entrada = devedores.write_export(
        SPEC,
        registos,
        collected_at="2026-09-29T11:00:00Z",
        pdf=pdf,
        escalao_pdf="Devedores de mais de 5.000.000 €",
        lista_atualizada_em="2026-09-28",
    )

    assert entrada["base"] == "listaFC6-2026-09-29"
    assert entrada["registos"] == 2
    assert entrada["collected_at"] == "2026-09-29T11:00:00Z"
    assert entrada["lista_atualizada_em"] == "2026-09-28"
    assert entrada["pdf_sha256"] == "abc"

    caminho = tmp_path / "json" / "listaFC6-2026-09-29.json"
    assert caminho.exists()
    payload = json.loads(caminho.read_text(encoding="utf-8"))
    assert payload["ficheiro"] == "listaFC6.pdf"
    assert payload["escalao"] == "mais de 5.000.000 €"
    assert payload["lista_atualizada_em"] == "2026-09-28"
    assert payload["collected_at"] == "2026-09-29T11:00:00Z"
    assert [item["nif"] for item in payload["registos"]] == ["510960316", "501637184"]

    manifesto = devedores.list_recolhas()
    assert manifesto["total"] == 1
    assert manifesto["registos"] == 2
    assert manifesto["items"][0]["ficheiro"] == "listaFC6.pdf"

    # `read_export` devolve o mesmo que ficou gravado.
    assert devedores.read_export("listaFC6-2026-09-29")["total"] == 2


def test_fontes_tem_os_12_ficheiros_das_financas(tmp_path, monkeypatch):
    """6 escalões de singulares + 6 de coletivos, com valores e URLs oficiais."""
    monkeypatch.setenv(devedores.EXPORT_DIR_ENV, str(tmp_path))

    catalogo = devedores.fontes()

    ficheiros = catalogo["financas"]["ficheiros"]
    assert len(ficheiros) == 12
    assert [item["ficheiro"] for item in ficheiros[:2]] == ["listaFS1.pdf", "listaFS2.pdf"]
    assert {item["tipo"] for item in ficheiros} == {"singulares", "coletivos"}
    assert catalogo["financas"]["total"] == 12
    assert catalogo["financas"]["recolhidos"] == 0
    primeiro = ficheiros[0]
    assert primeiro["url"].endswith("/listaFS1.pdf")
    assert primeiro["valor_min"] == 7500.0 and primeiro["valor_max"] == 25000.0
    assert ficheiros[-1]["valor_max"] is None  # «mais de 5.000.000 €»
    assert catalogo["seguranca_social"]["escaloes"]


def test_pesquisa_sem_elasticsearch_nao_rebenta(monkeypatch):
    """Sem Elasticsearch, a pesquisa e a ficha respondem com erro explícito."""
    from api import elasticsearch_client as esc

    monkeypatch.setattr(esc, "get_es_client", lambda *args, **kwargs: None)

    pesquisa = devedores.search(q="SONAE")
    assert pesquisa["total"] == 0
    assert "indisponível" in pesquisa["error"]

    ficha = devedores.por_nif("510960316")
    assert ficha["devedor"] is False
    assert "indisponível" in ficha["error"]


def test_por_nif_sem_nif_devolve_vazio():
    assert devedores.por_nif("")["total"] == 0


@pytest.mark.parametrize("nome", ["listaFS1.pdf", "listaFC1.pdf"])
def test_specs_existem_no_catalogo(nome):
    assert any(item["ficheiro"] == nome for item in devedores.FICHEIROS_FINANCAS)
