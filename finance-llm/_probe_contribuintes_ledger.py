"""Inspeciona o registo (ledger) da sincronizacao de contribuintes.

Uso:
    python _probe_contribuintes_ledger.py [fonte]

Mostra as colunas, uma amostra de linhas da fonte indicada (por omissao
`contratos`) e quantas linhas trazem `detail.localExecucao` preenchido -- que e
a origem da localizacao dos contribuintes (fallback a sede).
"""

from __future__ import annotations

import glob
import json
import os
import sqlite3
import sys

LEDGER_GLOB = "c:/LLMFinance/finance-llm/data/contribuintes/parts-*.sqlite3"


def main() -> int:
    source = sys.argv[1] if len(sys.argv) > 1 else "contratos"
    matches = glob.glob(LEDGER_GLOB)
    if not matches:
        print("sem registo em", LEDGER_GLOB)
        return 1
    path = max(matches, key=os.path.getmtime)
    print(f"registo: {os.path.basename(path)} ({os.path.getsize(path) / 1048576:.0f} MB)")

    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    print("colunas:", [row[1] for row in con.execute("PRAGMA table_info(parts)")])

    total = con.execute(
        "SELECT COUNT(*) FROM parts WHERE source = ?", (source,)
    ).fetchone()[0]
    print(f"linhas {source}: {total}")

    sql = "SELECT COUNT(*) FROM parts WHERE source = ? AND payload LIKE ?"
    with_exec = con.execute(sql, (source, "%localExecucao%")).fetchone()[0]
    print(f"linhas {source} com 'localExecucao' no payload: {with_exec}")

    for nif, payload in con.execute(
        "SELECT nif, payload FROM parts WHERE source = ? LIMIT 3", (source,)
    ):
        data = json.loads(payload)
        detail = json.dumps(data.get("detail"), ensure_ascii=False)
        print(f"  {nif} detail={detail[:200]}")

    print("--- contagem por fonte")
    for src, count in con.execute(
        "SELECT source, COUNT(*) FROM parts GROUP BY source ORDER BY 2 DESC"
    ):
        print(f"  {src}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
