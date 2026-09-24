"""Mede a velocidade do novo parser do golden copy (30 s de amostra)."""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from collectors import gleif  # noqa: E402

ZIP = Path(__file__).resolve().parent / "data" / "gleif" / "golden-copy" / "lei2-latest.zip"

start = time.time()
count = 0
countries = ["PT", "ES"]
for doc in gleif.iter_golden_copy_file(ZIP, countries=countries):
    count += 1
    if time.time() - start > 30:
        break
elapsed = time.time() - start
print(f"{count} documentos em {elapsed:.1f}s = {count / elapsed:.0f} doc/s (filtrado PT+ES)")
print(f"estimativa para ~212k documentos: {212000 / (count / elapsed) / 60:.1f} min")
if count:
    print("exemplo:", {k: doc.get(k) for k in ("lei", "legal_name", "country", "region", "city", "status", "legal_form")})
