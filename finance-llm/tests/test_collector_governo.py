"""Testes do coletor do Governo (nomeações e composição).

As páginas de ``portugal.gov.pt`` escondem a lista de áreas e os cartões da
composição atrás de JavaScript; estes testes fixam o contrato dos parsers que
correm sobre o HTML já renderizado pelo motor de recolha.
"""
from __future__ import annotations

from collectors import governo

AREAS_HTML = """
<ul>
  <li>
    <div>
      <h4 class="navigation-title"><span>Ministro de Estado e das Finanças</span></h4>
      <p class="navigation-subtitle">Nomeações dos Gabinetes da área das Finanças</p>
    </div>
    <a class="navigation-link" href="/pt/gc24/governo/nomeacoes/financas">Ver mais</a>
  </li>
  <li>
    <div>
      <h4 class="navigation-title"><span>Ministra da Cultura</span></h4>
      <p class="navigation-subtitle">Nomeações dos Gabinetes da área da Cultura</p>
    </div>
    <a class="navigation-link" href="/pt/gc24/governo/nomeacoes/cultura">Ver mais</a>
  </li>
  <li>
    <a class="navigation-link" href="/pt/gc24/governo/nomeacoes/legislacao-aplicavel">Legislação</a>
  </li>
</ul>
"""

NOMEACOES_HTML = """
<h4>Ministro de Estado e das Finanças</h4>
<table>
  <tr>
    <th>Função</th><th>Nome</th><th>Rendimento bruto</th>
    <th>Rendimento líquido</th><th>Data de nomeação</th><th>Publicação em DRE</th>
  </tr>
  <tr>
    <td>Chefe do Gabinete</td>
    <td>Nelson Miguel Rodrigues Coelho (1)</td>
    <td>5 144,36 €</td>
    <td>3 060,00 €</td>
    <td>01/02/2025</td>
    <td><a href="https://diariodarepublica.pt/dr/detalhe/despacho/958-2025-904227412">Despacho</a></td>
  </tr>
  <tr>
    <td>Adjunta</td>
    <td>Joana Martins Rodrigues</td>
    <td>3 981,49 €</td>
    <td>2 498,05 €</td>
    <td>02/04/2024</td>
    <td><a href="https://diariodarepublica.pt/dr/detalhe/despacho/5096-2024-864228261">Despacho</a></td>
  </tr>
</table>
"""

COMPOSICAO_HTML = """
<div class="search-composite-group">
  <h3 class="group-heading"><span class="template-name">Ministros</span></h3>
  <div class="item">
    <a href="/pt/gc24/area-de-governo/financas/ministro/"><img alt="Joaquim Miranda Sarmento"></a>
    <div class="govinfo">
      <div class="govtype">Joaquim Miranda Sarmento</div>
      <h4 class="title">Ministro de Estado e das Finanças</h4>
      <div class="period">
        <time datetime="2024-04-02T00:00:00.000Z">2024-04-02</time>
        <time datetime="2025-06-05T00:00:00.000Z">2025-06-05</time>
      </div>
      <div class="secretaries-count">
        <a href="/pt/gc24/area-de-governo/financas/secretarios-de-estado/">Secretários de Estado (4)</a>
      </div>
    </div>
  </div>
</div>
<div class="search-composite-group">
  <h3 class="group-heading"><span class="template-name">Secretários de Estado</span></h3>
  <div class="item">
    <a href="/pt/gc24/area-de-governo/cultura/secretarios-de-estado/cultura/"><img alt="Alberto Santos"></a>
    <div class="govinfo">
      <div class="govtype">Alberto Santos</div>
      <h4 class="title">Secretário de Estado da Cultura</h4>
      <div class="period">
        <time datetime="2025-02-13T00:00:00.000Z">2025-02-13</time>
        <time datetime="2025-06-05T00:00:00.000Z">2025-06-05</time>
      </div>
    </div>
  </div>
</div>
"""


def test_parse_area_links_ignora_legislacao_e_compila_metadados():
    areas = governo.parse_area_links(AREAS_HTML)

    assert [a["area_slug"] for a in areas] == ["financas", "cultura"]
    assert areas[0]["area"] == "Ministro de Estado e das Finanças"
    assert areas[0]["descricao"] == "Nomeações dos Gabinetes da área das Finanças"
    assert areas[0]["url"] == "https://portugal.gov.pt/pt/gc24/governo/nomeacoes/financas"


