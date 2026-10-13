"""Portal da Transparência da ERC — leitura, normalização e fichas.

Testa o que **não** depende da rede: a listagem de entidades proprietárias de
OCS, os separadores «Dados Gerais», «Órgãos Sociais» e «Órgão de Comunicação
Social» de uma entidade, os separadores de uma pessoa regulada e o sentido das
ligações de capital (quem detém quem) a partir das respostas da API. As páginas
reais são HTML do Umbraco; aqui usam-se fragmentos com a mesma estrutura, para os
testes serem rápidos e determinísticos.

O único teste que exercita a recolha usa um cliente HTTP falso — nada sai para a
internet.
"""
from __future__ import annotations

import json

import pytest

from api import erc_risco
from api import erc_service as erc
from collectors import erc_transparencia as coletor

# ---------------------------------------------------------------------------
# Fragmentos sintéticos
# ---------------------------------------------------------------------------

LISTAGEM = """
<table id="tabelaEntidades">
  <thead><tr><th>Designação</th><th>Tipo de Sociedade</th><th>Actividade Principal</th><th>Distrito</th></tr></thead>
  <tbody>
    <tr class="border_bottom">
      <td><a href="/entidades-ocs/7graus-lda/?IdEntidade=A28F2A03-1124-EB11-8111-00505684056E&geral=true">7Graus, Lda.</a></td>
      <td>Sociedade por quotas</td><td>Comunica&#231;&#227;o Social</td><td>Regi&#227;o Aut&#243;noma da Madeira</td>
    </tr>
    <tr class="border_bottom">
      <td><a href="/entidades-ocs/radio-on-fm-lda/?IdEntidade=07E29E36-580D-E611-80C8-00505684056E&geral=true">93.8 ON FM, Lda.</a></td>
      <td>Cooperativa</td><td>Outra</td><td>Lisboa</td>
    </tr>
  </tbody>
</table>
"""

ENTIDADE_GERAL = """
<div class="dadosGerais">7Graus, Lda. </div>
<ul>
  <li><a href='?IdEntidade=a28f2a03-1124-eb11-8111-00505684056e&amp;geral=geral'>Dados Gerais</a></li>
  <li><a href='?IdEntidade=a28f2a03-1124-eb11-8111-00505684056e&amp;nrRegisto=127440&amp;geral=ocs'>Órgão de Comunicação Social</a></li>
  <li><a href='?IdEntidade=a28f2a03-1124-eb11-8111-00505684056e&amp;nrRegisto=127440&amp;geral=orgs'>Órgãos Sociais</a></li>
</ul>
<label for="actividadePrincipal">Actividade Principal</label>
<input type="radio" id="radios_actividadePrincipal_cs" name="radio-group-actividadePrincipal-cs">
<input type="radio" id="radios_actividadePrincipal_outra" checked>
<label for="distrito">Distrito</label>
<input id="distrito" value="Regi&#227;o Aut&#243;noma da Madeira" disabled>
<label for="radios_Contabilidade_Organizada">Contabilidade Organizada</label>
<input type="radio" id="radios_Contabilidade_Organizada_sim" checked>
<input type="radio" id="radios_Contabilidade_Organizada_nao">
<label for="TipodeSociedade">Tipo de Sociedade</label>
<input id="TipodeSociedade" value="Sociedade por quotas" disabled>
<label for="radios_Detem_OCS">Detém OCS</label>
<input type="radio" id="radios_Detem_OCS_sim" checked>
<input type="radio" id="radios_Detem_OCS_nao">
<label for="capitalSocial">Capital Social</label>
<input id="capitalSocial" value="5 100,00 €" disabled>
"""

ENTIDADE_ORGS = """
<table id="orgaosSociaisTable">
  <thead><tr><th>Pessoa</th><th>Tipo de  órgãos sociais</th><th>Função </th></tr></thead>
  <tbody>
    <tr class="border_bottom">
      <td><a href="/pessoas-regulado/?idEntidade=03C7532D-1A24-EB11-8111-00505684056E&geral=true">Adriano Guimar&#227;es Fraz&#227;o</a></td>
      <td>Ger&#234;ncia </td><td>Gerente</td>
    </tr>
    <tr class="border_bottom">
      <td><a href="/pessoas-regulado/?idEntidade=8CACE519-1A24-EB11-8111-00505684056E&geral=true">Rui Pedro da Silva Marques</a></td>
      <td>Ger&#234;ncia </td><td>Gerente</td>
    </tr>
  </tbody>
</table>
"""

ENTIDADE_OCS = """
<table id="tabelaEntidadeOcs">
  <thead><tr><th>Designação</th><th>Tipo</th><th>Entidade Proprietária</th><th>Distrito</th></tr></thead>
  <tbody>
    <tr><td>4gnews</td><td>Online</td><td>7Graus, Lda.</td><td>Porto</td></tr>
    <tr><td>Rádio Regional</td><td>Rádio</td><td>7Graus, Lda.</td><td>Coimbra</td></tr>
  </tbody>
</table>
"""

PESSOA_GERAL = """
<div class="dadosGerais">Adriano Guimar&#227;es Fraz&#227;o</div>
<input type="radio" id="radios_actividadePrincipal_cs" checked>
<input type="radio" id="radios_actividadePrincipal_outra">
<input type="radio" id="radios_Detem_OCS_sim">
<input type="radio" id="radios_Detem_OCS_nao" checked>
<input id="distrito" value="Porto" disabled>
"""

