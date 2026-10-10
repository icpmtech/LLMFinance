/**
 * Cliente do módulo **Benchmark de preços e concorrência** (`/benchmark/*`).
 *
 * O backend responde com preço de referência do segmento (CPV + anos), a lista
 * de concorrentes, o historial de contrapartes da empresa e as oportunidades
 * (contrapartes com que a empresa nunca contratou). Tudo em euros.
 */
import { API_BASE } from "./api";

export type BenchmarkRole = "adjudicatario" | "adjudicante";

/** País dos dados: `all` é o quadro conjunto (por CPV). */
export type BenchmarkCountry = "pt" | "es" | "fr";
export type BenchmarkScope = BenchmarkCountry | "all";

export interface BenchmarkCountryInfo {
  country: BenchmarkCountry;
  label: string;
  short: string;
  index: string;
  total: number;
  years: number[];
  roles: string[];
  role_labels?: Record<string, string>;
}

export interface BenchmarkMetaAll {
  country: BenchmarkScope;
  label: string;
  total: number;
  years: number[];
  roles: string[];
  countries: BenchmarkCountryInfo[];
  error?: string;
}

export interface BenchmarkMeta {
  total: number;
  years: number[];
  roles?: string[];
  error?: string;
}

export interface BenchmarkCpv {
  code: string;
  description: string;
  count: number;
  value?: number | null;
}

export interface BenchmarkCpvResponse {
  query?: string | null;
  items: BenchmarkCpv[];
  error?: string;
}

export interface BenchmarkRow {
  nif: string;
  name: string;
  count: number;
  value?: number | null;
  last_date?: string | null;
  rank?: number;
  share_pct?: number | null;
  why?: string;
}

export interface BenchmarkByYear {
  year: string;
  count: number;
  value: number;
}

export interface BenchmarkRecentContract {
  idcontrato?: string | null;
  objecto?: string | null;
  value?: number | null;
  date?: string | null;
  counterpart?: string | null;
}

export interface BenchmarkEntityStats {
  nif?: string | null;
  name: string;
  contracts: number;
  total_value: number;
  avg_value?: number | null;
  median_value?: number | null;
  last_date?: string | null;
  rank?: number | null;
  share_pct?: number | null;
  count_share_pct?: number | null;
  price_index?: number | null;
  /** `false` quando a entidade não tem contratos nesse papel no segmento. */
  present?: boolean;
  by_year: BenchmarkByYear[];
  top_cpv: BenchmarkCpv[];
  recent: BenchmarkRecentContract[];
}

export interface BenchmarkReference {
  scope: string;
  contracts: number;
  total_value: number;
  avg?: number | null;
  median?: number | null;
  p10?: number | null;
  p25?: number | null;
  p75?: number | null;
  p90?: number | null;
  min?: number | null;
  max?: number | null;
}

export interface BenchmarkResponse {
  role: BenchmarkRole;
  entity: BenchmarkEntityStats;
  reference: BenchmarkReference;
  market: { contracts: number; peers: number; counterparts: number };
  competitors: BenchmarkRow[];
  counterparties: BenchmarkRow[];
  history: BenchmarkRow[];
  opportunities: BenchmarkRow[];
  notes: string[];
  error?: string;
}

export interface BenchmarkQuery {
  nif?: string;
  name?: string;
  role?: BenchmarkRole;
  country?: BenchmarkCountry;
  cpv_code?: string;
  year_from?: number;
  year_to?: number;
  region?: string;
  top?: number;
}

/** Volumetria do índice de contratos e anos disponíveis. */
export async function getBenchmarkMeta(country: BenchmarkScope = "pt"): Promise<BenchmarkMetaAll> {
  const res = await fetch(`${API_BASE}/benchmark/meta?country=${country}`);
  if (!res.ok) throw new Error(`Erro ao obter o estado do benchmark: ${res.status}`);
  return res.json();
}

/** CPV mais usados no país (para escolher o segmento). */
export async function getBenchmarkCpv(
  q?: string,
  size = 20,
  country: BenchmarkCountry = "pt",
): Promise<BenchmarkCpvResponse> {
  const params = new URLSearchParams({ size: String(size), country });
  if (q) params.set("q", q);
  const res = await fetch(`${API_BASE}/benchmark/cpv?${params}`);
  if (!res.ok) throw new Error(`Erro ao obter CPV: ${res.status}`);
  return res.json();
}

/** Benchmark de preços, concorrência, historial e oportunidades. */
export async function getBenchmarkEntity(params: BenchmarkQuery): Promise<BenchmarkResponse> {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    search.set(key, String(value));
  }
  const res = await fetch(`${API_BASE}/benchmark/entity?${search}`);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `Erro no benchmark: ${res.status}`);
  }
  return res.json();
}

/* ------------------------------------------------------------ comparação */

/** Máximo de empresas comparáveis de uma vez (igual ao limite do servidor). */
export const MAX_COMPARE = 10;

export interface BenchmarkCompareEntity {
  nif?: string;
  name?: string;
}

export interface BenchmarkCompareRequest {
  entities: BenchmarkCompareEntity[];
  role?: BenchmarkRole;
  country?: BenchmarkCountry;
  cpv_code?: string;
  year_from?: number;
  year_to?: number;
  region?: string;
  top?: number;
}

