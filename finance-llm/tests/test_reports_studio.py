"""Estúdio de relatórios: modelos, blocos, publicação, PDF e entrega automática.

O que aqui se prova é o que a equipa faz no estúdio — montar um relatório a
partir de um modelo, publicá-lo no catálogo e na loja com preço, gerar o PDF — e
o que o cliente recebe: com a chave `estudio:<id>` o pedido pago fica logo com o
relatório anexado, sem passar pela equipa.

Os dados das fontes são substituídos por um resultado fixo (`fake_query`): os
testes correm sem Elasticsearch e sem rede. O PDF é real (reportlab).
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

import pytest

from api import reports_store as store
from api import reports_studio as studio
from api import shop_store
from api import visualizador_service as viz

FONTE = "contrato"
DIMENSOES = ["ano", "adjudicatario"]
MEDIDAS = ["contagem", "soma_preco"]


@pytest.fixture()
def relatorios(tmp_path, monkeypatch):
    """Módulo de relatórios isolado em `tmp_path` (não toca em `data/`)."""
    monkeypatch.setattr(store, "REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr(store, "REPORTS_PATH", tmp_path / "reports" / "reports.json")
    monkeypatch.setattr(store, "FILES_DIR", tmp_path / "reports" / "files")
    monkeypatch.setattr(studio, "STUDIO_DIR", tmp_path / "reports" / "studio")
    store.reset_for_tests()
    studio.reset_for_tests()
    yield store
    store.reset_for_tests()
    studio.reset_for_tests()


@pytest.fixture()
def loja(tmp_path, monkeypatch):
    """Loja isolada (a publicação na loja cria lá o produto)."""
    monkeypatch.setattr(shop_store, "SHOP_DIR", tmp_path / "shop")
    monkeypatch.setattr(shop_store, "SHOP_PATH", tmp_path / "shop" / "shop.json")
    monkeypatch.setattr(shop_store, "FILES_DIR", tmp_path / "shop" / "files")
    monkeypatch.setattr(shop_store, "_cache", None)
    monkeypatch.setattr(shop_store, "_cache_mtime", None)
    yield shop_store


def _fake_query(payload: Dict[str, Any], scope: Optional[Dict[str, Any]] = None, es: Any = None) -> Dict[str, Any]:
    """Resultado fixo no lugar do Elasticsearch (mesma forma do Visualizador)."""
    dimensions = [entry if isinstance(entry, str) else str(entry.get("id")) for entry in (payload.get("dimensions") or [])]
    measures = [entry if isinstance(entry, str) else str(entry.get("id")) for entry in (payload.get("measures") or [])]
    rows: List[Dict[str, Any]] = []
    for index, label in enumerate(["2023", "2024", "2025"]):
        row: Dict[str, Any] = {dimension: f"{label}-{position}" for position, dimension in enumerate(dimensions)}
        for measure in measures:
            row[measure] = 1000.0 * (index + 1) if measure != "contagem" else float(5 + index)
        rows.append(row)
    columns = [{"key": dimension, "label": dimension, "type": "dimension"} for dimension in dimensions]
    columns += [
        {"key": measure, "label": measure, "type": "measure", "format": "currency" if measure == "soma_preco" else "number"}
        for measure in measures
    ]
    return {
        "dataset": {"id": payload.get("dataset"), "label": "Contratos Públicos"},
        "dimensions": [{"id": dimension, "label": dimension} for dimension in dimensions],
        "measures": [
            {"id": measure, "label": measure, "kind": "contagem" if measure == "contagem" else "soma",
             "format": "currency" if measure == "soma_preco" else "number"}
            for measure in measures
        ],
        "columns": columns,
        "rows": rows,
        "totals": {measure: 6000.0 for measure in measures},
        "meta": {"notes": [], "documents": 3},
        "error": None,
    }


@pytest.fixture()
def db(monkeypatch):
    """Substitui a consulta às fontes e o catálogo de dimensões/medidas."""
    monkeypatch.setattr(viz, "run_query", _fake_query)
    fonte = {
        "id": FONTE,
        "label": "Contratos Públicos",
        "description": "Contratos publicados no portal base.",
        "domain": "contratacao",
        "icon": "file-text",
        "kind": "es",
        "recommended": True,
        "dimensions": [
            {"id": dimension, "label": dimension, "type": "keyword", "unit": None}
            for dimension in ["ano", "adjudicatario", "adjudicante", "tipo_contrato", "regiao", "cpv"]
        ],
        "measures": [
            {"id": "contagem", "label": "Contagem", "kind": "contagem", "format": "integer"},
            {"id": "soma_preco", "label": "Soma de Preço", "kind": "soma", "format": "currency"},
            {"id": "media_preco", "label": "Média de Preço", "kind": "media", "format": "currency"},
            {"id": "distintos_adjudicatario", "label": "Distintos Adjudicatário", "kind": "distintos", "format": "number"},
        ],
        "defaults": {"dimension": "ano", "measure": "soma_preco", "limit": 25},
        "suggestions": [{"chart": "bar", "title": "Por ano", "dimensions": ["ano"], "measures": ["soma_preco"]}],
    }
    monkeypatch.setattr(studio, "_source_map", lambda scope=None: {FONTE: fonte})
    return fonte


def _rascunho(**extra: Any) -> Dict[str, Any]:
    payload = {
        "title": "Contratação pública 2025",
        "subtitle": "Leitura executiva",
        "blocks": [
            {"type": "heading", "title": "Enquadramento", "text": "Objeto e período."},
            {"type": "kpi", "title": "Indicadores", "source": FONTE, "measures": ["contagem", "soma_preco"]},
            {"type": "chart", "title": "Evolução", "source": FONTE, "chart": "bar", "dimensions": ["ano"], "measures": ["soma_preco"]},
            {"type": "table", "title": "Detalhe", "source": FONTE, "dimensions": ["ano", "adjudicatario"], "measures": ["contagem"], "limit": 10},
            {"type": "graph", "title": "Relações", "source": FONTE, "dimensions": ["ano", "adjudicatario"], "measures": ["soma_preco"], "limit": 10},
            {"type": "note", "title": "Método", "text": "Valores apurados a partir dos contratos indexados."},
        ],
    }
    payload.update(extra)
    return payload


# ------------------------------------------------------------------- acessos
def test_acesso_reservado_a_admin_manager_e_lista(relatorios):
    """Sem papel de gestão, só entra quem estiver na lista de gestores."""
    assert store.is_report_manager("admin@exemplo.pt", "admin") is True
    assert store.is_report_manager("gestor@exemplo.pt", "manager") is True
    assert store.is_report_manager("membro@exemplo.pt", "member") is False
    store.save_settings({"report_managers": ["Relatorios@Exemplo.pt", "invalido"]})
    assert store.report_managers() == ["relatorios@exemplo.pt"]
    assert store.is_report_manager("relatorios@exemplo.pt", "member") is True
    assert store.is_report_manager("outro@exemplo.pt", "member") is False
    assert studio.can_studio("relatorios@exemplo.pt", "member") is True


def test_lista_de_backoffice_e_gestores_sao_independentes(relatorios):
    store.save_settings({"backoffice_users": ["equipa@exemplo.pt"], "report_managers": ["autor@exemplo.pt"]})
    assert store.is_backoffice("equipa@exemplo.pt") is True
    assert store.is_report_manager("equipa@exemplo.pt", "member") is False
    assert store.is_report_manager("autor@exemplo.pt", "member") is True


# ------------------------------------------------------------------- modelos
def test_modelos_validados_contra_as_fontes(db):
    """Os modelos existem, têm blocos e nenhum bloco cai com as fontes de agora."""
    listing = studio.templates()
    ids = [item["id"] for item in listing["templates"]]
    assert ids == ["executivo", "mercado-cpv", "evolucao", "geografia", "entidades", "mercados", "dossie", "personalizado"]
    for item in listing["templates"]:
        if item["id"] == "personalizado":
            assert item["block_count"] == 0
            continue
        assert item["block_count"] > 0, item["id"]
        for warning in item["warnings"]:
            assert "retirado" in warning
    # Modelos que só usam a fonte disponível não perdem nada.
    for template_id in ("executivo", "evolucao", "entidades"):
        item = next(entry for entry in listing["templates"] if entry["id"] == template_id)
        assert item["warnings"] == [], template_id
    # Os que precisam de outras fontes dizem o que caiu, em vez de darem
    # gráficos vazios sem explicação.
    dossie = next(entry for entry in listing["templates"] if entry["id"] == "dossie")
    assert dossie["warnings"]
    assert dossie["block_count"] >= 4
    executivo = next(item for item in listing["templates"] if item["id"] == "executivo")
    assert {block["type"] for block in executivo["blocks"]} >= {"kpi", "chart", "ai", "note"}


def test_modelo_desconhecido(db):
    with pytest.raises(KeyError):
        studio.template("nao-existe")


def test_criar_a_partir_de_modelo(relatorios, db):
    created = studio.new_report({"template": "executivo"}, actor="autor@exemplo.pt")
    view = created["report"]
    assert view["title"] == "Sumário executivo"
    assert view["blocks"], "o modelo traz blocos"
    assert view["status"] == "rascunho"
    assert view["stats"]["charts"] >= 2
    # Não foi gravado: `new_report` é a proposta.
    assert studio.list_reports()["stats"]["total"] == 0
    # `create_report` (o que as rotas usam) grava a proposta.
    saved = studio.create_report({"template": "executivo"}, actor="autor@exemplo.pt")["report"]
    assert saved["stats"]["blocks"] == view["stats"]["blocks"]
    assert studio.list_reports()["stats"]["total"] == 1


# --------------------------------------------------------------------- blocos
def test_bloco_guarda_so_o_que_a_fonte_tem(db):
    doc = studio.normalise_report(
        {
            "title": "Teste",
            "blocks": [
                {
                    "type": "chart",
                    "title": "Com campos a mais",
                    "source": FONTE,
                    "chart": "bar",
                    "dimensions": ["ano", "nao-existe"],
                    "measures": ["soma_preco", "inventada"],
                }
            ],
        }
    )
    block = doc["blocks"][0]
    assert block["dimensions"] == ["ano"]
    assert block["measures"] == ["soma_preco"]


def test_previsualizacao_de_blocos_ignorados(db):
    """Um bloco que não passa a validação sai da vista, mas é dito porquê."""
    doc = studio.normalise_report(
        {
            "title": "Teste",
            "blocks": [
                {"type": "heading", "title": "Introdução"},
                {"type": "chart", "title": "Inválido", "source": FONTE, "chart": "bar", "dimensions": ["nao-existe"], "measures": ["soma_preco"]},
            ],
        }
    )
    assert [block["type"] for block in doc["blocks"]] == ["heading"]
    assert any("Inválido" in warning for warning in doc["_warnings"])


def test_blocos_invalidos_sao_recusados(db):
    with pytest.raises(ValueError):
        studio.normalise_report({"title": "T", "blocks": [{"type": "mapa"}]})
    with pytest.raises(ValueError):
        studio.normalise_report({"title": "T", "blocks": [{"type": "chart", "source": "inexistente", "chart": "bar", "dimensions": ["ano"]}]})
    with pytest.raises(ValueError):
        studio.normalise_report({"title": "T", "blocks": [{"type": "graph", "source": FONTE, "dimensions": ["ano"], "measures": ["contagem"]}]})
    with pytest.raises(ValueError):
        studio.normalise_report({"title": "", "blocks": []})


def test_bloco_invalido_no_modelo_e_retirado_com_aviso(db):
    doc = studio.normalise_report(
        {
            "title": "Teste",
            "blocks": [
                {"type": "chart", "title": "Válido", "source": FONTE, "chart": "bar", "dimensions": ["ano"], "measures": ["soma_preco"]},
                {"type": "chart", "title": "Inválido", "source": FONTE, "chart": "bolhas", "dimensions": ["ano"], "measures": ["soma_preco"]},
            ],
        }
    )
    assert len(doc["blocks"]) == 1
    assert doc["_warnings"]


def test_kpi_fica_sem_dimensoes_e_grafo_precisa_de_duas(db):
    doc = studio.normalise_report(
        {
            "title": "Teste",
            "blocks": [{"type": "kpi", "source": FONTE, "measures": ["contagem"], "dimensions": ["ano", "regiao"]}],
        }
    )
    assert doc["blocks"][0]["dimensions"] == []


def test_limites_de_tamanho(db):
    with pytest.raises(ValueError):
        studio.normalise_report({"title": "T", "blocks": [{"type": "heading", "title": f"B{i}"} for i in range(studio.MAX_BLOCKS + 1)]})


# ------------------------------------------------------------------ relatórios
def test_ciclo_de_vida_do_relatorio(relatorios, db):
    saved = studio.save_report(_rascunho(), actor="autor@exemplo.pt")["report"]
    assert saved["stats"]["blocks"] == 6
    assert saved["status"] == "rascunho"
    assert saved["status_label"] == "Rascunho"

    listed = studio.list_reports()
    assert listed["stats"]["total"] == 1
    assert listed["items"][0]["id"] == saved["id"]
    assert studio.list_reports(q="contratação")["total"] == 1
    assert studio.list_reports(q="petróleo")["total"] == 0

    edited = studio.save_report({"id": saved["id"], "title": "Outro título"}, actor="autor@exemplo.pt")["report"]
    assert edited["title"] == "Outro título"
    assert edited["blocks"] == saved["blocks"], "gravar sem `blocks` não deve apagar o que lá está"

    clone = studio.duplicate_report(saved["id"], actor="autor@exemplo.pt")["report"]
    assert clone["id"] != saved["id"]
    assert clone["title"].endswith("(cópia)")
    assert studio.list_reports()["stats"]["total"] == 2

    assert studio.delete_report(saved["id"], actor="autor@exemplo.pt") is True
    assert studio.delete_report(saved["id"], actor="autor@exemplo.pt") is False
    assert studio.list_reports()["stats"]["total"] == 1


def test_execucao_de_blocos_devolve_dados_e_grafo(relatorios, db):
    saved = studio.save_report(_rascunho(), actor="autor@exemplo.pt")["report"]
    executed = studio.run_report(studio.get_report(saved["id"]))
    assert executed["problems"] == []
    by_type = {block["type"]: block for block in executed["blocks"]}
    assert by_type["kpi"]["totals"]["soma_preco"] == 6000.0
    assert len(by_type["chart"]["rows"]) == 3
    assert by_type["table"]["columns"]
    grafo = by_type["graph"]["graph"]
    assert grafo["edges"], "o grafo tem arestas"
    assert {edge["source"] for edge in grafo["edges"]}
    assert by_type["heading"]["text"] == "Objeto e período."


def test_previsualizacao_parcial_por_bloco(relatorios, db):
    saved = studio.save_report(_rascunho(), actor="autor@exemplo.pt")["report"]
    first = saved["blocks"][1]["id"]
    executed = studio.run_report(studio.get_report(saved["id"]), block_ids=[first])
    assert [block.get("skipped") for block in executed["blocks"]].count(True) == 5
    assert executed["blocks"][1]["totals"]


# ----------------------------------------------------------------------- PDF
def test_pdf_gerado_e_guardado(relatorios, db):
    saved = studio.save_report(_rascunho(), actor="autor@exemplo.pt")["report"]
    result = studio.attach_pdf(saved["id"], "autor@exemplo.pt")
    assert result["file"]["mime"] == "application/pdf"
    assert result["file"]["size"] > 1000
    assert result["report"]["stats"]["has_pdf"] is True
    doc = studio.get_report(saved["id"])
    path, item = studio.file_of(doc, result["file"]["id"])
    assert path.exists() and path.read_bytes()[:4] == b"%PDF"
    # Refazer substitui (não acumula) e o ficheiro antigo sai do disco.
    second = studio.attach_pdf(saved["id"], "autor@exemplo.pt")
    assert len(second["report"]["files"]) == 1
    assert second["file"]["id"] != result["file"]["id"]


def test_pdf_de_relatorio_sem_dados_nao_rebenta(relatorios, db, monkeypatch):
    def rebenta(*_args: Any, **_kwargs: Any) -> Any:
        return {"error": "Elasticsearch indisponível.", "rows": [], "columns": []}

    monkeypatch.setattr(viz, "run_query", rebenta)
    saved = studio.save_report(_rascunho(), actor="autor@exemplo.pt")["report"]
    result = studio.attach_pdf(saved["id"], "autor@exemplo.pt")
    assert result["file"]["size"] > 1000


def test_remover_ficheiro_do_relatorio(relatorios, db):
    saved = studio.save_report(_rascunho(), actor="autor@exemplo.pt")["report"]
    result = studio.attach_pdf(saved["id"], "autor@exemplo.pt")
    assert studio.drop_file(saved["id"], result["file"]["id"], "autor@exemplo.pt") is True
    assert studio.get_report_view(saved["id"])["files"] == []
    assert studio.drop_file(saved["id"], "nao-existe", "autor@exemplo.pt") is False


# --------------------------------------------------------------- publicação
def test_publicar_no_site_cria_pacote_com_entrega_automatica(relatorios, db):
    saved = studio.save_report(_rascunho(), actor="autor@exemplo.pt")["report"]
    result = studio.publish_site(saved["id"], {"price": 39.9, "list_price": 59.9}, actor="autor@exemplo.pt")
    package = result["package"]
    assert package["id"] == "estudio-contratacao-publica-2025"
    assert package["price"] == 39.9
    assert package["active"] is True
    assert package["auto"] == studio.auto_key(saved["id"])
    assert store.package(package["id"])["auto"] == f"estudio:{saved['id']}"
    assert result["report"]["channels"] == ["site"]
    assert result["report"]["status"] == "publicado"

    removed = studio.unpublish(saved["id"], "site", actor="autor@exemplo.pt")
    assert removed["report"]["channels"] == []
    assert store.package(package["id"])["active"] is False


def test_publicar_na_loja_cria_produto(relatorios, loja, db):
    saved = studio.save_report(_rascunho(), actor="autor@exemplo.pt")["report"]
    result = studio.publish_shop(saved["id"], {"price": 49.0}, actor="autor@exemplo.pt")
    product = result["product"]
    assert product["type"] == "digital"
    assert product["status"] == "publicado"
    assert product["auto_report"] == f"estudio:{saved['id']}"
    assert product["price"] == 49.0
    assert shop_store.is_auto_report(product["auto_report"]) is True
    assert result["report"]["publication"]["loja"]["product_id"] == product["id"]

    # Publicar outra vez atualiza o produto em vez de criar um duplicado.
    again = studio.publish_shop(saved["id"], {"price": 55.0}, actor="autor@exemplo.pt")
    assert again["product"]["id"] == product["id"]
    assert again["product"]["price"] == 55.0
    assert len([item for item in shop_store.list_items("products")["items"] if item["id"] == product["id"]]) == 1

    removed = studio.unpublish(saved["id"], "loja", actor="autor@exemplo.pt")
    assert removed["report"]["channels"] == []
    assert loja.get_item("products", product["id"])["status"] == "rascunho"


def test_precos_invalidos_e_relatorio_vazio(relatorios, db):
    saved = studio.save_report(_rascunho(), actor="autor@exemplo.pt")["report"]
    with pytest.raises(ValueError):
        studio.publish_site(saved["id"], {"price": -1}, actor="autor")
    with pytest.raises(ValueError):
        studio.publish_site(saved["id"], {"price": 10, "list_price": 5}, actor="autor")
    with pytest.raises(ValueError):
        studio.publish(saved["id"], {"target": "televisao"}, actor="autor")
    empty = studio.save_report({"title": "Sem blocos"}, actor="autor")["report"]
    with pytest.raises(ValueError):
        studio.publish_site(empty["id"], {"price": 10}, actor="autor")


def test_publicar_nos_dois_canais(relatorios, loja, db):
    saved = studio.save_report(_rascunho(), actor="autor@exemplo.pt")["report"]
    result = studio.publish(saved["id"], {"target": "todos", "price": 29.0}, actor="autor@exemplo.pt")
    assert result["report"]["channels"] == ["site", "loja"]


def test_pacote_manual_nao_aceita_entrega_desconhecida(relatorios):
    with pytest.raises(ValueError):
        store.save_package({"id": "pacote-x", "title": "Pacote X", "auto": "inventado"})
    assert store.save_package({"id": "pacote-y", "title": "Pacote Y", "auto": "benchmark"})["auto"] == "benchmark"


# ------------------------------------------------------- entrega automática
def test_pedido_pago_no_site_recebe_o_pdf_do_estudio(relatorios, db):
    """O cliente pede o relatório publicado e o PDF é anexado sem a equipa."""
    saved = studio.save_report(_rascunho(), actor="autor@exemplo.pt")["report"]
    published = studio.publish_site(saved["id"], {"price": 0.0}, actor="autor@exemplo.pt")
    package_id = published["package"]["id"]

    pedido = store.create_request(
        {"email": "cliente@exemplo.pt", "name": "Cliente"},
        {"package_id": package_id, "targets": [{"name": "Empresa Alvo, LDA", "nif": "500697370"}]},
    )
    # O pacote é grátis: entra logo em produção (a geração corre no pedido).
    assert pedido["status"] in {"em_producao", "gerado"}
    assert pedido["files"], "o pedido ficou com o PDF anexado"
    assert pedido["files"][0]["name"].endswith(".pdf")


def test_gerar_pendentes_repetem_a_entrega(relatorios, db, monkeypatch):
    saved = studio.save_report(_rascunho(), actor="autor@exemplo.pt")["report"]
    published = studio.publish_site(saved["id"], {"price": 0.0}, actor="autor@exemplo.pt")
    pedido = store.create_request(
        {"email": "cliente@exemplo.pt", "name": "Cliente"},
        {"package_id": published["package"]["id"], "targets": [{"name": "Empresa Alvo, LDA", "nif": "500697370"}]},
    )
    assert pedido["files"]
    assert store.produzir_pendentes() == [], "um pedido já produzido não se repete"

    # Se a geração falhar no momento do pedido, a rede de segurança recupera.
    def rebenta(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("sem dados")

    with monkeypatch.context() as ctx:
        ctx.setattr(studio, "render_for_key", rebenta)
        quebrado = store.create_request(
            {"email": "outro@exemplo.pt", "name": "Outro"},
            {"package_id": published["package"]["id"], "targets": [{"name": "Outra, SA", "nif": "501234567"}]},
        )
    assert quebrado["files"] == []
    interno = store.get_request_view(str(quebrado["id"]), include_internal=True) or {}
    assert "falhou" in str(interno.get("internal_note") or ""), "a falha fica registada para o backoffice"
    assert store.produzir_pendentes(), "o pedido pago sem PDF é produzido na repetição"


def test_render_for_key(relatorios, db):
    assert studio.render_for_key("benchmark") is None
    assert studio.auto_key("rep-1") == "estudio:rep-1"
    assert studio.report_id_from_auto("estudio:rep-1") == "rep-1"
    assert studio.report_id_from_auto("outro") is None
    with pytest.raises(KeyError):
        studio.render_for_key("estudio:nao-existe")


def test_loja_entrega_o_pdf_do_estudio(relatorios, loja, db):
    """Na loja, o produto publicado entrega o PDF gerado pelo estúdio."""
    saved = studio.save_report(_rascunho(), actor="autor@exemplo.pt")["report"]
    studio.publish_shop(saved["id"], {"price": 25.0}, actor="autor@exemplo.pt")
    produto = next(item for item in loja.list_items("products")["items"] if item["auto_report"] == f"estudio:{saved['id']}")
    nome, dados, mime = loja._gerar_pdf({"number": "ENC-1", "customer": {"name": "Cliente"}}, produto)  # noqa: SLF001
    assert mime == "application/pdf"
    assert dados[:4] == b"%PDF"
    assert nome.endswith(".pdf")


def test_produto_com_entrega_desconhecida_nao_e_automatico(loja):
    produto = loja.save_item("products", {"name": "Relatório inventado", "price": 9.9, "auto_report": "inventado"}, author="autor")
    assert produto["auto_report"] == ""
    outro = loja.save_item("products", {"name": "Do estúdio", "price": 9.9, "auto_report": "estudio:rep-abc"}, author="autor")
    assert outro["auto_report"] == "estudio:rep-abc"


# ----------------------------------------------------------------------- IA
def test_ia_sem_modelo_devolve_texto_factual(relatorios, db, monkeypatch):
    """Sem IA configurada o estúdio não falha: dá o texto montado com os dados."""
    from api import people_360

    monkeypatch.setattr(people_360, "resolve_backend", lambda session, backend=None: ({"kind": "local", "note": "Sem modelo configurado."}, ""))
    saved = studio.save_report(_rascunho(), actor="autor@exemplo.pt")["report"]
    result = asyncio.run(studio.assist({"mode": "sumario", "report": saved["id"]}, None))
    assert result["mode"] == "sumario"
    assert result["text"]
    assert result["text"] == result["factual"]
    assert "Indicadores" in result["text"]


def test_ia_insights_e_sugestoes_de_blocos(relatorios, db, monkeypatch):
    from api import people_360

    monkeypatch.setattr(people_360, "resolve_backend", lambda session, backend=None: ({"kind": "local", "note": ""}, ""))
    saved = studio.save_report(_rascunho(), actor="autor@exemplo.pt")["report"]
    chart = next(block for block in saved["blocks"] if block["type"] == "chart")
    insights = asyncio.run(studio.assist({"mode": "insights", "report": saved["id"], "block": chart["id"]}, None))
    assert "Maior grupo" in insights["text"]
    blocos = asyncio.run(studio.assist({"mode": "blocos", "source": FONTE}, None))
    assert blocos["blocks"], "as sugestões vêm das sugestões da própria fonte"
    assert {block["source"] for block in blocos["blocks"]} == {FONTE}
    with pytest.raises(ValueError):
        asyncio.run(studio.assist({"mode": "adivinhar"}, None))
    with pytest.raises(KeyError):
        asyncio.run(studio.assist({"mode": "sumario", "report": "nao-existe"}, None))


def test_ia_usa_o_modelo_quando_existe(relatorios, db, monkeypatch):
    from api import ontology_ai, people_360

    monkeypatch.setattr(
        people_360,
        "resolve_backend",
        lambda session, backend=None: ({"kind": "cloud", "provider": "openai", "model": "gpt-x"}, ""),
    )

    async def responde(*_args: Any, **_kwargs: Any) -> str:
        return "Sumário escrito pelo modelo com base nos dados."

    monkeypatch.setattr(ontology_ai, "ask_model", responde)
    saved = studio.save_report(_rascunho(), actor="autor@exemplo.pt")["report"]
    result = asyncio.run(studio.assist({"mode": "sumario", "report": saved["id"]}, None))
    assert result["text"] == "Sumário escrito pelo modelo com base nos dados."
    assert result["ai"] is True
    assert result["backend"] == {"kind": "cloud", "provider": "openai", "model": "gpt-x"}


def test_ia_que_falha_cai_para_o_texto_factual(relatorios, db, monkeypatch):
    from api import ontology_ai, people_360

    monkeypatch.setattr(
        people_360, "resolve_backend", lambda session, backend=None: ({"kind": "cloud", "provider": "x", "model": "y"}, "")
    )

    async def rebenta(*_args: Any, **_kwargs: Any) -> str:
        raise RuntimeError("sem quota")

    monkeypatch.setattr(ontology_ai, "ask_model", rebenta)
    saved = studio.save_report(_rascunho(), actor="autor@exemplo.pt")["report"]
    result = asyncio.run(studio.assist({"mode": "sumario", "report": saved["id"]}, None))
    assert result["warnings"]
    assert result["text"] == result["factual"]


# ------------------------------------------------------------------- estado
def test_estado_do_estudio(relatorios, db):
    info = studio.state()
    assert info["module"] == "reports-studio"
    assert info["templates"] == len(studio.TEMPLATES)
    assert info["pdf"] is True
    assert "chart" in info["block_types"]
    assert info["limits"]["max_blocks"] == studio.MAX_BLOCKS


# --------------------------------------------------------------------- rotas
@pytest.fixture()
def cliente(relatorios, db):
    """Cliente HTTP com sessão falsa, sem correr o lifespan (não carrega modelos)."""
    from fastapi.testclient import TestClient

    from api import main as api_main
    from api.auth_routes import CurrentSession, UserResponse, require_session

    holder: Dict[str, CurrentSession] = {}

    def fake_session(email: str, role: str) -> CurrentSession:
        display = email.split("@")[0]
        return CurrentSession(
            user=UserResponse(
                id=f"u-{email}",
                email=email,
                name=display,
                role=role,
                initials=(display[:2] or "??").upper(),
                status="active",
                locale="pt-PT",
                timezone="Europe/Lisbon",
            ),
            session_id="s-prova",
            token="t-prova",
        )

    api_main.app.dependency_overrides[require_session] = lambda: holder["session"]
    client = TestClient(api_main.app, base_url="http://prova")
    holder["session"] = fake_session("admin@exemplo.pt", "admin")
    yield client, holder, fake_session
    api_main.app.dependency_overrides.pop(require_session, None)


def test_rotas_exigem_acesso_ao_estudio(cliente):
    client, holder, fake_session = cliente
    member = fake_session("membro@exemplo.pt", "member")
    holder["session"] = member
    assert client.get("/reports/studio/me").status_code == 403
    assert client.get("/reports/studio/templates").status_code == 403
    assert client.post("/reports/studio/reports", json={"template": "executivo"}).status_code == 403

    # O administrador autoriza a conta em *Gestores de relatórios*.
    holder["session"] = fake_session("admin@exemplo.pt", "admin")
    saved = client.put("/reports/admin/settings", json={"report_managers": ["membro@exemplo.pt"]})
    assert saved.status_code == 200, saved.text
    assert saved.json()["report_managers_effective"] == ["membro@exemplo.pt"]

    holder["session"] = member
    me = client.get("/reports/studio/me")
    assert me.status_code == 200, me.text
    assert me.json()["manager"] is True


def test_ciclo_completo_pelas_rotas(cliente):
    client, _holder, _fake = cliente
    created = client.post("/reports/studio/reports", json={"template": "executivo"})
    assert created.status_code == 201, created.text
    report_id = created.json()["report"]["id"]
    assert created.json()["report"]["blocks"]

    listing = client.get("/reports/studio/reports")
    assert listing.status_code == 200
    assert listing.json()["total"] == 1

    listed = client.post("/reports/studio/query", json={"report": {"id": report_id}})
    assert listed.status_code == 200, listed.text
    assert listed.json()["problems"] == []

    edited = client.put(
        f"/reports/studio/reports/{report_id}",
        json={"title": "Panorama 2025", "blocks": [{"type": "kpi", "title": "Totais", "source": FONTE, "measures": ["contagem"]}]},
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["report"]["stats"]["blocks"] == 1

    pdf = client.post(f"/reports/studio/reports/{report_id}/pdf")
    assert pdf.status_code == 200, pdf.text
    file_id = pdf.json()["file"]["id"]

    download = client.get(f"/reports/studio/reports/{report_id}/files/{file_id}")
    assert download.status_code == 200
    assert download.content[:4] == b"%PDF"

    published = client.post(f"/reports/studio/reports/{report_id}/publish", json={"target": "site", "price": 39.0})
    assert published.status_code == 200, published.text
    assert published.json()["report"]["channels"] == ["site"]
    assert store.package(published.json()["package"]["id"])["auto"] == f"estudio:{report_id}"

    removed = client.post(f"/reports/studio/reports/{report_id}/publish", json={"target": "site", "price": -1})
    assert removed.status_code == 400

    out = client.post(f"/reports/studio/reports/{report_id}/unpublish", json={"target": "site"})
    assert out.status_code == 200
    assert out.json()["report"]["channels"] == []

    assert client.delete(f"/reports/studio/reports/{report_id}/files/{file_id}").status_code == 200
    assert client.delete(f"/reports/studio/reports/{report_id}").status_code == 200
    assert client.get(f"/reports/studio/reports/{report_id}").status_code == 404


def test_rotas_de_ia(cliente):
    client, _holder, _fake = cliente
    report = client.post("/reports/studio/reports", json={"template": "executivo"}).json()["report"]
    resposta = client.post(f"/reports/studio/reports/{report['id']}/ai", json={"mode": "sumario"})
    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["text"]
    assert client.post("/reports/studio/ai", json={"mode": "inventado"}).status_code == 400
    assert client.post("/reports/studio/ai", json={"mode": "blocos", "source": FONTE}).status_code == 200


def test_middleware_deixa_o_gestor_de_relatorios_escrever_no_estudio(cliente, monkeypatch):
    """A lista de gestores tem de valer na escrita (é o middleware que a lê)."""
    from api import main as api_main

    client, _holder, _fake = cliente
    autor = {"email": "autor@exemplo.pt", "role": "member"}
    monkeypatch.setattr(api_main, "_utilizador_da_sessao", lambda _authorization: autor)
    headers = {"Authorization": "Bearer prova"}

    # Sem estar na lista, um `member` não escreve no estúdio...
    store.save_settings({"report_managers": []})
    bloqueado = client.post("/reports/studio/reports", json={"template": "executivo"}, headers=headers)
    assert bloqueado.status_code == 403
    assert bloqueado.json()["code"] == "read_only"

    # ... e com a lista preenchida, escreve (é o que lhe permite montar relatórios).
    store.save_settings({"report_managers": ["autor@exemplo.pt"]})
    permitido = client.post("/reports/studio/reports", json={"template": "executivo"}, headers=headers)
    assert permitido.status_code == 201, permitido.text
