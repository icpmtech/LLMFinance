"""Mede a cobertura da geocodificação das sedes legais sobre a golden copy local."""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api import gleif_geo  # noqa: E402

LEI_FILE = Path(__file__).resolve().parent / "data" / "gleif" / "lei.jsonl"
LIMIT = 30000

print("tabelas:", gleif_geo.stats())

counts: Counter[str] = Counter()
by_country: Counter[str] = Counter()
examples: dict[str, dict] = {}
for index, line in enumerate(LEI_FILE.open("r", encoding="utf-8")):
    if index >= LIMIT:
        break
    doc = json.loads(line)
    resolved = gleif_geo.resolve(doc.get("country"), doc.get("postal_code"), doc.get("city"))
    precision = resolved[2] if resolved else "sem ponto"
    counts[precision] += 1
    by_country[f"{doc.get('country')}:{precision}"] += 1
    if precision in {"postal", "city"} and precision not in examples:
        examples[precision] = {
            "lei": doc.get("lei"),
            "legal_name": doc.get("legal_name"),
            "postal_code": doc.get("postal_code"),
            "city": doc.get("city"),
            "region": doc.get("region"),
            "point": [round(resolved[0], 4), round(resolved[1], 4)],
        }

total = sum(counts.values())
print(f"\n{total} registos analisados:")
for kind, hits in counts.most_common():
    print(f"  {kind:12} {hits:>7}  {hits / total * 100:5.1f}%")
print("\npor país:")
for key, hits in sorted(by_country.items()):
    print(f"  {key:18} {hits:>7}")
print("\nexemplos:")
for kind, doc in examples.items():
    print(f"  {kind}: {doc}")

# Semelhança do resultado com o esperado para o caso do pedido (2680-102, Loures).
for postal, city, expected in (("2680-102", "Loures", "Loures"), ("4470-000", "Maia", "Maia"), ("28001", "Madrid", "Madrid")):
    country = "PT" if len(postal) == 8 else "ES"
    print(f"  {country} {postal} {city} -> {gleif_geo.resolve(country, postal, city)}")
