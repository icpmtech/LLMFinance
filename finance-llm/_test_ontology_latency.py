"""Mede a latência do contexto ontológico (usado pelo agente em cada pergunta)."""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api import ontology_service as ontology  # noqa: E402

QUESTIONS = [
    "Quais os contratos da EDP e da GALP?",
    "Qual o valor total da Infraestruturas de Portugal?",
    "Notícias e sentimento da EDP",
]


def main() -> int:
    ontology.clear_cache()
    for index, question in enumerate(QUESTIONS, start=1):
        started = time.time()
        context = ontology.ai_context(question, limit=4, links_per_object=2, link_budget=4)
        elapsed = time.time() - started
        print(
            f"  #{index} {elapsed:5.2f}s (serviço {context['elapsed_ms']:5d} ms) "
            f"objetos={len(context['objects'])} relações={len(context['relations'])} · {question}"
        )
        for entry in context["objects"]:
            print(f"      - {entry['type_label']}: {entry['label']} [{entry['id']}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
