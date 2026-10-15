"""Testes do módulo **Remunerações da Administração Pública** (DGAEP).

O que se verifica:

* a leitura dos valores dos quadros (euros, níveis da TRU, marcadores e células);
* a leitura do PDF real, quando ele está em disco (a recolha descarrega-o);
* o modelo (níveis, carreiras, dirigentes) e a simulação de uma posição;
* a fotografia que o CMS guarda e a página pública que dela se desenha;
* a entidade `remuneracoes` do CMS (publicação, endereço e SEO);
* as secções editáveis (título, subtítulo, ordem e estilo) e o artigo de blog
  que anuncia a página.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from api import cms_render as cms_render
from api import cms_routes as cms_routes
from api import cms_store as store
from api import remuneracoes_ap_service as ap
from api import remuneracoes_publicas as publicas


# ---------------------------------------------------------------------------
# Leitura dos valores
# ---------------------------------------------------------------------------
def test_euros_le_o_formato_do_quadro() -> None:
    assert ap._euros("878,41 €") == 878.41
    assert ap._euros("1 442,57") == 1442.57
    assert ap._euros("3 803,29 €") == 3803.29
    assert ap._euros("6 966,42") == 6966.42
    assert ap._euros("a)") is None
    assert ap._euros("") is None


def test_niveis_le_um_intervalo_e_um_minimo() -> None:
    assert ap._niveis("16") == ([16], "16")
    assert ap._niveis("[64 e 65]") == ([64, 65], "[64 e 65]")
    assert ap._niveis("> 115") == ([115], "> 115")
    assert ap._niveis("-") == ([], "-")


def test_celulas_separam_valores_vizinhos() -> None:
    linha = {
        "y": 100.0,
        "palavras": [
            (158.0, 100.0, 165.0, 110.0, "r)", 0, 0, 0),
            (173.0, 100.0, 177.0, 110.0, "1", 0, 0, 0),
            (179.0, 100.0, 203.0, 110.0, "442,57", 0, 0, 0),
            (210.0, 100.0, 214.0, 110.0, "1", 0, 0, 0),
            (216.0, 100.0, 240.0, 110.0, "705,73", 0, 0, 0),
        ],
    }
    celulas = ap._celulas(linha, a_partir_de=140.0)
    assert [celula["texto"] for celula in celulas] == ["1 442,57", "1 705,73"]


def test_marcadores_das_linhas() -> None:
    def linha(*palavras: Any) -> Dict[str, Any]:
        return {"y": 100.0, "palavras": list(palavras)}

    assert ap._marcador(linha((158.0, 100.0, 165.0, 110.0, "p)", 0, 0, 0))) == "p"
    assert ap._marcador(linha((189.0, 100.0, 196.0, 110.0, "i)", 0, 0, 0))) == "i"
    assert ap._marcador(linha((20.0, 100.0, 60.0, 110.0, "Reitor", 0, 0, 0))) is None


# ---------------------------------------------------------------------------
# Leitura do PDF (usa o que está em disco; salta se a recolha ainda não correu)
# ---------------------------------------------------------------------------
def _pdf_do_ano(ano: int) -> Path:
    nome = ap.FICHEIROS.get(ano)
    return ap.PASTA / "pdf" / str(nome) if nome else ap.PASTA / "pdf"


def test_le_o_quadro_do_ano_quando_o_pdf_esta_em_disco() -> None:
    pdf = _pdf_do_ano(2025)
    if not pdf.exists():
        pytest.skip("PDF da DGAEP ainda não recolhido (POST /remuneracoes-ap/refresh).")

    modelo = ap.ler_pdf(pdf, 2025)

    assert modelo["contagens"]["niveis"] == 115
    nivel_5 = next(item for item in modelo["niveis"] if item["nivel"] == 5)
    assert nivel_5["valor"] == 878.41  # BRAP de 2025, como o próprio quadro diz
    assert [item["nivel"] for item in modelo["niveis"] if item["valor"] is None] == [1, 2, 3, 4]
    assert any("Base Remuneratória" in nota for nota in modelo["tru_notas"])

    # Carreiras gerais: o técnico superior vai da posição 1 (nível 16) à 11 (58).
    tecnico = next(
        item
        for item in modelo["carreiras"]
        if item["carreira"] == "Técnico superior" and len(item["posicoes"]) == 11
    )
    assert tecnico["posicoes"][0] == {
        "posicao": "1",
        "nivel": 16,
        "niveis": [16],
        "niveis_texto": "16",
        "remuneracao": 1442.57,
    }
    assert tecnico["posicoes"][-1]["remuneracao"] == 3746.80

    # O dirigente é lido com índice, nível da TRU e remuneração.
    reitor = next(item for item in modelo["dirigentes"] if item["cargo"] == "Reitor")
    assert reitor["ambito"] == "UNIVERSIDADES"
    assert reitor["indice"] == 375
    assert reitor["niveis"] == [110, 111]
    assert reitor["nivel"] == 110
    assert reitor["remuneracao"] == 6733.24

    assert modelo["notas"] and modelo["base_legal"]


# ---------------------------------------------------------------------------
# Modelo e simulação
# ---------------------------------------------------------------------------
@pytest.fixture()
def modelo_falso(monkeypatch: pytest.MonkeyPatch) -> Dict[str, Any]:
    """Modelo pequeno em memória: o serviço é exercitado sem tocar em PDF."""
    modelo = {
        "ano": 2025,
        "versao": "05.jun.2025",
        "niveis": [
            {"nivel": 1, "valor": None, "nota": "a)"},
            {"nivel": 5, "valor": 878.41, "nota": None},
            {"nivel": 16, "valor": 1442.57, "nota": None},
            {"nivel": 58, "valor": 3746.80, "nota": None},
            {"nivel": 115, "valor": 6966.42, "nota": None},
        ],
        "tru_notas": ["a) - Base Remuneratória da Administração Pública (BRAP em 2025 = 878,41 €)."],
        "carreiras": [
            {
                "seccao": "Carreiras Gerais",
                "carreira": "Técnico superior",
                "categoria": "Técnico superior",
                "variante": None,
                "posicoes": [
                    {"posicao": "1", "nivel": 16, "niveis": [16], "niveis_texto": "16", "remuneracao": 1442.57},
                    {"posicao": "11", "nivel": 58, "niveis": [58], "niveis_texto": "58", "remuneracao": 3746.80},
                ],
                "minimo": 1442.57,
                "maximo": 3746.80,
            }
        ],
        "dirigentes": [
            {
                "seccao": "Cargos Dirigentes",
                "ambito": "UNIVERSIDADES",
                "grupo": "Reitoria",
                "cargo": "Reitor",
                "etiquetas": ["UNIVERSIDADES", "Reitoria"],
                "indice": 375,
                "indice_texto": "375",
                "nivel": 110,
                "niveis": [110, 111],
                "niveis_texto": "[110 e 111]",
                "remuneracao": 6733.24,
            }
        ],
        "notas": [{"seccao": "Carreiras Gerais", "titulo": "Notas sobre as Carreiras Gerais", "texto": ["Notas:"]}],
        "base_legal": [
            {
                "seccao": "Carreiras Gerais",
                "cabecalho": ["Designação da carreira", "Grau"],
                "linhas": [{"Designação da carreira": "Técnico superior", "Grau": "3"}],
            }
        ],
        "fontes": [],
        "contagens": {"niveis": 5, "carreiras": 1, "posicoes": 2, "dirigentes": 1, "notas": 1, "base_legal": 1},
    }
    monkeypatch.setattr(ap, "ler_modelo", lambda ano: dict(modelo, ano=int(ano)))
    monkeypatch.setattr(ap, "anos_disponiveis", lambda: [2025])
    monkeypatch.setattr(ap, "ano_de_referencia", lambda ano=None: 2025)
    monkeypatch.setattr(ap, "serie_dos_niveis", lambda inicio=5, fim=None: [{"nivel": 5, "valores": {"2024": 821.83, "2025": 878.41}}])
    return modelo


def test_simular_por_nivel(modelo_falso: Dict[str, Any]) -> None:
    resultado = ap.simular(ano=2025, nivel=16)

    assert resultado["remuneracao_base_mensal"] == 1442.57
    assert resultado["remuneracao_base_anual"] == round(1442.57 * 14, 2)
    assert resultado["origem"]["via"] == "Tabela Remuneratória Única"


def test_simular_por_carreira_e_posicao(modelo_falso: Dict[str, Any]) -> None:
    resultado = ap.simular(ano=2025, carreira="Técnico superior", posicao="11")

    assert resultado["remuneracao_base_mensal"] == 3746.80
    assert resultado["origem"]["carreira"] == "Técnico superior"
    assert resultado["origem"]["posicao"] == "11"
    assert any("suplementos" in nota for nota in resultado["notas"])


def test_simular_sem_posicao_na_tabela(modelo_falso: Dict[str, Any]) -> None:
    resultado = ap.simular(ano=2025, carreira="carreira que não existe")

    assert "error" in resultado
    assert resultado["ano"] == 2025


def test_simular_cargo_dirigente(modelo_falso: Dict[str, Any]) -> None:
    resultado = ap.simular(ano=2025, cargo="reitor")

    assert resultado["remuneracao_base_mensal"] == 6733.24
    assert resultado["remuneracao_base_anual"] == round(6733.24 * 14, 2)
    assert resultado["origem"]["via"] == "Cargo dirigente e equiparado"
    assert resultado["origem"]["cargo"] == "Reitor"
    assert resultado["origem"]["ambito"] == "UNIVERSIDADES"
    assert resultado["origem"]["niveis"] == "[110 e 111]"
    assert resultado["cargos_disponiveis"][0]["cargo"] == "Reitor"


def test_simular_cargo_dirigente_por_indice(modelo_falso: Dict[str, Any]) -> None:
    resultado = ap.simular(ano=2025, indice=375)

    assert resultado["origem"]["cargo"] == "Reitor"
    assert resultado["remuneracao_base_mensal"] == 6733.24


def test_simular_cargo_dirigente_inexistente(modelo_falso: Dict[str, Any]) -> None:
    resultado = ap.simular(ano=2025, cargo="cargo que não existe")

    assert "error" in resultado
    assert "cargo dirigente" in resultado["error"]
    # Sem candidatos, a resposta devolve todos os cargos do ano como alternativas.
    assert [item["cargo"] for item in resultado["cargos_disponiveis"]] == ["Reitor"]


def test_parametros_e_stats(modelo_falso: Dict[str, Any]) -> None:
    parametros = ap.parametros_do_ano(2025)
    assert parametros["brap"] == 878.41
    assert parametros["nivel_maximo"] == 115
    assert "BRAP" in (parametros["brap_nota"] or "")

    contagens = ap.stats(2025)["contagens"]
    assert contagens["dirigentes"] == 1


# ---------------------------------------------------------------------------
# Fotografia para o CMS e página pública
# ---------------------------------------------------------------------------
def test_dados_do_ano_monta_a_fotografia(modelo_falso: Dict[str, Any]) -> None:
    dados = publicas.dados_do_ano(2025)

    assert dados["ano"] == 2025
    assert dados["parametros"]["brap"] == 878.41
    assert len(dados["niveis"]) == 5
    assert dados["carreiras"][0]["carreira"] == "Técnico superior"
    assert dados["dirigentes"][0]["cargo"] == "Reitor"
    assert dados["fonte"]["documento"] == ap.FONTE
    assert "quadro da DGAEP de 2025" in publicas.descricao_dos_dados(dados)
    assert "BRAP 878,41 €" in publicas.resumo_dos_dados(dados)


def test_dados_do_ano_guarda_a_serie_do_brap_e_do_topo(modelo_falso: Dict[str, Any]) -> None:
    """A série da página traz o nível 5 (BRAP) — e o topo da tabela."""
    dados = publicas.dados_do_ano(2025)

    assert [int(linha["nivel"]) for linha in dados["serie"]] == [5]
    assert dados["serie"][0]["valores"]["2025"] == 878.41


def test_dados_do_ano_sem_recolha(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ap, "anos_disponiveis", lambda: [])
    monkeypatch.setattr(ap, "ano_de_referencia", lambda ano=None: None)

    dados = publicas.dados_do_ano()

    assert "error" in dados


@pytest.fixture()
def cms_limpo(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> Any:
    """CMS isolado em `tmp_path` (sem tocar no ficheiro real)."""
    monkeypatch.setattr(store, "CMS_DIR", tmp_path)
    monkeypatch.setattr(store, "CMS_PATH", tmp_path / "cms.json")
    monkeypatch.setattr(store, "MEDIA_DIR", tmp_path / "media")
    with store._lock:
        store._cache = None
        store._cache_mtime = None
    yield store
    with store._lock:
        store._cache = None
        store._cache_mtime = None


def _pagina(**extra: Any) -> Dict[str, Any]:
    dados = publicas.dados_do_ano(2025)
    pagina: Dict[str, Any] = {
        "title": "Remunerações da Administração Pública 2025",
        "slug": "administracao-publica-2025",
        "status": "rascunho",
        "ano": 2025,
        "intro": "## Quanto se paga\n\nO quadro consolidado da DGAEP.",
        "destacar": ["Técnico superior"],
        "mostrar": {},
        "cor": "#1d4ed8",
        "seo": {
            "title": "Remunerações da Administração Pública 2025",
            "description": "Tabela Remuneratória Única, carreiras e cargos dirigentes.",
            "keywords": ["remunerações", "administração pública", "TRU"],
        },
        "dados": dados,
    }
    pagina.update(extra)
    return pagina


def test_pagina_do_modelo_publica_e_tem_endereco(cms_limpo: Any) -> None:
    item = store.save_item("remuneracoes", _pagina(), "qa@teste.pt")

    assert store.remuneracao_path(item) == "/remuneracoes/administracao-publica-2025"
    assert store.remuneracao_by_slug("administracao-publica-2025", published_only=True) is None

    store.publish_item("remuneracoes", item["id"], "qa@teste.pt")

    publicada = store.remuneracao_by_slug("administracao-publica-2025")
    assert publicada and publicada["ano"] == 2025
    assert [item["id"] for item in store.published_remuneracoes()] == [item["id"]]


def test_pagina_do_modelo_normaliza_ano_e_mostrar(cms_limpo: Any) -> None:
    item = store.save_item(
        "remuneracoes",
        _pagina(ano="2024 (revisão)", mostrar={"niveis": False}),
        "qa@teste.pt",
    )

    assert item["ano"] == 2024
    assert item["mostrar"]["niveis"] is False
    assert item["mostrar"]["carreiras"] is True


def test_pagina_do_modelo_sem_titulo_falha(cms_limpo: Any) -> None:
    with pytest.raises(ValueError):
        store.save_item("remuneracoes", {"title": "", "slug": "x"}, "qa@teste.pt")


def test_render_da_pagina_do_modelo_tem_seo_tabelas_e_simulador(cms_limpo: Any) -> None:
    capa = store.save_media({"title": "Capa", "url": "https://exemplo.test/capa.jpg"}, "qa@teste.pt")
    logo = store.save_media({"title": "Logótipo", "url": "https://exemplo.test/logo.png"}, "qa@teste.pt")
    item = store.save_item(
        "remuneracoes",
        _pagina(capa_id=capa["id"], logo_id=logo["id"]),
        "qa@teste.pt",
    )

    html = cms_render.render_remuneracao(item)

    assert "<title>Remunerações da Administração Pública 2025" in html
    assert 'name="description" content="Tabela Remuneratória Única' in html
    assert 'rel="canonical" href="' in html and "/site/remuneracoes/administracao-publica-2025" in html
    assert '"@type": "Dataset"' in html
    assert '"temporalCoverage": "2025"' in html
    assert "--accent: #1d4ed8" in html
    assert "https://exemplo.test/capa.jpg" in html  # imagem de capa
    assert "https://exemplo.test/logo.png" in html  # logótipo
    assert "Tabela Remuneratória Única" in html
    assert "878,41" in html  # BRAP do ano
    assert 'data-papel="nivel"' in html  # simulador
    assert 'data-papel="cargo"' in html  # cargos dirigentes no simulador
    assert "Reitor · Reitoria · UNIVERSIDADES" in html
    assert "Base legal" in html
    assert 'class="breadcrumb"' in html
    assert '"@type": "BreadcrumbList"' in html
    assert html.count("<h1") == 1
    assert "<h1>Remunerações da Administração Pública 2025</h1>" in html


def test_render_do_modelo_respeita_o_que_esta_desligado(cms_limpo: Any) -> None:
    item = store.save_item(
        "remuneracoes",
        _pagina(mostrar={"simulador": False, "dirigentes": False, "notas": False, "serie": False}),
        "qa@teste.pt",
    )

    html = cms_render.render_remuneracao(item)

    assert 'data-papel="nivel"' not in html
    assert "Cargos dirigentes e equiparados" not in html
    assert "Notas da DGAEP" not in html
    assert "Tabela Remuneratória Única" in html  # esta continua ligada


def test_pagina_do_modelo_guarda_seccoes_ordem_e_estilo(cms_limpo: Any) -> None:
    item = store.save_item(
        "remuneracoes",
        _pagina(
            seccoes={"niveis": {"titulo": "Quanto paga cada nível", "sub": "valores de 2025"}},
            ordem=["simulador", "niveis", "seccao-que-nao-existe", "niveis"],
            estilo="destaque",
        ),
        "qa@teste.pt",
    )

    assert item["seccoes"]["niveis"] == {"titulo": "Quanto paga cada nível", "sub": "valores de 2025"}
    # as secções que o editor não escreveu ficam com o texto do modelo
    assert item["seccoes"]["dirigentes"]["titulo"] == "Cargos dirigentes e equiparados"
    assert item["seccoes"]["dirigentes"]["sub"]
    # a ordem pedida manda no início, sem repetições nem chaves desconhecidas, e
    # as secções que faltavam entram no fim
    assert item["ordem"][:2] == ["simulador", "niveis"]
    assert sorted(item["ordem"]) == sorted(store.SECCOES_REMUNERACOES_IDS)
    assert item["estilo"] == "destaque"


def test_pagina_do_modelo_recusa_estilo_desconhecido(cms_limpo: Any) -> None:
    item = store.save_item("remuneracoes", _pagina(estilo="neon"), "qa@teste.pt")

    assert item["estilo"] == store.ESTILO_REMUNERACOES_PADRAO


def test_render_usa_os_titulos_e_a_ordem_das_seccoes(cms_limpo: Any) -> None:
    item = store.save_item(
        "remuneracoes",
        _pagina(
            seccoes={"niveis": {"titulo": "Quanto paga cada nível", "sub": "a partir do quadro da DGAEP"}},
            ordem=["notas", "niveis"],
            estilo="plano",
            seo={"title": "Remunerações 2025", "description": "Os números do ano.", "keywords": ["TRU"]},
        ),
        "qa@teste.pt",
    )

    html = cms_render.render_remuneracao(item)

    assert "Quanto paga cada nível" in html
    assert "a partir do quadro da DGAEP" in html
    assert "<h2>Tabela Remuneratória Única</h2>" not in html  # o título do modelo foi substituído
    assert 'class="rem-pagina rem-estilo-plano"' in html
    assert html.index('id="rem-notas"') < html.index('id="rem-niveis"')  # a ordem escolhida manda
    assert html.index("#rem-notas") < html.index("#rem-niveis")  # o índice segue a mesma ordem


def test_render_do_modelo_tem_indice_navegavel_e_seccoes_marcadas(cms_limpo: Any) -> None:
    item = store.save_item("remuneracoes", _pagina(estilo="destaque", cor="#1d4ed8"), "qa@teste.pt")

    html = cms_render.render_remuneracao(item)

    assert 'class="rem-pagina rem-estilo-destaque"' in html
    assert 'class="rem-indice"' in html and 'aria-label="Secções do quadro"' in html
    assert 'class="rem-sec-cabeca"' in html and 'class="rem-sec-corpo"' in html
    assert html.count('class="rem-sec-corpo"') == html.count('class="section rem-sec"') > 3
    assert "rem-tabela rem-niveis" in html  # a TRU continua a rolar com cabeçalho preso


def test_artigo_do_modelo_anuncia_a_pagina(cms_limpo: Any) -> None:
    item = store.save_item("remuneracoes", _pagina(), "qa@teste.pt")

    sugestao = publicas.artigo_do_modelo(item)

    assert sugestao["title"] == "Remunerações da Administração Pública 2025: o que o quadro da DGAEP mostra"
    assert sugestao["slug"] == "remuneracoes-administracao-publica-2025"
    assert "878,41" in sugestao["markdown"]  # o BRAP da fotografia, em markdown
    assert f"/site/remuneracoes/{item['slug']}" in sugestao["markdown"]  # liga à página publicada
    assert sugestao["excerpt"] == item["excerpt"]
    assert "DGAEP" in sugestao["tags"]


def test_rota_do_artigo_cria_rascunho_e_liga_a_pagina(cms_limpo: Any) -> None:
    capa = store.save_media({"title": "Capa", "url": "https://exemplo.test/capa.jpg"}, "qa@teste.pt")
    item = store.save_item("remuneracoes", _pagina(capa_id=capa["id"]), "qa@teste.pt")
    sessao = SimpleNamespace(user=SimpleNamespace(email="qa@teste.pt"))

    corpo = cms_routes.cms_remuneracao_artigo(item["id"], {}, sessao)  # type: ignore[arg-type]

    artigo = corpo["artigo"]
    assert artigo["status"] == "rascunho"
    assert artigo["cover_id"] == capa["id"]  # o artigo herda a capa da página
    assert "878,41" in artigo["markdown"]
    assert corpo["item"]["artigo_id"] == artigo["id"]  # a página fica a saber do artigo
    assert corpo["url"] == f"/cms/blog?id={artigo['id']}"
    assert store.get_item("posts", artigo["id"])["slug"] == artigo["slug"]


def test_rota_do_artigo_recusa_pagina_inexistente(cms_limpo: Any) -> None:
    from fastapi import HTTPException

    sessao = SimpleNamespace(user=SimpleNamespace(email="qa@teste.pt"))

    with pytest.raises(HTTPException) as erro:
        cms_routes.cms_remuneracao_artigo("rem_nao_existe", {}, sessao)  # type: ignore[arg-type]

    assert erro.value.status_code == 404


def test_render_das_tabelas_traz_pesquisa_e_filtros(cms_limpo: Any, modelo_falso: Dict[str, Any]) -> None:
    item = store.save_item("remuneracoes", _pagina(), "qa@teste.pt")

    html = cms_render.render_remuneracao(item)

    # Uma barra de pesquisa e filtros por cada tabela do modelo (TRU, carreiras,
    # dirigentes e base legal) — e um só script para todas.
    assert html.count('<div class="rem-filtro" data-tabela-filtro') == 4
    assert html.count("[data-tabela-filtro]") == 1
    assert html.count('<input type="search" data-papel="busca"') == 4
    assert 'placeholder="Pesquisar por nível, valor ou nota…"' in html
    assert 'data-filtro="valor"' in html and "Sem valor publicado" in html
    assert 'data-filtro="seccao"' in html  # carreiras e base legal
    assert 'data-filtro="ambito"' in html and 'data-filtro="grupo"' in html
    # Os atributos das linhas são o que os filtros comparam (só o nível 1 do
    # modelo pequeno não tem valor publicado).
    assert 'data-valor="nao"' in html
    assert html.count('data-valor="sim"') == 4
    assert 'data-seccao="Carreiras Gerais"' in html
    assert 'data-ambito="UNIVERSIDADES"' in html
    # O contador começa com o total, com a unidade certa (singular incluído).
    assert "5 níveis" in html and "1 carreira/categoria" in html
    assert "1 cargo" in html and "1 linha" in html
    assert "Nenhuma linha corresponde à pesquisa." in html


def test_render_mostra_os_valores_sem_arredondar(cms_limpo: Any, modelo_falso: Dict[str, Any]) -> None:
    """O quadro publica cêntimos: a página não pode mostrar «878 €»."""
    item = store.save_item("remuneracoes", _pagina(), "qa@teste.pt")

    html = cms_render.render_remuneracao(item)

    assert "878,41 €" in html  # BRAP e, na TRU, o valor do nível 5
    assert "1 442,57 €" in html  # 1.ª posição do técnico superior
    assert "878 €" not in html  # o arredondamento dos grandes números fica fora daqui


def test_render_sem_tabelas_nao_traz_o_script_dos_filtros(
    cms_limpo: Any, modelo_falso: Dict[str, Any]
) -> None:
    item = store.save_item(
        "remuneracoes",
        _pagina(mostrar={"niveis": False, "serie": False, "carreiras": False, "dirigentes": False, "parametros": False}),
        "qa@teste.pt",
    )

    html = cms_render.render_remuneracao(item)

    assert "<table>" not in html
    assert "[data-tabela-filtro]" not in html  # sem tabelas não há script


def _scripts_js(html: str) -> List[str]:
    """JavaScript embutido no HTML (deixa de fora os blocos `ld+json`)."""
    codigos: List[str] = []
    for atributos, corpo in re.findall(r"<script([^>]*)>(.*?)</script>", html, re.S):
        tipo = re.search(r'type=["\']([^"\']+)["\']', atributos)
        if tipo and tipo.group(1) not in ("text/javascript", "module", "application/javascript"):
            continue
        if corpo.strip():
            codigos.append(corpo)
    return codigos


def test_javascript_da_pagina_publica_e_valido(cms_limpo: Any, tmp_path: Any) -> None:
    """O simulador é JavaScript embutido: um erro de sintaxe desligava-o em silêncio."""
    item = store.save_item("remuneracoes", _pagina(), "qa@teste.pt")
    html = cms_render.render_remuneracao(item)
    scripts = _scripts_js(html)

    assert scripts, "a página devia trazer o JavaScript do simulador"
    node = shutil.which("node")
    if not node:
        pytest.skip("node não está disponível para validar o JavaScript embutido.")

    for indice, codigo in enumerate(scripts):
        ficheiro = tmp_path / f"script-{indice}.js"
        ficheiro.write_text(codigo, encoding="utf-8")
        resultado = subprocess.run([node, "--check", str(ficheiro)], capture_output=True, text=True)
        assert resultado.returncode == 0, f"script {indice} com erro de sintaxe: {resultado.stderr[:400]}"
