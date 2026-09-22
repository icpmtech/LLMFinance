"""Estado dos fornecedores de IA (para saber que motor de sentimento usar)."""
from __future__ import annotations

import os

import httpx

from api import providers_service as providers

for spec in providers.PROVIDERS:
    env = spec.get("env") or ""
    value = os.getenv(env) if env else None
    print(
        "{id:14s} env={env:24s} chave={key:3s} key_optional={optional}".format(
            id=spec["id"],
            env=env or "-",
            key="sim" if value else "nao",
            optional=bool(spec.get("key_optional")),
        )
    )

try:
    resposta = httpx.get("http://127.0.0.1:11434/api/tags", timeout=4)
    modelos = [m["name"] for m in resposta.json().get("models", [])]
    print("ollama:", resposta.status_code, modelos[:6])
except Exception as exc:  # pragma: no cover - depende da máquina
    print("ollama: indisponivel", type(exc).__name__, exc)

# Chaves guardadas por utilizador os Elasticsearch.
from api.elasticsearch_client import get_es_client, ensure_indices  # noqa: E402

client = get_es_client()
if client:
    ensure_indices(client)
    try:
        resposta = client.search(index=providers.PROVIDER_KEYS_INDEX, body={"query": {"match_all": {}}, "size": 10})
        for hit in resposta["hits"]["hits"]:
            chaves = (hit["_source"].get("keys") or {}).keys()
            print("utilizador", hit["_id"], "fornecedores com chave:", list(chaves))
    except Exception as exc:
        print("sem indice de chaves:", exc)
