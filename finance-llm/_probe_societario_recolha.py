"""Serviço da recolha massiva: alvos, ficheiros JSON e indexação."""
from __future__ import annotations

import json
import os

os.environ.setdefault("ELASTICSEARCH_URL", "http://127.0.0.1:9200")

from api import societario_recolha as recolha  # noqa: E402

TESTE_NIF = "999999999"


def main() -> None:
    print("=== meta ===")
    print(json.dumps(recolha.meta(), ensure_ascii=False, indent=2))

    print("\n=== alvos: 2024, adjudicatário, min 50 contratos ===")
    res = recolha.targets(ano_ini=2024, ano_fim=2024, papel="adjudicatario", min_contracts=50, limit=3, exclude_collected=False)
    for item in res.get("items", []):
        print(f"  {item['nif']} {(item.get('name') or '')[:40]:<40} periodo={item.get('period_contracts')} pubs={item['publications_count']}")

    print("\n=== escrita/leitura de um ficheiro de teste ===")
    escrito = recolha.write_export(
        TESTE_NIF,
        "EMPRESA DE TESTE, LDA",
        [
            {"pub_id": "t1", "data_publicacao": "2021-03-04", "acto": "Designação"},
            {"pub_id": "t2", "data_publicacao": "2022-05-06", "acto": "Prestação de contas"},
        ],
        criteria={"nif": TESTE_NIF},
    )
    print("  1ª escrita:", escrito)
    # repetir com uma publicação nova e uma duplicada
    escrito2 = recolha.write_export(
        TESTE_NIF,
        None,
        [
            {"pub_id": "t2", "data_publicacao": "2022-05-06", "acto": "Prestação de contas"},
            {"pub_id": "t3", "data_publicacao": "2023-07-08", "acto": "Cessação"},
        ],
    )
    print("  2ª escrita:", escrito2)

    ficheiro = recolha.read_export(TESTE_NIF)
    print(f"  ficheiro: total={ficheiro.get('total')} ids={[i['pub_id'] for i in ficheiro.get('items', [])]}")
    print(f"  cabeçalho: nif={ficheiro.get('nif')} nome={ficheiro.get('name')} criterios={ficheiro.get('criteria')}")

    listagem = recolha.list_exports()
    print(f"  manifest: {listagem['total']} ficheiro(s), {listagem['publications']} publicações, pasta={listagem['dir']}")

    preview = recolha.read_export(TESTE_NIF, limit_items=1)
    print(f"  pré-visualização: itens={len(preview.get('items') or [])} de {preview.get('items_total')}")

    print("\n=== apagar o ficheiro de teste ===")
    print(" ", recolha.delete_export(TESTE_NIF))
    print("  manifest agora:", recolha.list_exports()["total"], "ficheiro(s)")


if __name__ == "__main__":
    main()
