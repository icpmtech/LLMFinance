import { useCallback, useEffect, useMemo, useState } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  ResponsiveContainer,
  CartesianGrid,
  ReferenceLine,
  Brush,
} from "recharts";
import {
  Search,
  Play,
  TrendingUp,
  Activity,
  BarChart3,
  Calendar,
  RotateCcw,
  Eye,
  EyeOff,
  Sparkles,
  ArrowLeft,
  Newspaper,
  Loader2,
} from "lucide-react";
import { runForecast, searchLocalTickers, getPlotUrl, analyzeSentiment } from "../api";
import type { ForecastRequest, ForecastResponse, ForecastSeries, SentimentBlendedResponse } from "../types";

const PERIODS = ["1y", "2y", "5y", "10y", "max"];
const BACKENDS: { value: "arima" | "kronos"; label: string }[] = [
  { value: "arima", label: "ARIMA" },
  { value: "kronos", label: "Kronos (fundational)" },
];
const DEFAULT_REQUEST: ForecastRequest = {
  ticker: "AAPL",
  future_days: 5,
  period: "5y",
  order: "2,1,2",
  train_ratio: 0.85,
  backend: "arima",
};

function formatDateLabel(value: string) {
  const d = new Date(value);
  return isNaN(d.getTime()) ? value : d.toLocaleDateString("pt-PT");
}

