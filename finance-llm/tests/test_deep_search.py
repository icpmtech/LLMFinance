"""Testes da Pesquisa profunda (recuperação, citações e fluxo SSE)."""
from __future__ import annotations

import asyncio
import json

import pytest

from api import deep_search_service as deep


# --------------------------------------------------------------------- auxiliares

def _item(scope: str, item_id: str, title: str, *, snippet: str = "", url: str = "", date=None, **extra):
    return {
        "scope": scope,
        "id": item_id,
        "title": title,
        "subtitle": "",
        "snippet": snippet,
        "url": url,
        "date": date,
        "badges": [],
        "image": "",
        "extra": extra,
        "open": None,
    }


def _group(scope: str, items):
    return {"scope": scope, "label": scope, "total": len(items), "items": items, "took_ms": 5, "error": None}


@pytest.fixture(autouse=True)
def _isolate_vectors(monkeypatch):
    """Por omissão os testes não tocam no modelo de embeddings nem no Elasticsearch
    para vectores: quem quiser testar o kNN substitui `vector_coverage`/`vector_search`."""
    monkeypatch.setattr(deep, "vector_coverage", lambda refresh=False: {"scopes": {}})
    monkeypatch.setattr(deep.vectors, "vector_search", lambda *a, **k: {"items": [], "total": 0})


def _coverage(**scopes):
    """Cobertura vectorial para o teste: `_coverage(entities=(214123, 214123))`."""
    out = {}
    for scope_id, (with_embedding, total) in scopes.items():
        out[scope_id] = {
            "index": deep.VECTOR_INDEXES[scope_id],
            "with_embedding": with_embedding,
            "total": total,
            "ready": with_embedding > 0,
            "percent": round(100.0 * with_embedding / total, 2) if total else 0.0,
        }
    return {"scopes": out}


def _entity_row():
    """Documento de entidade tal como sai do kNN (`finance_entities`)."""
    return {
        "nif": "503504564",
        "name": "CLARANET II SOLUTIONS, S.A.",
        "country": "Portugal",
        "contracts_count": 3952,
        "total_value": 1000.0,
        "vector_score": 0.91,
    }


def _fake_unified(groups, *, error=None, calls=None):
    """Substitui `search_service.unified_search` por uma resposta fixa."""

    def fake(q, *, scope="all", size=8, offset=0, filters=None, session_scope=None):
        if calls is not None:
            calls.append({"q": q, "scope": scope, "size": size, "session_scope": session_scope})
        payload = {"query": q, "total": 0, "took_ms": 7, "groups": list(groups)}
        if error:
            payload["error"] = error
        return payload

    return fake


def _events(stream_chunks):
    """Converte as linhas SSE numa lista de `(evento, dados)`."""
    parsed = []
    for block in "".join(stream_chunks).split("\n\n"):
        event, data = "message", None
        for line in block.split("\n"):
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data = json.loads(line[5:].strip())
        if data is not None:
            parsed.append((event, data))
    return parsed


# --------------------------------------------------------------------- recuperação

def test_retrieve_numera_fontes_e_remove_repetidos(monkeypatch):
    monkeypatch.setattr(
        deep.search_service,
        "unified_search",
        _fake_unified(
            [
                _group(
                    "contracts",
                    [
                        _item("contracts", "1", "Contrato de videovigilância Leiria", snippet="manutenção 2026"),
                        _item("contracts", "1", "Contrato de videovigilância Leiria", snippet="repetido"),
                    ],
                ),
                _group("imprensa", [_item("imprensa", "n1", "Notícia sobre a CIMRL", url="https://eco.pt/x")]),
            ]
        ),
    )

    result = deep.retrieve("videovigilância Leiria", sources=["contracts", "imprensa"], max_sources=5)

    assert result["error"] is None
    assert [source["n"] for source in result["sources"]] == [1, 2]
    # O contrato (peso 1.0) vem antes da notícia (peso 0.85) e o id repetido cai.
    assert result["sources"][0]["scope"] == "contracts"
    assert result["sources"][0]["id"] == "1"
    assert result["sources"][1]["scope"] == "imprensa"
    # O rótulo vem do catálogo de âmbitos (e não da resposta da pesquisa).
    assert result["sources"][1]["scope_label"] == "Imprensa"


