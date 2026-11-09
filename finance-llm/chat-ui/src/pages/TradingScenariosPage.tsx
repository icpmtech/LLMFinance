import { useCallback, useEffect, useMemo, useState } from "react";
import {
  FlaskConical,
  Activity,
  AlertTriangle,
  RefreshCw,
  Play,
  Scale,
  Sparkles,
  Shuffle,
} from "lucide-react";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  Area,
  AreaChart,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  BarChart,
  Bar,
  Legend,
  PieChart,
  Pie,
  Cell,
} from "recharts";
import {
  getScenarioTemplates,
  getScenariosSummary,
  runStressTest,
  runBacktest,
  getTradingSignals,
  runWhatIf,
  runMonteCarlo,
  type ScenarioTemplate,
  type StressTestResponse,
  type BacktestResponse,
  type TradingSignalsResponse,
  type WhatIfResponse,
  type MonteCarloResponse,
  type ScenariosSummaryResponse,
  type TradingSignal,
} from "../portfolioScenariosApi";
import { usePortfolioScope } from "../portfolioScope";
import { PortfolioScopeBar } from "../components/portfolio/PortfolioScopeBar";
import { PortfolioLoading } from "../components/portfolio/PortfolioLoading";

const STRATEGIES = [
  { value: "sma-cross", label: "Cruzamento de médias (SMA 20/50)" },
  { value: "rsi-mean-reversion", label: "RSI reversão à média (30/70)" },
  { value: "momentum", label: "Momentum (90 dias)" },
];
const HORIZON_DAYS = [60, 126, 252, 504];

