"""Sonda: recolha em lote por mês e ano (avisos Vortal publicados nos contratos).

Uso:
    ..\.venv\Scripts\python.exe _probe_vortal_lote.py [ANO] [MÊS] [--recolher] [--lotes N]

Sem argumentos usa o mês mais recente com avisos publicados. Sem `--recolher`
fica-se pela leitura do período (não se descarrega nada).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api import vortal_service as vortal  # noqa: E402


def main() -> None:
    argumentos = [item for item in sys.argv[1:] if not item.startswith("--")]
    recolher = "--recolher" in sys.argv
    lotes = int(sys.argv[sys.argv.index("--lotes") + 1]) if "--lotes" in sys.argv else 1

    periodos = vortal.periodos()
    print("== períodos ==")
    print(" contratos com peças Vortal:", periodos.get("total"))
    for item in (periodos.get("anos") or [])[-5:]:
        print(f"   {item['ano']}: {item['avisos']} avisos")
    if periodos.get("erro"):
        print(" erro:", periodos["erro"])

    anos = periodos.get("anos") or []
    meses = periodos.get("meses") or []
    if not argumentos and not anos:
        print("não há períodos com avisos Vortal")
        return
    ano = int(argumentos[0]) if argumentos else int(anos[-1]["ano"])
    mes = int(argumentos[1]) if len(argumentos) > 1 else (int(meses[-1]["mes"][5:7]) if meses else None)

    print(f"\n== período {ano}-{mes or 'ano'} ==")
    periodo = vortal.avisos_do_periodo(ano=ano, mes=mes, limite=10, escanear=vortal.ESCANEAR_MAXIMO)
    print(
        f" contratos: {periodo['total']} | avisos únicos: {periodo['unicos']} | "
        f"em disco: {periodo['em_disco']} | por recolher: {periodo['pendentes']}"
    )
    for aviso in periodo["avisos"]:
        estado = "disco" if aviso["em_disco"] else "novo "
        print(f"   {aviso['data_publicacao']}  {estado}  {aviso['url'][:88]}")

    if not recolher:
        print("\n(sem --recolher: não se descarrega nada; junte --recolher para correr o lote)")
        return

    resultado = vortal.recolher_lote(
        ano=ano, mes=mes, lote=5, lotes=lotes, indexar=True, extrair=True, escanear=vortal.ESCANEAR_MAXIMO
    )
    print("\n== lote ==")
    resumo = {chave: valor for chave, valor in resultado.items() if chave != "detalhe"}
    print(json.dumps(resumo, ensure_ascii=False, indent=1)[:2500])
    for aviso in resultado["detalhe"]:
        print(f"\n aviso {aviso['uid']} ({aviso.get('url_aviso')})")
        for peca in aviso["pecas"]:
            print(
                f"   {peca['ficheiro'][:56]:56} {peca.get('tipo'):18} {int(peca.get('bytes') or 0):>10} B "
                f"texto={peca.get('texto_chars')} [{peca.get('texto_metodo')}]"
            )


if __name__ == "__main__":
    main()
