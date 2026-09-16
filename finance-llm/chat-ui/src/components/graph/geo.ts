/**
 * Georreferenciação dos nós do grafo.
 *
 * Os dados de contratos trazem códigos NUTS (ex.: "PT11A - Área Metropolitana do Porto"),
 * mas não trazem coordenadas. Este módulo resolve um código/nome para um centroide
 * e diz explicitamente se essa posição é exata (centroide do próprio NUTS) ou aproximada
 * (centroide do NUTS pai ou do país) — o mapa usa essa informação para não apresentar
 * posições aproximadas como se fossem reais.
 */

export type GeoPoint = { lat: number; lon: number };
export type ResolvedPlace = GeoPoint & { exact: boolean };

/** Centro inicial do mapa (Portugal continental). */
export const MAP_CENTER: GeoPoint = { lat: 39.5, lon: -8.2 };
/** Lado de um tile do OpenStreetMap, em píxeis CSS. */
export const TILE_SIZE = 256;

export function lonToWorld(lon: number, zoom: number) {
  return ((lon + 180) / 360) * TILE_SIZE * 2 ** zoom;
}

export function latToWorld(lat: number, zoom: number) {
  const clamped = Math.max(-85.05, Math.min(85.05, lat));
  const sin = Math.sin((clamped * Math.PI) / 180);
  return (0.5 - Math.log((1 + sin) / (1 - sin)) / (4 * Math.PI)) * TILE_SIZE * 2 ** zoom;
}

/** Inversa de `lonToWorld` (usada na navegação do mapa). */
export function worldToLon(worldX: number, zoom: number) {
  return (worldX / (TILE_SIZE * 2 ** zoom)) * 360 - 180;
}

/** Inversa de `latToWorld` (usada na navegação do mapa). */
export function worldToLat(worldY: number, zoom: number) {
  const n = Math.PI - (2 * Math.PI * worldY) / (TILE_SIZE * 2 ** zoom);
  return (180 / Math.PI) * Math.atan(0.5 * (Math.exp(n) - Math.exp(-n)));
}

