import { useEffect, useMemo, useState } from "react";
import {
  ArrowLeft,
  ArrowUpRight,
  ArrowDownRight,
  CandlestickChart,
  TrendingUp,
  Newspaper,
  Zap,
  Activity,
  BarChart3,
  Target,
  RefreshCw,
  Star,
  AlertTriangle,
  CheckCircle,
  MessageSquare,
  ChevronRight,
  Maximize2,
} from "lucide-react";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  getTickerHistory,
  getTickerInfo,
  getTickerNews,
  getTickerRecommendations,
  getTickerTechnical,
  getTickerTechnicalExplain,
  runForecast,
} from "../api";
import type {
  ForecastPoint,
  ForecastResponse,
  HistoryPoint,
  News,
  Recommendations,
  TechnicalAnalysis,
  TechnicalExplanation,
  TickerHistory,
  TickerInfo,
} from "../types";
import { TradingViewChart, tradingViewSymbol } from "./RealtimeChartPage";
import { TickerKpiCards } from "../components/TickerKpiCards";

type Tab = "overview" | "chart" | "analysis" | "forecast" | "sentiment";

function fmt(n?: number | null) {
  if (n == null || Number.isNaN(n)) return "—";
  return n.toLocaleString("pt-PT", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function pct(n?: number | null) {
  if (n == null || Number.isNaN(n)) return "—";
  const sign = n > 0 ? "+" : "";
  return `${sign}${(n * 100).toFixed(2)}%`;
}

function pctFromRatio(n?: number | null) {
  if (n == null || Number.isNaN(n)) return "—";
  const sign = n > 0 ? "+" : "";
  return `${sign}${Math.abs(n).toFixed(2)}%`;
}

function compact(n?: number | null) {
  if (n == null || Number.isNaN(n)) return "—";
  const abs = Math.abs(n);
  if (abs >= 1e12) return `${(n / 1e12).toFixed(2)}T`;
  if (abs >= 1e9) return `${(n / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${(n / 1e6).toFixed(2)}M`;
  if (abs >= 1e3) return `${(n / 1e3).toFixed(2)}K`;
  return fmt(n);
}

function recommendationBadge(rec?: string) {
  const text = (rec || "neutro").toLowerCase();
  if (text.includes("buy") || text.includes("compra") || text.includes("strong")) {
    return { label: "Comprar", color: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30" };
  }
  if (text.includes("sell") || text.includes("venda")) {
    return { label: "Vender", color: "bg-rose-500/15 text-rose-400 border-rose-500/30" };
  }
  return { label: "Neutro", color: "bg-amber-500/15 text-amber-400 border-amber-500/30" };
}

function sentimentFromChange(changePct?: number | null) {
  if (changePct == null || Number.isNaN(changePct)) return { label: "Neutro", tone: "neutral", score: 50 };
  if (changePct > 0.02) return { label: "Positivo", tone: "positive", score: 75 };
  if (changePct < -0.02) return { label: "Negativo", tone: "negative", score: 25 };
  return { label: "Neutro", tone: "neutral", score: 50 };
}

function buildChartData(history?: TickerHistory | null, forecast?: ForecastResponse | null) {
  const histPoints = history?.points || [];
  const forecastPoints = forecast?.forecast || [];

  type Row = {
    date: string;
    price?: number;
    forecast?: number;
    lower?: number;
    upper?: number;
  };

  const rows: Row[] = histPoints.map((p: HistoryPoint) => ({
    date: p.date,
    price: p.close ?? p.open,
  }));

  if (forecastPoints.length) {
    forecastPoints.forEach((f: ForecastPoint) => {
      rows.push({
        date: f.date,
        forecast: f.price,
        lower: f.lower,
        upper: f.upper,
      });
    });
  }
  return rows;
}

export function TickerDetailPage({
  ticker,
  onBack,
  onSwitchView,
}: {
  ticker: string;
  onBack?: () => void;
  onSwitchView?: (view: string) => void;
}) {
  const [activeTab, setActiveTab] = useState<Tab>("overview");
  const [info, setInfo] = useState<TickerInfo | null>(null);
  const [history, setHistory] = useState<TickerHistory | null>(null);
  const [technical, setTechnical] = useState<TechnicalAnalysis | null>(null);
  const [technicalExplain, setTechnicalExplain] = useState<TechnicalExplanation | null>(null);
  const [, setRecommendations] = useState<Recommendations | null>(null);
  const [news, setNews] = useState<News | null>(null);
  const [forecast, setForecast] = useState<ForecastResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingForecast, setLoadingForecast] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [aiQuestion, setAiQuestion] = useState("");

  async function loadAll() {
    setLoading(true);
    setError(null);
    try {
      const [infoRes, histRes, techRes, recRes, newsRes] = await Promise.all([
        getTickerInfo(ticker),
        getTickerHistory(ticker, "1y"),
        getTickerTechnical(ticker, "1y"),
        getTickerRecommendations(ticker),
        getTickerNews(ticker, 8),
      ]);
      setInfo(infoRes);
      setHistory(histRes);
      setTechnical(techRes);
      setRecommendations(recRes);
      setNews(newsRes);

      try {
        const explain = await getTickerTechnicalExplain(ticker, "1y");
        setTechnicalExplain(explain);
      } catch {}

      setLoadingForecast(true);
      try {
        const f = await runForecast({ ticker, future_days: 30, period: "1y", order: "2,1,2", backend: "arima" });
        setForecast(f);
      } catch (e) {
        // forecast is optional
      } finally {
        setLoadingForecast(false);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao carregar ticker");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadAll();
  }, [ticker]);

  const firstPrice = useMemo(() => history?.points?.[0]?.close ?? info?.price, [history, info]);
  const lastPrice = useMemo(
    () => history?.points?.[history.points.length - 1]?.close ?? info?.price,
    [history, info],
  );
  const changePct = useMemo(() => {
    if (firstPrice == null || lastPrice == null || firstPrice === 0) return undefined;
    return (lastPrice - firstPrice) / firstPrice;
  }, [firstPrice, lastPrice]);

  const sentiment = useMemo(() => sentimentFromChange(changePct), [changePct]);
  const recBadge = useMemo(() => recommendationBadge(info?.recommendation), [info?.recommendation]);

  const chartData = useMemo(() => buildChartData(history, forecast), [history, forecast]);

  const targetMean = info?.target_mean_price;
  const targetHigh = info?.target_high_price;
  const targetLow = info?.target_low_price;
  const upside = targetMean && lastPrice ? (targetMean - lastPrice) / lastPrice : undefined;

  const technicalSummary = technicalExplain?.combined_signal || technicalExplain?.summary;

  return (
    <div className="min-h-screen bg-[#0f1115] text-slate-300">
      {/* Topbar */}
      <header className="sticky top-0 z-30 glass-panel border-b border-white/10 bg-[#0f1115]/80 backdrop-blur-xl px-4 sm:px-6 py-3 flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <button
            onClick={() => onBack?.() || onSwitchView?.("dashboard")}
            className="neumorphic-btn p-2 rounded-xl hover:text-white transition"
          >
            <ArrowLeft size={20} />
          </button>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-lg font-bold tracking-tight text-white">{info?.name || ticker}</h1>
              <span className="text-xs text-slate-400">({ticker})</span>
            </div>
            <div className="text-xs text-slate-400">{info?.exchange || info?.sector}</div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={loadAll} className="neumorphic-btn p-2 rounded-xl hover:text-white transition" title="Atualizar">
            <RefreshCw size={18} className={loading ? "animate-spin" : ""} />
          </button>
          <button className="neumorphic-btn p-2 rounded-xl hover:text-white transition" title="Favorito">
            <Star size={18} />
          </button>
        </div>
      </header>

      {error && (
        <div className="mx-4 sm:mx-6 mt-4 rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-300 flex items-center gap-2 glow-accent">
          <AlertTriangle size={18} />
          {error}
        </div>
      )}

      <main className="max-w-7xl mx-auto p-4 sm:p-6 lg:p-8 space-y-6">
        {/* Hero */}
        <section className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2 glass-card gradient-border p-6">
            <div className="flex items-start justify-between">
              <div>
                <div className="flex items-center gap-3">
                  <div className="w-12 h-12 rounded-2xl bg-gradient-to-br from-teal-500/20 to-blue-500/20 text-teal-300 flex items-center justify-center text-xl font-bold border border-white/10">
                    {ticker.slice(0, 1)}
                  </div>
                  <div>
                    <h2 className="text-2xl font-bold text-white">{info?.name || ticker}</h2>
                    <div className="text-sm text-slate-400">
                      {info?.sector} {info?.industry ? `• ${info.industry}` : ""}
                    </div>
                  </div>
                </div>
                <div className="mt-6 flex items-baseline gap-3">
                  <span className="text-4xl sm:text-5xl font-bold text-white stat-value">{fmt(lastPrice)}</span>
                  <span className="text-sm text-slate-400">{info?.currency || "USD"}</span>
                </div>
                <div className={`mt-2 inline-flex items-center gap-1.5 text-sm font-semibold ${(changePct ?? 0) >= 0 ? "text-teal-400" : "text-rose-400"}`}>
                  {(changePct ?? 0) >= 0 ? <ArrowUpRight size={18} /> : <ArrowDownRight size={18} />}
                  {pct(changePct)} desde início do período
                </div>
              </div>
              <div className="text-right">
                <span className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold border ${recBadge.color}`}>
                  {recBadge.label}
                </span>
                <div className="mt-2 text-xs text-slate-400">Recomendação média</div>
                <div className="text-sm font-medium text-white">{info?.recommendation_mean ? info.recommendation_mean.toFixed(2) : "—"}</div>
              </div>
            </div>

            {/* Mini price chart */}
            <div className="mt-6 h-52 sm:h-64">
              {chartData.length > 0 ? (
                <ResponsiveContainer width="100%" height="100%">
                  <ComposedChart data={chartData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                    <defs>
                      <linearGradient id="priceFill" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#14b8a6" stopOpacity={0.25} />
                        <stop offset="100%" stopColor="#14b8a6" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" opacity={0.5} />
                    <XAxis dataKey="date" tick={{ fontSize: 11 }} stroke="#64748b" />
                    <YAxis tick={{ fontSize: 11 }} stroke="#64748b" domain={["auto", "auto"]} />
                    <Tooltip
                      contentStyle={{ background: "#0f1115", border: "1px solid rgba(255,255,255,0.1)", borderRadius: "0.75rem" }}
                      labelStyle={{ color: "#94a3b8" }}
                    />
                    <Legend />
                    <Area type="monotone" dataKey="price" stroke="#14b8a6" fill="url(#priceFill)" strokeWidth={2} dot={false} name="Preço" />
                    {forecast && (
                      <Line type="monotone" dataKey="forecast" stroke="#3b82f6" strokeWidth={2} dot={false} name="Previsão" />
                    )}
                    {forecast && (
                      <Area type="monotone" dataKey="upper" stroke="none" fill="#3b82f6" fillOpacity={0.08} name="Limite superior" />
                    )}
                    {forecast && (
                      <Area type="monotone" dataKey="lower" stroke="none" fill="#3b82f6" fillOpacity={0.08} name="Limite inferior" />
                    )}
                  </ComposedChart>
                </ResponsiveContainer>
              ) : (
                <div className="w-full h-full bg-white/5 rounded-xl animated-shimmer" />
              )}
            </div>
          </div>

          {/* Sentiment / Targets */}
          <div className="space-y-4">
            <div className="glass-card gradient-border p-5">
              <h3 className="font-semibold flex items-center gap-2 mb-4 text-white">
                <Activity size={18} className="text-teal-400" />
                Sentimento
              </h3>
              <div className="flex items-center gap-4">
                <div className="relative w-24 h-24">
                  <svg viewBox="0 0 36 36" className="w-full h-full -rotate-90">
                    <path d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" fill="none" stroke="#1e293b" strokeWidth="4" />
                    <path
                      d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
                      fill="none"
                      stroke={sentiment.tone === "positive" ? "#14b8a6" : sentiment.tone === "negative" ? "#f43f5e" : "#f59e0b"}
                      strokeDasharray={`${sentiment.score}, 100`}
                      strokeWidth="4"
                      strokeLinecap="round"
                    />
                  </svg>
                  <div className="absolute inset-0 flex flex-col items-center justify-center">
                    <span className="text-lg font-bold text-white stat-value">{sentiment.score}</span>
                    <span className="text-[10px] text-slate-400">score</span>
                  </div>
                </div>
                <div>
                  <div className={`text-xl font-bold ${sentiment.tone === "positive" ? "text-teal-400" : sentiment.tone === "negative" ? "text-rose-400" : "text-amber-400"}`}>
                    {sentiment.label}
                  </div>
                  <div className="text-sm text-slate-400">Baseado no movimento de preço</div>
                </div>
              </div>
            </div>

            <div className="glass-card gradient-border p-5">
              <h3 className="font-semibold flex items-center gap-2 mb-4 text-white">
                <Target size={18} className="text-blue-400" />
                Preços Alvo
              </h3>
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <span className="text-sm text-slate-400">Média analistas</span>
                  <span className="font-semibold text-white stat-value">{fmt(targetMean)}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-sm text-slate-400">Alto</span>
                  <span className="font-semibold text-white stat-value">{fmt(targetHigh)}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-sm text-slate-400">Baixo</span>
                  <span className="font-semibold text-white stat-value">{fmt(targetLow)}</span>
                </div>
                <div className="h-px bg-white/10" />
                <div className="flex items-center justify-between">
                  <span className="text-sm text-slate-400">Potencial</span>
                  <span className={`font-semibold stat-value ${(upside ?? 0) >= 0 ? "text-teal-400" : "text-rose-400"}`}>
                    {pct(upside)}
                  </span>
                </div>
              </div>
            </div>

            <div className="glass-card gradient-border glow-accent p-5">
              <div className="flex items-center gap-2 mb-2">
                <Zap size={18} className="text-amber-400" />
                <h3 className="font-semibold text-white">Queres saber mais?</h3>
              </div>
              <p className="text-sm text-slate-400 mb-3">Pergunta à IA sobre este ticker, notícias ou previsões.</p>
              <button
                onClick={() => onSwitchView?.("chat")}
                className="neumorphic-btn w-full py-2 rounded-xl text-sm font-medium transition flex items-center justify-center gap-2 text-white"
              >
                <MessageSquare size={16} />
                Falar com IA
              </button>
            </div>
          </div>
        </section>

        {/* Tabs */}
        <div className="glass-panel rounded-xl border border-white/10 p-1">
          <div className="flex gap-1 overflow-x-auto">
            <TabButton active={activeTab === "overview"} label="Visão Geral" onClick={() => setActiveTab("overview")} />
            <TabButton active={activeTab === "chart"} label="Gráfico em tempo real" onClick={() => setActiveTab("chart")} />
            <TabButton active={activeTab === "analysis"} label="Análise Técnica" onClick={() => setActiveTab("analysis")} />
            <TabButton active={activeTab === "forecast"} label="Previsão" onClick={() => setActiveTab("forecast")} />
            <TabButton active={activeTab === "sentiment"} label="Notícias & Sentimento" onClick={() => setActiveTab("sentiment")} />
          </div>
        </div>

        {activeTab === "overview" && (
          <div className="space-y-6">
            <div className="grid grid-cols-1 @4xl:grid-cols-3 gap-6">
            <div className="@4xl:col-span-2 glass-card gradient-border p-5">
              <h3 className="font-semibold mb-4 flex items-center gap-2 text-white">
                <BarChart3 size={18} className="text-blue-400" />
                Visão Geral
              </h3>
              <p className="text-sm text-slate-300 leading-relaxed">
                {info?.summary || technicalSummary || "Sem descrição disponível para este ativo."}
              </p>

              <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mt-6 data-grid">
                <Kpi label="Capitalização" value={compact(info?.market_cap)} />
                <Kpi label="P/E" value={fmt(info?.pe)} />
                <Kpi label="EPS" value={fmt(info?.eps)} />
                <Kpi label="Dividendo" value={pctFromRatio(info?.dividend_yield)} />
                <Kpi label="ROE" value={pctFromRatio(info?.roe)} />
                <Kpi label="Beta" value={fmt(info?.beta)} />
                <Kpi label="Analistas" value={info?.number_of_analysts ?? "—"} />
                <Kpi label="País" value={info?.country || "—"} />
              </div>
            </div>

            <div className="glass-card gradient-border p-5">
              <h3 className="font-semibold mb-4 text-white">Análise da IA</h3>
              <div className="space-y-4">
                <AiInsight icon={<TrendingUp size={18} />} label="Tendência de preço" value={technicalExplain?.price_trend || "Indisponível"} />
                <AiInsight icon={<Activity size={18} />} label="RSI (14)" value={technicalExplain?.rsi_analysis || "Indisponível"} />
                <AiInsight icon={<BarChart3 size={18} />} label="MACD" value={technicalExplain?.macd_analysis || "Indisponível"} />
                <AiInsight icon={<Target size={18} />} label="Bandas de Bollinger" value={technicalExplain?.bb_analysis || "Indisponível"} />
                <AiInsight icon={<CheckCircle size={18} />} label="Sinal combinado" value={technicalSummary || "Indisponível"} />
              </div>
            </div>            </div>

            {info?.kpis && Object.keys(info.kpis).length > 0 && (
              <section className="@container space-y-3">
                <div className="flex flex-wrap items-baseline gap-2">
                  <h2 className="text-sm font-semibold text-white">Indicadores</h2>
                  <span className="text-xs text-slate-500">
                    múltiplos, margens, resultados, balanço, analistas e mercado
                  </span>
                </div>
                <TickerKpiCards kpis={info.kpis} currency={info.currency} />
              </section>
            )}          </div>
        )}

        {activeTab === "chart" && (
          <div className="glass-card gradient-border p-5 flex flex-col gap-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="min-w-0">
                <h3 className="font-semibold flex items-center gap-2 text-white">
                  <CandlestickChart size={18} className="text-emerald-400" />
                  Cotação em tempo real
                </h3>
                <p className="text-xs text-slate-400">
                  Gráfico interativo da TradingView para <span className="font-mono">{tradingViewSymbol(ticker, info?.exchange)}</span>
                  {" "}— velas, intervalos, indicadores e ferramentas de desenho.
                </p>
              </div>
              <button
                type="button"
                onClick={() => onSwitchView?.("ticker-chart")}
                className="neumorphic-btn px-3 py-1.5 rounded-xl text-sm flex items-center gap-2 text-white"
              >
                <Maximize2 size={15} /> Abrir em janela
              </button>
            </div>
            <div className="h-[520px] min-h-[360px]">
              <TradingViewChart symbol={tradingViewSymbol(ticker, info?.exchange)} />
            </div>
          </div>
        )}

        {activeTab === "analysis" && (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <div className="lg:col-span-2 glass-card gradient-border p-5">
              <h3 className="font-semibold mb-4 text-white">Indicadores técnicos</h3>
              <div className="h-80">
                {technical?.points?.length ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <ComposedChart data={technical.points.slice(-90)} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" opacity={0.5} />
                      <XAxis dataKey="date" tick={{ fontSize: 11 }} stroke="#64748b" />
                      <YAxis yAxisId="left" tick={{ fontSize: 11 }} stroke="#64748b" domain={["auto", "auto"]} />
                      <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 11 }} stroke="#64748b" domain={[0, 100]} />
                      <Tooltip
                        contentStyle={{ background: "#0f1115", border: "1px solid rgba(255,255,255,0.1)", borderRadius: "0.75rem" }}
                        labelStyle={{ color: "#94a3b8" }}
                      />
                      <Legend />
                      <Line yAxisId="left" type="monotone" dataKey="sma20" stroke="#14b8a6" strokeWidth={1.5} dot={false} name="SMA20" />
                      <Line yAxisId="left" type="monotone" dataKey="sma50" stroke="#3b82f6" strokeWidth={1.5} dot={false} name="SMA50" />
                      <Line yAxisId="left" type="monotone" dataKey="sma200" stroke="#f59e0b" strokeWidth={1.5} dot={false} name="SMA200" />
                      <Line yAxisId="right" type="monotone" dataKey="rsi14" stroke="#f43f5e" strokeWidth={2} dot={false} name="RSI14" />
                    </ComposedChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="w-full h-full bg-white/5 rounded-xl animated-shimmer" />
                )}
              </div>
            </div>

            <div className="glass-card gradient-border p-5">
              <h3 className="font-semibold mb-4 text-white">Destaques técnicos</h3>
              <div className="space-y-3 text-sm">
                <TechRow label="Último RSI" value={fmt(technical?.points?.[technical.points.length - 1]?.rsi14)} />
                <TechRow label="MACD" value={fmt(technical?.points?.[technical.points.length - 1]?.macd)} />
                <TechRow label="Sinal MACD" value={fmt(technical?.points?.[technical.points.length - 1]?.macd_signal)} />
                <TechRow label="Banda superior" value={fmt(technical?.points?.[technical.points.length - 1]?.bb_upper)} />
                <TechRow label="Banda inferior" value={fmt(technical?.points?.[technical.points.length - 1]?.bb_lower)} />
                <TechRow label="ATR (14)" value={fmt(technical?.points?.[technical.points.length - 1]?.atr14)} />
                <TechRow label="OBV" value={compact(technical?.points?.[technical.points.length - 1]?.obv)} />
              </div>
            </div>
          </div>
        )}

        {activeTab === "forecast" && (
          <div className="glass-card gradient-border p-5">
            <div className="flex items-center justify-between mb-4">
              <h3 className="font-semibold flex items-center gap-2 text-white">
                <TrendingUp size={18} className="text-teal-400" />
                Previsão de preço (ARIMA)
              </h3>
              {forecast && (
                <div className="text-xs text-slate-400">
                  MAPE: {forecast.mape?.toFixed(2) ?? "—"}% • RMSE: {fmt(forecast.rmse)}
                </div>
              )}
            </div>
            <div className="h-80">
              {forecast ? (
                <ResponsiveContainer width="100%" height="100%">
                  <ComposedChart data={chartData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" opacity={0.5} />
                    <XAxis dataKey="date" tick={{ fontSize: 11 }} stroke="#64748b" />
                    <YAxis tick={{ fontSize: 11 }} stroke="#64748b" domain={["auto", "auto"]} />
                    <Tooltip
                      contentStyle={{ background: "#0f1115", border: "1px solid rgba(255,255,255,0.1)", borderRadius: "0.75rem" }}
                      labelStyle={{ color: "#94a3b8" }}
                    />
                    <Legend />
                    <Area type="monotone" dataKey="price" stroke="#14b8a6" fill="url(#priceFill)" strokeWidth={2} dot={false} name="Histórico" />
                    <Line type="monotone" dataKey="forecast" stroke="#3b82f6" strokeWidth={2} dot={false} name="Previsão" />
                    <Line type="monotone" dataKey="upper" stroke="#3b82f6" strokeDasharray="4 4" strokeWidth={1} dot={false} name="Limite superior" />
                    <Line type="monotone" dataKey="lower" stroke="#3b82f6" strokeDasharray="4 4" strokeWidth={1} dot={false} name="Limite inferior" />
                  </ComposedChart>
                </ResponsiveContainer>
              ) : loadingForecast ? (
                <div className="w-full h-full flex items-center justify-center text-slate-400">
                  A calcular previsão…
                </div>
              ) : (
                <div className="w-full h-full flex items-center justify-center text-slate-400">
                  Previsão indisponível.
                </div>
              )}
            </div>
            {forecast?.explanation && (
              <p className="mt-4 text-sm text-slate-300 leading-relaxed">{forecast.explanation}</p>
            )}
          </div>
        )}

        {activeTab === "sentiment" && (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <div className="lg:col-span-2 glass-card gradient-border p-5">
              <h3 className="font-semibold mb-4 flex items-center gap-2 text-white">
                <Newspaper size={18} className="text-blue-400" />
                Notícias recentes
              </h3>
              <div className="space-y-3">
                {news?.news?.length ? (
                  news.news.map((item, i) => (
                    <a
                      key={i}
                      href={item.url || "#"}
                      target="_blank"
                      rel="noreferrer"
                      className="flex items-start gap-4 p-3 rounded-xl hover:bg-white/5 transition group"
                    >
                      <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-blue-500/20 to-teal-500/20 flex items-center justify-center shrink-0 font-bold text-sm text-white border border-white/10">
                        {ticker.slice(0, 1)}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="text-xs text-slate-400">{item.published || item.publisher}</div>
                        <div className="text-sm font-medium mt-0.5 line-clamp-2 group-hover:text-teal-300 transition text-slate-200">
                          {item.title || "Sem título"}
                        </div>
                      </div>
                      <span className="text-xs px-2 py-1 rounded-full bg-teal-500/15 text-teal-400 border border-teal-500/30 shrink-0">
                        Positivo
                      </span>
                    </a>
                  ))
                ) : (
                  <div className="text-sm text-slate-400">Sem notícias disponíveis.</div>
                )}
              </div>
            </div>

            <div className="glass-card gradient-border p-5">
              <h3 className="font-semibold mb-4 text-white">Distribuição de sentimento</h3>
              <div className="space-y-3">
                <SentimentRow color="#14b8a6" label="Positivo" value={sentiment.tone === "positive" ? 62 : 18} />
                <SentimentRow color="#94a3b8" label="Neutro" value={sentiment.tone === "neutral" ? 62 : 24} />
                <SentimentRow color="#f43f5e" label="Negativo" value={sentiment.tone === "negative" ? 62 : 14} />
              </div>
              <div className="mt-5 p-4 rounded-xl bg-white/5 border border-white/10">
                <div className="text-xs text-slate-400 mb-1">Recomendação de analistas</div>
                <div className="text-lg font-bold text-white stat-value">{recBadge.label}</div>
                <div className="text-xs text-slate-400 mt-1">
                  {info?.number_of_analysts ? `${info.number_of_analysts} analistas acompanhando` : "Sem dados de analistas"}
                </div>
              </div>

              <div className="mt-5">
                <label className="text-xs text-slate-400">Pergunta à IA sobre notícias</label>
                <div className="flex gap-2 mt-1.5">
                  <input
                    value={aiQuestion}
                    onChange={(e) => setAiQuestion(e.target.value)}
                    placeholder="Ex: impacto das últimas notícias?"
                    className="flex-1 bg-[#0f1115] rounded-lg px-3 py-2 text-sm outline-none border border-white/10 focus:border-teal-500/50 text-slate-200 placeholder:text-slate-500"
                  />
                  <button
                    onClick={() => {
                      if (!aiQuestion.trim()) return;
                      onSwitchView?.("chat");
                    }}
                    className="neumorphic-btn px-3 py-2 rounded-lg text-white"
                  >
                    <ChevronRight size={18} />
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

function TabButton({ active, label, onClick }: { active: boolean; label: string; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={`px-4 py-2 text-sm font-medium rounded-lg transition whitespace-nowrap ${
        active
          ? "bg-white/10 text-white border border-white/10 shadow-[inset_0_1px_0_rgba(255,255,255,0.1)]"
          : "text-slate-400 hover:text-white hover:bg-white/5"
      }`}
    >
      {label}
    </button>
  );
}

function Kpi({ label, value }: { label: string; value?: string | number }) {
  return (
    <div className="p-3 rounded-xl bg-white/5 border border-white/10">
      <div className="text-xs text-slate-400">{label}</div>
      <div className="text-base font-semibold mt-0.5 text-white stat-value">{value ?? "—"}</div>
    </div>
  );
}

function AiInsight({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div className="flex gap-3">
      <div className="mt-0.5 text-teal-400">{icon}</div>
      <div>
        <div className="text-xs text-slate-400">{label}</div>
        <div className="text-sm font-medium leading-snug text-slate-200">{value}</div>
      </div>
    </div>
  );
}

function TechRow({ label, value }: { label: string; value?: string | number }) {
  return (
    <div className="flex items-center justify-between py-1.5 border-b border-white/10 last:border-0">
      <span className="text-slate-400">{label}</span>
      <span className="font-medium text-white stat-value">{value ?? "—"}</span>
    </div>
  );
}

function SentimentRow({ color, label, value }: { color: string; label: string; value: number }) {
  return (
    <div className="flex items-center gap-3">
      <span className="w-3 h-3 rounded-full" style={{ background: color }} />
      <span className="text-sm text-slate-400 flex-1">{label}</span>
      <span className="text-sm font-semibold text-white stat-value">{value}%</span>
    </div>
  );
}