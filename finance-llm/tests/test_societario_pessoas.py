"""Extração de pessoas/cargos das publicações de atos societários.

Regressão de 2026-09-28: a entidade 503106542 (JAJA – Gestão e Investimentos)
tinha 25 publicações indexadas e **zero** pessoas extraídas, porque o extrator
só reconhecia uma lista fixa de órgãos sociais («GERÊNCIA», «ADMINISTRAÇÃO»,
«FISCALIZAÇÃO»…) e o portal publica etiquetas como «ADMINISTRADOR ÚNICO»,
«FISCAL ÚNICO» ou «SUPLENTE(S) DO FISCAL ÚNICO».
"""
from __future__ import annotations

from collectors.people_extractor import extract_people_from_publicacao

# Publicação real (pub_id 3c5aad16dc6156f9720c891523235ffaf7e34733, MJ) condensada.
PUBLICACAO_JAJA = {
    "nif": "503106542",
    "firma": "JAJA - GESTÃO E INVESTIMENTOS S.A.",
    "data_publicacao": "2025-03-20",
    "acto": "Designação de membro(s) de órgão(s) social(ais)",
    "pub_id": "3c5aad16dc6156f9720c891523235ffaf7e34733",
    "texto": (
        "Publica-se que em relação à entidade: Nº de Matrícula/NIPC: 503106542 Firma: JAJA - GESTÃO E "
        "INVESTIMENTOS S.A. Natureza Jurídica: SOCIEDADE ANÓNIMA Sede: ZONA INDUSTRIAL ALTO DA CRUZ "
        "Distrito: Porto Concelho: Santo Tirso 4780 - 739 SANTO TIRSO pela Apresentação AP. 2/20250314 , "
        "referente à inscrição 6, foi efectuado o seguinte acto de registo: Insc. 6 - AP. 2/20250314 "
        "11:04:45 UTC - DESIGNAÇÃO DE MEMBRO(S) DE ÓRGÃO(S) SOCIAL(AIS) DESIGNADO(S): "
        "ADMINISTRADOR ÚNICO: Nome/Firma: DIOGO LEMOS PINTO CARDOSO NIF/NIPC: 179018531 "
        "Nacionalidade: Portuguesa Cargo: Administrador Único Residência/Sede: Rua D. Paio Mendes, nº 73, "
        "Maximinos, Sé e Cividade 4700 - 424 Porto "
        "FISCAL ÚNICO: Nome/Firma: RSM & ASSOCIADOS - SROC, LDA NIF/NIPC: 501612181 "
        "Cargo: Fiscal Único Residência/Sede: Av. do Brasil, 15 - 1º 1749 - 112 Lisboa "
        "SUPLENTE(S) DO FISCAL ÚNICO: Nome/Firma: CARLOS DE JESUS PINTO DE CARVALHO NIF/NIPC: 108671208 "
        "Nacionalidade: Portuguesa Cargo: Suplente do Fiscal Único Residência/Sede: Rua José Falcão, nº 190 "
        "- 1º 4050 - 315 Porto Prazo de duração do(s) mandato(s): Quadriénio 2025/2028 "
        "Data da deliberação: 16 de janeiro de 2025 Os documentos que serviram de base ao presente registo "
        "estão depositados em suporte electrónico."
    ),
}


def test_designacao_administrador_unico_e_fiscais():
    """Órgãos nomeados fora da lista fixa («Administrador Único», «Fiscal Único»)."""
    records = extract_people_from_publicacao(PUBLICACAO_JAJA)

    cargos = {(r["nif"], r["cargo"], r["role_org"]) for r in records}
    assert cargos == {
        ("179018531", "Administrador Único", "Administrador Único"),
        ("501612181", "Fiscal Único", "Fiscal Único"),
        ("108671208", "Suplente do Fiscal Único", "Suplente(S) Do Fiscal Único"),
    }
    # Todos os registos ficam ligados à empresa da publicação.
    assert {r["company_nif"] for r in records} == {"503106542"}
    assert {r["publication_id"] for r in records} == {PUBLICACAO_JAJA["pub_id"]}


def test_is_company_decidido_pelo_nif():
    """O NIF manda: 1/2/3 = pessoa singular, 5/6/7/9 = pessoa coletiva."""
    por_nif = {r["nif"]: r for r in extract_people_from_publicacao(PUBLICACAO_JAJA)}
    assert por_nif["179018531"]["is_company"] is False
    assert por_nif["108671208"]["is_company"] is False
    assert por_nif["501612181"]["is_company"] is True  # SROC


def test_etiqueta_com_morada_em_maiusculas_nao_polui_o_orgao():
    """Moradas em maiúsculas não devem entrar na etiqueta do órgão."""
    pub = {
        "nif": "608345678",
        "firma": "EMPRESA EXEMPLO, S.A.",
        "data_publicacao": "2024-01-10",
        "acto": "Designação de membro(s) de órgão(s) social(ais)",
        "pub_id": "x1",
        "texto": (
            "DESIGNADO(S): CONSELHO DE ADMINISTRAÇÃO: Nome/Firma: ANA MARIA COSTA NIF/NIPC: 123456789 "
            "Cargo: Vogal Residência/Sede: AV. DA LIBERDADE 1, 6.º 1050 - 094 LISBOA "
            "FISCAL ÚNICO: Nome/Firma: PEDRO SANTOS SILVA NIF/NIPC: 223344556 Cargo: Fiscal Único "
            "Data da deliberação: 5 de janeiro de 2024"
        ),
    }
    orgs = {r["nif"]: r["role_org"] for r in extract_people_from_publicacao(pub)}
    assert orgs == {"123456789": "Conselho De Administração", "223344556": "Fiscal Único"}


def test_gerencia_no_formato_antigo_continua_a_funcionar():
    """O caminho antigo («GERÊNCIA: … Cargo: …») não pode regredir."""
    pub = {
        "nif": "500000000",
        "firma": "SOCIEDADE EXEMPLO, LDA",
        "data_publicacao": "2020-05-05",
        "acto": "Designação de membro(s) de órgão(s) social(ais)",
        "pub_id": "y1",
        "texto": (
            "GERÊNCIA: Nome/Firma: JOÃO MANUEL SILVA NIF/NIPC: 111222333 Cargo: Gerente "
            "Residência/Sede: Rua A, 1 4000-000 Porto Data da deliberação: 1 de maio de 2020"
        ),
    }
    records = extract_people_from_publicacao(pub)
    assert [(r["nif"], r["cargo"], r["role_org"]) for r in records] == [
        ("111222333", "Gerente", "Gerência")
    ]
