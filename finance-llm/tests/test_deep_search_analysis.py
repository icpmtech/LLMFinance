"""Testes da ontologia, das analogias e da análise da pesquisa profunda.

Cobrem o que a página passou a mostrar em separadores: o grafo de objectos e
relações construído a partir das fontes (sem tocar no Elasticsearch, com um
cliente falso), as analogias por vector e a rede de segurança por CPV/valor, e a
interpretação pelo modelo ou pelo agente Hermes.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from api import deep_search_analysis as analysis
from api import deep_search_analogies as analogies


# --------------------------------------------------------------------- auxiliares

def _fonte_contrato(
    idcontrato: str,
    *,
    titulo: str = "Licenças de software",
    preco: float = 1000.0,
    cpv: str = "72268000-1",
    ano: int = 2026,
    adjudicante: str | None = "MUNICÍPIO DE LEIRIA",
    adjudicante_nif: str | None = "506606013",
    adjudicatario: str | None = "CLARANET II SOLUTIONS",
    adjudicatario_nif: str | None = "510728189",
    n: int = 1,
) -> dict:
    """Fonte de contrato tal como o `/deep-search/ask` a devolve."""
    meta = {"preco": preco, "cpv": cpv, "ano": ano}
    if adjudicante:
        meta["adjudicante"] = adjudicante
    if adjudicante_nif:
        meta["adjudicante_nif"] = adjudicante_nif
    if adjudicatario:
        meta["adjudicatario"] = adjudicatario
    if adjudicatario_nif:
        meta["adjudicatario_nif"] = adjudicatario_nif
    return {
        "n": n,
        "id": idcontrato,
        "scope": "contracts",
        "scope_label": "Contratos",
        "title": titulo,
        "subtitle": f"{adjudicante} → {adjudicatario}",
        "snippet": "…",
        "url": "",
        "date": f"{ano}-09-11",
        "badges": [ano],
        "image": "",
        "open": {"view": "contract-detail", "arg": idcontrato},
        "meta": meta,
        "links": [],
    }


@pytest.fixture(autouse=True)
def _sem_elasticsearch(monkeypatch):
    """Por omissão a ontologia não vai ao ES; quem testa o cadastro substitui-o."""
    monkeypatch.setattr(analysis.search_service, "get_es_client", lambda *a, **k: None)
    monkeypatch.setattr(analogies.search_service, "get_es_client", lambda *a, **k: None)


def _no(grafo: dict, tipo: str, chave: str) -> dict | None:
    return next((no for no in grafo["nodes"] if no["id"] == f"{tipo}|{chave}"), None)


def _aresta(grafo: dict, origem: str, destino: str, label: str) -> dict | None:
    return next(
        (
            aresta
            for aresta in grafo["edges"]
            if aresta["source"] == origem and aresta["target"] == destino and aresta["label"] == label
        ),
        None,
    )


# --------------------------------------------------------------------- ontologia

def test_ontologia_das_fontes_liga_contrato_as_partes_cpv_e_ano():
    grafo = analysis.ontologia_das_fontes(
        [_fonte_contrato("C1", preco=1000.0, cpv="72268000-1", ano=2026)]
    )

    contrato = _no(grafo, "processo", "C1")
    assert contrato is not None
    assert contrato["count"] == 1 and contrato["total_value"] == 1000.0
    assert contrato["dimension"] == analysis.ONTOLOGY_DIMENSION

    # As partes ficam indexadas pelo NIF (é o que as junta entre contratos).
    assert _no(grafo, "entidade", "506606013")["role"] == analysis.ROLE_ADJUDICANTE
    assert _no(grafo, "entidade", "510728189")["role"] == analysis.ROLE_ADJUDICATARIO
    assert _no(grafo, "cpv", "72268000-1") is not None
    assert _no(grafo, "tempo", "2026") is not None

    assert _aresta(grafo, "processo|C1", "entidade|506606013", "adjudicado por") is not None
    assert _aresta(grafo, "processo|C1", "entidade|510728189", "adjudicado a") is not None
    assert _aresta(grafo, "processo|C1", "cpv|72268000-1", "classificado como") is not None
    assert _aresta(grafo, "processo|C1", "tempo|2026", "celebrado em") is not None


def test_ontologia_agrega_a_mesma_entidade_em_dois_contratos():
    """Sem agregação o grafo mostrava dez nós iguais em vez de uma empresa."""
    grafo = analysis.ontologia_das_fontes(
        [
            _fonte_contrato("C1", preco=1000.0, n=1),
            _fonte_contrato("C2", preco=500.0, titulo="Outro contrato", n=2),
        ]
    )

    empresa = _no(grafo, "entidade", "510728189")
    assert empresa["count"] == 2
    assert empresa["total_value"] == 1500.0
    assert len([no for no in grafo["nodes"] if no["type"] == "entidade"]) == 2


def test_ontologia_cria_relacoes_entre_entidades():
    """É aqui que está o valor: quem contrata com quem, e quem partilha comprador."""
    grafo = analysis.ontologia_das_fontes(
        [
            _fonte_contrato("C1", adjudicatario="EMPRESA A", adjudicatario_nif="500000001"),
            _fonte_contrato("C2", adjudicatario="EMPRESA B", adjudicatario_nif="500000002", n=2),
        ]
    )

    # O mesmo organismo contratou as duas empresas.
    assert _aresta(grafo, "entidade|506606013", "entidade|500000001", "contrata com") is not None
    assert _aresta(grafo, "entidade|506606013", "entidade|500000002", "contrata com") is not None
    # E as duas aparecem no mesmo mercado.
    assert _aresta(grafo, "entidade|500000001", "entidade|500000002", "mesmo comprador") is not None


def test_ontologia_sem_nif_avisa_que_pode_duplicar_entidades():
    grafo = analysis.ontologia_das_fontes(
        [_fonte_contrato("C1", adjudicatario="EMPRESA SEM NIF", adjudicatario_nif=None)]
    )

    no = _no(grafo, "entidade", "nome:" + analysis.deep._fold("EMPRESA SEM NIF")[:60])
    assert no is not None
    assert any("sem NIF" in nota for nota in grafo["meta"]["notes"])


def test_ontologia_ignora_noticias_e_diz_quantas():
    fontes = [
        _fonte_contrato("C1"),
        {"n": 2, "id": "N1", "scope": "news", "title": "Notícia", "meta": {}, "links": []},
    ]

    grafo = analysis.ontologia_das_fontes(fontes)

    assert all(no["type"] != "outra" for no in grafo["nodes"])
    assert any("fora da ontologia" in nota for nota in grafo["meta"]["notes"])


def test_ontologia_envelope_e_mermaid():
    grafo = analysis.ontologia_das_fontes([_fonte_contrato("C1")])

    # Envelope do grafo de contratos: é o que deixa a interface reutilizar o desenho.
    for campo in ("dimension_a", "metric", "nodes_total", "kept_nodes", "directed", "notes", "limits"):
        assert campo in grafo["meta"]
    assert grafo["meta"]["dimension_a"] == analysis.ONTOLOGY_DIMENSION
    assert grafo["meta"]["directed"] is True
    assert grafo["totals"]["contracts"] == 1
    assert grafo["legend"] and grafo["legend"][0]["type"] in analysis.ONTOLOGY_TYPES

    # Mermaid: rótulos entre aspas (sem elas a sintaxe com parênteses rebenta).
    linhas = grafo["mermaid"].splitlines()
    assert linhas[0] == "graph LR"
    assert any('-->"' in linha or '-->|"' in linha for linha in linhas)
    assert all(linha.startswith("  n") or linha == "graph LR" for linha in linhas if linha.strip())


def test_mermaid_sem_nos_e_vazio():
    assert analysis.mermaid_da_ontologia([], []) == ""


def test_mermaid_escapa_aspas():
    texto = analysis.mermaid_da_ontologia(
        [{"id": "entidade|1", "label": 'Empresa "X" (Lda)'}],
        [],
    )

    assert '#quot;' in texto
    assert texto.count('"') % 2 == 0


def test_ontologia_avisa_quando_corta():
    fontes = [
        _fonte_contrato(f"C{i}", titulo=f"Contrato {i}", adjudicatario=f"EMPRESA {i}", n=i)
        for i in range(1, analysis.ONTOLOGY_MAX_NODES + 40)
    ]

    grafo = analysis.ontologia_das_fontes(fontes)

    assert len(grafo["nodes"]) == analysis.ONTOLOGY_MAX_NODES
    assert grafo["meta"]["complete"] is False
    assert any("ficaram de fora" in nota for nota in grafo["meta"]["notes"])


def test_ontologia_enriquece_com_o_cadastro(monkeypatch):
    chamadas = []

    class _Es:
        def search(self, **kwargs):
            chamadas.append(kwargs)
            return {
                "hits": {
                    "hits": [
                        {
                            "_source": {
                                "nif": "510728189",
                                "name": "CLARANET II SOLUTIONS, S.A.",
                                "contracts_count": 3952,
                                "total_value": 624938766.0,
                                "cae_principal": "62010",
                                "country": "Portugal",
                            }
                        }
                    ]
                }
            }

    monkeypatch.setattr(analysis.search_service, "get_es_client", lambda *a, **k: _Es())

    grafo = analysis.ontologia_das_fontes([_fonte_contrato("C1")])

    empresa = _no(grafo, "entidade", "510728189")
    assert empresa["label"] == "CLARANET II SOLUTIONS, S.A."
    assert empresa["cae"] == "62010"
    assert empresa["global_contracts"] == 3952
    # O `count` do nó é o da resposta (é sobre ela que o grafo fala), não o global.
    assert empresa["count"] == 1
    assert chamadas[0]["index"] == analysis.vectors.ENTITIES_INDEX
    assert chamadas[0]["body"]["query"] == {"terms": {"nif": ["506606013", "510728189"]}}


# --------------------------------------------------------------------- analogias

class _EsAnalogias:
    """Cliente falso que responde a cada consulta das analogias pelo seu corpo."""

    def __init__(self, *, alvo=None, vizinhos=None, mercado=None, mesmo_cpv=None, falhar_em=()):
        self.alvo = alvo or []
        self.vizinhos = vizinhos or []
        self.mercado = mercado or {}
        self.mesmo_cpv = mesmo_cpv or []
        self.falhar_em = falhar_em
        self.pedidos = []

    def search(self, **kwargs):
        body = kwargs.get("body") or {}
        self.pedidos.append(body)
        if "knn" in body:
            if "knn" in self.falhar_em:
                raise RuntimeError("kNN indisponível")
            return {"hits": {"hits": self.vizinhos}}
        if "aggs" in body:
            if "aggs" in self.falhar_em:
                raise RuntimeError("agregação indisponível")
            return {"aggregations": self.mercado}
        # Leitura do contrato alvo: é a única consulta com `query.ids` no topo.
        if "ids" in (body.get("query") or {}):
            return {"hits": {"hits": self.alvo}}
        if "sort" in body:
            return {"hits": {"hits": self.mesmo_cpv}}
        return {"hits": {"hits": []}}


def _hit(idcontrato: str, *, preco: float, titulo: str = "Contrato", score: float | None = None) -> dict:
    return {
        "_id": idcontrato,
        "_score": score,
        "_source": {
            "idcontrato": idcontrato,
            "objectoContrato": titulo,
            "precoContratual": preco,
            "cpv": [{"code": "72268000-1", "description": "Serviços de programação"}],
            "Ano": 2026,
            "adjudicantes": {"parsed": [{"nif": "506606013", "nome": "MUNICÍPIO DE LEIRIA"}]},
            "adjudicatarios": {"parsed": [{"nif": "510728189", "nome": "CLARANET II SOLUTIONS"}]},
        },
    }


def _agregacao_mercado(mediana: float = 10000.0, p25: float = 5000.0, p75: float = 20000.0) -> dict:
    return {
        "cpv": {
            "codigos": {
                "buckets": [
                    {
                        "key": "72268000-1",
                        "contratos": {
                            "doc_count": 100,
                            "preco": {"values": {"25.0": p25, "50.0": mediana, "75.0": p75}},
                            "minimo": {"value": 0.0},
                            "maximo": {"value": 900000.0},
                        },
                    }
                ]
            }
        }
    }


def _fonte_com_contrato(idcontrato: str = "C1") -> dict:
    return _fonte_contrato(idcontrato, preco=1000.0)


def test_analogias_usa_o_vector_do_proprio_contrato(monkeypatch):
    es = _EsAnalogias(
        alvo=[{"_id": "C1", "_source": {"idcontrato": "C1", "embedding": [0.1] * 384, "precoContratual": 1000.0, "cpv": [{"code": "72268000-1"}]}}],
        vizinhos=[_hit("V1", preco=990.0, titulo="Muito parecido", score=0.97)],
        mercado=_agregacao_mercado(),
    )
    monkeypatch.setattr(analogies.search_service, "get_es_client", lambda *a, **k: es)

    resultado = analogies.analogias([_fonte_com_contrato()], contratos=1, semelhantes=1)

    item = resultado["items"][0]
    assert item["contrato"]["id"] == "C1"
    assert item["semelhantes"][0]["id"] == "V1"
    assert item["semelhantes"][0]["porque"] == "semelhança semântica com este contrato"
    assert item["semelhantes"][0]["score"] == 0.97
    assert resultado["totals"]["semantic"] == 1
    # A consulta kNN tem de excluir o próprio contrato.
    knn = next(body for body in es.pedidos if "knn" in body)
    assert "C1" in json.dumps(knn["knn"].get("filter"))


def test_analogias_sem_vector_cai_no_mesmo_cpv_e_faixa_de_valor(monkeypatch):
    es = _EsAnalogias(
        alvo=[{"_id": "C1", "_source": {"idcontrato": "C1", "precoContratual": 1000.0, "cpv": [{"code": "72268000-1"}]}}],
        mesmo_cpv=[_hit("V2", preco=800.0, titulo="Mesmo CPV")],
        mercado=_agregacao_mercado(),
    )
    monkeypatch.setattr(analogies.search_service, "get_es_client", lambda *a, **k: es)

    resultado = analogies.analogias([_fonte_com_contrato()], contratos=1, semelhantes=1)

    semelhante = resultado["items"][0]["semelhantes"][0]
    assert semelhante["id"] == "V2"
    assert semelhante["porque"] == "mesmo CPV e valor na mesma faixa"
    assert semelhante["desvio_pct"] == -20.0
    assert resultado["totals"]["by_value"] == 1
    assert any("não tinham vector" in nota for nota in resultado["notes"])
    faixa = next(body for body in es.pedidos if "sort" in body)
    filtros = json.dumps(faixa["query"])
    assert "500.0" in filtros and "1500.0" in filtros  # ±50 % de 1000


def test_analogias_posicao_face_ao_mercado(monkeypatch):
    es = _EsAnalogias(
        alvo=[{"_id": "C1", "_source": {"idcontrato": "C1", "embedding": [0.2] * 384, "precoContratual": 40000.0, "cpv": [{"code": "72268000-1"}]}}],
        vizinhos=[_hit("V1", preco=39000.0)],
        mercado=_agregacao_mercado(mediana=10000.0, p25=5000.0, p75=20000.0),
    )
    monkeypatch.setattr(analogies.search_service, "get_es_client", lambda *a, **k: es)

    resultado = analogies.analogias([_fonte_com_contrato()], contratos=1, semelhantes=1)

    posicao = resultado["items"][0]["posicao"]
    assert posicao["estado"] == "acima"
    assert "p75" in posicao["frase"]
    assert posicao["vezes_a_mediana"] == 4.0


def test_analogias_sem_contratos_explica(monkeypatch):
    fonte = {"n": 1, "id": "E1", "scope": "entities", "title": "Empresa", "meta": {}, "links": []}

    resultado = analogies.analogias([fonte])

    assert resultado["items"] == []
    assert any("Nenhum contrato" in nota for nota in resultado["notes"])


def test_analogias_le_o_contrato_pelo_campo_idcontrato(monkeypatch):
    """O `_id` do documento nem sempre é o número do contrato.

    Era isto que fazia só um de cada três contratos ser lido (e comparado).
    """
    pedidos = []

    class _Es:
        def search(self, **kwargs):
            body = kwargs["body"]
            pedidos.append(body)
            if "term" in (body.get("query") or {}):
                return {"hits": {"hits": [{"_id": "doc-abc", "_source": {"idcontrato": "C9", "precoContratual": 100.0, "cpv": [{"code": "72268000-1"}]}}]}}
            if "aggs" in body:
                return {"aggregations": {}}
            if "sort" in body:
                return {"hits": {"hits": []}}
            return {"hits": {"hits": []}}

    monkeypatch.setattr(analogies.search_service, "get_es_client", lambda *a, **k: _Es())

    resultado = analogies.analogias([_fonte_contrato("C9", preco=100.0)], contratos=1, semelhantes=1)

    assert resultado["items"][0]["contrato"]["id"] == "C9"
    # A primeira tentativa é pelo campo, não pelo `_id`.
    assert "term" in pedidos[0]["query"]


def test_analogias_usa_o_id_do_documento_para_excluir_o_proprio(monkeypatch):
    es = _EsAnalogias(
        alvo=[{"_id": "doc-abc", "_source": {"idcontrato": "C1", "embedding": [0.3] * 384, "precoContratual": 1000.0, "cpv": [{"code": "72268000-1"}]}}],
        vizinhos=[_hit("V1", preco=900.0)],
        mercado=_agregacao_mercado(),
    )
    monkeypatch.setattr(analogies.search_service, "get_es_client", lambda *a, **k: es)

    analogies.analogias([_fonte_com_contrato()], contratos=1, semelhantes=1)

    knn = next(body for body in es.pedidos if "knn" in body)
    excluidos = json.dumps(knn["knn"].get("filter"))
    assert "doc-abc" in excluidos
    assert "C1" in excluidos


def test_analogias_aguenta_elasticsearch_em_baixo(monkeypatch):
    class _Es:
        def search(self, **kwargs):
            raise RuntimeError("Elasticsearch indisponível")

    monkeypatch.setattr(analogies.search_service, "get_es_client", lambda *a, **k: _Es())

    resultado = analogies.analogias([_fonte_com_contrato()])

    assert resultado["items"] == []
    assert resultado["error"] is None  # degradar não é falhar
    assert resultado["notes"]


# --------------------------------------------------------------------- análise

def test_digest_leva_os_numeros_que_o_modelo_precisa():
    grafo = analysis.ontologia_das_fontes([_fonte_contrato("C1", preco=40000.0)])
    analogias_calculadas = {
        "items": [
            {
                "contrato": {"id": "C1", "title": "Licenças de software", "preco": "40 000 €", "cpv": "72268000-1"},
                "semelhantes": [{"title": "Outro parecido", "preco": "39 000 €", "desvio_pct": -2.5, "porque": "semelhança semântica"}],
                "posicao": {"frase": "acima do p75 do mesmo CPV", "mediana": "10 000 €"},
            }
        ]
    }

    resumo = analysis._digest("Quanto custou?", grafo, analogias_calculadas, [_fonte_contrato("C1", preco=40000.0)])

    assert "### Ontologia" in resumo
    assert "### Analogias" in resumo
    assert "acima do p75" in resumo
    assert "Outro parecido" in resumo
    assert "MUNICÍPIO DE LEIRIA" in resumo
    assert "[1]" in resumo  # as fontes mantêm a numeração da resposta
    assert len(resumo) <= analysis.ANALISE_MAX_DIGEST


def test_analisar_sem_dados_explica_em_vez_de_chamar_o_modelo(monkeypatch):
    async def nao_devia(*args, **kwargs):
        raise AssertionError("não devia chamar o modelo")

    monkeypatch.setattr(analysis.deep, "_stream_model", nao_devia)

    resultado = asyncio.run(analysis.analisar("Pergunta", ontologia={"nodes": []}, analogias={"items": []}))

    assert resultado["texto"] == ""
    assert "Não há ontologia nem analogias" in resultado["error"]


def test_analisar_com_o_modelo(monkeypatch):
    visto = {}

    async def modelo(messages, **kwargs):
        visto["messages"] = messages
        visto["backend"] = kwargs.get("backend")
        yield "A ontologia mostra "
        yield "duas empresas."

    monkeypatch.setattr(analysis.deep, "_stream_model", modelo)
    monkeypatch.setattr(analysis.deep, "resolve_backend", lambda backend, user_id: {"label": "deepseek:deepseek-chat", "kind": "cloud"})

    resultado = asyncio.run(
        analysis.analisar(
            "Quanto custou?",
            ontologia=analysis.ontologia_das_fontes([_fonte_contrato("C1")]),
            backend="deepseek:deepseek-chat",
            user_id="u1",
        )
    )

    assert resultado["motor"] == "modelo"
    assert resultado["texto"] == "A ontologia mostra duas empresas."
    assert resultado["modelo"] == "deepseek:deepseek-chat"
    assert resultado["error"] is None
    assert visto["messages"][0]["role"] == "system"
    assert "### Ontologia" in visto["messages"][-1]["content"]


def test_analisar_falha_do_modelo_chega_ao_utilizador(monkeypatch):
    async def modelo(messages, **kwargs):
        raise RuntimeError("DeepSeek não respondeu a tempo.")
        yield ""  # pragma: no cover - mantém a função como gerador

    monkeypatch.setattr(analysis.deep, "_stream_model", modelo)
    monkeypatch.setattr(analysis.deep, "resolve_backend", lambda backend, user_id: {"label": "deepseek:deepseek-chat"})

    resultado = asyncio.run(analysis.analisar("Pergunta", ontologia=analysis.ontologia_das_fontes([_fonte_contrato("C1")])))

    assert resultado["texto"] == ""
    assert "não respondeu a tempo" in resultado["error"]


def test_analisar_com_o_hermes(monkeypatch):
    import api.hermes_service as hermes

    visto = {}

    async def ask(question, **kwargs):
        visto["question"] = question
        visto["depth"] = kwargs.get("depth")
        return {
            "mode": "ai",
            "backend": {"label": "deepseek:deepseek-chat"},
            "text": "O município concentra as adjudicações.",
            "evidence": [{"n": 1, "title": "Contrato C1", "url": "https://x"}],
            "steps": [{"focus": "contratos", "question": "quem ganhou?", "items": 3}],
            "facts": ["3 contratos"],
            "notes": ["amostra parcial"],
            "warnings": [],
            "followups": [],
            "stats": {"ms": 1200},
        }

    monkeypatch.setattr(hermes, "ask", ask)

    resultado = asyncio.run(
        analysis.analisar(
            "Quanto custou?",
            ontologia=analysis.ontologia_das_fontes([_fonte_contrato("C1")]),
            motor="hermes",
        )
    )

    assert resultado["motor"] == "hermes"
    assert resultado["modo"] == "ai"
    assert resultado["texto"] == "O município concentra as adjudicações."
    assert resultado["evidencias"][0]["title"] == "Contrato C1"
    assert resultado["passos"][0]["focus"] == "contratos"
    assert resultado["notes"] == ["amostra parcial"]
    # O resumo vai dentro da pergunta (o `ask` do Hermes só aceita texto).
    assert "### Ontologia" in visto["question"]
    assert len(visto["question"]) <= 1950
    assert visto["depth"] == "profunda"


def test_analisar_hermes_que_falha_nao_rebenta(monkeypatch):
    import api.hermes_service as hermes

    async def ask(question, **kwargs):
        raise RuntimeError("sem ligação")

    monkeypatch.setattr(hermes, "ask", ask)

    resultado = asyncio.run(
        analysis.analisar("Pergunta", ontologia=analysis.ontologia_das_fontes([_fonte_contrato("C1")]), motor="hermes")
    )

    assert resultado["texto"] == ""
    assert "Hermes falhou" in resultado["error"]
