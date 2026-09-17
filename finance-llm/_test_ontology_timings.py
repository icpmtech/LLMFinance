"""Mede tempos das consultas da ontologia (sem cache), incluindo a agregação de empresas."""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api import ontology_service as ontology  # noqa: E402

CASES = [
    ("empresa (sem pesquisa)", lambda: ontology.query_objects("empresa", size=3)),
    ("empresa EDP", lambda: ontology.query_objects("empresa", search="EDP", size=3)),
    ("empresa 'Infraestruturas de Portugal'", lambda: ontology.query_objects("empresa", search="Infraestruturas de Portugal", size=3)),
    ("entidade_publica", lambda: ontology.query_objects("entidade_publica", size=3)),
    ("empresa por NIF", lambda: ontology.query_objects("empresa", filters={"nif": "500233810"}, size=1)),
    ("contrato ano=2025", lambda: ontology.query_objects("contrato", filters={"ano": 2025}, size=1)),
    ("contrato por NIF", lambda: ontology.query_objects("contrato", filters={"adjudicatario_nif": "500233810"}, size=1)),
    ("cpv", lambda: ontology.query_objects("cpv", size=3)),
    ("noticia", lambda: ontology.query_objects("noticia", size=3)),
    ("ai_context (contratos EDP/GALP)", lambda: ontology.ai_context("Quais os contratos da EDP e da GALP?")),
]


def main() -> int:
    for label, call in CASES:
        ontology.clear_cache()
        started = time.time()
        try:
            result = call()
            elapsed = (time.time() - started) * 1000
            if isinstance(result, dict) and "items" in result:
                first = result["items"][0] if result["items"] else None
                summary = f"total={result['total']} erro={result.get('error', '-')} primeiro={(first or {}).get('nome') or (first or {}).get('_label')}"
            else:
                summary = f"objetos={len(result.get('objects', []))}"
            print(f"  {label:40s} {elapsed:7.0f} ms  {summary}")
        except Exception as exc:
            print(f"  {label:40s} EXCEÇÃO {type(exc).__name__}: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
