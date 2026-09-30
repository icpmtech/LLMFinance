"""Sincroniza a fonte `devedores` no índice de contribuintes (fusão com o existente)."""
from __future__ import annotations

import json
import os
import sys

os.environ.setdefault("ELASTICSEARCH_URL", "http://127.0.0.1:9200")

from api import contribuintes_service as contribuintes  # noqa: E402

fontes = sys.argv[1:] or ["devedores"]
resumo = contribuintes.run_sync(fontes, trigger="manual")
print(
    json.dumps(
        {
            k: v
            for k, v in resumo.items()
            if k in ("run_id", "full", "sources", "written", "write_errors", "unique", "deleted", "errors")
        },
        ensure_ascii=False,
        default=str,
    )[:1200]
)
