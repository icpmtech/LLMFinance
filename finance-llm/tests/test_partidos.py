"""Partidos políticos e as suas contas (Tribunal Constitucional + CNE).

Testa o que **não** depende da rede nem do Elasticsearch: a leitura das páginas
anuais do financiamento partidário (secções por âncora, entradas com PDF, quem
não entregou, notas e documentos agregados), a leitura do registo oficial da CNE
(inscritos e extintos), a normalização dos nomes/siglas — o TC escreve o mesmo
de várias formas: `PCP (não comunicou)`, `PXXI - Contas entregues fora de prazo`,
`PAN (Retificadas em 03-04-2014`, `PPD/PSD "Retificou em 13/04/2016"` — e a
gravação do JSONL e do manifesto.

As páginas reais são HTML gerado pelo site do TC; aqui usam-se páginas sintéticas
com a mesma estrutura, para os testes serem rápidos e determinísticos.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from api import partidos_service as partidos

# ---------------------------------------------------------------------------
# Páginas sintéticas
# ---------------------------------------------------------------------------


def _entrada(nome: str = "", *, href: str = "", titulo: str = "", sigla: str = "", texto: str = "") -> str:
    """Uma entrada (`<li class="list">`) de uma secção, como o TC a escreve."""
    if href:
        corpo = f'<a href="{href}" class=" " target="_pdf" title="{titulo}">{nome}</a>'
    else:
        corpo = nome or texto
    if sigla or href:
        corpo += f'\n<br /><span class="links">{sigla}</span>\n<br />'
    return f'<li class="list" style="margin-top:6px;">{corpo}</li>'


def _nota(texto: str) -> str:
    return f'<li class="list" style="margin-top:6px; list-style-type:none; font-size:84%; ">{texto}</li>'


def _secao(ancora: str, titulo: str, entradas: list[str]) -> str:
    return (
        f'<li class="list" style="margin-top:64px;"><a name="{ancora}" class="sub_sub_titulo"></a>'
        f"<h4>{titulo}</h4>\n<ul>{''.join(entradas)}</ul></li>"
    )


def _pagina(*secoes: str) -> str:
    return (
        "<!doctype html><html><body>\n"
        '<ul><li class="list"><a href="#1104">Lista de ações e meios por partido político</a></li>'
        '<li class="list"><a href="#1111">Contas Anuais dos Partidos Políticos</a></li></ul>\n'
        f"<article><div class=\"eleicoes18\">{''.join(secoes)}</div></article>\n"
        "</body></html>"
    )


PAGINA_2024 = _pagina(
    _secao(
        "1104",
        "Lista de ações e meios por partido político",
        [
            _nota("Listas de ações de propaganda política e meios nelas utilizados<br />Comunicação à ECFP"),
            _entrada(
                "Partido Comunista Português",
                href="file/4_CA2025_PCP_ListaAM_vf.pdf?src=1&mid=9340&bid=8158",
                titulo="doc em formato PDF (9376 kb); ",
                sigla="PCP",
            ),
            _entrada(
                "Partido Comunista dos Trabalhadores Portugueses",
                sigla="PCTP/MRPP (Não entregou)",
            ),
            _entrada("Partido Comunista Português", href="file/pcp-lista.pdf", sigla="PCP (retificadas em 9/11/2012)"),
        ],
    ),
    _secao(
        "1111",
        "Contas Anuais enviadas pelos Partidos Políticos à ECFP referentes ao ano de 2024 para apreciação",
        [
            _nota("(artigo 26.º, n.º 1, da Lei n.º 19/2003, de 20 de junho)"),
            _entrada(
                "Partido Socialista",
                href="file/4_CA2024_PS_Balanco_DResultados.pdf?src=1&mid=8767&bid=7529",
                titulo="doc em formato PDF (2924 kb); ",
                sigla="PS",
            ),
            _entrada("Partido Comunista Português", sigla="PCP [versão retificada em 8.06.2022 (a pedido do partido)]"),
            _entrada("CDS - Partido Popular", href="file/CDS.pdf", sigla="CDS - PP"),
            _entrada("Deputado independente na ALRAM", href="file/declaracao.pdf", sigla="Deputado independente na ALRAM"),
        ],
    ),
)


# ---------------------------------------------------------------------------
# Leitura das páginas anuais
# ---------------------------------------------------------------------------


def test_pagina_ano_le_as_secoes_pela_ancora():
    analise = partidos.parse_pagina_ano(PAGINA_2024, 2024)
    assert analise["ano"] == 2024
    assert [secao["secao"] for secao in analise["secoes"]] == ["lista_acoes", "contas_anuais"]
    assert analise["secoes"][0]["ancora"] == "1104"
    assert analise["secoes"][1]["ancora"] == "1111"


def test_entrada_com_pdf_fica_com_url_absoluta_e_ficheiro():
    lista = partidos.parse_pagina_ano(PAGINA_2024, 2024)["secoes"][0]["itens"][1]
    assert lista["partido_sigla"] == "PCP"
    assert lista["partido_nome"] == "Partido Comunista Português"
    assert lista["entregou"] is True
    assert lista["documento"] is True
    assert lista["pdf_titulo"] == "doc em formato PDF (9376 kb);"
    assert lista["href"] == "https://www.tribunalconstitucional.pt/tc/file/4_CA2025_PCP_ListaAM_vf.pdf?src=1&mid=9340&bid=8158"


def test_entrada_sem_pdf_e_sem_entrega_tem_motivo():
    itens = partidos.parse_pagina_ano(PAGINA_2024, 2024)["secoes"][0]["itens"]
    pctp = next(item for item in itens if item["partido_sigla"] == "PCTP/MRPP")
    assert pctp["entregou"] is False
    assert pctp["documento"] is False
    assert pctp["motivo"] == "Não entregou"
    assert pctp["partido_nome"] == "Partido Comunista dos Trabalhadores Portugueses"


def test_observacao_sai_da_sigla_e_do_nome():
    itens = partidos.parse_pagina_ano(PAGINA_2024, 2024)["secoes"][0]["itens"]
    retificada = next(item for item in itens if item["observacao"] == "retificadas em 9/11/2012")
    assert retificada["partido_sigla"] == "PCP"
    assert retificada["entregou"] is True

    contas = partidos.parse_pagina_ano(PAGINA_2024, 2024)["secoes"][1]["itens"]
    versao = next(item for item in contas if item["observacao"] and "8.06.2022" in item["observacao"])
    assert versao["partido_sigla"] == "PCP"
    assert versao["partido_nome"] == "Partido Comunista Português"


def test_notas_da_seccao_nao_se_confundem_com_partidos():
    analise = partidos.parse_pagina_ano(PAGINA_2024, 2024)
    notas = [item for secao in analise["secoes"] for item in secao["itens"] if item["nota"]]
    assert len(notas) == 2
    assert all(nota["partido_chave"] is None and nota["entregou"] is None for nota in notas)
    assert "artigo 26.º" in notas[1]["texto"]


def test_sigla_que_e_prosa_vira_documento_agregado():
    """«Deputado independente na ALRAM» não é uma sigla: a entrada fica agregada."""
    contas = partidos.parse_pagina_ano(PAGINA_2024, 2024)["secoes"][1]["itens"]
    agregado = next(item for item in contas if item["agregado"])
    assert agregado["partido_chave"] is None
    assert agregado["documento"] is True
    assert "Deputado independente" in (agregado["observacao"] or agregado["partido_nome"])


def test_sigla_composta_mantem_se():
    """«CDS - PP» é a sigla que o TC publicou — não se parte ao meio."""
    contas = partidos.parse_pagina_ano(PAGINA_2024, 2024)["secoes"][1]["itens"]
    cds = next(item for item in contas if item["partido_chave"] == "CDSPP")
    assert cds["partido_sigla"] == "CDS - PP"
    assert cds["partido_nome"] == "CDS - Partido Popular"


def test_sigla_derivada_do_nome_quando_o_span_falta():
    """Em 2008 o TC escreve «PCP - Partido Comunista Português», sem `<span>`."""
    pagina = _pagina(
        _secao(
            "1111",
            "Contas Anuais dos Partidos Políticos referentes ao ano de 2008",
            [_entrada("PCP - Partido Comunista Português", href="file/PCP.pdf?src=1")],
        )
    )
    item = partidos.parse_pagina_ano(pagina, 2008)["secoes"][0]["itens"][0]
    assert item["partido_sigla"] == "PCP"
    assert item["partido_nome"] == "Partido Comunista Português"
    assert item["partido_chave"] == "PCP"


def test_span_com_prosa_e_nota_e_nao_partido():
    """O acórdão de 2008 põe a publicação em `<span class="links">`, sem partido."""
    pagina = _pagina(
        _secao(
            "1114",
            "Acórdãos sobre as contas anuais dos partidos políticos",
            [_entrada(sigla="[Publicado no Diário da República n.º 94/2015, Série II, de 15 de maio]")],
        )
    )
    item = partidos.parse_pagina_ano(pagina, 2008)["secoes"][0]["itens"][0]
    assert item["nota"] is True
    assert item["partido_chave"] is None
    assert "Diário da República" in item["texto"]


def test_agregado_da_lista_de_accoes_sem_chave_de_partido():
    pagina = _pagina(
        _secao(
            "1104",
            "Lista de ações e meios por partido político",
            [
                _nota("Listas de ações por força política"),
                _entrada("Lista de ações por força política, referentes ao ano de 2008", href="file/ListaAcoesEMeios2008.pdf"),
            ],
        )
    )
    item = partidos.parse_pagina_ano(pagina, 2008)["secoes"][0]["itens"][1]
    assert item["agregado"] is True
    assert item["partido_chave"] is None
    assert item["documento"] is True


def test_secção_desconhecida_usa_slug_do_titulo():
    pagina = _pagina(_secao("9999", "Relatórios da ECFP", [_entrada("Ergue-te", sigla="E")]))
    secao = partidos.parse_pagina_ano(pagina, 2020)["secoes"][0]
    assert secao["secao"] == "relatorios-da-ecfp"


def test_anos_na_pagina_indice():
    html = (
        '<a href="contas_eleicoes-partidos-2025.html">2025</a>'
        '<a href="contas_eleicoes-partidos-2024.html">2024</a>'
        '<a href="contas_eleicoes-partidos-2004.html">2004</a>'
        '<a href="contas_eleicoes-fp_acordaos_arquivo.html">Arquivo</a>'
    )
    assert partidos.anos_na_pagina_indice(html) == [2004, 2024, 2025]


# ---------------------------------------------------------------------------
# Chaves e nomes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [
        ("PCP", "PCP"),
        ("CDS-PP", "CDSPP"),
        ("PPD/PSD", "PPDPSD"),
        ("B.E.", "BE"),
        ("A)T", "AT"),
        ("Bloco de Esquerda", "BLOCODEESQUERDA"),
    ],
)
def test_chave_partido(valor, esperado):
    assert partidos._chave_partido(valor) == esperado


def test_chaves_partido_inclui_sub_tokens_da_sigla():
    """«CDS-PP» tem de encontrar o «CDS» que a página de 2008 publica."""
    assert partidos._chaves_partido("CDS-PP") == ["CDSPP", "CDS", "PP"]
    assert partidos._chaves_partido("B.E.") == ["BE"]


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [
        ("PCP", True),
        ("PPD/PSD", True),
        ("B.E.", True),
        ("A)T", True),
        ("Ergue-te", True),
        ("L", True),
        ("", False),
        ("Decisão da ECFP", False),
        ("Partido da Terra", False),
        ("Nós, Cidadãos!", False),
        ("Deputado independente na ALRAM", False),
        ("Contas apresentadas fora de prazo", False),
    ],
)
def test_parece_sigla(valor, esperado):
    assert partidos._parece_sigla(valor) is esperado


@pytest.mark.parametrize(
    ("valor", "base", "notas"),
    [
        ("PCP (não comunicou)", "PCP", ["não comunicou"]),
        ("PCP [versão retificada em 8.06.2022 (a pedido do partido)]", "PCP", ["versão retificada em 8.06.2022 (a pedido do partido)"]),
        ("PAN (Retificadas em 03-04-2014", "PAN", ["Retificadas em 03-04-2014"]),
        ('PPD/PSD "Retificou em 13/04/2016"', "PPD/PSD", ["Retificou em 13/04/2016"]),
        ("PXXI - Contas entregues fora de prazo", "PXXI", ["Contas entregues fora de prazo"]),
        ("CDS - PP", "CDS - PP", []),
    ],
)
def test_separar_notas(valor, base, notas):
    assert partidos._separar_notas(valor) == (base, notas)


# ---------------------------------------------------------------------------
# Registo da CNE
# ---------------------------------------------------------------------------

CNE_LISTA = """
<h3>Contactos dos partidos políticos</h3>
<p>Disponibilizam-se elementos sobre os partidos políticos atualmente inscritos e
os partidos já extintos.</p>
Inscritos
<table class="views-table cols-4">
  <thead><tr><th>Denominação</th><th>Símbolo</th><th>Sigla</th><th>Data da inscrição</th></tr></thead>
  <tbody>
    <tr>
      <td><a href="/partido/partido-comunista-portugues" target="_blank">Partido Comunista Português</a></td>
      <td><a href="/partido/partido-comunista-portugues"><img src="/sites/default/files/partido1_0.png" /></a></td>
      <td>PCP</td>
      <td><span content="1974-12-26T00:00:00+01:00">26/12/1974</span></td>
    </tr>
    <tr>
      <td><a href="/partido/partido-socialista" target="_blank">Partido Socialista</a></td>
      <td><a href="/partido/partido-socialista"><img src="/sites/default/files/partido4_0.png" /></a></td>
      <td>PS</td>
      <td><span content="1975-02-01T00:00:00+01:00">01/02/1975</span></td>
    </tr>
  </tbody>
