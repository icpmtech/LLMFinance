/**
 * Vista de mercado (`/market/*`): os tickers da plataforma agrupados por país.
 *
 * O país tem **origem declarada** (`country_source`): `yahoo` (campo `country` do
 * Yahoo Finance), `mercado` (sufixo do símbolo, ex.: `.LS` → Portugal) ou
 * `desconhecido`. Nenhuma linha é preenchida com um valor suposto: um ticker sem
 * cotação traz o `error` que explica porquê.
 *
 * A **marca** de cada empresa vem em `logo_url` (rota `/market/logo/<ticker>`),
 * extraída do site oficial e guardada no servidor. Vem `null` quando não há site
 * de onde a tirar (um índice não tem) — nesse caso o frontend mostra as iniciais,
 * sem chegar a pedir uma imagem que só podia falhar.
 */
import { API_BASE } from "./api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, init);
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

/** De onde veio o país de uma linha. */
export type MarketCountrySource = "yahoo" | "mercado" | "desconhecido" | "cache";

/** Um ticker na vista: cotação do dia, país resolvido e identidade. */
export type MarketCountryTicker = {
  ticker: string;
  name?: string | null;
  sector?: string | null;
  exchange?: string | null;
  currency?: string | null;
  /** Site oficial da empresa (Yahoo Finance) — a origem do logótipo. */
  site?: string | null;
  /** A empresa tem site? `true` quando o Yahoo respondeu (mesmo sem site). */
  site_verificado?: boolean;
  price?: number | null;
  previous_close?: number | null;
  change?: number | null;
  change_pct?: number | null;
  change_label?: string | null;
  price_label?: string | null;
  market_cap?: number | null;
  market_cap_label?: string | null;
  /** Marca da empresa (`/market/logo/<ticker>`), ou `null` quando não há de onde a tirar. */
  logo_url?: string | null;
  /** País (ISO alfa-2) e a sua etiqueta em português. */
  country: string;
  country_label: string;
  country_source: MarketCountrySource;
  /** Endereço da ficha do ticker na aplicação. */
  url: string;
  /** Presente quando **não** há cotação: explica o motivo. */
  error?: string | null;
};

/** Agregados de um país (só contam o que foi lido). */
export type MarketCountryStats = {
  tickers: number;
  quoted: number;
  without_quote: number;
  advancers: number;
  decliners: number;
  flat: number;
  average_change_pct: number | null;
  market_cap: number | null;
  market_cap_count: number;
};

export type MarketCountryBest = { ticker: string; name?: string | null; change_pct: number } | null;

/** Um país e os seus tickers. */
export type MarketCountryGroup = {
  country: string;
  country_label: string;
  unknown: boolean;
  tickers: MarketCountryTicker[];
  stats: MarketCountryStats;
  rank: { id: "em-alta" | "em-baixa" | "estavel" | "sem-cotacao"; label: string };
  best: MarketCountryBest;
  worst: MarketCountryBest;
};

export type MarketByCountry = {
  source: string;
  generated_at: string;
  caveat: string;
  universe: {
    requested: number;
    available: number;
    truncated: number;
    errors: { ticker: string; error: string | null; country?: string; country_label?: string }[];
  };
  countries: MarketCountryGroup[];
  totals: MarketCountryStats;
};

/** Metamodelo da vista (fonte, limites e o significado de cada origem de país). */
export type MarketMeta = {
  source: string;
  caveat: string;
  universe: number;
  default_limit: number;
  max_limit: number;
  cache_seconds: number;
  country_sources: Record<string, string>;
  /** De onde vem a marca de cada empresa e por quanto tempo não se repete. */
  logo: { fonte: string; rota: string; retry_days: number };
  /** Ficheiro onde fica o perfil aprendido de cada ticker (país, nome, site). */
  profile_cache: string | null;
};

export type MarketQuery = {
  /** Quantos tickers ler (o universo da plataforma tem ~90). */
  limit?: number;
  /** Tickers específicos; sem valor, usa o universo da plataforma. */
  tickers?: string[];
  /** Ignorar a cópia em memória do servidor e voltar a ler o Yahoo. */
  refresh?: boolean;
};

/** Tickers da plataforma agrupados por país, com a cotação do dia. */
export function getMarketByCountry(options: MarketQuery = {}) {
  const params = new URLSearchParams();
  if (options.limit) params.set("limit", String(options.limit));
  if (options.tickers?.length) params.set("tickers", options.tickers.join(","));
  if (options.refresh) params.set("refresh", "1");
  const search = params.toString();
  return request<MarketByCountry>(`/market/by-country${search ? `?${search}` : ""}`);
}

/** Fonte, ressalva de preço e limites da vista. */
export function getMarketMeta() {
  return request<MarketMeta>("/market/meta");
}
