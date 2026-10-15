"""Biblioteca pública: relatórios gratuitos e documentos já gerados, por área.

O que se prova aqui:

* o **agrupamento por área** dos pacotes do catálogo e dos documentos do Estúdio,
  incluindo as instalações antigas (pacotes sem área gravada);
* a **fronteira do download** — só os documentos gratuitos e publicados se
  descarregam; os pagos encaminham para o catálogo;
* o **bloco do CMS** (`relatorios`) que desenha a área pública, o modelo
  «Biblioteca de relatórios» e a página editorial que o usa;
* a rota pública `/site/documento/{id}`.

Nada aqui toca em `data/`: a loja de relatórios e o CMS vivem em `tmp_path`.
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
from api import cms_render  # noqa: E402
from api import cms_store  # noqa: E402
from api import reports_library as library  # noqa: E402
from api import reports_store as store  # noqa: E402
from api import reports_studio as studio  # noqa: E402


@pytest.fixture()
def instalacao(tmp_path, monkeypatch):
    """CMS e relatórios isolados em `tmp_path` (sem ler nem escrever em `data/`)."""
    monkeypatch.setattr(store, "REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr(store, "REPORTS_PATH", tmp_path / "reports" / "reports.json")
    monkeypatch.setattr(store, "FILES_DIR", tmp_path / "reports" / "files")
    monkeypatch.setattr(studio, "STUDIO_DIR", tmp_path / "reports" / "studio")

    cms = tmp_path / "cms"
    monkeypatch.setattr(cms_store, "CMS_DIR", cms)
    monkeypatch.setattr(cms_store, "CMS_PATH", cms / "cms.json")
    monkeypatch.setattr(cms_store, "MEDIA_DIR", cms / "media")
    monkeypatch.setattr(cms_store, "_cache", None)
    monkeypatch.setattr(cms_store, "_cache_mtime", None)

    store.reset_for_tests()
    studio.reset_for_tests()
    yield
    store.reset_for_tests()
    studio.reset_for_tests()


def _documento(titulo: str, *, preco: float, tags: list[str], publicar: bool = True, com_pdf: bool = True) -> Dict[str, Any]:
    """Relatório do Estúdio com PDF gerado (e, por omissão, publicado)."""
    criado = studio.save_report(
        {
            "title": titulo,
            "subtitle": f"Leitura de {titulo}",
            "template": "personalizado",
            "tags": tags,
            "blocks": [{"type": "heading", "title": "Enquadramento", "text": "Objeto e período."}],
        },
        actor="autor@exemplo.pt",
    )["report"]
    if com_pdf:
        studio.attach_pdf(criado["id"], "autor@exemplo.pt")
    if publicar:
        studio.publish_site(criado["id"], {"price": preco}, actor="autor@exemplo.pt")
    return criado


def _item(dados: Dict[str, Any], titulo: str) -> Dict[str, Any]:
    return next(item for item in dados["items"] if item["title"] == titulo)


# ----------------------------------------------------------- áreas e itens
def test_area_vem_do_campo_das_etiquetas_e_do_catalogo_de_origem():
    assert library.area_of({"area": "mercados"})["id"] == "mercados"
    # A primeira etiqueta que conhece uma área decide (é a matéria principal).
    assert library.area_of({"tags": ["empresa", "cpv"]})["id"] == "empresas"
    assert library.area_of({"tags": ["contratação"]})["id"] == "contratacao"
    # Sem área nem etiquetas, vale o identificador…
    assert library.area_of({"id": "concorrencia"})["id"] == "empresas"
    # … e, em último recurso, a área com que o pacote nasceu no catálogo.
    assert library.area_of({"id": "benchmark"})["id"] == "contratacao"
    assert library.area_of({"id": "financeiro-resumido"})["id"] == "empresas"
    # O que não se conhece não desaparece: fica em «Outros documentos».
    assert library.area_of({"id": "seja-o-que-for"})["id"] == "outros"


def test_catalogo_por_omissao_tem_area(instalacao):
    """Os pacotes de origem declaram a área — é o que agrupa a página pública."""
    por_omissao = {str(item["id"]): item.get("area") for item in store.DEFAULT_CATALOGUE}
    assert por_omissao["corporativo"] == "empresas"
    assert por_omissao["benchmark"] == "contratacao"
    assert store.money(next(item for item in store.catalogue() if item["id"] == "corporativo")["price"]) == 0.0


def test_biblioteca_junta_gratuitos_e_documentos_gerados(instalacao):
    grátis = _documento("Concorrência — Empresa A", preco=0.0, tags=["empresa", "concorrência"])
    pago = _documento("Área de CAE — Empresa A", preco=39.0, tags=["cae", "setor"])
    _documento("Rascunho não publicado", preco=0.0, tags=["empresa"], publicar=False)
    _documento("Publicado sem PDF", preco=0.0, tags=["empresa"], com_pdf=False)

    dados = library.library()
    titulos = [item["title"] for item in dados["items"]]
    # O que não está publicado não entra na montra.
    assert "Rascunho não publicado" not in titulos
    # Publicado sem PDF ainda aparece — mas como pacote, para se pedir (o PDF é
    # gerado na entrega); não é um documento que se descarregue.
    sem_pdf = _item(dados, "Publicado sem PDF")
    assert sem_pdf["kind"] == "relatorio" and sem_pdf["download"] == ""

    documento_gratis = _item(dados, "Concorrência — Empresa A")
    assert documento_gratis["free"] is True
    assert documento_gratis["kind"] == "documento"
    assert documento_gratis["download"] == f"/site/documento/{grátis['id']}"
    assert documento_gratis["area"] == "empresas"

    documento_pago = _item(dados, "Área de CAE — Empresa A")
    assert documento_pago["free"] is False and documento_pago["price"] == 39.0
    assert documento_pago["download"] == ""
    assert documento_pago["area"] == "empresas"

    # O pacote que a publicação criou no catálogo não duplica o documento.
    assert len([item for item in dados["items"] if item["title"] == "Concorrência — Empresa A"]) == 1
    assert dados["documents"] == 2
    # Gratuitos: o documento publicado a 0 €, o corporativo do catálogo e o
    # relatório publicado sem PDF (que se pede e é gerado na entrega).
    gratuitos = sorted(item["title"] for item in dados["items"] if item["free"])
    assert gratuitos == ["Concorrência — Empresa A", "Publicado sem PDF", "Relatório Corporativo"]

    areas = {area["id"]: area for area in dados["areas"]}
    assert areas["empresas"]["total"] >= 2
    # Gratuitos na área: o documento publicado a 0 €, o corporativo do catálogo e
    # o relatório publicado sem PDF.
    assert areas["empresas"]["free"] == 3
    assert areas["contratacao"]["free"] == 0
    # O corporativo (grátis no catálogo) aparece como relatório a pedir.
    corporativo = _item(dados, "Relatório Corporativo")
    assert corporativo["kind"] == "relatorio" and corporativo["free"] is True
    assert corporativo["download"] == "" and corporativo["href"] == "/reports"


def test_biblioteca_filtra_areas_e_gratuitos(instalacao):
    _documento("Concorrência — Empresa A", preco=0.0, tags=["empresa"])
    _documento("Área de CAE — Empresa A", preco=39.0, tags=["cae"])
    so_empresas = library.library(areas=["empresas"])
    assert so_empresas["items"]
    assert {item["area"] for item in so_empresas["items"]} == {"empresas"}
    gratuitos = library.library(free_only=True)
    assert gratuitos["items"]
    assert all(item["free"] for item in gratuitos["items"])
    assert not any(item["price"] > 0 for item in gratuitos["items"])


def test_so_se_descarregam_documentos_gratuitos_publicados(instalacao):
    gratis = _documento("Documento gratuito", preco=0.0, tags=["empresa"])
    pago = _documento("Documento pago", preco=25.0, tags=["empresa"])
    rascunho = _documento("Documento não publicado", preco=0.0, tags=["empresa"], publicar=False)

    encontrado = library.document_for_download(str(gratis["id"]))
    assert encontrado is not None
    nome, conteudo, mime = encontrado
    assert mime == "application/pdf" and conteudo[:4] == b"%PDF" and nome.endswith(".pdf")
    assert library.document_for_download(str(pago["id"])) is None
    assert library.document_for_download(str(rascunho["id"])) is None
    assert library.document_for_download("nao-existe") is None
    assert library.document_for_download("") is None


# --------------------------------------------------------------- bloco do CMS
def test_bloco_do_cms_desenha_areas_e_descarregamento(instalacao):
    documento = _documento("Concorrência — Empresa A", preco=0.0, tags=["empresa"])
    html = cms_render._render_block(
        {"type": "relatorios", "data": {"title": "Por área", "limit": 12, "intro": "Escolha a área."}}
    )
    assert "Por área" in html and "Escolha a área." in html
    assert "library-area" in html and "library-card" in html
    assert "Empresas e risco" in html and "Contratação pública" in html
    assert "Descarregar PDF" in html and "/site/documento/" in html
    # O botão descarrega mesmo: `download` no link e `attachment` na resposta.
    assert f'href="/site/documento/{documento["id"]}" download' in html
    assert "tag-free" in html and "Grátis" in html
    # O contador diz o que a página tem (é a leitura rápida do topo).
    assert "documento(s) em" in html and "gratuito(s)" in html


def test_bloco_do_cms_sem_dados_explica(instalacao, monkeypatch):
    """Sem nada publicado o bloco explica-se, em vez de ficar uma secção vazia."""
    monkeypatch.setattr(
        library,
        "library",
        lambda **_kwargs: {"items": [], "areas": [], "total": 0, "free": 0, "documents": 0, "areas_total": 0},
    )
    html = cms_render._render_block({"type": "relatorios", "data": {"title": "Relatórios"}})
    assert "Ainda não há relatórios publicados" in html
    assert "library-card" not in html


def test_bloco_do_cms_aceita_areas_como_texto_e_so_gratuitos(instalacao):
    _documento("Concorrência — Empresa A", preco=0.0, tags=["empresa"])
    _documento("Mercados — Empresa A", preco=0.0, tags=["mercados"])
    html = cms_render._render_block({"type": "relatorios", "data": {"areas": "mercados", "free_only": True}})
    assert "Mercados e notícias" in html
    assert "Empresas e risco" not in html


def test_modelo_e_pagina_editorial_da_biblioteca(instalacao):
    """O modelo entra na semente e a página existe no editorial, com o bloco."""
    nomes = [item["id"] for item in cms_store._empty_store()["templates"]]  # noqa: SLF001 - estrutura vazia
    assert nomes == []
    modelo = cms_store.TEMPLATE_BIBLIOTECA
    assert modelo["id"] == "tpl_biblioteca" and modelo["builtin"] is True
    assert any(block["type"] == "relatorios" for block in modelo["blocks"])

    paginas = {pagina["id"]: pagina for pagina in cms_editorial.paginas_do_site({})}
    assert "pag_relatorios" in paginas
    pagina = paginas["pag_relatorios"]
    assert pagina["path"] == "relatorios-gratuitos" and pagina["status"] == "publicado"
    tipos = [block["type"] for block in pagina["blocks"]]
    assert "relatorios" in tipos and "hero" in tipos and "faq" in tipos
    assert ("Relatórios", "relatorios-gratuitos") in cms_editorial.MENU_PRINCIPAL


def test_instalador_acrescenta_o_modelo_uma_vez(instalacao):
    """O deploy não leva `data/`: uma instalação em uso recebe o modelo pelo instalador."""
    cms_store.list_items("pages")  # primeira leitura: semeia a loja do CMS
    assert any(item["id"] == "tpl_biblioteca" for item in cms_store.list_items("templates")["items"])
    assert cms_store.instalar_templates_editoriais() == []
    # Um modelo editado fica como está (o instalador não passa por cima).
    with cms_store._lock:  # noqa: SLF001 - teste do instalador
        bruto = cms_store._load()  # noqa: SLF001
        item = next(item for item in bruto["templates"] if item["id"] == "tpl_biblioteca")
        item["name"] = "Biblioteca (editada)"
        cms_store._write_store(bruto)  # noqa: SLF001
    assert cms_store.instalar_templates_editoriais() == []
    guardado = next(item for item in cms_store.list_items("templates")["items"] if item["id"] == "tpl_biblioteca")
    assert guardado["name"] == "Biblioteca (editada)"
    # E volta a entrar se alguém o apagar da loja.
    with cms_store._lock:  # noqa: SLF001
        bruto = cms_store._load()  # noqa: SLF001
        bruto["templates"] = [item for item in bruto["templates"] if item["id"] != "tpl_biblioteca"]
        cms_store._write_store(bruto)  # noqa: SLF001
    assert cms_store.instalar_templates_editoriais() == ["tpl_biblioteca"]


# ------------------------------------------------------------------- rota
def test_rota_publica_de_documento(instalacao):
    from fastapi.testclient import TestClient

    from api import main as api_main

    gratis = _documento("Documento gratuito", preco=0.0, tags=["empresa"])
    pago = _documento("Documento pago", preco=25.0, tags=["empresa"])
    cliente = TestClient(api_main.app, base_url="http://prova")

    resposta = cliente.get(f"/site/documento/{gratis['id']}")
    assert resposta.status_code == 200, resposta.text
    assert resposta.headers["content-type"].startswith("application/pdf")
    assert resposta.content[:4] == b"%PDF"
    # Descarrega (não abre no leitor do browser) e com o nome do documento.
    disposicao = resposta.headers.get("content-disposition", "")
    assert disposicao.startswith("attachment;") and "filename=" in disposicao

    assert cliente.get(f"/site/documento/{pago['id']}").status_code == 404
    assert cliente.get("/site/documento/nao-existe").status_code == 404


def test_pagina_publica_responde_com_a_biblioteca(instalacao):
    """A página editorial responde no site com o bloco já desenhado."""
    from fastapi.testclient import TestClient

    from api import main as api_main

    _documento("Concorrência — Empresa A", preco=0.0, tags=["empresa"])
    cms_store.list_items("pages")  # primeira leitura: semeia a loja do CMS
    for pagina in cms_editorial.paginas_do_site({}):
        cms_store.save_item("pages", pagina, "sistema")

    cliente = TestClient(api_main.app, base_url="http://prova")
    resposta = cliente.get("/site/relatorios-gratuitos")
    assert resposta.status_code == 200, resposta.text
    html = resposta.text
    assert "Relatórios gratuitos e documentos já gerados" in html
    assert "library-card" in html and "/site/documento/" in html
    assert "Empresas e risco" in html
