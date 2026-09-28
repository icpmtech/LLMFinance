"""Sonda: porque é que a pesquisa por nome de empresa falha no cadastro?

Testa, sobre `finance_contribuintes`, o que a pesquisa atual devolve e o que
devolvem variantes de consulta (frase, `and` de tokens, autocomplete, NIF),
mostrando a pontuação e o nº de contratos. É a base para a correção da pesquisa
do módulo Empresas & Risco.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.elasticsearch_client import CONTRIBUINTES_INDEX, get_es_client  # noqa: E402

TERMOS = ["CLARANET, S.A.", "CLARANET PORTUGAL", "claranet", "Montepio Crédito", "Águas do Norte, SA", "nos comunicações", "Mota-Engil"]


def analisar(client, texto: str, campo: str) -> list[str]:
    try:
        resp = client.indices.analyze(index=CONTRIBUINTES_INDEX, body={"field": campo, "text": texto})
    except Exception as exc:  # noqa: BLE001
        return [f"<erro: {exc}>"]
    return [token["token"] for token in resp.get("tokens") or []]


def pesquisar(client, body: dict, etiqueta: str) -> None:
    try:
        resp = client.search(index=CONTRIBUINTES_INDEX, body=body)
    except Exception as exc:  # noqa: BLE001
        print(f"    {etiqueta}: ERRO {exc}")
        return
    hits = (resp.get("hits") or {}).get("hits") or []
    total = ((resp.get("hits") or {}).get("total") or {}).get("value")
    print(f"    {etiqueta}: total={total} → " + " | ".join(
        f"{h['_source'].get('name')} [{h['_source'].get('nif')}] c={h['_source'].get('contracts_count') or 0} s={h.get('_score')}"
        for h in hits[:4]
    ))


def main() -> None:
    client = get_es_client()
    if client is None:
        print("ES indisponível")
        return

    print("== mapeamento de `name`/`search_text` ==")
    mapping = client.indices.get_mapping(index=CONTRIBUINTES_INDEX)
    props = list(mapping.values())[0]["mappings"].get("properties", {})
    for campo in ("name", "names", "search_text", "nif", "contracts_count"):
        print(f"  {campo}: {props.get(campo)}")

    for texto in TERMOS:
        print(f"\n== {texto!r} ==")
        print(f"  tokens(name)={analisar(client, texto, 'name')}")
        print(f"  tokens(search_text)={analisar(client, texto, 'search_text')}")
        base = {"size": 4, "track_total_hits": True, "_source": ["name", "nif", "contracts_count"]}
        pesquisar(client, {**base, "query": {"match": {"name": {"query": texto, "operator": "and"}}}}, "match name AND")
        pesquisar(client, {**base, "query": {"match": {"name": {"query": texto, "operator": "or"}}}, "sort": [{"contracts_count": {"order": "desc", "missing": 0}}]}, "match name OR + sort contratos")
        pesquisar(client, {**base, "query": {"match_phrase": {"name": texto}}}, "match_phrase name")
        pesquisar(client, {**base, "query": {"match": {"name.autocomplete": {"query": texto, "operator": "and"}}}}, "autocomplete AND")
        pesquisar(client, {**base, "query": {"multi_match": {"query": texto, "fields": ["names^3", "name^2", "search_text"], "operator": "and"}}}, "multi_match AND")
        # variante com o que a pesquisa atual faz
        pesquisar(
            client,
            {
                **base,
                "query": {
                    "bool": {
                        "should": [
                            {"term": {"nif": texto}},
                            {"multi_match": {"query": texto, "fields": ["name^4", "name.autocomplete^3", "names^3", "nif^5", "search_text"], "type": "best_fields", "operator": "and", "boost": 3}},
                            {"multi_match": {"query": texto, "fields": ["name^4", "name.autocomplete^3", "names^3", "nif^5", "search_text"], "type": "best_fields", "operator": "or"}},
                        ],
                        "minimum_should_match": 1,
                    }
                },
                "sort": [{"contracts_count": {"order": "desc", "missing": 0}}, "_score"],
            },
            "atual (padrões) + sort contratos",
        )
        pesquisar(
            client,
            {
                **base,
                "query": {
                    "bool": {
                        "should": [
                            {"term": {"nif": texto}},
                            {"multi_match": {"query": texto, "fields": ["name^4", "name.autocomplete^3", "names^3", "nif^5", "search_text"], "type": "best_fields", "operator": "and", "boost": 3}},
                            {"multi_match": {"query": texto, "fields": ["name^4", "name.autocomplete^3", "names^3", "nif^5", "search_text"], "type": "best_fields", "operator": "or"}},
                        ],
                        "minimum_should_match": 1,
                    }
                },
                "sort": ["_score", {"contracts_count": {"order": "desc", "missing": 0}}],
            },
            "atual (padrões) + sort relevância",
        )
        # filtro de contratos, como a pesquisa do risco usa
        pesquisar(
            client,
            {
                **base,
                "query": {
                    "bool": {
                        "must": [{"multi_match": {"query": texto, "fields": ["names^3", "name^2", "search_text"], "operator": "and"}}],
                        "filter": [{"range": {"contracts_count": {"gte": 1}}}],
                    }
                },
            },
            "AND + has_contracts",
        )


if __name__ == "__main__":
    main()
