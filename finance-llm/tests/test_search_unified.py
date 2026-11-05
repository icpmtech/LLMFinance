from api import search_service


def test_unified_search_includes_execucoes_with_filters(monkeypatch):
    received = {}
    facets = {
        "estado": [{"key": "Ativa", "count": 3}],
        "comarca": [{"key": "Lisboa", "count": 2}],
        "tribunal": [{"key": "Tribunal Judicial", "count": 1}],
        "agente_execucao": [{"key": "Agente A", "count": 1}],
    }

    def fake_search_execucoes(**kwargs):
        received.update(kwargs)
        return {
            "total": 1,
            "items": [
                {
                    "pub_id": "public-id",
                    "nome_executado": "Pessoa Exemplo",
                    "numero_processo": "123/24.0T8LSB",
                    "data_entrada": "2024-01-02",
                    "extra": {"estado": "Ativa", "comarca": "Lisboa"},
                }
            ],
            "facets": facets,
        }

    monkeypatch.setattr(search_service, "get_es_client", lambda: object())
    monkeypatch.setattr(search_service, "ensure_indices", lambda _client: None)
    monkeypatch.setattr(search_service, "search_execucoes", fake_search_execucoes)

    result = search_service.unified_search(
        "Pessoa Exemplo",
        scope="execucoes",
        filters='{"estado":"Ativa"}',
    )

    assert "execucoes" in search_service.SCOPE_IDS
    assert received["q"] == "Pessoa Exemplo"
    assert received["estado"] == "Ativa"
    group = result["groups"][0]
    assert group["scope"] == "execucoes"
    assert group["items"][0]["title"] == "Pessoa Exemplo"
    assert group["filters"][0]["name"] == "estado"
    assert group["filters"][0]["values"] == facets["estado"]
