/**
 * Cliente do mapa ibérico de contratos públicos.
 *
 * `GET /contracts/analytics/iberia-map` agrega, numa só chamada, os contratos
 * portugueses (por distrito de execução) e os espanhóis (por província/NUTS).
 * A API devolve as chaves administrativas; a posição no mapa é resolvida em
 * `components/geo/iberia.ts`, porque os contratos não têm coordenadas.
 */
import { API_BASE } from "./api";

export type IberiaMapCountry = "PT" | "ES";

/** Volume e valor de contratos numa região (distrito PT ou código NUTS ES). */
export type IberiaMapRegion = {
  pais: IberiaMapCountry;
  /** Distrito (ex.: «Lisboa») ou código NUTS espanhol (ex.: «ES300»). */
  code: string;
  label: string;
  /** `distrito` | `nuts3` | `nuts2` | `nuts1` | `pais`. */
  level: string;
  count: number;
  total_value: number;
};

export type IberiaMapCountryTotal = {
  code: IberiaMapCountry;
  label: string;
  total_contracts: number;
  total_value: number;
};

export type IberiaMapTotals = { count: number; total_value: number };

/** Filtros de pesquisa aplicados ao agregado (refletidos em `filters`). */
export type IberiaMapFilters = {
  q?: string | null;
  entidade?: string | null;
  cpv?: string | null;
};

export type IberiaMapResponse = {
  ano?: number | null;
  pais: string;
  filters?: IberiaMapFilters;
  countries: IberiaMapCountryTotal[];
  regions: IberiaMapRegion[];
  /** Contratos sem geografia utilizável, por país. */
  unspecified: Partial<Record<IberiaMapCountry, IberiaMapTotals>>;
  /** Contratos de Espanha executados fora de Espanha. */
  other_locations: IberiaMapTotals;
  warnings?: string[];
  error?: string;
};

/**
 * Agregado geográfico dos contratos dos dois países.
 *
 * `q`/`entidade` fazem pesquisa de texto (todos os termos exigidos) e `cpv` filtra
 * por código CPV — o mapa responde a «onde foram executados estes contratos?».
 */
export async function getContractsIberiaMap(
  params: { ano?: number | null; pais?: IberiaMapCountry | "all"; q?: string; entidade?: string; cpv?: string } = {},
): Promise<IberiaMapResponse> {
  const search = new URLSearchParams();
  if (params.ano) search.set("ano", String(params.ano));
  if (params.pais) search.set("pais", params.pais);
  if (params.q) search.set("q", params.q);
  if (params.entidade) search.set("entidade", params.entidade);
  if (params.cpv) search.set("cpv", params.cpv);
  const query = search.toString();
  const res = await fetch(`${API_BASE}/contracts/analytics/iberia-map${query ? `?${query}` : ""}`);
  if (!res.ok) {
    throw new Error(`Não foi possível carregar o mapa (HTTP ${res.status})`);
  }
  return (await res.json()) as IberiaMapResponse;
}

/* ------------------------------------------------------- ficha de região */

/** Linha analítica da ficha de região (ano, CPV, procedimento, escalão…). */
export type RegionDetailRow = {
  key: string;
  count: number;
  total_value: number;
  description?: string | null;
};

/** Entidade que adjudica (PT: adjudicante) ou empresa adjudicatária. */
export type RegionDetailEntity = {
  nif?: string | null;
  name: string;
  count: number;
  total_value: number;
  avg_value?: number | null;
  share?: number | null;
  first_year?: number | null;
  last_year?: number | null;
};

/** Contrato listado na ficha da região. */
export type RegionDetailContract = {
  doc_id?: string | null;
  title: string;
  awarder?: string;
  supplier?: string;
  value?: number | null;
  ano?: number | null;
  date?: string | null;
};

export type RegionDetailResponse = {
  pais: IberiaMapCountry;
  code: string;
  ano?: number | null;
  /** Pesquisa aplicada ao conjunto (texto e/ou CPV). */
  filters?: { q?: string | null; cpv?: string | null };
  totals: {
    contracts: number;
    value: number;
    avg?: number | null;
    max?: number | null;
    /** Entidades que adjudicam (PT: adjudicantes; ES: órgãos). */
    awarders?: number | null;
    /** Empresas adjudicatárias distintas. */
    suppliers?: number | null;
  };
  by_year: RegionDetailRow[];
  by_cpv: RegionDetailRow[];
  by_procedure: RegionDetailRow[];
  by_contract_type: RegionDetailRow[];
  by_value_range: RegionDetailRow[];
  awarders: RegionDetailEntity[];
  suppliers: RegionDetailEntity[];
  contracts: RegionDetailContract[];
  error?: string | null;
};

/**
 * Contratos, entidades e métricas de uma região (distrito PT ou província/NUTS ES).
 * `q` (texto) e `cpv` filtram métricas, entidades e contratos ao mesmo tempo —
 * é a pesquisa da janela aberta no menu de contexto do mapa.
 */
export async function getContractRegionDetail(params: {
  pais: IberiaMapCountry;
  code: string;
  ano?: number | null;
  q?: string;
  cpv?: string;
}): Promise<RegionDetailResponse> {
  const search = new URLSearchParams({ pais: params.pais, code: params.code });
  if (params.ano) search.set("ano", String(params.ano));
  if (params.q) search.set("q", params.q);
  if (params.cpv) search.set("cpv", params.cpv);
  const res = await fetch(`${API_BASE}/contracts/region-detail?${search.toString()}`);
  if (!res.ok) {
    throw new Error(`Não foi possível carregar a região (HTTP ${res.status})`);
  }
  return (await res.json()) as RegionDetailResponse;
}
