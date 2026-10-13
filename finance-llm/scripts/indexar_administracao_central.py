"""Constrói o índice das entidades da Administração Central (INE / SEC 2010).

Lê o PDF «Entidades que integram o Setor Institucional das Administrações
Públicas» (a edição anual do INE, em `data/entidades-sector/`), liga cada
entidade ao NIF com que contrata no portal BASE — usando as agregações do índice
de contratos — e grava `data/entidades-sector/administracao-central.json`.

É o mesmo trabalho que `POST /administracao-central/reindexar` faz a pedido da
interface; este script existe para o poder correr **fora da API** e para ver o
relatório de cobertura (que entidades ficaram sem NIF e porquê).

Uso::

    python scripts/indexar_administracao_central.py               # constrói e grava
    python scripts/indexar_administracao_central.py --relatorio    # lista todas as ligações
    python scripts/indexar_administracao_central.py --sem-contratos  # só o PDF (sem ES)
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api import administracao_central_service as administracao_central  # noqa: E402


def _relatorio(indice: dict, detalhado: bool) -> None:
    tipos = Counter(item["ligacao"] for item in indice["entidades"])
    print(f"\nÍndice: {indice['total']} entidades — {indice['ligadas']} com NIF ligado")
    for subsetor in indice["subsetores"]:
        print(
            f"  {subsetor['id']:8} {subsetor['nome'][:52]:52} "
            f"{subsetor['ligadas']:>4}/{subsetor['total']:<4} ligadas"
        )
    print("  ligações: " + ", ".join(f"{tipo}={total}" for tipo, total in tipos.most_common()))

    sem_nif = [item for item in indice["entidades"] if not item["nif"]]
    if not sem_nif:
        return
    print(f"\nSem NIF ({len(sem_nif)}) — não contratam no portal BASE ou o nome diverge:")
    for item in sem_nif:
        print(f"   {item['subsetor']}  {item['nome']}")

    if detalhado:
        print("\nLigações:")
        for item in indice["entidades"]:
            if item["nif"]:
                print(
                    f"   {item['ligacao'][:4]:4} {item['nome'][:64]:64} -> "
                    f"{item['nif']} {item['nome_contratos'] or ''} ({item['contratos']} contratos)"
                )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Índice das entidades da Administração Central (INE/SEC 2010).")
    parser.add_argument("--relatorio", action="store_true", help="lista todas as ligações nome→NIF")
    parser.add_argument("--sem-contratos", action="store_true", help="não consulta o Elasticsearch (só o PDF)")
    parser.add_argument("--destino", type=Path, default=None, help="ficheiro de destino (JSON)")
    args = parser.parse_args(argv)

    print(f"A ler {administracao_central.PDF_FONTE.name}…")
    indice = administracao_central.reconstruir(usar_contratos=not args.sem_contratos, destino=args.destino)
    destino = args.destino or administracao_central.INDICE
    print(f"escrito {destino} ({destino.stat().st_size / 1024:.0f} KB)")
    _relatorio(indice, detalhado=args.relatorio)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