def test_retrieve_respeita_ambitos_escolhidos(monkeypatch):
    chamadas = []
    monkeypatch.setattr(
        deep.search_service,
        "unified_search",
        _fake_unified(
            [_group("contracts", [_item("contracts", "1", "Um")]), _group("social", [_item("social", "s1", "Post")])],
            calls=chamadas,
        ),
    )

    result = deep.retrieve("contratos", sources=["contracts"], max_sources=5)

    assert result["searched"] == ["contracts"]
    assert {source["scope"] for source in result["sources"]} == {"contracts"}
    # Uma só ida ao Elasticsearch, com o tamanho pedido por âmbito.
    assert len(chamadas) == 1 and chamadas[0]["scope"] == "all"


def test_retrieve_exclui_crm_sem_sessao(monkeypatch):
    monkeypatch.setattr(deep.search_service, "unified_search", _fake_unified([_group("contracts", [])]))

    result = deep.retrieve("contratos", sources=["contracts", "crm"])

    assert "crm" not in result["searched"]


def test_retrieve_com_elasticsearch_em_baixo(monkeypatch):
    monkeypatch.setattr(
        deep.search_service, "unified_search", _fake_unified([], error="Elasticsearch indisponível")
    )

    result = deep.retrieve("contratos")

    assert result["sources"] == []
    assert result["error"] == "Elasticsearch indisponível"


def test_retrieve_sem_pergunta():
    result = deep.retrieve("   ")

    assert result["sources"] == []
    assert result["error"] == "Pergunta vazia."


def test_source_catalog_tem_limites_e_predefinicoes():
    catalog = deep.source_catalog()

    ids = [entry["id"] for entry in catalog["sources"]]
    assert "contracts" in ids and "crm" in ids
    assert catalog["defaults"], "deve haver âmbitos ligados por omissão"
    assert catalog["limits"]["max_sources"]["default"] == deep.MAX_SOURCES_DEFAULT
    assert catalog["sources"][ids.index("crm")]["kind"] == "interno"
    # Modos de recuperação e marca dos âmbitos que podem fazer kNN.
    assert [mode["id"] for mode in catalog["modes"]] == ["hybrid", "text", "vector"]
    assert catalog["default_mode"] == "hybrid"
    assert catalog["sources"][ids.index("contracts")]["vector"] is True
    assert catalog["sources"][ids.index("imprensa")]["vector"] is False
    # Perguntas de exemplo e «sem limite» vêm do catálogo (uma só verdade).
    assert catalog["examples"] == deep.EXAMPLES
    assert catalog["limits"]["unlimited"] == deep.UNLIMITED
    assert catalog["limits"]["citable_max"] == deep.CITABLE_MAX


# --------------------------------------------------------------------- prompt e citações

def test_build_messages_numera_fontes_e_inclui_historico():
    sources = [
        {"n": 1, "scope_label": "Contratos", "title": "CIMRL", "subtitle": "A → B", "date": "2026-09-12", "url": "https://x", "snippet": "74 900 €"},
        {"n": 2, "scope_label": "Imprensa", "title": "Notícia", "snippet": "texto"},
    ]

    messages = deep.build_messages("Quem ganhou?", sources, [{"role": "user", "content": "Olá"}, {"role": "assistant", "content": "Bom dia"}])

    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == deep.SYSTEM_PROMPT
    prompt = messages[-1]["content"]
    assert "[1] Contratos · CIMRL" in prompt
    assert "74 900 €" in prompt
    assert "Quem ganhou?" in prompt
    # Histórico entra antes da pergunta atual, pela ordem original.
    assert [m["content"] for m in messages[1:-1]] == ["Olá", "Bom dia"]


