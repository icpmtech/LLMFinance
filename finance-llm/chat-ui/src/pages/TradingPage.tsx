import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  createChart,
  type IChartApi,
  type ISeriesApi,
  ColorType,
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
} from "lightweight-charts";
import {
  ArrowLeft,
  Search,
  Play,
  RotateCcw,
  TrendingUp,
  TrendingDown,
  Wallet,
  DollarSign,
  Activity,
  BarChart3,
  AlertTriangle,
  Calendar,
  ChevronDown,
  ChevronUp,
  Sparkles,
  Loader2,
  Newspaper,
} from "lucide-react";
import {
  analyzeSentiment,
  getTickerHistory,
  getTickerInfo,
  runForecast,
  searchLocalTickers,
  searchYahooTickers,
  getPlotUrl,
} from "../api";
import type { ForecastResponse, HistoryPoint, SentimentBlendedResponse, TickerHistory, TickerInfo } from "../types";

const PERIODS = ["1mo", "3mo", "6mo", "1y", "2y", "5y"];
const DEFAULT_TICKER = "AAPL";
const DEFAULT_PERIOD = "1y";
const DEFAULT_CAPITAL = 10000;

function fmt(n?: number | null, digits = 2) {
  if (n == null || Number.isNaN(n)) return "—";
  return n.toLocaleString("pt-PT", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function pct(n?: number | null) {
  if (n == null || Number.isNaN(n)) return "—";
  const sign = n > 0 ? "+" : "";
  return `${sign}${(n * 100).toFixed(2)}%`;
}

function parseDate(value: string) {
  return new Date(value).getTime();
}

function classNames(...c: Array<string | false | null | undefined>) {
  return c.filter(Boolean).join(" ");
}

interface ChartRow extends HistoryPoint {
  dateMs: number;
  volumeColor?: string;
}

interface CandlePoint {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
}

interface LinePoint {
  time: string;
  value: number;
}

interface Trade {
  date: string;
  side: "buy" | "sell";
  shares: number;
  price: number;
  value: number;
  pnl?: number;
}

interface SimulationResult {
  trades: Trade[];
  finalCapital: number;
  totalReturn: number;
  totalTrades: number;
  winRate: number;
  maxDrawdown: number;
  sharpe: number;
  remainingShares: number;
}

export function TradingPage({ onSwitchView }: { onSwitchView?: () => void }) {
  const [ticker, setTicker] = useState(DEFAULT_TICKER);
  const [search, setSearch] = useState(DEFAULT_TICKER);
  const [period, setPeriod] = useState(DEFAULT_PERIOD);
  const [history, setHistory] = useState<TickerHistory | null>(null);
  const [info, setInfo] = useState<TickerInfo | null>(null);
  const [forecast, setForecast] = useState<ForecastResponse | null>(null);
  const [sentiment, setSentiment] = useState<SentimentBlendedResponse | null>(null);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [loadingForecast, setLoadingForecast] = useState(false);
  const [loadingSentiment, setLoadingSentiment] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [useSentiment, setUseSentiment] = useState(true);

  const [suggestions, setSuggestions] = useState<{ symbol: string; name?: string }[]>([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [loadingSuggestions, setLoadingSuggestions] = useState(false);

  const [capital, setCapital] = useState(DEFAULT_CAPITAL);
  const [positionSizePct, setPositionSizePct] = useState(100);
  const [mode, setMode] = useState<"kronos" | "manual">("kronos");
  const [manualSide, setManualSide] = useState<"buy" | "sell">("buy");
  const [simulation, setSimulation] = useState<SimulationResult | null>(null);
  const [showForecast, setShowForecast] = useState(true);
  const [showVolume, setShowVolume] = useState(true);
  const [showSentiment, setShowSentiment] = useState(true);
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");

  const chartContainerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const forecastLineRef = useRef<ISeriesApi<"Line"> | null>(null);
  const forecastUpperRef = useRef<ISeriesApi<"Line"> | null>(null);
  const forecastLowerRef = useRef<ISeriesApi<"Line"> | null>(null);
  const sentimentLineRef = useRef<ISeriesApi<"Line"> | null>(null);
  const todayLineRef = useRef<ISeriesApi<"Line"> | null>(null);

  const fetchSuggestions = useCallback(async (q: string) => {
    if (q.length < 2) {
      setSuggestions([]);
      return;
    }
    setLoadingSuggestions(true);
    try {
      const local = await searchLocalTickers(q);
      const mapped = local.map((s) => ({ symbol: s }));
      if (mapped.length < 6) {
        try {
          const yahoo = await searchYahooTickers(q);
          const yahooMapped = (yahoo.yahoo_results || []).slice(0, 8).map((r) => ({
            symbol: r.symbol,
            name: r.name,
          }));
          const seen = new Set(mapped.map((m) => m.symbol));
          for (const y of yahooMapped) {
            if (!seen.has(y.symbol)) mapped.push(y);
          }
        } catch {}
      }
      setSuggestions(mapped.slice(0, 8));
    } catch {
      setSuggestions([]);
    } finally {
      setLoadingSuggestions(false);
    }
  }, []);

  useEffect(() => {
    const t = setTimeout(() => fetchSuggestions(search), 250);
    return () => clearTimeout(t);
  }, [search, fetchSuggestions]);

  const loadData = useCallback(async () => {
    if (!ticker) return;
    setError(null);
    setLoadingHistory(true);
    try {
      const [h, i] = await Promise.all([
        getTickerHistory(ticker, period),
        getTickerInfo(ticker).catch(() => null),
      ]);
      setHistory(h);
      setInfo(i);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setHistory(null);
      setInfo(null);
    } finally {
      setLoadingHistory(false);
    }
  }, [ticker, period]);

  const runForecastAndSentiment = useCallback(async () => {
    if (!ticker) return;
    setLoadingForecast(true);
    setLoadingSentiment(true);
    setError(null);
    try {
      const [forecastRes, sentimentRes] = await Promise.all([
        runForecast({
          ticker,
          future_days: 10,
          period: "5y",
          train_ratio: 0.85,
          backend: "kronos",
          use_sentiment: useSentiment,
        }),
        analyzeSentiment(ticker, "kronos", 10, "5y", false).catch((err) => {
          console.warn("Sentiment analyze failed:", err);
          return null;
        }),
      ]);
      setForecast(forecastRes);
      setSentiment(sentimentRes);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setForecast(null);
      setSentiment(null);
    } finally {
      setLoadingForecast(false);
      setLoadingSentiment(false);
    }
  }, [ticker, useSentiment]);

  const chartData: ChartRow[] = useMemo(() => {
    if (!history?.points?.length) return [];
    const points = history.points.filter((p) => p.close != null);
    return points.map((p, i) => {
      const prev = i > 0 ? points[i - 1] : p;
      const positive = (p.close ?? 0) >= (prev.close ?? 0);
      return { ...p, dateMs: parseDate(p.date), volumeColor: positive ? "#16a34a" : "#dc2626" };
    });
  }, [history]);

  const filteredData = useMemo(() => {
    if (!startDate && !endDate) return chartData;
    const s = startDate ? parseDate(startDate) : -Infinity;
    const e = endDate ? parseDate(endDate) : Infinity;
    return chartData.filter((d) => {
      const t = parseDate(d.date);
      return t >= s && t <= e;
    });
  }, [chartData, startDate, endDate]);

  const lastPrice = history?.points?.[history.points.length - 1]?.close ?? info?.price ?? null;

  const candles: CandlePoint[] = useMemo(() => {
    return filteredData
      .filter((p) => p.open != null && p.high != null && p.low != null && p.close != null)
      .map((p) => ({
        time: p.date.slice(0, 10),
        open: p.open!,
        high: p.high!,
        low: p.low!,
        close: p.close!,
      }));
  }, [filteredData]);

  const volumes = useMemo(() => {
    return filteredData
      .filter((p) => p.volume != null)
      .map((p, i, arr) => {
        const prev = i > 0 ? arr[i - 1] : p;
        const positive = (p.close ?? 0) >= (prev.close ?? 0);
        return {
          time: p.date.slice(0, 10),
          value: p.volume!,
          color: positive ? "#16a34a" : "#dc2626",
        };
      });
  }, [filteredData]);

  const forecastLine: LinePoint[] = useMemo(() => {
    if (!forecast?.forecast?.length) return [];
    return forecast.forecast.map((p) => ({ time: p.date.slice(0, 10), value: p.price }));
  }, [forecast]);

  const forecastUpper: LinePoint[] = useMemo(() => {
    if (!forecast?.forecast?.length) return [];
    return forecast.forecast
      .filter((p) => p.upper != null)
      .map((p) => ({ time: p.date.slice(0, 10), value: p.upper! }));
  }, [forecast]);

  const forecastLower: LinePoint[] = useMemo(() => {
    if (!forecast?.forecast?.length) return [];
    return forecast.forecast
      .filter((p) => p.lower != null)
      .map((p) => ({ time: p.date.slice(0, 10), value: p.lower! }));
  }, [forecast]);

  const sentimentLine: LinePoint[] = useMemo(() => {
    if (!sentiment?.adjusted_forecast?.length) return [];
    return sentiment.adjusted_forecast.map((p) => ({ time: p.date.slice(0, 10), value: p.price }));
  }, [sentiment]);

  const runSimulation = useCallback(() => {
    if (!history?.points?.length || !lastPrice) return;
    if (mode === "kronos" && (!forecast?.forecast?.length || !lastPrice)) return;

    const sortedHistory = [...history.points].sort((a, b) => parseDate(a.date) - parseDate(b.date));
    const startPrice = sortedHistory[0].close ?? lastPrice;
    let capitalUsed = capital * (positionSizePct / 100);
    const cashReserve = capital - capitalUsed;
    let shares = 0;
    const trades: Trade[] = [];
    let peak = capital;
    let maxDrawdown = 0;

    const simulateDays: { date: string; price: number }[] =
      mode === "kronos" && forecast
        ? forecast.forecast.map((p) => ({ date: p.date, price: p.price }))
        : sortedHistory.slice(1).map((p) => ({ date: p.date, price: p.close ?? startPrice }));
    let currentPrice = startPrice;

    simulateDays.forEach((day, idx) => {
      const price = day.price;
      currentPrice = price;
      const prevPrice = idx === 0 ? startPrice : simulateDays[idx - 1].price;
      let side: "buy" | "sell" | null = null;

      if (mode === "kronos" && forecast) {
        const signalPrice = forecast.forecast[forecast.forecast.length - 1]?.price ?? price;
        side = signalPrice > lastPrice ? "buy" : "sell";
      } else {
        side = manualSide;
      }

      if (side === "buy" && shares === 0 && capitalUsed > 0) {
        const buyShares = Math.floor(capitalUsed / price);
        if (buyShares > 0) {
          shares = buyShares;
          const cost = shares * price;
          capitalUsed -= cost;
          trades.push({ date: day.date, side: "buy", shares, price, value: cost });
        }
      } else if (side === "sell" && shares > 0) {
        const proceeds = shares * price;
        const buyTrade = trades.find((t) => t.side === "buy");
        const cost = buyTrade ? buyTrade.value : shares * prevPrice;
        const pnl = proceeds - cost;
        trades.push({ date: day.date, side: "sell", shares, price, value: proceeds, pnl });
        capitalUsed += proceeds;
        shares = 0;
      }

      const equity = cashReserve + capitalUsed + shares * price;
      if (equity > peak) peak = equity;
      const dd = (peak - equity) / peak;
      if (dd > maxDrawdown) maxDrawdown = dd;
    });

    const finalPrice = currentPrice;
    const finalCapital = cashReserve + capitalUsed + shares * finalPrice;
    const totalReturn = (finalCapital - capital) / capital;
    const sellTrades = trades.filter((t) => t.side === "sell");
    const winTrades = sellTrades.filter((t) => (t.pnl ?? 0) > 0);
    const winRate = sellTrades.length
      ? winTrades.length / sellTrades.length
      : shares > 0
        ? NaN
        : 0;
    const returns = trades
      .filter((t) => t.side === "sell" && t.pnl != null)
      .map((t) => (t.pnl ?? 0) / capital);
    const mean = returns.length ? returns.reduce((a, b) => a + b, 0) / returns.length : 0;
    const std = returns.length > 1
      ? Math.sqrt(returns.reduce((a, b) => a + (b - mean) ** 2, 0) / (returns.length - 1))
      : 0;
    const sharpe = std > 0 ? (mean / std) * Math.sqrt(252) : 0;

    setSimulation({
      trades,
      finalCapital,
      totalReturn,
      totalTrades: trades.length,
      winRate,
      maxDrawdown,
      sharpe,
      remainingShares: shares,
    });
  }, [history, forecast, lastPrice, capital, positionSizePct, mode, manualSide]);

  useEffect(() => {
    setSimulation(null);
  }, [ticker, period, mode, manualSide, capital, positionSizePct, forecast, sentiment]);

  useEffect(() => {
    if (!chartContainerRef.current) return;
    if (chartRef.current) return;

    const isDark = document.documentElement.classList.contains("dark");
    const chart = createChart(chartContainerRef.current, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: isDark ? "#0f172a" : "#ffffff" },
        textColor: isDark ? "#e2e8f0" : "#1e293b",
      },
      grid: {
        vertLines: { color: isDark ? "#1e293b" : "#f1f5f9" },
        horzLines: { color: isDark ? "#1e293b" : "#f1f5f9" },
      },
      crosshair: { mode: 1 },
      rightPriceScale: { borderColor: isDark ? "#334155" : "#e2e8f0" },
      timeScale: { borderColor: isDark ? "#334155" : "#e2e8f0", timeVisible: true },
    });

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: "#16a34a",
      downColor: "#dc2626",
      borderVisible: false,
      wickUpColor: "#16a34a",
      wickDownColor: "#dc2626",
    });

    const volumeSeries = chart.addSeries(HistogramSeries, {
      color: "#94a3b8",
      priceFormat: { type: "volume" },
      priceScaleId: "left",
    });
    volumeSeries.priceScale().applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });

    const forecastLineSeries = chart.addSeries(LineSeries, {
      color: "#dc2626",
      lineStyle: 2,
      lineWidth: 2,
      title: "Previsão Kronos",
      visible: false,
    });

    const forecastUpperSeries = chart.addSeries(LineSeries, {
      color: "#fca5a5",
      lineStyle: 3,
      lineWidth: 1,
      lastValueVisible: false,
      title: "Limite superior",
      visible: false,
    });

    const forecastLowerSeries = chart.addSeries(LineSeries, {
      color: "#93c5fd",
      lineStyle: 3,
      lineWidth: 1,
      lastValueVisible: false,
      title: "Limite inferior",
      visible: false,
    });

    const sentimentLineSeries = chart.addSeries(LineSeries, {
      color: "#f59e0b",
      lineStyle: 0,
      lineWidth: 2,
      lastValueVisible: false,
      title: "Ajustado sentimento",
      visible: false,
    });

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    volumeSeriesRef.current = volumeSeries;
    forecastLineRef.current = forecastLineSeries;
    forecastUpperRef.current = forecastUpperSeries;
    forecastLowerRef.current = forecastLowerSeries;
    sentimentLineRef.current = sentimentLineSeries;

    return () => {
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      volumeSeriesRef.current = null;
      forecastLineRef.current = null;
      forecastUpperRef.current = null;
      forecastLowerRef.current = null;
      sentimentLineRef.current = null;
    };
  }, [history]);

  useEffect(() => {
    if (!chartRef.current || !candleSeriesRef.current) return;
    candleSeriesRef.current.setData(candles);
    if (!candles.length) return;
    chartRef.current.timeScale().fitContent();

    if (startDate || endDate) {
      const from = startDate ? startDate.slice(0, 10) : candles[0].time;
      const to = endDate ? endDate.slice(0, 10) : candles[candles.length - 1].time;
      if (from <= to) {
        try {
          chartRef.current.timeScale().setVisibleRange({ from, to });
        } catch {
          chartRef.current.timeScale().fitContent();
        }
      }
    }
  }, [candles, startDate, endDate]);

  useEffect(() => {
    if (!volumeSeriesRef.current) return;
    volumeSeriesRef.current.setData(volumes);
    volumeSeriesRef.current.applyOptions({ visible: showVolume });
  }, [volumes, showVolume]);

  useEffect(() => {
    if (!forecastLineRef.current) return;
    forecastLineRef.current.setData(forecastLine);
    forecastLineRef.current.applyOptions({ visible: showForecast });
  }, [forecastLine, showForecast]);

  useEffect(() => {
    if (!forecastUpperRef.current) return;
    forecastUpperRef.current.setData(forecastUpper);
    forecastUpperRef.current.applyOptions({ visible: showForecast });
  }, [forecastUpper, showForecast]);

  useEffect(() => {
    if (!forecastLowerRef.current) return;
    forecastLowerRef.current.setData(forecastLower);
    forecastLowerRef.current.applyOptions({ visible: showForecast });
  }, [forecastLower, showForecast]);

  useEffect(() => {
    if (!sentimentLineRef.current) return;
    sentimentLineRef.current.setData(sentimentLine);
    sentimentLineRef.current.applyOptions({ visible: showSentiment });
  }, [sentimentLine, showSentiment]);

  useEffect(() => {
    if (!chartRef.current || !candleSeriesRef.current) return;
    if (todayLineRef.current) {
      chartRef.current.removeSeries(todayLineRef.current);
      todayLineRef.current = null;
    }
    if (forecast?.last_test_date && candles.length) {
      const todaySeries = chartRef.current.addSeries(LineSeries, {
        color: "#94a3b8",
        lineStyle: 2,
        lineWidth: 1,
        lastValueVisible: false,
        title: "Hoje",
        pointMarkersVisible: false,
      });
      const yMin = Math.min(...candles.map((c) => c.low));
      const yMax = Math.max(...candles.map((c) => c.high));
      todaySeries.setData([
        { time: forecast.last_test_date.slice(0, 10), value: yMin },
        { time: forecast.last_test_date.slice(0, 10), value: yMax },
      ]);
      todayLineRef.current = todaySeries;
    }
  }, [forecast?.last_test_date, candles]);

  const kronosSignal = useMemo(() => {
    if (!forecast?.forecast?.length || lastPrice == null) return null;
    const lastForecast = forecast.forecast[forecast.forecast.length - 1].price;
    if (lastForecast > lastPrice * 1.005) return { side: "buy" as const, strength: ((lastForecast - lastPrice) / lastPrice) * 100 };
    if (lastForecast < lastPrice * 0.995) return { side: "sell" as const, strength: ((lastPrice - lastForecast) / lastPrice) * 100 };
    return { side: "hold" as const, strength: 0 };
  }, [forecast, lastPrice]);

  return (
    <div className="min-h-screen bg-background text-foreground p-4 sm:p-6">
      <div className="max-w-7xl mx-auto space-y-6">
        <header className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div className="flex items-center gap-3">
            {onSwitchView && (
              <button
                onClick={onSwitchView}
                className="p-2 rounded-lg hover:bg-accent transition"
                title="Voltar"
              >
                <ArrowLeft size={18} />
              </button>
            )}
            <div>
              <h1 className="text-2xl sm:text-3xl font-bold flex items-center gap-3">
                <BarChart3 className="text-primary" />
                Trading & Simulação (Kronos)
              </h1>
              <p className="text-muted-foreground text-sm mt-1">
                Pesquisa um ticker, visualiza o histórico e simula estratégias com base na previsão Kronos.
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {info && (
              <div className="text-right hidden sm:block">
                <div className="text-xs text-muted-foreground">{info.name || info.ticker}</div>
                <div className="font-bold">{fmt(info.price)} {info.currency}</div>
              </div>
            )}
          </div>
        </header>

        <section className="bg-card border border-border rounded-2xl p-5 shadow-sm space-y-5">
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            <div className="relative md:col-span-2">
              <label className="block text-sm font-medium mb-1">Pesquisar ticker</label>
              <div className="relative">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" size={16} />
                <input
                  type="text"
                  value={search}
                  placeholder="Ex: AAPL, EDP.LS, TSLA..."
                  onChange={(e) => {
                    setSearch(e.target.value.toUpperCase());
                    setShowSuggestions(true);
                  }}
                  onFocus={() => setShowSuggestions(true)}
                  onBlur={() => setTimeout(() => setShowSuggestions(false), 150)}
                  className="w-full pl-9 pr-3 py-2 rounded-lg border border-input bg-background focus:outline-none focus:ring-2 focus:ring-ring"
                />
                {loadingSuggestions && (
                  <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-muted-foreground">
                    a carregar…
                  </span>
                )}
              </div>
              {showSuggestions && suggestions.length > 0 && (
                <ul className="absolute z-20 mt-1 w-full bg-popover border border-border rounded-lg shadow-lg max-h-56 overflow-auto">
                  {suggestions.map((s) => (
                    <li key={s.symbol}>
                      <button
                        className="w-full px-4 py-2 text-left text-sm hover:bg-accent"
                        onMouseDown={(e) => {
                          e.preventDefault();
                          setTicker(s.symbol);
                          setSearch(s.symbol);
                          setShowSuggestions(false);
                        }}
                      >
                        <span className="font-semibold">{s.symbol}</span>
                        <span className="text-muted-foreground ml-2">{s.name}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">Ticker ativo</label>
              <input
                type="text"
                value={ticker}
                onChange={(e) => {
                  setTicker(e.target.value.toUpperCase());
                  setSearch(e.target.value.toUpperCase());
                }}
                className="w-full px-3 py-2 rounded-lg border border-input bg-background focus:outline-none focus:ring-2 focus:ring-ring font-medium"
              />
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">Período do gráfico</label>
              <select
                value={period}
                onChange={(e) => setPeriod(e.target.value)}
                className="w-full px-3 py-2 rounded-lg border border-input bg-background focus:outline-none focus:ring-2 focus:ring-ring"
              >
                {PERIODS.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <button
              onClick={loadData}
              disabled={loadingHistory || !ticker}
              className="flex items-center gap-2 px-4 py-2 rounded-xl bg-primary text-primary-foreground font-medium hover:opacity-90 disabled:opacity-50 transition"
            >
              <Play size={16} />
              {loadingHistory ? "A carregar histórico…" : "Carregar histórico"}
            </button>
            <button
              onClick={runForecastAndSentiment}
              disabled={loadingForecast || !ticker}
              className="flex items-center gap-2 px-4 py-2 rounded-xl bg-card border border-border font-medium hover:bg-accent disabled:opacity-50 transition"
            >
              <Sparkles size={16} className="text-primary" />
              {loadingForecast ? "Kronos a pensar…" : "Gerar previsão Kronos"}
            </button>
            {error && <p className="text-destructive text-sm">{error}</p>}
          </div>

          <div className="flex items-center gap-2 pt-2 border-t border-border">
            <input
              id="use-sentiment"
              type="checkbox"
              checked={useSentiment}
              onChange={(e) => setUseSentiment(e.target.checked)}
              className="h-4 w-4 rounded border-border text-primary focus:ring-ring"
            />
            <label htmlFor="use-sentiment" className="text-sm font-medium">
              Misturar previsão com sentimento, macro e resultados
            </label>
            {loadingSentiment && (
              <span className="ml-auto text-xs text-muted-foreground inline-flex items-center gap-1">
                <Loader2 size={12} className="animate-spin" />
                Analisar sentimento…
              </span>
            )}
          </div>
        </section>

        {history && (
          <>
            <section className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <MetricCard
                icon={<DollarSign size={20} />}
                label="Último preço"
                value={fmt(lastPrice)}
                hint={info?.currency || "USD"}
              />
              <MetricCard
                icon={<Activity size={20} />}
                label="Máx. 52s / Mín. 52s"
                value={`${fmt(info?.target_high_price)} / ${fmt(info?.target_low_price)}`}
                hint="Yahoo Finance"
              />
              <MetricCard
                icon={<TrendingUp size={20} />}
                label="Recomendação"
                value={info?.recommendation ? info.recommendation.toUpperCase() : "—"}
                hint={info?.recommendation_mean ? `média ${info.recommendation_mean}` : ""}
              />
              <MetricCard
                icon={<Calendar size={20} />}
                label="Dados"
                value={`${history.points.length}`}
                hint={`período ${history.period}`}
              />
            </section>

            {forecast && (
              <section className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <MetricCard
                  icon={<Activity size={20} />}
                  label="RMSE"
                  value={fmt(forecast.rmse, 4)}
                  hint="Erro quadrático médio"
                />
                <MetricCard
                  icon={<BarChart3 size={20} />}
                  label="MAPE"
                  value={`${fmt(forecast.mape, 2)}%`}
                  hint="Erro percentual absoluto médio"
                />
                <MetricCard
                  icon={kronosSignal?.side === "buy" ? <TrendingUp size={20} /> : kronosSignal?.side === "sell" ? <TrendingDown size={20} /> : <Activity size={20} />}
                  label="Sinal Kronos"
                  value={kronosSignal?.side.toUpperCase() || "—"}
                  hint={kronosSignal && kronosSignal.side !== "hold" ? `força ${fmt(kronosSignal.strength, 2)}%` : "sem direção clara"}
                />
                <MetricCard
                  icon={<Calendar size={20} />}
                  label="Horizonte"
                  value={`${forecast.forecast.length} dias`}
                  hint={`até ${forecast.forecast[forecast.forecast.length - 1]?.date}`}
                />
              </section>
            )}

            <section className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              <div className="lg:col-span-2 bg-card border border-border rounded-2xl p-5 shadow-sm space-y-4">
                <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
                  <h3 className="font-semibold">Gráfico {ticker}</h3>
                  <div className="flex flex-wrap items-center gap-2">
                    <Toggle active={showForecast} onClick={() => setShowForecast((v) => !v)} label="Previsão" />
                    <Toggle active={showSentiment} onClick={() => setShowSentiment((v) => !v)} label="Sentimento" />
                    <Toggle active={showVolume} onClick={() => setShowVolume((v) => !v)} label="Volume" />
                    <button
                      onClick={() => {
                        setStartDate("");
                        setEndDate("");
                      }}
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md border border-border text-xs hover:bg-accent transition"
                    >
                      <RotateCcw size={12} />
                      Reset
                    </button>
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
                </div>
                <div className="h-[420px]">
                  <div ref={chartContainerRef} className="w-full h-full" />
                </div>
                <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
                  <span className="inline-flex items-center gap-1"><span className="w-3 h-3 rounded-sm bg-emerald-600" /> Alta</span>
                  <span className="inline-flex items-center gap-1"><span className="w-3 h-3 rounded-sm bg-red-600" /> Baixa</span>
                  <span className="inline-flex items-center gap-1"><span className="w-4 h-0.5 bg-red-600" /> Previsão Kronos</span>
                  <span className="inline-flex items-center gap-1"><span className="w-4 h-0.5 bg-amber-500" /> Ajustado sentimento</span>
                  <span className="inline-flex items-center gap-1"><span className="w-4 h-0.5 bg-red-300" /> Limite superior</span>
                  <span className="inline-flex items-center gap-1"><span className="w-4 h-0.5 bg-blue-300" /> Limite inferior</span>
                </div>
                {forecast?.plot_url && (
                  <div className="border-t border-border pt-4">
                    <h4 className="text-sm font-medium mb-2">Gráfico gerado pelo Kronos</h4>
                    <img
                      src={getPlotUrl(forecast.plot_url)}
                      alt={`Gráfico Kronos ${forecast.ticker}`}
                      className="rounded-xl border border-border w-full max-h-[320px] object-contain"
                    />
                  </div>
                )}
              </div>

              <div className="bg-card border border-border rounded-2xl p-5 shadow-sm space-y-5">
                <h3 className="font-semibold flex items-center gap-2">
                  <Wallet size={18} className="text-primary" />
                  Simulação
                </h3>

                <div className="space-y-3">
                  <div>
                    <label className="block text-sm font-medium mb-1">Capital inicial</label>
                    <input
                      type="number"
                      min={100}
                      step={100}
                      value={capital}
                      onChange={(e) => setCapital(parseFloat(e.target.value) || 0)}
                      className="w-full px-3 py-2 rounded-lg border border-input bg-background focus:outline-none focus:ring-2 focus:ring-ring"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium mb-1">Alocação por trade (%)</label>
                    <input
                      type="number"
                      min={1}
                      max={100}
                      value={positionSizePct}
                      onChange={(e) => setPositionSizePct(parseFloat(e.target.value) || 100)}
                      className="w-full px-3 py-2 rounded-lg border border-input bg-background focus:outline-none focus:ring-2 focus:ring-ring"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium mb-1">Modo</label>
                    <div className="flex rounded-lg border border-border overflow-hidden">
                      <button
                        onClick={() => setMode("kronos")}
                        className={classNames(
                          "flex-1 px-3 py-2 text-sm font-medium transition",
                          mode === "kronos" ? "bg-primary text-primary-foreground" : "hover:bg-accent",
                        )}
                      >
                        Sinal Kronos
                      </button>
                      <button
                        onClick={() => setMode("manual")}
                        className={classNames(
                          "flex-1 px-3 py-2 text-sm font-medium transition",
                          mode === "manual" ? "bg-primary text-primary-foreground" : "hover:bg-accent",
                        )}
                      >
                        Manual
                      </button>
                    </div>
                  </div>
                  {mode === "manual" && (
                    <div>
                      <label className="block text-sm font-medium mb-1">Ordem inicial</label>
                      <div className="flex rounded-lg border border-border overflow-hidden">
                        <button
                          onClick={() => setManualSide("buy")}
                          className={classNames(
                            "flex-1 px-3 py-2 text-sm font-medium transition",
                            manualSide === "buy" ? "bg-emerald-600 text-white" : "hover:bg-accent",
                          )}
                        >
                          Comprar
                        </button>
                        <button
                          onClick={() => setManualSide("sell")}
                          className={classNames(
                            "flex-1 px-3 py-2 text-sm font-medium transition",
                            manualSide === "sell" ? "bg-red-600 text-white" : "hover:bg-accent",
                          )}
                        >
                          Vender
                        </button>
                      </div>
                    </div>
                  )}
                  <button
                    onClick={runSimulation}
                    disabled={mode === "kronos" && !forecast}
                    className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl bg-primary text-primary-foreground font-medium hover:opacity-90 disabled:opacity-50 transition"
                  >
                    <Play size={16} />
                    Correr simulação
                  </button>
                  {mode === "kronos" && !forecast && (
                    <p className="text-xs text-muted-foreground flex items-center gap-1">
                      <AlertTriangle size={12} />
                      Gera primeiro a previsão Kronos.
                    </p>
                  )}
                </div>

                {simulation && (
                  <div className="space-y-3 border-t border-border pt-4">
                    <h4 className="text-sm font-semibold">Resultado</h4>
                    <div className="grid grid-cols-2 gap-3">
                      <div className="bg-muted rounded-xl p-3">
                        <div className="text-xs text-muted-foreground">Capital final</div>
                        <div className="font-bold text-lg">{fmt(simulation.finalCapital)}</div>
                      </div>
                      <div className={classNames("bg-muted rounded-xl p-3", simulation.totalReturn >= 0 ? "text-emerald-600" : "text-red-600")}>
                        <div className="text-xs text-muted-foreground">Retorno total</div>
                        <div className="font-bold text-lg">{pct(simulation.totalReturn)}</div>
                      </div>
                      <div className="bg-muted rounded-xl p-3">
                        <div className="text-xs text-muted-foreground">Trades</div>
                        <div className="font-bold text-lg">{simulation.totalTrades}</div>
                      </div>
                      <div className="bg-muted rounded-xl p-3">
                        <div className="text-xs text-muted-foreground">Win rate</div>
                        <div className="font-bold text-lg">{fmt(simulation.winRate * 100, 1)}%</div>
                      </div>
                      <div className="bg-muted rounded-xl p-3">
                        <div className="text-xs text-muted-foreground">Max drawdown</div>
                        <div className="font-bold text-lg">{fmt(simulation.maxDrawdown * 100, 2)}%</div>
                      </div>
                      <div className="bg-muted rounded-xl p-3">
                        <div className="text-xs text-muted-foreground">Sharpe anual.</div>
                        <div className="font-bold text-lg">{fmt(simulation.sharpe, 2)}</div>
                      </div>
                    </div>
                    {simulation.trades.length > 0 && (
                      <div>
                        <h5 className="text-xs font-semibold text-muted-foreground mb-2 uppercase tracking-wide">
                          Trades
                        </h5>
                        <div className="max-h-48 overflow-auto space-y-1">
                          {simulation.trades.map((t, i) => (
                            <div
                              key={`${t.date}-${i}`}
                              className={classNames(
                                "flex items-center justify-between text-sm px-3 py-2 rounded-lg border",
                                t.side === "buy"
                                  ? "bg-emerald-50 border-emerald-200 text-emerald-800"
                                  : "bg-red-50 border-red-200 text-red-800",
                              )}
                            >
                              <span className="font-medium">{t.side.toUpperCase()}</span>
                              <span className="text-muted-foreground">{t.shares} @ {fmt(t.price)}</span>
                              <span>{new Date(t.date).toLocaleDateString("pt-PT")}</span>
                              {t.pnl != null && (
                                <span className={t.pnl >= 0 ? "text-emerald-600" : "text-red-600"}>
                                  {t.pnl >= 0 ? "+" : ""}
                                  {fmt(t.pnl)}
                                </span>
                              )}
                            </div>
                          ))}
                        </div>
                        {simulation.remainingShares > 0 && (
                          <p className="text-xs text-muted-foreground mt-2">
                            Posição aberta: {simulation.remainingShares} ações no final da simulação.
                          </p>
                        )}
                      </div>
                    )}
                  </div>
                )}
              </div>
            </section>

            {sentiment && (
              <section className="bg-card border border-border rounded-2xl p-5 shadow-sm">
                <h3 className="font-semibold mb-3 flex items-center gap-2">
                  <Newspaper className="text-primary" size={18} />
                  Análise de Sentimento &amp; Sinais
                </h3>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
                  <SignalCard label="Notícias" signal={sentiment.signals.sentiment_signal} />
                  <SignalCard label="Macro" signal={sentiment.signals.macro_signal} />
                  <SignalCard label="Resultados" signal={sentiment.signals.earnings_signal} />
                  <SignalCard label="Combinado" signal={sentiment.signals.blended_signal} highlighted />
                </div>
                {sentiment.features && (
                  <div className="text-xs text-muted-foreground">
                    <div className="flex flex-wrap gap-2">
                      {sentiment.features.news_count != null && (
                        <span className="bg-muted rounded px-2 py-1">
                          notícias: {String(sentiment.features.news_count)}
                        </span>
                      )}
                      {sentiment.features.avg_daily_sentiment != null && (
                        <span className="bg-muted rounded px-2 py-1">
                          sent. médio: {fmt(Number(sentiment.features.avg_daily_sentiment), 3)}
                        </span>
                      )}
                      {sentiment.features.next_earnings_days != null && (
                        <span className="bg-muted rounded px-2 py-1">
                          próx. resultados: {String(sentiment.features.next_earnings_days)}d
                        </span>
                      )}
                      {sentiment.features.macro_features_count != null && (
                        <span className="bg-muted rounded px-2 py-1">
                          indicadores macro: {String(sentiment.features.macro_features_count)}
                        </span>
                      )}
                    </div>
                  </div>
                )}
              </section>
            )}

            {forecast?.explanation && (
              <section className="bg-card border border-border rounded-2xl p-5 shadow-sm">
                <h3 className="font-semibold mb-3 flex items-center gap-2">
                  <Sparkles className="text-primary" size={18} />
                  Leitura Kronos
                </h3>
                <p className="text-sm leading-relaxed whitespace-pre-line text-foreground">
                  {forecast.explanation}
                </p>
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
  signal,
  highlighted = false,
}: {
  label: string;
  signal: number;
  highlighted?: boolean;
}) {
  const side = signal > 0.1 ? "Bullish" : signal < -0.1 ? "Bearish" : "Neutro";
  const color =
    signal > 0.1 ? "text-emerald-600 bg-emerald-50 border-emerald-200" : signal < -0.1 ? "text-red-600 bg-red-50 border-red-200" : "text-slate-600 bg-slate-50 border-slate-200";
  return (
    <div className={classNames("rounded-xl p-4 border", highlighted ? "ring-1 ring-primary/30" : "", color)}>
      <div className="text-xs font-medium opacity-80">{label}</div>
      <div className="text-xl font-bold">{side}</div>
      <div className="text-xs opacity-70">{fmt(signal, 3)}</div>
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
  hint?: string;
}) {
  return (
    <div className="bg-card border border-border rounded-xl p-4 shadow-sm">
      <div className="flex items-center gap-2 text-muted-foreground mb-1">
        {icon}
        <span className="text-sm font-medium">{label}</span>
      </div>
      <p className="text-xl sm:text-2xl font-bold truncate">{value}</p>
      {hint && <p className="text-xs text-muted-foreground mt-1 truncate">{hint}</p>}
    </div>
  );
}

function Toggle({ active, onClick, label }: { active: boolean; onClick: () => void; label: string }) {
  return (
    <button
      onClick={onClick}
      className={classNames(
        "inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium border transition",
        active ? "bg-primary/10 border-primary text-primary" : "bg-muted border-border text-muted-foreground",
      )}
    >
      {active ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
      {label}
    </button>
  );
}
