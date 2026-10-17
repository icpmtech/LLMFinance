"""Artigo «2025 contra 2026»: comparação dos dois anos em valores absolutos.

O que se prova aqui:

* o artigo compara **o mesmo período de cada ano** e não apresenta o ano de 2025
  fechado como se fosse comparável com o que 2026 tem até 10 de outubro;
* cada gráfico compara os dois anos em **euros absolutos**, com duas séries na
  mesma escala e legenda, e cita a fonte;
* as séries de CPV e de empresas trazem os valores dos dois anos — é isso que
  torna o gráfico uma comparação e não um retrato;
* o artigo tem **metadados de SEO** próprios (título, descrição e palavras-chave)
  diferentes do título visível;
* os números das séries são os mesmos que os textos citam.

Nada aqui toca em `data/`: o CMS vive em `tmp_path`.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

import pytest

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from api import cms_editorial  # noqa: E402
from api import cms_post_report  # noqa: E402
from api import cms_render  # noqa: E402
from api import cms_store  # noqa: E402


@pytest.fixture()
def instalacao(tmp_path, monkeypatch):
    """CMS isolado em `tmp_path` (sem ler nem escrever em `data/`)."""
    cms = tmp_path / "cms"
    monkeypatch.setattr(cms_store, "CMS_DIR", cms)
    monkeypatch.setattr(cms_store, "CMS_PATH", cms / "cms.json")
    monkeypatch.setattr(cms_store, "MEDIA_DIR", cms / "media")
    monkeypatch.setattr(cms_store, "_cache", None)
    monkeypatch.setattr(cms_store, "_cache_mtime", None)
    yield


def _blocos(post: Dict[str, Any], tipo: str):
    return [bloco for bloco in post["blocks"] if bloco["type"] == tipo]


def _post(instalacao) -> Dict[str, Any]:
    post = cms_store.resolve_post_by_slug(cms_editorial.ARTIGO_2025_2026_SLUG, published_only=False)
    assert post is not None
    return post


# ------------------------------------------------------------------ helper
def test_variacao_escreve_o_sinal_e_o_caso_de_quem_nao_voltou():
    assert cms_editorial._variacao(100.0, 50.0) == "\u221250,0%"  # noqa: SLF001
    assert cms_editorial._variacao(100.0, 150.0) == "+50,0%"  # noqa: SLF001
    assert cms_editorial._variacao(100.0, 0.0) == "não voltou a contratar"  # noqa: SLF001


def test_euros_escreve_a_grandeza_por_extenso():
    assert cms_editorial._euros(3_193_728_479.26) == "3,19 mil M€"  # noqa: SLF001
    assert cms_editorial._euros(728_242_832.13) == "728,2 M€"  # noqa: SLF001


# ------------------------------------------------------------------ artigo
def test_artigo_existe_publicado_com_resumo_e_seo(instalacao):
    post = _post(instalacao)
    assert post["title"] == "2025 contra 2026: mais contratos, menos dinheiro"
    assert post["status"] == "publicado"
    assert post["slug"] == "contratos-publicos-2025-vs-2026"

    markdown = post["markdown"]
    for marca in ("192 941", "173 830", "11,0%", "16,36", "17,41", "15,3%", "\u22126,0%"):
        assert marca in markdown, marca
    assert "três leituras" in markdown

    # SEO próprio, diferente do título visível — é o que aparece na pesquisa.
    seo = post["seo"]
    assert seo["title"] and seo["title"] != post["title"]
    assert "2025" in seo["title"] and "2026" in seo["title"]
    assert len(seo["description"]) >= 120
    assert "contratos públicos 2025" in seo["keywords"]
    assert seo["noindex"] is False


def test_artigo_compara_e_nao_retrata(instalacao):
    """Comparar obriga a duas séries: 2025 **e** 2026 em cada gráfico."""
    post = _post(instalacao)
    graficos = _blocos(post, "grafico")
    assert len(graficos) >= 4  # valor total, CPV, empresas, compradores

    for bloco in graficos:
        data = bloco["data"]
        assert data["format"] == "euros", bloco["id"]
        assert data.get("source"), bloco["id"]
        assert all(item.get("value") is not None for item in data["series"]), bloco["id"]
        # Os gráficos comparativos trazem o segundo ano e a legenda que o nomeia.
        if data.get("legend"):
            assert data["legend"] == ["2025", "2026"], bloco["id"]
            assert any("value2" in item for item in data["series"]), bloco["id"]

    comparativos = [bloco for bloco in graficos if bloco["data"].get("legend")]
    assert len(comparativos) >= 3  # CPV, empresas e compradores


def test_series_de_cpv_e_de_empresas_cobrem_os_dois_anos(instalacao):
    post = _post(instalacao)
    cpv = next(bloco for bloco in _blocos(post, "grafico") if "CPV" in bloco["data"]["title"])
    series = {item["label"]: item for item in cpv["data"]["series"]}
    assert len(series) == len(cms_editorial._CPV_2025_2026) == 12  # noqa: SLF001
    farmacia = series["Produtos farmacêuticos (3360)"]
    assert farmacia["value"] == 2_625_427_553.97 and farmacia["value2"] == 2_598_184_999.77
    assert farmacia["note"] == "\u22121,0%"

    empresas = next(bloco for bloco in _blocos(post, "grafico") if "empresas" in bloco["data"]["title"])
    por_nome = {item["label"]: item for item in empresas["data"]["series"]}
    avanc = por_nome["AVAN Norte — Gestão da Ferrovia de Alta Velocidade"]
    # Sem contratos em 2026 não há segunda barra nem um zero desenhado.
    assert avanc["value"] == 1_661_362_811.55 and "value2" not in avanc
    assert avanc["note"] == "não voltou a contratar"


def test_tabelas_trazem_os_dois_anos_e_a_variacao(instalacao):
    post = _post(instalacao)
    cpv = next(bloco for bloco in _blocos(post, "tabela") if bloco["data"]["head"][0] == "CPV")
    assert cpv["data"]["head"] == ["CPV", "Classe", "Contr. 2025", "Valor 2025", "Contr. 2026", "Valor 2026", "Variação"]
    assert len(cpv["data"]["rows"]) == 12
    linha = next(linha for linha in cpv["data"]["rows"] if linha[0] == "4523")
    assert linha[2] == "5208" and linha[3] == "3,19 mil M€"
    assert linha[4] == "2723" and linha[5] == "1,35 mil M€"
    assert linha[6] == "\u221257,8%"

    empresas = next(bloco for bloco in _blocos(post, "tabela") if bloco["data"]["head"][0].startswith("Empresa"))
    assert len(empresas["data"]["rows"]) == len(cms_editorial._EMPRESAS_2025_2026)  # noqa: SLF001
    for linha in empresas["data"]["rows"]:
        assert len(linha) == len(empresas["data"]["head"])

    compradores = next(bloco for bloco in _blocos(post, "tabela") if bloco["data"]["head"][0].startswith("Entidade"))
    assert compradores["data"]["rows"][0][0] == "Infraestruturas de Portugal"
    assert compradores["data"]["rows"][0][4] == "1,03 mil M€"


def test_artigo_tem_caixa_de_numeros_aviso_e_aviso_de_metodo(instalacao):
    post = _post(instalacao)
    tipos = [bloco["type"] for bloco in post["blocks"]]
    assert "numeros" in tipos and "aviso" in tipos and "cta" in tipos
    assert tipos.count("texto") >= 4  # uma leitura por secção

    numeros = next(bloco for bloco in _blocos(post, "numeros"))
    valores = {item["value"] for item in numeros["data"]["items"]}
    assert "192 941" in valores and "16,36 mil M€" in valores

    aviso = next(bloco for bloco in _blocos(post, "aviso"))
    assert "mesmo intervalo de calendário" in aviso["data"]["text"]
    assert "euros absolutos" in aviso["data"]["text"]


def test_pagina_do_artigo_desenha_barras_e_tem_pdf(instalacao):
    post = _post(instalacao)
    html = cms_render.render_post(post, settings=cms_store.get_settings())
    assert 'class="grafico-lista"' in html
    barras = sum(len(bloco["data"]["series"]) for bloco in _blocos(post, "grafico"))
    assert html.count('class="grafico-item"') == barras
    assert "tabela-rolavel" in html
    assert f'/site/blog/{cms_editorial.ARTIGO_2025_2026_SLUG}/pdf" download' in html
    # Os dois anos estão nomeados no gráfico, não só nas barras.
    assert "grafico-legenda" in html


# --------------------------------------------------------------- migracao
def _sem_o_artigo_na_instalacao(instalacao) -> None:
    """Tira o artigo da instalação — é o que uma instalação em uso tem a menos."""
    cms_store._load()  # noqa: SLF001 - força a semente antes de apagar
    cms_store.delete_item("posts", "post_contratos_2025_2026", "teste")
    assert cms_store.resolve_post_by_slug(cms_editorial.ARTIGO_2025_2026_SLUG, published_only=False) is None


def test_script_de_migracao_cria_o_artigo_numa_instalacao_em_uso(instalacao):
    """O deploy não leva a pasta `data/`: é o script de migração que publica o artigo."""
    import _atualizar_site_sabemos as migracao

    _sem_o_artigo_na_instalacao(instalacao)
    media = cms_store.instalar_media_de_marca()
    migracao._aplicar_posts(media)  # noqa: SLF001

    post = _post(instalacao)
    assert post["status"] == "publicado"
    assert post["slug"] == cms_editorial.ARTIGO_2025_2026_SLUG
    assert post["seo"]["title"] == cms_editorial.ARTIGO_2025_2026_SEO["title"]
    assert len(post["blocks"]) == len(cms_editorial.artigo_contratos_2025_2026()["blocks"])
    assert post["reading_minutes"] > 0
    # O artigo de 2026 continua a ser publicado pelo mesmo caminho.
    assert cms_store.resolve_post_by_slug(cms_editorial.ARTIGO_CONTRATOS_2026_SLUG, published_only=False)


def test_script_de_migracao_nao_volta_a_gravar_o_que_esta_igual(instalacao, capsys):
    import _atualizar_site_sabemos as migracao

    _sem_o_artigo_na_instalacao(instalacao)
    media = cms_store.instalar_media_de_marca()
    migracao._aplicar_posts(media)  # noqa: SLF001
    assert "artigo contratos-publicos-2025-vs-2026: criado" in capsys.readouterr().out

    migracao._aplicar_posts(media)  # noqa: SLF001
    saida = capsys.readouterr().out
    assert saida.count("já estava atualizado") >= 2
    assert "criado" not in saida


def test_seccoes_do_relatorio_saem_dos_blocos(instalacao):
    post = _post(instalacao)
    secoes = cms_post_report.artigo_seccoes(post, cms_store.get_settings())
    titulos = [secao["title"] for secao in secoes]
    assert any(titulo.startswith("As áreas de CPV") for titulo in titulos)
    assert any(titulo.startswith("As empresas adjudicatárias") for titulo in titulos)

    cpv = next(secao for secao in secoes if secao["title"].startswith("As áreas de CPV"))
    assert cpv["columns"] == ["Item", "2025", "2026", "Nota"]
    assert cpv["rows"][2][0].startswith("Produtos farmacêuticos")
    assert all(len(linha) == len(cpv["columns"]) for linha in cpv["rows"])