function formatNumber(n: number | undefined, digits = 2) {
  if (n === undefined || n === null || Number.isNaN(n)) return "—";
  return n.toLocaleString("pt-PT", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function classNames(...c: Array<string | false | null | undefined>) {
  return c.filter(Boolean).join(" ");
}

export function ForecastPage({ onSwitchView }: { onSwitchView?: () => void }) {
  const [request, setRequest] = useState<ForecastRequest>(DEFAULT_REQUEST);
  const [search, setSearch] = useState(DEFAULT_REQUEST.ticker);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [loadingTickers, setLoadingTickers] = useState(false);
  const [result, setResult] = useState<ForecastResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [showSummary, setShowSummary] = useState(false);
  const [useSentiment, setUseSentiment] = useState(false);
  const [sentiment, setSentiment] = useState<SentimentBlendedResponse | null>(null);
  const [loadingSentiment, setLoadingSentiment] = useState(false);

  const [visibleSeries, setVisibleSeries] = useState<Record<string, boolean>>({
    train: true,
    test: true,
    forecast: true,
    upper: true,
    lower: true,
  });
  const [startDate, setStartDate] = useState<string>("");
  const [endDate, setEndDate] = useState<string>("");

  const fetchSuggestions = useCallback(async (q: string) => {
    if (q.length < 2) {
      setSuggestions([]);
      return;
    }
    setLoadingTickers(true);
    try {
      const list = await searchLocalTickers(q);
      setSuggestions(list.slice(0, 8));
    } catch (e) {
      setSuggestions([]);
    } finally {
      setLoadingTickers(false);
    }
  }, []);

  useEffect(() => {
    const t = setTimeout(() => fetchSuggestions(search), 250);
    return () => clearTimeout(t);
  }, [search, fetchSuggestions]);

  const handleRun = async () => {
    setError(null);
    setResult(null);
    setSentiment(null);
    setLoading(true);
    try {
      const data = await runForecast({ ...request, use_sentiment: useSentiment });
      setResult(data);
      if (useSentiment && data) {
        setLoadingSentiment(true);
        try {
          const s = await analyzeSentiment(request.ticker, "kronos", request.future_days, request.period, true);
          setSentiment(s);
        } catch (se) {
          console.warn("Sentiment analysis failed:", se);
        } finally {
          setLoadingSentiment(false);
        }
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  const rawSeriesByDate = useMemo(() => {
    if (!result) return [];
    const grouped = new Map<string, Record<string, number | string | undefined>>();
    result.series.forEach((s: ForecastSeries) => {
      const row = grouped.get(s.date) || { date: s.date };
      row[s.type] = s.value;
      grouped.set(s.date, row);
    });
    result.forecast.forEach((p) => {
      const row = grouped.get(p.date) || { date: p.date };
      row.forecast = p.price;
      row.lower = p.lower;
      row.upper = p.upper;
      grouped.set(p.date, row);
    });
    return Array.from(grouped.values()).sort(
      (a, b) => new Date(String(a.date)).getTime() - new Date(String(b.date)).getTime(),
    );
  }, [result]);

  const seriesByDate = useMemo(() => {
    if (!startDate && !endDate) return rawSeriesByDate;
    return rawSeriesByDate.filter((row) => {
      const t = new Date(String(row.date)).getTime();
      const s = startDate ? new Date(startDate).getTime() : -Infinity;
      const e = endDate ? new Date(endDate).getTime() : Infinity;
      return t >= s && t <= e;
    });
  }, [rawSeriesByDate, startDate, endDate]);

  const lastTestDate = result?.last_test_date;

  const allKeys = ["train", "test", "forecast", "upper", "lower"] as const;

  const toggleSeries = (key: string) => {
    setVisibleSeries((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  const resetZoom = () => {
    setStartDate("");
    setEndDate("");
  };

  const resetVisibility = () => {
    setVisibleSeries({ train: true, test: true, forecast: true, upper: true, lower: true });
  };

  return (
    <div className="min-h-screen bg-background text-foreground p-6">
      <div className="max-w-7xl mx-auto space-y-6">
        <header className="space-y-1">
          <div className="flex items-center gap-3 mb-2">
            {onSwitchView && (
              <button
                onClick={onSwitchView}
                className="p-2 rounded-lg hover:bg-accent transition"
                title="Voltar ao chat"
              >
                <ArrowLeft size={18} />
              </button>
            )}
            <h1 className="text-3xl font-bold flex items-center gap-3">
              <TrendingUp className="text-primary" />
              Previsão de Preços (ARIMA)
            </h1>
          </div>
          <p className="text-muted-foreground">
            Escolha um ticker, ajuste os parâmetros do modelo e visualize a previsão com gráficos e
            métricas.
          </p>
        </header>

        <section className="bg-card border border-border rounded-2xl p-6 shadow-sm space-y-6">
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-5">
            <div className="relative">
              <label className="block text-sm font-medium mb-1">Ticker</label>
              <div className="relative">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" size={16} />
                <input
                  type="text"
                  value={search}
                  placeholder="Procurar (ex: EDP, AAPL)..."
                  onChange={(e) => {
                    setSearch(e.target.value.toUpperCase());
                    setShowSuggestions(true);
                  }}
                  onFocus={() => setShowSuggestions(true)}
                  onBlur={() => setTimeout(() => setShowSuggestions(false), 150)}
                  className="w-full pl-9 pr-3 py-2 rounded-lg border border-input bg-background focus:outline-none focus:ring-2 focus:ring-ring"
                />
                {loadingTickers && (
                  <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-muted-foreground">
                    a carregar…
                  </span>
                )}
              </div>
              {showSuggestions && (
                <ul className="absolute z-10 mt-1 w-full bg-popover border border-border rounded-lg shadow-lg max-h-56 overflow-auto">
                  {suggestions.length > 0 ? (
                    suggestions.map((t) => (
                      <li key={t}>
                        <button
                          className={classNames(
                            "w-full px-4 py-2 text-left text-sm hover:bg-accent",
                            request.ticker === t && "bg-accent font-medium",
                          )}
                          onMouseDown={(e) => {
                            e.preventDefault();
                            setRequest((r) => ({ ...r, ticker: t }));
                            setSearch(t);
                            setShowSuggestions(false);
                          }}
                        >
                          {t}
                        </button>
                      </li>
                    ))
                  ) : search.length >= 2 ? (
                    <li className="px-4 py-2 text-sm text-muted-foreground">
                      Nenhum resultado local. Escreve o ticker diretamente no campo "Ticker selecionado" e corre a previsão.
                    </li>
                  ) : null}
                </ul>
              )}
            </div>

            <div>
              <label className="block text-sm font-medium mb-1">Ticker selecionado</label>
              <input
                type="text"
                value={request.ticker ?? ""}
                onChange={(e) => setRequest((r) => ({ ...r, ticker: e.target.value.toUpperCase() }))}
                className="w-full px-3 py-2 rounded-lg border border-input bg-background focus:outline-none focus:ring-2 focus:ring-ring font-medium"
              />
            </div>

            <div>
              <label className="block text-sm font-medium mb-1">Dias futuros</label>
              <input
                type="number"
                min={1}
                max={90}
                value={request.future_days ?? 5}
                onChange={(e) =>
                  setRequest((r) => ({ ...r, future_days: parseInt(e.target.value, 10) || 1 }))
                }
                className="w-full px-3 py-2 rounded-lg border border-input bg-background focus:outline-none focus:ring-2 focus:ring-ring"
              />
            </div>

            <div>
              <label className="block text-sm font-medium mb-1">Período histórico</label>
              <select
                value={request.period ?? "5y"}
                onChange={(e) => setRequest((r) => ({ ...r, period: e.target.value }))}
                className="w-full px-3 py-2 rounded-lg border border-input bg-background focus:outline-none focus:ring-2 focus:ring-ring"
              >
                {PERIODS.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-sm font-medium mb-1">Modelo</label>
              <select
                value={request.backend ?? "arima"}
                onChange={(e) => setRequest((r) => ({ ...r, backend: e.target.value as "arima" | "kronos" }))}
                className="w-full px-3 py-2 rounded-lg border border-input bg-background focus:outline-none focus:ring-2 focus:ring-ring"
              >
                {BACKENDS.map((b) => (
                  <option key={b.value} value={b.value}>
                    {b.label}
                  </option>
                ))}
              </select>
              <p className="text-xs text-muted-foreground mt-1">
                {request.backend === "kronos"
                  ? "Kronos: LLM fundacional para séries financeiras."
                  : "ARIMA: modelo estatístico clássico."}
              </p>
            </div>

            <div className={request.backend === "kronos" ? "opacity-50 pointer-events-none" : ""}>
              <label className="block text-sm font-medium mb-1">Ordem ARIMA (p,d,q)</label>
              <input
                type="text"
                value={request.order ?? "2,1,2"}
                pattern="\\d+,\\d+,\\d+"
                onChange={(e) => setRequest((r) => ({ ...r, order: e.target.value }))}
                className="w-full px-3 py-2 rounded-lg border border-input bg-background focus:outline-none focus:ring-2 focus:ring-ring font-mono"
              />
              <p className="text-xs text-muted-foreground mt-1">Formato: p,d,q (ex: 2,1,2)</p>
            </div>

            <div>
              <label className="block text-sm font-medium mb-1">Rácio treino</label>
              <input
                type="number"
                min={0.5}
                max={0.95}
                step={0.01}
                value={request.train_ratio ?? 0.85}
                onChange={(e) =>
                  setRequest((r) => ({ ...r, train_ratio: parseFloat(e.target.value) || 0.85 }))
                }
                className="w-full px-3 py-2 rounded-lg border border-input bg-background focus:outline-none focus:ring-2 focus:ring-ring"
              />
            </div>
          </div>

          <div className="flex items-center gap-4 flex-wrap">
            <button
              onClick={handleRun}
              disabled={loading || !request.ticker}
              className="flex items-center gap-2 px-5 py-2.5 rounded-xl bg-primary text-primary-foreground font-medium hover:opacity-90 disabled:opacity-50 transition"
            >
              <Play size={18} />
              {loading ? "A calcular…" : "Gerar previsão"}
            </button>
            <label className="inline-flex items-center gap-2 px-3 py-2 rounded-xl border border-border bg-card cursor-pointer hover:bg-accent transition">
              <input
                type="checkbox"
                checked={useSentiment}
                onChange={(e) => setUseSentiment(e.target.checked)}
                className="h-4 w-4 accent-primary"
              />
              <Newspaper size={16} />
              <span className="text-sm font-medium">Incluir análise de sentimento</span>
            </label>
            {error && <p className="text-destructive text-sm">{error}</p>}
          </div>
        </section>

        {result && (
          <>
            <section className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <MetricCard
                icon={<Activity size={20} />}
                label="RMSE"
                value={formatNumber(result.rmse)}
                hint="Erro quadrático médio"
              />
              <MetricCard
                icon={<BarChart3 size={20} />}
                label="MAPE"
                value={`${formatNumber(result.mape, 2)}%`}
                hint="Erro percentual absoluto médio"
              />
              <MetricCard
                icon={<Calendar size={20} />}
                label="Ljung-Box p-value"
                value={
                  result.ljung_box_pvalue === undefined || result.ljung_box_pvalue === null
                    ? "—"
                    : formatNumber(result.ljung_box_pvalue, 4)
                }
                hint="Teste de autocorrelação residual"
              />
              <MetricCard
                icon={<TrendingUp size={20} />}
                label="Ordem ARIMA"
                value={`${result.order[0]},${result.order[1]},${result.order[2]}`}
                hint={`${result.train_days} dias treino / ${result.test_days} dias teste`}
              />
            </section>

            <section className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              <div className="lg:col-span-2 bg-card border border-border rounded-2xl p-5 shadow-sm space-y-4">
                <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
                  <h3 className="font-semibold">Série histórica e previsão</h3>
                  <div className="flex flex-wrap items-center gap-2">
                    {allKeys.map((key) => {
                      const active = visibleSeries[key];
                      const labels: Record<typeof allKeys[number], string> = {
                        train: "Treino",
                        test: "Teste",
                        forecast: "Previsão",
                        upper: "IC superior",
                        lower: "IC inferior",
                      };
                      return (
                        <button
                          key={key}
                          onClick={() => toggleSeries(key)}
                          className={classNames(
                            "inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium border transition",
                            active
                              ? "bg-primary/10 border-primary text-primary"
                              : "bg-muted border-border text-muted-foreground",
                          )}
                        >
                          {active ? <Eye size={14} /> : <EyeOff size={14} />}
                          {labels[key]}
                        </button>
                      );
                    })}
                  </div>
                </div>

                <div className="flex flex-wrap items-end gap-3">
                  <div className="flex flex-col gap-1">
                    <label className="text-xs font-medium text-muted-foreground">Desde</label>
                    <input
                      type="date"
                      value={startDate}
                      onChange={(e) => setStartDate(e.target.value)}
                      className="px-2 py-1.5 rounded-md border border-input bg-background text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                    />
                  </div>
                  <div className="flex flex-col gap-1">
                    <label className="text-xs font-medium text-muted-foreground">Até</label>
                    <input
                      type="date"
                      value={endDate}
                      onChange={(e) => setEndDate(e.target.value)}
                      className="px-2 py-1.5 rounded-md border border-input bg-background text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                    />
                  </div>
                  <button
                    onClick={resetZoom}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md border border-border text-sm hover:bg-accent transition"
                  >
                    <RotateCcw size={14} />
                    Reset datas
                  </button>
                  <button
                    onClick={resetVisibility}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md border border-border text-sm hover:bg-accent transition"
                  >
                    <Eye size={14} />
                    Mostrar tudo
                  </button>
                </div>

                <div className="h-[420px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart
                      data={seriesByDate}
                      margin={{ top: 5, right: 20, left: 0, bottom: 5 }}
                    >
                      <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                      <XAxis
                        dataKey="date"
                        tickFormatter={formatDateLabel}
                        minTickGap={30}
                        tick={{ fontSize: 11 }}
                      />
                      <YAxis
                        tick={{ fontSize: 11 }}
                        domain={["auto", "auto"]}
                        allowDataOverflow={false}
                      />
                      <Tooltip
                        labelFormatter={(label) => formatDateLabel(String(label))}
                        formatter={(value) => [formatNumber(typeof value === "number" ? value : undefined, 4), ""]}
                      />
                      <Legend />
                      <ReferenceLine x={lastTestDate} stroke="#94a3b8" strokeDasharray="4 4" label="Hoje" />
                      {visibleSeries.train && (
                        <Line
                          type="monotone"
                          dataKey="train"
                          name="Treino"
                          stroke="#2563eb"
                          dot={false}
                          strokeWidth={2}
                          connectNulls={false}
                        />
                      )}
                      {visibleSeries.test && (
                        <Line
                          type="monotone"
                          dataKey="test"
                          name="Teste"
                          stroke="#16a34a"
                          dot={false}
                          strokeWidth={2}
                          connectNulls={false}
                        />
                      )}
                      {visibleSeries.forecast && (
                        <Line
                          type="monotone"
                          dataKey="forecast"
                          name="Previsão"
                          stroke="#dc2626"
                          dot={false}
                          strokeWidth={2}
                          connectNulls={false}
                        />
                      )}
                      {visibleSeries.upper && (
                        <Line
                          type="monotone"
                          dataKey="upper"
                          name="Limite superior (IC 95%)"
                          stroke="#f87171"
                          strokeDasharray="4 4"
                          dot={false}
                          connectNulls={false}
                        />
                      )}
                      {visibleSeries.lower && (
                        <Line
                          type="monotone"
                          dataKey="lower"
                          name="Limite inferior (IC 95%)"
                          stroke="#f87171"
                          strokeDasharray="4 4"
                          dot={false}
                          connectNulls={false}
                        />
                      )}
                      <Brush dataKey="date" height={24} stroke="#64748b" />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </div>

              <div className="bg-card border border-border rounded-2xl p-5 shadow-sm flex flex-col">
                <h3 className="font-semibold mb-4">Preços previstos</h3>
                <div className="flex-1 overflow-auto max-h-[420px]">
                  <table className="w-full text-sm">
                    <thead className="sticky top-0 bg-card z-10">
                      <tr className="text-left text-muted-foreground border-b border-border">
                        <th className="py-2 pr-2">Data</th>
                        <th className="py-2 px-2 text-right">Preço</th>
                        <th className="py-2 pl-2 text-right">IC 95%</th>
                      </tr>
                    </thead>
                    <tbody>
                      {result.forecast.map((p, idx) => (
                        <tr key={p.date} className={idx % 2 === 1 ? "bg-muted/30" : ""}>
                          <td className="py-2 pr-2">{formatDateLabel(p.date)}</td>
                          <td className="py-2 px-2 text-right font-medium">
                            {formatNumber(p.price, 4)}
                          </td>
                          <td className="py-2 pl-2 text-right text-muted-foreground">
                            {p.lower !== undefined && p.upper !== undefined
                              ? `${formatNumber(p.lower, 2)} – ${formatNumber(p.upper, 2)}`
                              : "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </section>

            {result.explanation && (
              <section className="bg-card border border-border rounded-2xl p-5 shadow-sm">
                <h3 className="font-semibold mb-3 flex items-center gap-2">
                  <Sparkles className="text-primary" size={18} />
                  Leitura do gráfico (IA)
                </h3>
                <p className="text-sm leading-relaxed whitespace-pre-line text-foreground">
                  {result.explanation}
                </p>
              </section>
            )}

            {result.plot_url && (
              <section className="bg-card border border-border rounded-2xl p-5 shadow-sm">
                <h3 className="font-semibold mb-4">Gráfico gerado pelo modelo</h3>
                <img
                  src={getPlotUrl(result.plot_url)}
                  alt={`Gráfico de previsão ${result.ticker}`}
                  className="rounded-xl border border-border w-full max-h-[520px] object-contain"
                />
              </section>
            )}

            {result.model_summary && (
              <section className="bg-card border border-border rounded-2xl p-5 shadow-sm">
                <button
                  onClick={() => setShowSummary((s) => !s)}
                  className="text-sm font-medium text-primary hover:underline"
                >
                  {showSummary ? "Ocultar" : "Mostrar"} resumo do modelo
                </button>
                {showSummary && (
                  <pre className="mt-4 whitespace-pre-wrap text-xs font-mono bg-muted p-4 rounded-lg overflow-auto max-h-[500px]">
                    {result.model_summary}
                  </pre>
                )}
              </section>
            )}

            {(sentiment || loadingSentiment) && (
              <section className="bg-card border border-border rounded-2xl p-5 shadow-sm">
                <h3 className="font-semibold mb-4 flex items-center gap-2">
                  <Newspaper className="text-primary" size={18} />
                  Painel de sentimento
                </h3>
                {loadingSentiment && (
                  <div className="flex items-center gap-3 text-muted-foreground">
                    <Loader2 className="animate-spin" size={18} />
                    <span className="text-sm">A analisar notícias, macro e resultados…</span>
                  </div>
                )}
                {sentiment && (
                  <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
                    <SignalCard
                      label="Sinal"
                      value={sentiment.signals?.blended_signal === undefined ? "—" : String(sentiment.signals.blended_signal)}
                      hint="Sinal combinado de sentimento, macro e resultados"
                    />
                    <SignalCard
                      label="Confiança"
                      value={sentiment.signals?.sentiment_signal === undefined ? "—" : `${sentiment.signals.sentiment_signal}%`}
                      hint="Confiança do sinal de sentimento"
                    />
                    <SignalCard
                      label="Sinal macro"
                      value={String(sentiment.signals?.macro_signal ?? 0)}
                      hint="Sinal macro no período"
                    />
                    <SignalCard
                      label="Sinal resultados"
                      value={`${sentiment.signals?.earnings_signal === undefined ? "—" : `${sentiment.signals.earnings_signal}%`}`}
                      hint="Ajuste aplicado à previsão base"
                    />
                  </div>
                )}
              </section>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function SignalCard({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="bg-muted/50 border border-border rounded-xl p-4">
      <p className="text-xs text-muted-foreground uppercase tracking-wide">{label}</p>
      <p className="text-2xl font-bold mt-1">{value}</p>
      {hint && <p className="text-xs text-muted-foreground mt-1 line-clamp-2">{hint}</p>}
    </div>
  );
}

function MetricCard({
  icon,
  label,
  value,
  hint,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  hint: string;
}) {
  return (
    <div className="bg-card border border-border rounded-xl p-4 shadow-sm">
      <div className="flex items-center gap-2 text-muted-foreground mb-1">
        {icon}
        <span className="text-sm font-medium">{label}</span>
      </div>
      <p className="text-2xl font-bold">{value}</p>
      <p className="text-xs text-muted-foreground mt-1">{hint}</p>
    </div>
  );
}