def test_citacoes_extraidas_da_resposta():
    answer = "A CIMRL adjudicou [1] e o valor consta em [2, 3]. Uma nota solta [9] fica de fora."

    assert deep._cited_numbers(answer, 4) == [1, 2, 3]

    sources = [{"n": n, "id": f"i{n}"} for n in range(1, 5)]
    assert [s["n"] for s in deep.cited_sources(answer, sources)] == [1, 2, 3]
    assert deep.referenced_ids(answer, sources) == ["i1", "i2", "i3"]
    # Sem citações, devolvem-se todas as fontes (a UI mostrou-as todas).
    assert len(deep.cited_sources("sem marcas", sources)) == 4


# --------------------------------------------------------------------- fluxo SSE

def _stub_retrieve(sources, *, error=None, searched=None):
    def fake(question, **kwargs):
        return {
            "question": question,
            "sources": sources,
            "searched": searched or ["contracts"],
            "took_ms": 12,
            "error": error,
        }

    return fake


def test_stream_answer_envia_fontes_depois_tokens_e_fim(monkeypatch):
    sources = [
        {
            "n": 1,
            "id": "1",
            "scope": "contracts",
            "scope_label": "Contratos",
            "title": "CIMRL",
            "subtitle": "",
            "snippet": "…",
            "url": "",
            "badges": [],
        }
    ]
    monkeypatch.setattr(deep, "retrieve", _stub_retrieve(sources))

    async def fake_model(messages, *, backend, user_id, temperature, max_tokens):
        assert "[1] Contratos · CIMRL" in messages[-1]["content"]
        yield "A CIMRL "
        yield "adjudicou [1]."

    monkeypatch.setattr(deep, "_stream_model", fake_model)

    events = _events(asyncio.run(_collect(deep.stream_answer("contratos da CIMRL", backend="deepseek:deepseek-chat"))))

    names = [name for name, _ in events]
    assert names[0] == "sources"
    assert names[1] == "meta"
    assert names[-1] == "done"
    assert names.count("done") == 1

    assert events[0][1]["sources"][0]["n"] == 1
    assert events[0][1]["model"] == "deepseek:deepseek-chat"
    assert "".join(data.get("token", "") for _, data in events) == "A CIMRL adjudicou [1]."
    assert events[-1][1]["citations"] == [1]
    assert events[-1][1]["answer"] == "A CIMRL adjudicou [1]."


def test_stream_answer_sem_fontes_explica_em_vez_de_inventar(monkeypatch):
    monkeypatch.setattr(deep, "retrieve", _stub_retrieve([]))

    async def fake_model(messages, **kwargs):  # pragma: no cover - não deve ser chamado
        raise AssertionError("o modelo não deve ser chamado sem fontes")
        yield ""

    monkeypatch.setattr(deep, "_stream_model", fake_model)

    events = _events(asyncio.run(_collect(deep.stream_answer("pergunta sem dados"))))

    assert [name for name, _ in events][-1] == "done"
    assert events[0][1]["sources"] == []
    assert "Não encontrei nada" in events[-1][1]["answer"]


def test_stream_answer_falha_do_modelo_chega_ao_utilizador(monkeypatch):
    monkeypatch.setattr(
        deep,
        "retrieve",
        _stub_retrieve(
            [
                {
                    "n": 1,
                    "id": "1",
                    "scope": "contracts",
                    "scope_label": "Contratos",
                    "title": "Um",
                    "subtitle": "",
                    "snippet": "",
                    "url": "",
                    "badges": [],
                }
            ]
        ),
    )

    async def fake_model(messages, **kwargs):
        raise RuntimeError("chave inválida")
        yield ""

    monkeypatch.setattr(deep, "_stream_model", fake_model)

    events = _events(asyncio.run(_collect(deep.stream_answer("contratos"))))

    tokens = "".join(data.get("token", "") for _, data in events)
    assert "chave inválida" in tokens
    assert [name for name, _ in events][-1] == "done"