</table>
<h3>Extintos</h3>
<table class="views-table cols-4">
  <thead><tr><th>Denominação</th><th>Símbolo</th><th>Sigla</th><th>Data da inscrição</th></tr></thead>
  <tbody>
    <tr>
      <td><a href="/partido/nova-democracia" target="_blank">Nova Democracia</a></td>
      <td><a href="/partido/nova-democracia"><img src="/sites/default/files/nd.png" /></a></td>
      <td>PND</td>
      <td></td>
    </tr>
  </tbody>
</table>
"""

CNE_FICHA = """
<h1 class="title">Partido Socialista</h1>
<div class="field field-name-title field-type-ds field-label-inline clearfix">
  <div class="field-label">Denominação:&nbsp;</div>
  <div class="field-items"><div class="field-item even" property="dc:title">Partido Socialista</div></div>
</div>
<div class="field field-name-field-pp-sigla field-type-text field-label-inline clearfix">
  <div class="field-label">Sigla:&nbsp;</div>
  <div class="field-items"><div class="field-item even">PS</div></div>
</div>
<div class="field field-name-field-http field-type-link-field field-label-inline clearfix">
  <div class="field-label">Sítio na Internet:&nbsp;</div>
  <div class="field-items"><div class="field-item even"><a href="https://www.ps.pt">https://www.ps.pt</a></div></div>
