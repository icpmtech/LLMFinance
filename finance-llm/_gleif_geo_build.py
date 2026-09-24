"""Constrói as tabelas de geocodificação do módulo GLEIF a partir do GeoNames.

Os registos LEI não trazem coordenadas: trazem o **endereço da sede legal**
(código postal, cidade, região, país). Para colocar as empresas no mapa pela sua
sede é preciso geocodificar — e geocodificar 212 mil registos num serviço
externo (Nominatim) não é viável nem educado (1 pedido/s).

Este script descarrega os ficheiros livres do **GeoNames** e constrói dois
índices por país, guardados em `data/gleif/geo/<país>.json`:

* `postal` — código postal → [lat, lon] (PT: os 4 dígitos; ES: os 5 dígitos);
* `city`   — nome da cidade (sem acentos, minúsculas) → [lat, lon], escolhendo a
  localidade **mais populosa** com esse nome (evita ficar com uma aldeia
  homónima).

Uso:
    python _gleif_geo_build.py PT ES
"""
from __future__ import annotations

import io
import json
import sys
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import httpx

ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "data" / "gleif" / "geo"
POSTAL_URL = "https://download.geonames.org/export/zip/{country}.zip"
PLACES_URL = "https://download.geonames.org/export/dump/{country}.zip"

sys.path.insert(0, str(ROOT))
from collectors.gleif import fold  # noqa: E402


def _download(url: str, timeout: float = 300.0) -> bytes:
    print(f"  a descarregar {url}")
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.content


def _first_member(payload: bytes, suffix: str, country: str = "") -> str:
    """Lê o ficheiro de dados do ZIP.

    Os ZIP do GeoNames trazem `readme.txt` **primeiro** e o ficheiro de dados
    (`PT.txt`) depois — escolher «o primeiro .txt» lia o readme e não extraía
    nada. Prefere-se o membro com o nome do país e, em falta, o maior.
    """
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        members = [info for info in archive.infolist() if info.filename.lower().endswith(suffix)]
        if not members:
            raise RuntimeError(f"ZIP sem ficheiros «{suffix}»")
        wanted = f"{country.upper()}{suffix}".lower()
        chosen = next((m for m in members if m.filename.lower().endswith(wanted)), None)
        if chosen is None:
            chosen = max(members, key=lambda m: m.file_size)
        with archive.open(chosen) as raw:
            return io.TextIOWrapper(raw, encoding="utf-8", errors="replace").read()


def build_postal(payload: bytes, country: str) -> Dict[str, List[float]]:
    """Código postal → coordenadas (agrega por média quando há repetidos)."""
    totals: Dict[str, List[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])
    for line in _first_member(payload, ".txt", country).splitlines():
        parts = line.split("\t")
        if len(parts) < 11:
            continue
        code = parts[1].strip()
        try:
            lat, lon = float(parts[9]), float(parts[10])
        except ValueError:
            continue
        if not code or not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue
        acc = totals[code]
        acc[0] += lat
        acc[1] += lon
        acc[2] += 1
    return {code: [round(lat / count, 5), round(lon / count, 5)] for code, (lat, lon, count) in totals.items() if count}


#: População a partir da qual os **nomes alternativos** de uma localidade entram no
#: índice. É o que faz «LISBOA» encontrar a localidade que o GeoNames chama
#: «Lisbon» (o `name` do ficheiro está em inglês para as cidades grandes).
ALTERNATES_MIN_POPULATION = 20000


def build_cities(payload: bytes, country: str) -> Dict[str, List[float]]:
    """Nome da cidade → coordenadas, preferindo **localidades povoadas**.

    A ordenação é por `(é localidade, população)`: sem isto o distrito de Lisboa
    (classe `A`, 547 mil habitantes) ganhava à cidade (classe `P`, 517 mil) e a
    sede das empresas ficava no centroide do distrito.

    Indexa o nome, o nome ASCII e — para as localidades com alguma dimensão — os
    nomes alternativos (é assim que «Lisboa» encontra «Lisbon», que é o `name`
    do ficheiro do GeoNames).
    """
    best: Dict[str, Tuple[bool, int, float, float]] = {}
    for line in _first_member(payload, ".txt", country).splitlines():
        parts = line.split("\t")
        if len(parts) < 15:
            continue
        is_place = parts[6] == "P"
        try:
            lat, lon = float(parts[4]), float(parts[5])
            population = int(parts[14] or 0)
        except ValueError:
            continue
        keys = {fold(parts[1]), fold(parts[2])}
        if is_place and population >= ALTERNATES_MIN_POPULATION:
            keys |= {fold(alternate) for alternate in parts[3].split(",") if alternate}
        for key in keys:
            if not key:
                continue
            current = best.get(key)
            rank = (is_place, population)
            if current is None or rank > (current[0], current[1]):
                best[key] = (is_place, population, round(lat, 5), round(lon, 5))
    return {key: [lat, lon] for key, (_place, _pop, lat, lon) in best.items()}


def summarise(postal: Dict[str, List[float]], cities: Dict[str, List[float]]) -> str:
    lengths = sorted({len(code) for code in postal})
    return f"{len(postal)} códigos postais (comprimentos {lengths}) · {len(cities)} cidades"


def main() -> int:
    countries = [c.upper() for c in (sys.argv[1:] or ["PT", "ES"])]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for country in countries:
        print(f"{country}:")
        postal = build_postal(_download(POSTAL_URL.format(country=country)), country)
        cities = build_cities(_download(PLACES_URL.format(country=country)), country)
        # Portugal: guarda-se o código completo (`2680-102`, mais preciso) e o
        # prefixo de 4 dígitos (`2680`, a localidade) — os endereços dos registos
        # LEI aparecem nas duas formas.
        if country == "PT":
            grouped: Dict[str, List[float]] = dict(postal)
            for code, point in postal.items():
                grouped.setdefault(code.split("-")[0], point)
            postal = grouped
        payload = {
            "country": country,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "sources": ["geonames.org/export/zip", "geonames.org/export/dump"],
            "postal": postal,
            "city": cities,
        }
        path = OUT_DIR / f"{country.lower()}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        print(f"  {summarise(postal, cities)} → {path} ({path.stat().st_size / 1024:.0f} KB)")

    # Amostras para conferir à mão (Loures é o caso do pedido).
    sample_path = OUT_DIR / "pt.json"
    if sample_path.exists():
        data = json.loads(sample_path.read_text(encoding="utf-8"))
        for code in ("2680", "2685", "4470", "1000"):
            print(f"  amostra PT {code} -> {data['postal'].get(code)}")
        for city in ("loures", "maia", "lisboa"):
            print(f"  amostra cidade {city} -> {data['city'].get(city)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