def test_stream_answer_erro_de_recuperacao(monkeypatch):
    monkeypatch.setattr(deep, "retrieve", _stub_retrieve([], error="Elasticsearch indisponível"))

    events = _events(asyncio.run(_collect(deep.stream_answer("contratos"))))

    assert events == [("error", {"message": "Elasticsearch indisponível"})]


async def _collect(stream):
    return [chunk async for chunk in stream]


# --------------------------------------------------------------------- backend/modelo

def test_resolve_backend_usa_predefinicoes_do_utilizador(monkeypatch):
    monkeypatch.setattr(
        deep.providers,
        "load_user_config",
        lambda user_id: {"keys": {}, "defaults": {"provider": "deepseek", "model": "deepseek-chat"}},
    )

    resolved = deep.resolve_backend("", "u1")

    assert resolved["kind"] == "cloud"
    assert resolved["provider"] == "deepseek"
    assert resolved["label"] == "deepseek:deepseek-chat"


def test_resolve_backend_sem_predefinicoes_cai_no_local():
    resolved = deep.resolve_backend("", None)

    assert resolved["kind"] == "local"
    assert resolved["backend"] == "gpt2"


def test_resolve_backend_com_modelo_explicito():
    resolved = deep.resolve_backend("openai:gpt-4o-mini", None)

    assert resolved["label"] == "openai:gpt-4o-mini"
    assert resolved["model"] == "gpt-4o-mini"


# --------------------------------------------------------------------- palavras-chave

@pytest.mark.parametrize(
    "question,expected",
    [
        ("CLARANET II SOLUTIONS quanto contratos?", "CLARANET II SOLUTIONS"),
        ("Quem ganhou mais contratos na saúde em 2025?", "saúde 2025"),
        # Termos genéricos deste corpus (aparecem em quase todos os contratos):
        # como a consulta exige todos os termos, mantê-los exclui os documentos
        # certos. Medido: «Quantos contratos tem a CLARANET II SOLUTIONS e qual o
        # valor total adjudicado?» atirava a entidade para 10.º lugar.
        (
            "Quantos contratos tem a CLARANET II SOLUTIONS e qual o valor total adjudicado?",
            "CLARANET II SOLUTIONS",
        ),
        ("contratos de obras públicas", "obras públicas"),
        # Só termos genéricos: recorre a eles em vez de devolver vazio.
        ("valor total dos contratos", "valor total contratos"),
    ],
)
def test_keywords_limpam_a_pergunta(question, expected):
    assert deep.keywords(question) == expected


def test_keywords_sem_termos_uteis():
    assert deep.keywords("quanto?") == ""
    assert deep.keywords("") == ""


def test_keywords_recorre_aos_genericos_se_nada_sobrar():
    """«quantos contratos?» não pode virar consulta vazia para o Elasticsearch."""
    assert deep.keywords("quantos contratos?") == "contratos"


def test_keywords_ignoram_termos_genericos_do_corpus():
    assert "contratos" not in deep.keywords("contratos da CLARANET")
    assert "valor" not in deep.keywords("valor dos contratos da CLARANET")


def test_retrieve_usa_palavras_chave_na_consulta(monkeypatch):
    """A pergunta em linguagem natural não vai crua para o BM25 (senão só traz ruído)."""
    chamadas = []
    monkeypatch.setattr(
        deep.search_service,
        "unified_search",
        _fake_unified([_group("contracts", [_item("contracts", "1", "Um")])], calls=chamadas),
    )

    deep.retrieve("CLARANET II SOLUTIONS quanto contratos?", sources=["contracts"])

    assert chamadas[0]["q"] == "CLARANET II SOLUTIONS"


