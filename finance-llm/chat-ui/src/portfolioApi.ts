/**
 * API do módulo de portfólio financeiro (`/portfolio/*`).
 *
 * Todas as respostas vêm do backend FastAPI e usam dados reais do Yahoo Finance
 * e notícias do índice finance_news.
 */
import { API_BASE } from "./api";

/** Token da sessão: as rotas de gestão escrevem no índice da conta. */
function authHeaders(): Record<string, string> {
  const token = typeof window !== "undefined" ? window.localStorage.getItem("finance-llm-token") : null;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export type PortfolioTicker = {
  ticker: string;
  name: string;
  currency: string;
  exchange?: string;
  sector?: string;
  industry?: string;
  price?: number;
  previous_close?: number;
  change?: number;
  change_pct?: number;
  volume?: number;
  market_cap?: number;
  pe?: number;
  eps?: number;
  dividend_yield?: number;
  beta?: number;
  target_mean_price?: number;
  recommendation?: string;
  recommendation_mean?: number;
  number_of_analysts?: number;
  kpis?: Record<string, number>;
  quantity?: number;
  avg_price?: number;
  market_value?: number;
  cost_basis?: number;
  unrealized_pnl?: number;
  unrealized_pnl_pct?: number;
  weight?: number;
  error?: string;
};

export type PortfolioNewsItem = {
  id: string;
  title: string;
  /** T?tulo/resumo em portugu?s (tradu??o em segundo plano no servidor). */
  title_pt?: string;
  summary_pt?: string;
  summary?: string;
  publisher?: string;
  published?: string;
  url?: string;
  ticker?: string;
  sentiment?: string;
  topics?: string[];
};

export type PortfolioSummaryResponse = {
  portfolio_value: number;
  portfolio_change_pct: number;
  currency: string;
  tickers: PortfolioTicker[];
  weights: number[];
  cash?: number;
  invested_value?: number;
  positioned?: boolean;
  news: PortfolioNewsItem[];
  benchmark: { ticker: string; name: string };
  scope?: PortfolioScopeMeta;
  as_of: string;
};

export type PortfolioScopeMeta = {
  source: "request" | "portfolio" | "watchlist" | "default";
  portfolio_id?: string;
  portfolio_name?: string;
  watchlist_id?: string;
  watchlist_name?: string;
  currency?: string;
  cash?: number;
};

export type PortfolioAttributionSector = {
  sector: string;
  portfolio_weight: number;
  benchmark_weight: number;
  portfolio_return: number;
  benchmark_return: number;
  allocation_effect: number;
  selection_effect: number;
  currency_effect: number;
  total_effect: number;
  tickers: string[];
};

export type PortfolioAttributionResponse = {
  error?: string;
  period: string;
  portfolio_return: number;
  active_return: number;
  currency: string;
  sectors: PortfolioAttributionSector[];
  top_contributors: { ticker: string; weight: number; return_pct: number; contribution_pct: number; name: string }[];
  bottom_contributors: { ticker: string; weight: number; return_pct: number; contribution_pct: number; name: string }[];
  as_of: string;
};

export type PortfolioRiskResponse = {
  portfolio_volatility: number;
  portfolio_volatility_pct: number;
  expected_return_annual: number;
  beta: number;
  tracking_error: number;
  tracking_error_pct: number;
  var_95_daily: number;
  var_99_daily: number;
  cvar_95_daily: number;
  sharpe_ratio: number;
  total_active_risk_pct: number;
  factor_exposures: { factor: string; exposure: number; proxy: string }[];
  idiosyncratic_risk_pct: number;
  marginal_risk: { ticker: string; weight: number; volatility: number; marginal_risk: number; risk_contribution_pct: number; name: string }[];
  currency: string;
  as_of: string;
  error?: string;
};

export type PortfolioOptimizeResponse = {
  objective: string;
  optimal_weights: number[];
  expected_return_annual: number;
  expected_volatility: number;
  sharpe_ratio: number;
  current_weights: number[];
  current_expected_return: number;
  current_expected_volatility: number;
  tickers: { ticker: string; name: string }[];
  fundamental_scores: { ticker: string; ltg_eps_growth: number; sales_growth: number; active_total_risk: number; score: number; name: string }[];
  constraints: { field: string; group: string; min?: number; max: number; unit: string }[];
  currency: string;
  as_of: string;
  error?: string;
};

export type ForecastPoint = { date: string; price?: number; lower?: number; upper?: number };
export type ForecastSeries = { date: string; value?: number; type: string };

export type PortfolioForecastResponse = {
  future_days: number;
  use_sentiment: boolean;
  forecasts: {
    ticker: string;
    rmse?: number;
    mape?: number;
    currency?: string;
    company_name?: string;
    forecast: ForecastPoint[];
    series: ForecastSeries[];
    last_train_date?: string;
    last_test_date?: string;
    model_summary?: string;
    error?: string;
  }[];
  news: PortfolioNewsItem[];
  as_of: string;
};

export type PortfolioReportingResponse = {
  title: string;
  generated_at: string;
  currency: string;
  summary: PortfolioSummaryResponse;
  attribution: PortfolioAttributionResponse;
  risk: PortfolioRiskResponse;
  optimization: PortfolioOptimizeResponse;
  performance_series: Record<string, number | string>[];
  benchmark: { ticker: string; name: string };
};

export type PortfolioMetaResponse = {
  source: string;
  news_source: string;
  currency_default: string;
  cache_ttl_seconds: number;
  default_tickers: string[];
  default_weights: number[];
};

export type TickerHistoryResponse = {
  ticker: string;
  period: string;
  points: { date: string; open?: number; high?: number; low?: number; close?: number; volume?: number }[];
  error?: string;
};

export type PortfolioRequest = {
  tickers?: string[];
  weights?: number[];
  portfolio_id?: string;
  watchlist_id?: string;
};
export type ForecastRequest = PortfolioRequest & { future_days?: number; use_sentiment?: boolean };
export type OptimizeRequest = PortfolioRequest & { objective?: string };

/**
 * Respostas de an?lise que falham trazem `error` no corpo (HTTP 200): sem isto
 * o ecr? rebentava a ler listas que n?o existem.
 */
function ensureOk<T>(payload: T): T {
  const problem = (payload as { error?: unknown } | null)?.error;
  if (typeof problem === "string" && problem.trim()) {
    throw new Error(problem);
  }
  return payload;
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Erro ${res.status}: ${text}`);
  }
  return res.json();
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { headers: authHeaders() });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Erro ${res.status}: ${text}`);
  }
  return res.json();
}

