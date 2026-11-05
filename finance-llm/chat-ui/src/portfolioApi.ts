/**
 * API do módulo de portfólio financeiro (`/portfolio/*`).
 *
 * Todas as respostas vêm do backend FastAPI e usam dados reais do Yahoo Finance
 * e notícias do índice finance_news.
 */
import { API_BASE } from "./api";

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
  error?: string;
};

export type PortfolioNewsItem = {
  id: string;
  title: string;
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
  news: PortfolioNewsItem[];
  benchmark: { ticker: string; name: string };
  as_of: string;
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

export type PortfolioRequest = { tickers?: string[]; weights?: number[] };
export type ForecastRequest = { tickers?: string[]; future_days?: number; use_sentiment?: boolean };
export type OptimizeRequest = { tickers?: string[]; weights?: number[]; objective?: string };

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Erro ${res.status}: ${text}`);
  }
  return res.json();
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Erro ${res.status}: ${text}`);
  }
  return res.json();
}

export async function getPortfolioMeta(): Promise<PortfolioMetaResponse> {
  return getJson("/portfolio/meta");
}

export async function getPortfolioSummary(req?: PortfolioRequest): Promise<PortfolioSummaryResponse> {
  return postJson("/portfolio/summary", req ?? {});
}

export async function getPortfolioReporting(req?: PortfolioRequest): Promise<PortfolioReportingResponse> {
  return postJson("/portfolio/reporting", req ?? {});
}

export async function getPortfolioForecast(req?: ForecastRequest): Promise<PortfolioForecastResponse> {
  return postJson("/portfolio/forecast", req ?? {});
}

export async function getPortfolioResilience(req?: OptimizeRequest): Promise<PortfolioOptimizeResponse> {
  return postJson("/portfolio/resilience", req ?? {});
}

export async function getPortfolioAttribution(req?: PortfolioRequest): Promise<PortfolioAttributionResponse> {
  return postJson("/portfolio/attribution", req ?? {});
}

export async function getPortfolioRisk(req?: PortfolioRequest): Promise<PortfolioRiskResponse> {
  return postJson("/portfolio/risk", req ?? {});
}

export async function getPortfolioTickerInfo(ticker: string): Promise<PortfolioTicker> {
  return getJson(`/portfolio/ticker/${encodeURIComponent(ticker)}/info`);
}

export async function getPortfolioTickerHistory(ticker: string, period = "1y", interval = "1d"): Promise<TickerHistoryResponse> {
  return getJson(
    `/portfolio/ticker/${encodeURIComponent(ticker)}/history?period=${encodeURIComponent(period)}&interval=${encodeURIComponent(interval)}`,
  );
}
