/**
 * Geografia do mapa ibérico de contratos públicos.
 *
 * Os contratos **não trazem coordenadas**: trazem a divisão administrativa onde
 * foram executados. Este módulo converte essa chave numa posição no mapa, dizendo
 * sempre se a posição é exata (capital do próprio distrito/província) ou
 * aproximada (centroide de uma região NUTS 2/1, quando o dado só identifica o
 * agrupamento) — o mapa marca as aproximadas com círculo tracejado.
 *
 * Chaves usadas:
 * - Portugal (`pais: "PT"`): nome do distrito, tal como vem no segundo segmento
 *   de `localExecucao` («Portugal, Lisboa, Cascais» → «Lisboa»). 20 distritos,
 *   incluindo as duas regiões autónomas.
 * - Espanha (`pais: "ES"`): código NUTS do campo `nuts` (`ES300` província,
 *   `ES30` NUTS 2, `ES3` NUTS 1). Os códigos sem província (`ES`, `ESZ`, …) não
 *   são posicionáveis e ficam assinalados como "sem localização".
 */

export type GeoPoint = { lat: number; lon: number };

export type IberiaLevel = "distrito" | "nuts3" | "nuts2" | "nuts1";

export type IberiaRegion = GeoPoint & {
  /** Chave devolvida pela API (`code`). */
  code: string;
  /** Nome legível (distrito em PT; província/comunidade em ES). */
  name: string;
  pais: "PT" | "ES";
  level: IberiaLevel;
  /** `true` quando a posição é o centroide de uma região maior que a do dado. */
  approx: boolean;
};

/** Distritos e regiões autónomas de Portugal → capital (sede de distrito). */
const PT_DISTRICTS: Record<string, GeoPoint> = {
  Aveiro: { lat: 40.64, lon: -8.65 },
  Beja: { lat: 38.02, lon: -7.86 },
  Braga: { lat: 41.55, lon: -8.42 },
  Bragança: { lat: 41.81, lon: -6.76 },
  "Castelo Branco": { lat: 39.82, lon: -7.49 },
  Coimbra: { lat: 40.21, lon: -8.43 },
  Évora: { lat: 38.57, lon: -7.91 },
  Faro: { lat: 37.02, lon: -7.93 },
  Guarda: { lat: 40.54, lon: -7.27 },
  Leiria: { lat: 39.74, lon: -8.81 },
  Lisboa: { lat: 38.72, lon: -9.14 },
  Portalegre: { lat: 39.29, lon: -7.43 },
  Porto: { lat: 41.15, lon: -8.61 },
  Santarém: { lat: 39.24, lon: -8.69 },
  Setúbal: { lat: 38.52, lon: -8.89 },
  "Viana do Castelo": { lat: 41.69, lon: -8.83 },
  "Vila Real": { lat: 41.3, lon: -7.74 },
  Viseu: { lat: 40.66, lon: -7.91 },
  // Regiões autónomas: centroide do arquipélago (as ilhas não cabem no
  // enquadramento da Península, por isso o mapa pode zoomar para elas).
  "Região Autónoma da Madeira": { lat: 32.65, lon: -16.95 },
  "Região Autónoma dos Açores": { lat: 38.53, lon: -28.05 },
};

