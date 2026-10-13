"""Sonda 6: agregacao de contratos por adjudicante-municipio (valor e por ano)."""
import json
import re
import time

from api.elasticsearch_client import CONTRACTS_INDEX, get_es_client

client = get_es_client()

MUNICIPIO_RE = re.compile(r"^(?:Munic[íi]pio|C[âa]mara Municipal)\s+d[eo]\s+(?P<nome>.+)$", re.IGNORECASE)

query = {
    "size": 0,
    "query": {
        "nested": {
            "path": "adjudicantes.parsed",
            "query": {
                "bool": {
                    "should": [
                        {"wildcard": {"adjudicantes.parsed.nome": {"value": "*Município de*", "case_insensitive": True}}},
                        {"wildcard": {"adjudicantes.parsed.nome": {"value": "*Câmara Municipal*", "case_insensitive": True}}},
                    ],
                    "minimum_should_match": 1,
                }
            },
        }
    },
    "aggs": {
        "adj": {
            "nested": {"path": "adjudicantes.parsed"},
            "aggs": {
                "nomes": {
                    "terms": {"field": "adjudicantes.parsed.nome", "size": 2000},
                    "aggs": {
                        "raiz": {
                            "reverse_nested": {},
                            "aggs": {
                                "valor": {"sum": {"field": "precoContratual"}},
                                "por_ano": {
                                    "date_histogram": {
                                        "field": "dataCelebracaoContrato",
                                        "calendar_interval": "year",
                                        "format": "yyyy",
                                    }
                                },
                            },
                        }
                    },
                }
            },
        }
    },
}

t0 = time.time()
r = client.search(index=CONTRACTS_INDEX, body=query)
print(f"agregacao em {time.time()-t0:.1f}s")

buckets = r["aggregations"]["adj"]["nomes"]["buckets"]
print("adjudicantes municipais distintos:", len(buckets))

municipios = {}
for b in buckets:
    m = MUNICIPIO_RE.match(b["key"])
    if not m:
        continue
    nome = m.group("nome").strip()
    valor = b["raiz"]["valor"]["value"] or 0.0
    por_ano = {x["key_as_string"]: x["doc_count"] for x in b["raiz"]["por_ano"]["buckets"]}
    atual = municipios.get(nome)
    if atual:
        atual["contratos"] += b["doc_count"]
        atual["valor"] += valor
        for k, v in por_ano.items():
            atual["por_ano"][k] = atual["por_ano"].get(k, 0) + v
    else:
        municipios[nome] = {"contratos": b["doc_count"], "valor": valor, "por_ano": por_ano}

print("municipios reconhecidos:", len(municipios))
top = sorted(municipios.items(), key=lambda kv: -kv[1]["valor"])[:10]
for nome, d in top:
    print(f"   {nome:<28} {d['contratos']:>7} contratos  {d['valor']/1e6:>10.1f} M€  anos={sorted(d['por_ano'])}")

# nomes que nao casaram o padrao
nao_casados = [b["key"] for b in buckets if not MUNICIPIO_RE.match(b["key"])]
print("\nnomes municipais fora do padrao (top 10):")
for n in nao_casados[:10]:
    print("   ", n)

Path = __import__("pathlib").Path
out = Path(__file__).resolve().parent / "contratos_municipios.json"
out.write_text(json.dumps(municipios, ensure_ascii=False, indent=1), encoding="utf-8")
print("\nguardado:", out)