def test_consulta_vetorial_usa_palavras_chave(monkeypatch):
    """A busca semântica tem de receber as palavras-chave, não a pergunta crua.

    Medido: com a pergunta inteira, a vizinhança de «Quantos contratos tem a
    CLARANET II SOLUTIONS e qual o valor total adjudicado?» devolvia
    «Solresor i Sverige AB» em 1.º e a CLARANET em 10.º.
    """
    vistas = []

    def vectors(index, query, top_k=20, **kwargs):
        vistas.append(query)
        return {"items": [_entity_row()], "total": 1}

    monkeypatch.setattr(deep.vectors, "vector_search", vectors)
    monkeypatch.setattr(deep, "vector_coverage", lambda refresh=False: _coverage(entities=(214123, 214123)))
    monkeypatch.setattr(deep.search_service, "unified_search", _fake_unified([]))

    deep.retrieve("Quantos contratos tem a CLARANET II SOLUTIONS e qual o valor total adjudicado?", max_sources=5)

    assert vistas == ["CLARANET II SOLUTIONS"]


def test_todos_os_ambitos_entram_por_omissao():
    catalog = deep.source_catalog()

    assert all(entry["default"] for entry in catalog["sources"])
    assert catalog["defaults"] == deep.SOURCE_IDS


# --------------------------------------------------------------------- híbrido (BM25 + kNN)

def test_hibrido_funde_texto_e_vectores(monkeypatch):
    def vectors(index, query, top_k=20, **kwargs):
        assert index == deep.VECTOR_INDEXES["entities"]
        return {"items": [_entity_row()], "total": 1}

    monkeypatch.setattr(deep.vectors, "vector_search", vectors)
    monkeypatch.setattr(deep, "vector_coverage", lambda refresh=False: _coverage(entities=(214123, 214123)))
    monkeypatch.setattr(
        deep.search_service,
        "unified_search",
        _fake_unified([_group("contracts", [_item("contracts", "c1", "Contrato da CLARANET")])]),
    )

    result = deep.retrieve("CLARANET II SOLUTIONS quanto contratos?", max_sources=5)

    assert result["mode"] == "hybrid"
    assert result["text_lists"] == 1 and result["vector_lists"] == 1
    titles = [source["title"] for source in result["sources"]]
    assert "Contrato da CLARANET" in titles
    entity = next(source for source in result["sources"] if source["scope"] == "entities")
    assert entity["title"] == "CLARANET II SOLUTIONS, S.A."
    assert "3952" in entity["snippet"]


def test_ambito_vectorial_com_pouca_cobertura_e_ignorado(monkeypatch):
    chamadas = []

    def vectors(index, query, top_k=20, **kwargs):  # pragma: no cover - não deve correr
        chamadas.append(index)
        return {"items": [], "total": 0}

    monkeypatch.setattr(deep.vectors, "vector_search", vectors)
    # 510 vectores em 2,25 M de contratos (0,02%): só traria ruído.
    monkeypatch.setattr(deep, "vector_coverage", lambda refresh=False: _coverage(contracts=(510, 2250969)))
    monkeypatch.setattr(
        deep.search_service,
        "unified_search",
        _fake_unified([_group("contracts", [_item("contracts", "c1", "Um contrato")])]),
    )

    result = deep.retrieve("contratos de software", sources=["contracts"])

    assert chamadas == []
    assert result["vector_lists"] == 0
    assert "contracts" in result["vector_skipped"]
    assert [source["scope"] for source in result["sources"]] == ["contracts"]


def test_modo_vector_sem_vectores_utilizaveis_cai_para_palavras(monkeypatch):
    monkeypatch.setattr(deep, "vector_coverage", lambda refresh=False: _coverage(contracts=(510, 2250969)))
    monkeypatch.setattr(
        deep.search_service,
        "unified_search",
        _fake_unified([_group("contracts", [_item("contracts", "c1", "Contrato relevante")])]),
    )

    result = deep.retrieve("contrato relevante", sources=["contracts"], mode="vector")

    assert result["mode"] == "text"
    assert [source["title"] for source in result["sources"]] == ["Contrato relevante"]


