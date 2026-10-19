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