PESSOA_ORGS = """
<table id="orgaosSociaisTable">
  <thead><tr><th>Empresa</th><th>Tipo de órgãos sociais</th><th>Função </th></tr></thead>
  <tbody>
    <tr class="border_bottom">
      <td><a href="/entidades-ocs/?IDentidade=a28f2a03-1124-eb11-8111-00505684056e&amp;geral=true">7Graus, Lda. </a></td>
      <td>Ger&#234;ncia </td>
      <td style="display:none">0</td>
      <td>Gerente</td>
      <td style="display:none">0</td>
    </tr>
  </tbody>
</table>
"""


# ---------------------------------------------------------------------------
# Leitura das páginas
# ---------------------------------------------------------------------------

def test_parse_listing():
    entidades = coletor.parse_listing(LISTAGEM)
    assert [e["nome"] for e in entidades] == ["7Graus, Lda.", "93.8 ON FM, Lda."]
    assert entidades[0]["id"] == "a28f2a03-1124-eb11-8111-00505684056e"
    assert entidades[0]["slug"] == "7graus-lda"
    assert entidades[0]["tipo_sociedade"] == "Sociedade por quotas"
    assert entidades[0]["actividade_principal"] == "Comunicação Social"
    assert entidades[0]["distrito"] == "Região Autónoma da Madeira"
    assert entidades[0]["url"].endswith("/entidades-ocs/7graus-lda/")


def test_parse_listing_sem_tabela():
    assert coletor.parse_listing("<html><body>sem tabela</body></html>") == []


def test_parse_entity_geral():
    geral = coletor.parse_entity_geral(ENTIDADE_GERAL)
    assert geral["nome"] == "7Graus, Lda."
    assert geral["actividade_principal"] == "Outra"
    assert geral["contabilidade_organizada"] is True
    assert geral["tipo_sociedade"] == "Sociedade por quotas"
    assert geral["detem_ocs"] is True
    assert geral["capital_social"] == "5 100,00 €"
    assert coletor.parse_money(geral["capital_social"]) == 5100.0
    assert geral["distrito"] == "Região Autónoma da Madeira"
    assert geral["nr_registo"] == "127440"


def test_parse_entity_tabs():
    assert coletor.parse_entity_tabs(ENTIDADE_GERAL) == ["geral", "ocs", "orgs"]


def test_parse_entity_orgs():
    orgaos = coletor.parse_entity_orgs(ENTIDADE_ORGS)
    assert len(orgaos) == 2
    assert orgaos[0] == {
        "id": "03c7532d-1a24-eb11-8111-00505684056e",
        "nome": "Adriano Guimarães Frazão",
        "tipo_orgao": "Gerência",
        "funcao": "Gerente",
    }


def test_parse_entity_ocs():
    ocs = coletor.parse_entity_ocs(ENTIDADE_OCS)
    assert [o["designacao"] for o in ocs] == ["4gnews", "Rádio Regional"]
    assert ocs[0]["tipo"] == "Online"
    assert ocs[0]["entidade_proprietaria"] == "7Graus, Lda."


def test_parse_person_geral_e_orgs():
    geral = coletor.parse_person_geral(PESSOA_GERAL)
    assert geral["nome"] == "Adriano Guimarães Frazão"
    assert geral["actividade_principal"] == "Comunicação Social"
    assert geral["detem_ocs"] is False
    assert geral["distrito"] == "Porto"

    orgaos = coletor.parse_person_orgs(PESSOA_ORGS)
    assert orgaos == [{
        "id": "a28f2a03-1124-eb11-8111-00505684056e",
        "nome": "7Graus, Lda.",
        "tipo_orgao": "Gerência",
        "tipo_orgao_id": "0",
        "funcao": "Gerente",
        "funcao_id": "0",
    }]


def test_parse_financeiro_anos_e_dados():
    html = '<select><option value="2019" selected>2019</option><option value="2018">2018</option></select>'
    assert coletor.parse_financeiro_anos(html) == [2018, 2019]
    dados = coletor.parse_financeiro([{
        "Erc_ano": "2019",
        "Erc_ativototal": "8948803,2400",
        "Erc_capitalproprio": "8124957,0400",
        "Erc_resultadosliquidos": "2404694,8400",
        "Erc_resultadosoperacionaisdepreciacoes": "1500000,0000",
        "Erc_responsabilidadesnaoinscritas": "250000,0000",
        "Erc_solicitopedidoconfidencialidade": "False",
    }])
    assert dados == [{
        "ano": 2019,
        "ativo_total": 8948803.24,
        "passivo_total": None,
        "passivos_totais": None,
        "capital_proprio": 8124957.04,
        "rendimentos_totais": None,
        "resultados_antes_custos": None,
        "resultados_operacionais_depreciacoes": 1500000.0,
        "resultados_liquidos": 2404694.84,
        "responsabilidades_nao_inscritas": 250000.0,
        "nota": None,
        "confidencialidade": False,
    }]


def test_parse_money_recusa_texto():
    """O portal publica deliberações no lugar das contas: não são números."""
    assert coletor.parse_money("5 100,00 €") == 5100.0
    assert coletor.parse_money("1.234.567,89") == 1234567.89
    assert coletor.parse_money("50%") == 50.0
    assert coletor.parse_money("-1.234,56") == -1234.56
    assert coletor.parse_money(None) is None
    assert coletor.parse_money("") is None
    assert coletor.parse_money("n.d.") is None
    # Sem a validação, os dígitos da deliberação davam 20 mil milhões de euros.
    assert coletor.parse_money("Deliberação ERC/2024/532 - Defere a exceção de divulgação") is None


