/**
 * Georreferenciação dos registos **LEI** (GLEIF) para o mapa OpenStreetMap.
 *
 * Os registos LEI não têm coordenadas: o que existe é o **país** e a **região**
 * (ISO 3166-2) do endereço da sede legal. Este módulo resolve esses códigos para
 * um centroide:
 *
 * - **país** — tabela completa de centroides (ISO 3166-1 alfa-2), gerada a partir
 *   da lista pública `average-latitude-longitude-countries`;
 * - **região** — distritos/regiões autónomas de Portugal (`PT-01`…`PT-30`) e
 *   comunidades/províncias de Espanha (`ES-A`…, `ES-MD`…), que é onde está a
 *   maior parte dos registos do módulo.
 *
 * Uma região desconhecida **não** é colocada numa posição inventada: cai no
 * centroide do país com `exact: false`, e o mapa desenha-a com círculo tracejado
 * (tal como o mapa dos contratos faz com as posições aproximadas).
 */
import type { GeoPoint } from "../graph/geo";
import { COUNTRY_CENTROIDS } from "./countries";

export type ResolvedLeiPlace = GeoPoint & { exact: boolean; label: string };

export { COUNTRY_CENTROIDS };

/** Códigos ISO 3166-2:PT dos distritos/regiões autónomas → centroide. */
export const PT_REGION_CENTROIDS: Record<string, [number, number]> = {
  "PT-01": [40.64, -8.65], // Aveiro
  "PT-02": [38.02, -7.86], // Beja
  "PT-03": [41.55, -8.42], // Braga
  "PT-04": [41.81, -6.76], // Bragança
  "PT-05": [39.82, -7.49], // Castelo Branco
  "PT-06": [40.21, -8.43], // Coimbra
  "PT-07": [38.57, -7.91], // Évora
  "PT-08": [37.02, -7.93], // Faro
  "PT-09": [40.54, -7.27], // Guarda
  "PT-10": [39.74, -8.81], // Leiria
  "PT-11": [38.72, -9.14], // Lisboa
  "PT-12": [39.29, -7.43], // Portalegre
  "PT-13": [41.15, -8.61], // Porto
  "PT-14": [39.24, -8.69], // Santarém
  "PT-15": [38.52, -8.89], // Setúbal
  "PT-16": [41.69, -8.83], // Viana do Castelo
  "PT-17": [41.3, -7.74], // Vila Real
  "PT-18": [40.66, -7.91], // Viseu
  "PT-20": [37.74, -25.68], // Açores (Ponta Delgada)
  "PT-30": [32.65, -16.91], // Madeira (Funchal)
};