</div>
<div class="field field-name-body field-type-text-with-summary field-label-hidden">
  <div class="field-items"><div class="field-item even" property="content:encoded">
    <p>Fundado em 19 de Abril de 1973.</p>
    <p>Inscrito no Supremo Tribunal de Justiça em 1 de Fevereiro de 1975.</p>
  </div></div>
</div>
<div class="field field-name-field-pp-logo field-type-image field-label-hidden">
  <div class="field-items"><div class="field-item even"><a href="/sites/default/files/ps.png"><img src="/sites/default/files/ps.png" /></a></div></div>
</div>
"""


def test_cne_lista_separa_inscritos_de_extintos():
    lista = partidos.parse_cne_lista(CNE_LISTA)
    assert [item["denominacao"] for item in lista["inscritos"]] == ["Partido Comunista Português", "Partido Socialista"]
    assert [item["situacao"] for item in lista["inscritos"]] == ["inscrito", "inscrito"]
    assert [item["denominacao"] for item in lista["extintos"]] == ["Nova Democracia"]
    assert lista["extintos"][0]["situacao"] == "extinto"
    assert lista["extintos"][0]["data_inscricao"] is None


def test_cne_lista_le_sigla_data_logotipo_e_url():
    inscritos = partidos.parse_cne_lista(CNE_LISTA)["inscritos"]
    assert inscritos[0]["sigla"] == "PCP"
    assert inscritos[0]["data_inscricao"] == "1974-12-26"
    assert inscritos[0]["logotipo_url"] == "https://www.cne.pt/sites/default/files/partido1_0.png"
    assert inscritos[0]["url"] == "https://www.cne.pt/partido/partido-comunista-portugues"


def test_cne_ficha_do_partido():
    ficha = partidos.parse_cne_partido(CNE_FICHA)
    assert ficha["denominacao"] == "Partido Socialista"
    assert ficha["sigla"] == "PS"
    assert ficha["site"] == "https://www.ps.pt"
    assert ficha["logotipo_url"] == "https://www.cne.pt/sites/default/files/ps.png"
    assert "Fundado em 19 de Abril de 1973." in ficha["descricao"]
    assert "Inscrito no Supremo Tribunal de Justiça" in ficha["descricao"]


# ---------------------------------------------------------------------------
# Recolha para JSONL e manifesto
# ---------------------------------------------------------------------------


@pytest.fixture()
def pasta(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Pasta do módulo isolada, com a página-índice já em disco (sem rede)."""
    monkeypatch.setenv(partidos.DATA_DIR_ENV, str(tmp_path))
    (tmp_path / "paginas").mkdir(parents=True, exist_ok=True)
    (tmp_path / "paginas" / "indice.html").write_text(
        '<a href="contas_eleicoes-partidos-2024.html">2024</a>', encoding="utf-8"
    )
    (tmp_path / "paginas" / "2024.html").write_text(PAGINA_2024, encoding="utf-8")
    return tmp_path