export interface BenchmarkCompareRow {
  nif?: string | null;
  name: string;
  contracts: number;
  total_value: number;
  avg_value?: number | null;
  median_value?: number | null;
  p25?: number | null;
  p75?: number | null;
  share_pct?: number | null;
  count_share_pct?: number | null;
  rank?: number | null;
  price_index?: number | null;
  /** `abaixo` | `na linha` | `acima` do preço de referência do mercado. */
  price_position?: string | null;
  last_date?: string | null;
  present?: boolean;
  /** Posição na tabela (1 = maior valor no segmento). */
  order?: number;
  /** CPV em que a empresa atua dentro do segmento (maiores primeiro). */
  top_cpv: BenchmarkCpv[];
  /** Contrapartes da empresa no segmento (quem lhe compra, se vende). */
  buyers: BenchmarkRow[];
  /** Contrapartes distintas da empresa no segmento. */
  buyers_total?: number;
}

/** Contraparte que compra a duas ou mais das empresas comparadas. */
export interface BenchmarkSharedBuyer {
  nif: string;
  name: string;
  companies: string[];
  companies_total: number;
  value: number;
}

/** CPV em que atuam duas ou mais das empresas comparadas. */
export interface BenchmarkSharedCpv {
  code: string;
  description: string;
  companies: string[];
  companies_total: number;
  value: number;
  count: number;
}

export interface BenchmarkCompareResponse {
  role: BenchmarkRole;
  country?: BenchmarkCountry;
  country_label?: string;
  reference: {
    scope: string;
    contracts: number;
    total_value: number;
    avg?: number | null;
    median?: number | null;
    p25?: number | null;
    p75?: number | null;
  };
  market: { contracts: number; peers: number };
  /** Papel das contrapartes: `adjudicante` (quem compra) ou `adjudicatario`. */
  counterpart_role?: BenchmarkRole;
  entities: BenchmarkCompareRow[];
  ranking: (BenchmarkRow & { selected?: boolean; label?: string | null })[];
  /** Contrapartes comuns a duas ou mais empresas comparadas. */
  shared_buyers: BenchmarkSharedBuyer[];
  /** CPV em que atuam duas ou mais empresas comparadas. */
  shared_cpvs: BenchmarkSharedCpv[];
  notes: string[];
  error?: string;
}

/** Compara até 10 empresas no mesmo segmento (papel + CPV + anos). */
export async function compareBenchmarkEntities(
  payload: BenchmarkCompareRequest,
): Promise<BenchmarkCompareResponse> {
  const res = await fetch(`${API_BASE}/benchmark/compare`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `Erro na comparação: ${res.status}`);
  }
  return res.json();
}

/* ------------------------------------------- quadro conjunto, por CPV */

/** Parcela de um CPV num país (contratos, valor e mediana). */
export interface BenchmarkByCpvCell {
  contracts: number;
  value?: number | null;
  median?: number | null;
}

export interface BenchmarkByCpvRow {
  rank: number;
  code: string;
  description: string;
  example: string;
  contracts: number;
  value: number;
  by_country: Record<string, BenchmarkByCpvCell>;
}

export interface BenchmarkByCpvResponse {
  countries: {
    country: BenchmarkCountry;
    label: string;
    short: string;
    index: string;
    contracts: number;
    priced_contracts: number;
    total_value: number;
    median?: number | null;
  }[];
  cpv_filter?: string | null;
  items: BenchmarkByCpvRow[];
  notes: string[];
  error?: string;
}

/** Quadro por CPV com o volume e o preço de cada país (página conjunta). */
export async function getBenchmarkByCpv(params: {
  countries?: BenchmarkCountry[];
  cpv_code?: string;
  year_from?: number;
  year_to?: number;
  top?: number;
} = {}): Promise<BenchmarkByCpvResponse> {
  const search = new URLSearchParams();
  if (params.countries?.length) search.set("countries", params.countries.join(","));
  if (params.cpv_code) search.set("cpv_code", params.cpv_code);
  if (params.year_from !== undefined) search.set("year_from", String(params.year_from));
  if (params.year_to !== undefined) search.set("year_to", String(params.year_to));
  if (params.top !== undefined) search.set("top", String(params.top));
  const res = await fetch(`${API_BASE}/benchmark/by-cpv?${search}`);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `Erro no quadro por CPV: ${res.status}`);
  }
  return res.json();
}

/** Pesquisa de entidades por país (para o seletor, conforme o papel).
 *
 * Usa o próprio módulo do benchmark (`/benchmark/entities`): assim os três
 * países respondem na mesma forma — e em França, onde o DECP não traz nomes, a
 * pesquisa é por SIRET (o campo `name` devolve o identificador).
 */
export async function searchBenchmarkEntities(
  country: BenchmarkCountry,
  role: BenchmarkRole,
  q: string,
  size = 8,
): Promise<{ nif: string; name: string; contracts: number; total_value?: number | null }[]> {
  const params = new URLSearchParams({ q, role, country, size: String(size) });
  const res = await fetch(`${API_BASE}/benchmark/entities?${params}`);
  if (!res.ok) throw new Error(`Erro ao procurar entidades: ${res.status}`);
  const dados: { items?: { nif?: string; name?: string; contracts?: number; total_value?: number | null }[] } =
    await res.json();
  return (dados.items ?? []).map((item) => ({
    nif: item.nif ?? "",
    name: item.name ?? item.nif ?? "",
    contracts: item.contracts ?? 0,
    total_value: item.total_value ?? null,
  }));
}
