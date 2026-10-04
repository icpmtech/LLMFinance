/**
 * Geografia do mapa de contratos publicos de Franca (DECP).
 *
 * Gerado a partir de api/fr_geo.py. Nao editar a mao.
 */
import type { GeoPoint } from "./iberia";

export type FranceLevel = "departamento" | "regiao" | "pais";

export type FranceRegion = GeoPoint & {
  code: string;
  name: string;
  /** Pais ao qual a regiao pertence. Sempre "FR" neste modulo. */
  pais: "FR";
  level: FranceLevel;
  approx: boolean;
  offshore: boolean;
};

export const FRANCE_VIEW = {
  center: { lat: 46.6, lon: 2.35 } as GeoPoint,
  zoom: 6,
  regionZoom: 8,
};

export const FRANCE_ISLANDS_VIEW = {
  center: { lat: 15.0, lon: -55.0 } as GeoPoint,
  zoom: 3,
};

const FR_DEPARTMENTS: Record<string, GeoPoint & { name: string }> = {"01": {"lat": 46.0997, "lon": 5.3487, "name": "Ain"}, "02": {"lat": 49.561, "lon": 3.5592, "name": "Aisne"}, "03": {"lat": 46.3936, "lon": 3.1877, "name": "Allier"}, "04": {"lat": 44.1062, "lon": 6.2448, "name": "Alpes-de-Haute-Provence"}, "05": {"lat": 44.6638, "lon": 6.265, "name": "Hautes-Alpes"}, "06": {"lat": 43.9382, "lon": 7.1163, "name": "Alpes-Maritimes"}, "07": {"lat": 44.7527, "lon": 4.4256, "name": "Ardèche"}, "08": {"lat": 49.6162, "lon": 4.6407, "name": "Ardennes"}, "09": {"lat": 42.921, "lon": 1.5036, "name": "Ariège"}, "10": {"lat": 48.3046, "lon": 4.1614, "name": "Aube"}, "11": {"lat": 43.1032, "lon": 2.4137, "name": "Aude"}, "12": {"lat": 44.2811, "lon": 2.6785, "name": "Aveyron"}, "13": {"lat": 43.5433, "lon": 5.0857, "name": "Bouches-du-Rhône"}, "14": {"lat": 49.0998, "lon": -0.3616, "name": "Calvados"}, "15": {"lat": 45.0512, "lon": 2.669, "name": "Cantal"}, "16": {"lat": 45.7187, "lon": 0.2031, "name": "Charente"}, "17": {"lat": 45.7657, "lon": -0.6542, "name": "Charente-Maritime"}, "18": {"lat": 47.0658, "lon": 2.4911, "name": "Cher"}, "19": {"lat": 45.3573, "lon": 1.8777, "name": "Corrèze"}, "20": {"lat": 42.1517, "lon": 9.106, "name": "Corse (código postal 20)"}, "21": {"lat": 47.4261, "lon": 4.7727, "name": "Côte-d'Or"}, "22": {"lat": 48.4405, "lon": -2.8645, "name": "Côtes-d'Armor"}, "23": {"lat": 46.0906, "lon": 2.0182, "name": "Creuse"}, "24": {"lat": 45.1049, "lon": 0.7412, "name": "Dordogne"}, "25": {"lat": 47.1659, "lon": 6.3627, "name": "Doubs"}, "26": {"lat": 44.6791, "lon": 5.1635, "name": "Drôme"}, "27": {"lat": 49.1137, "lon": 0.9964, "name": "Eure"}, "28": {"lat": 48.388, "lon": 1.37, "name": "Eure-et-Loir"}, "29": {"lat": 48.2611, "lon": -4.0571, "name": "Finistère"}, "2A": {"lat": 41.8643, "lon": 8.9875, "name": "Corse-du-Sud"}, "2B": {"lat": 42.3949, "lon": 9.2062, "name": "Haute-Corse"}, "30": {"lat": 43.9936, "lon": 4.1799, "name": "Gard"}, "31": {"lat": 43.3589, "lon": 1.175, "name": "Haute-Garonne"}, "32": {"lat": 43.6929, "lon": 0.4529, "name": "Gers"}, "33": {"lat": 44.839, "lon": -0.5831, "name": "Gironde"}, "34": {"lat": 43.5795, "lon": 3.3685, "name": "Hérault"}, "35": {"lat": 48.1509, "lon": -1.6341, "name": "Ille-et-Vilaine"}, "36": {"lat": 46.7783, "lon": 1.576, "name": "Indre"}, "37": {"lat": 47.2585, "lon": 0.6911, "name": "Indre-et-Loire"}, "38": {"lat": 45.2639, "lon": 5.5742, "name": "Isère"}, "39": {"lat": 46.7293, "lon": 5.6974, "name": "Jura"}, "40": {"lat": 43.9658, "lon": -0.7837, "name": "Landes"}, "41": {"lat": 47.6168, "lon": 1.4279, "name": "Loir-et-Cher"}, "42": {"lat": 45.728, "lon": 4.1646, "name": "Loire"}, "43": {"lat": 45.1281, "lon": 3.8063, "name": "Haute-Loire"}, "44": {"lat": 47.363, "lon": -1.6792, "name": "Loire-Atlantique"}, "45": {"lat": 47.9119, "lon": 2.344, "name": "Loiret"}, "46": {"lat": 44.6246, "lon": 1.6055, "name": "Lot"}, "47": {"lat": 44.3679, "lon": 0.4607, "name": "Lot-et-Garonne"}, "48": {"lat": 44.5175, "lon": 3.4997, "name": "Lozère"}, "49": {"lat": 47.3898, "lon": -0.5594, "name": "Maine-et-Loire"}, "50": {"lat": 49.0813, "lon": -1.3288, "name": "Manche"}, "51": {"lat": 48.9499, "lon": 4.2385, "name": "Marne"}, "52": {"lat": 48.1104, "lon": 5.2255, "name": "Haute-Marne"}, "53": {"lat": 48.1472, "lon": -0.6574, "name": "Mayenne"}, "54": {"lat": 48.7882, "lon": 6.1624, "name": "Meurthe-et-Moselle"}, "55": {"lat": 48.9914, "lon": 5.3815, "name": "Meuse"}, "56": {"lat": 47.8554, "lon": -2.8045, "name": "Morbihan"}, "57": {"lat": 49.0375, "lon": 6.6614, "name": "Moselle"}, "58": {"lat": 47.1157, "lon": 3.5042, "name": "Nièvre"}, "59": {"lat": 50.4488, "lon": 3.2162, "name": "Nord"}, "60": {"lat": 49.4099, "lon": 2.4249, "name": "Oise"}, "61": {"lat": 48.6231, "lon": 0.1278, "name": "Orne"}, "62": {"lat": 50.4926, "lon": 2.2888, "name": "Pas-de-Calais"}, "63": {"lat": 45.7259, "lon": 3.1402, "name": "Puy-de-Dôme"}, "64": {"lat": 43.2566, "lon": -0.7581, "name": "Pyrénées-Atlantiques"}, "65": {"lat": 43.0513, "lon": 0.1664, "name": "Hautes-Pyrénées"}, "66": {"lat": 42.5993, "lon": 2.5207, "name": "Pyrénées-Orientales"}, "67": {"lat": 48.6715, "lon": 7.552, "name": "Bas-Rhin"}, "68": {"lat": 47.8594, "lon": 7.274, "name": "Haut-Rhin"}, "69": {"lat": 45.871, "lon": 4.6408, "name": "Rhône"}, "70": {"lat": 47.6412, "lon": 6.0872, "name": "Haute-Saône"}, "71": {"lat": 46.6448, "lon": 4.5428, "name": "Saône-et-Loire"}, "72": {"lat": 47.9949, "lon": 0.2226, "name": "Sarthe"}, "73": {"lat": 45.4775, "lon": 6.4429, "name": "Savoie"}, "74": {"lat": 46.0346, "lon": 6.4284, "name": "Haute-Savoie"}, "75": {"lat": 48.8566, "lon": 2.3428, "name": "Paris"}, "76": {"lat": 49.6547, "lon": 1.0272, "name": "Seine-Maritime"}, "77": {"lat": 48.6275, "lon": 2.9341, "name": "Seine-et-Marne"}, "78": {"lat": 48.8153, "lon": 1.8413, "name": "Yvelines"}, "79": {"lat": 46.557, "lon": -0.3178, "name": "Deux-Sèvres"}, "80": {"lat": 49.9579, "lon": 2.2761, "name": "Somme"}, "81": {"lat": 43.7857, "lon": 2.1657, "name": "Tarn"}, "82": {"lat": 44.0858, "lon": 1.2822, "name": "Tarn-et-Garonne"}, "83": {"lat": 43.4438, "lon": 6.2442, "name": "Var"}, "84": {"lat": 43.994, "lon": 5.1852, "name": "Vaucluse"}, "85": {"lat": 46.6726, "lon": -1.2877, "name": "Vendée"}, "86": {"lat": 46.5649, "lon": 0.4595, "name": "Vienne"}, "87": {"lat": 45.8922, "lon": 1.2348, "name": "Haute-Vienne"}, "88": {"lat": 48.1962, "lon": 6.3802, "name": "Vosges"}, "89": {"lat": 47.8405, "lon": 3.5633, "name": "Yonne"}, "90": {"lat": 47.6317, "lon": 6.9286, "name": "Territoire de Belfort"}, "91": {"lat": 48.5226, "lon": 2.2434, "name": "Essonne"}, "92": {"lat": 48.8475, "lon": 2.2461, "name": "Hauts-de-Seine"}, "93": {"lat": 48.9176, "lon": 2.4784, "name": "Seine-Saint-Denis"}, "94": {"lat": 48.7774, "lon": 2.4693, "name": "Val-de-Marne"}, "95": {"lat": 49.0827, "lon": 2.131, "name": "Val-d'Oise"}};
const FR_REGIONS: Record<string, GeoPoint & { name: string }> = {"01": {"lat": 15.9985, "lon": -61.7294, "name": "Guadeloupe (Basse-Terre)"}, "02": {"lat": 14.6161, "lon": -61.0588, "name": "Martinique (Fort-de-France)"}, "03": {"lat": 4.9372, "lon": -52.326, "name": "Guyane (Cayenne)"}, "04": {"lat": -20.8823, "lon": 55.4504, "name": "La Réunion (Saint-Denis)"}, "06": {"lat": -12.7806, "lon": 45.2278, "name": "Mayotte (Mamoudzou)"}, "11": {"lat": 48.7093, "lon": 2.5034, "name": "Île-de-France"}, "24": {"lat": 47.4847, "lon": 1.6844, "name": "Centre-Val de Loire"}, "27": {"lat": 47.2343, "lon": 4.8071, "name": "Bourgogne-Franche-Comté"}, "28": {"lat": 49.1202, "lon": 0.1108, "name": "Normandie"}, "32": {"lat": 49.9693, "lon": 2.7715, "name": "Hauts-de-France"}, "44": {"lat": 48.6889, "lon": 5.6131, "name": "Grand Est"}, "52": {"lat": 47.4793, "lon": -0.8137, "name": "Pays de la Loire"}, "53": {"lat": 48.1803, "lon": -2.8394, "name": "Bretagne"}, "75": {"lat": 45.2033, "lon": 0.212, "name": "Nouvelle-Aquitaine"}, "76": {"lat": 43.7024, "lon": 2.1453, "name": "Occitanie"}, "84": {"lat": 45.5126, "lon": 4.5369, "name": "Auvergne-Rhône-Alpes"}, "93": {"lat": 43.9556, "lon": 6.0604, "name": "Provence-Alpes-Côte d'Azur"}, "94": {"lat": 42.1517, "lon": 9.106, "name": "Corse"}};
const FR_OVERSEAS: Record<string, GeoPoint & { name: string }> = {"971": {"lat": 15.9985, "lon": -61.7294, "name": "Guadeloupe (Basse-Terre)"}, "972": {"lat": 14.6161, "lon": -61.0588, "name": "Martinique (Fort-de-France)"}, "973": {"lat": 4.9372, "lon": -52.326, "name": "Guyane (Cayenne)"}, "974": {"lat": -20.8823, "lon": 55.4504, "name": "La Réunion (Saint-Denis)"}, "975": {"lat": 46.8852, "lon": -56.3159, "name": "Saint-Pierre-et-Miquelon"}, "976": {"lat": -12.7806, "lon": 45.2278, "name": "Mayotte (Mamoudzou)"}, "977": {"lat": 17.9, "lon": -62.8333, "name": "Saint-Barthélemy"}, "978": {"lat": 18.0708, "lon": -63.0501, "name": "Saint-Martin"}};
const FR_COUNTRY: GeoPoint & { name: string } = {"lat": 46.6, "lon": 2.5, "name": "França"};

