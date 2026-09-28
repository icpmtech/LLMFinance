"""Sonda 2: validar o **filtro por papel** do CIRE (insolvente vs credor).

O índice lista em `nifs` todos os intervenientes do processo — inclui bancos,
AT e Segurança Social como credores. Aqui confirmamos, documento a documento,
qual é o papel de um dado NIF, e procuramos uma empresa realmente insolvente
(com contratos) para validar o componente de insolvência do motor de risco.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.elasticsearch_client import CONTRIBUINTES_INDEX, get_es_client  # noqa: E402
from api.padroes_service import CIRE_INDEX, fold, _client  # noqa: E402
from api.risco_service import insolvencias_da_empresa  # noqa: E402

CREDORES_CONHECIDOS = ["513204016", "505305500", "600084779", "500792615"]


def papeis_por_nif(client, nif: str, limite: int = 5) -> list[tuple[str, str]]:
    resp = client.search(
        index=CIRE_INDEX,
        body={
            "size": limite,
            "track_total_hits": False,
            "_source": ["insolvente", "processo_numero", "intervenientes"],
            "query": {"terms": {"nifs": [nif]}},
        },
    )
    saida = []
    for hit in (resp.get("hits") or {}).get("hits") or []:
        src = hit.get("_source") or {}
        for entry in src.get("intervenientes") or []:
            if isinstance(entry, dict) and str(entry.get("nif") or "") == nif:
                saida.append((str(entry.get("papel") or ""), str(src.get("insolvente") or "")[:40]))
    return saida


def main() -> None:
    client = _client(None) or get_es_client()
    if client is None:
        print("ES indisponível")
        return

    print("== NIFs que são credores conhecidos (banca/AT/SS) ==")
    for nif in CREDORES_CONHECIDOS:
        papeis = papeis_por_nif(client, nif, limite=3)
        filtradas = insolvencias_da_empresa(client, nif)
        print(f"  {nif}: papeis={[p[0] for p in papeis]} · insolvencias_filtradas={len(filtradas)}")

    print("\n== Empresas realmente insolventes, com contratos como adjudicatárias ==")
    achados = 0
    corte = None
    for _ in range(4):
        body = {
            "size": 500,
            "track_total_hits": False,
            "_source": ["insolvente", "processo_numero", "data_publicacao", "intervenientes"],
            "query": {"nested": {"path": "intervenientes", "query": {"match": {"intervenientes.papel": "Insolvente"}}}},
            "sort": [{"data_publicacao": {"order": "desc", "unmapped_type": "date"}}],
        }
        if corte:
            body["search_after"] = corte
        resp = client.search(index=CIRE_INDEX, body=body)
        hits = (resp.get("hits") or {}).get("hits") or []
        if not hits:
            break
        corte = hits[-1].get("sort")
        for hit in hits:
            src = hit.get("_source") or {}
            insolventes = [
                str(entry.get("nif") or "")
                for entry in src.get("intervenientes") or []
                if isinstance(entry, dict) and "insolvente" in fold(entry.get("papel")) and entry.get("nif")
            ]
            for nif in insolventes:
                contratos = client.count(
                    index="contratos",
                    body={
                        "query": {
                            "nested": {
                                "path": "adjudicatarios.parsed",
                                "query": {"term": {"adjudicatarios.parsed.nif": nif}},
                            }
                        }
                    },
                )["count"]
                if contratos < 5:
                    continue
                nome_hit = client.search(
                    index=CONTRIBUINTES_INDEX,
                    body={"size": 1, "track_total_hits": False, "_source": ["name"], "query": {"term": {"nif": nif}}},
                )
                nome = ((nome_hit.get("hits") or {}).get("hits") or [{}])[0].get("_source", {}).get("name")
                filtradas = insolvencias_da_empresa(client, nif)
                print(
                    f"  {nif} · contratos={contratos} · insolvencias_filtradas={len(filtradas)} · "
                    f"especie={src.get('especie')} · nome={nome}"
                )
                achados += 1
                if achados >= 4:
                    return
    if not achados:
        print("  (nenhuma encontrada nesta amostra)")


if __name__ == "__main__":
    main()
