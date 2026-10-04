"""Gera chat-ui/src/components/geo/france.ts a partir de api/fr_geo.py."""
from pathlib import Path
import re
import json


def parse_dict(name: str, text: str) -> dict:
    m = re.search(rf'{name}: Dict\[str, Dict\[str, Any\]\] = \{{(.*?)\n\}}', text, re.S)
    if not m:
        raise ValueError(name)
    body = m.group(1).strip()
    body = re.sub(r'#.*', '', body)
    return eval('{' + body + '}')


def main() -> None:
    src = Path('finance-llm/api/fr_geo.py').read_text(encoding='utf-8')
    deps = parse_dict('FR_DEPARTMENT_CENTROIDS', src)
    regs = parse_dict('FR_REGION_CENTROIDS', src)
    over = parse_dict('FR_OVERSEAS_CENTROIDS', src)
    country = eval(re.search(r'FR_COUNTRY_CENTROID = (\{.*?\})', src, re.S).group(1))

    def ts_literal(d):
        return json.dumps(d, ensure_ascii=False)

    dep_obj = {k: {'lat': v['lat'], 'lon': v['lon'], 'name': v['nom']} for k, v in deps.items()}
    reg_obj = {k: {'lat': v['lat'], 'lon': v['lon'], 'name': v['nom']} for k, v in regs.items()}
    over_obj = {k: {'lat': v['lat'], 'lon': v['lon'], 'name': v['nom']} for k, v in over.items()}
    country_obj = {'lat': country['lat'], 'lon': country['lon'], 'name': country['nom']}

    parts = [
        '/**\n * Geografia do mapa de contratos publicos de Franca (DECP).\n *\n * Gerado a partir de api/fr_geo.py. Nao editar a mao.\n */\n',
        'import type { GeoPoint } from "./iberia";\n\n',
        'export type FranceLevel = "departamento" | "regiao" | "pais";\n\n',
        'export type FranceRegion = GeoPoint & {\n  code: string;\n  name: string;\n  /** Pais ao qual a regiao pertence. Sempre "FR" neste modulo. */\n  pais: "FR";\n  level: FranceLevel;\n  approx: boolean;\n  offshore: boolean;\n};\n\n',
        'export const FRANCE_VIEW = {\n  center: { lat: 46.6, lon: 2.35 } as GeoPoint,\n  zoom: 6,\n  regionZoom: 8,\n};\n\n',
        'export const FRANCE_ISLANDS_VIEW = {\n  center: { lat: 15.0, lon: -55.0 } as GeoPoint,\n  zoom: 3,\n};\n\n',
        f'const FR_DEPARTMENTS: Record<string, GeoPoint & {{ name: string }}> = {ts_literal(dep_obj)};\n',
        f'const FR_REGIONS: Record<string, GeoPoint & {{ name: string }}> = {ts_literal(reg_obj)};\n',
        f'const FR_OVERSEAS: Record<string, GeoPoint & {{ name: string }}> = {ts_literal(over_obj)};\n',
        f'const FR_COUNTRY: GeoPoint & {{ name: string }} = {ts_literal(country_obj)};\n\n',
        'export const FRANCE_LEVEL_LABELS: Record<FranceLevel, string> = {\n  departamento: "Departamento",\n  regiao: "Regiao",\n  pais: "Pais",\n};\n\n',
        'export function isOffshoreFranceRegion(region: { lat: number; lon: number }): boolean {\n  return region.lat < 41 || region.lon < -6;\n}\n\n',
        '''export function resolveFranceRegion(code: string, level?: string): FranceRegion | null {
  const key = (code || "").trim();
  if (!key) return null;
  if (level === "pais" || key === "FR") {
    return { code: "FR", name: FR_COUNTRY.name, level: "pais", approx: false, offshore: false, lat: FR_COUNTRY.lat, lon: FR_COUNTRY.lon };
  }
  if (level === "regiao") {
    const r = FR_REGIONS[key];
    if (!r) return { code: key, name: `Regiao <<${key}>>`, level: "regiao", approx: true, offshore: false, lat: FR_COUNTRY.lat, lon: FR_COUNTRY.lon };
    return { code: key, name: r.name, level: "regiao", approx: false, offshore: r.lat < 41 || r.lon < -6, lat: r.lat, lon: r.lon };
  }
  const dep = FR_DEPARTMENTS[key] || FR_OVERSEAS[key];
  if (dep) {
    return { code: key, name: dep.name, level: "departamento", approx: false, offshore: dep.lat < 41 || dep.lon < -6, lat: dep.lat, lon: dep.lon };
  }
  return null;
}

''',
        '''export function allFranceRegions(): FranceRegion[] {
  const out: FranceRegion[] = [];
  for (const [code, dep] of Object.entries(FR_DEPARTMENTS)) {
    out.push({ code, name: dep.name, level: "departamento", approx: false, offshore: dep.lat < 41 || dep.lon < -6, lat: dep.lat, lon: dep.lon });
  }
  for (const [code, reg] of Object.entries(FR_REGIONS)) {
    out.push({ code, name: reg.name, level: "regiao", approx: false, offshore: reg.lat < 41 || reg.lon < -6, lat: reg.lat, lon: reg.lon });
  }
  return out;
}
''',
    ]

    out = Path('finance-llm/chat-ui/src/components/geo/france.ts')
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(''.join(parts), encoding='utf-8')
    print('wrote', out, 'chars', len(''.join(parts)))


if __name__ == '__main__':
    main()