def test_parse_financeiro_guarda_nota_de_excecao():
    """Exceção de divulgação: os valores ficam vazios, a nota e o sinal ficam."""
    dados = coletor.parse_financeiro([{
        "Erc_ano": "2023",
        "Erc_ativototal": "123456,0000",
        "Erc_passivototal": "Deliberação ERC/2024/532 - Defere a exceção\nde divulgação dos fluxos",
    }])
    assert dados[0]["ativo_total"] == 123456.0
    assert dados[0]["passivo_total"] is None
    assert dados[0]["nota"] == "Deliberação ERC/2024/532 - Defere a exceção de divulgação dos fluxos"
    assert dados[0]["confidencialidade"] is True


def test_parse_financeiro_ignora_marcadores_de_vazio():
    """«True» e «Não aplicável» não são notas: o portal usa-os para dizer vazio."""
    dados = coletor.parse_financeiro([{
        "Erc_ano": "2022",
        "Erc_ativototal": "1000,0000",
        "Erc_resultadosoperacionaisdepreciacoes": "True",
        "Erc_passivototal": "Não aplicável",
        "Erc_solicitopedidoconfidencialidade": "False",
    }])
    assert dados[0]["nota"] is None
    assert dados[0]["resultados_operacionais_depreciacoes"] is None
    assert dados[0]["passivo_total"] is None
    assert dados[0]["ativo_total"] == 1000.0
    assert dados[0]["confidencialidade"] is False


def test_analise_assinala_excecao_de_divulgacao():
    entidade = {
        "nome": "Exceção, Lda.",
        "financeiro": [
            {"ano": 2024, "nota": "Deliberação ERC/2024/532 - Defere a exceção de divulgação", "confidencialidade": True},
            {"ano": 2023, "ativo_total": 1000.0, "passivo_total": 400.0, "capital_proprio": 600.0,
             "rendimentos_totais": 900.0, "resultados_liquidos": 50.0, "confidencialidade": False},
        ],
    }
    analise = erc_risco.analisar(entidade)
    assert any("Exceção de divulgação deferida pela ERC em 2024" in alerta for alerta in analise["alertas"])
    componentes = {item["chave"]: item for item in analise["risco"]["componentes"]}
    assert "2024" in componentes["confidencialidade"]["detalhe"]


def test_iter_pessoas_deduplica():
    orgaos = [
        {"id": "a", "nome": "Ana"},
        {"id": "a", "nome": "Ana"},
        {"id": None, "nome": "Sem id"},
        {"id": "b", "nome": "Bruno"},
    ]
    assert coletor.iter_pessoas(orgaos) == [{"id": "a", "nome": "Ana"}, {"id": "b", "nome": "Bruno"}]


# ---------------------------------------------------------------------------
# Estrutura de propriedade: sentido da ligação
# ---------------------------------------------------------------------------

_DETEM = "07a62852-28a3-e511-80d7-6c3be5beee0c"       # «Detém diretamente»
_DETIDA = "f315cd28-287e-e511-80fa-3863bb3630d8"      # «Diretamente detidas»


def _ligacao(r1: str, r1nome: str, r1role: str, r2: str, r2nome: str, r2role: str, pct: str = "50,000") -> dict:
    return {
        "record1id": r1, "record1id_name": r1nome, "record1roleid": r1role, "record1roleid_name": "",
        "record2id": r2, "record2id_name": r2nome, "record2roleid": r2role, "record2roleid_name": "",
        "record1objecttypecode": "2", "record2objecttypecode": "1",
        "erc_percentagem": pct, "erc_direitosvoto": pct,
    }


def test_estrutura_sujeito_detem_contraparte_e_detentor():
    """Sujeito com papel «detém» → a contraparte detém-no (é detentora)."""
    payload = {"data": [_ligacao("guid-pessoa", "Adriano", _DETIDA, "guid-empresa", "7Graus", _DETEM)]}
    ligacoes = coletor.parse_estrutura(payload, "guid-empresa")
    assert len(ligacoes) == 1
    assert ligacoes[0]["nome"] == "Adriano"
    assert ligacoes[0]["tipo_relacao"] == "detentor"
    assert ligacoes[0]["percentagem_valor"] == 50.0
    assert ligacoes[0]["e_pessoa"] is True


def test_estrutura_sujeito_detido_contraparte_e_detida():
    """Sujeito com papel «é detida» → a contraparte é detida por ele."""
    payload = {"data": [_ligacao("guid-empresa", "7Graus", _DETIDA, "guid-filha", "Filha", _DETEM)]}
    ligacoes = coletor.parse_estrutura(payload, "guid-empresa")
    assert ligacoes[0]["nome"] == "Filha"
    assert ligacoes[0]["tipo_relacao"] == "detida"


def test_estrutura_ignora_papeis_que_nao_sao_detencao():
    payload = {"data": [_ligacao("a", "A", "outro-papel", "b", "B", "outro-papel")]}
    assert coletor.parse_estrutura(payload, "b") == []


def test_estrutura_participacoes_de_pessoa_nao_filtram_papel():
    payload = {"data": [_ligacao("guid-empresa", "7Graus", _DETIDA, "guid-pessoa", "Adriano", _DETEM)]}
    ligacoes = coletor.parse_estrutura(payload, "guid-pessoa", pessoa=True)
    assert ligacoes[0]["nome"] == "7Graus"
    assert ligacoes[0]["tipo_relacao"] == "detida"


