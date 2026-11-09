/**
 * Gráficos de performance e risco do módulo de portfólio.
 *
 * Todos os números vêm de um único pedido (`/portfolio/timeseries`), que devolve
 * as séries normalizadas de **todos** os ativos do escopo e as métricas
 * derivadas (drawdown, volatilidade móvel, correlação, histograma de retornos e
 * contribuição para o retorno). Assim o browser não faz N pedidos ao Yahoo.
 */
import { useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { PortfolioTimeseriesResponse } from "../../portfolioApi";

/** Paleta com cor distinta para carteiras de 15+ ativos. */
export const SERIES_COLORS = [
  "#34d399", "#60a5fa", "#f87171", "#fbbf24", "#a78bfa",
  "#22d3ee", "#f472b6", "#a3e635", "#fb923c", "#38bdf8",
  "#c084fc", "#4ade80", "#facc15", "#fda4af", "#2dd4bf",
  "#93c5fd", "#fca5a5", "#d9f99d", "#fdba74", "#67e8f9",
];

const PORTFOLIO_COLOR = "#e2e8f0";

export function seriesColor(index: number): string {
  return SERIES_COLORS[index % SERIES_COLORS.length];
}

function fmtPct(value?: number | null, digits = 2): string {
  if (value == null || Number.isNaN(value)) return "—";
  return `${value > 0 ? "+" : ""}${value.toFixed(digits)}%`;
}

function fmtNum(value?: number | null, digits = 2): string {
  if (value == null || Number.isNaN(value)) return "—";
  return value.toLocaleString("pt-PT", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

const TOOLTIP_STYLE = { backgroundColor: "#0f172a", borderColor: "#334155", fontSize: 12 };

type Row = { date: string } & Record<string, number | string>;

/** Converte `dates` + `series[]` na forma que o recharts consome. */
function useChartRows(data: PortfolioTimeseriesResponse | null, mode: "index" | "return", includePortfolio: boolean) {
  return useMemo<Row[]>(() => {
    if (!data?.dates?.length) return [];
    const shift = mode === "return" ? 100 : 0;
    return data.dates.map((date, i) => {
      const row: Row = { date };
      for (const serie of data.series) {
        const value = serie.values[i];
        row[serie.ticker] = value == null ? Number.NaN : Number((value - shift).toFixed(3));
      }
      if (includePortfolio) {
        const value = data.portfolio.values[i];
        row.__portfolio = value == null ? Number.NaN : Number((value - shift).toFixed(3));
      }
      return row;
    });
  }, [data, mode, includePortfolio]);
}

// ---------------------------------------------------------------------------
// Performance normalizada (todos os ativos)
// ---------------------------------------------------------------------------
export function PortfolioPerformanceChart({ data }: { data: PortfolioTimeseriesResponse | null }) {
  const [mode, setMode] = useState<"index" | "return">("index");
  const [includePortfolio, setIncludePortfolio] = useState(true);
  const [hidden, setHidden] = useState<Record<string, boolean>>({});
  const rows = useChartRows(data, mode, includePortfolio);

  if (!data?.series?.length) return null;

  const toggle = (ticker: string) =>
    setHidden((current) => ({ ...current, [ticker]: !current[ticker] }));

  return (
    <section className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-400">
            Performance normalizada
          </h2>
          <p className="mt-0.5 text-xs text-slate-500">
            {data.series.length} ativos · {data.period} · base 100 no início do período · clique na legenda para
            isolar
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex rounded-md border border-slate-700 bg-slate-900 p-0.5">
            {([
              { id: "index", label: "Base 100" },
              { id: "return", label: "Variação %" },
            ] as const).map((option) => (
              <button
                key={option.id}
                onClick={() => setMode(option.id)}
                aria-pressed={mode === option.id}
                className={[
                  "rounded px-2.5 py-1 text-xs font-medium transition",
                  mode === option.id ? "bg-emerald-600 text-white" : "text-slate-400 hover:text-slate-200",
                ].join(" ")}
              >
                {option.label}
              </button>
            ))}
          </div>
          <button
            onClick={() => setIncludePortfolio((value) => !value)}
            aria-pressed={includePortfolio}
            className={[
              "rounded-md border px-2.5 py-1 text-xs font-medium transition",
              includePortfolio
                ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-300"
                : "border-slate-700 text-slate-400 hover:text-slate-200",
            ].join(" ")}
          >
            Carteira
          </button>
        </div>
      </div>

      <div className="h-[380px]">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={rows} margin={{ top: 4, right: 12, bottom: 0, left: -12 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,0.12)" />
            <XAxis
              dataKey="date"
              stroke="#94a3b8"
              fontSize={11}
              tickFormatter={(value: string) => value.slice(5)}
              minTickGap={40}
            />
            <YAxis
              stroke="#94a3b8"
              fontSize={11}
              domain={["auto", "auto"]}
              tickFormatter={(value: number) => (mode === "return" ? `${value}%` : String(Math.round(value)))}
            />
            <Tooltip
              contentStyle={TOOLTIP_STYLE}
              labelFormatter={(label) => String(label)}
              formatter={(value: unknown) => (typeof value === "number" ? fmtNum(value) : "—")}
            />
            <Legend
              onClick={(payload) => {
                const key = String((payload as { dataKey?: string })?.dataKey ?? "");
                if (key) toggle(key);
              }}
              wrapperStyle={{ fontSize: 11, cursor: "pointer", paddingTop: 6 }}
            />
            {mode === "return" && <ReferenceLine y={0} stroke="rgba(148,163,184,0.5)" strokeDasharray="4 4" />}
            {includePortfolio && (
              <Line
                type="monotone"
                dataKey="__portfolio"
                name="Carteira"
                stroke={PORTFOLIO_COLOR}
                strokeWidth={2.5}
                dot={false}
                hide={Boolean(hidden.__portfolio)}
              />
            )}
            {data.series.map((serie, index) => (
              <Line
                key={serie.ticker}
                type="monotone"
                dataKey={serie.ticker}
                name={serie.ticker}
                stroke={seriesColor(index)}
                strokeWidth={1.4}
                strokeOpacity={0.85}
                dot={false}
                hide={Boolean(hidden[serie.ticker])}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Drawdown (underwater) — risco
// ---------------------------------------------------------------------------
export function PortfolioDrawdownChart({ data }: { data: PortfolioTimeseriesResponse | null }) {
  const [showAssets, setShowAssets] = useState(false);

  const rows = useMemo<Row[]>(() => {
    if (!data?.dates?.length) return [];
    return data.dates.map((date, i) => {
      const row: Row = { date };
      const value = data.portfolio.drawdown[i];
      row.__portfolio = value == null ? Number.NaN : value;
      if (showAssets) {
        for (const serie of data.series) {
          const assetValue = serie.drawdown[i];
          row[serie.ticker] = assetValue == null ? Number.NaN : assetValue;
        }
      }
      return row;
    });
  }, [data, showAssets]);

  if (!data?.dates?.length) return null;

  return (
    <section className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-400">
            Drawdown (queda face ao topo)
          </h2>
          <p className="mt-0.5 text-xs text-slate-500">
            Máximo da carteira: {fmtPct(data.portfolio.max_drawdown_pct)}
          </p>
        </div>
        <button
          onClick={() => setShowAssets((value) => !value)}
          aria-pressed={showAssets}
          className={[
            "rounded-md border px-2.5 py-1 text-xs font-medium transition",
            showAssets
              ? "border-rose-500/40 bg-rose-500/10 text-rose-300"
              : "border-slate-700 text-slate-400 hover:text-slate-200",
          ].join(" ")}
        >
          {showAssets ? "Só carteira" : "Ver ativos"}
        </button>
      </div>
      <div className="h-[260px]">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={rows} margin={{ top: 4, right: 12, bottom: 0, left: -12 }}>
            <defs>
              <linearGradient id="dd-fill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#f87171" stopOpacity={0.05} />
                <stop offset="100%" stopColor="#f87171" stopOpacity={0.35} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,0.12)" />
            <XAxis
              dataKey="date"
              stroke="#94a3b8"
              fontSize={11}
              tickFormatter={(value: string) => value.slice(5)}
              minTickGap={40}
            />
            <YAxis
              stroke="#94a3b8"
              fontSize={11}
              tickFormatter={(value: number) => `${value.toFixed(0)}%`}
            />
            <Tooltip
              contentStyle={TOOLTIP_STYLE}
              formatter={(value: unknown) => (typeof value === "number" ? fmtPct(value) : "—")}
            />
            <ReferenceLine y={0} stroke="rgba(148,163,184,0.4)" />
            <Area
              type="monotone"
              dataKey="__portfolio"
              name="Carteira"
              stroke="#f87171"
              strokeWidth={2}
              fill="url(#dd-fill)"
              dot={false}
            />
            {showAssets &&
              data.series.map((serie, index) => (
                <Line
                  key={serie.ticker}
                  type="monotone"
                  dataKey={serie.ticker}
                  name={serie.ticker}
                  stroke={seriesColor(index)}
                  strokeWidth={1}
                  strokeOpacity={0.6}
                  dot={false}
                />
              ))}
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Volatilidade móvel anualizada — risco
// ---------------------------------------------------------------------------
export function PortfolioRollingVolatilityChart({ data }: { data: PortfolioTimeseriesResponse | null }) {
  const [selected, setSelected] = useState<string>("");

  const rows = useMemo<Row[]>(() => {
    if (!data?.dates?.length) return [];
    const asset = selected ? data.rolling_volatility.by_ticker[selected] : null;
    return data.dates.map((date, i) => {
      const row: Row = { date };
      const portfolioValue = data.rolling_volatility.portfolio[i];
      row.__portfolio = portfolioValue == null ? Number.NaN : portfolioValue;
      if (asset) {
        const value = asset[i];
        row.__asset = value == null ? Number.NaN : value;
      }
      return row;
    });
  }, [data, selected]);

  if (!data?.dates?.length) return null;

  return (
    <section className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-400">
            Volatilidade móvel ({data.rolling_volatility.window} sessões)
          </h2>
          <p className="mt-0.5 text-xs text-slate-500">
            Anualizada · carteira {fmtPct(data.portfolio.volatility_pct)}
          </p>
        </div>
        <select
          value={selected}
          onChange={(event) => setSelected(event.target.value)}
          className="rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-200"
          aria-label="Comparar ativo na volatilidade móvel"
        >
          <option value="">Só carteira</option>
          {data.tickers.map((ticker) => (
            <option key={ticker} value={ticker}>
              {ticker}
            </option>
          ))}
        </select>
      </div>
      <div className="h-[240px]">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={rows} margin={{ top: 4, right: 12, bottom: 0, left: -12 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,0.12)" />
            <XAxis
              dataKey="date"
              stroke="#94a3b8"
              fontSize={11}
              tickFormatter={(value: string) => value.slice(5)}
              minTickGap={40}
            />
            <YAxis stroke="#94a3b8" fontSize={11} tickFormatter={(value: number) => `${value.toFixed(0)}%`} />
            <Tooltip
              contentStyle={TOOLTIP_STYLE}
              formatter={(value: unknown) => (typeof value === "number" ? fmtPct(value) : "—")}
            />
            <Legend wrapperStyle={{ fontSize: 11, paddingTop: 6 }} />
            <Line
              type="monotone"
              dataKey="__portfolio"
              name="Carteira"
              stroke="#22d3ee"
              strokeWidth={2}
              dot={false}
              connectNulls
            />
            {selected && (
              <Line
                type="monotone"
                dataKey="__asset"
                name={selected}
                stroke="#fbbf24"
                strokeWidth={1.5}
                dot={false}
                connectNulls
              />
            )}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Correlação entre ativos — risco / diversificação
// ---------------------------------------------------------------------------
export function PortfolioCorrelationHeatmap({ data }: { data: PortfolioTimeseriesResponse | null }) {
  if (!data?.correlation?.tickers?.length) return null;
  const { tickers, matrix } = data.correlation;

  const cellColor = (value: number) => {
    const clamped = Math.max(-1, Math.min(1, value));
    if (clamped >= 0) return `rgba(248, 113, 113, ${0.08 + clamped * 0.62})`;
    return `rgba(52, 211, 153, ${0.08 + Math.abs(clamped) * 0.62})`;
  };

  return (
    <section className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
      <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-400">
        Correlação de retornos diários
      </h2>
      <p className="mt-0.5 mb-3 text-xs text-slate-500">
        Verde = movem-se em sentidos opostos (diversifica) · vermelho = movem-se juntos (concentra risco)
      </p>
      <div className="-mx-1 overflow-x-auto px-1 pb-2">
        <table className="border-separate border-spacing-0.5 text-[11px]">
          <thead>
            <tr>
              <th className="sticky left-0 z-10 bg-slate-900/40 px-1" />
              {tickers.map((ticker) => (
                <th key={ticker} className="px-1 pb-1 font-medium text-slate-500">
                  {ticker.length > 6 ? `${ticker.slice(0, 6)}…` : ticker}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {matrix.map((row, i) => (
              <tr key={tickers[i]}>
                <th className="sticky left-0 z-10 whitespace-nowrap bg-slate-900/40 py-0.5 pr-2 text-right font-medium text-slate-400">
                  {tickers[i]}
                </th>
                {row.map((value, j) => (
                  <td
                    key={`${tickers[i]}-${tickers[j]}`}
                    title={`${tickers[i]} ↔ ${tickers[j]}: ${fmtNum(value)}`}
                    style={{ backgroundColor: cellColor(value) }}
                    className="h-7 w-11 rounded text-center text-slate-100"
                  >
                    {value.toFixed(2)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Distribuição dos retornos diários + VaR — risco
// ---------------------------------------------------------------------------
export function PortfolioReturnsHistogram({ data }: { data: PortfolioTimeseriesResponse | null }) {
  if (!data?.histogram?.counts?.length) return null;
  const { histogram, stats } = data;

  const rows = histogram.center.map((center, index) => ({
    center,
    label: `${center.toFixed(1)}%`,
    count: histogram.counts[index] ?? 0,
    negative: center < 0,
  }));

  return (
    <section className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
      <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-400">
        Distribuição dos retornos diários
      </h2>
      <p className="mt-0.5 mb-3 text-xs text-slate-500">
        {stats.observations} sessões · média {fmtPct(histogram.mean_pct)} · desvio {fmtPct(histogram.std_pct)} · VaR 95%{" "}
        {fmtPct(stats.var_95_pct)} · CVaR 95% {fmtPct(stats.cvar_95_pct)}
      </p>
      <div className="h-[240px]">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={rows} margin={{ top: 4, right: 12, bottom: 0, left: -12 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,0.12)" vertical={false} />
            <XAxis dataKey="label" stroke="#94a3b8" fontSize={10} minTickGap={24} />
            <YAxis stroke="#94a3b8" fontSize={11} allowDecimals={false} />
            <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(value: unknown) => `${value} sessões`} />
            <ReferenceLine x={`${stats.var_95_pct.toFixed(1)}%`} stroke="#fbbf24" strokeDasharray="4 4" />
            <Bar dataKey="count" name="Sessões" radius={[3, 3, 0, 0]}>
              {rows.map((row) => (
                <Cell key={row.label} fill={row.negative ? "#f87171" : "#34d399"} fillOpacity={0.75} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div className="mt-2 flex flex-wrap gap-4 text-xs text-slate-400">
        <span>Dias positivos: <span className="text-emerald-400">{fmtNum(stats.positive_days_pct, 1)}%</span></span>
        <span>Melhor dia: <span className="text-emerald-400">{fmtPct(stats.best_day.pct)}</span> ({stats.best_day.date})</span>
        <span>Pior dia: <span className="text-rose-400">{fmtPct(stats.worst_day.pct)}</span> ({stats.worst_day.date})</span>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Contribuição de cada ativo para o retorno do período — performance
// ---------------------------------------------------------------------------
export function PortfolioContributionChart({ data }: { data: PortfolioTimeseriesResponse | null }) {
  if (!data?.contribution?.length) return null;
  const rows = [...data.contribution].sort((a, b) => b.contribution_pct - a.contribution_pct);

  return (
    <section className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
      <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-400">
        Contribuição para o retorno
      </h2>
      <p className="mt-0.5 mb-3 text-xs text-slate-500">
        Peso × retorno do ativo no período · total da carteira {fmtPct(data.portfolio.return_pct)}
      </p>
      <div style={{ height: Math.max(220, rows.length * 26) }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={rows} layout="vertical" margin={{ top: 0, right: 16, bottom: 0, left: 8 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,0.12)" horizontal={false} />
            <XAxis type="number" stroke="#94a3b8" fontSize={10} tickFormatter={(value: number) => `${value}%`} />
            <YAxis type="category" dataKey="ticker" stroke="#94a3b8" fontSize={11} width={76} />
            <Tooltip
              contentStyle={TOOLTIP_STYLE}
              formatter={(value: unknown) => (typeof value === "number" ? fmtPct(value) : "—")}
            />
            <ReferenceLine x={0} stroke="rgba(148,163,184,0.5)" />
            <Bar dataKey="contribution_pct" name="Contribuição" radius={[0, 3, 3, 0]}>
              {rows.map((row) => (
                <Cell key={row.ticker} fill={row.contribution_pct >= 0 ? "#34d399" : "#f87171"} fillOpacity={0.8} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}
