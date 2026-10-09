/**
 * Cliente do diretório de empresas do Racius (`/racius/*`).
 *
 * O diretório é alimentado pela recolha do IQ OS (fonte `racius-diretorio`), que
 * grava cada empresa em `finance_racius` com os campos da ficha normalizados
 * (concelho, distrito, forma jurídica, capital social…). Esta é a leitura: uma
 * pesquisa por texto + filtros, com facetas para os dropdowns.
 */
import { API_BASE } from "./api";

export type RaciusFacetValue = { value: string; count: number };

export type RaciusCompany = {
  nome?: string;
  nif?: string;
  concelho?: string;
  distrito?: string;
  forma_juridica?: string;
  capital_social_eur?: number;
  morada?: string;
  atividade?: string;
  cae?: string;
  url?: string;
  /** Ficha completa, como está na página da empresa (rótulo → valor). */
  ficha?: Record<string, string>;
  scraped_at?: string;
  source_id?: string;
  source_name?: string;
};

export type RaciusSearchResult = {
  total: number;
  items: RaciusCompany[];
  facets: Record<string, RaciusFacetValue[]>;
  error?: string;
};

export type RaciusMeta = {
  available: boolean;
  total: number;
  source_id?: string;
  source_name?: string;
  facets: Record<string, RaciusFacetValue[]>;
  facets_order: string[];
  sort_options: string[];
  error?: string;
};

export type RaciusQuery = {
  q?: string;
  distrito?: string;
  concelho?: string;
  forma_juridica?: string;
  cae?: string;
  minCapital?: number;
  maxCapital?: number;
  sort?: string;
  size?: number;
  offset?: number;
};

async function request<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`);
  if (!response.ok) {
    let detail = `${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: unknown };
      if (payload?.detail) detail = String(payload.detail);
    } catch {
      /* resposta sem JSON */
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

export function getRaciusMeta() {
  return request<RaciusMeta>("/racius/meta");
}

export function searchRaciusCompanies(query: RaciusQuery = {}) {
  const params = new URLSearchParams();
  const put = (name: string, value: string | number | undefined) => {
    if (value === undefined || value === null || value === "") return;
    params.set(name, String(value));
  };
  put("q", query.q?.trim());
  put("distrito", query.distrito);
  put("concelho", query.concelho);
  put("forma_juridica", query.forma_juridica);
  put("cae", query.cae);
  put("min_capital", query.minCapital);
  put("max_capital", query.maxCapital);
  put("sort", query.sort);
  put("size", query.size);
  put("offset", query.offset);
  const suffix = params.toString();
  return request<RaciusSearchResult>(`/racius/search${suffix ? `?${suffix}` : ""}`);
}

/** Formata euros como no resto da aplicação (sem casas decimais). */
export function formatEuros(value?: number | null): string {
  if (value === undefined || value === null) return "—";
  return new Intl.NumberFormat("pt-PT", { style: "currency", currency: "EUR", maximumFractionDigits: 0 }).format(value);
}