# ---------------------------------------------------------------------------
# Recolha (cliente HTTP falso)
# ---------------------------------------------------------------------------

class _Resposta:
    def __init__(self, texto: str, payload=None):
        self.text = texto
        self.status_code = 200
        self._payload = payload

    def json(self):
        return self._payload if self._payload is not None else {}

    def raise_for_status(self):
        return None


class _ClienteFalso:
    """Cliente que responde às páginas e à API pelos parâmetros do pedido."""

    def __init__(self, paginas: dict, api: dict):
        self.paginas = paginas
        self.api = api
        self.pedidos = []

    def get(self, url, params=None, **kwargs):
        self.pedidos.append((url, dict(params or {})))
        caminho = url.split("?")[0]
        chave = "/".join(caminho.split("/")[3:])
        if "Umbraco/Api" in url:
            # A API financeira distingue-se pelo exercício pedido.
            especifica = (caminho, (params or {}).get("anoFinanceiro"))
            if especifica in self.api:
                return _Resposta("", self.api[especifica])
            return _Resposta("", self.api.get(caminho))
        geral = (params or {}).get("geral")
        return _Resposta(self.paginas.get((chave, geral), "<html></html>"))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture()
def data_dir_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(erc, "DEFAULT_DATA_DIR", tmp_path / "erc")
    return tmp_path / "erc"


def test_ficha_entidade_e_pessoa(data_dir_tmp):
    cliente = _ClienteFalso(
        paginas={
            (f"entidades-ocs/7graus-lda/", "geral"): ENTIDADE_GERAL,
            (f"entidades-ocs/7graus-lda/", "orgs"): ENTIDADE_ORGS,
            (f"entidades-ocs/7graus-lda/", "ocs"): ENTIDADE_OCS,
            ("pessoas-regulado/", "geral"): PESSOA_GERAL,
            ("pessoas-regulado/", "orgs"): PESSOA_ORGS,
        },
        api={
            "https://portaltransparencia.erc.pt/Umbraco/Api/EstruturaCapitalSocial/GetEmpresasQueDetemEstaEmpresa":
                {"data": [_ligacao("guid-adriano", "Adriano Guimarães Frazão", _DETIDA, "guid-7graus", "7Graus", _DETEM)]},
            "https://portaltransparencia.erc.pt/Umbraco/Api/EstruturaCapitalSocial/GetEmpresasQueDetemParticipacao":
                {"data": [_ligacao("guid-7graus", "7Graus, Lda.", _DETIDA, "guid-adriano", "Adriano Guimarães Frazão", _DETEM)]},
        },
    )
    item = {"id": "a28f2a03-1124-eb11-8111-00505684056e", "nome": "7Graus, Lda.", "slug": "7graus-lda"}
    doc, orgs, ocs, recolhas = erc._ficha_entidade(
        cliente, item, pausa=0.0, com_estrutura=True, com_financeiro=False, guardar_html=True,
    )
    assert doc["doc_id"] == item["id"]
    assert doc["nome"] == "7Graus, Lda."
    assert doc["n_pessoas"] == 2 and doc["n_ocs"] == 2
    assert doc["n_detentores"] == 1 and doc["n_detidas"] == 0
    assert doc["pessoas_nomes"] == ["Adriano Guimarães Frazão", "Rui Pedro da Silva Marques"]
    assert doc["ocs_designacoes"] == ["4gnews", "Rádio Regional"]
    assert doc["capital_social_eur"] == 5100.0
    assert len(orgs) == 2 and len(ocs) == 2
    assert len(recolhas) == 3  # geral + orgs + ocs

    pessoas = coletor.iter_pessoas(orgs)
    doc_p, _ = erc._ficha_pessoa(cliente, pessoas[0], pausa=0.0, guardar_html=True)
    assert doc_p["doc_id"] == "03c7532d-1a24-eb11-8111-00505684056e"
    assert doc_p["nome"] == "Adriano Guimarães Frazão"
    assert doc_p["n_empresas"] == 1
    assert doc_p["empresas"] == ["7Graus, Lda."]
    assert doc_p["n_participacoes"] == 1
    assert doc_p["participacoes"][0]["tipo_relacao"] == "detida"

    assert (erc.data_dir() / "raw").exists()


def test_recolher_grava_jsonl_e_recolhas(data_dir_tmp, monkeypatch):
    cliente = _ClienteFalso(
        paginas={
            ("entidades-ocs/7graus-lda/", "geral"): ENTIDADE_GERAL,
            ("entidades-ocs/7graus-lda/", "orgs"): ENTIDADE_ORGS,
            ("entidades-ocs/7graus-lda/", "ocs"): ENTIDADE_OCS,
            ("pessoas-regulado/", "geral"): PESSOA_GERAL,
            ("pessoas-regulado/", "orgs"): PESSOA_ORGS,
        },
        api={
            "https://portaltransparencia.erc.pt/Umbraco/Api/EstruturaCapitalSocial/GetEmpresasQueDetemEstaEmpresa": {"data": []},
            "https://portaltransparencia.erc.pt/Umbraco/Api/EstruturaCapitalSocial/GetEmpresasQueDetemParticipacao": {"data": []},
        },
    )
    monkeypatch.setattr(erc.erc, "make_client", lambda timeout=60.0: cliente)
    monkeypatch.setattr(erc, "ler_listagem", lambda *, forcar=False, progresso=None: [
        {"id": "a28f2a03-1124-eb11-8111-00505684056e", "nome": "7Graus, Lda.", "slug": "7graus-lda"},
    ])

    resultado = erc.recolher(limite=1, pausa=0.0, guardar_html=False, forcar=True)
    assert resultado["errors"] == []
    assert resultado["entidades"] == 1
    assert resultado["pessoas"] == 2
    assert resultado["ocs"] == 2

    entidades = [json.loads(linha) for linha in erc.entidades_jsonl().read_text(encoding="utf-8").splitlines()]
    pessoas = [json.loads(linha) for linha in erc.pessoas_jsonl().read_text(encoding="utf-8").splitlines()]
    recolhas = [json.loads(linha) for linha in erc.recolhas_jsonl().read_text(encoding="utf-8").splitlines()]
    assert len(entidades) == 1 and entidades[0]["nome"] == "7Graus, Lda."
    assert len(pessoas) == 2
    assert recolhas and all(r.get("recolha_id") for r in recolhas)

    # Reexecutar substitui (upsert por `doc_id`), não duplica.
    erc.recolher(limite=1, pausa=0.0, guardar_html=False, forcar=True)
    entidades = [json.loads(linha) for linha in erc.entidades_jsonl().read_text(encoding="utf-8").splitlines()]
    assert len(entidades) == 1