/** Códigos ISO 3166-2:ES (comunidades e províncias) → centroide. */
export const ES_REGION_CENTROIDS: Record<string, [number, number]> = {
  // Comunidades autónomas e cidades autónomas
  "ES-AN": [37.39, -5.98], // Andaluzia (Sevilha)
  "ES-AR": [41.65, -0.89], // Aragão (Saragoça)
  "ES-AS": [43.36, -5.85], // Astúrias (Oviedo)
  "ES-CB": [43.46, -3.81], // Cantábria (Santander)
  "ES-CE": [35.89, -5.32], // Ceuta
  "ES-CL": [41.65, -4.72], // Castela e Leão (Valladolid)
  "ES-CM": [39.86, -4.03], // Castela-Mancha (Toledo)
  "ES-CN": [28.12, -15.43], // Canárias (Las Palmas)
  "ES-CT": [41.39, 2.17], // Catalunha (Barcelona)
  "ES-EX": [38.92, -6.34], // Estremadura (Mérida)
  "ES-GA": [42.88, -8.54], // Galiza (Santiago de Compostela)
  "ES-IB": [39.57, 2.65], // Ilhas Baleares (Palma)
  "ES-MC": [37.99, -1.13], // Região de Múrcia
  "ES-MD": [40.42, -3.7], // Comunidade de Madrid
  "ES-ML": [35.29, -2.95], // Melilla
  "ES-NC": [42.82, -1.64], // Navarra (Pamplona)
  "ES-PV": [42.85, -2.67], // País Basco (Vitória)
  "ES-RI": [42.46, -2.45], // La Rioja (Logronho)
  "ES-VC": [39.47, -0.38], // Comunidade Valenciana
  // Províncias
  "ES-A": [38.35, -0.48], // Alicante
  "ES-AB": [38.99, -1.86], // Albacete
  "ES-AL": [36.84, -2.46], // Almeria
  "ES-AV": [40.66, -4.7], // Ávila
  "ES-B": [41.39, 2.17], // Barcelona
  "ES-BA": [38.88, -6.97], // Badajoz
  "ES-BI": [43.26, -2.93], // Biscaia (Bilbau)
  "ES-BU": [42.34, -3.7], // Burgos
  "ES-C": [43.36, -8.41], // A Coruña
  "ES-CA": [36.53, -6.29], // Cádis
  "ES-CC": [39.47, -6.37], // Cáceres
  "ES-CO": [37.89, -4.78], // Córdova
  "ES-CR": [38.99, -3.93], // Ciudad Real
  "ES-CS": [39.99, -0.04], // Castelló
  "ES-CU": [40.07, -2.13], // Cuenca
  "ES-GC": [28.12, -15.43], // Las Palmas
  "ES-GI": [41.98, 2.82], // Girona
  "ES-GR": [37.18, -3.6], // Granada
  "ES-GU": [40.63, -3.16], // Guadalajara
  "ES-H": [37.26, -6.94], // Huelva
  "ES-HU": [42.14, -0.41], // Huesca
  "ES-J": [37.77, -3.79], // Jaén
  "ES-L": [41.62, 0.62], // Lleida
  "ES-LE": [42.6, -5.57], // Leão
  "ES-LO": [42.46, -2.45], // La Rioja (Logronho)
  "ES-LU": [43.01, -7.56], // Lugo
  "ES-M": [40.42, -3.7], // Madrid
  "ES-MA": [36.72, -4.42], // Málaga
  "ES-MU": [37.99, -1.13], // Múrcia
  "ES-NA": [42.82, -1.64], // Navarra (Pamplona)
  "ES-O": [43.36, -5.85], // Astúrias (Oviedo)
  "ES-OR": [42.34, -7.86], // Ourense
  "ES-P": [42.01, -4.53], // Palência
  "ES-PM": [39.57, 2.65], // Ilhas Baleares (Palma)
  "ES-PO": [42.43, -8.64], // Pontevedra
  "ES-S": [43.46, -3.81], // Cantábria (Santander)
  "ES-SA": [40.97, -5.66], // Salamanca
  "ES-SE": [37.39, -5.98], // Sevilha
  "ES-SG": [40.95, -4.12], // Segóvia
  "ES-SO": [41.76, -2.47], // Sória
  "ES-SS": [43.31, -1.98], // Guipúscoa (San Sebastián)
  "ES-T": [41.12, 1.25], // Tarragona
  "ES-TE": [40.34, -1.11], // Teruel
  "ES-TF": [28.46, -16.25], // Santa Cruz de Tenerife
  "ES-TO": [39.86, -4.03], // Toledo
  "ES-V": [39.47, -0.38], // Valência
  "ES-VA": [41.65, -4.72], // Valladolid
  "ES-VI": [42.85, -2.67], // Álava (Vitória)
  "ES-Z": [41.65, -0.89], // Saragoça
  "ES-ZA": [41.5, -5.75], // Zamora
};

/** Regiões insulares: não cabem no enquadramento da Península Ibérica. */
export const ISLAND_REGIONS = new Set([
  "PT-20",
  "PT-30",
  "ES-CN",
  "ES-GC",
  "ES-TF",
  "ES-PM",
  "ES-CE",
  "ES-ML",
]);