/** Centroides exatos por código NUTS II/III (código é a chave fiável). */
const PLACE_COORDS_BY_CODE: Record<string, GeoPoint> = {
  // NUTS II — Portugal
  PT11: { lat: 41.35, lon: -8.15 },
  PT15: { lat: 37.15, lon: -7.95 },
  PT16: { lat: 40.2, lon: -8.2 },
  PT17: { lat: 38.72, lon: -9.14 },
  PT18: { lat: 38.2, lon: -7.9 },
  PT19: { lat: 40.2, lon: -8.3 },
  PT1A: { lat: 38.72, lon: -9.14 },
  PT1B: { lat: 38.55, lon: -9.0 },
  PT1C: { lat: 38.3, lon: -7.9 },
  PT1D: { lat: 39.4, lon: -8.6 },
  PT20: { lat: 38.6, lon: -27.9 },
  PT30: { lat: 32.75, lon: -16.95 },
  PTZZ: { lat: 39.5, lon: -8.2 },
  // NUTS III — Norte
  PT111: { lat: 41.87, lon: -8.62 },
  PT112: { lat: 41.55, lon: -8.55 },
  PT119: { lat: 41.4, lon: -8.35 },
  PT11A: { lat: 41.15, lon: -8.6 },
  PT11B: { lat: 41.6, lon: -7.7 },
  PT11C: { lat: 41.2, lon: -8.15 },
  PT11D: { lat: 41.15, lon: -7.4 },
  PT11E: { lat: 41.6, lon: -6.95 },
  // NUTS III — Centro
  PT16B: { lat: 39.3, lon: -9.15 },
  PT16D: { lat: 40.6, lon: -8.5 },
  PT16E: { lat: 40.2, lon: -8.4 },
  PT16F: { lat: 39.7, lon: -8.8 },
  PT16G: { lat: 40.6, lon: -7.9 },
  PT16H: { lat: 39.8, lon: -7.45 },
  PT16I: { lat: 40.4, lon: -7.3 },
  PT16J: { lat: 39.5, lon: -8.3 },
  PT191: { lat: 40.6, lon: -8.5 },
  PT192: { lat: 40.2, lon: -8.4 },
  PT193: { lat: 39.7, lon: -8.8 },
  PT194: { lat: 40.6, lon: -7.9 },
  PT195: { lat: 39.8, lon: -7.45 },
  PT196: { lat: 40.4, lon: -7.3 },
  // NUTS III — Lisboa / Alentejo
  PT1A0: { lat: 38.72, lon: -9.14 },
  PT1B0: { lat: 38.55, lon: -9.0 },
  PT1C1: { lat: 37.9, lon: -8.7 },
  PT1C2: { lat: 37.7, lon: -7.9 },
  PT1C3: { lat: 39.0, lon: -7.5 },
  PT1C4: { lat: 38.5, lon: -7.85 },
  PT1D1: { lat: 39.3, lon: -9.15 },
  PT1D2: { lat: 39.5, lon: -8.3 },
  PT1D3: { lat: 39.2, lon: -8.6 },
  PT180: { lat: 38.52, lon: -8.89 },
  PT181: { lat: 37.9, lon: -8.7 },
  PT182: { lat: 39.0, lon: -7.5 },
  PT184: { lat: 38.5, lon: -7.85 },
  PT185: { lat: 37.7, lon: -7.9 },
  PT186: { lat: 39.2, lon: -8.6 },
  PT187: { lat: 38.0, lon: -7.9 },
  // NUTS III — Ilhas
  PT150: { lat: 37.02, lon: -7.93 },
  PT200: { lat: 38.6, lon: -27.9 },
  PT300: { lat: 32.75, lon: -16.95 },
  // NUTS III — Espanha (fronteira e grandes centros)
  ES111: { lat: 43.0, lon: -8.4 },
  ES114: { lat: 42.43, lon: -8.65 },
  ES120: { lat: 43.36, lon: -5.85 },
  ES130: { lat: 43.2, lon: -4.0 },
  ES211: { lat: 42.85, lon: -2.67 },
  ES212: { lat: 43.32, lon: -1.98 },
  ES213: { lat: 43.26, lon: -2.93 },
  ES220: { lat: 42.82, lon: -1.65 },
  ES230: { lat: 42.29, lon: -2.45 },
  ES241: { lat: 42.6, lon: -0.9 },
  ES243: { lat: 41.66, lon: -0.88 },
  ES300: { lat: 40.42, lon: -3.7 },
  ES411: { lat: 40.97, lon: -5.66 },
  ES412: { lat: 42.35, lon: -3.7 },
  ES413: { lat: 42.6, lon: -6.0 },
  ES414: { lat: 41.65, lon: -4.72 },
  ES415: { lat: 40.66, lon: -4.7 },
  ES416: { lat: 40.95, lon: -4.12 },
  ES418: { lat: 41.65, lon: -4.72 },
  ES419: { lat: 41.5, lon: -5.75 },
  ES421: { lat: 38.99, lon: -1.86 },
  ES422: { lat: 39.4, lon: -3.5 },
  ES423: { lat: 39.9, lon: -2.9 },
  ES424: { lat: 40.6, lon: -3.16 },
  ES425: { lat: 39.86, lon: -4.02 },
  ES431: { lat: 38.88, lon: -6.97 },
  ES432: { lat: 39.47, lon: -6.37 },
  ES511: { lat: 41.39, lon: 2.17 },
  ES512: { lat: 42.27, lon: 2.96 },
  ES513: { lat: 42.0, lon: 1.5 },
  ES514: { lat: 40.5, lon: 0.5 },
  ES521: { lat: 38.35, lon: -0.48 },
  ES522: { lat: 39.5, lon: -0.4 },
  ES523: { lat: 39.47, lon: -0.38 },
  ES531: { lat: 39.6, lon: 2.9 },
  ES532: { lat: 39.6, lon: 3.0 },
  ES533: { lat: 38.9, lon: 1.4 },
  ES611: { lat: 36.84, lon: -2.46 },
  ES612: { lat: 36.53, lon: -6.29 },
  ES613: { lat: 37.88, lon: -4.78 },
  ES614: { lat: 37.18, lon: -3.6 },
  ES615: { lat: 37.26, lon: -6.95 },
  ES616: { lat: 37.77, lon: -3.79 },
  ES617: { lat: 36.72, lon: -4.42 },
  ES618: { lat: 37.39, lon: -5.99 },
  ES620: { lat: 37.99, lon: -1.13 },
  ES630: { lat: 35.89, lon: -5.32 },
  ES640: { lat: 35.29, lon: -2.95 },
  ES703: { lat: 28.49, lon: -16.31 },
  ES704: { lat: 28.35, lon: -14.05 },
  ES705: { lat: 28.1, lon: -15.42 },
  ES707: { lat: 28.68, lon: -17.76 },
  ES709: { lat: 28.29, lon: -16.62 },
};