def test_recolher_escreve_jsonl_e_manifesto(pasta: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        partidos,
        "_pdf_do_documento",
        lambda href, ano, **kw: {
            "ficheiro": Path(href).name,
            "pdf_bytes": 1024,
            "pdf_sha256": "abc",
            "paginas": None,
            "texto": "",
            "erro": None,
        },
    )
    resultado = partidos.recolher([2024], com_cne=False)
    assert resultado["anos_lidos"] == 1
    resumo = resultado["anos"]["2024"]
    assert resumo["itens"] == 9
    assert resumo["notas"] == 2
    assert resumo["documentos"] == 5
    assert resumo["partidos"] == 4  # PCP, PCTP/MRPP, PS e CDS-PP (notas e agregado ficam de fora)
    assert resumo["sem_documento"] == 2  # PCTP/MRPP e o PCP retificado só na lista de 2024

    jsonl = pasta / "_normalized" / "tc-2024.jsonl"
    linhas = [json.loads(linha) for linha in jsonl.read_text(encoding="utf-8").splitlines()]
    assert len(linhas) == 9
    assert {linha["ano"] for linha in linhas} == {2024}
    ids = [linha["doc_id"] for linha in linhas]
    assert len(ids) == len(set(ids))
    assert all(linha["secao"] in ("lista_acoes", "contas_anuais") for linha in linhas)

    manifesto = partidos.read_manifest()
    assert manifesto["anos"]["2024"]["itens"] == 9
    assert manifesto["anos"]["2024"]["jsonl"] == "tc-2024.jsonl"


