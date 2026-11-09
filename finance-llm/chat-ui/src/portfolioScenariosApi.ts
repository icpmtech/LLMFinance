/**
 * API do módulo "Test market scenarios - AI tools for trading" (`/portfolio/scenarios/*`).
 *
 * O módulo reutiliza o escopo de portfólio (carteira ou watchlist) mas apresenta-se
 * como aplicação própria no menu principal (`/trading-scenarios`).
 */
import { API_BASE } from "./api";

function authHeaders(): Record<string, string> {
  const token = typeof window !== "undefined" ? window.localStorage.getItem("finance-llm-token") : null;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export type ScenariosScopeRequest = {
  tickers?: string[];
  weights?: number[];
  portfolio_id?: string;
  watchlist_id?: string;
};

export type ScenarioTemplate = {
  id: string;
  label: string;
  description: string;
  probability: number;
  shocks: Record<string, number>;
  factor_correlation: number;
};

export type StressTestTicker = {
  ticker: string;
  sector: string;
  weight: number;
  beta: number;
  scenario_return: number;
  annualized_return: number;
};

export type StressTestResponse = {
  scenario_id: string;
  scenario_label: string;
  scenario_description: string;
  horizon_days: number;
  probability?: number;
  portfolio_impact_pct: number;
  scenario_volatility_pct: number;
  var_95_pct: number;
  cvar_95_pct: number;
  tickers: StressTestTicker[];
  shocks: Record<string, number>;
  as_of: string;
  scope?: ScenariosScopeMeta;
  error?: string;
};

export type BacktestMetrics = {
  total_return_pct: number;
  annualized_return_pct: number;
  volatility_pct: number;
  sharpe_ratio: number;
  max_drawdown_pct: number;
  trades?: number;
};

export type BacktestResponse = {
  strategy: string;
  tickers: string[];
  weights: number[];
  initial_cash: number;
  final_value_strategy: number;
  final_value_buyhold: number;
  strategy_metrics: BacktestMetrics;
  buyhold_metrics: BacktestMetrics;
  equity_curve: { date: string; strategy: number; buyhold: number }[];
  as_of: string;
  scope?: ScenariosScopeMeta;
  error?: string;
};

export type SignalIndicator = {
  ticker: string;
  last_price: number;
  sma20: number;
  sma50: number;
  rsi14: number;
  macd: number;
  macd_signal: number;
  dates?: string[];
  prices?: number[];
};

export type TradingSignal = {
  ticker: string;
  signal: "comprar" | "vender" | "neutro";
  confidence: number;
  rationale: string;
  time_horizon: string;
  stop_loss?: number;
  take_profit?: number;
  source: "llm" | "heuristic";
  indicators: SignalIndicator;
  error?: string;
};

export type TradingSignalsResponse = {
  signals: TradingSignal[];
  count: number;
  llm_enabled: boolean;
  as_of: string;
  scope?: ScenariosScopeMeta;
  error?: string;
};

export type WhatIfTrade = {
  ticker: string;
  side: "buy" | "sell";
  quantity: number;
  price: number;
  fees: number;
};

export type WhatIfHolding = {
  ticker: string;
  shares: number;
  price?: number;
  weight: number;
  value: number;
};

export type WhatIfResponse = {
  initial_value: number;
  final_value: number;
  cash_remaining: number;
  pnl_pct: number;
  trades: WhatIfTrade[];
  holdings: WhatIfHolding[];
  as_of: string;
  scope?: ScenariosScopeMeta;
  error?: string;
};

export type MonteCarloResponse = {
  initial_value: number;
  horizon_days: number;
  simulations: number;
  shock_probability: number;
  shock_mean_pct: number;
  shock_std_pct: number;
  median_final_value: number;
  worst_1pct_final_value: number;
  best_1pct_final_value: number;
  probability_of_loss_pct: number;
  var_95_pct: number;
  paths: {
    dates: string[];
    percentiles: Record<string, number[]>;
  };
  as_of: string;
  scope?: ScenariosScopeMeta;
  error?: string;
};

export type ScenariosSummaryTicker = {
  ticker: string;
  name?: string;
  price?: number;
  sector?: string;
};

export type ScenariosSummaryResponse = {
  tickers: ScenariosSummaryTicker[];
  weights: number[];
  portfolio_volatility_pct: number;
  scenario_count: number;
  templates: ScenarioTemplate[];
  as_of: string;
  scope?: ScenariosScopeMeta;
  error?: string;
};

export type ScenariosScopeMeta = {
  source: "request" | "portfolio" | "watchlist" | "default";
  portfolio_id?: string;
  portfolio_name?: string;
  watchlist_id?: string;
  watchlist_name?: string;
  currency?: string;
};

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

export async function getScenarioTemplates(): Promise<ScenarioTemplate[]> {
  return getJson<ScenarioTemplate[]>("/portfolio/scenarios/templates");
}

export async function getScenariosSummary(req?: ScenariosScopeRequest): Promise<ScenariosSummaryResponse> {
  return ensureOk(await postJson<ScenariosSummaryResponse>("/portfolio/scenarios/summary", req ?? {}));
}

export async function runStressTest(
  req: ScenariosScopeRequest & {
    scenario_id?: string;
    custom_shocks?: Record<string, number>;
    horizon_days?: number;
  },
): Promise<StressTestResponse> {
  return ensureOk(await postJson<StressTestResponse>("/portfolio/scenarios/stress", req));
}

export async function runBacktest(
  req: ScenariosScopeRequest & {
    strategy?: string;
    initial_cash?: number;
    params?: Record<string, unknown>;
  },
): Promise<BacktestResponse> {
  return ensureOk(await postJson<BacktestResponse>("/portfolio/scenarios/backtest", req));
}

export async function getTradingSignals(
  req: ScenariosScopeRequest & { use_llm?: boolean } = {},
): Promise<TradingSignalsResponse> {
  return ensureOk(await postJson<TradingSignalsResponse>("/portfolio/scenarios/signals", req));
}

export async function runWhatIf(
  req: ScenariosScopeRequest & {
    initial_value?: number;
    orders?: { ticker: string; side: "buy" | "sell"; quantity: number; price?: number; fee_rate?: number }[];
  },
): Promise<WhatIfResponse> {
  return ensureOk(await postJson<WhatIfResponse>("/portfolio/scenarios/what-if", req));
}

export async function runMonteCarlo(
  req: ScenariosScopeRequest & {
    horizon_days?: number;
    simulations?: number;
    shock_probability?: number;
    shock_mean?: number;
    shock_std?: number;
  } = {},
): Promise<MonteCarloResponse> {
  return ensureOk(await postJson<MonteCarloResponse>("/portfolio/scenarios/monte-carlo", req));
}
