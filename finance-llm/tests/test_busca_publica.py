"""Pesquisa pública do site (`/site/pesquisar`) e fichas de empresa e de contrato.

O que se prova aqui:

* o **agrupamento** por âmbito (empresas, contratos, notícias, insolvências) e o
  destino de cada resultado — as fichas do site, não a plataforma;
* a **fronteira da falha**: um âmbito em baixo não derruba os outros;
* a **ficha** renderizada no servidor, com os números, as partes e os processos;
* o **bloco do CMS** (`pesquisa-sabemos`): a página é editorial, o comportamento
  é fixo, e o termo chega pela barra de endereço.

Nada aqui fala com o Elasticsearch: as funções de leitura do `site_busca` são
substituídas por dados fixos, e o CMS vive em `tmp_path`.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from api import cms_render  # noqa: E402
from api import cms_store  # noqa: E402
from api import site_busca  # noqa: E402


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


def _resultado(titulo: str, href: str, **extra: Any) -> Dict[str, Any]:
    base = {
        "titulo": titulo,
        "href": href,
        "sub": "",
        "resumo": "",
        "data": "",
        "etiquetas": [],
        "externo": False,
    }
    base.update(extra)
    return base


def _grupo(grupo_id: str, rotulo: str, total: int, itens: List[Dict[str, Any]], erro: str = "") -> Dict[str, Any]:
    return {"id": grupo_id, "label": rotulo, "total": total, "items": itens, "erro": erro}


def _falsos_ambitos(monkeypatch, *, grupos: Dict[str, Dict[str, Any]]) -> None:
    """Substitui as quatro pesquisas por resultados fixos (por âmbito)."""

    def fabrica(grupo_id: str, rotulo: str):
        def pesquisa(termo: str, limite: int) -> Dict[str, Any]:
            if grupo_id not in grupos:
                raise RuntimeError("índice em baixo")
            dados = grupos[grupo_id]
            return _grupo(grupo_id, rotulo, dados["total"], dados["items"][:limite], dados.get("erro", ""))

        return pesquisa

    for grupo_id, rotulo in (
        ("empresas", "Empresas"),
        ("contratos", "Contratos"),
        ("noticias", "Notícias"),
        ("insolvencias", "Insolvências"),
    ):
        monkeypatch.setattr(site_busca, f"_{grupo_id}", fabrica(grupo_id, rotulo))


def _ambitos_de_exemplo() -> Dict[str, Dict[str, Any]]:
    return {
        "empresas": {"total": 17, "items": [_resultado("GALP", "/site/empresa/501331581")]},
        "contratos": {"total": 3013, "items": [_resultado("Gasóleo", "/site/contrato/15696069")]},
        "noticias": {
            "total": 93,
            "items": [_resultado("Galp duplicou margem", "https://exemplo.pt/noticia", externo=True)],
        },
        "insolvencias": {"total": 2, "items": [_resultado("Falconriver", "/site/empresa/515074195")]},
    }


# ------------------------------------------------------------------ pesquisa
def test_resultados_ligam_as_fichas_do_site(monkeypatch):
    _falsos_ambitos(monkeypatch, grupos=_ambitos_de_exemplo())

    achado = site_busca.pesquisar("galp")

    assert [grupo["id"] for grupo in achado["grupos"]] == ["empresas", "contratos", "noticias", "insolvencias"]
    assert achado["total"] == 17 + 3013 + 93 + 2
    empresas = achado["grupos"][0]
    assert empresas["items"][0]["href"] == "/site/empresa/501331581"
    assert achado["grupos"][1]["items"][0]["href"] == "/site/contrato/15696069"
    # A notícia abre na publicação original: sai do site.
    assert achado["grupos"][2]["items"][0]["externo"] is True


def test_ambito_escolhido_devolve_so_esse_grupo(monkeypatch):
    _falsos_ambitos(monkeypatch, grupos=_ambitos_de_exemplo())

    achado = site_busca.pesquisar("galp", tipo="contratos")

    assert achado["tipo"] == "contratos"
    assert [grupo["id"] for grupo in achado["grupos"]] == ["contratos"]


def test_ambito_em_baixo_nao_derruba_a_pesquisa(monkeypatch):
    _falsos_ambitos(monkeypatch, grupos={"empresas": {"total": 1, "items": [_resultado("GALP", "/site/empresa/1")]}})

    achado = site_busca.pesquisar("galp")

    por_id = {grupo["id"]: grupo for grupo in achado["grupos"]}
    assert por_id["empresas"]["items"][0]["titulo"] == "GALP"
    assert por_id["contratos"]["erro"] and not por_id["contratos"]["items"]
    assert achado["total"] == 1


def test_sem_termo_nao_pesquisa(monkeypatch):
    def explode(*_args: Any, **_kwargs: Any) -> Dict[str, Any]:
        raise AssertionError("não devia pesquisar sem termo")

    monkeypatch.setattr(site_busca, "_empresas", explode)

    assert site_busca.pesquisar("   ")["grupos"] == []


def test_tipo_desconhecido_cai_em_tudo(monkeypatch):
    _falsos_ambitos(monkeypatch, grupos=_ambitos_de_exemplo())

    achado = site_busca.pesquisar("galp", tipo="inventado")

    assert achado["tipo"] == "tudo"
    assert len(achado["grupos"]) == 4


# -------------------------------------------------------------------- ficha
def test_empresa_sem_contratos_mas_com_insolvencia(monkeypatch):
    """Quem só aparece no CIRE também tem ficha (com os processos e sem contratos)."""
    monkeypatch.setattr(site_busca, "get_company_by_nif", lambda nif: {"nif": nif, "name": nif})
    monkeypatch.setattr(site_busca, "_entidade_leve", lambda nif: {})
    monkeypatch.setattr(site_busca, "_nome_no_cire", lambda nif: "Falconriver - Lda")
    monkeypatch.setattr(site_busca, "_cire_da_empresa", lambda nif, limite=0: {"erro": "", "insolvente": _grupo("insolvente", "Processos", 2, []), "outros": _grupo("outros", "Outras", 0, [])})
    monkeypatch.setattr(site_busca, "_noticias_da_empresa", lambda nome, limite=0: [])

    dados = site_busca.empresa("515074195")

    assert dados is not None
    assert dados["nome"] == "Falconriver - Lda"
    assert dados["contratos_total"] == 0
    assert dados["insolvencias"]["insolvente"]["total"] == 2


def test_empresa_inexistente_devolve_none(monkeypatch):
    monkeypatch.setattr(site_busca, "get_company_by_nif", lambda nif: {"nif": nif, "name": nif})
    monkeypatch.setattr(site_busca, "_entidade_leve", lambda nif: {})
    monkeypatch.setattr(site_busca, "_nome_no_cire", lambda nif: "")

    assert site_busca.empresa("999999999") is None


def test_contrato_formata_valores_e_prazos(monkeypatch):
    monkeypatch.setattr(
        site_busca,
        "get_contract_by_id",
        lambda codigo: {
            "idcontrato": codigo,
            "objectoContrato": "Fornecimento de gasóleo",
            "precoContratual": 310653.36,
            "prazoExecucao": 365.0,
            "dataCelebracaoContrato": "2026-09-28",
            "adjudicantes": {"parsed": [{"nif": "512073821", "nome": "Município da Horta"}]},
            "adjudicatarios": {"parsed": [{"nif": "512044635", "nome": "GALP AÇORES"}]},
            "cpv": [{"code": "09134100-8", "description": "Gasóleo"}],
            "localExecucao": ["Portugal, Horta", "Portugal, Horta"],
        },
    )

    dados = site_busca.contrato("15696069")

    assert dados is not None
    assert dados["preco_texto"] == "310 653 €"
    assert dados["prazo"] == "365"
    assert dados["data_celebracao"] == "28/09/2026"
    assert dados["adjudicantes"][0]["nome"] == "Município da Horta"
    assert dados["cpv"][0]["codigo"] == "09134100-8"
    # A lista de locais vem repetida do índice: mostra-se uma vez.
    assert dados["local"] == "Portugal, Horta"


def test_contrato_inexistente_devolve_none(monkeypatch):
    monkeypatch.setattr(site_busca, "get_contract_by_id", lambda codigo: {"error": "Contrato não encontrado"})

    assert site_busca.contrato("000") is None


# ------------------------------------------------------------------- bloco
def test_bloco_registado_no_catalogo():
    assert "pesquisa-sabemos" in cms_store.BLOCK_IDS


def _pagina_com_busca() -> Dict[str, Any]:
    return cms_store.save_item(
        "pages",
        {
            "title": "Pesquisar",
            "slug": "pesquisar",
            "status": "publicado",
            "blocks": [
                {
                    "id": "b1",
                    "type": "pesquisa-sabemos",
                    "data": {"title": "Pesquisar", "intro": "Tudo o que os dados dizem."},
                }
            ],
        },
        "sistema",
    )


def test_pagina_da_pesquisa_sem_termo_apresenta_a_caixa(instalacao, monkeypatch):
    pagina = _pagina_com_busca()

    html = cms_render.render_page(pagina, query="")

    assert "<h1>Pesquisar</h1>" in html
    assert 'action="/site/pesquisar"' in html and 'name="q"' in html
    for aba in ("Tudo", "Empresas", "Contratos", "Notícias", "Insolvências"):
        assert f">{aba}</a>" in html
    assert "resultado(s) para" not in html


def test_pagina_da_pesquisa_desenha_os_resultados(instalacao, monkeypatch):
    _falsos_ambitos(monkeypatch, grupos=_ambitos_de_exemplo())
    pagina = _pagina_com_busca()

    html = cms_render.render_page(pagina, query="galp")

    assert 'value="galp"' in html
    assert "resultados</strong> para «galp»" in html
    assert 'href="/site/empresa/501331581"' in html
    assert 'href="/site/contrato/15696069"' in html
    # O "ver todos" do grupo leva o tipo escolhido na barra de endereço.
    assert 'href="/site/pesquisar?q=galp&amp;tipo=contratos"' in html
    # As notícias abrem fora, com `rel="noopener"`.
    assert 'href="https://exemplo.pt/noticia" target="_blank" rel="noopener"' in html


def test_pagina_do_ambito_escolhido(instalacao, monkeypatch):
    _falsos_ambitos(monkeypatch, grupos=_ambitos_de_exemplo())
    pagina = _pagina_com_busca()

    html = cms_render.render_page(pagina, query="galp", tipo="noticias")

    assert 'aria-current="page"' in html
    assert '<mark>Galp</mark> duplicou margem' in html
    assert "Ver os" not in html


def test_resultados_nao_se_indexam(instalacao, monkeypatch):
    """A página entra no índice; os resultados com `?q=` não."""
    _falsos_ambitos(monkeypatch, grupos=_ambitos_de_exemplo())
    pagina = _pagina_com_busca()

    assert 'content="index, follow"' in cms_render.render_page(pagina, query="")
    assert 'content="noindex, nofollow"' in cms_render.render_page(pagina, query="galp")


def test_ficha_de_empresa_tem_numeros_e_processos(instalacao):
    dados = {
        "nif": "512044635",
        "nome": "Galp Açores",
        "pais": "Portugal",
        "localizacao": "",
        "forma_juridica": "",
        "cae": "46811",
        "contratos_total": 380,
        "valor_total_texto": "120,8 M€",
        "adjudicante": {"total": 0, "valor": "0 €"},
        "adjudicatario": {"total": 380, "valor": "120,8 M€"},
        "contratos": [
            {
                "id": "15696069",
                "objeto": "Fornecimento de gasóleo",
                "data": "28/09/2026",
                "valor": "310 653 €",
                "papel": "Adjudicatário",
                "contraparte": "Município da Horta",
            }
        ],
        "insolvencias": {
            "erro": "",
            "insolvente": _grupo("insolvente", "Insolvente", 0, []),
            "outros": _grupo(
                "outros",
                "Outras",
                18,
                [
                    {
                        "data": "24/05/2026",
                        "tipo": "Insolvência",
                        "especie": "Insolvência pessoa coletiva",
                        "ato": "Encerramento do Processo",
                        "processo": "95/21.3T8SRQ",
                        "tribunal": "Comarca dos Açores",
                        "documento": "",
                        "papel": "Credor",
                    }
                ],
            ),
        },
        "noticias": [],
    }

    html = cms_render.render_empresa(dados)

    assert "<h1>Galp Açores</h1>" in html
    assert "NIF 512044635" in html
    assert "120,8 M€" in html
    assert 'href="/site/contrato/15696069"' in html
    assert "Insolvências e processos (CIRE)" in html and "Credor" in html
    assert "18 outra(s) publicação(ões)" in html


def test_ficha_de_contrato_liga_as_partes(instalacao):
    dados = {
        "id": "15696069",
        "objeto": "Fornecimento de gasóleo",
        "preco_texto": "310 653 €",
        "preco_base": "326 421 €",
        "data_celebracao": "28/09/2026",
        "prazo": "365",
        "adjudicantes": [{"nif": "512073821", "nome": "Município da Horta"}],
        "adjudicatarios": [{"nif": "512044635", "nome": "GALP AÇORES"}],
        "cpv": [{"codigo": "09134100-8", "descricao": "Gasóleo"}],
        "pecas": "https://exemplo.pt/pecas",
    }

    html = cms_render.render_contrato(dados)

    assert "<h1>Fornecimento de gasóleo</h1>" in html
    assert 'href="/site/empresa/512073821"' in html
    assert 'href="/site/empresa/512044635"' in html
    assert "365 dias" in html
    assert 'href="https://exemplo.pt/pecas"' in html


# ------------------------------------------------------------------- rotas
def test_rotas_publicas_das_fichas(instalacao, monkeypatch):
    from fastapi.testclient import TestClient

    from api import main as api_main

    monkeypatch.setattr(
        site_busca,
        "empresa",
        lambda nif: {"nif": nif, "nome": "Galp Açores", "contratos": [], "insolvencias": {}, "noticias": []},
    )
    monkeypatch.setattr(
        site_busca,
        "contrato",
        lambda codigo: {"id": codigo, "objeto": "Fornecimento de gasóleo", "adjudicantes": [], "adjudicatarios": []},
    )

    cliente = TestClient(api_main.app, base_url="http://prova")

    empresa = cliente.get("/site/empresa/512044635")
    assert empresa.status_code == 200
    assert "Galp Açores" in empresa.text

    contrato = cliente.get("/site/contrato/15696069")
    assert contrato.status_code == 200
    assert "Fornecimento de gasóleo" in contrato.text

    monkeypatch.setattr(site_busca, "empresa", lambda nif: None)
    monkeypatch.setattr(site_busca, "contrato", lambda codigo: None)
    assert cliente.get("/site/empresa/000000000").status_code == 404
    assert cliente.get("/site/contrato/000").status_code == 404