def test_amostra_do_ano_lido(pasta: Path):
    partidos.recolher([2024], com_pdf=False, com_cne=False)
    amostra = partidos.amostra(2024, limite=3)
    assert amostra["total"] == 9
    assert len(amostra["items"]) == 3
    assert amostra["items"][0]["texto_extraido"] is False


def test_meta_conta_o_que_esta_em_disco(pasta: Path):
    partidos.recolher([2024], com_pdf=False, com_cne=False)
    dados = partidos.meta()
    assert dados["anos_recolhidos"] == 1
    assert dados["anos_em_disco"] == [2024]
    assert dados["itens"] == 9
    assert dados["anos"][0]["ano"] == 2024
    assert dados["anos"][0]["url"].endswith("contas_eleicoes-partidos-2024.html")


def test_ficheiros_lista_paginas_e_jsonl(pasta: Path):
    partidos.recolher([2024], com_pdf=False, com_cne=False)
    dados = partidos.ficheiros()
    assert "2024.html" in dados["paginas"]
    assert dados["jsonl"][0]["ficheiro"] == "tc-2024.jsonl"
    assert dados["pdf_total"] == 0


def test_recolher_ano_desconhecido_nao_estoura(pasta: Path):
    """Pedir um ano que não está publicado não vira «recolhe tudo»."""
    resultado = partidos.recolher([1999], com_pdf=False, com_cne=False)
    assert resultado["anos"] == {}
    assert resultado["anos_lidos"] == 0
    assert resultado["ignorados"] == [1999]
    assert resultado["errors"] and "1999" in resultado["errors"][0]["error"]


def test_guarda_do_caminho_do_pdf(pasta: Path):
    with pytest.raises(ValueError):
        partidos.caminho_documento(2024, "../fora.pdf")
    with pytest.raises(ValueError):
        partidos.caminho_documento(2024, "sub/pasta.pdf")
    caminho = partidos.caminho_documento(2024, "conta.pdf")
    assert caminho.parent.name == "2024"