def test_modo_palavras_nao_chama_vectores(monkeypatch):
    chamadas = []

    def vectors(index, query, top_k=20, **kwargs):  # pragma: no cover - não deve correr
        chamadas.append(index)
        return {"items": [], "total": 0}

    monkeypatch.setattr(deep.vectors, "vector_search", vectors)
    monkeypatch.setattr(deep, "vector_coverage", lambda refresh=False: _coverage(entities=(214123, 214123)))
    monkeypatch.setattr(
        deep.search_service,
        "unified_search",
        _fake_unified([_group("contracts", [_item("contracts", "c1", "Um")])]),
    )

    result = deep.retrieve("um", mode="text")

    assert chamadas == []
    assert result["vector_lists"] == 0


def test_hibrido_reporta_erro_dos_vectores_sem_falhar(monkeypatch):
    monkeypatch.setattr(deep.vectors, "vector_search", lambda *a, **k: {"items": [], "error": "sentence-transformers não está instalado."})
    monkeypatch.setattr(deep, "vector_coverage", lambda refresh=False: _coverage(entities=(214123, 214123)))
    monkeypatch.setattr(
        deep.search_service,
        "unified_search",
        _fake_unified([_group("contracts", [_item("contracts", "c1", "Um")])]),
    )

    result = deep.retrieve("um", sources=["contracts", "entities"])

    assert result["error"] is None
    assert result["vector_error"] == "sentence-transformers não está instalado."
    assert result["sources"], "os resultados de palavras-chave continuam a valer"


def test_vector_is_usable_respeita_limiares():
    assert deep._vector_is_usable({"ready": True, "with_embedding": 214123, "percent": 100.0}) is True
    assert deep._vector_is_usable({"ready": True, "with_embedding": 510, "percent": 0.02}) is False
    assert deep._vector_is_usable({"ready": False, "with_embedding": 0, "percent": 0.0}) is False


# --------------------------------------------------------------------- sem limite


def test_max_sources_zero_devolve_tudo(monkeypatch):
    """`max_sources=0` é «sem limite»: não corta as fontes encontradas."""
    items = [_item("contracts", f"c{i}", f"Contrato {i}") for i in range(40)]
    monkeypatch.setattr(deep.search_service, "unified_search", _fake_unified([_group("contracts", items)]))

    result = deep.retrieve("contratos", sources=["contracts"], max_sources=0)

    assert result["unlimited"] is True
    assert len(result["sources"]) == 40
    assert result["citable_max"] == deep.CITABLE_MAX
    assert [source["n"] for source in result["sources"]] == list(range(1, 41))


def test_prompt_recebe_apenas_as_fontes_citaveis(monkeypatch):
    """Acima de `CITABLE_MAX` as fontes ficam na interface mas não no prompt."""
    total = deep.CITABLE_MAX + 20
    items = [_item("contracts", f"c{i}", f"Contrato {i}") for i in range(total)]
    monkeypatch.setattr(deep.search_service, "unified_search", _fake_unified([_group("contracts", items)]))

    seen = {}

    async def fake_model(messages, **kwargs):
        seen["prompt"] = messages[-1]["content"]
        yield "ok"

    monkeypatch.setattr(deep, "_stream_model", fake_model)

    events = _events(
        asyncio.run(_collect(deep.stream_answer("contratos", sources=["contracts"], max_sources=deep.UNLIMITED)))
    )

    sources_event = next(data for name, data in events if name == "sources")
    assert len(sources_event["sources"]) == total
    assert f"[{deep.CITABLE_MAX}]" in seen["prompt"]
    assert f"[{deep.CITABLE_MAX + 1}]" not in seen["prompt"]


# --------------------------------------------------------------------- sugestões


def test_suggest_terms_normaliza_a_resposta(monkeypatch):
    monkeypatch.setattr(
        deep.search_service,
        "suggest",
        lambda q, limit=8, session_scope=None: {
            "query": q,
            "items": [
                {
                    "text": "CLARANET PORTUGAL, S.A.",
                    "scope": "entities",
                    "kind": "entities",
                    "hint": "Empresa · NIF 503412031",
                    "arg": "503412031",
                }
            ],
        },
    )

    result = deep.suggest_terms("CLARAN")

    assert result["items"][0]["text"] == "CLARANET PORTUGAL, S.A."
    assert result["items"][0]["hint"].startswith("Empresa")


