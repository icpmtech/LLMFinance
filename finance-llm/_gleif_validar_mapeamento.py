"""Valida o novo mapeamento do XML (corroboração, forma jurídica, endereços)."""
from __future__ import annotations

import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from collectors import gleif  # noqa: E402

ZIP = Path(__file__).resolve().parent / "data" / "gleif" / "golden-copy" / "lei2-latest.zip"

start = time.time()
docs = []
for doc in gleif.iter_golden_copy_file(ZIP, countries=["PT"]):
    docs.append(doc)
    if len(docs) >= 400:
        break
elapsed = time.time() - start

print(f"{len(docs)} documentos PT em {elapsed:.1f}s ({len(docs) / elapsed:.0f} doc/s)")
print("\ndistribuições:")
for field in ("corroboration_level", "legal_form", "legal_form_other", "status", "category", "hq_city", "hq_country"):
    counter = Counter(doc.get(field) for doc in docs)
    top = ", ".join(f"{value or '—'}={count}" for value, count in counter.most_common(4))
    print(f"  {field:22} {top}")
print("\nexemplo:")
example = docs[0]
for key in (
    "lei", "legal_name", "country", "region", "region_name", "city", "address_lines", "postal_code",
    "hq_city", "hq_country", "jurisdiction", "category", "legal_form", "legal_form_other", "status",
    "registration_status", "corroboration_level", "managing_lou", "registered_as", "registered_at",
    "validated_as", "initial_registration_date", "last_update_date", "creation_date",
):
    print(f"  {key:26} {example.get(key)!r}")