def test_parse_nomeacoes_converte_valores_datas_e_nota_do_servico_de_origem():
    rows = governo.parse_nomeacoes(
        NOMEACOES_HTML,
        area="Finanças",
        area_slug="financas",
        source_url="https://portugal.gov.pt/pt/gc24/governo/nomeacoes/financas",
    )

    assert len(rows) == 2
    first = rows[0]
    assert first["membro"] == "Ministro de Estado e das Finanças"
    assert first["nome"] == "Nelson Miguel Rodrigues Coelho"
    assert first["encargos_servico_origem"] is True
    assert first["rendimento_bruto_eur"] == 5144.36
    assert first["rendimento_liquido_eur"] == 3060.0
    assert first["data_nomeacao"] == "2025-02-01"
    assert first["dre_url"].endswith("/despacho/958-2025-904227412")

    second = rows[1]
    assert second["nome"] == "Joana Martins Rodrigues"
    assert second["encargos_servico_origem"] is False


def test_parse_nomeacoes_ignora_linhas_repetidas_na_pagina():
    duplicated = NOMEACOES_HTML.replace(
        "</table>",
        """
  <tr>
    <td>Chefe do Gabinete</td>
    <td>Nelson Miguel Rodrigues Coelho (1)</td>
    <td>5 144,36 €</td>
    <td>3 060,00 €</td>
    <td>01/02/2025</td>
    <td><a href="https://diariodarepublica.pt/dr/detalhe/despacho/958-2025-904227412">Despacho</a></td>
  </tr>
</table>
""",
    )

    rows = governo.parse_nomeacoes(
        duplicated,
        area="Finanças",
        area_slug="financas",
        source_url="https://portugal.gov.pt/pt/gc24/governo/nomeacoes/financas",
    )

    assert len(rows) == 2


def test_parse_composicao_le_grupos_periodos_e_secretarios():
    members = governo.parse_composicao(COMPOSICAO_HTML, source_url="https://portugal.gov.pt/")

    assert len(members) == 2
    ministro = members[0]
    assert ministro["grupo"] == "Ministros"
    assert ministro["nome"] == "Joaquim Miranda Sarmento"
    assert ministro["cargo"] == "Ministro de Estado e das Finanças"
    assert ministro["area_slug"] == "financas"
    assert ministro["periodo_inicio"] == "2024-04-02"
    assert ministro["periodo_fim"] == "2025-06-05"
    assert ministro["secretarios_count"] == 4
    assert ministro["secretarios_url"].endswith("/financas/secretarios-de-estado/")

    secretario = members[1]
    assert secretario["grupo"] == "Secretários de Estado"
    assert secretario["area_slug"] == "cultura"
    assert secretario["secretarios_count"] is None


def test_build_ministerios_consolida_titular_secretarios_e_nomeacoes():
    areas = [
        {"area": "Primeiro-Ministro", "area_slug": "primeiro-ministro", "descricao": "", "url": "pm"},
        {"area": "Ministro de Estado e das Finanças", "area_slug": "financas", "descricao": "", "url": "fin"},
    ]
    members = [
        {"nome": "Luís Montenegro", "cargo": "Primeiro-Ministro", "grupo": "Primeiro-Ministro", "area_slug": ""},
        {"nome": "Joaquim Miranda Sarmento", "cargo": "Ministro de Estado e das Finanças", "grupo": "Ministros", "area_slug": "financas"},
        {"nome": "Secretário A", "cargo": "Secretário de Estado", "grupo": "Secretários de Estado", "area_slug": "financas"},
        {"nome": "Secretária B", "cargo": "Secretária de Estado", "grupo": "Secretários de Estado", "area_slug": "financas"},
    ]
    nomeacoes = [
        {"area_slug": "financas"},
        {"area_slug": "financas"},
        {"area_slug": "primeiro-ministro"},
    ]

    ministerios = governo.build_ministerios(areas, members, nomeacoes)

    assert len(ministerios) == 2
    pm, financas = ministerios
    assert pm["tipo"] == "Primeiro-Ministro"
    assert pm["titular"] == "Luís Montenegro"
    assert pm["nomeacoes_count"] == 1
    assert financas["tipo"] == "Ministério"
    assert financas["titular"] == "Joaquim Miranda Sarmento"
    assert financas["secretarios_count"] == 2
    assert financas["nomeacoes_count"] == 2
    assert len(financas["membros"]) == 3


