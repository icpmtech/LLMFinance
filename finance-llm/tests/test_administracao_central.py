"""Administração Central (INE / SEC 2010).

O que se testa aqui é o que **não** depende da rede nem do Elasticsearch: a
leitura do PDF do INE, a normalização dos nomes (grafia anterior ao Acordo
Ortográfico, formas societárias, siglas), a ligação de cada entidade ao NIF com
que contrata e a pesquisa/ordenação/exportação do índice.

A ligação nome→NIF é a parte crítica do módulo: uma ligação errada atribuiria a
uma entidade os contratos de outra. Os casos negativos (nomes parecidos que
**não** são a mesma entidade) valem tanto como os positivos.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from api import administracao_central_service as ac


# --------------------------------------------------------------------- nomes


def test_normalizar_aproxima_grafias_do_acordo_ortografico():
    assert ac.normalizar("Direcção Regional de Qualificação") == "DIRECAO REGIONAL DE QUALIFICACAO"
    assert ac.normalizar("Inspecção-Geral das Actividades Culturais") == "INSPECAO GERAL DAS ATIVIDADES CULTURAIS"


def test_normalizar_nao_confunde_ordinais_com_numeros():
    # «2.º» e «2º» dão a mesma palavra — senão duas escolas com o mesmo nome em
    # versões diferentes do portal BASE deixavam de ser a mesma.
    assert ac.normalizar("Escola Básica dos 2.º e 3.º Ciclos do Caniço") == ac.normalizar(
        "Escola Básica dos 2º e 3º Ciclos do Caniço"
    )


def test_chave_nome_remove_formas_societarias_do_fim():
    assert ac.chave_nome("Infraestruturas de Portugal, S.A.") == "INFRAESTRUTURAS DE PORTUGAL"
    assert ac.chave_nome("ADSE - Instituto de Proteção e Assistência na Doença, I.P.") == (
        "ADSE INSTITUTO DE PROTECAO E ASSISTENCIA NA DOENCA"
    )
    # Só o **fim** do nome é limpo: «IP» a meio de um nome não desaparece.
    assert ac.chave_nome("IP - Instituto Público") == "IP INSTITUTO PUBLICO"


def test_sigla_e_nome_sem_sigla():
    assert ac.sigla_nome("IMT - Instituto da Mobilidade e dos Transportes, I.P.") == "IMT"
    assert ac.nome_sem_sigla("IMT - Instituto da Mobilidade e dos Transportes, I.P.") == (
        "Instituto da Mobilidade e dos Transportes, I.P."
    )
    # AICEP Portugal Global é o bloco que abre o nome (não uma sigla de 3 letras).
    assert ac.nome_sem_sigla(
        "AICEP Portugal Global - Agência para o Investimento e Comércio Externo de Portugal, E.P.E."
    ) == "Agência para o Investimento e Comércio Externo de Portugal, E.P.E."


def test_tokens_equivalentes_exige_palavras_longe_de_siglas():
    assert ac.tokens_equivalentes("ENERGETICO", "ENERGETICOS")  # plural
    assert ac.tokens_equivalentes("DIRECAO", "DIRECAO")
    # METRO nunca é METROPOLITANOS.
    assert not ac.tokens_equivalentes("METRO", "METROPOLITANOS")
    assert not ac.tokens_equivalentes("LEIRIA", "LEZIRIA")


# ------------------------------------------------------------------ PDF (INE)


def test_le_entidades_do_pdf_ine():
    if not ac.PDF_FONTE.is_file():
        pytest.skip("PDF do INE não está no repositório.")
    entidades = ac.ler_entidades_do_pdf()
    assert set(entidades) == {"S.13111", "S.13112", "S.13113"}
    assert len(entidades["S.13112"]) > 250
    assert "AdC - Autoridade da Concorrência" in entidades["S.13112"]
    # O cabeçalho repetido em todas as páginas não é confundido com entidades.
    assert "Serviços e Fundos Autónomos da Administração Central" not in entidades["S.13112"]
    assert not any(nome.startswith("S.13") for nomes in entidades.values() for nome in nomes)
    assert not any(" de 88" in nome for nomes in entidades.values() for nome in nomes)


# ------------------------------------------------------------------- ligações


def _candidatos(*nomes: str) -> dict:
    """Índice invertido a partir de nomes de adjudicantes (como o do Elasticsearch)."""
    return ac._indice_invertido(
        [
            {"nif": f"{indice:09d}", "nome": nome, "contratos": 10 * (indice + 1), "valor": 1000.0 * (indice + 1)}
            for indice, nome in enumerate(nomes)
        ]
    )


def test_liga_nome_exato_e_sem_sigla():
    indice = _candidatos("Autoridade da Concorrência", "Instituto da Mobilidade e dos Transportes")
    ligado, tipo, _ = ac.ligar_nome("AdC - Autoridade da Concorrência", indice)
    assert ligado and ligado["nome"] == "Autoridade da Concorrência" and tipo == "nome"
    ligado, tipo, _ = ac.ligar_nome("IMT - Instituto da Mobilidade e dos Transportes, I.P.", indice)
    assert ligado and tipo in ("nome", "exato")
    ligado, _, _ = ac.ligar_nome("Instituto da Mobilidade e dos Transportes", indice)
    assert ligado and tipo and ligado["nome"] == "Instituto da Mobilidade e dos Transportes"


def test_liga_nome_truncado_no_portal_base():
    # O portal BASE trunca nomes longos: «Agência para a Integração» é o mesmo
    # que «Agência para a Integração, Migrações e Asilo».
    indice = _candidatos("Agência para a Integração")
    ligado, tipo, _ = ac.ligar_nome("Agência para a Integração, Migrações e Asilo, I.P.", indice)
    assert ligado and tipo == "prefixo"


def test_nao_liga_nomes_que_apenas_contem_o_outro():
    # Nome mais curto **diferente**: uma secretaria regional não é a outra.
    indice = _candidatos("Secretaria Regional da Juventude")
    ligado, tipo, _ = ac.ligar_nome("Secretaria Regional de Inclusão, Trabalho e Juventude", indice)
    assert ligado is None and tipo == "nenhuma"

    indice = _candidatos("Direção Regional de Cultura do Centro")
    ligado, _, _ = ac.ligar_nome("Direção Regional da Cultura", indice)
    assert ligado is None

    indice = _candidatos("Laboratório Nacional de Engenharia Civil")
    ligado, _, _ = ac.ligar_nome("Laboratório Regional de Engenharia Civil", indice)
    assert ligado is None

    indice = _candidatos("Unidade Local de Saúde da Região de Leiria")
    ligado, _, _ = ac.ligar_nome("Unidade Local de Saúde da Lezíria, E.P.E.", indice)
    assert ligado is None


def test_liga_pelo_nome_completo_quando_a_sigla_so_aparece_no_contrato():
    indice = _candidatos("ISEG - Instituto Superior de Economia e Gestão")
    ligado, tipo, _ = ac.ligar_nome("UL - Instituto Superior de Economia e Gestão", indice)
    assert ligado and tipo in ("nome", "exato", "sigla")


def test_liga_nome_sem_sigla_quando_e_o_contrato_que_a_tem():
    indice = _candidatos("ANI - Agência Nacional de Inovação")
    ligado, tipo, _ = ac.ligar_nome("ANI - Agência Nacional de Inovação, S.A.", indice)
    assert ligado and tipo in ("exato", "prefixo", "sigla")


def test_ligacoes_manuais_tem_precedencia(tmp_path, monkeypatch):
    manual = tmp_path / "ligacoes-manuais.json"
    manual.write_text(json.dumps({"Fundo Inventado": "123456789"}), encoding="utf-8")
    monkeypatch.setattr(ac, "LIGACOES_MANUAIS", manual)
    assert ac._ligacoes_manuais() == {"Fundo Inventado": "123456789"}


def test_ids_estaveis_por_entidade():
    proprio, identificador = ac._ids_estaveis("AdC - Autoridade da Concorrência", "S.13112")
    assert identificador == "s-13112-adc-autoridade-da-concorrencia"
    assert proprio == "adc-autoridade-da-concorrencia"


# ------------------------------------------------------------------- índice


_INDICE = {
    "fonte": ac.FONTE,
    "gerado_em": "2026-01-01T00:00:00+00:00",
    "subsetor_omissao": "S.13112",
    "subsetores": [
        {"id": "S.13112", "nome": "Serviços e Fundos Autónomos da Administração Central", "total": 2, "ligadas": 1}
    ],
    "total": 2,
    "ligadas": 1,
    "entidades": [
        {
            "id": "s-13112-alfa",
            "nome": "Alfa, I.P.",
            "slug": "alfa",
            "subsetor": "S.13112",
            "subsetor_nome": "Serviços e Fundos Autónomos da Administração Central",
            "nif": "123456789",
            "nome_contratos": "Alfa",
            "ligacao": "prefixo",
            "ligacao_confianca": 0.95,
            "contratos": 100,
            "valor": 5000.0,
            "ano_min": 2015,
            "ano_max": 2026,
        },
        {
            "id": "s-13112-beta",
            "nome": "Beta, Fundo",
            "slug": "beta",
            "subsetor": "S.13112",
            "subsetor_nome": "Serviços e Fundos Autónomos da Administração Central",
            "nif": None,
            "nome_contratos": None,
            "ligacao": "nenhuma",
            "ligacao_confianca": 0.0,
            "contratos": 0,
            "valor": 0.0,
            "ano_min": None,
            "ano_max": None,
        },
    ],
}


@pytest.fixture()
def indice_temporario(tmp_path, monkeypatch) -> Path:
    caminho = tmp_path / "administracao-central.json"
    caminho.write_text(json.dumps(_INDICE, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(ac, "INDICE", caminho)
    ac.cache_limpar()
    yield caminho
    ac.cache_limpar()


def test_pesquisa_ordena_e_filtra(indice_temporario):
    assert ac.meta()["total"] == 2
    assert ac.meta()["indice_em_falta"] is False

    resultado = ac.pesquisar(ordenar="valor")
    assert [item["nome"] for item in resultado["items"]] == ["Alfa, I.P.", "Beta, Fundo"]

    assert ac.pesquisar(q="alfa")["total"] == 1
    assert ac.pesquisar(q="123456789")["total"] == 1
    assert ac.pesquisar(q="nada disto")["total"] == 0
    assert ac.pesquisar(ligacao="com_nif")["total"] == 1
    assert ac.pesquisar(ligacao="sem_nif")["total"] == 1
    assert ac.pesquisar(ligacao="com_contratos")["total"] == 1
    assert ac.pesquisar(subsetor="S.13113")["total"] == 0


def test_ficha_de_entidade_inexistente(indice_temporario):
    assert ac.entidade("nao-existe") is None
    ficha = ac.ficha_entidade("nao-existe", es=None)
    assert ficha["error"] == "Entidade não encontrada"


def test_entidade_sem_nif_nao_vai_ao_elasticsearch(indice_temporario):
    ficha = ac.ficha_entidade("s-13112-beta", es=None)
    assert ficha["entidade"]["nif"] is None
    assert "aviso" in ficha and "contratos" not in ficha


def test_exporta_csv_do_indice(indice_temporario):
    linhas = ac.exportar_csv(subsetor="S.13112").strip().splitlines()
    assert linhas[0].startswith("id;nome;subsetor")
    assert len(linhas) == 3
    assert "123456789" in linhas[1]


def test_assinatura_do_indice_forca_recarga(indice_temporario):
    assert len(ac.entidades()) == 2
    dados = json.loads(indice_temporario.read_text(encoding="utf-8"))
    dados["entidades"].append({**dados["entidades"][0], "id": "s-13112-gama", "nome": "Gama"})
    indice_temporario.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
    assert len(ac.entidades()) == 3


# --------------------------------------------------------------- agregações


def test_valor_do_balde_nas_duas_formas():
    assert ac._valor_do_balde({"valor": {"value": 10.5}}) == 10.5
    assert ac._valor_do_balde({"valor": {"v": {"value": 20.25}}}) == 20.25
    assert ac._valor_do_balde({}) == 0.0


def test_linhas_de_baldes_usa_a_chave_quando_nao_ha_nome():
    linhas = ac._linhas_de_baldes(
        [
            {"key": "Ajuste Direto Regime Geral", "doc_count": 5, "valor": {"value": 100.0}},
            {"key": "Concurso público", "doc_count": 2, "valor": {"v": {"value": 50.0}}},
        ]
    )
    assert linhas == [
        {"key": "Ajuste Direto Regime Geral", "nome": "Ajuste Direto Regime Geral", "count": 5, "valor": 100.0},
        {"key": "Concurso público", "nome": "Concurso público", "count": 2, "valor": 50.0},
    ]


def test_filtro_do_setor_usa_os_nifs_como_terms_nested():
    assert ac._filtro_setor(["123456789"]) == {
        "nested": {
            "path": "adjudicantes.parsed",
            "query": {"terms": {"adjudicantes.parsed.nif": ["123456789"]}},
        }
    }
    assert ac._filtro_setor(["1"], papel="adjudicatarios")["nested"]["path"] == "adjudicatarios.parsed"