def test_suggest_terms_nao_quebra_com_elasticsearch_em_baixo(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("ES em baixo")

    monkeypatch.setattr(deep.search_service, "suggest", boom)

    assert deep.suggest_terms("CLARAN")["items"] == []


def test_followups_usam_entidade_e_adjudicatario():
    entity = {"scope": "entities", "title": "CLARANET II SOLUTIONS, S.A.", "subtitle": "", "snippet": ""}
    contract = {
        "scope": "contracts",
        "title": "Contrato X",
        "subtitle": "Município de Sesimbra → CLARANET II SOLUTIONS",
        "snippet": "",
    }

    suggestions = deep.followups("quantos contratos?", [contract, entity])

    assert any("Quantos contratos tem CLARANET II SOLUTIONS, S.A." in s for s in suggestions)
    assert any("adjudicados a CLARANET II SOLUTIONS" in s for s in suggestions)
    assert len(suggestions) <= 4
    assert len(suggestions) == len(set(suggestions)), "sem repetições"


def test_followups_sem_fontes_dao_perguntas_genericas():
    assert deep.followups("nada", []) == [
        "Que entidades adjudicaram mais contratos com estes termos?",
        "Como evoluiu o valor destes contratos por ano?",
    ]


@pytest.mark.parametrize(
    "subtitle,expected",
    [
        ("Município de X → CLARANET II SOLUTIONS, S.A.", "CLARANET II SOLUTIONS"),
        # O subtítulo ajunta o `extra` com «·» → o nome vinha repetido.
        ("Município de X → CLARANET II SOLUTIONS · CLARANET II SOLUTIONS", "CLARANET II SOLUTIONS"),
        ("Município de X → CLARANET II SOLUTIONS, S.A. · NIF 503412031", "CLARANET II SOLUTIONS"),
        ("Empresa A, Empresa B → CLARANET PORTUGAL, S.A., Outra Lda", "CLARANET PORTUGAL"),
        ("Claranet II Solutions, SA (Iten Solutions) → Iten", "Iten"),
        ("Adjudicatário: CLARANET PORTUGAL, S.A. · NIF 503412031", "CLARANET PORTUGAL"),
        ("", ""),
        ("sem seta nenhuma", ""),
    ],
)
def test_party_from_subtitle(subtitle, expected):
    assert deep._party_from_subtitle(subtitle) == expected


def test_followups_nao_repetem_o_nome_do_adjudicatario():
    """Regressão: «… adjudicados a CLARANET II SOLUTIONS · CLARANET II SOLUTIONS?»."""
    contract = {
        "scope": "contracts",
        "title": "Aquisição de licenciamento Adobe",
        "subtitle": "Município de Sesimbra → CLARANET II SOLUTIONS · CLARANET II SOLUTIONS",
        "snippet": "",
    }

    suggestions = deep.followups("contratos da claranet", [contract])

    assert suggestions[0] == "Que outros contratos foram adjudicados a CLARANET II SOLUTIONS?"
    assert all("CLARANET II SOLUTIONS · CLARANET" not in s for s in suggestions)


def test_followups_vem_na_resposta_da_recuperacao(monkeypatch):
    monkeypatch.setattr(
        deep.search_service,
        "unified_search",
        _fake_unified([_group("contracts", [_item("contracts", "c1", "Contrato da CIMRL")])]),
    )

    result = deep.retrieve("contratos da cimrl")

    assert result["suggestions"], "a recuperação sugere o passo seguinte"


@pytest.mark.parametrize("value,expected", [(1, deep.PER_SOURCE_MIN), (99, deep.PER_SOURCE_MAX), ("x", deep.PER_SOURCE_DEFAULT)])
def test_limites_sao_aproximados(value, expected):
    assert deep._clamp(value, deep.PER_SOURCE_MIN, deep.PER_SOURCE_MAX, deep.PER_SOURCE_DEFAULT) == expected