def test_recolher_salta_existentes_e_usa_varios_trabalhadores(data_dir_tmp, monkeypatch):
    """`saltar_existentes` retoma sem repetir; `trabalhadores>1` corre em paralelo."""
    cliente = _ClienteFalso(
        paginas={
            ("entidades-ocs/7graus-lda/", "geral"): ENTIDADE_GERAL,
            ("entidades-ocs/7graus-lda/", "orgs"): ENTIDADE_ORGS,
            ("entidades-ocs/7graus-lda/", "ocs"): ENTIDADE_OCS,
            ("entidades-ocs/outra-lda/", "geral"): ENTIDADE_GERAL,
            ("entidades-ocs/outra-lda/", "orgs"): ENTIDADE_ORGS,
            ("entidades-ocs/outra-lda/", "ocs"): ENTIDADE_OCS,
        },
        api={
            "https://portaltransparencia.erc.pt/Umbraco/Api/EstruturaCapitalSocial/GetEmpresasQueDetemEstaEmpresa": {"data": []},
        },
    )
    monkeypatch.setattr(erc.erc, "make_client", lambda timeout=60.0: cliente)
    monkeypatch.setattr(erc, "ler_listagem", lambda *, forcar=False, progresso=None: [
        {"id": "a28f2a03-1124-eb11-8111-00505684056e", "nome": "7Graus, Lda.", "slug": "7graus-lda"},
        {"id": "bbbbbbbb-1124-eb11-8111-00505684056e", "nome": "Outra, Lda.", "slug": "outra-lda"},
    ])

    primeira = erc.recolher(limite=1, pausa=0.0, guardar_html=False, com_pessoas=False, forcar=True)
    assert primeira["recolhidas_agora"]["entidades"] == 1

    segunda = erc.recolher(pausa=0.0, guardar_html=False, com_pessoas=False, forcar=True, saltar_existentes=True, trabalhadores=2)
    assert segunda["recolhidas_agora"]["saltadas"] == 1  # a primeira entidade não é relida
    assert segunda["recolhidas_agora"]["entidades"] == 1
    assert segunda["entidades"] == 2
    assert segunda["trabalhadores"] == 2


# ---------------------------------------------------------------------------
# Leitura sem Elasticsearch
# ---------------------------------------------------------------------------

def test_listar_sem_es(data_dir_tmp):
    entidade = {
        "doc_id": "a", "nome": "7Graus, Lda.", "distrito": "Região Autónoma da Madeira",
        "tipo_sociedade": "Sociedade por quotas", "ocs_designacoes": ["4gnews"],
        "pessoas_nomes": ["Adriano Guimarães Frazão"],
    }
    outra = {"doc_id": "b", "nome": "Rádio X", "distrito": "Lisboa", "tipo_sociedade": "Cooperativa"}
    erc.entidades_jsonl().write_text(
        "\n".join(json.dumps(d, ensure_ascii=False) for d in (entidade, outra)), encoding="utf-8",
    )
    assert erc.listar_entidades(usar_es=False)["total"] == 2
    assert erc.listar_entidades(q="4gnews", usar_es=False)["total"] == 1
    assert erc.listar_entidades(distrito="lisboa", usar_es=False)["total"] == 1
    assert erc.listar_entidades(tipo_sociedade="Cooperativa", usar_es=False)["total"] == 1
    assert erc.get_entidade("a")["nome"] == "7Graus, Lda."
    assert erc.get_entidade("inexistente") is None

    erc.pessoas_jsonl().write_text(json.dumps({
        "doc_id": "p", "nome": "Adriano Guimarães Frazão", "distrito": "Porto",
        "empresas": ["7Graus, Lda."], "participacoes_nomes": ["7Graus, Lda."],
    }, ensure_ascii=False), encoding="utf-8")
    assert erc.listar_pessoas(q="Frazão", usar_es=False)["total"] == 1
    assert erc.listar_pessoas(empresa="7graus", usar_es=False)["total"] == 1
    assert erc.get_pessoa("p")["nome"] == "Adriano Guimarães Frazão"
    assert erc.get_pessoa("p").get("n_empresas") is None  # só existe se a recolha o tiver

    erc.ocs_jsonl().write_text(json.dumps({
        "doc_id": "o", "designacao": "4gnews", "tipo": "Online", "entidade_proprietaria": "7Graus, Lda.",
    }, ensure_ascii=False), encoding="utf-8")
    assert erc.listar_ocs(tipo="Online", usar_es=False)["total"] == 1
    assert erc.listar_ocs(proprietaria="7graus", usar_es=False)["total"] == 1


