"""Confirma a cobertura de localização no índice `finance_contribuintes`.

Uso:
    python _probe_contribuintes_location.py [nif]

Mostra os números de `contribuintes/status` (com localização, distritos,
concelhos), o topo de cada faceta e, se for indicado um NIF (ou se escolher um
com localização), a localização de uma ficha concreta.
"""

from __future__ import annotations

import json
import sys
import urllib.request

API = "http://127.0.0.1:8002"


def get(path: str) -> dict:
    with urllib.request.urlopen(f"{API}{path}", timeout=300) as response:
        return json.loads(response.read().decode("utf-8"))


def es(path: str, body: dict | None = None) -> dict:
    payload = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        f"http://127.0.0.1:9200{path}",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        return json.loads(response.read().decode("utf-8"))


def pick_nif(minimum: int = 3) -> tuple[str, str]:
    """Escolhe um contribuinte com localização e vários contratos."""
    data = es(
        "/finance_contribuintes/_search",
        {
            "size": 1,
            "query": {
                "bool": {
                    "filter": [
                        {"exists": {"field": "location.distrito"}},
                        {"range": {"contracts_count": {"gte": minimum}}},
                    ]
                }
            },
            "_source": ["nif", "name", "location", "contracts_count", "contracts_value"],
            "sort": [{"contracts_value": "desc"}],
        },
    )
    hit = data["hits"]["hits"][0]["_source"]
    print(f"  amostra do índice: {hit['nif']} {hit.get('name')} {json.dumps(hit.get('location'), ensure_ascii=False)}")
    return hit["nif"], hit.get("name") or ""


def main() -> int:
    nif = sys.argv[1] if len(sys.argv) > 1 else ""
    status = get("/contribuintes/status")
    print(f"documentos: {status['documents']}")
    print(f"com localização (distrito): {status['with_location']}")
    print(f"distritos: {len(status['districts'])} · concelhos: {len(status['municipalities'])}")
    print("top distritos:")
    for bucket in (status["districts"] or [])[:8]:
        print(f"  {bucket['count']:>8}  {bucket['key']}")
    print("top concelhos:")
    for bucket in (status["municipalities"] or [])[:6]:
        print(f"  {bucket['count']:>8}  {bucket['key']}")
    print(f"tipos x distrito: {len(status['types_by_district'])} combinações")
    for entry in (status["types_by_district"] or [])[:4]:
        tipos = ", ".join(f"{t['key']}={t['count']}" for t in (entry.get("types") or [])[:3])
        print(f"  {entry['key']}: {entry['count']} ({tipos}) valor={entry.get('value')}")

    if not nif:
        nif, name = pick_nif()
        print(f"contribuinte escolhido: {nif} ({name})")

    ficha = get(f"/contribuintes/{nif}")
    print(f"ficha {ficha.get('nif')} — {ficha.get('name')}")
    print(f"  localização: {json.dumps(ficha.get('location'), ensure_ascii=False)}")
    print(f"  país: {ficha.get('country')} · tipo: {ficha.get('type_label')}")
    print(f"  contratos: {ficha.get('contracts_count')} · valor: {ficha.get('contracts_value')}")
    for source in ficha.get("sources") or []:
        detail = (ficha.get(f"src_{source}") or {}).get("detail") or {}
        print(f"  fonte: {source}" + (f" · {json.dumps(detail, ensure_ascii=False)[:220]}" if detail else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
