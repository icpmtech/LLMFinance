"""Teste HTTP dos endpoints do Visualizador (usa a instância em 127.0.0.1:8010)."""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8010"


def call(method: str, path: str, payload=None, raw: bool = False):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(f"{BASE}{path}", data=data, method=method,
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            body = response.read()
            if raw:
                return response.status, response.headers, body
            return response.status, json.loads(body.decode("utf-8"))
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8") or "{}")


status, meta = call("GET", "/visualizador/meta")
print(f"meta: {status} · datasets={len(meta['datasets'])} · tipos de gráfico={len(meta['chart_types'])}")
print("  privados indisponíveis:", [d["id"] for d in meta["datasets"] if not d["available"]])

status, detail = call("GET", "/visualizador/datasets/contrato")
print(f"dataset contrato: {status} · dimensões={len(detail['dimensions'])} medidas={len(detail['measures'])} "
      f"sugestões={len(detail['suggestions'])} count_field={detail['count_field']}")
print("  sugestões:", [s["title"] for s in detail["suggestions"]])

query = {"dataset": "contrato", "dimensions": ["regiao"], "measures": ["contagem", "soma_preco"],
         "limit": 4, "top_n": 3, "others": True,
         "formulas": [{"id": "ticket", "label": "Ticket médio", "expression": "[Soma de Preço contratual] / [Contagem]"}]}
status, result = call("POST", "/visualizador/query", query)
print(f"query: {status} · linhas={len(result.get('rows', []))} · totais={result.get('totals')}")
for row in result.get("rows", []):
    print(f"  {row.get('regiao')}: {row.get('contagem')} · {row.get('soma_preco')} · ticket={row.get('ticket')}")

status, records = call("POST", "/visualizador/records", {"dataset": "contrato", "size": 1, "filters": {"ano": 2024}})
print(f"records: {status} · total={records.get('total')} · colunas={len(records.get('columns', []))}")

status, values = call("POST", "/visualizador/values", {"dataset": "contrato", "field": "tipo_contrato", "limit": 4})
print(f"values: {status} · {values.get('items')}")

status, headers, content = call("POST", "/visualizador/export/csv", query, raw=True)
print(f"export csv: {status} · {len(content)} bytes · {headers.get('Content-Disposition')}")

status, headers, content = call("POST", "/visualizador/export/xlsx", query, raw=True)
print(f"export xlsx: {status} · {len(content)} bytes")

status, listing = call("GET", "/visualizador/dashboards")
print(f"dashboards (sem sessão): {status} · total={listing.get('total')} · nota={listing.get('note')}")

status, denied = call("POST", "/visualizador/dashboards", {"name": "Teste", "dataset": "contrato"})
print(f"guardar dashboard sem sessão: {status} · {str(denied)[:120]}")

status, private = call("POST", "/visualizador/query", {"dataset": "conta", "dimensions": ["estado"], "measures": ["contagem"]})
print(f"dataset privado sem sessão: {status} · erro={private.get('error')}")