/** Províncias (NUTS 3) de Espanha → nome + capital de província. */
const ES_PROVINCES: Record<string, { name: string } & GeoPoint> = {
  // Galicia
  ES111: { name: "A Coruña", lat: 43.36, lon: -8.41 },
  ES112: { name: "Lugo", lat: 43.01, lon: -7.56 },
  ES113: { name: "Ourense", lat: 42.34, lon: -7.86 },
  ES114: { name: "Pontevedra", lat: 42.43, lon: -8.65 },
  // Cornisa cantábrica
  ES120: { name: "Asturias", lat: 43.36, lon: -5.84 },
  ES130: { name: "Cantabria", lat: 43.46, lon: -3.81 },
  ES211: { name: "Álava / Araba", lat: 42.85, lon: -2.67 },
  ES212: { name: "Gipuzkoa", lat: 43.32, lon: -1.98 },
  ES213: { name: "Bizkaia", lat: 43.26, lon: -2.94 },
  ES220: { name: "Navarra", lat: 42.82, lon: -1.65 },
  ES230: { name: "La Rioja", lat: 42.46, lon: -2.45 },
  // Aragón y Madrid
  ES241: { name: "Huesca", lat: 42.14, lon: -0.41 },
  ES242: { name: "Teruel", lat: 40.34, lon: -1.11 },
  ES243: { name: "Zaragoza", lat: 41.65, lon: -0.88 },
  ES300: { name: "Madrid", lat: 40.42, lon: -3.7 },
  // Castilla y León
  ES411: { name: "Ávila", lat: 40.66, lon: -4.7 },
  ES412: { name: "Burgos", lat: 42.34, lon: -3.7 },
  ES413: { name: "León", lat: 42.6, lon: -5.57 },
  ES414: { name: "Palencia", lat: 42.01, lon: -4.53 },
  ES415: { name: "Salamanca", lat: 40.96, lon: -5.66 },
  ES416: { name: "Segovia", lat: 40.95, lon: -4.12 },
  ES417: { name: "Soria", lat: 41.77, lon: -2.47 },
  ES418: { name: "Valladolid", lat: 41.65, lon: -4.72 },
  ES419: { name: "Zamora", lat: 41.5, lon: -5.75 },
  // Castilla-La Mancha y Extremadura
  ES421: { name: "Albacete", lat: 38.99, lon: -1.86 },
  ES422: { name: "Ciudad Real", lat: 38.99, lon: -3.93 },
  ES423: { name: "Cuenca", lat: 40.07, lon: -2.13 },
  ES424: { name: "Guadalajara", lat: 40.63, lon: -3.17 },
  ES425: { name: "Toledo", lat: 39.86, lon: -4.03 },
  ES431: { name: "Badajoz", lat: 38.88, lon: -6.97 },
  ES432: { name: "Cáceres", lat: 39.47, lon: -6.37 },
  // Cataluña, Comunitat Valenciana, Illes Balears
  ES511: { name: "Barcelona", lat: 41.39, lon: 2.17 },
  ES512: { name: "Girona", lat: 41.98, lon: 2.82 },
  ES513: { name: "Lleida", lat: 41.62, lon: 0.62 },
  ES514: { name: "Tarragona", lat: 41.12, lon: 1.25 },
  ES521: { name: "Alicante / Alacant", lat: 38.35, lon: -0.48 },
  ES522: { name: "Castellón", lat: 39.99, lon: -0.04 },
  ES523: { name: "Valencia", lat: 39.47, lon: -0.38 },
  ES531: { name: "Eivissa i Formentera", lat: 38.91, lon: 1.43 },
  ES532: { name: "Mallorca", lat: 39.57, lon: 2.65 },
  ES533: { name: "Menorca", lat: 39.89, lon: 4.27 },
  // Andalucía, Murcia, Ceuta y Melilla
  ES611: { name: "Almería", lat: 36.84, lon: -2.46 },
  ES612: { name: "Cádiz", lat: 36.53, lon: -6.29 },
  ES613: { name: "Córdoba", lat: 37.89, lon: -4.78 },
  ES614: { name: "Granada", lat: 37.18, lon: -3.6 },
  ES615: { name: "Huelva", lat: 37.26, lon: -6.95 },
  ES616: { name: "Jaén", lat: 37.77, lon: -3.79 },
  ES617: { name: "Málaga", lat: 36.72, lon: -4.42 },
  ES618: { name: "Sevilla", lat: 37.39, lon: -5.99 },
  ES620: { name: "Murcia", lat: 37.99, lon: -1.13 },
  ES630: { name: "Ceuta", lat: 35.89, lon: -5.32 },
  ES640: { name: "Melilla", lat: 35.29, lon: -2.95 },
  // Canarias
  ES703: { name: "El Hierro", lat: 27.81, lon: -17.92 },
  ES704: { name: "Fuerteventura", lat: 28.5, lon: -13.86 },
  ES705: { name: "Gran Canaria", lat: 28.12, lon: -15.43 },
  ES706: { name: "La Gomera", lat: 28.09, lon: -17.11 },
  ES707: { name: "La Palma", lat: 28.68, lon: -17.76 },
  ES708: { name: "Lanzarote", lat: 28.96, lon: -13.55 },
  ES709: { name: "Tenerife", lat: 28.46, lon: -16.25 },
};

/** Comunidades autónomas (NUTS 2): usadas quando o dado só identifica o grupo. */
const ES_NUTS2: Record<string, { name: string } & GeoPoint> = {
  ES11: { name: "Galicia", lat: 42.8, lon: -8.0 },
  ES12: { name: "Principado de Asturias", lat: 43.36, lon: -5.84 },
  ES13: { name: "Cantabria", lat: 43.46, lon: -3.81 },
  ES21: { name: "País Vasco", lat: 43.0, lon: -2.5 },
  ES22: { name: "Navarra", lat: 42.82, lon: -1.65 },
  ES23: { name: "La Rioja", lat: 42.46, lon: -2.45 },
  ES24: { name: "Aragón", lat: 41.6, lon: -0.9 },
  ES30: { name: "Comunidad de Madrid", lat: 40.42, lon: -3.7 },
  ES41: { name: "Castilla y León", lat: 41.7, lon: -4.7 },
  ES42: { name: "Castilla-La Mancha", lat: 39.9, lon: -3.5 },
  ES43: { name: "Extremadura", lat: 39.2, lon: -6.4 },
  ES51: { name: "Cataluña", lat: 41.8, lon: 1.6 },
  ES52: { name: "Comunitat Valenciana", lat: 39.3, lon: -0.5 },
  ES53: { name: "Illes Balears", lat: 39.6, lon: 2.9 },
  ES61: { name: "Andalucía", lat: 37.4, lon: -4.7 },
  ES62: { name: "Región de Murcia", lat: 37.99, lon: -1.13 },
  ES63: { name: "Ciudad de Ceuta", lat: 35.89, lon: -5.32 },
  ES64: { name: "Ciudad de Melilla", lat: 35.29, lon: -2.95 },
  ES70: { name: "Canarias", lat: 28.3, lon: -15.6 },
};

