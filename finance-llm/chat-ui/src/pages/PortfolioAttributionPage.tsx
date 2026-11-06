import { useCallback, useEffect, useState } from "react";
import { PieChart, RefreshCw, ArrowUpRight, ArrowDownRight } from "lucide-react";
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Pie,
  Cell,
} from "recharts";
import { getPortfolioAttribution, type PortfolioAttributionResponse } from "../portfolioApi";
import { usePortfolioScope } from "../portfolioScope";
import { PortfolioScopeBar } from "../components/portfolio/PortfolioScopeBar";
import { PortfolioLoading } from "../components/portfolio/PortfolioLoading";

const COLORS = ["#34d399", "#60a5fa", "#f87171", "#fbbf24", "#a78bfa", "#22d3ee", "#f472b6", "#94a3b8"];

export function PortfolioAttributionPage() {
  const scope = usePortfolioScope();
  const portfolioId = scope.portfolioId;

  const [data, setData] = useState<PortfolioAttributionResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (scope.loading) return;
    setLoading(true);
    setError(null);
    try {
      const result = await getPortfolioAttribution({ portfolio_id: portfolioId ?? undefined });
      setData(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao carregar attribution");
    } finally {
      setLoading(false);
    }
  }, [portfolioId, scope.loading]);

  useEffect(() => {
    void load();
  }, [load]);

  const sectorData =
    data?.sectors.map((s, i) => ({
      name: s.sector,
      allocation: Number((s.allocation_effect * 100).toFixed(2)),
      selection: Number((s.selection_effect * 100).toFixed(2)),
      total: Number((s.total_effect * 100).toFixed(2)),
      color: COLORS[i % COLORS.length],
    })) ?? [];

  const pieData =
    data?.sectors.map((s, i) => ({
      name: s.sector,
      value: Number((s.portfolio_weight * 100).toFixed(2)),
      color: COLORS[i % COLORS.length],
    })) ?? [];

  return (
    <div className="min-h-screen bg-[#0b0d10] text-slate-200 p-4 md:p-6">
      <div className="mx-auto max-w-7xl space-y-6">
        <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
          <div className="flex items-center gap-3">
            <div className="rounded-lg bg-cyan-500/10 p-2">
              <PieChart className="h-6 w-6 text-cyan-400" />
            </div>
            <div>
              <h1 className="text-2xl font-semibold text-white">Ver o que impulsiona retornos</h1>
              <p className="text-sm text-slate-400">
                Attribution Brinson: alocação por setor, selecção de títulos e contributors.
              </p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <PortfolioScopeBar scope={scope} />
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
              <Card label="Retorno carteira" value={`${data.portfolio_return.toFixed(2)}%`} />
              <Card label="Active return" value={`${data.active_return >= 0 ? "+" : ""}${data.active_return.toFixed(2)}%`} />
              <Card label="Setores" value={String(data.sectors.length)} />
              <Card label="Período" value={data.period} />
            </div>

            <div className="grid gap-6 lg:grid-cols-2">
              <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
                <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-slate-400">
                  Efeito de alocação vs selecção por setor
                </h2>
                <div className="h-[360px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={sectorData}>
                      <CartesianGrid stroke="rgba(148,163,184,0.08)" />
                      <XAxis dataKey="name" stroke="#64748b" tick={{ fontSize: 10 }} />
                      <YAxis stroke="#64748b" tick={{ fontSize: 10 }} />
                      <Tooltip
                        contentStyle={{ backgroundColor: "#0f172a", borderColor: "#1e293b" }}
                        itemStyle={{ color: "#e2e8f0" }}
                        formatter={(value) => `${Number(value).toFixed(2)}%`}
                      />
                      <Bar dataKey="allocation" stackId="a" fill="#22d3ee" name="Alocação" />
                      <Bar dataKey="selection" stackId="a" fill="#f472b6" name="Selecção" />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>

              <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
                <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-slate-400">
                  Peso da carteira por setor
                </h2>
                <div className="h-[360px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie data={pieData} dataKey="value" nameKey="name" outerRadius={120}>
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
              </div>
            </div>

            <div className="grid gap-6 lg:grid-cols-2">
              <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
                <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-emerald-400">
                  Top contributors
                </h2>
                <div className="space-y-2">
                  {data.top_contributors.slice(0, 10).map((c) => (
                    <div key={c.ticker} className="flex items-center justify-between rounded-md bg-slate-800/40 p-2">
                      <div>
                        <div className="text-sm font-medium text-slate-200">{c.ticker}</div>
                        <div className="text-xs text-slate-500">{c.name}</div>
                      </div>
                      <div className="flex items-center gap-3 text-sm">
                        <span className="text-slate-400">{(c.weight * 100).toFixed(1)}%</span>
                        <span className="flex items-center gap-1 font-medium text-emerald-400">
                          <ArrowUpRight className="h-3.5 w-3.5" />
                          +{c.contribution_pct.toFixed(2)}%
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
                <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-rose-400">
                  Bottom contributors
                </h2>
                <div className="space-y-2">
                  {data.bottom_contributors.slice(0, 10).map((c) => (
                    <div key={c.ticker} className="flex items-center justify-between rounded-md bg-slate-800/40 p-2">
                      <div>
                        <div className="text-sm font-medium text-slate-200">{c.ticker}</div>
                        <div className="text-xs text-slate-500">{c.name}</div>
                      </div>
                      <div className="flex items-center gap-3 text-sm">
                        <span className="text-slate-400">{(c.weight * 100).toFixed(1)}%</span>
                        <span className="flex items-center gap-1 font-medium text-rose-400">
                          <ArrowDownRight className="h-3.5 w-3.5" />
                          {c.contribution_pct.toFixed(2)}%
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
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
