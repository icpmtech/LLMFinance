"""Teste rápido do motor do Visualizador (executar a partir de finance-llm).

Não faz parte da aplicação: serve para validar o catálogo, o motor de agregações
(incluindo campos aninhados dos contratos), as fórmulas, os datasets locais e as
exportações.
"""
from __future__ import annotations

import json
import sys
import time

sys.path.insert(0, ".")

from api import visualizador_service as service  # noqa: E402
from api.elasticsearch_client import get_es_client  # noqa: E402

RELATORIO = {}


def _log(title: str, value) -> None:
    print(f"\n=== {title} ===")
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str)[:2200])


client = get_es_client()
print("ES:", "disponível" if client else "INDISPONÍVEL")
if client:
    try:
        print("ES info:", client.info().get("version", {}).get("number"))
    except Exception as exc:
        print("ES info falhou:", exc)

catalog = service.catalog(scope=None)
RELATORIO["datasets"] = [item["id"] for item in catalog["datasets"]]
print("\nDatasets:", ", ".join(RELATORIO["datasets"]))
print("Indisponíveis (privados):", [d["id"] for d in catalog["datasets"] if not d["available"]])

# 1. Contratos por ano + fórmula (valor médio por contrato)
t0 = time.time()
res = service.run_query({
    "dataset": "contrato",
    "dimensions": ["ano"],
    "measures": ["contagem", "soma_preco", "media_preco"],
    "filters": {"ano": {"min": 2020}},
    "sort": {"by": "soma_preco", "order": "desc"},
    "limit": 10,
    "formulas": [{"id": "ticket_medio", "label": "Ticket médio", "expression": "[Soma de Preço contratual] / [Contagem]", "format": "currency"}],
    "top_n": 5,
    "others": True,
})
RELATORIO["por_ano"] = {
    "erro": res.get("error"),
    "ms": round((time.time() - t0) * 1000),
    "totais": res.get("totals"),
    "notas": res.get("meta", {}).get("notes"),
    "linhas": [{k: v for k, v in row.items() if not k.startswith("_")} for row in (res.get("rows") or [])],
    "truncado": res.get("meta", {}).get("truncated"),
}
_log("Contratos por ano (2020+) com Ticket médio", RELATORIO["por_ano"])

# 2. Dimensão aninhada (adjudicatário) + medida no documento (reverse_nested)
res2 = service.run_query({
    "dataset": "contrato",
    "dimensions": ["adjudicatario"],
    "measures": ["contagem", "soma_preco"],
    "filters": {"ano": {"min": 2023}},
    "limit": 5,
    "top_n": 5,
})
RELATORIO["aninhado"] = {
    "erro": res2.get("error"),
    "total_documentos": res2.get("meta", {}).get("documents"),
    "linhas": [{k: v for k, v in row.items() if not k.startswith("_")} for row in (res2.get("rows") or [])],
    "notas": res2.get("meta", {}).get("notes"),
}
_log("Top adjudicatários 2023+ (campo aninhado)", RELATORIO["aninhado"])

# 3. Duas dimensões: região × tipo de contrato
res3 = service.run_query({
    "dataset": "contrato",
    "dimensions": ["regiao", "tipo_contrato"],
    "measures": ["contagem", "soma_preco"],
    "limit": 4,
})
RELATORIO["cruzamento"] = {
    "erro": res3.get("error"),
    "linhas": [{k: v for k, v in row.items() if not k.startswith("_")} for row in (res3.get("rows") or [])],
}
_log("Região × Tipo de contrato", RELATORIO["cruzamento"])

# 4. Dataset agregado CPV (herda dimensões do tipo Contrato, no mesmo índice)
res4 = service.run_query({
    "dataset": "cpv",
    "dimensions": ["cpv"],
    "measures": ["contagem", "valor", "valor_medio"],
    "limit": 5,
    "sort": {"by": "valor", "order": "desc"},
    "top_n": 5,
})
RELATORIO["cpv"] = {
    "erro": res4.get("error"),
    "linhas": [{k: v for k, v in row.items() if not k.startswith("_")} for row in (res4.get("rows") or [])],
    "notas": res4.get("meta", {}).get("notes"),
}
_log("Top CPV por valor", RELATORIO["cpv"])

# 5. Série temporal (notícias por mês)
res5 = service.run_query({
    "dataset": "noticia",
    "dimensions": [{"id": "publicado", "interval": "mes"}],
    "measures": ["contagem"],
    "limit": 6,
})
RELATORIO["noticias"] = {
    "erro": res5.get("error"),
    "linhas": [{k: v for k, v in row.items() if not k.startswith("_")} for row in (res5.get("rows") or [])],
}
_log("Notícias por mês", RELATORIO["noticias"])

# 6. Dataset local (Office) — agregação em memória
res6 = service.run_query({"dataset": "documento", "dimensions": ["tipo", "pasta"], "measures": ["contagem", "palavras"], "limit": 6})
RELATORIO["office"] = {
    "erro": res6.get("error"),
    "linhas": [{k: v for k, v in row.items() if not k.startswith("_")} for row in (res6.get("rows") or [])],
    "notas": res6.get("meta", {}).get("notes"),
}
_log("Documentos Office por tipo/pasta", RELATORIO["office"])

# 7. Valores distintos (seletor de filtros)
values = service.distinct_values({"dataset": "contrato", "field": "regiao", "limit": 8})
RELATORIO["valores"] = values
_log("Regiões distintas", values)

# 8. Registos individuais (drill-through)
records = service.run_records({"dataset": "contrato", "size": 2, "filters": {"ano": 2024}})
RELATORIO["registos"] = {
    "erro": records.get("error"),
    "total": records.get("total"),
    "exemplo": {k: v for k, v in list((records.get("items") or [{}])[0].items())[:8]},
}
_log("Registos de contrato (drill-through)", RELATORIO["registos"])

# 9. Exportação
name, content, media = service.export_csv(res, "Contratos Públicos")
print(f"\nCSV: {name} · {media} · {len(content)} bytes")
print("\n".join(content.decode("utf-8-sig").splitlines()[:6]))
xname, xcontent, xmedia = service.export_xlsx(res, "Contratos Públicos")
print(f"\nXLSX: {xname} · {xmedia} · {len(xcontent)} bytes")
RELATORIO["export"] = [name, xname]

# 10. Fórmula inválida (deve devolver nota, não rebentar)
res7 = service.run_query({
    "dataset": "contrato",
    "dimensions": ["ano"],
    "measures": ["contagem"],
    "formulas": [{"id": "mau", "label": "Má formula", "expression": "[Nao Existe] + 1"}],
    "limit": 2,
})
print("\nFormula invalida ->", res7.get("meta", {}).get("notes"))
print("valor calculado:", [row.get("mau") for row in res7.get("rows") or []])