/** Coordenadas de NUTS pai (aproximadas) quando o código exato não é conhecido. */
const NUTS_PREFIX_COORDS: Record<string, GeoPoint> = {
  // Portugal
  PT11: { lat: 41.35, lon: -8.15 },
  PT15: { lat: 37.15, lon: -7.95 },
  PT16: { lat: 40.2, lon: -8.2 },
  PT17: { lat: 38.72, lon: -9.14 },
  PT18: { lat: 38.2, lon: -7.9 },
  PT19: { lat: 40.2, lon: -8.3 },
  PT1A: { lat: 38.72, lon: -9.14 },
  PT1B: { lat: 38.55, lon: -9.0 },
  PT1C: { lat: 38.3, lon: -7.9 },
  PT1D: { lat: 39.4, lon: -8.6 },
  PT20: { lat: 38.6, lon: -27.9 },
  PT30: { lat: 32.75, lon: -16.95 },
  // Espanha
  ES11: { lat: 42.7, lon: -8.0 },
  ES12: { lat: 43.3, lon: -6.0 },
  ES13: { lat: 43.2, lon: -4.0 },
  ES21: { lat: 43.0, lon: -2.6 },
  ES22: { lat: 42.7, lon: -1.6 },
  ES23: { lat: 42.3, lon: -2.4 },
  ES24: { lat: 41.7, lon: -0.9 },
  ES30: { lat: 40.4, lon: -3.7 },
  ES41: { lat: 41.6, lon: -4.7 },
  ES42: { lat: 39.5, lon: -3.0 },
  ES43: { lat: 39.0, lon: -6.2 },
  ES51: { lat: 41.6, lon: 1.6 },
  ES52: { lat: 39.2, lon: -0.6 },
  ES53: { lat: 39.6, lon: 3.0 },
  ES61: { lat: 37.4, lon: -4.7 },
  ES62: { lat: 38.0, lon: -1.4 },
  ES63: { lat: 35.89, lon: -5.32 },
  ES64: { lat: 35.29, lon: -2.95 },
  ES70: { lat: 28.3, lon: -15.6 },
  // França
  FR10: { lat: 48.85, lon: 2.35 },
  FRB0: { lat: 47.4, lon: 1.7 },
  FRD0: { lat: 49.1, lon: 0.1 },
  FRE1: { lat: 50.4, lon: 3.0 },
  FRE2: { lat: 49.5, lon: 2.5 },
  FRF0: { lat: 48.4, lon: 7.3 },
  FRG0: { lat: 47.4, lon: -1.0 },
  FRH0: { lat: 48.2, lon: -3.0 },
  FRI1: { lat: 44.8, lon: -0.5 },
  FRI2: { lat: 45.5, lon: 1.0 },
  FRI3: { lat: 46.3, lon: 0.0 },
  FRJ1: { lat: 43.6, lon: 3.5 },
  FRJ2: { lat: 43.9, lon: 1.3 },
  FRK2: { lat: 45.4, lon: 4.8 },
  FRL0: { lat: 43.9, lon: 5.5 },
  FRM0: { lat: 42.15, lon: 9.1 },
  // Alemanha
  DE1: { lat: 48.6, lon: 9.0 },
  DE2: { lat: 48.9, lon: 11.4 },
  DE3: { lat: 52.52, lon: 13.4 },
  DE4: { lat: 52.4, lon: 13.0 },
  DE5: { lat: 53.1, lon: 8.8 },
  DE6: { lat: 53.55, lon: 10.0 },
  DE7: { lat: 50.6, lon: 8.7 },
  DE8: { lat: 53.8, lon: 12.6 },
  DE9: { lat: 52.65, lon: 9.3 },
  DEA: { lat: 51.4, lon: 7.0 },
  DEB: { lat: 49.9, lon: 7.5 },
  DEC: { lat: 49.4, lon: 6.9 },
  DED: { lat: 51.0, lon: 13.3 },
  DEE: { lat: 51.9, lon: 11.7 },
  DEF: { lat: 54.2, lon: 9.7 },
  DEG: { lat: 50.9, lon: 11.0 },
  // Itália
  ITC1: { lat: 45.1, lon: 7.7 },
  ITC2: { lat: 45.7, lon: 7.3 },
  ITC3: { lat: 44.4, lon: 8.9 },
  ITC4: { lat: 45.5, lon: 9.7 },
  ITH1: { lat: 46.5, lon: 11.3 },
  ITH2: { lat: 46.1, lon: 12.5 },
  ITH3: { lat: 45.6, lon: 11.6 },
  ITH4: { lat: 45.7, lon: 13.5 },
  ITH5: { lat: 44.6, lon: 11.0 },
  ITI1: { lat: 43.5, lon: 11.0 },
  ITI2: { lat: 43.0, lon: 12.5 },
  ITI3: { lat: 43.4, lon: 13.2 },
  ITI4: { lat: 41.9, lon: 12.6 },
  ITF1: { lat: 42.3, lon: 13.8 },
  ITF2: { lat: 41.5, lon: 14.6 },
  ITF3: { lat: 40.8, lon: 14.8 },
  ITF4: { lat: 40.9, lon: 16.6 },
  ITF5: { lat: 40.1, lon: 16.0 },
  ITF6: { lat: 39.2, lon: 16.5 },
  ITG1: { lat: 37.5, lon: 14.0 },
  ITG2: { lat: 39.2, lon: 9.1 },
  // Grécia, Suíça, Áustria, Bélgica, Restantes
  EL30: { lat: 38.0, lon: 23.7 },
  EL41: { lat: 39.6, lon: 19.9 },
  EL42: { lat: 40.6, lon: 22.9 },
  EL43: { lat: 35.3, lon: 25.1 },
  EL51: { lat: 41.1, lon: 25.4 },
  EL52: { lat: 40.7, lon: 23.0 },
  EL53: { lat: 40.5, lon: 21.8 },
  EL54: { lat: 39.4, lon: 20.9 },
  EL61: { lat: 39.3, lon: 22.8 },
  EL62: { lat: 38.6, lon: 20.9 },
  EL63: { lat: 37.6, lon: 21.6 },
  EL64: { lat: 38.4, lon: 23.0 },
  EL65: { lat: 37.4, lon: 24.5 },
  CH01: { lat: 46.5, lon: 6.6 },
  CH02: { lat: 47.0, lon: 7.4 },
  CH03: { lat: 47.5, lon: 7.8 },
  CH04: { lat: 47.4, lon: 8.6 },
  CH05: { lat: 47.4, lon: 9.3 },
  CH06: { lat: 47.0, lon: 8.3 },
  CH07: { lat: 46.2, lon: 8.9 },
  AT11: { lat: 47.0, lon: 16.4 },
  AT12: { lat: 48.2, lon: 15.6 },
  AT13: { lat: 48.2, lon: 16.4 },
  AT21: { lat: 46.6, lon: 14.3 },
  AT22: { lat: 47.0, lon: 15.4 },
  AT31: { lat: 48.2, lon: 14.0 },
  AT32: { lat: 47.8, lon: 13.0 },
  AT33: { lat: 47.3, lon: 11.4 },
  AT34: { lat: 47.5, lon: 9.7 },
  BE10: { lat: 50.85, lon: 4.35 },
  BE21: { lat: 51.2, lon: 4.6 },
  BE22: { lat: 51.0, lon: 5.4 },
  BE23: { lat: 51.0, lon: 3.8 },
  BE24: { lat: 50.9, lon: 4.7 },
  BE25: { lat: 51.2, lon: 3.2 },
  BE31: { lat: 50.6, lon: 5.3 },
  BE32: { lat: 50.5, lon: 4.2 },
  BE33: { lat: 50.6, lon: 5.7 },
  BE34: { lat: 50.0, lon: 5.4 },
  BE35: { lat: 50.4, lon: 4.9 },
  LU00: { lat: 49.8, lon: 6.1 },
  NO01: { lat: 59.9, lon: 10.8 },
  NO02: { lat: 60.8, lon: 11.0 },
  NO03: { lat: 59.4, lon: 6.0 },
  NO04: { lat: 61.5, lon: 6.0 },
  NO05: { lat: 63.0, lon: 9.5 },
  NO06: { lat: 65.5, lon: 13.0 },
  NO07: { lat: 69.6, lon: 20.0 },
  DK01: { lat: 55.7, lon: 12.5 },
  DK02: { lat: 55.4, lon: 11.8 },
  DK03: { lat: 55.4, lon: 9.5 },
  DK04: { lat: 56.2, lon: 9.2 },
  DK05: { lat: 57.0, lon: 9.9 },
  IE01: { lat: 53.5, lon: -7.5 },
  IE02: { lat: 51.9, lon: -8.5 },
  IE04: { lat: 54.3, lon: -8.5 },
  IE05: { lat: 52.4, lon: -8.0 },
  IE06: { lat: 53.35, lon: -6.3 },
  FI19: { lat: 61.5, lon: 23.0 },
  FI1B: { lat: 60.3, lon: 24.9 },
  FI1C: { lat: 60.5, lon: 22.3 },
  FI1D: { lat: 64.0, lon: 27.0 },
  FI20: { lat: 60.1, lon: 19.9 },
  EE00: { lat: 58.7, lon: 25.5 },
  HU11: { lat: 47.5, lon: 19.05 },
  HU12: { lat: 47.2, lon: 19.4 },
  HU21: { lat: 47.2, lon: 18.4 },
  HU31: { lat: 48.1, lon: 20.8 },
  HU32: { lat: 47.5, lon: 21.6 },
  SK01: { lat: 48.15, lon: 17.1 },
  SK02: { lat: 48.6, lon: 17.8 },
  RO11: { lat: 46.9, lon: 23.4 },
  RO12: { lat: 45.8, lon: 24.9 },
  RO21: { lat: 46.5, lon: 27.3 },
  RO22: { lat: 45.2, lon: 28.1 },
  RO31: { lat: 44.7, lon: 26.3 },
  RO32: { lat: 44.4, lon: 26.1 },
  RO41: { lat: 44.4, lon: 23.8 },
  RO42: { lat: 45.7, lon: 21.9 },
  NL11: { lat: 53.2, lon: 6.6 },
  NL12: { lat: 53.0, lon: 6.1 },
  NL13: { lat: 52.6, lon: 6.5 },
  NL21: { lat: 52.2, lon: 5.9 },
  NL22: { lat: 52.0, lon: 5.3 },
  NL23: { lat: 52.4, lon: 4.9 },
  NL31: { lat: 52.0, lon: 4.7 },
  NL32: { lat: 52.4, lon: 4.8 },
  NL33: { lat: 51.9, lon: 4.4 },
  NL34: { lat: 51.5, lon: 3.8 },
  NL41: { lat: 51.5, lon: 5.3 },
  NL42: { lat: 51.1, lon: 5.9 },
  PL11: { lat: 51.3, lon: 19.4 },
  PL12: { lat: 52.2, lon: 20.8 },
  PL21: { lat: 50.1, lon: 19.9 },
  PL22: { lat: 50.4, lon: 18.9 },
  PL31: { lat: 51.2, lon: 22.6 },
  PL32: { lat: 50.3, lon: 22.0 },
  PL33: { lat: 50.7, lon: 21.2 },
  PL34: { lat: 53.1, lon: 23.1 },
  PL41: { lat: 52.4, lon: 16.9 },
  PL42: { lat: 53.4, lon: 14.6 },
  PL43: { lat: 51.9, lon: 15.5 },
  PL51: { lat: 51.1, lon: 17.0 },
  PL52: { lat: 50.7, lon: 17.9 },
  PL61: { lat: 53.1, lon: 18.5 },
  PL62: { lat: 53.8, lon: 20.5 },
  PL63: { lat: 54.4, lon: 18.6 },
  CZ01: { lat: 50.1, lon: 14.4 },
  CZ02: { lat: 50.1, lon: 14.9 },
  CZ03: { lat: 49.5, lon: 13.5 },
  CZ04: { lat: 50.4, lon: 13.6 },
  CZ05: { lat: 50.4, lon: 15.6 },
  CZ06: { lat: 49.4, lon: 15.6 },
  CZ07: { lat: 49.2, lon: 16.6 },
  CZ08: { lat: 49.8, lon: 18.2 },
  SE11: { lat: 59.3, lon: 18.1 },
  SE12: { lat: 58.4, lon: 15.6 },
  SE21: { lat: 57.1, lon: 14.5 },
  SE22: { lat: 55.7, lon: 13.2 },
  SE23: { lat: 57.7, lon: 12.0 },
  SE31: { lat: 58.4, lon: 13.5 },
  SE32: { lat: 62.4, lon: 16.5 },
  SE33: { lat: 65.6, lon: 22.1 },
  BG31: { lat: 43.2, lon: 25.3 },
  BG32: { lat: 43.3, lon: 26.9 },
  BG33: { lat: 43.4, lon: 28.0 },
  BG34: { lat: 42.4, lon: 25.6 },
  BG41: { lat: 42.7, lon: 23.3 },
  BG42: { lat: 42.0, lon: 25.0 },
  HR03: { lat: 45.4, lon: 15.3 },
  HR04: { lat: 45.8, lon: 16.0 },
  HR05: { lat: 45.3, lon: 18.7 },
  HR06: { lat: 43.6, lon: 16.5 },
  SI03: { lat: 46.1, lon: 14.8 },
  SI04: { lat: 46.4, lon: 15.2 },
  LT01: { lat: 54.7, lon: 25.3 },
  LT02: { lat: 55.3, lon: 21.4 },
  LV00: { lat: 56.9, lon: 24.6 },
  CY00: { lat: 35.0, lon: 33.2 },
  MT00: { lat: 35.9, lon: 14.4 },
  IS00: { lat: 64.9, lon: -18.6 },
  TR10: { lat: 41.0, lon: 28.9 },
  TR51: { lat: 39.9, lon: 32.9 },
  UKI: { lat: 51.5, lon: -0.1 },
  UKJ: { lat: 51.8, lon: -1.3 },
  UKD: { lat: 53.5, lon: -2.6 },
  UKE: { lat: 53.8, lon: -1.5 },
  UKF: { lat: 52.6, lon: -1.2 },
  UKG: { lat: 52.5, lon: -2.0 },
  UKH: { lat: 52.3, lon: 0.7 },
  UKL: { lat: 51.5, lon: -3.2 },
  UKM: { lat: 56.5, lon: -4.0 },
};

