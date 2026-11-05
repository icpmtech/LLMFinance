import { useEffect, useState } from "react";
import { Sparkles, RefreshCw, TrendingUp, TrendingDown, Minus } from "lucide-react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceArea,
} from "recharts";
import { getPortfolioForecast, type PortfolioForecastResponse, type ForecastPoint, type ForecastSeries } from "../portfolioApi";
import { PortfolioLoading } from "../components/portfolio/PortfolioLoading";
import { PortfolioNewsStrip } from "../components/portfolio/PortfolioNewsStrip";

export function PortfolioForecastPage() {
  const [data, setData] = useState<PortfolioForecastResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [days, setDays] = useState(30);
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await getPortfolioForecast({ future_days: days, use_sentiment: false });
      setData(result);
      setSelectedTicker((prev) => prev || (result.forecasts[0]?.ticker ?? null));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao carregar previsões");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, [days]);

  const selected = data?.forecasts.find((f) => f.ticker === selectedTicker);

  const chartData = useChartData(selected);

  return (
    <div className="min-h-screen bg-[#0b0d10] text-slate-200 p-4 md:p-6">
      <div className="mx-auto max-w-7xl space-y-6">
        <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
          <div className="flex items-center gap-3">
            <div className="rounded-lg bg-violet-500/10 p-2">
              <Sparkles className="h-6 w-6 text-violet-400" />
            </div>
            <div>
              <h1 className="text-2xl font-semibold text-white">Antecipar o futuro</h1>
              <p className="text-sm text-slate-400">Previsões ARIMA de preço com bandas de confiança e notícias de contexto.</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <select
              value={days}
              onChange={(e) => setDays(Number(e.target.value))}
              className="rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200"
            >
              {[7, 14, 30, 60, 90].map((d) => (
                <option key={d} value={d}>{d} dias à frente</option>
              ))}
            </select>
            <button
              onClick={load}
              disabled={loading}
              className="inline-flex items-center gap-2 rounded-md bg-slate-800 px-3 py-2 text-sm font-medium text-slate-200 hover:bg-slate-700 disabled:opacity-50"
            >
              <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
              Atualizar
            </button>
          </div>
        </div>

        {loading && !data ? (
          <PortfolioLoading />
        ) : error ? (
          <div className="rounded-lg border border-rose-900/50 bg-rose-950/30 p-4 text-rose-200">{error}</div>
        ) : data ? (
          <>
            <div className="flex flex-wrap gap-2">
              {data.forecasts.map((f) => (
                <button
                  key={f.ticker}
                  onClick={() => setSelectedTicker(f.ticker)}
                  className={[
                    "rounded-full px-3 py-1 text-sm font-medium transition",
                    selectedTicker === f.ticker
                      ? "bg-violet-600 text-white"
                      : "bg-slate-800 text-slate-300 hover:bg-slate-700",
                  ].join(" ")}
                >
                  {f.ticker}
                  {f.error && <span className="ml-1 text-rose-400">!</span>}
                </button>
              ))}
            </div>

            <div className="grid gap-6 lg:grid-cols-3">
              <div className="lg:col-span-2 space-y-6">
                {selected && (
                  <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
                    <div className="mb-4 flex items-center justify-between">
                      <div>
                        <h2 className="text-lg font-semibold text-white">{selected.company_name || selected.ticker}</h2>
                        <p className="text-sm text-slate-400">
                          Previsão ARIMA · {data.future_days} dias · RMSE {selected.rmse?.toFixed(3) ?? "-"} · MAPE{" "}
                          {selected.mape?.toFixed(2) ?? "-"}%
                        </p>
                      </div>
                      <ForecastSignal forecast={selected.forecast} />
                    </div>

                    <div className="h-[420px]">
                      <ResponsiveContainer width="100%" height="100%">
                        <LineChart data={chartData}>
                          <CartesianGrid stroke="rgba(148,163,184,0.08)" />
                          <XAxis dataKey="date" stroke="#64748b" tick={{ fontSize: 10 }} />
                          <YAxis stroke="#64748b" tick={{ fontSize: 10 }} domain={["auto", "auto"]} />
                          <Tooltip
                            contentStyle={{ backgroundColor: "#0f172a", borderColor: "#1e293b" }}
                            itemStyle={{ color: "#e2e8f0" }}
                            labelStyle={{ color: "#94a3b8" }}
                          />
                          <ReferenceArea
                            x1={chartData.find((d) => d.isForecast)?.date}
                            x2={chartData[chartData.length - 1]?.date}
                            fill="rgba(139,92,246,0.08)"
                          />
                          <Line
                            type="monotone"
                            dataKey="price"
                            stroke="#8b5cf6"
                            strokeWidth={2}
                            dot={false}
                            name="Preço"
                          />
                          <Line
                            type="monotone"
                            dataKey="upper"
                            stroke="rgba(139,92,246,0.4)"
                            strokeDasharray="4 4"
                            dot={false}
                            name="Limite superior"
                          />
                          <Line
                            type="monotone"
                            dataKey="lower"
                            stroke="rgba(139,92,246,0.4)"
                            strokeDasharray="4 4"
                            dot={false}
                            name="Limite inferior"
                          />
                        </LineChart>
                      </ResponsiveContainer>
                    </div>
                  </div>
                )}

                {selected?.error && (
                  <div className="rounded-lg border border-rose-900/50 bg-rose-950/30 p-4 text-rose-200">
                    {selected.error}
                  </div>
                )}
              </div>

              <div className="space-y-6">
                <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
                  <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-slate-400">
                    Notícias de contexto
                  </h2>
                  <PortfolioNewsStrip news={data.news} />
                </div>

                <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
                  <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-slate-400">
                    Previsões resumidas
                  </h2>
                  <div className="space-y-2">
                    {data.forecasts.map((f) => {
                      const lastPrice = f.series.findLast((s) => s.type === "history")?.value;
                      const lastForecast = f.forecast[f.forecast.length - 1]?.price;
                      const change = lastPrice && lastForecast ? (lastForecast / lastPrice - 1) * 100 : null;
                      return (
                        <div key={f.ticker} className="flex items-center justify-between rounded-md bg-slate-800/50 p-2">
                          <span className="text-sm font-medium text-slate-200">{f.ticker}</span>
                          <span
                            className={`text-sm font-medium ${
                              change === null ? "text-slate-400" : change >= 0 ? "text-emerald-400" : "text-rose-400"
                            }`}
                          >
                            {change !== null ? `${change >= 0 ? "+" : ""}${change.toFixed(2)}%` : "-"}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                </div>
              </div>
            </div>
          </>
        ) : null}
      </div>
    </div>
  );
}

function useChartData(selected?: { forecast: ForecastPoint[]; series: ForecastSeries[] }) {
  if (!selected) return [];
  const history = selected.series
    .filter((s) => s.type === "history" && typeof s.value === "number")
    .map((s) => ({ date: formatDate(s.date), price: s.value, lower: undefined, upper: undefined, isForecast: false }));
  const forecast = selected.forecast.map((p) => ({
    date: formatDate(p.date),
    price: p.price,
    lower: p.lower,
    upper: p.upper,
    isForecast: true,
  }));
  return [...history, ...forecast];
}

function formatDate(value: string) {
  if (!value) return "";
  const d = new Date(value);
  if (isNaN(d.getTime())) return value.slice(0, 10);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function ForecastSignal({ forecast }: { forecast: ForecastPoint[] }) {
  const first = forecast[0]?.price;
  const last = forecast[forecast.length - 1]?.price;
  if (!first || !last) return null;
  const change = (last / first - 1) * 100;
  const Icon = change > 0 ? TrendingUp : change < 0 ? TrendingDown : Minus;
  const color = change > 0 ? "text-emerald-400" : change < 0 ? "text-rose-400" : "text-slate-400";
  return (
    <div className={`flex items-center gap-2 rounded-lg bg-slate-800 px-3 py-1.5 ${color}`}>
      <Icon className="h-4 w-4" />
      <span className="text-sm font-semibold">{change >= 0 ? "+" : ""}
        {change.toFixed(2)}%
      </span>
    </div>
  );
}
