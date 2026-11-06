import { useCallback, useEffect, useState } from "react";
import { BarChart3, RefreshCw, AlertTriangle } from "lucide-react";
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  Radar,
} from "recharts";
import { getPortfolioRisk, type PortfolioRiskResponse } from "../portfolioApi";
import { usePortfolioScope } from "../portfolioScope";
import { PortfolioScopeBar } from "../components/portfolio/PortfolioScopeBar";
import { PortfolioLoading } from "../components/portfolio/PortfolioLoading";

export function PortfolioRiskPage() {
  const scope = usePortfolioScope();
  const portfolioId = scope.portfolioId;

  const [data, setData] = useState<PortfolioRiskResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (scope.loading) return;
    setLoading(true);
    setError(null);
    try {
      const result = await getPortfolioRisk({ portfolio_id: portfolioId ?? undefined });
      setData(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao carregar risco");
    } finally {
      setLoading(false);
    }
  }, [portfolioId, scope.loading]);

  useEffect(() => {
    void load();
  }, [load]);

  const marginalData =
    data?.marginal_risk.slice(0, 10).map((m) => ({
      name: m.ticker,
      contribution: Number(m.risk_contribution_pct.toFixed(2)),
      volatility: Number((m.volatility * 100).toFixed(2)),
    })) ?? [];

  const radarData =
    data?.factor_exposures.map((f) => ({
      subject: f.factor,
      A: Number((f.exposure * 100).toFixed(2)),
      fullMark: 100,
    })) ?? [];

  return (
    <div className="min-h-screen bg-[#0b0d10] text-slate-200 p-4 md:p-6">
      <div className="mx-auto max-w-7xl space-y-6">
        <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
          <div className="flex items-center gap-3">
            <div className="rounded-lg bg-rose-500/10 p-2">
              <BarChart3 className="h-6 w-6 text-rose-400" />
            </div>
            <div>
              <h1 className="text-2xl font-semibold text-white">Controlar risco</h1>
              <p className="text-sm text-slate-400">Volatilidade, VaR, CVaR, beta, tracking error e exposição a factores.</p>
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
              <Card label="Volatilidade anual" value={`${data.portfolio_volatility_pct.toFixed(2)}%`} />
              <Card label="Beta vs S&P 500" value={data.beta.toFixed(2)} />
              <Card label="VaR 95% diário" value={`${data.var_95_daily.toFixed(2)}%`} />
              <Card label="Sharpe ratio" value={data.sharpe_ratio.toFixed(2)} />
            </div>

            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              <RiskTile label="Tracking error" value={`${data.tracking_error_pct.toFixed(2)}%`} />
              <RiskTile label="CVaR 95% diário" value={`${data.cvar_95_daily.toFixed(2)}%`} />
              <RiskTile label="Risco idiossincrático" value={`${data.idiosyncratic_risk_pct.toFixed(2)}%`} />
              <RiskTile label="Retorno esperado anual" value={`${data.expected_return_annual.toFixed(2)}%`} />
              <RiskTile label="Total active risk" value={`${data.total_active_risk_pct.toFixed(2)}%`} />
              <RiskTile label="VaR 99% diário" value={`${data.var_99_daily.toFixed(2)}%`} />
            </div>

            <div className="grid gap-6 lg:grid-cols-2">
              <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
                <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-slate-400">
                  Contribuição marginal ao risco
                </h2>
                <div className="h-[360px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={marginalData}>
                      <CartesianGrid stroke="rgba(148,163,184,0.08)" />
                      <XAxis dataKey="name" stroke="#64748b" tick={{ fontSize: 10 }} />
                      <YAxis stroke="#64748b" tick={{ fontSize: 10 }} />
                      <Tooltip
                        contentStyle={{ backgroundColor: "#0f172a", borderColor: "#1e293b" }}
                        itemStyle={{ color: "#e2e8f0" }}
                        formatter={(value, name) => [`${Number(value).toFixed(1)}%`, String(name)]}
                      />
                      <Bar dataKey="contribution" fill="#f43f5e" name="Contribuição ao risco %" />
                      <Bar dataKey="volatility" fill="#64748b" name="Volatilidade anual %" />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>

              <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
                <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-slate-400">
                  Exposição a factores
                </h2>
                <div className="h-[360px]">
                  {radarData.length > 2 ? (
                    <ResponsiveContainer width="100%" height="100%">
                      <RadarChart data={radarData}>
                        <PolarGrid stroke="rgba(148,163,184,0.15)" />
                        <PolarAngleAxis dataKey="subject" tick={{ fill: "#94a3b8", fontSize: 11 }} />
                        <PolarRadiusAxis angle={30} domain={[-100, 100]} tick={false} axisLine={false} />
                        <Radar
                          name="Exposição %"
                          dataKey="A"
                          stroke="#f43f5e"
                          fill="#f43f5e"
                          fillOpacity={0.35}
                        />
                      </RadarChart>
                    </ResponsiveContainer>
                  ) : (
                    <div className="flex h-full items-center justify-center text-slate-500">
                      Dados insuficientes para radar
                    </div>
                  )}
                </div>

                <div className="mt-4 space-y-2">
                  {data.factor_exposures.map((f) => (
                    <div key={f.factor} className="flex items-center justify-between text-sm">
                      <span className="text-slate-300">
                        {f.factor} <span className="text-xs text-slate-500">({f.proxy})</span>
                      </span>
                      <span className={`font-medium ${f.exposure >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                        {f.exposure >= 0 ? "+" : ""}
                        {(f.exposure * 100).toFixed(2)}%
                      </span>
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

function RiskTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center gap-3 rounded-lg border border-slate-800 bg-slate-900/40 p-4">
      <AlertTriangle className="h-5 w-5 text-rose-400" />
      <div>
        <div className="text-xs text-slate-500">{label}</div>
        <div className="text-lg font-semibold text-white">{value}</div>
      </div>
    </div>
  );
}
