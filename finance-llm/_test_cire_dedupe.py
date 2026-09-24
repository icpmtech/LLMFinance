"""Teste dos novos comportamentos: não reindexar o que já existe e não repetir dias já processados."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api import cire_service  # noqa: E402


def main() -> None:
    print("=== cobertura (janelas já processadas) ===")
    cov = cire_service.coverage()
    for janela in cov["windows"][:5]:
        print(f"  {janela['desde']} → {janela['ate']} · {janela['collected']} docs · {janela['run_id']}")

    print("\n=== recolha de um dia já processado (2026-09-23) ===")
    res = cire_service.collect(desde="2026-09-23", ate="2026-09-23", max_pages=1, min_interval=1.0, persist=False)
    meta = res["meta"]
    print("collected:", meta["collected"], "| skipped:", len(meta["skipped_windows"]))
    for aviso in meta["warnings"]:
        print("  aviso:", aviso)

    print("\n=== recolha do mesmo dia com force=True (deve recolher) ===")
    res2 = cire_service.collect(
        desde="2026-09-23", ate="2026-09-23", max_pages=1, min_interval=1.0, force=True, persist=False
    )
    print("collected:", res2["meta"]["collected"], "| warnings:", res2["meta"]["warnings"])

    print("\n=== reimportar uma recolha já indexada (não deve reescrever) ===")
    run_id = cire_service.latest_run_id()
    ing = cire_service.ingest_run(run_id)
    print({k: ing.get(k) for k in ("run_id", "received", "indexed_count", "skipped_existing", "index_total")})

    print("\n=== reimportar com update_existing=True (reescreve) ===")
    ing2 = cire_service.ingest_run(run_id, update_existing=True)
    print({k: ing2.get(k) for k in ("run_id", "received", "indexed_count", "skipped_existing")})


if __name__ == "__main__":
    main()