/** Centroides de região/distrito por nome (reforço quando o código não é conhecido). */
const PLACE_COORDS_BY_NAME: Record<string, GeoPoint> = {
  "area metropolitana de lisboa": { lat: 38.72, lon: -9.14 },
  "grande lisboa": { lat: 38.72, lon: -9.14 },
  "peninsula de setubal": { lat: 38.52, lon: -8.89 },
  "area metropolitana do porto": { lat: 41.15, lon: -8.6 },
  "regiao autonoma dos acores": { lat: 38.6, lon: -27.9 },
  "regiao autonoma da madeira": { lat: 32.75, lon: -16.95 },
  "terras de tras-os-montes": { lat: 41.6, lon: -6.95 },
  "beiras e serra da estrela": { lat: 40.4, lon: -7.3 },
  "alentejo litoral": { lat: 37.9, lon: -8.7 },
  "alto alentejo": { lat: 39.0, lon: -7.5 },
  "alentejo central": { lat: 38.5, lon: -7.85 },
  "baixo alentejo": { lat: 37.7, lon: -7.9 },
  "alto minho": { lat: 41.87, lon: -8.62 },
  "alto tamega": { lat: 41.6, lon: -7.7 },
  "alto tamega e barroso": { lat: 41.6, lon: -7.7 },
  "tamega e sousa": { lat: 41.2, lon: -8.15 },
  "viseu dao lafoes": { lat: 40.6, lon: -7.9 },
  "regiao de aveiro": { lat: 40.6, lon: -8.5 },
  "regiao de coimbra": { lat: 40.2, lon: -8.4 },
  "regiao de leiria": { lat: 39.7, lon: -8.8 },
  "medio tejo": { lat: 39.5, lon: -8.3 },
  "leziria do tejo": { lat: 39.2, lon: -8.6 },
  "beira baixa": { lat: 39.8, lon: -7.45 },
  "viana do castelo": { lat: 41.69, lon: -8.83 },
  "castelo branco": { lat: 39.82, lon: -7.49 },
  "vila real": { lat: 41.3, lon: -7.74 },
  braganca: { lat: 41.81, lon: -6.76 },
  cavado: { lat: 41.55, lon: -8.55 },
  douro: { lat: 41.15, lon: -7.4 },
  oeste: { lat: 39.3, lon: -9.15 },
  ave: { lat: 41.4, lon: -8.35 },
  algarve: { lat: 37.02, lon: -7.93 },
  acores: { lat: 38.6, lon: -27.9 },
  madeira: { lat: 32.75, lon: -16.95 },
  lisboa: { lat: 38.72, lon: -9.14 },
  porto: { lat: 41.15, lon: -8.6 },
  braga: { lat: 41.55, lon: -8.42 },
  coimbra: { lat: 40.21, lon: -8.43 },
  faro: { lat: 37.02, lon: -7.93 },
  setubal: { lat: 38.52, lon: -8.89 },
  santarem: { lat: 39.24, lon: -8.69 },
  leiria: { lat: 39.74, lon: -8.81 },
  aveiro: { lat: 40.64, lon: -8.65 },
  viseu: { lat: 40.66, lon: -7.91 },
  guarda: { lat: 40.54, lon: -7.27 },
  portalegre: { lat: 39.29, lon: -7.43 },
  evora: { lat: 38.57, lon: -7.91 },
  beja: { lat: 38.02, lon: -7.87 },
  // NUTS estrangeiros mais frequentes
  pontevedra: { lat: 42.43, lon: -8.65 },
  "a coruna": { lat: 43.36, lon: -8.4 },
  madrid: { lat: 40.42, lon: -3.7 },
  barcelona: { lat: 41.39, lon: 2.17 },
  sevilla: { lat: 37.39, lon: -5.99 },
  malaga: { lat: 36.72, lon: -4.42 },
  huelva: { lat: 37.26, lon: -6.95 },
  badajoz: { lat: 38.88, lon: -6.97 },
  zamora: { lat: 41.5, lon: -5.75 },
  paris: { lat: 48.85, lon: 2.35 },
  "alpes-maritimes": { lat: 43.7, lon: 7.26 },
  berlin: { lat: 52.52, lon: 13.4 },
  stuttgart: { lat: 48.78, lon: 9.18 },
  dusseldorf: { lat: 51.22, lon: 6.78 },
  munchen: { lat: 48.14, lon: 11.58 },
  "frankfurt am main": { lat: 50.11, lon: 8.68 },
  bonn: { lat: 50.73, lon: 7.1 },
  wien: { lat: 48.21, lon: 16.37 },
  zurich: { lat: 47.37, lon: 8.54 },
  geneve: { lat: 46.2, lon: 6.14 },
  "basel-stadt": { lat: 47.56, lon: 7.59 },
  luxembourg: { lat: 49.61, lon: 6.13 },
  oslo: { lat: 59.91, lon: 10.75 },
  bornholm: { lat: 55.11, lon: 14.92 },
  helsinki: { lat: 60.17, lon: 24.94 },
  "pohja-eesti": { lat: 59.4, lon: 24.8 },
  budapest: { lat: 47.5, lon: 19.05 },
  bratislava: { lat: 48.15, lon: 17.11 },
  cluj: { lat: 46.77, lon: 23.6 },
  dublin: { lat: 53.35, lon: -6.26 },
  venezia: { lat: 45.44, lon: 12.32 },
  milano: { lat: 45.46, lon: 9.19 },
  roma: { lat: 41.9, lon: 12.5 },
  gent: { lat: 51.05, lon: 3.72 },
  bruxelles: { lat: 50.85, lon: 4.35 },
  "extra-regio": { lat: 39.5, lon: -8.2 },
  "nao especificado": { lat: 39.5, lon: -8.2 },
  "nao especificada": { lat: 39.5, lon: -8.2 },
  desconhecido: { lat: 39.5, lon: -8.2 },
  norte: { lat: 41.4, lon: -8.1 },
  centro: { lat: 40.2, lon: -8.2 },
  alentejo: { lat: 38.3, lon: -7.9 },
};

