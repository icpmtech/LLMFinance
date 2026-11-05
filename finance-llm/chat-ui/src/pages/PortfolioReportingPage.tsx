import { useEffect, useState } from "react";
import { FileText, Download, RefreshCw } from "lucide-react";
import { getPortfolioReporting, type PortfolioReportingResponse } from "../portfolioApi";
import { PortfolioLoading } from "../components/portfolio/PortfolioLoading";
import { PortfolioNewsStrip } from "../components/portfolio/PortfolioNewsStrip";

export function PortfolioReportingPage() {
  const [data, setData] = useState<PortfolioReportingResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const report = await getPortfolioReporting();
      setData(report);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao gerar relatório");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const downloadJson = () => {
    if (!data) return;
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `portfolio-report-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="min-h-screen bg-[#0b0d10] text-slate-200 p-4 md:p-6">
      <div className="mx-auto max-w-7xl space-y-6">
        <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
          <div className="flex items-center gap-3">
            <div className="rounded-lg bg-emerald-500/10 p-2">
              <FileText className="h-6 w-6 text-emerald-400" />
            </div>
            <div>
              <h1 className="text-2xl font-semibold text-white">Relatórios de carteira</h1>
              <p className="text-sm text-slate-400">Dados agregados de sumário, attribution, risco e otimização.</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={load}
              disabled={loading}
              className="inline-flex items-center gap-2 rounded-md bg-slate-800 px-3 py-2 text-sm font-medium text-slate-200 hover:bg-slate-700 disabled:opacity-50"
            >
              <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
              Atualizar
            </button>
            <button
              onClick={downloadJson}
              disabled={!data}
              className="inline-flex items-center gap-2 rounded-md bg-emerald-600/20 px-3 py-2 text-sm font-medium text-emerald-300 hover:bg-emerald-600/30 disabled:opacity-50"
            >
              <Download className="h-4 w-4" />
              JSON
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
              <Card label="Valor" value={`${data.currency} ${data.summary.portfolio_value.toLocaleString()}`} />
              <Card
                label="Variação hoje"
                value={`${data.summary.portfolio_change_pct >= 0 ? "+" : ""}${data.summary.portfolio_change_pct.toFixed(2)}%`}
                positive={data.summary.portfolio_change_pct >= 0}
              />
              <Card label="Volatilidade" value={`${data.risk.portfolio_volatility_pct.toFixed(2)}%`} />
              <Card label="Ratio de Sharpe" value={data.risk.sharpe_ratio.toFixed(2)} />
            </div>

            <div className="grid gap-6 lg:grid-cols-3">
              <div className="lg:col-span-2 space-y-6">
                <Section title="Alocação actual" emoji="📊">
                  <div className="space-y-2">
                    {data.summary.tickers.map((t, i) => (
                      <div key={t.ticker} className="flex items-center gap-3">
                        <div className="w-24 text-sm text-slate-300">{t.ticker}</div>
                        <div className="flex-1 h-2 rounded bg-slate-800">
                          <div
                            className="h-2 rounded bg-emerald-500"
                            style={{ width: `${(data.summary.weights[i] ?? 0) * 100}%` }}
                          />
                        </div>
                        <div className="w-16 text-right text-sm text-slate-400">
                          {((data.summary.weights[i] ?? 0) * 100).toFixed(1)}%
                        </div>
                      </div>
                    ))}
                  </div>
                </Section>

                <Section title="Attribution por setor" emoji="🎯">
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead className="text-left text-xs uppercase text-slate-500">
                        <tr>
                          <th className="py-2">Setor</th>
                          <th className="py-2 text-right">Peso PF</th>
                          <th className="py-2 text-right">Retorno PF</th>
                          <th className="py-2 text-right">Alocação</th>
                          <th className="py-2 text-right">Selecção</th>
                          <th className="py-2 text-right">Total</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-800">
                        {data.attribution.sectors.map((s) => (
                          <tr key={s.sector}>
                            <td className="py-2 text-slate-300">{s.sector}</td>
                            <td className="py-2 text-right text-slate-400">{(s.portfolio_weight * 100).toFixed(1)}%</td>
                            <td className={`py-2 text-right ${s.portfolio_return >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                              {s.portfolio_return >= 0 ? "+" : ""}
                              {(s.portfolio_return * 100).toFixed(2)}%
                            </td>
                            <td className={`py-2 text-right ${s.allocation_effect >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                              {s.allocation_effect >= 0 ? "+" : ""}
                              {(s.allocation_effect * 100).toFixed(2)}%
                            </td>
                            <td className={`py-2 text-right ${s.selection_effect >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                              {s.selection_effect >= 0 ? "+" : ""}
                              {(s.selection_effect * 100).toFixed(2)}%
                            </td>
                            <td className={`py-2 text-right font-medium ${s.total_effect >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                              {s.total_effect >= 0 ? "+" : ""}
                              {(s.total_effect * 100).toFixed(2)}%
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </Section>

                <Section title="Top contributors" emoji="🚀">
                  <div className="space-y-2">
                    {data.attribution.top_contributors.slice(0, 10).map((c) => (
                      <div key={c.ticker} className="flex items-center gap-3">
                        <div className="w-24 text-sm text-slate-300">{c.ticker}</div>
                        <div className="flex-1 h-2 rounded bg-slate-800">
                          <div
                            className="h-2 rounded bg-emerald-500"
                            style={{ width: `${Math.min(Math.max(c.contribution_pct, 0), 100)}%` }}
                          />
                        </div>
                        <div className="w-24 text-right text-sm text-emerald-400">+{c.contribution_pct.toFixed(2)}%</div>
                      </div>
                    ))}
                  </div>
                </Section>
              </div>

              <div className="space-y-6">
                <Section title="Métricas de risco" emoji="⚠️">
                  <RiskMetric label="Volatilidade anual" value={`${data.risk.portfolio_volatility_pct.toFixed(2)}%`} />
                  <RiskMetric label="Beta vs S&P 500" value={data.risk.beta.toFixed(2)} />
                  <RiskMetric label="Tracking error" value={`${data.risk.tracking_error_pct.toFixed(2)}%`} />
                  <RiskMetric label="VaR 95% (dia)" value={`${data.risk.var_95_daily.toFixed(2)}%`} />
                  <RiskMetric label="CVaR 95% (dia)" value={`${data.risk.cvar_95_daily.toFixed(2)}%`} />
                  <RiskMetric label="Sharpe" value={data.risk.sharpe_ratio.toFixed(2)} />
                </Section>

                <Section title="Factor exposures" emoji="📈">
                  <div className="space-y-2">
                    {data.risk.factor_exposures.map((f) => (
                      <div key={f.factor} className="flex items-center justify-between">
                        <span className="text-sm text-slate-300">{f.factor} <span className="text-xs text-slate-500">({f.proxy})</span></span>
                        <span className={`text-sm font-medium ${f.exposure >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                          {f.exposure >= 0 ? "+" : ""}
                          {f.exposure.toFixed(2)}
                        </span>
                      </div>
                    ))}
                  </div>
                </Section>

                <Section title="Notícias" emoji="📰">
                  <PortfolioNewsStrip news={data.summary.news} />
                </Section>
              </div>
            </div>
          </>
        ) : null}
      </div>
    </div>
  );
}

function Card({ label, value, positive }: { label: string; value: string; positive?: boolean }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
      <div className="text-xs uppercase tracking-wider text-slate-500">{label}</div>
      <div className={`mt-2 text-xl font-semibold ${positive === true ? "text-emerald-400" : positive === false ? "text-rose-400" : "text-white"}`}>
        {value}
      </div>
    </div>
  );
}

function Section({ title, children, emoji }: { title: string; children: React.ReactNode; emoji?: string }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
      <h2 className="mb-4 text-sm font-semibold uppercase tracking-wider text-slate-400">
        {emoji && <span className="mr-2">{emoji}</span>}
        {title}
      </h2>
      {children}
    </div>
  );
}

function RiskMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between border-b border-slate-800 py-2 last:border-0">
      <span className="text-sm text-slate-400">{label}</span>
      <span className="text-sm font-medium text-white">{value}</span>
    </div>
  );
}
