"""Sincroniza o índice de contribuintes (`finance_contribuintes`) a partir das fontes.

O índice da plataforma é derivado: este script percorre, por agregação, todos os
índices que guardam NIF/NIPC (contratos PT e ES, cadastro de entidades,
publicações societárias, CIRE, PessoasIQ, firmas, marcas e CRM) e reconstrói o
índice de contribuintes. É o mesmo trabalho que o cron faz
(`contribuintes_scheduler`) e que o botão «Sincronizar agora» da aplicação lança.

Uso:
    c:\\LLMFinance\\.venv\\Scripts\\python.exe _sync_contribuintes.py            # todas as fontes
    c:\\LLMFinance\\.venv\\Scripts\\python.exe _sync_contribuintes.py contratos cire
    c:\\LLMFinance\\.venv\\Scripts\\python.exe _sync_contribuintes.py --page-size 4000

Grava o progresso em `logs/contribuintes_sync.log` e o resumo em
`logs/contribuintes_sync.json`.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from api import contribuintes_service as service  # noqa: E402

LOG_PATH = ROOT / "logs" / "contribuintes_sync.log"
SUMMARY_PATH = ROOT / "logs" / "contribuintes_sync.json"


def main(argv: list[str]) -> int:
    sources = [arg for arg in argv if not arg.startswith("-")]
    page_size = None
    if "--page-size" in argv:
        page_size = int(argv[argv.index("--page-size") + 1])
        sources = [source for source in sources if source != str(page_size)]

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    started = time.time()

    def log(message: str) -> None:
        line = f"[{time.strftime('%H:%M:%S')}] {message}"
        print(line, flush=True)
        with LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def progress(payload: dict) -> None:
        phase = payload.get("phase")
        if phase == "source-done":
            stats = payload.get("sources", {}).get(payload.get("source"), {})
            log(
                f"fonte {payload.get('source')}: {stats.get('nifs')} registos em "
                f"{stats.get('pages')} páginas ({stats.get('seconds')} s)"
            )
        elif phase == "write":
            log(f"a escrever: {payload.get('written')} de {payload.get('total')}")

    log(f"a sincronizar contribuintes de {'todas as fontes' if not sources else ', '.join(sources)}")
    summary = service.run_sync(sources or None, page_size=page_size, progress=progress, trigger="script")
    log(
        "concluído: {unique} contribuintes únicos, {written} escritos, {deleted} removidos em {duration}s ({status})".format(
            unique=summary.get("unique"),
            written=summary.get("written"),
            deleted=summary.get("deleted"),
            duration=summary.get("duration_s"),
            status=summary.get("status"),
        )
    )
    for source_id, stats in (summary.get("sources") or {}).items():
        log(f"  · {source_id}: {stats.get('nifs')} registos, {stats.get('pages')} páginas, {stats.get('seconds')} s")
    for error in summary.get("errors") or []:
        log(f"  ! {error.get('source')}.{error.get('spec')}: {error.get('error')}")
    SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"total {round(time.time() - started, 1)} s · resumo em {SUMMARY_PATH.relative_to(ROOT)}")
    return 0 if summary.get("status") == "ok" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