export const FRANCE_LEVEL_LABELS: Record<FranceLevel, string> = {
  departamento: "Departamento",
  regiao: "Regiao",
  pais: "Pais",
};

export function isOffshoreFranceRegion(region: { lat: number; lon: number }): boolean {
  return region.lat < 41 || region.lon < -6;
}

export function resolveFranceRegion(code: string, level?: string): FranceRegion | null {
  const key = (code || "").trim();
  if (!key) return null;
  if (level === "pais" || key === "FR") {
    return { code: "FR", name: FR_COUNTRY.name, pais: "FR", level: "pais", approx: false, offshore: false, lat: FR_COUNTRY.lat, lon: FR_COUNTRY.lon };
  }
  if (level === "regiao") {
    const r = FR_REGIONS[key];
    if (!r) return { code: key, name: `Regiao <<${key}>>`, pais: "FR", level: "regiao", approx: true, offshore: false, lat: FR_COUNTRY.lat, lon: FR_COUNTRY.lon };
    return { code: key, name: r.name, pais: "FR", level: "regiao", approx: false, offshore: r.lat < 41 || r.lon < -6, lat: r.lat, lon: r.lon };
  }
  const dep = FR_DEPARTMENTS[key] || FR_OVERSEAS[key];
  if (dep) {
    return { code: key, name: dep.name, pais: "FR", level: "departamento", approx: false, offshore: dep.lat < 41 || dep.lon < -6, lat: dep.lat, lon: dep.lon };
  }
  return null;
}

export function allFranceRegions(): FranceRegion[] {
  const out: FranceRegion[] = [];
  for (const [code, dep] of Object.entries(FR_DEPARTMENTS)) {
    out.push({ code, name: dep.name, pais: "FR", level: "departamento", approx: false, offshore: dep.lat < 41 || dep.lon < -6, lat: dep.lat, lon: dep.lon });
  }
  for (const [code, reg] of Object.entries(FR_REGIONS)) {
    out.push({ code, name: reg.name, pais: "FR", level: "regiao", approx: false, offshore: reg.lat < 41 || reg.lon < -6, lat: reg.lat, lon: reg.lon });
  }
  return out;
}
