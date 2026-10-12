"""Sonda: recolha real de peças da Vortal (disco + índice) e pesquisa no texto.

Uso:
    ..\.venv\Scripts\python.exe _probe_vortal_pecas.py [URL-ou-UID ...]

Sem argumentos usa um aviso público conhecido (token da página de peças).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api import vortal_service as vortal  # noqa: E402

PADRAO = (
    "https://community.vortal.biz/Public/public-tender-documents/"
    "NDR3OVplcDc3Q2ZSb1RWUEpQaDd4MTVMWnBtN3o1OEsvbElnN2hDTjBxM1RUNUQxc1FNbDR5Z29xdytt"
    "QTI5OXdtcjArY0JYdmFSazM2cVcwdjlLK0E9PTApaSFf"
)

alvos = sys.argv[1:] or [PADRAO]

resultado = vortal.recolher(alvos, indexar=True, extrair=True)
print("== recolha ==")
print(" avisos:", resultado["avisos"], "| peças:", resultado["pecas"], "| bytes:", resultado["bytes"])
print(" duração:", resultado.get("duracao_s"), "s | erros:", len(resultado["erros"]))
for erro in resultado["erros"][:5]:
    print("   -", erro)
for aviso in resultado["detalhe"]:
    print(f"\n aviso {aviso['uid']} ({aviso.get('url_aviso')})")
    for peca in aviso["pecas"]:
        print(
            f"   {peca['ficheiro'][:60]:60} {peca.get('tipo'):18} {int(peca.get('bytes') or 0):>10} B "
            f"texto={peca.get('texto_chars')} [{peca.get('texto_metodo')}]"
        )
print("\n== índice ==")
print(json.dumps(resultado.get("indice"), ensure_ascii=False, indent=1))

print("\n== estado ==")
print(json.dumps(vortal.estado(), ensure_ascii=False, indent=1)[:1500])

print("\n== peças indexadas ==")
pecas = vortal.listar_pecas(limite=5)
for item in pecas.get("itens", []):
    print(f"   {item.get('nome')} :: {item.get('tipo_label')} :: {item.get('texto_chars')} chars")

print("\n== pesquisa ==")
for termo in ("bedaquilina", "caderno de encargos", "preço base"):
    achado = vortal.pesquisar(termo, limite=3)
    print(f" '{termo}': {achado.get('total')} resultados")
    for item in achado.get("itens", [])[:2]:
        trecho = (item.get("trechos") or [""])[0][:160].replace("\n", " ")
        print(f"   - {item.get('nome')}: …{trecho}…")