def test_resumo_e_export(data_dir_tmp):
    erc.entidades_jsonl().write_text(json.dumps({
        "doc_id": "a", "nome": "7Graus, Lda.", "distrito": "Madeira", "tipo_sociedade": "Sociedade por quotas",
        "actividade_principal": "Outra", "detem_ocs": True, "n_ocs": 1, "n_pessoas": 1,
        "ocs_designacoes": ["4gnews"], "pessoas_nomes": ["Adriano"],
        "pessoas": [{"id": "p", "nome": "Adriano", "tipo_orgao": "Gerência", "funcao": "Gerente"}],
    }, ensure_ascii=False), encoding="utf-8")
    erc.ocs_jsonl().write_text(json.dumps({
        "doc_id": "o", "designacao": "4gnews", "tipo": "Online", "entidade_proprietaria": "7Graus, Lda.",
        "distrito": "Porto",
    }, ensure_ascii=False), encoding="utf-8")
    resumo = erc.resumo()
    assert resumo["entidades"] == 1 and resumo["ocs"] == 1
    assert resumo["distritos"][0] == {"key": "Madeira", "count": 1}
    assert resumo["funcoes"][0] == {"key": "Gerente", "count": 1}

    csv_entidades = erc.export_csv("entidades")
    assert csv_entidades.splitlines()[0].startswith("id,nome,tipo_sociedade")
    assert "7Graus, Lda." in csv_entidades
    assert "designacao" in erc.export_csv("ocs").splitlines()[0]
    assert "participacoes" in erc.export_csv("pessoas").splitlines()[0]


def test_meta_lista_indices(data_dir_tmp):
    info = erc.meta()
    assert info["indices"]["entidades"] == "finance_erc_entidades"
    assert info["indices"]["pessoas"] == "finance_erc_pessoas"
    assert info["indices"]["ocs"] == "finance_erc_ocs"
    assert info["contagens"]["entidades"] == 0


def test_slug_normaliza_acentos():
    assert erc._slug("Rádio Regional do Centro, Lda.") == "radio-regional-do-centro-lda"
    assert erc._slug("") == "sem-nome"


# ---------------------------------------------------------------------------
# Dados financeiros (secção `dafin`) e análise de risco
# ---------------------------------------------------------------------------

SERIE = [
    {"ano": 2024, "ativo_total": 3204.72, "passivo_total": 2000.0, "capital_proprio": 1204.72,
     "rendimentos_totais": 3900.0, "resultados_liquidos": 180.0, "confidencialidade": False},
    {"ano": 2025, "ativo_total": 2403.31, "passivo_total": 900.0, "capital_proprio": 1503.31,
     "rendimentos_totais": 4200.0, "resultados_liquidos": 320.0, "confidencialidade": False},
]


def test_enriquecer_serie_ordena_e_calcula_racios():
    serie = erc_risco.enriquecer_serie(SERIE)
    assert [item["ano"] for item in serie] == [2025, 2024]
    assert serie[0]["autonomia_financeira"] == pytest.approx(1503.31 / 2403.31)
    assert serie[0]["endividamento"] == pytest.approx(900.0 / 2403.31)
    assert serie[0]["margem_liquida"] == pytest.approx(320.0 / 4200.0)
    # O crescimento compara com o exercício publicado anterior (2024), não com o ano civil.
    assert serie[0]["ano_comparacao"] == 2024
    assert serie[0]["crescimento_rendimentos"] == pytest.approx((4200.0 - 3900.0) / 3900.0)
    assert serie[1]["crescimento_rendimentos"] is None


def test_resumo_financeiro_conta_positivos_e_negativos():
    resumo = erc_risco.resumo_financeiro([
        {"ano": 2025, "resultados_liquidos": 10.0},
        {"ano": 2024, "resultados_liquidos": -5.0},
        {"ano": 2023, "resultados_liquidos": 7.0},
    ])
    assert resumo["n_anos_financeiro"] == 3
    assert resumo["primeiro_ano_financeiro"] == 2023
    assert resumo["ultimo_ano_financeiro"] == 2025
    assert resumo["anos_resultados_positivos"] == 2
    assert resumo["anos_resultados_negativos"] == 1


def test_analise_sem_contas_nao_inventa_credito():
    analise = erc_risco.analisar({"nome": "Sem contas", "financeiro": [], "n_pessoas": 0, "n_ocs": 0})
    assert analise["credito"]["disponivel"] is False
    assert analise["credito"]["score"] is None
    assert analise["credito"]["nivel"] == "sem dados"
    assert analise["transparencia"]["score"] < 25
    # Sem contas publicadas o risco sobe: é a opacidade que está a ser medida.
    assert analise["risco"]["banda"] in {"elevado", "critico"}
    assert any("Sem contas publicadas" in alerta for alerta in analise["alertas"])
    assert "autodeclarados" in analise["limitacoes"]


def test_analise_entidade_solida_fica_com_risco_baixo():
    entidade = {
        "nome": "Sólida, Lda.", "contabilidade_organizada": True, "detem_ocs": True, "n_ocs": 3,
        "n_pessoas": 4, "n_detentores": 2, "n_detidas": 1, "capital_social": "100 000,00 €",
        "capital_social_eur": 100000.0, "financeiro": SERIE,
    }
    analise = erc_risco.analisar(entidade)
    assert analise["transparencia"]["score"] >= 75
    assert analise["credito"]["nivel"] in {"A", "B"}
    assert analise["risco"]["banda"] == "baixo"
    assert analise["alertas"] == []
    assert analise["cobertura"]["anos_financeiros"] == 2