/** Agrupamentos NUTS 1 (o último recurso antes de "sem localização"). */
const ES_NUTS1: Record<string, { name: string } & GeoPoint> = {
  ES1: { name: "Noroeste", lat: 43.0, lon: -6.4 },
  ES2: { name: "Noreste", lat: 42.2, lon: -1.6 },
  ES3: { name: "Comunidad de Madrid", lat: 40.42, lon: -3.7 },
  ES4: { name: "Centro", lat: 40.2, lon: -4.5 },
  ES5: { name: "Este", lat: 40.2, lon: -0.4 },
  ES6: { name: "Sur", lat: 37.4, lon: -4.5 },
  ES7: { name: "Canarias", lat: 28.3, lon: -15.6 },
};

/** Enquadramento inicial: Península Ibérica + Baleares (a 6 preenche o painel do mapa). */
export const IBERIA_VIEW = {
  center: { lat: 40.1, lon: -3.6 } as GeoPoint,
  zoom: 6,
  /** Zoom usado ao focar uma região. */
  regionZoom: 8,
};

/** Enquadramento usado quando se quer ver também as ilhas (Açores, Madeira, Canárias). */
export const IBERIA_ISLANDS_VIEW = {
  center: { lat: 35.5, lon: -13.5 } as GeoPoint,
  zoom: 4,
};

/**
 * Regiões insulares e cidades autónomas, fora do enquadramento da Península:
 * Canarias, Ceuta e Melilla ficam a sul de 36°N; os Açores a oeste de 11°W
 * (a Madeira falha as duas condições). O mapa lista-as à parte, em vez de as
 * espremer no canto do enquadramento.
 */
export function isOffshoreRegion(region: { lat: number; lon: number }): boolean {
  return region.lat < 36 || region.lon < -11;
}

/** Resolve a chave geográfica de um contrato numa posição no mapa. */
export function resolveIberiaRegion(pais: "PT" | "ES", code: string): IberiaRegion | null {
  const key = (code || "").trim();
  if (!key) return null;

  if (pais === "PT") {
    const point = PT_DISTRICTS[key];
    if (!point) return null;
    return { code: key, name: key, pais: "PT", level: "distrito", approx: false, ...point };
  }

  const province = ES_PROVINCES[key];
  if (province) {
    return { code: key, name: province.name, pais: "ES", level: "nuts3", approx: false, lat: province.lat, lon: province.lon };
  }
  const nuts2 = ES_NUTS2[key];
  if (nuts2) {
    return { code: key, name: nuts2.name, pais: "ES", level: "nuts2", approx: true, lat: nuts2.lat, lon: nuts2.lon };
  }
  const nuts1 = ES_NUTS1[key];
  if (nuts1) {
    return { code: key, name: nuts1.name, pais: "ES", level: "nuts1", approx: true, lat: nuts1.lat, lon: nuts1.lon };
  }
  return null;
}

/** Etiqueta do nível geográfico, para legenda e fichas. */
export const LEVEL_LABELS: Record<IberiaLevel, string> = {
  distrito: "Distrito",
  nuts3: "Província",
  nuts2: "Comunidade autónoma",
  nuts1: "Agrupamento NUTS 1",
};

/**
 * Todas as regiões conhecidas (distritos, províncias, comunidades e
 * agrupamentos). Serve as sugestões «ir para» da pesquisa do mapa, por isso é
 * independente do que o agregado devolveu (que depende dos filtros).
 */
export function allIberiaRegions(): IberiaRegion[] {
  const regions: IberiaRegion[] = [];
  for (const [name, point] of Object.entries(PT_DISTRICTS)) {
    regions.push({ code: name, name, pais: "PT", level: "distrito", approx: false, ...point });
  }
  for (const [code, province] of Object.entries(ES_PROVINCES)) {
    regions.push({ code, name: province.name, pais: "ES", level: "nuts3", approx: false, lat: province.lat, lon: province.lon });
  }
  for (const [code, group] of Object.entries(ES_NUTS2)) {
    regions.push({ code, name: group.name, pais: "ES", level: "nuts2", approx: true, lat: group.lat, lon: group.lon });
  }
  for (const [code, group] of Object.entries(ES_NUTS1)) {
    regions.push({ code, name: group.name, pais: "ES", level: "nuts1", approx: true, lat: group.lat, lon: group.lon });
  }
  return regions;
}

/** Compara texto sem acentos e sem maiúsculas (sugestões de região). */
export function foldIberiaText(value: string): string {
  return (value || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .trim();
}
