"""Manutenção das recolhas de citações editais gravadas em `data/citacoes/runs`.

1. **Recalcula a análise** de cada documento a partir do texto já guardado
   (título, assunto, modelo, valor, prazo, NIF) — sem voltar a pedir os PDF ao
   portal, porque a análise é uma função pura do texto.
2. **Preenche a comarca judicial** nos éditos recolhidos antes de o campo existir.
3. **Reimporta** as recolhas alteradas (atualizando os documentos no índice).
4. Com `--apagar <run_id> <run_id>...` remove recolhas do disco **e** do índice
   (usado para descartar recolhas obsoletas depois de uma recolha mais completa).

Uso:
    python _fix_citacoes_runs.py                 # só relatório
    python _fix_citacoes_runs.py --aplicar       # recalcula e reimporta
    python _fix_citacoes_runs.py --apagar <id> --aplicar
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api import citacoes_service as sv  # noqa: E402
from collectors.citius_citacoes import (  # noqa: E402
    analyze_documento,
    comarca_judicial as comarca_de,
)


def corrigir_run(run_id: str, aplicar: bool) -> dict:
    """Recalcula a análise e a comarca judicial dos itens de uma recolha."""
    payload = sv.load_run(run_id)
    itens = payload.get("items") or []
    analises = comarcas = 0
    CHAVES_ANALISE = (
        "documento_titulo",
        "documento_assunto",
        "documento_modelo",
        "documento_referencia_interna",
        "documento_codigo",
        "documento_valor",
        "documento_prazo",
        "documento_partes",
        "documento_nifs",
    )

    for item in itens:
        if item.get("texto"):
            nova = analyze_documento(item["texto"])
            antigo = {k: item.get(k) for k in ("documento_titulo", "documento_assunto")}
            # A análise é substituída por inteiro: uma chave que já não se aplica
            # (ex.: um título mal escolhido) tem de sair, não ficar.
            for chave in CHAVES_ANALISE:
                if chave in nova:
                    continue
                if item.pop(chave, None) is not None:
                    analises += 1
            for chave, valor in nova.items():
                if valor in (None, "", [], {}):
                    item.pop(chave, None)
                    continue
                if item.get(chave) != valor:
                    analises += 1
                item[chave] = valor
            if antigo.get("documento_titulo") != item.get("documento_titulo"):
                print(f"    título: {antigo.get('documento_titulo')!r} → {item.get('documento_titulo')!r}")
        if not item.get("comarca_judicial"):
            item["comarca_judicial"] = comarca_de(item.get("tribunal"), item.get("tribunal_sede"))
            if item["comarca_judicial"]:
                comarcas += 1
        item.setdefault("has_texto", bool(item.get("texto")))

    resumo = {"run_id": run_id, "itens": len(itens), "campos_analise": analises, "comarcas": comarcas}
    if aplicar and (analises or comarcas):
        sv.save_run(payload, sv.load_run_meta(run_id))
        ing = sv.ingest_run(run_id, update_existing=True)
        resumo["indexados"] = ing.get("indexed_count")
        resumo["error"] = ing.get("error")
    return resumo


def main() -> int:
    parser = argparse.ArgumentParser(description="Manutenção das recolhas de citações editais")
    parser.add_argument("--aplicar", action="store_true", help="Gravar as correções e reimportar")
    parser.add_argument("--apagar", nargs="*", default=[], help="Recolhas a remover (disco + índice)")
    parser.add_argument("--listar", action="store_true", help="Só listar as recolhas")
    args = parser.parse_args()

    runs = sv.list_runs(200)
    print(f"{len(runs)} recolhas em {sv.RUNS_DIR}\n")
    for meta in runs:
        print(
            f"  {meta.get('run_id')} · {meta.get('collected')} éditos · "
            f"docs {meta.get('documentos_extraidos') or 0} · {meta.get('created_at')}"
        )
    if args.listar:
        return 0
    print()

    for meta in runs:
        run_id = str(meta.get("run_id"))
        if run_id in args.apagar:
            continue
        print(f"— {run_id}")
        resumo = corrigir_run(run_id, args.aplicar)
        print(
            f"  {resumo['itens']} itens · {resumo['campos_analise']} campos de análise · "
            f"{resumo['comarcas']} comarcas preenchidas"
            + (f" · indexados {resumo['indexados']}" if resumo.get("indexados") is not None else "")
        )

    for run_id in args.apagar:
        if not any(str(meta.get("run_id")) == run_id for meta in runs):
            print(f"— {run_id}: não encontrada")
            continue
        if not args.aplicar:
            print(f"— {run_id}: seria apagada (use --aplicar)")
            continue
        res = sv.delete_run(run_id, drop_index=True)
        print(f"— {run_id}: apagada ({res.get('removed')}) · índice: {res.get('index')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
