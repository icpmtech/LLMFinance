"""Repara concelho/distrito dos documentos Racius já indexados.

Usa a mesma resolução do coletor (`resolve_geo`): o par que segue «Morada» na
ficha é validado contra os 308 concelhos, pelo que a freguesia deixa de cair no
campo `concelho`. `--apply` grava; sem ele só mostra o que mudaria.
"""
import sys

from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk

sys.path.insert(0, r"C:\LLMFinance\finance-llm")
from collectors.racius import _geo_from_localizacao, resolve_geo  # noqa: E402

APPLY = "--apply" in sys.argv
es = Elasticsearch(["http://127.0.0.1:9200"], request_timeout=60)


def geo_do_documento(source):
    ficha = source.get("ficha") or {}
    items = list(ficha.items())
    for index, (key, value) in enumerate(items):
        if key.strip().lower() == "morada" and index + 1 < len(items):
            geo = resolve_geo(*items[index + 1])
            if geo:
                return geo
            break
    return _geo_from_localizacao(source.get("localizacao") or "")


def main():
    alteracoes = []
    docs = es.search(index="finance_racius", size=1000, query={"match_all": {}})["hits"]["hits"]
    for hit in docs:
        source = hit["_source"]
        geo = geo_do_documento(source)
        novo = {
            "concelho": geo.get("concelho"),
            "distrito": geo.get("distrito"),
            "localidade": geo.get("localidade"),
        }
        antigo = {k: source.get(k) for k in novo}
        if any(novo[k] != antigo[k] for k in novo):
            alteracoes.append({"id": hit["_id"], "antes": antigo, "depois": novo, "nome": source.get("nome")})

    print(f"finance_racius: {len(docs)} documentos, {len(alteracoes)} a corrigir")
    for item in alteracoes:
        print(f"  {item['nome'][:40]:40} {item['antes']} -> {item['depois']}")

    if APPLY and alteracoes:
        actions = [{"_op_type": "update", "_index": "finance_racius", "_id": a["id"], "doc": a["depois"]} for a in alteracoes]
        ok, errors = bulk(es, actions, refresh=True, raise_on_error=False)
        print(f"gravados: {ok}, erros: {len(errors) if isinstance(errors, list) else errors}")

    # Espelho em finance_scraped (fonte racius-diretorio).
    espelho = es.search(
        index="finance_scraped", size=1000, query={"term": {"source_id": "racius-diretorio"}}
    )["hits"]["hits"]
    acoes_espelho = []
    for hit in espelho:
        source = hit["_source"]
        data = source.get("data") or {}
        geo = geo_do_documento(data)
        if geo.get("concelho") != data.get("concelho") or geo.get("distrito") != data.get("distrito"):
            acoes_espelho.append(
                {
                    "_op_type": "update",
                    "_index": "finance_scraped",
                    "_id": hit["_id"],
                    "doc": {
                        "data.concelho": geo.get("concelho"),
                        "data.distrito": geo.get("distrito"),
                        "data.localidade": geo.get("localidade"),
                    },
                }
            )
    print(f"finance_scraped: {len(espelho)} documentos, {len(acoes_espelho)} a corrigir")
    if APPLY and acoes_espelho:
        ok, errors = bulk(es, acoes_espelho, refresh=True, raise_on_error=False)
        print(f"gravados: {ok}, erros: {len(errors) if isinstance(errors, list) else errors}")


if __name__ == "__main__":
    main()