/** Último recurso: centroide do país do código NUTS (as posições são aproximadas). */
const COUNTRY_COORDS: Record<string, GeoPoint> = {
  PT: { lat: 39.5, lon: -8.2 },
  ES: { lat: 40.3, lon: -3.7 },
  FR: { lat: 46.6, lon: 2.4 },
  DE: { lat: 51.2, lon: 10.4 },
  IT: { lat: 42.8, lon: 12.5 },
  EL: { lat: 39.3, lon: 22.5 },
  CH: { lat: 46.8, lon: 8.2 },
  AT: { lat: 47.6, lon: 14.1 },
  BE: { lat: 50.6, lon: 4.6 },
  LU: { lat: 49.8, lon: 6.1 },
  NO: { lat: 64.6, lon: 11.5 },
  DK: { lat: 56.0, lon: 9.5 },
  IE: { lat: 53.2, lon: -8.0 },
  FI: { lat: 64.0, lon: 26.0 },
  EE: { lat: 58.6, lon: 25.5 },
  HU: { lat: 47.2, lon: 19.4 },
  SK: { lat: 48.7, lon: 19.5 },
  RO: { lat: 45.9, lon: 25.0 },
  NL: { lat: 52.2, lon: 5.5 },
  PL: { lat: 52.0, lon: 19.4 },
  CZ: { lat: 49.8, lon: 15.5 },
  SE: { lat: 62.8, lon: 16.7 },
  BG: { lat: 42.7, lon: 25.2 },
  HR: { lat: 45.1, lon: 15.5 },
  SI: { lat: 46.1, lon: 14.8 },
  LT: { lat: 55.2, lon: 23.9 },
  LV: { lat: 56.9, lon: 24.6 },
  CY: { lat: 35.0, lon: 33.2 },
  MT: { lat: 35.9, lon: 14.4 },
  IS: { lat: 64.9, lon: -18.6 },
  TR: { lat: 39.0, lon: 35.2 },
  GB: { lat: 54.5, lon: -2.5 },
  UK: { lat: 54.5, lon: -2.5 },
};

