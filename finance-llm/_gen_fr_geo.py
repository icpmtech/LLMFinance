"""Gera `api/fr_geo.py` — centroides dos departamentos e regiões de França.

Os contratos do DECP **não têm coordenadas**: trazem o código do local de execução
(`lieu_execution_code`) e o seu tipo (`lieu_execution_type`): código de
departamento («35»), código postal («43190»), código INSEE de comuna («2A004»),
código de região («11»), código de país («FR»)…

Este script constrói a tabela de posições a partir de dados oficiais:

- **departamentos** — centroide (centro de massa) do polígono de cada
  departamento, calculado a partir do GeoJSON público
  `gregoiredavid/france-geojson` (licença ODbL, derivado do IGN/ADMIN EXPRESS);
- **regiões** — centro de massa das suas departamentos (média ponderada pela área
  dos polígonos), usando o mapeamento oficial departamento→região de
  `geo.api.gouv.fr`;
- **ultramar (DOM/COM)** — sem polígonos no GeoJSON metropolitano: usam-se as
  coordenadas da **prefeitura** (capital), que ficam marcadas como tal.

Nada é inventado: o que não tiver posição conhecida não entra na tabela (a API
devolve esses códigos em «sem posição no mapa»).

Uso:
    python _gen_fr_geo.py            # usa cache em data/fr-geo/ se existir
    python _gen_fr_geo.py --refresh  # volta a descarregar
"""
from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "data" / "fr-geo"
DESTINO = ROOT / "api" / "fr_geo.py"

GEOJSON_URL = "https://raw.githubusercontent.com/gregoiredavid/france-geojson/master/departements.geojson"
DEPARTAMENTOS_URL = "https://geo.api.gouv.fr/departements?fields=nom,code,region"
REGIOES_URL = "https://geo.api.gouv.fr/regions?fields=nom,code"

# Ultramar: o GeoJSON metropolitano não tem polígonos destes departamentos.
# Coordenadas da **prefeitura** (capital) — nível departamental, sem inventar.
ULTRAMAR = {
    "971": (-61.7294, 15.9985, "Guadeloupe (Basse-Terre)"),
    "972": (-61.0588, 14.6161, "Martinique (Fort-de-France)"),
    "973": (-52.326, 4.9372, "Guyane (Cayenne)"),
    "974": (55.4504, -20.8823, "La Réunion (Saint-Denis)"),
    "975": (-56.3159, 46.8852, "Saint-Pierre-et-Miquelon"),
    "976": (45.2278, -12.7806, "Mayotte (Mamoudzou)"),
    "977": (-62.8333, 17.9, "Saint-Barthélemy"),
    "978": (-63.0501, 18.0708, "Saint-Martin"),
}

PREFIXO = '''"""Posições de França para o mapa dos contratos (gerado por `_gen_fr_geo.py`).

**Não editar à mão.** Cada entrada é `dict(code={...})` com `lat`, `lon` e `nom`.

- Departamentos: centro de massa do polígono oficial (`gregoiredavid/france-geojson`).
- Regiões: centro de massa dos seus departamentos (mapeamento `geo.api.gouv.fr`).
- Ultramar: coordenadas da prefeitura (não há polígonos metropolitanos para lá).
"""

from __future__ import annotations

from typing import Any, Dict

#: Centro de massa da França metropolitana (usado no nível «país»).
FR_COUNTRY_CENTROID = {"lat": 46.6, "lon": 2.5, "nom": "França"}

#: Departamentos metropolitanos (96) — centro de massa do polígono.
FR_DEPARTMENT_CENTROIDS: Dict[str, Dict[str, Any]] = {
'''

FIM = '''}

#: Regiões (18) — centro de massa dos departamentos que as compõem.
FR_REGION_CENTROIDS: Dict[str, Dict[str, Any]] = {
'''

FIM2 = '''}

#: Ultramar (DOM/COM) — coordenadas da prefeitura.
FR_OVERSEAS_CENTROIDS: Dict[str, Dict[str, Any]] = {
'''

FIM3 = '''}
'''


def _descarregar(url: str, destino: Path, refresh: bool) -> Path:
    if destino.is_file() and not refresh:
        return destino
    destino.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=60) as resposta:  # noqa: S310 - URL fixo
        destino.write_bytes(resposta.read())
    return destino


def _anel_maior(geometria: dict) -> list[list[float]]:
    """Anel exterior do polígono (o maior, em MultiPolygon)."""
    tipo = geometria.get("type")
    coordenadas = geometria.get("coordinates") or []
    aneis: list[list[list[float]]] = []
    if tipo == "Polygon":
        aneis = [coordenadas[0]] if coordenadas else []
    elif tipo == "MultiPolygon":
        aneis = [poligono[0] for poligono in coordenadas if poligono]
    if not aneis:
        return []
    return max(aneis, key=len)