/**
 * Regiões fora de Portugal/Espanha que aparecem em registos com sede legal
 * ibérica (jurisdição PT/ES com endereço no estrangeiro) — poucos registos, mas
 * ficam na posição certa em vez de caírem no centroide do país.
 */
export const EXTRA_REGION_CENTROIDS: Record<string, [number, number]> = {
  "DE-BE": [52.52, 13.4], // Berlim
  "DE-HE": [50.08, 8.24], // Hesse (Wiesbaden)
  "DE-NI": [52.37, 9.73], // Baixa Saxónia (Hanover)
  "DE-RP": [49.99, 8.27], // Renânia-Palatinado (Mainz)
  "FR-IDF": [48.85, 2.35], // Île-de-France
  "FR-75C": [48.86, 2.35], // Paris
  "FR-92": [48.89, 2.21], // Hauts-de-Seine (Nanterre)
  "CH-ZH": [47.37, 8.54], // Zurique
  "CY-01": [35.19, 33.38], // Nicósia
  "IT-MI": [45.46, 9.19], // Milão
  "LU-LU": [49.61, 6.13], // Luxemburgo
  "PL-18": [51.76, 19.46], // Łódź
  "SE-N": [62.39, 17.31], // Norrland (Sundsvall)
  "US-FL": [30.44, -84.28], // Florida (Tallahassee)
  "US-GA": [33.75, -84.39], // Geórgia (Atlanta)
  "US-IL": [39.8, -89.64], // Illinois (Springfield)
  "US-MI": [42.73, -84.56], // Michigan (Lansing)
  "US-NY": [42.65, -73.76], // Nova Iorque (Albany)
};

const displayNames = typeof Intl !== "undefined" && "DisplayNames" in Intl
  ? new Intl.DisplayNames(["pt"], { type: "region" })
  : null;

/** Nome do país em português (`PT` → «Portugal»); devolve o código se não houver nome. */
export function countryName(code?: string | null): string {
  if (!code) return "—";
  const key = code.toUpperCase();
  try {
    return displayNames?.of(key) || key;
  } catch {
    return key;
  }
}

/** Bandeira emoji a partir do código ISO (útil nos cartões e na lista do mapa). */
export function countryFlag(code?: string | null): string {
  if (!code || !/^[A-Za-z]{2}$/.test(code)) return "🏳️";
  return String.fromCodePoint(...[...code.toUpperCase()].map((ch) => 127397 + ch.charCodeAt(0)));
}

/**
 * Resolve a posição de um agregado do mapa.
 *
 * - `level = "country"` → centroide do país (`key` é o ISO);
 * - `level = "region"` → centroide da região conhecida; se não existir, cai no
 *   centroide do país (`fallbackCountry`) com `exact: false`.
 */
export function resolveLeiPlace(
  key: string,
  level: "country" | "region",
  fallbackCountry?: string | null,
): ResolvedLeiPlace | null {
  const code = (key || "").toUpperCase();
  if (level === "country") {
    const point = COUNTRY_CENTROIDS[code];
    if (!point) return null;
    return { lat: point[0], lon: point[1], exact: true, label: countryName(code) };
  }
  const known = PT_REGION_CENTROIDS[code] || ES_REGION_CENTROIDS[code] || EXTRA_REGION_CENTROIDS[code];
  if (known) return { lat: known[0], lon: known[1], exact: true, label: code };
  const country = (fallbackCountry || code.split("-")[0] || "").toUpperCase();
  const point = COUNTRY_CENTROIDS[country];
  if (!point) return null;
  return { lat: point[0], lon: point[1], exact: false, label: code };
}

/** Enquadramentos do mapa (o das ilhas é usado quando o filtro é insular). */
export const IBERIA_VIEW = { lat: 39.6, lon: -4.2, zoom: 5.2 };
export const ATLANTIC_ISLANDS_VIEW = { lat: 33.5, lon: -18.5, zoom: 4 };
export const WORLD_VIEW = { lat: 24, lon: 0, zoom: 1.6 };