const FOLDED_BY_NAME: Record<string, GeoPoint> = Object.fromEntries(
  Object.entries(PLACE_COORDS_BY_NAME).map(([name, point]) => [fold(name), point])
);
const PREFIXES_BY_LENGTH = Object.keys(NUTS_PREFIX_COORDS).sort((a, b) => b.length - a.length);

function fold(value: string) {
  return value
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9\s-]/gi, " ")
    .replace(/\s+/g, " ")
    .toLowerCase()
    .trim();
}

/** "PT11A - Área Metropolitana do Porto" → "Área Metropolitana do Porto". */
function placeNameOf(value: string) {
  const parts = value.split(" - ");
  return parts.length > 1 ? parts.slice(1).join(" - ") : value;
}

/** Normaliza ids com prefixo de dimensão ("regiao|PT11A" → "PT11A"). */
function codeOf(value: string) {
  const withoutDimension = value.includes("|") ? value.slice(value.indexOf("|") + 1) : value;
  return (withoutDimension.split(" - ")[0] || "").trim().toUpperCase();
}

/**
 * Resolve coordenadas para um nó. `exact: false` significa que a posição é o centroide
 * do NUTS pai ou do país — aproximada, e assinalada como tal no mapa.
 */
export function lookupPlace(key: string, label?: string): ResolvedPlace | null {
  const code = codeOf(key);
  if (PLACE_COORDS_BY_CODE[code]) return { ...PLACE_COORDS_BY_CODE[code], exact: true };

  const candidates = [placeNameOf(label ?? ""), placeNameOf(key), label ?? "", key];
  for (const candidate of candidates) {
    const folded = fold(candidate);
    if (!folded) continue;
    if (FOLDED_BY_NAME[folded]) return { ...FOLDED_BY_NAME[folded], exact: true };
    const hit = Object.keys(FOLDED_BY_NAME).find((name) => name.length > 3 && folded.includes(name));
    if (hit) return { ...FOLDED_BY_NAME[hit], exact: true };
  }

  const prefix = PREFIXES_BY_LENGTH.find((candidate) => code.startsWith(candidate));
  if (prefix) return { ...NUTS_PREFIX_COORDS[prefix], exact: false };

  const country = COUNTRY_COORDS[code.slice(0, 2)];
  if (country) return { ...country, exact: false };

  return null;
}

/**
 * Espalha nós sem coordenadas próprias em torno de um centro (ex.: entidades de uma região),
 * de forma determinística, para que não fiquem todos sobrepostos no mesmo ponto.
 */
export function jitterAround(center: GeoPoint, seed: string, spread = 0.3) {
  let hash = 0;
  for (let i = 0; i < seed.length; i++) hash = (hash * 31 + seed.charCodeAt(i)) >>> 0;
  const angle = ((hash % 360) * Math.PI) / 180;
  const radius = spread * (0.35 + ((hash >> 9) % 100) / 100);
  return {
    lat: center.lat + Math.sin(angle) * radius * 0.7,
    lon: center.lon + Math.cos(angle) * radius,
  };
}