function fmtPct(n?: number | null) {
  if (n == null || Number.isNaN(n)) return "—";
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(2)}%`;
}

function fmt(n?: number | null, digits = 2) {
  if (n == null || Number.isNaN(n)) return "—";
  return n.toLocaleString("pt-PT", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function signalColor(signal: string) {
  if (signal === "comprar") return "text-emerald-400 bg-emerald-500/10";
  if (signal === "vender") return "text-rose-400 bg-rose-500/10";
  return "text-slate-300 bg-slate-700/40";
}

export function TradingScenariosPage() {
  const scope = usePortfolioScope();
  const portfolioId = scope.portfolioId;

  const [summary, setSummary] = useState<ScenariosSummaryResponse | null>(null);
  const [templates, setTemplates] = useState<ScenarioTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [activeTab, setActiveTab] = useState<"stress" | "backtest" | "signals" | "whatif" | "montecarlo">("stress");
  const [selectedScenario, setSelectedScenario] = useState<string>("recession");
  const [horizon, setHorizon] = useState<number>(252);
  const [strategy, setStrategy] = useState<string>("sma-cross");
  const [useLlm, setUseLlm] = useState<boolean>(true);

  const [stress, setStress] = useState<StressTestResponse | null>(null);
  const [backtest, setBacktest] = useState<BacktestResponse | null>(null);
  const [signals, setSignals] = useState<TradingSignalsResponse | null>(null);
  const [whatIf, setWhatIf] = useState<WhatIfResponse | null>(null);
  const [monteCarlo, setMonteCarlo] = useState<MonteCarloResponse | null>(null);
  const [orderInput, setOrderInput] = useState<{ ticker: string; side: "buy" | "sell"; quantity: number }[]>([]);
  const baseReq = useMemo(
    () => ({ portfolio_id: portfolioId ?? undefined }),
    [portfolioId],
  );

  const loadSummary = useCallback(async () => {
    if (scope.loading) return;
    setLoading(true);
    setError(null);
    try {
      const [tpl, sum] = await Promise.all([
        getScenarioTemplates(),
        getScenariosSummary(portfolioId ? { portfolio_id: portfolioId } : {}),
      ]);
      setTemplates(tpl);
      setSummary(sum);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao carregar cenários");
    } finally {
      setLoading(false);
    }
  }, [portfolioId, scope.loading]);

  useEffect(() => {
    void loadSummary();
  }, [loadSummary]);

  // Quando o sumário chega, preenche as ordens exemplificativas com os tickers
  // da carteira — apenas se ainda não foram editadas pelo utilizador.
  useEffect(() => {
    if (summary?.tickers && orderInput.length === 0) {
      setOrderInput(summary.tickers.slice(0, 5).map((t) => ({ ticker: t.ticker, side: "buy", quantity: 10 })));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [summary]);

  const runStress = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await runStressTest({ ...baseReq, scenario_id: selectedScenario, horizon_days: horizon });
      setStress(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro no stress-test");
    } finally {
      setLoading(false);
    }
  }, [baseReq, selectedScenario, horizon]);

  const runBack = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await runBacktest({ ...baseReq, strategy });
      setBacktest(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro no backtest");
    } finally {
      setLoading(false);
    }
  }, [baseReq, strategy]);

  const runSignals = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await getTradingSignals({ ...baseReq, use_llm: useLlm });
      setSignals(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro nos sinais");
    } finally {
      setLoading(false);
    }
  }, [baseReq, useLlm]);

  const runOrders = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await runWhatIf({ ...baseReq, initial_value: 100_000, orders: orderInput.filter((o) => o.quantity > 0) });
      setWhatIf(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro no simulador");
    } finally {
      setLoading(false);
    }
  }, [baseReq, orderInput]);

  const runMC = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await runMonteCarlo({ ...baseReq, horizon_days: 60, simulations: 500 });
      setMonteCarlo(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro no Monte Carlo");
    } finally {
      setLoading(false);
    }
  }, [baseReq]);

  const updateOrder = (index: number, patch: Partial<{ ticker: string; side: "buy" | "sell"; quantity: number }>) => {
    setOrderInput((prev) => prev.map((o, i) => (i === index ? { ...o, ...patch } : o)));
  };

  const stressChartData = useMemo(
    () =>
      stress?.tickers.slice(0, 12).map((t) => ({
        name: t.ticker,
        impact: t.scenario_return,
        weight: t.weight * 100,
      })) ?? [],
    [stress],
  );

  const backtestChartData = useMemo(() => backtest?.equity_curve ?? [], [backtest]);

  const mcPercentiles = useMemo(() => {
    if (!monteCarlo?.paths) return [];
    const { dates, percentiles } = monteCarlo.paths;
    return dates.map((date, i) => ({
      date,
      p5: percentiles["5"][i],
      p25: percentiles["25"][i],
      p50: percentiles["50"][i],
      p75: percentiles["75"][i],
      p95: percentiles["95"][i],
    }));
  }, [monteCarlo]);

  const signalPieData = useMemo(() => {
    if (!signals) return [];
    const counts: Record<string, number> = { comprar: 0, vender: 0, neutro: 0 };
    signals.signals.forEach((s) => {
      if (!s.error) counts[s.signal] = (counts[s.signal] || 0) + 1;
    });
    return Object.entries(counts)
      .filter(([, v]) => v > 0)
      .map(([name, value]) => ({ name, value, color: name === "comprar" ? "#34d399" : name === "vender" ? "#f87171" : "#94a3b8" }));
  }, [signals]);

  return (
    <div className="min-h-screen bg-[#0b0d10] text-slate-200 p-4 md:p-6">
      <div className="mx-auto max-w-7xl space-y-6">
        <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
          <div className="flex items-center gap-3">
            <div className="rounded-lg bg-violet-500/10 p-2">
              <FlaskConical className="h-6 w-6 text-violet-400" />
            </div>
            <div>
              <h1 className="text-2xl font-semibold text-white">Testar cenários de mercado</h1>
              <p className="text-sm text-slate-400">
                Stress-test, backtest, sinais de IA e simulação de choques sobre a carteira.
              </p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <PortfolioScopeBar scope={scope} />
            <button
              onClick={loadSummary}
              disabled={loading}
              className="inline-flex items-center gap-2 rounded-md bg-slate-800 px-3 py-2 text-sm font-medium text-slate-200 hover:bg-slate-700 disabled:opacity-50"
            >
              <RefreshCw className={classNames("h-4 w-4", loading && "animate-spin")} />
              Atualizar
            </button>
          </div>
        </div>

        {summary && !summary.error && (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-4">
              <div className="text-xs uppercase tracking-wider text-slate-500">Ativos no escopo</div>
              <div className="mt-1 text-xl font-semibold text-white">{summary.tickers.length}</div>
            </div>
            <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-4">
              <div className="text-xs uppercase tracking-wider text-slate-500">Volatilidade anualizada</div>
              <div className="mt-1 text-xl font-semibold text-white">{fmtPct(summary.portfolio_volatility_pct)}</div>
            </div>
            <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-4">
              <div className="text-xs uppercase tracking-wider text-slate-500">Cenários disponíveis</div>
              <div className="mt-1 text-xl font-semibold text-white">{summary.scenario_count}</div>
            </div>
            <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-4">
              <div className="text-xs uppercase tracking-wider text-slate-500">Modelo IA</div>
              <div className="mt-1 text-sm text-slate-200">Opcional (LLM cloud)</div>
            </div>
          </div>
        )}

        {error && (
          <div className="flex items-center gap-3 rounded-md border border-rose-500/30 bg-rose-500/10 p-4 text-rose-200">
            <AlertTriangle className="h-5 w-5" />
            <div>{error}</div>
          </div>
        )}

        {loading && !summary && <PortfolioLoading />}

        <div className="flex flex-wrap gap-2">
          {[
            { id: "stress", label: "Stress-test", icon: Activity },
            { id: "backtest", label: "Backtest", icon: Play },
            { id: "signals", label: "Sinais IA", icon: Sparkles },
            { id: "whatif", label: "What-if", icon: Scale },
            { id: "montecarlo", label: "Monte Carlo", icon: Shuffle },
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id as any)}
              className={classNames(
                "inline-flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium",
                activeTab === tab.id
                  ? "bg-violet-600 text-white"
                  : "bg-slate-800 text-slate-300 hover:bg-slate-700",
              )}
            >
              <tab.icon className="h-4 w-4" />
              {tab.label}
            </button>
          ))}
        </div>

        {activeTab === "stress" && (
          <div className="space-y-4">
            <div className="flex flex-wrap items-end gap-3 rounded-lg border border-slate-800 bg-slate-900/50 p-4">
              <div>
                <label className="block text-xs text-slate-500">Cenário</label>
                <select
                  value={selectedScenario}
                  onChange={(e) => setSelectedScenario(e.target.value)}
                  className="mt-1 rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200"
                >
                  {templates.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.label}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-xs text-slate-500">Horizonte (dias)</label>
                <select
                  value={horizon}
                  onChange={(e) => setHorizon(Number(e.target.value))}
                  className="mt-1 rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200"
                >
                  {HORIZON_DAYS.map((d) => (
                    <option key={d} value={d}>
                      {d}
                    </option>
                  ))}
                </select>
              </div>
              <button
                onClick={runStress}
                disabled={loading}
                className="inline-flex items-center gap-2 rounded-md bg-violet-600 px-4 py-2 text-sm font-medium text-white hover:bg-violet-500 disabled:opacity-50"
              >
                <Activity className="h-4 w-4" />
                Correr stress-test
              </button>
            </div>

            {stress && !stress.error && (
              <div className="grid gap-4 lg:grid-cols-3">
                <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-4 lg:col-span-1">
                  <h3 className="text-sm font-medium text-slate-200">{stress.scenario_label}</h3>
                  <p className="mt-1 text-xs text-slate-400">{stress.scenario_description}</p>
                  <div className="mt-4 space-y-3">
                    <div className="flex justify-between text-sm">
                      <span className="text-slate-400">Impacto na carteira</span>
                      <span className={stress.portfolio_impact_pct >= 0 ? "text-emerald-400" : "text-rose-400"}>
                        {fmtPct(stress.portfolio_impact_pct)}
                      </span>
                    </div>
                    <div className="flex justify-between text-sm">
                      <span className="text-slate-400">Volatilidade esperada</span>
                      <span className="text-slate-200">{fmtPct(stress.scenario_volatility_pct)}</span>
                    </div>
                    <div className="flex justify-between text-sm">
                      <span className="text-slate-400">VaR 95%</span>
                      <span className="text-rose-400">{fmtPct(stress.var_95_pct)}</span>
                    </div>
                    <div className="flex justify-between text-sm">
                      <span className="text-slate-400">CVaR 95%</span>
                      <span className="text-rose-400">{fmtPct(stress.cvar_95_pct)}</span>
                    </div>
                  </div>
                </div>
                <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-4 lg:col-span-2">
                  <h3 className="mb-3 text-sm font-medium text-slate-200">Impacto por ativo</h3>
                  <div className="h-80">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={stressChartData} layout="vertical" margin={{ left: 40 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#334155" horizontal={false} />
                        <XAxis type="number" stroke="#94a3b8" tickFormatter={(v) => `${v}%`} />
                        <YAxis type="category" dataKey="name" stroke="#94a3b8" width={60} />
                        <Tooltip
                          contentStyle={{ backgroundColor: "#0f172a", borderColor: "#334155" }}
                          formatter={(value: unknown) => {
                            const v = Array.isArray(value) ? value[0] : value;
                            return fmtPct(typeof v === "number" ? v : undefined);
                          }}
                        />
                        <Bar dataKey="impact" radius={[0, 4, 4, 0]}>
                          {stressChartData.map((entry, i) => (
                            <Cell key={i} fill={entry.impact >= 0 ? "#34d399" : "#f87171"} />
                          ))}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        {activeTab === "backtest" && (
          <div className="space-y-4">
            <div className="flex flex-wrap items-end gap-3 rounded-lg border border-slate-800 bg-slate-900/50 p-4">
              <div>
                <label className="block text-xs text-slate-500">Estratégia</label>
                <select
                  value={strategy}
                  onChange={(e) => setStrategy(e.target.value)}
                  className="mt-1 rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200"
                >
                  {STRATEGIES.map((s) => (
                    <option key={s.value} value={s.value}>
                      {s.label}
                    </option>
                  ))}
                </select>
              </div>
              <button
                onClick={runBack}
                disabled={loading}
                className="inline-flex items-center gap-2 rounded-md bg-violet-600 px-4 py-2 text-sm font-medium text-white hover:bg-violet-500 disabled:opacity-50"
              >
                <Play className="h-4 w-4" />
                Correr backtest
              </button>
            </div>

            {backtest && !backtest.error && (
              <div className="space-y-4">
                <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                  <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-4">
                    <div className="text-xs uppercase tracking-wider text-slate-500">Valor final estratégia</div>
                    <div className="mt-1 text-xl font-semibold text-white">{fmt(backtest.final_value_strategy)} $</div>
                  </div>
                  <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-4">
                    <div className="text-xs uppercase tracking-wider text-slate-500">Buy &amp; hold</div>
                    <div className="mt-1 text-xl font-semibold text-white">{fmt(backtest.final_value_buyhold)} $</div>
                  </div>
                  <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-4">
                    <div className="text-xs uppercase tracking-wider text-slate-500">Sharpe estratégia</div>
                    <div className="mt-1 text-xl font-semibold text-white">{backtest.strategy_metrics.sharpe_ratio}</div>
                  </div>
                  <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-4">
                    <div className="text-xs uppercase tracking-wider text-slate-500">Trades</div>
                    <div className="mt-1 text-xl font-semibold text-white">{backtest.strategy_metrics.trades ?? 0}</div>
                  </div>
                </div>
                <div className="h-80 rounded-lg border border-slate-800 bg-slate-900/50 p-4">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={backtestChartData}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                      <XAxis dataKey="date" stroke="#94a3b8" tickFormatter={(v) => v.slice(0, 7)} minTickGap={30} />
                      <YAxis stroke="#94a3b8" tickFormatter={(v) => fmt(v, 0)} />
                      <Tooltip contentStyle={{ backgroundColor: "#0f172a", borderColor: "#334155" }} />
                      <Legend />
                      <Line type="monotone" dataKey="strategy" name="Estratégia" stroke="#8b5cf6" strokeWidth={2} dot={false} />
                      <Line type="monotone" dataKey="buyhold" name="Buy &amp; hold" stroke="#94a3b8" strokeWidth={2} dot={false} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </div>
            )}
          </div>
        )}

        {activeTab === "signals" && (
          <div className="space-y-4">
            <div className="flex flex-wrap items-end gap-3 rounded-lg border border-slate-800 bg-slate-900/50 p-4">
              <label className="inline-flex items-center gap-2 text-sm text-slate-300">
                <input
                  type="checkbox"
                  checked={useLlm}
                  onChange={(e) => setUseLlm(e.target.checked)}
                  className="h-4 w-4 rounded border-slate-600 bg-slate-900 text-violet-600"
                />
                Usar LLM (cloud) quando disponível
              </label>
              <button
                onClick={runSignals}
                disabled={loading}
                className="inline-flex items-center gap-2 rounded-md bg-violet-600 px-4 py-2 text-sm font-medium text-white hover:bg-violet-500 disabled:opacity-50"
              >
                <Sparkles className="h-4 w-4" />
                Gerar sinais
              </button>
            </div>

            {signals && !signals.error && (
              <div className="grid gap-4 lg:grid-cols-3">
                <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-4 lg:col-span-1">
                  <h3 className="mb-2 text-sm font-medium text-slate-200">Distribuição de sinais</h3>
                  <div className="h-64">
                    <ResponsiveContainer width="100%" height="100%">
                      <PieChart>
                        <Pie
                          data={signalPieData}
                          dataKey="value"
                          nameKey="name"
                          innerRadius={50}
                          outerRadius={80}
                          paddingAngle={4}
                        >
                          {signalPieData.map((entry, i) => (
                            <Cell key={i} fill={entry.color} />
                          ))}
                        </Pie>
                        <Tooltip contentStyle={{ backgroundColor: "#0f172a", borderColor: "#334155" }} />
                        <Legend />
                      </PieChart>
                    </ResponsiveContainer>
                  </div>
                </div>
                <div className="space-y-3 lg:col-span-2">
                  {signals.signals.map((s) => (
                    <SignalCard key={s.ticker} signal={s} />
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {activeTab === "whatif" && (
          <div className="space-y-4">
            <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-4">
              <h3 className="mb-3 text-sm font-medium text-slate-200">Ordens hipotéticas</h3>
              <div className="space-y-2">
                {orderInput.map((o, i) => (
                  <div key={i} className="flex flex-wrap items-center gap-2">
                    <input
                      type="text"
                      value={o.ticker}
                      onChange={(e) => updateOrder(i, { ticker: e.target.value.toUpperCase() })}
                      className="w-24 rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-sm text-slate-200"
                      placeholder="Ticker"
                    />
                    <select
                      value={o.side}
                      onChange={(e) => updateOrder(i, { side: e.target.value as "buy" | "sell" })}
                      className="rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-sm text-slate-200"
                    >
                      <option value="buy">Comprar</option>
                      <option value="sell">Vender</option>
                    </select>
                    <input
                      type="number"
                      min={0}
                      value={o.quantity}
                      onChange={(e) => updateOrder(i, { quantity: Number(e.target.value) })}
                      className="w-24 rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-sm text-slate-200"
                      placeholder="Qtd"
                    />
                  </div>
                ))}
              </div>
              <button
                onClick={runOrders}
                disabled={loading}
                className="mt-3 inline-flex items-center gap-2 rounded-md bg-violet-600 px-4 py-2 text-sm font-medium text-white hover:bg-violet-500 disabled:opacity-50"
              >
                <Scale className="h-4 w-4" />
                Simular
              </button>
            </div>

            {whatIf && !whatIf.error && (
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-4">
                  <div className="text-xs uppercase tracking-wider text-slate-500">Valor inicial</div>
                  <div className="mt-1 text-xl font-semibold text-white">{fmt(whatIf.initial_value)} $</div>
                </div>
                <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-4">
                  <div className="text-xs uppercase tracking-wider text-slate-500">Valor final</div>
                  <div className="mt-1 text-xl font-semibold text-white">{fmt(whatIf.final_value)} $</div>
                </div>
                <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-4">
                  <div className="text-xs uppercase tracking-wider text-slate-500">P/L</div>
                  <div className={classNames("mt-1 text-xl font-semibold", whatIf.pnl_pct >= 0 ? "text-emerald-400" : "text-rose-400")}>
                    {fmtPct(whatIf.pnl_pct)}
                  </div>
                </div>
                <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-4">
                  <div className="text-xs uppercase tracking-wider text-slate-500">Caixa restante</div>
                  <div className="mt-1 text-xl font-semibold text-white">{fmt(whatIf.cash_remaining)} $</div>
                </div>
                <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-4 sm:col-span-2 lg:col-span-4">
                  <h3 className="mb-2 text-sm font-medium text-slate-200">Posições resultantes</h3>
                  <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                    {whatIf.holdings.map((h) => (
                      <div key={h.ticker} className="rounded-md bg-slate-800/50 p-3">
                        <div className="flex justify-between text-sm font-medium">
                          <span className="text-white">{h.ticker}</span>
                          <span className="text-slate-400">{fmtPct(h.weight * 100)}</span>
                        </div>
                        <div className="mt-1 text-xs text-slate-400">
                          {h.shares.toFixed(2)} ações · {fmt(h.value)} $
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        {activeTab === "montecarlo" && (
          <div className="space-y-4">
            <div className="flex flex-wrap items-end gap-3 rounded-lg border border-slate-800 bg-slate-900/50 p-4">
              <button
                onClick={runMC}
                disabled={loading}
                className="inline-flex items-center gap-2 rounded-md bg-violet-600 px-4 py-2 text-sm font-medium text-white hover:bg-violet-500 disabled:opacity-50"
              >
                <Shuffle className="h-4 w-4" />
                Correr Monte Carlo
              </button>
            </div>

            {monteCarlo && !monteCarlo.error && (
              <div className="space-y-4">
                <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                  <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-4">
                    <div className="text-xs uppercase tracking-wider text-slate-500">Mediana final</div>
                    <div className="mt-1 text-xl font-semibold text-white">{fmt(monteCarlo.median_final_value)} $</div>
                  </div>
                  <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-4">
                    <div className="text-xs uppercase tracking-wider text-slate-500">Pior 1%</div>
                    <div className="mt-1 text-xl font-semibold text-rose-400">{fmt(monteCarlo.worst_1pct_final_value)} $</div>
                  </div>
                  <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-4">
                    <div className="text-xs uppercase tracking-wider text-slate-500">Melhor 1%</div>
                    <div className="mt-1 text-xl font-semibold text-emerald-400">{fmt(monteCarlo.best_1pct_final_value)} $</div>
                  </div>
                  <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-4">
                    <div className="text-xs uppercase tracking-wider text-slate-500">Prob. perda</div>
                    <div className="mt-1 text-xl font-semibold text-white">{fmtPct(monteCarlo.probability_of_loss_pct)}</div>
                  </div>
                </div>
                <div className="h-80 rounded-lg border border-slate-800 bg-slate-900/50 p-4">
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={mcPercentiles}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                      <XAxis dataKey="date" stroke="#94a3b8" tickFormatter={(v) => v.slice(5, 10)} minTickGap={20} />
                      <YAxis stroke="#94a3b8" tickFormatter={(v) => fmt(v, 0)} />
                      <Tooltip contentStyle={{ backgroundColor: "#0f172a", borderColor: "#334155" }} />
                      <Legend />
                      <Area type="monotone" dataKey="p95" name="P95" stroke="#34d399" fill="#34d399" fillOpacity={0.05} dot={false} />
                      <Area type="monotone" dataKey="p75" name="P75" stroke="#60a5fa" fill="#60a5fa" fillOpacity={0.05} dot={false} />
                      <Line type="monotone" dataKey="p50" name="Mediana" stroke="#fbbf24" strokeWidth={2} dot={false} />
                      <Line type="monotone" dataKey="p25" name="P25" stroke="#a78bfa" strokeWidth={1} dot={false} />
                      <Line type="monotone" dataKey="p5" name="P5" stroke="#f87171" strokeWidth={1} dot={false} />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function SignalCard({ signal }: { signal: TradingSignal }) {
  if (signal.error) {
    return (
      <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 p-4 text-rose-200">
        <div className="font-medium">{signal.ticker}</div>
        <div className="text-sm">{signal.error}</div>
      </div>
    );
  }
  const ind = signal.indicators;
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-4">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-3">
          <div className={`rounded-md px-2 py-1 text-xs font-semibold ${signalColor(signal.signal)}`}>
            {signal.signal.toUpperCase()}
          </div>
          <span className="font-semibold text-white">{signal.ticker}</span>
          <span className="text-xs text-slate-400">
            Confiança {signal.confidence}% · {signal.time_horizon} · {signal.source === "llm" ? "IA (cloud)" : "heurística"}
          </span>
        </div>
        <div className="text-xs text-slate-400">
          RSI {fmt(ind.rsi14, 1)} · MACD {fmt(ind.macd, 2)} · SMA20 {fmt(ind.sma20)}
        </div>
      </div>
      <p className="mt-2 text-sm text-slate-300">{signal.rationale}</p>
      {(signal.stop_loss || signal.take_profit) && (
        <div className="mt-2 flex gap-4 text-xs">
          {signal.stop_loss != null && (
            <span className="text-rose-400">
              Stop loss: {fmt(signal.stop_loss)} $
            </span>
          )}
          {signal.take_profit != null && (
            <span className="text-emerald-400">
              Take profit: {fmt(signal.take_profit)} $
            </span>
          )}
        </div>
      )}
    </div>
  );
}

function classNames(...c: Array<string | false | null | undefined>) {
  return c.filter(Boolean).join(" ");
}
