"""Gera `chat-ui/src/components/geo/countries.ts` a partir de `countries.json`."""
from __future__ import annotations

import json
from pathlib import Path

GEO = Path(__file__).resolve().parent / "chat-ui" / "src" / "components" / "geo"

HEADER = '''/**
 * Centroides dos países (ISO 3166-1 alfa-2 → latitude/longitude), gerados a partir
 * da lista pública `average-latitude-longitude-countries`.
 *
 * Ficheiro **gerado** (`scripts/`/`_gen_countries_ts.py`): não editar à mão. É
 * usado pelo mapa do módulo GLEIF / LEI quando a região da sede legal de um
 * registo não tem centroide próprio.
 */
export const COUNTRY_CENTROIDS: Record<string, [number, number]> = {
'''


def main() -> None:
    data: dict[str, list[float]] = json.loads((GEO / "countries.json").read_text(encoding="utf-8"))
    items = sorted(data.items())
    lines: list[str] = []
    for index in range(0, len(items), 8):
        chunk = items[index : index + 8]
        lines.append("  " + " ".join(f'"{key}": [{value[0]}, {value[1]}],' for key, value in chunk))
    out = HEADER + "\n".join(lines) + "\n};\n"
    (GEO / "countries.ts").write_text(out, encoding="utf-8")
    print(f"countries.ts escrito com {len(items)} países")


if __name__ == "__main__":
    main()