def test_analise_prejuizo_e_endividamento_sobem_o_risco():
    entidade = {
        "nome": "Endividada, Lda.", "financeiro": [
            {"ano": 2025, "ativo_total": 1000.0, "passivo_total": 980.0, "capital_proprio": 20.0,
             "rendimentos_totais": 500.0, "resultados_liquidos": -120.0, "confidencialidade": True},
            {"ano": 2024, "ativo_total": 1000.0, "passivo_total": 950.0, "capital_proprio": 50.0,
             "rendimentos_totais": 700.0, "resultados_liquidos": -30.0, "confidencialidade": False},
        ],
    }
    analise = erc_risco.analisar(entidade)
    chaves = {item["chave"] for item in analise["risco"]["componentes"]}
    assert {"resultado_negativo", "prejuizos_repetidos", "capital_proprio_baixo", "endividamento_critico", "confidencialidade"} <= chaves
    assert analise["risco"]["banda"] in {"elevado", "critico"}
    assert any("Prejuízo no exercício 2025" in alerta for alerta in analise["alertas"])


def test_aplicar_acrescenta_resumo_e_analise_ao_documento():
    doc = erc_risco.aplicar({"doc_id": "x", "nome": "Exemplo", "financeiro": SERIE, "n_pessoas": 1})
    assert doc["n_anos_financeiro"] == 2
    assert doc["ultimo_ano_financeiro"] == 2025
    assert doc["ultimo_rendimentos"] == 4200.0
    assert doc["financeiro"][0]["ano"] == 2025
    assert doc["analise"]["transparencia"]["score"] > 0


def test_recalcular_analises_escreve_nos_jsonl(data_dir_tmp):
    erc.entidades_jsonl().write_text(
        "\n".join(json.dumps(doc, ensure_ascii=False) for doc in (
            {"doc_id": "a", "nome": "Com contas", "financeiro": SERIE},
            {"doc_id": "b", "nome": "Sem contas", "financeiro": []},
        )),
        encoding="utf-8",
    )
    resultado = erc.recalcular_analises()
    assert resultado["entidades"] == 2
    assert resultado["com_dados_financeiros"] == 1
    assert resultado["com_credito"] == 1
    docs = {json.loads(linha)["doc_id"]: json.loads(linha) for linha in erc.entidades_jsonl().read_text(encoding="utf-8").splitlines()}
    assert docs["a"]["analise"]["credito"]["disponivel"] is True
    assert docs["b"]["analise"]["credito"]["disponivel"] is False


