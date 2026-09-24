"""Prova real da agregação de contratos: confirma a forma da resposta.

Corre a mesma spec usada pela sincronização (nested sobre `adjudicantes.parsed`,
com `root_detail=["localExecucao"]`) numa página pequena e imprime o primeiro
bucket **em bruto**, para confirmar:
  * como vem o `_source` do `top_hits` aninhado (nome simples ou caminho?);
  * se o `reverse_nested` traz o `localExecucao` da raiz.
"""

from __future__ import annotations

import json

from elasticsearch import Elasticsearch

from api import contribuintes_service as service

ES = "http://127.0.0.1:9200"


def main() -> int:
    client = Elasticsearch(ES, request_timeout=300)
    source = service.SOURCE_BY_ID["contratos"]
    spec = {**source["specs"][0], "top_hits": service._spec_top_hits(spec=source["specs"][0])}
    # só empresas com contratos: evita páginas vazias
    spec = dict(spec)

    body = {"size": 0, "track_total_hits": False, "aggs": service._spec_aggs(spec, 3, None)}
    print("corpo da agregação:")
    print(json.dumps(body, ensure_ascii=False, indent=2)[:1200])

    response = client.search(index=source["index"], body=body, request_timeout=300)
    node = response["aggregations"]["n"]["c"]
    print("\nbuckets:", len(node.get("buckets") or []))
    for bucket in node.get("buckets", [])[:3]:
        print(" key:", bucket.get("key"), "docs:", bucket.get("doc_count"))
        print("  top:", json.dumps(bucket.get("top"), ensure_ascii=False)[:300])
        print("  back.root:", json.dumps((bucket.get("back") or {}).get("root"), ensure_ascii=False)[:300])

        payload = service._bucket_payload("contratos", spec, bucket)
        print("  payload:", json.dumps(payload, ensure_ascii=False)[:400])
        if payload:
            print("  localizacao:", service._location_from_local_execucao((payload.get("detail") or {}).get("localExecucao")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