async function sendJson<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = `Erro ${res.status}`;
    try {
      const payload = (await res.json()) as { detail?: unknown };
      if (payload?.detail) detail = String(payload.detail);
    } catch {
      /* resposta sem JSON */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export async function getPortfolioMeta(): Promise<PortfolioMetaResponse> {
  return getJson("/portfolio/meta");
}

export async function getPortfolioSummary(req?: PortfolioRequest): Promise<PortfolioSummaryResponse> {
  return ensureOk(await postJson<PortfolioSummaryResponse>("/portfolio/summary", req ?? {}));
}

export async function getPortfolioReporting(req?: PortfolioRequest): Promise<PortfolioReportingResponse> {
  return ensureOk(await postJson<PortfolioReportingResponse>("/portfolio/reporting", req ?? {}));
}

export async function getPortfolioForecast(req?: ForecastRequest): Promise<PortfolioForecastResponse> {
  return ensureOk(await postJson<PortfolioForecastResponse>("/portfolio/forecast", req ?? {}));
}

export async function getPortfolioResilience(req?: OptimizeRequest): Promise<PortfolioOptimizeResponse> {
  return ensureOk(await postJson<PortfolioOptimizeResponse>("/portfolio/resilience", req ?? {}));
}

export async function getPortfolioAttribution(req?: PortfolioRequest): Promise<PortfolioAttributionResponse> {
  return ensureOk(await postJson<PortfolioAttributionResponse>("/portfolio/attribution", req ?? {}));
}

export async function getPortfolioRisk(req?: PortfolioRequest): Promise<PortfolioRiskResponse> {
  return ensureOk(await postJson<PortfolioRiskResponse>("/portfolio/risk", req ?? {}));
}

export async function getPortfolioTickerInfo(ticker: string): Promise<PortfolioTicker> {
  return getJson(`/portfolio/ticker/${encodeURIComponent(ticker)}/info`);
}

export async function getPortfolioTickerHistory(ticker: string, period = "1y", interval = "1d"): Promise<TickerHistoryResponse> {
  return getJson(
    `/portfolio/ticker/${encodeURIComponent(ticker)}/history?period=${encodeURIComponent(period)}&interval=${encodeURIComponent(interval)}`,
  );
}

// ---------------------------------------------------------------------------
// Gestão de carteiras, watchlists e ordens (estado por conta)
// ---------------------------------------------------------------------------
export type SavedPosition = {
  ticker: string;
  name: string;
  weight: number;
  quantity: number;
  avg_price: number;
  target_price: number;
  note: string;
  added_at?: string;
};

export type SavedPortfolio = {
  id: string;
  name: string;
  description: string;
  currency: string;
  benchmark: string;
  cash: number;
  initial_cash: number;
  tags: string[];
  tickers: SavedPosition[];
  ticker_count: number;
  created_at?: string;
  updated_at?: string;
};

export type WatchlistItem = {
  ticker: string;
  name: string;
  target_price: number;
  note: string;
  added_at?: string;
};

export type SavedWatchlist = {
  id: string;
  name: string;
  description: string;
  items: WatchlistItem[];
  item_count: number;
  created_at?: string;
  updated_at?: string;
};

export type SavedOrder = {
  id: string;
  order_id: string;
  portfolio_id: string;
  ticker: string;
  side: "buy" | "sell";
  order_type: "market" | "limit";
  status: "pending" | "filled" | "cancelled" | "rejected";
  quantity: number;
  limit_price: number;
  filled_price: number;
  filled_quantity: number;
  notional: number;
  fees: number;
  placed_at?: string;
  executed_at?: string;
};

export type TickerSearchItem = {
  ticker: string;
  name: string;
  exchange: string;
  type: string;
  sector: string;
  industry: string;
};

export type PortfolioSources = {
  portfolios: SavedPortfolio[];
  watchlists: SavedWatchlist[];
  has_portfolio: boolean;
  has_watchlist: boolean;
};

export async function getPortfolioSources(): Promise<PortfolioSources> {
  return getJson("/portfolio/sources");
}

export async function searchTickers(q: string, limit = 12): Promise<TickerSearchItem[]> {
  const result = await getJson<{ items: TickerSearchItem[] }>(
    `/portfolio/search?q=${encodeURIComponent(q)}&limit=${limit}`,
  );
  return result.items ?? [];
}

export async function listPortfolios(): Promise<SavedPortfolio[]> {
  const result = await getJson<{ items: SavedPortfolio[] }>("/portfolio/portfolios");
  return result.items ?? [];
}

export async function createPortfolio(body: {
  name: string;
  description?: string;
  currency?: string;
  benchmark?: string;
  cash?: number;
  tags?: string[];
}): Promise<SavedPortfolio> {
  return sendJson("POST", "/portfolio/portfolios", body);
}

export async function updatePortfolio(
  portfolioId: string,
  body: Partial<Pick<SavedPortfolio, "name" | "description" | "currency" | "benchmark" | "cash" | "tags">>,
): Promise<SavedPortfolio> {
  return sendJson("PATCH", `/portfolio/portfolios/${encodeURIComponent(portfolioId)}`, body);
}

export async function deletePortfolio(portfolioId: string): Promise<{ deleted: string }> {
  return sendJson("DELETE", `/portfolio/portfolios/${encodeURIComponent(portfolioId)}`);
}

export async function addPortfolioTicker(
  portfolioId: string,
  body: {
    ticker: string;
    name?: string;
    weight?: number;
    quantity?: number;
    avg_price?: number;
    target_price?: number;
    note?: string;
    fill_price?: boolean;
  },
): Promise<SavedPortfolio> {
  return sendJson("POST", `/portfolio/portfolios/${encodeURIComponent(portfolioId)}/tickers`, body);
}

export async function updatePortfolioTicker(
  portfolioId: string,
  ticker: string,
  body: {
    name?: string;
    weight?: number;
    quantity?: number;
    avg_price?: number;
    target_price?: number;
    note?: string;
  },
): Promise<SavedPortfolio> {
  return sendJson("PATCH", `/portfolio/portfolios/${encodeURIComponent(portfolioId)}/tickers/${encodeURIComponent(ticker)}`, body);
}

export async function removePortfolioTicker(portfolioId: string, ticker: string): Promise<SavedPortfolio> {
  return sendJson(
    "DELETE",
    `/portfolio/portfolios/${encodeURIComponent(portfolioId)}/tickers/${encodeURIComponent(ticker)}`,
  );
}

export async function listWatchlists(): Promise<SavedWatchlist[]> {
  const result = await getJson<{ items: SavedWatchlist[] }>("/portfolio/watchlists");
  return result.items ?? [];
}

export async function createWatchlist(body: {
  name: string;
  description?: string;
}): Promise<SavedWatchlist> {
  return sendJson("POST", "/portfolio/watchlists", body);
}

export async function deleteWatchlist(watchlistId: string): Promise<{ deleted: string }> {
  return sendJson("DELETE", `/portfolio/watchlists/${encodeURIComponent(watchlistId)}`);
}

export async function addWatchlistItem(
  watchlistId: string,
  body: { ticker: string; name?: string; target_price?: number; note?: string },
): Promise<SavedWatchlist> {
  return sendJson("POST", `/portfolio/watchlists/${encodeURIComponent(watchlistId)}/items`, body);
}

export async function removeWatchlistItem(watchlistId: string, ticker: string): Promise<SavedWatchlist> {
  return sendJson(
    "DELETE",
    `/portfolio/watchlists/${encodeURIComponent(watchlistId)}/items/${encodeURIComponent(ticker)}`,
  );
}

export type CsvImportRow = {
  symbol: string;
  side?: "buy" | "sell" | "deposit" | string;
  quantity?: number;
  price?: number;
  fees?: number;
  date?: string;
  note?: string;
};

export type CsvImportResponse = {
  portfolio: SavedPortfolio;
  imported: number;
  cash: number;
  skipped?: { row: number; symbol: string; reason: string }[];
};

export async function importPortfolioCsv(body: {
  name: string;
  currency?: string;
  deposit_cash?: boolean;
  future_dates_as_today?: boolean;
  rows: CsvImportRow[];
}): Promise<CsvImportResponse> {
  return sendJson("POST", "/portfolio/import-csv", body);
}

export async function listOrders(portfolioId?: string): Promise<SavedOrder[]> {
  const query = portfolioId ? `?portfolio_id=${encodeURIComponent(portfolioId)}` : "";
  const result = await getJson<{ items: SavedOrder[] }>(`/portfolio/orders${query}`);
  return result.items ?? [];
}

export async function placeOrder(body: {
  portfolio_id: string;
  ticker: string;
  side: "buy" | "sell";
  quantity: number;
  order_type?: "market" | "limit";
  limit_price?: number;
  fees?: number;
  price?: number;
}): Promise<SavedOrder> {
  return sendJson("POST", "/portfolio/orders", body);
}

export async function cancelOrder(orderId: string): Promise<SavedOrder> {
  return sendJson("POST", `/portfolio/orders/${encodeURIComponent(orderId)}/cancel`);
}
