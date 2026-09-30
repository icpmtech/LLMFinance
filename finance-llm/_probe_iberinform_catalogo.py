"""Mostra o catálogo do diretório: distritos e respetivos concelhos.

Uso:
    python _probe_iberinform_catalogo.py            # resumo por distrito
    python _probe_iberinform_catalogo.py evora      # concelhos de um distrito
    python _probe_iberinform_catalogo.py --refresh  # ignora a cache
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api import empresas_recolha_service as service  # noqa: E402


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    forcar = "--refresh" in sys.argv
    catalogo = service.catalogo(forcar=forcar)

    if args:
        alvo = args[0].strip().lower()
        distrito = next(
            (d for d in catalogo["distritos"] if d["slug"] == alvo or d["nome"].lower() == alvo),
            None,
        )
        if not distrito:
            print(f"Distrito não encontrado: {alvo}")
            return 1
        print(f"{distrito['nome']} ({distrito['slug']}): {len(distrito['concelhos'])} concelhos")
        for concelho in distrito["concelhos"]:
            print(f"  {concelho['slug']:26s} {concelho['nome']}")
        return 0

    print(
        f"fonte={catalogo['source']} distritos={catalogo['total_distritos']} "
        f"concelhos={catalogo['total_concelhos']} empresas={catalogo.get('total_empresas')}"
    )
    if catalogo.get("sem_concelhos"):
        print(f"SEM CONCELHOS: {', '.join(catalogo['sem_concelhos'])}")
    for distrito in catalogo["distritos"]:
        nomes = ", ".join(c["nome"] for c in distrito["concelhos"][:5])
        resto = len(distrito["concelhos"]) - 5
        total = distrito.get("empresas")
        print(
            f"{distrito['slug']:22s} {len(distrito['concelhos']):3d} concelhos "
            f"{('~' + format(total, ',d')) if total else '':>12s} | {nomes}{' …' if resto > 0 else ''}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
