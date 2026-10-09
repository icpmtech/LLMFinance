/**
 * Cliente do módulo **Benchmark de preços e concorrência** (`/benchmark/*`).
 *
 * O backend responde com preço de referência do segmento (CPV + anos), a lista
 * de concorrentes, o historial de contrapartes da empresa e as oportunidades
 * (contrapartes com que a empresa nunca contratou). Tudo em euros.
 */
import { API_BASE } from "./api";

export type BenchmarkRole = "adjudicatario" | "adjudicante";

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
  cpv_code?: string;
  year_from?: number;
  year_to?: number;
  region?: string;
  top?: number;
}

/** Volumetria do índice de contratos e anos disponíveis. */
export async function getBenchmarkMeta(): Promise<BenchmarkMeta> {
  const res = await fetch(`${API_BASE}/benchmark/meta`);
  if (!res.ok) throw new Error(`Erro ao obter o estado do benchmark: ${res.status}`);
  return res.json();
}

/** CPV mais usados no índice (para escolher o segmento). */
export async function getBenchmarkCpv(q?: string, size = 20): Promise<BenchmarkCpvResponse> {
  const params = new URLSearchParams({ size: String(size) });
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
