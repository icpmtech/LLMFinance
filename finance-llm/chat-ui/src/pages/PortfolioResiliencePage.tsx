import { useEffect, useState } from "react";
import { ShieldAlert, RefreshCw, Target, SlidersHorizontal } from "lucide-react";
import {
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  Tooltip,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
} from "recharts";
import { getPortfolioResilience, type PortfolioOptimizeResponse } from "../portfolioApi";
import { PortfolioLoading } from "../components/portfolio/PortfolioLoading";

const COLORS = ["#34d399", "#60a5fa", "#f87171", "#fbbf24", "#a78bfa", "#22d3ee", "#f472b6"];

export function PortfolioResiliencePage() {
  const [data, setData] = useState<PortfolioOptimizeResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [objective, setObjective] = useState<"sharpe" | "risk" | "resilience" | "return">("sharpe");

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await getPortfolioResilience({ objective });
      setData(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao otimizar carteira");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, [objective]);

  const pieData =
    data?.tickers.map((t, i) => ({
      name: t.ticker,
      value: Number((data.optimal_weights[i] * 100).toFixed(2)),
      color: COLORS[i % COLORS.length],
    })) ?? [];

  const fundamentalData =
    data?.fundamental_scores.slice(0, 8).map((f) => ({
      name: f.ticker,
      score: f.score,
      eps: f.ltg_eps_growth * 100,
      sales: f.sales_growth * 100,
    })) ?? [];

  return (
    <div className="min-h-screen bg-[#0b0d10] text-slate-200 p-4 md:p-6">
      <div className="mx-auto max-w-7xl space-y-6">
        <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
          <div className="flex items-center gap-3">
            <div className="rounded-lg bg-amber-500/10 p-2">
              <ShieldAlert className="h-6 w-6 text-amber-400" />
            </div>
            <div>
              <h1 className="text-2xl font-semibold text-white">Construir portfólio resiliente</h1>
              <p className="text-sm text-slate-400">Otimização de pesos com restrições: maximizar Sharpe, retorno ou minimizar risco.</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <select
              value={objective}
              onChange={(e) => setObjective(e.target.value as any)}
              className="rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200"
            >
              <option value="sharpe">Maximizar Sharpe</option>
              <option value="return">Maximizar retorno</option>
              <option value="risk">Minimizar risco</option>
              <option value="resilience">Resiliência (min. vol)</option>
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
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <Card label="Retorno esperado (otimizado)" value={`${data.expected_return_annual.toFixed(2)}%`} />
              <Card label="Volatilidade esperada" value={`${data.expected_volatility.toFixed(2)}%`} />
              <Card label="Sharpe ratio" value={data.sharpe_ratio.toFixed(2)} />
              <Card label="Retorno actual" value={`${data.current_expected_return.toFixed(2)}%`} />
            </div>

            <div className="grid gap-6 lg:grid-cols-2">
              <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
                <div className="mb-3 flex items-center gap-2">
                  <Target className="h-5 w-5 text-amber-400" />
                  <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-400">
                    Alocação óptima
                  </h2>
                </div>
                <div className="h-[360px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie
                        data={pieData}
                        dataKey="value"
                        nameKey="name"
                        innerRadius={60}
                        outerRadius={110}
                        paddingAngle={2}
                      >
                        {pieData.map((entry, index) => (
                          <Cell key={`cell-${index}`} fill={entry.color} />
                        ))}
                      </Pie>
                      <Tooltip
                        contentStyle={{ backgroundColor: "#0f172a", borderColor: "#1e293b" }}
                        itemStyle={{ color: "#e2e8f0" }}
                        formatter={(value, name) => [`${Number(value).toFixed(1)}%`, String(name)]}
                      />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
                <div className="mt-2 grid grid-cols-2 gap-2">
                  {data.tickers.map((t, i) => (
                    <div key={t.ticker} className="flex items-center gap-2 text-sm">
                      <span
                        className="inline-block h-2 w-2 rounded-full"
                        style={{ backgroundColor: COLORS[i % COLORS.length] }}
                      />
                      <span className="text-slate-300">{t.ticker}</span>
                      <span className="ml-auto text-slate-500">{(data.optimal_weights[i] * 100).toFixed(1)}%</span>
                    </div>
                  ))}
                </div>
              </div>

              <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
                <div className="mb-3 flex items-center gap-2">
                  <SlidersHorizontal className="h-5 w-5 text-amber-400" />
                  <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-400">
                    Restrições da otimização
                  </h2>
                </div>
                <div className="space-y-3">
                  {data.constraints.map((c) => (
                    <div key={`${c.field}-${c.group}`} className="rounded-md bg-slate-800/50 p-3">
                      <div className="flex items-center justify-between">
                        <span className="text-sm font-medium text-slate-200">{c.field}</span>
                        <span className="text-xs text-slate-500">{c.group} · {c.unit}</span>
                      </div>
                      <div className="mt-2 flex items-center gap-2">
                        {c.min !== undefined && <span className="text-xs text-slate-400">Min {c.min}%</span>}
                        <div className="flex-1 h-2 rounded bg-slate-700">
                          <div
                            className="h-2 rounded bg-amber-500"
                            style={{
                              width: `${Math.min(Math.max((c.max / 40) * 100, 5), 100)}%`,
                            }}
                          />
                        </div>
                        <span className="text-xs text-slate-400">Max {c.max}%</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
              <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-slate-400">
                Score fundamental (LTG EPS & sales growth ajustado ao risco)
              </h2>
              <div className="h-[320px]">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={fundamentalData}>
                    <CartesianGrid stroke="rgba(148,163,184,0.08)" />
                    <XAxis dataKey="name" stroke="#64748b" tick={{ fontSize: 10 }} />
                    <YAxis stroke="#64748b" tick={{ fontSize: 10 }} />
                    <Tooltip
                      contentStyle={{ backgroundColor: "#0f172a", borderColor: "#1e293b" }}
                      itemStyle={{ color: "#e2e8f0" }}
                    />
                    <Bar dataKey="eps" stackId="a" fill="#34d399" name="LTG EPS growth %" />
                    <Bar dataKey="sales" stackId="a" fill="#60a5fa" name="Sales growth %" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          </>
        ) : null}
      </div>
    </div>
  );
}

function Card({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
      <div className="text-xs uppercase tracking-wider text-slate-500">{label}</div>
      <div className="mt-2 text-xl font-semibold text-white">{value}</div>
    </div>
  );
}