def test_parse_dre_detail_normaliza_texto_e_datas():
    detail = {
        "Id": "904227412",
        "Titulo": "Despacho n.º 958/2025 ",
        "Publicacao": "Diário da República n.º 15/2025, Série II de 2025-01-22",
        "Numero": "958/2025",
        "Sumario": "Exoneração e designação do chefe do Gabinete.",
        "Texto": "<p>1 - Ao abrigo do disposto no n.º 1 do artigo 11.º.</p>",
        "DataPublicacao": "2025-01-22",
        "Emissor": "Finanças - Gabinete do Ministro de Estado e das Finanças",
        "Serie": "II",
        "Pagina": "47 - 48",
        "URL_PDF": "https://files.diariodarepublica.pt/2s/2025/01/015000000/0004700048.pdf",
        "DiarioRepublica": {"URL_PDF": "https://files.diariodarepublica.pt/gratuitos/2s/2025/01/2S015A0000S00.pdf"},
        "TipoDiploma": "Despacho",
    }

    fields = governo.parse_dre_detail(detail)

    assert fields["dre_id"] == "904227412"
    assert fields["dre_titulo"] == "Despacho n.º 958/2025"
    assert fields["dre_sumario"] == "Exoneração e designação do chefe do Gabinete."
    assert fields["dre_texto"].startswith("1 - Ao abrigo")
    assert fields["dre_data_publicacao"] == "2025-01-22"
    assert fields["dre_pdf_url"].endswith("0004700048.pdf")
    assert fields["dre_diario_pdf_url"].endswith("2S015A0000S00.pdf")


def _profile_html(context: dict) -> str:
    import json as _json

    payload = {
        "props": {
            "pageProps": {
                "layoutData": {
                    "sitecore": {
                        "route": {
                            "placeholders": {
                                "headless-main": [
                                    {
                                        "componentName": "OfficialProfile",
                                        "fields": {"data": {"contextItem": context}},
                                    }
                                ]
                            }
                        }
                    }
                }
            }
        }
    }
    return f'<script id="__NEXT_DATA__" type="application/json">{_json.dumps(payload, ensure_ascii=False)}</script>'


def test_parse_member_profile_ministro_com_historico():
    context = {
        "officialsHistory": {
            "targetItems": [
                {
                    "official": {"targetItem": {"fullName": {"jsonValue": {"value": "Dalila Rodrigues"}}}},
                    "governmentRole": {"jsonValue": {"value": "Ministra"}},
                    "bio": {"jsonValue": {"value": "<p>Historiadora de arte.</p>"}},
                    "bioPhoto": {"jsonValue": {"value": {"src": "https://example.pt/dalila.jpg"}}},
                    "startDate": {"jsonValue": {"value": "2024-04-02T00:00:00Z"}},
                    "endDate": {"jsonValue": {"value": "2025-06-05T00:00:00Z"}},
                }
            ]
        },
        "parent": {"governmentTitle": {"jsonValue": {"value": "Cultura"}}},
    }

    fields = governo.parse_member_profile(_profile_html(context))

    assert fields["nome_oficial"] == "Dalila Rodrigues"
    assert fields["cargo_oficial"] == "Ministra"
    assert fields["area_nome"] == "Cultura"
    assert fields["biografia"] == "Historiadora de arte."
    assert fields["foto_biografia"] == "https://example.pt/dalila.jpg"
    assert fields["perfil_inicio"] == "2024-04-02"
    assert fields["perfil_fim"] == "2025-06-05"


def test_parse_member_profile_primeiro_ministro_sem_historico():
    context = {
        "official": {"targetItem": {"fullName": {"jsonValue": {"value": "Luís Montenegro"}}}},
        "governmentRole": {"jsonValue": {"value": "Primeiro-Ministro"}},
        "bio": {"jsonValue": {"value": "<p>Advogado.</p>"}},
        "governmentTitle": {"jsonValue": {"value": "Primeiro-Ministro"}},
        "startDate": {"jsonValue": {"value": "2024-04-02T00:00:00Z"}},
        "endDate": {"jsonValue": {"value": "2025-06-05T00:00:00Z"}},
    }

    fields = governo.parse_member_profile(_profile_html(context))

    assert fields["nome_oficial"] == "Luís Montenegro"
    assert fields["cargo_oficial"] == "Primeiro-Ministro"
    assert fields["area_nome"] == "Primeiro-Ministro"
    assert fields["biografia"] == "Advogado."


def test_documentos_elastic_tem_ids_estaveis_e_campos_de_topologia():
    record = {
        "area": "Finanças",
        "area_slug": "financas",
        "membro": "Ministro de Estado e das Finanças",
        "funcao": "Chefe do Gabinete",
        "nome": "Nelson Miguel Rodrigues Coelho",
        "data_nomeacao": "2025-02-01",
        "dre_url": "https://diariodarepublica.pt/dr/detalhe/despacho/958-2025-904227412",
    }
    first = governo._nomeacao_doc(record, "run-1", "2026-10-19T12:00:00Z")
    second = governo._nomeacao_doc(dict(record), "run-2", "2026-10-20T12:00:00Z")

    assert first["item_id"] == second["item_id"]
    assert first["item_id"].startswith("governo-nomeacoes:")
    assert first["source_id"] == "governo-nomeacoes"
    assert first["run_id"] == "run-1"