def test_fontes_descrevem_as_duas_origens():
    dados = partidos.fontes()
    ids = [fonte["id"] for fonte in dados["fontes"]]
    assert ids == ["tc", "cne"]
    assert "finance_partidos" in dados["indices"]
    secoes = {secao["id"] for secao in dados["fontes"][0]["secoes"]}
    assert secoes == {"lista_acoes", "contas_anuais", "relatorios_ecfp", "acordaos", "decisoes_ecfp"}


# ---------------------------------------------------------------------------
# Trabalhos em segundo plano
# ---------------------------------------------------------------------------


def test_start_job_recusa_tipo_desconhecido():
    with pytest.raises(ValueError):
        partidos.start_job("apagar")


def test_job_status_de_desconhecido(pasta: Path):
    assert partidos.job_status("nao-existe") is None


def test_start_job_recolher_arranca_e_termina(pasta: Path, monkeypatch: pytest.MonkeyPatch):
    """O trabalho corre em segundo plano e o progresso fica consultável."""
    monkeypatch.setattr(partidos, "_pdf_do_documento", lambda href, ano, **kw: None)
    job = partidos.start_job("recolher", {"anos": [2024], "com_pdf": False, "com_cne": False})
    assert job["tipo"] == "recolher"
    assert job["status"] == "running"

    for _ in range(200):
        atual = partidos.job_status(job["job_id"])
        if atual and atual["status"] != "running":
            break
        import time

        time.sleep(0.05)
    atual = partidos.job_status(job["job_id"])
    assert atual["status"] == "done"
    assert atual["result"]["anos_lidos"] == 1
    assert atual["progress"]["phase"] == "concluído"
    assert partidos.list_jobs()["total"] >= 1


# ---------------------------------------------------------------------------
# PDF: MarkItDown (Markdown com tabelas) e recurso ao PyMuPDF
# ---------------------------------------------------------------------------


def _pdf_com_tabela(linhas: list[list[str]]) -> bytes:
    """PDF sintético com uma tabela simples (células alinhadas em colunas)."""
    import pymupdf

    documento = pymupdf.open()
    pagina = documento.new_page()
    altura = 60
    for indice, linha in enumerate(linhas):
        for coluna, celula in enumerate(linha):
            pagina.insert_text((60 + coluna * 130, altura + indice * 16), celula, fontsize=10)
    conteudo = documento.tobytes()
    documento.close()
    return conteudo


def _pdf_sem_texto() -> bytes:
    """PDF de uma página em branco: é o que uma digitalização dá sem OCR."""
    import pymupdf

    documento = pymupdf.open()
    documento.new_page()
    conteudo = documento.tobytes()
    documento.close()
    return conteudo


def test_extrair_documento_pdf_usa_o_markdown_do_markitdown():
    pytest.importorskip("markitdown")
    linhas = [
        ["Ação", "Gasto", "Fornecedor"],
        ["Povo Livre Digital", "492,00", "CodeWrite"],
    ]
    extraido = partidos.extrair_documento_pdf(_pdf_com_tabela(linhas))
    assert extraido["texto_metodo"] == partidos.METODO_MARKITDOWN
    assert extraido["digitalizado"] is False
    assert "Povo Livre Digital" in extraido["texto"]
    assert "CodeWrite" in extraido["texto"]


def test_extrair_documento_pdf_recorre_ao_pymupdf_quando_o_markitdown_falha(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        partidos,
        "extrair_markdown_pdf",
        lambda conteudo, **kw: {"texto": "", "truncado": False, "error": "MissingDependencyException: pdf"},
    )
    extraido = partidos.extrair_documento_pdf(_pdf_com_tabela([["Povo Livre Digital", "492,00"]]))
    assert extraido["texto_metodo"] == partidos.METODO_PYMUPDF
    assert "Povo Livre Digital" in extraido["texto"]
    assert extraido["digitalizado"] is False


def test_extrair_documento_pdf_sem_texto_fica_marcado_para_ocr(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        partidos,
        "extrair_markdown_pdf",
        lambda conteudo, **kw: {"texto": "", "truncado": False, "error": None},
    )
    extraido = partidos.extrair_documento_pdf(_pdf_sem_texto())
    assert extraido["texto_metodo"] == partidos.METODO_SEM_TEXTO
    assert extraido["texto"] == ""
    assert extraido["digitalizado"] is True
    assert extraido["paginas"] == 1


