"""Sonda: pesquisar **entidades** nos éditos por nome e filtrar.

    c:\\LLMFinance\\.venv\\Scripts\\python.exe _probe_citacoes_entidades.py [termo]

Mostra, por entidade, os éditos distintos, as grafias agrupadas, os papéis e os
NIF/NIPC dos documentos — e confirma que filtrar pelos nomes do grupo devolve
exatamente os éditos que o grupo conta.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api.elasticsearch_client import search_citacoes, search_citacoes_entidades  # noqa: E402


def show(termo: str | None = None) -> int:
    res = search_citacoes_entidades(q=termo, size=8)
    if res.get("error"):
        print("ERRO:", res["error"])
        return 1
    print(
        f"termo={termo!r} | éditos no conjunto: {res['total_editais']} | "
        f"entidades: {len(res['entities'])} | truncado: {res.get('truncated')}"
    )
    for item in res["entities"]:
        papeis = ", ".join(f"{p['key']}×{p['count']}" for p in item["papeis"][:3])
        nifs = ", ".join(n["key"] for n in item["documento_nifs"][:3]) or "—"
        print(f"  {item['editais']:>3} éditos · {item['mentions']:>3} menções · {item['name'][:58]}")
        print(f"        variantes={len(item['variants'])} · papéis: {papeis or '—'} · NIF do documento: {nifs}")
    if not res["entities"]:
        return 0

    # Coerência: o filtro pelas grafias do grupo tem de dar os éditos do grupo.
    grupo = res["entities"][0]
    filtrado = search_citacoes(nomes=grupo["nomes"], size=1, with_texto=False)
    ok = filtrado.get("total") == grupo["editais"]
    print(
        f"\ncoerência do grupo «{grupo['name'][:44]}»: grupo conta {grupo['editais']} éditos, "
        f"o filtro por {len(grupo['nomes'])} grafias devolve {filtrado.get('total')} → "
        f"{'OK' if ok else 'DIVERGENTE'}"
    )

    # Filtros combinados (papel + tipo) mudam o conjunto de entidades.
    com_filtro = search_citacoes_entidades(q=termo, tipo="Notificação", size=3)
    print(f"com tipo=Notificação: {com_filtro['total_editais']} éditos, {len(com_filtro['entities'])} entidades")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(show(sys.argv[1] if len(sys.argv) > 1 else None))