def test_recolher_financeiro_funde_series_e_regista_recolhas(data_dir_tmp, monkeypatch):
    """A janela é varrida ano a ano e só o que existe entra no documento."""
    caminho = "https://portaltransparencia.erc.pt/Umbraco/Api/CaracterizacaoFinanceira/GetDadosFinanceira"
    cliente = _ClienteFalso(
        paginas={},
        api={
            (caminho, 2025): [{"Erc_ano": "2025", "Erc_ativototal": "2403,3100", "Erc_capitalproprio": "1503,3100",
                               "Erc_rendimentostotais": "4200,0000", "Erc_resultadosliquidos": "320,0000"}],
            (caminho, 2024): [{"Erc_ano": "2024", "Erc_ativototal": "3204,7200", "Erc_capitalproprio": "1204,7200",
                               "Erc_rendimentostotais": "3900,0000", "Erc_resultadosliquidos": "180,0000"}],
            # 2023 e 2022 não têm publicação: a API devolve vazio.
        },
    )
    monkeypatch.setattr(erc.erc, "make_client", lambda timeout=60.0: cliente)
    erc.entidades_jsonl().write_text(
        json.dumps({"doc_id": "a", "nome": "7Graus, Lda.", "n_pessoas": 2}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    resultado = erc.recolher_financeiro(ano_inicio=2022, ano_fim=2025, pausa=0.0, trabalhadores=1)
    assert resultado["errors"] == []
    assert resultado["varridas"] == 1
    assert resultado["com_dados"] == 1
    assert resultado["anos"] == {"inicio": 2022, "fim": 2025, "total": 4}

    doc = json.loads(erc.entidades_jsonl().read_text(encoding="utf-8").splitlines()[0])
    assert [item["ano"] for item in doc["financeiro"]] == [2025, 2024]
    assert doc["n_anos_financeiro"] == 2
    assert doc["analise"]["credito"]["disponivel"] is True
    recolhas = [json.loads(linha) for linha in erc.recolhas_jsonl().read_text(encoding="utf-8").splitlines()]
    assert [r["ano"] for r in recolhas] == [2025, 2024]
    assert all(r["tipo"] == "financeiro" for r in recolhas)

    # Segunda passagem: a entidade já tem contas, por isso é saltada.
    segunda = erc.recolher_financeiro(ano_inicio=2022, ano_fim=2025, pausa=0.0, trabalhadores=1)
    assert segunda["varridas"] == 0
    assert segunda["com_dados"] == 0


def test_recolher_financeiro_para_depois_de_anos_vazios(data_dir_tmp, monkeypatch):
    """`vazios_seguidos` corta o varrimento depois de N exercícios sem publicação."""
    caminho = "https://portaltransparencia.erc.pt/Umbraco/Api/CaracterizacaoFinanceira/GetDadosFinanceira"
    cliente = _ClienteFalso(
        paginas={},
        api={(caminho, 2025): [{"Erc_ano": "2025", "Erc_ativototal": "100,0000"}]},
    )
    monkeypatch.setattr(erc.erc, "make_client", lambda timeout=60.0: cliente)
    erc.entidades_jsonl().write_text(json.dumps({"doc_id": "a", "nome": "Curta", "n_pessoas": 0}) + "\n", encoding="utf-8")

    erc.recolher_financeiro(ano_inicio=2015, ano_fim=2025, vazios_seguidos=3, pausa=0.0, trabalhadores=1)
    anos_pedidos = [params.get("anoFinanceiro") for _, params in cliente.pedidos]
    assert anos_pedidos == [2025, 2024, 2023, 2022]  # para aos 3 vazios depois do último com dados


def test_listar_analise_sem_es(data_dir_tmp):
    docs = [
        erc_risco.aplicar({"doc_id": "a", "nome": "Alfa, Lda.", "distrito": "Lisboa", "financeiro": SERIE, "n_pessoas": 3}),
        erc_risco.aplicar({"doc_id": "b", "nome": "Beta, Lda.", "distrito": "Porto", "financeiro": []}),
    ]
    erc.entidades_jsonl().write_text("\n".join(json.dumps(doc, ensure_ascii=False) for doc in docs), encoding="utf-8")

    todos = erc.listar_analise(usar_es=False, ordenar="nome")
    assert todos["origem"] == "jsonl"
    assert [item["doc_id"] for item in todos["items"]] == ["a", "b"]

    sem_contas = erc.listar_analise(usar_es=False, com_financeiro=False)
    assert [item["doc_id"] for item in sem_contas["items"]] == ["b"]

    so_lisboa = erc.listar_analise(usar_es=False, distrito="Lisboa")
    assert [item["doc_id"] for item in so_lisboa["items"]] == ["a"]

    # Ordenar por risco traz primeiro o pior (Beta não publica contas).
    por_risco = erc.listar_analise(usar_es=False, ordenar="risco")
    assert por_risco["items"][0]["doc_id"] == "b"
    assert por_risco["items"][0]["analise"]["risco"]["score"] >= por_risco["items"][1]["analise"]["risco"]["score"]


def test_export_csv_inclui_analise_e_serie(data_dir_tmp):
    doc = erc_risco.aplicar({"doc_id": "a", "nome": "Alfa, Lda.", "financeiro": SERIE, "n_pessoas": 1})
    erc.entidades_jsonl().write_text(json.dumps(doc, ensure_ascii=False) + "\n", encoding="utf-8")

    csv_entidades = erc.export_csv("entidades")
    assert "risco,banda_risco" in csv_entidades.splitlines()[0]
    assert "Alfa, Lda." in csv_entidades

    csv_analise = erc.export_csv("analise")
    assert "transparencia,nivel_transparencia,credito,nivel_credito" in csv_analise.splitlines()[0]

    csv_financeiro = erc.export_csv("financeiro")
    linhas = csv_financeiro.splitlines()
    assert linhas[0].startswith("id,nome,distrito,ano,ativo_total")
    assert len(linhas) == 3  # cabeçalho + dois exercícios


def test_meta_e_resumo_contam_financeiro(data_dir_tmp):
    docs = [
        erc_risco.aplicar({"doc_id": "a", "nome": "Alfa", "distrito": "Lisboa", "financeiro": SERIE, "n_pessoas": 0}),
        erc_risco.aplicar({"doc_id": "b", "nome": "Beta", "distrito": "Porto", "financeiro": []}),
    ]
    erc.entidades_jsonl().write_text("\n".join(json.dumps(doc, ensure_ascii=False) for doc in docs), encoding="utf-8")

    info = erc.meta()
    assert info["contagens"]["entidades_com_financeiro"] == 1
    assert info["contagens"]["anos_financeiro"] == [2025, 2024]
    assert sum(info["contagens"]["bandas_risco"].values()) == 2

    painel = erc.resumo()
    assert painel["entidades_com_financeiro"] == 1
    assert {item["key"] for item in painel["anos_financeiro"]} == {"2024", "2025"}


def test_painel_financeiro_sem_es(data_dir_tmp, monkeypatch):
    from api import elasticsearch_client as es

    monkeypatch.setattr(es, "erc_financeiro_painel", lambda es=None: {"error": "Elasticsearch indisponível"})
    doc = erc_risco.aplicar({"doc_id": "a", "nome": "Alfa", "financeiro": SERIE, "n_pessoas": 0})
    erc.entidades_jsonl().write_text(json.dumps(doc, ensure_ascii=False) + "\n", encoding="utf-8")

    painel = erc.painel_financeiro()
    assert painel["origem"] == "jsonl"
    assert painel["com_financeiro"] == 1
    anos = {item["ano"]: item for item in painel["anos"]}
    assert anos[2025]["balancos"] == 1
    assert anos[2025]["rendimentos"] == 4200.0
    assert anos[2025]["com_prejuizo"] == 0


def test_anos_a_varrer_por_omissao_e_janela():
    from datetime import datetime

    atual = datetime.now().year
    assert erc.anos_a_varrer() == [atual - 1, atual - 2, atual - 3, atual - 4]
    assert erc.anos_a_varrer(2018, 2020) == [2020, 2019, 2018]
    assert erc.anos_a_varrer(2020, 2018) == [2020, 2019, 2018]  # inverte se vierem trocados