def test_extrair_documento_pdf_traz_o_numero_de_paginas(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        partidos,
        "extrair_markdown_pdf",
        lambda conteudo, **kw: {"texto": "| a | b |", "truncado": False, "error": None},
    )
    extraido = partidos.extrair_documento_pdf(_pdf_sem_texto())
    assert extraido["paginas"] == 1
    assert extraido["texto_metodo"] == partidos.METODO_MARKITDOWN


def test_documento_indexado_regista_o_metodo_e_a_falta_de_ocr():
    item = {"ordem": 1, "partido_chave": "PPDPSD", "partido_nome": "Partido Social Democrata", "entregou": True}
    documento = partidos._documento_do_item(
        item,
        ano=2025,
        secao="lista_acoes",
        secao_titulo="Lista de ações e meios de propaganda política",
        ancora="1104",
        pagina_url="https://www.tribunalconstitucional.pt/tc/contas_eleicoes-partidos-2025.html",
        recolhido_em="2026-01-01T00:00:00Z",
        dados_pdf={
            "ficheiro": "11_CA2025_PSD_ListaAM_vf.pdf",
            "pdf_bytes": 434001,
            "pdf_sha256": "abc",
            "paginas": 100,
            "texto": "| Ação | Gasto |\n| --- | --- |\n| Povo Livre Digital | 492,00 |",
            "texto_metodo": partidos.METODO_MARKITDOWN,
            "digitalizado": False,
        },
    )
    assert documento["texto_metodo"] == partidos.METODO_MARKITDOWN
    assert documento["texto_extraido"] is True
    assert documento["pdf_digitalizado"] is False
    assert documento["precisa_ocr"] is False

    digitalizado = partidos._documento_do_item(
        {**item, "ordem": 2},
        ano=2025,
        secao="contas_anuais",
        secao_titulo="Contas anuais dos partidos políticos",
        ancora="1111",
        pagina_url="https://www.tribunalconstitucional.pt/tc/contas_eleicoes-partidos-2025.html",
        recolhido_em="2026-01-01T00:00:00Z",
        dados_pdf={
            "ficheiro": "4_CA2025_PCP_Bal_DR_vf.pdf",
            "pdf_bytes": 574000,
            "pdf_sha256": "def",
            "paginas": 6,
            "texto": "",
            "texto_metodo": partidos.METODO_SEM_TEXTO,
            "digitalizado": True,
        },
    )
    assert digitalizado["texto_extraido"] is False
    assert digitalizado["pdf_digitalizado"] is True
    assert digitalizado["precisa_ocr"] is True


def test_markdown_do_documento_le_o_texto_indexado(pasta: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        partidos,
        "_pdf_do_documento",
        lambda href, ano, **kw: {
            "ficheiro": partidos._ficheiro_do_href(href) or "x.pdf",
            "pdf_bytes": 1234,
            "pdf_sha256": "abc",
            "paginas": 3,
            "texto": "| Ação | Gasto |",
            "texto_metodo": partidos.METODO_MARKITDOWN,
            "digitalizado": False,
            "erro": None,
        },
    )
    partidos.recolher([2024], com_pdf=True, com_cne=False)
    dados = partidos.markdown_do_documento(2024, "4_CA2025_PCP_ListaAM_vf.pdf")
    assert dados["metodo"] == partidos.METODO_MARKITDOWN
    assert dados["markdown"] == "| Ação | Gasto |"
    assert dados["precisa_ocr"] is False
    assert dados["partido_sigla"] == "PCP"


def test_markdown_do_documento_converte_o_pdf_quando_o_ano_nao_foi_lido(pasta: Path):
    destino = partidos.pdf_dir(2024) / "conta.pdf"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(_pdf_com_tabela([["Povo Livre Digital", "492,00"]]))
    dados = partidos.markdown_do_documento(2024, "conta.pdf")
    assert dados["ficheiro"] == "conta.pdf"
    assert dados["metodo"] in (partidos.METODO_MARKITDOWN, partidos.METODO_PYMUPDF)
    assert "Povo Livre Digital" in dados["markdown"]


def test_markdown_do_documento_inexistente(pasta: Path):
    with pytest.raises(FileNotFoundError):
        partidos.markdown_do_documento(2024, "nao-existe.pdf")
    with pytest.raises(ValueError):
        partidos.markdown_do_documento(2024, "../fora.pdf")
