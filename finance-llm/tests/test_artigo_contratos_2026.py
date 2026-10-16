"""Artigo «Contratos públicos em 2026»: resumo, gráficos, tabelas e PDF.

O que se prova aqui:

* o **bloco `grafico`** desenha barras horizontais em HTML/CSS (uma ou duas
  séries na mesma escala), escreve sempre o valor por extenso e não inventa uma
  barra a zero quando a segunda série não existe;
* o bloco está no **catálogo do CMS**, que é o que faz aparecer o editor no
  painel sem mais nenhuma alteração;
* o **artigo** tem resumo, gráficos e tabelas, e os números que publica são os
  mesmos que as fontes citadas;
* o **relatório PDF** (`/site/blog/{slug}/pdf`) sai do próprio artigo — secções
  a partir dos blocos, sem uma segunda cópia dos números — e é **opcional por
  artigo** (`report_pdf`);
* a **partilha** da página usa a Web Share API do sistema (com o endereço
  absoluto do artigo) e o botão só aparece se o browser souber partilhar ou
  copiar.

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


# ------------------------------------------------------------------- bloco
def test_bloco_de_grafico_desenha_barras_com_o_valor_escrito():
    html = cms_render._render_block(  # noqa: SLF001 - o bloco é o objeto do teste
        {
            "type": "grafico",
            "data": {
                "title": "Onde está o valor",
                "note": "Dez maiores, 2026",
                "format": "euros",
                "series": [
                    {"label": "Maior", "value": 100_000_000, "note": "10 contratos"},
                    {"label": "Metade", "value": 50_000_000},
                ],
                "source": "Fonte: base de contratos.",
            },
        }
    )
    assert 'class="grafico-lista"' in html and html.count('class="grafico-item"') == 2
    # A barra é proporcional ao maior valor, e o valor vai escrito (leitor de ecrã).
    assert 'style="width:100%"' in html and 'style="width:50%"' in html
    assert "100,0 M€" in html and "50,0 M€" in html
    assert "10 contratos" in html and "Fonte: base de contratos." in html
    # Sem segundo valor não há segunda barra nem legenda.
    assert "grafico-barra secundaria" not in html and "grafico-legenda" not in html


def test_bloco_de_grafico_com_duas_series_na_mesma_escala():
    html = cms_render._render_block(  # noqa: SLF001
        {
            "type": "grafico",
            "data": {
                "title": "Peso no número e no valor",
                "format": "percentagem",
                "legend": ["Contratos", "Valor"],
                "series": [
                    {"label": "Ajuste direto", "value": 41.9, "value2": 16.6},
                    {"label": "Concurso público", "value": 15.8, "value2": 47.9},
                ],
            },
        }
    )
    assert '<li class=""><span class="grafico-ponto"></span>Contratos</li>' in html
    assert '<li class="secundaria"><span class="grafico-ponto"></span>Valor</li>' in html
    # As duas séries partilham a escala: 47,9% é o máximo de ambas.
    assert 'style="width:100%"' in html and 'style="width:33%"' in html
    assert "41,9 %" in html and "16,6 %" in html


def test_bloco_de_grafico_sem_numeros_nao_desenha_nada():
    assert cms_render._render_block({"type": "grafico", "data": {}}) == ""  # noqa: SLF001
    assert cms_render._render_block({"type": "grafico", "data": {"series": [{"label": "x", "value": ""}]}}) == ""  # noqa: SLF001


def test_bloco_de_grafico_le_valores_em_texto_a_portuguesa():
    html = cms_render._render_block(  # noqa: SLF001
        {"type": "grafico", "data": {"format": "numero", "series": [{"label": "A", "value": "1 234,5"}]}}
    )
    assert "1 234" in html or "1 235" in html


def test_grafico_esta_no_catalogo_do_cms(instalacao):
    """O catálogo é o que faz aparecer o editor do bloco no painel."""
    assert "grafico" in cms_store.BLOCK_IDS
    tipo = next(item for item in cms_store.BLOCK_TYPES if item["id"] == "grafico")
    assert tipo["label"] == "Gráfico" and tipo["hint"]


# ------------------------------------------------------------------- artigo
def test_artigo_tem_resumo_graficos_e_tabelas(instalacao):
    post = cms_store.resolve_post_by_slug(cms_editorial.ARTIGO_CONTRATOS_2026_SLUG, published_only=False)
    assert post is not None
    assert post["title"] == "Contratos públicos em 2026: o que os dados mostram"
    assert post["status"] == "publicado"

    markdown = post["markdown"]
    # O resumo abre pelo período e pelos três números que o artigo defende.
    for marca in ("192 955 contratos", "16,4 mil milhões", "188 725", "três leituras"):
        assert marca in markdown, marca

    blocos = [bloco["type"] for bloco in post["blocks"]]
    assert blocos.count("grafico") >= 5  # escalões, adjudicatários, procedimentos, CPV, regiões
    assert blocos.count("tabela") >= 3  # compradores, procedimentos, CPV
    assert "numeros" in blocos and "aviso" in blocos and "cta" in blocos

    # Todos os gráficos têm barras com valor e uma fonte citada.
    for bloco in _blocos(post, "grafico"):
        data = bloco["data"]
        assert data.get("series"), bloco["id"]
        assert all(item.get("value") is not None for item in data["series"]), bloco["id"]
        assert data.get("source"), bloco["id"]
        # O segundo valor só existe onde há mesmo segunda série (procedimentos).
        assert ("value2" in data["series"][0]) == (bloco["data"]["format"] == "percentagem"), bloco["id"]


def test_artigo_publica_a_analise_por_cpv(instalacao):
    """A análise por CPV deixou de estar «em preparação»: tem gráfico e tabela."""
    import json

    post = cms_store.resolve_post_by_slug(cms_editorial.ARTIGO_CONTRATOS_2026_SLUG, published_only=False)
    textos = json.dumps(post["blocks"], ensure_ascii=False)
    assert "CPV" in textos
    assert "Produtos farmacêuticos" in textos and "Serviços de limpeza" in textos
    assert "em preparação" not in post["markdown"]

    cpv = next(
        bloco for bloco in _blocos(post, "tabela") if bloco["data"].get("head", [""])[0] == "CPV"
    )
    assert cpv["data"]["head"] == ["CPV", "Classe", "Contratos", "Valor", "Valor médio"]
    assert len(cpv["data"]["rows"]) == 12
    # A soma das cinco classes da família 33 no topo é o que o texto afirma: 22,5%.
    familia = [linha for linha in cpv["data"]["rows"] if str(linha[0]).startswith("33")]
    assert len(familia) == 5
    total = 16_370_319_232.74
    soma = 2_598_184_999.77 + 473_913_219.86 + 271_025_534.94 + 232_246_535.24 + 100_441_855.64
    assert f"{soma / total * 100:.1f}".replace(".", ",") == "22,5"


def test_pagina_do_artigo_tem_graficos_tabelas_e_botao_de_pdf(instalacao):
    post = cms_store.resolve_post_by_slug(cms_editorial.ARTIGO_CONTRATOS_2026_SLUG, published_only=False)
    html = cms_render.render_post(post, settings=cms_store.get_settings())
    assert 'class="grafico-lista"' in html
    assert html.count('class="grafico-item"') >= 45  # as barras de todos os gráficos
    assert "tabela-rolavel" in html  # as tabelas rolam na horizontal no telefone
    assert f'/site/blog/{cms_editorial.ARTIGO_CONTRATOS_2026_SLUG}/pdf" download' in html

    # Na pré-visualização de um rascunho o artigo ainda não está publicado:
    # o botão não aparece, para não levar a um 404.
    previa = cms_render.render_post(post, preview=True, settings=cms_store.get_settings())
    assert f"/site/blog/{cms_editorial.ARTIGO_CONTRATOS_2026_SLUG}/pdf" not in previa


def test_pagina_do_artigo_partilha_pela_web_share_api(instalacao):
    slug = cms_editorial.ARTIGO_CONTRATOS_2026_SLUG
    post = cms_store.resolve_post_by_slug(slug, published_only=False)
    html = cms_render.render_post(post, settings=cms_store.get_settings())

    # O botão nasce escondido: quem o mostra é o script, que é quem sabe se o
    # browser tem partilha do sistema ou área de transferência.
    assert "data-partilhar hidden" in html
    assert "navigator.share" in html and "navigator.clipboard.writeText" in html
    assert f'data-url="/site/blog/{slug}"' in html

    # Num rascunho não há endereço público para partilhar (nem PDF para servir).
    previa = cms_render.render_post(post, preview=True, settings=cms_store.get_settings())
    assert "data-partilhar" not in previa and "navigator.share" not in previa

    # Com o endereço do site definido, o que se partilha é o endereço absoluto.
    definicoes = {**cms_store.get_settings(), "base_url": "https://sabemos.studio"}
    html = cms_render.render_post(post, settings=definicoes)
    assert f'data-url="https://sabemos.studio/site/blog/{slug}"' in html


def test_relatorio_pdf_e_opcional_e_decide_se_no_artigo(instalacao):
    from fastapi.testclient import TestClient

    from api import main as api_main

    slug = cms_editorial.ARTIGO_CONTRATOS_2026_SLUG
    post = cms_store.resolve_post_by_slug(slug, published_only=False)
    # Um artigo que não traz o campo (é o caso da semente, que não passa pelo
    # `_normalise`) continua com relatório: o que já estava publicado não muda
    # de comportamento.
    assert "report_pdf" not in post
    assert f"/site/blog/{slug}/pdf" in cms_render.render_post(post, settings=cms_store.get_settings())

    cms_store.save_item("posts", {"id": post["id"], "report_pdf": False}, "teste")
    sem_relatorio = cms_store.resolve_post_by_slug(slug, published_only=False)
    assert sem_relatorio["report_pdf"] is False

    html = cms_render.render_post(sem_relatorio, settings=cms_store.get_settings())
    assert f"/site/blog/{slug}/pdf" not in html
    # A partilha não depende do relatório.
    assert "data-partilhar" in html

    cliente = TestClient(api_main.app, base_url="http://prova")
    resposta = cliente.get(f"/site/blog/{slug}/pdf")
    assert resposta.status_code == 404
    assert "relatório em PDF" in resposta.json()["detail"]


def test_artigo_conta_o_tempo_de_leitura_dos_blocos(instalacao):
    """O tempo de leitura conta o Markdown e os blocos (gráficos e tabelas incluídos)."""
    post = cms_store.resolve_post_by_slug(cms_editorial.ARTIGO_CONTRATOS_2026_SLUG, published_only=False)
    apenas_texto = cms_store.reading_minutes(post["markdown"])
    assert post["reading_minutes"] > apenas_texto


# ---------------------------------------------------------------------- PDF
def test_seccoes_do_relatorio_saem_dos_blocos(instalacao):
    post = cms_store.resolve_post_by_slug(cms_editorial.ARTIGO_CONTRATOS_2026_SLUG, published_only=False)
    secoes = cms_post_report.artigo_seccoes(post, cms_store.get_settings())
    titulos = [secao["title"] for secao in secoes]
    assert any(titulo.startswith("Os dez maiores adjudicatários") for titulo in titulos)
    assert any(titulo.startswith("As doze maiores classes de CPV") for titulo in titulos)

    adjudicatarios = next(secao for secao in secoes if secao["title"].startswith("Os dez maiores adjudicatários"))
    assert adjudicatarios["columns"] == ["Item", "Valor", "Nota"]
    assert adjudicatarios["rows"][0][:2] == ["Medtronic Portugal", "125,0 M€"]

    procedimentos = next(secao for secao in secoes if secao["title"].startswith("Peso no número"))
    assert procedimentos["columns"] == ["Item", "Contratos", "Valor", "Nota"]

    # Os gráficos simples não ganham uma coluna de zeros.
    assert all(len(linha) == len(adjudicatarios["columns"]) for linha in adjudicatarios["rows"])


def test_rota_do_pdf_do_artigo(instalacao):
    from fastapi.testclient import TestClient

    from api import main as api_main

    cliente = TestClient(api_main.app, base_url="http://prova")
    resposta = cliente.get(f"/site/blog/{cms_editorial.ARTIGO_CONTRATOS_2026_SLUG}/pdf")
    assert resposta.status_code == 200, resposta.text
    assert resposta.headers["content-type"].startswith("application/pdf")
    assert resposta.content[:4] == b"%PDF"
    disposicao = resposta.headers.get("content-disposition", "")
    assert disposicao.startswith("attachment;") and cms_editorial.ARTIGO_CONTRATOS_2026_SLUG in disposicao

    assert cliente.get("/site/blog/nao-existe/pdf").status_code == 404