def _centroide(anel: list[list[float]]) -> tuple[float, float] | None:
    """Centro de massa do polígono (fórmula do shoelace), em (lat, lon)."""
    if len(anel) < 3:
        return None
    area = 0.0
    cx = 0.0
    cy = 0.0
    for i in range(len(anel) - 1):
        x0, y0 = anel[i][0], anel[i][1]
        x1, y1 = anel[i + 1][0], anel[i + 1][1]
        cruz = x0 * y1 - x1 * y0
        area += cruz
        cx += (x0 + x1) * cruz
        cy += (y0 + y1) * cruz
    if abs(area) < 1e-12:
        # Anel degenerado: média dos vértices (aproximação honesta).
        lon = sum(p[0] for p in anel) / len(anel)
        lat = sum(p[1] for p in anel) / len(anel)
        return lat, lon
    area *= 0.5
    return cy / (6 * area), cx / (6 * area)


def _area_anel(anel: list[list[float]]) -> float:
    area = 0.0
    for i in range(len(anel) - 1):
        x0, y0 = anel[i][0], anel[i][1]
        x1, y1 = anel[i + 1][0], anel[i + 1][1]
        area += x0 * y1 - x1 * y0
    return abs(area) * 0.5


def _formatar_entrada(chave: str, valor: dict, indentacao: str = "    ") -> str:
    return f'{indentacao}"{chave}": {{"lat": {valor["lat"]:.4f}, "lon": {valor["lon"]:.4f}, "nom": {json.dumps(valor["nom"], ensure_ascii=False)}}},'


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()

    geojson = json.loads(_descarregar(GEOJSON_URL, CACHE / "departements.geojson", args.refresh).read_text(encoding="utf-8"))
    departamentos = json.loads(_descarregar(DEPARTAMENTOS_URL, CACHE / "departements.json", args.refresh).read_text(encoding="utf-8"))
    regioes = json.loads(_descarregar(REGIOES_URL, CACHE / "regions.json", args.refresh).read_text(encoding="utf-8"))

    nomes_dep = {item["code"]: item["nom"] for item in departamentos}
    regiao_do_dep = {item["code"]: (item.get("region") or {}).get("code") for item in departamentos}
    nomes_reg = {item["code"]: item["nom"] for item in regioes}

    centros: dict[str, dict] = {}
    areas: dict[str, float] = {}
    for feature in geojson["features"]:
        codigo = str(feature["properties"].get("code") or "").strip()
        anel = _anel_maior(feature["geometry"])
        centro = _centroide(anel)
        if not codigo or centro is None:
            continue
        lat, lon = centro
        centros[codigo] = {"lat": lat, "lon": lon, "nom": feature["properties"].get("nom") or nomes_dep.get(codigo, codigo)}
        areas[codigo] = _area_anel(anel)

    # Regiões: centro de massa dos departamentos (ponderado pela área).
    acumulado: dict[str, dict] = {}
    for codigo, centro in centros.items():
        codigo_regiao = regiao_do_dep.get(codigo)
        if not codigo_regiao:
            continue
        peso = areas.get(codigo, 1.0)
        item = acumulado.setdefault(codigo_regiao, {"peso": 0.0, "lat": 0.0, "lon": 0.0})
        item["peso"] += peso
        item["lat"] += centro["lat"] * peso
        item["lon"] += centro["lon"] * peso
    regioes_centro: dict[str, dict] = {}
    for codigo, item in acumulado.items():
        if not item["peso"]:
            continue
        regioes_centro[codigo] = {
            "lat": item["lat"] / item["peso"],
            "lon": item["lon"] / item["peso"],
            "nom": nomes_reg.get(codigo, codigo),
        }
    # Regiões de ultramar (códigos INSEE 01–06), a partir do respetivo departamento.
    for codigo_regiao, codigo_dep in (("01", "971"), ("02", "972"), ("03", "973"), ("04", "974"), ("06", "976")):
        lon, lat, nome = ULTRAMAR[codigo_dep]
        regioes_centro[codigo_regiao] = {"lat": lat, "lon": lon, "nom": nome}

    # «20» não existe como departamento: os códigos postais da Córsega começam por
    # 20 e não dizem se é 2A ou 2B. Fica um grupo «Córsega» no centro da ilha
    # (centro de massa de 2A+2B), assinalado na API como posição do conjunto.
    pesos = {c: areas.get(c, 1.0) for c in ("2A", "2B") if c in centros}
    if pesos:
        total_peso = sum(pesos.values())
        centros["20"] = {
            "lat": sum(centros[c]["lat"] * p for c, p in pesos.items()) / total_peso,
            "lon": sum(centros[c]["lon"] * p for c, p in pesos.items()) / total_peso,
            "nom": "Corse (código postal 20)",
        }
        areas["20"] = total_peso

    partes = [PREFIXO]
    for codigo in sorted(centros):
        partes.append(_formatar_entrada(codigo, centros[codigo]))
    partes.append(FIM)
    for codigo in sorted(regioes_centro):
        partes.append(_formatar_entrada(codigo, regioes_centro[codigo]))
    partes.append(FIM2)
    for codigo in sorted(ULTRAMAR):
        lon, lat, nome = ULTRAMAR[codigo]
        partes.append(_formatar_entrada(codigo, {"lat": lat, "lon": lon, "nom": nome}))
    partes.append(FIM3)

    DESTINO.write_text("\n".join(partes), encoding="utf-8")
    print(f"{len(centros)} departamentos, {len(regioes_centro)} regioes, {len(ULTRAMAR)} ultramar -> {DESTINO}")


if __name__ == "__main__":
    main()
