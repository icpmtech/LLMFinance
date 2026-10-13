"""Contagens de todos os indices finance_* no Elasticsearch local.

Corre no PC (usa ES_LOCAL) e na VM (usa ELASTICSEARCH_URL).
Imprime uma linha por indice, ordenada por nome, para diff directo.
"""

import json
import os
import sys
import urllib.error
import urllib.request

BASE = (
    os.environ.get("ES_BASE")
    or os.environ.get("ELASTICSEARCH_URL")
    or "http://127.0.0.1:9200"
)

prefixo = sys.argv[1] if len(sys.argv) > 1 else "finance_"


def pedir(caminho):
    with urllib.request.urlopen(f"{BASE}{caminho}", timeout=30) as resposta:
        return json.load(resposta)


try:
    indices = pedir("/_cat/indices?format=json&h=index,docs.count")
except (urllib.error.URLError, OSError) as exc:
    print(f"erro a contactar {BASE}: {exc}", file=sys.stderr)
    sys.exit(1)

linhas = []
for item in indices:
    nome = item.get("index", "")
    if not nome.startswith(prefixo) or nome.startswith("."):
        continue
    try:
        docs = int(item.get("docs.count") or 0)
    except ValueError:
        docs = -1
    linhas.append((nome, docs))

linhas.sort()
for nome, docs in linhas:
    print(f"{nome}\t{docs}")
print(f"__total__\t{len(linhas)}")
