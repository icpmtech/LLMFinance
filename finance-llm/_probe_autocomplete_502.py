"""Sonda: /contracts/autocomplete depois da correção (keyword + regex escapado)."""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api import elasticsearch_client as ec  # noqa: E402

CONSULTAS = [
    "jan",
    "JANSSEN",
    "Município",
    "3360",
    "3001/22/0000082",
    "3001-22-0000082",
    "software para as Iniciativas",
    "3001/22/0000082 - Aquisição de serviços de desenvolvimento de software para as Iniciativas planeadas no âmbito",
    'aspas "estranhas"',
    "AND OR NOT",
    "(((",
    ".*",
    "a|b",
]

for consulta in CONSULTAS:
    inicio = time.time()
    resultado = ec.contracts_autocomplete(q=consulta, size=6)
    decorrido = round(time.time() - inicio, 2)
    erro = resultado.get("error")
    sugestoes = resultado.get("suggestions") or []
    amostra = " | ".join(f"{item['type']}:{item['text'][:32]} ({item['count']})" for item in sugestoes[:3])
    print(f"q={consulta[:44]!r} {decorrido}s erro={erro!r} n={len(sugestoes)} :: {amostra}")
