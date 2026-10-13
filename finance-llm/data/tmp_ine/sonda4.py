"""Sonda 4: mapping real de `adjudicantes` e contagens com acentos corretos."""
import json

from api.elasticsearch_client import CONTRACTS_INDEX, get_es_client

client = get_es_client()
mp = client.indices.get_mapping(index=CONTRACTS_INDEX)[CONTRACTS_INDEX]["mappings"]["properties"]
print("adjudicantes (live mapping):")
print(json.dumps(mp.get("adjudicantes"), ensure_ascii=False, indent=1)[:1500])
print("\nlocalExecucao:", json.dumps(mp.get("localExecucao"), ensure_ascii=False))
print("precoContratual:", json.dumps(mp.get("precoContratual"), ensure_ascii=False))
print("dataCelebracaoContrato:", json.dumps(mp.get("dataCelebracaoContrato"), ensure_ascii=False))


def contar(rotulo, query):
    try:
        r = client.count(index=CONTRACTS_INDEX, body={"query": query})
        print(f"{r['count']:>10}  {rotulo}")
    except Exception as exc:
        print(f"{'ERRO':>10}  {rotulo} -> {str(exc)[:120]}")


for termo in ("Município de", "Câmara Municipal", "Camara Municipal", "Municipio de"):
    contar(
        f"parsed.nome match_phrase '{termo}'",
        {"nested": {"path": "adjudicantes.parsed", "query": {"match_phrase": {"adjudicantes.parsed.nome": termo}}}},
    )
