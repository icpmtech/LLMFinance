import { useEffect, useMemo, useState } from "react";
import {
  ArrowLeft,
  ArrowUpRight,
  ArrowDownRight,
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

type Tab = "overview" | "analysis" | "forecast" | "sentiment";

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
  // O backend já normaliza dividend_yield e roe para valores percentuais
  // (e.g. 0.33 para 0.33%, 148.75 para 148.75%). Apenas formatamos.
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
    return { label: "Vender", color: "bg-red-500/15 text-red-400 border-red-500/30" };
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
    <div className="min-h-screen bg-[#0b0d12] text-foreground">
      {/* Topbar */}
      <header className="sticky top-0 z-30 border-b border-border/60 bg-[#0b0d12]/90 backdrop-blur px-4 sm:px-6 py-3 flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <button
            onClick={() => onBack?.() || onSwitchView?.("dashboard")}
            className="p-2 rounded-xl hover:bg-accent transition"
          >
            <ArrowLeft size={20} />
          </button>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-lg font-bold tracking-tight">{info?.name || ticker}</h1>
              <span className="text-xs text-muted-foreground">({ticker})</span>
            </div>
            <div className="text-xs text-muted-foreground">{info?.exchange || info?.sector}</div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={loadAll} className="p-2 rounded-xl hover:bg-accent transition" title="Atualizar">
            <RefreshCw size={18} className={loading ? "animate-spin" : ""} />
          </button>
          <button className="p-2 rounded-xl hover:bg-accent transition" title="Favorito">
            <Star size={18} />
          </button>
        </div>
      </header>

      {error && (
        <div className="mx-4 sm:mx-6 mt-4 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300 flex items-center gap-2">
          <AlertTriangle size={18} />
          {error}
        </div>
      )}

      <main className="max-w-7xl mx-auto p-4 sm:p-6 lg:p-8 space-y-6">
        {/* Hero */}
        <section className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2 rounded-2xl border border-border bg-card p-6">
            <div className="flex items-start justify-between">
              <div>
                <div className="flex items-center gap-3">
                  <div className="w-12 h-12 rounded-2xl bg-primary/15 text-primary flex items-center justify-center text-xl font-bold">
                    {ticker.slice(0, 1)}
                  </div>
                  <div>
                    <h2 className="text-2xl font-bold">{info?.name || ticker}</h2>
                    <div className="text-sm text-muted-foreground">
                      {info?.sector} {info?.industry ? `• ${info.industry}` : ""}
                    </div>
                  </div>
                </div>
                <div className="mt-6 flex items-baseline gap-3">
                  <span className="text-4xl sm:text-5xl font-bold">{fmt(lastPrice)}</span>
                  <span className="text-sm text-muted-foreground">{info?.currency || "USD"}</span>
                </div>
                <div className={`mt-2 inline-flex items-center gap-1.5 text-sm font-semibold ${(changePct ?? 0) >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                  {(changePct ?? 0) >= 0 ? <ArrowUpRight size={18} /> : <ArrowDownRight size={18} />}
                  {pct(changePct)} desde início do período
                </div>
              </div>
              <div className="text-right">
                <span className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold border ${recBadge.color}`}>
                  {recBadge.label}
                </span>
                <div className="mt-2 text-xs text-muted-foreground">Recomendação média</div>
                <div className="text-sm font-medium">{info?.recommendation_mean ? info.recommendation_mean.toFixed(2) : "—"}</div>
              </div>
            </div>

            {/* Mini price chart */}
            <div className="mt-6 h-52 sm:h-64">
              {chartData.length > 0 ? (
                <ResponsiveContainer width="100%" height="100%">
                  <ComposedChart data={chartData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                    <defs>
                      <linearGradient id="priceFill" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#10a37f" stopOpacity={0.25} />
                        <stop offset="100%" stopColor="#10a37f" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="#2e323b" opacity={0.5} />
                    <XAxis dataKey="date" tick={{ fontSize: 11 }} stroke="#6b7280" />
                    <YAxis tick={{ fontSize: 11 }} stroke="#6b7280" domain={["auto", "auto"]} />
                    <Tooltip
                      contentStyle={{ background: "#16181d", border: "1px solid #2e323b", borderRadius: "0.75rem" }}
                      labelStyle={{ color: "#9ca3af" }}
                    />
                    <Legend />
                    <Area type="monotone" dataKey="price" stroke="#10a37f" fill="url(#priceFill)" strokeWidth={2} dot={false} name="Preço" />
                    {forecast && (
                      <Line type="monotone" dataKey="forecast" stroke="#38bdf8" strokeWidth={2} dot={false} name="Previsão" />
                    )}
                    {forecast && (
                      <Area type="monotone" dataKey="upper" stroke="none" fill="#38bdf8" fillOpacity={0.08} name="Limite superior" />
                    )}
                    {forecast && (
                      <Area type="monotone" dataKey="lower" stroke="none" fill="#38bdf8" fillOpacity={0.08} name="Limite inferior" />
                    )}
                  </ComposedChart>
                </ResponsiveContainer>
              ) : (
                <div className="w-full h-full bg-muted/30 rounded-xl animate-pulse" />
              )}
            </div>
          </div>

          {/* Sentiment / Targets */}
          <div className="space-y-4">
            <div className="rounded-2xl border border-border bg-card p-5">
              <h3 className="font-semibold flex items-center gap-2 mb-4">
                <Activity size={18} className="text-primary" />
                Sentimento
              </h3>
              <div className="flex items-center gap-4">
                <div className="relative w-24 h-24">
                  <svg viewBox="0 0 36 36" className="w-full h-full -rotate-90">
                    <path d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" fill="none" stroke="#1e2128" strokeWidth="4" />
                    <path
                      d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
                      fill="none"
                      stroke={sentiment.tone === "positive" ? "#10b981" : sentiment.tone === "negative" ? "#ef4444" : "#f59e0b"}
                      strokeDasharray={`${sentiment.score}, 100`}
                      strokeWidth="4"
                      strokeLinecap="round"
                    />
                  </svg>
                  <div className="absolute inset-0 flex flex-col items-center justify-center">
                    <span className="text-lg font-bold">{sentiment.score}</span>
                    <span className="text-[10px] text-muted-foreground">score</span>
                  </div>
                </div>
                <div>
                  <div className={`text-xl font-bold ${sentiment.tone === "positive" ? "text-emerald-400" : sentiment.tone === "negative" ? "text-red-400" : "text-amber-400"}`}>
                    {sentiment.label}
                  </div>
                  <div className="text-sm text-muted-foreground">Baseado no movimento de preço</div>
                </div>
              </div>
            </div>

            <div className="rounded-2xl border border-border bg-card p-5">
              <h3 className="font-semibold flex items-center gap-2 mb-4">
                <Target size={18} className="text-primary" />
                Preços Alvo
              </h3>
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <span className="text-sm text-muted-foreground">Média analistas</span>
                  <span className="font-semibold">{fmt(targetMean)}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-sm text-muted-foreground">Alto</span>
                  <span className="font-semibold">{fmt(targetHigh)}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-sm text-muted-foreground">Baixo</span>
                  <span className="font-semibold">{fmt(targetLow)}</span>
                </div>
                <div className="h-px bg-border" />
                <div className="flex items-center justify-between">
                  <span className="text-sm text-muted-foreground">Potencial</span>
                  <span className={`font-semibold ${(upside ?? 0) >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                    {pct(upside)}
                  </span>
                </div>
              </div>
            </div>

            <div className="rounded-2xl border border-border bg-gradient-to-br from-card to-muted p-5">
              <div className="flex items-center gap-2 mb-2">
                <Zap size={18} className="text-primary" />
                <h3 className="font-semibold">Queres saber mais?</h3>
              </div>
              <p className="text-sm text-muted-foreground mb-3">Pergunta à IA sobre este ticker, notícias ou previsões.</p>
              <button
                onClick={() => onSwitchView?.("chat")}
                className="w-full py-2 rounded-xl bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 transition flex items-center justify-center gap-2"
              >
                <MessageSquare size={16} />
                Falar com IA
              </button>
            </div>
          </div>
        </section>

        {/* Tabs */}
        <div className="border-b border-border">
          <div className="flex gap-1 overflow-x-auto">
            <TabButton active={activeTab === "overview"} label="Visão Geral" onClick={() => setActiveTab("overview")} />
            <TabButton active={activeTab === "analysis"} label="Análise Técnica" onClick={() => setActiveTab("analysis")} />
            <TabButton active={activeTab === "forecast"} label="Previsão" onClick={() => setActiveTab("forecast")} />
            <TabButton active={activeTab === "sentiment"} label="Notícias & Sentimento" onClick={() => setActiveTab("sentiment")} />
          </div>
        </div>

        {activeTab === "overview" && (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <div className="lg:col-span-2 rounded-2xl border border-border bg-card p-5">
              <h3 className="font-semibold mb-4 flex items-center gap-2">
                <BarChart3 size={18} className="text-primary" />
                Visão Geral
              </h3>
              <p className="text-sm text-muted-foreground leading-relaxed">
                {info?.summary || technicalSummary || "Sem descrição disponível para este ativo."}
              </p>

              <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mt-6">
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

            <div className="rounded-2xl border border-border bg-card p-5">
              <h3 className="font-semibold mb-4">Análise da IA</h3>
              <div className="space-y-4">
                <AiInsight icon={<TrendingUp size={18} />} label="Tendência de preço" value={technicalExplain?.price_trend || "Indisponível"} />
                <AiInsight icon={<Activity size={18} />} label="RSI (14)" value={technicalExplain?.rsi_analysis || "Indisponível"} />
                <AiInsight icon={<BarChart3 size={18} />} label="MACD" value={technicalExplain?.macd_analysis || "Indisponível"} />
                <AiInsight icon={<Target size={18} />} label="Bandas de Bollinger" value={technicalExplain?.bb_analysis || "Indisponível"} />
                <AiInsight icon={<CheckCircle size={18} />} label="Sinal combinado" value={technicalSummary || "Indisponível"} />
              </div>
            </div>
          </div>
        )}

        {activeTab === "analysis" && (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <div className="lg:col-span-2 rounded-2xl border border-border bg-card p-5">
              <h3 className="font-semibold mb-4">Indicadores técnicos</h3>
              <div className="h-80">
                {technical?.points?.length ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <ComposedChart data={technical.points.slice(-90)} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#2e323b" opacity={0.5} />
                      <XAxis dataKey="date" tick={{ fontSize: 11 }} stroke="#6b7280" />
                      <YAxis yAxisId="left" tick={{ fontSize: 11 }} stroke="#6b7280" domain={["auto", "auto"]} />
                      <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 11 }} stroke="#6b7280" domain={[0, 100]} />
                      <Tooltip
                        contentStyle={{ background: "#16181d", border: "1px solid #2e323b", borderRadius: "0.75rem" }}
                        labelStyle={{ color: "#9ca3af" }}
                      />
                      <Legend />
                      <Line yAxisId="left" type="monotone" dataKey="sma20" stroke="#10a37f" strokeWidth={1.5} dot={false} name="SMA20" />
                      <Line yAxisId="left" type="monotone" dataKey="sma50" stroke="#38bdf8" strokeWidth={1.5} dot={false} name="SMA50" />
                      <Line yAxisId="left" type="monotone" dataKey="sma200" stroke="#f59e0b" strokeWidth={1.5} dot={false} name="SMA200" />
                      <Line yAxisId="right" type="monotone" dataKey="rsi14" stroke="#ef4444" strokeWidth={2} dot={false} name="RSI14" />
                    </ComposedChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="w-full h-full bg-muted/30 rounded-xl animate-pulse" />
                )}
              </div>
            </div>

            <div className="rounded-2xl border border-border bg-card p-5">
              <h3 className="font-semibold mb-4">Destaques técnicos</h3>
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
          <div className="rounded-2xl border border-border bg-card p-5">
            <div className="flex items-center justify-between mb-4">
              <h3 className="font-semibold flex items-center gap-2">
                <TrendingUp size={18} className="text-primary" />
                Previsão de preço (ARIMA)
              </h3>
              {forecast && (
                <div className="text-xs text-muted-foreground">
                  MAPE: {forecast.mape?.toFixed(2) ?? "—"}% • RMSE: {fmt(forecast.rmse)}
                </div>
              )}
            </div>
            <div className="h-80">
              {forecast ? (
                <ResponsiveContainer width="100%" height="100%">
                  <ComposedChart data={chartData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#2e323b" opacity={0.5} />
                    <XAxis dataKey="date" tick={{ fontSize: 11 }} stroke="#6b7280" />
                    <YAxis tick={{ fontSize: 11 }} stroke="#6b7280" domain={["auto", "auto"]} />
                    <Tooltip
                      contentStyle={{ background: "#16181d", border: "1px solid #2e323b", borderRadius: "0.75rem" }}
                      labelStyle={{ color: "#9ca3af" }}
                    />
                    <Legend />
                    <Area type="monotone" dataKey="price" stroke="#10a37f" fill="url(#priceFill)" strokeWidth={2} dot={false} name="Histórico" />
                    <Line type="monotone" dataKey="forecast" stroke="#38bdf8" strokeWidth={2} dot={false} name="Previsão" />
                    <Line type="monotone" dataKey="upper" stroke="#38bdf8" strokeDasharray="4 4" strokeWidth={1} dot={false} name="Limite superior" />
                    <Line type="monotone" dataKey="lower" stroke="#38bdf8" strokeDasharray="4 4" strokeWidth={1} dot={false} name="Limite inferior" />
                  </ComposedChart>
                </ResponsiveContainer>
              ) : loadingForecast ? (
                <div className="w-full h-full flex items-center justify-center text-muted-foreground">
                  A calcular previsão…
                </div>
              ) : (
                <div className="w-full h-full flex items-center justify-center text-muted-foreground">
                  Previsão indisponível.
                </div>
              )}
            </div>
            {forecast?.explanation && (
              <p className="mt-4 text-sm text-muted-foreground leading-relaxed">{forecast.explanation}</p>
            )}
          </div>
        )}

        {activeTab === "sentiment" && (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <div className="lg:col-span-2 rounded-2xl border border-border bg-card p-5">
              <h3 className="font-semibold mb-4 flex items-center gap-2">
                <Newspaper size={18} className="text-primary" />
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
                      className="flex items-start gap-4 p-3 rounded-xl hover:bg-accent/40 transition group"
                    >
                      <div className="w-10 h-10 rounded-xl bg-muted flex items-center justify-center shrink-0 font-bold text-sm">
                        {ticker.slice(0, 1)}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="text-xs text-muted-foreground">{item.published || item.publisher}</div>
                        <div className="text-sm font-medium mt-0.5 line-clamp-2 group-hover:text-primary transition">
                          {item.title || "Sem título"}
                        </div>
                      </div>
                      <span className="text-xs px-2 py-1 rounded-full bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 shrink-0">
                        Positivo
                      </span>
                    </a>
                  ))
                ) : (
                  <div className="text-sm text-muted-foreground">Sem notícias disponíveis.</div>
                )}
              </div>
            </div>

            <div className="rounded-2xl border border-border bg-card p-5">
              <h3 className="font-semibold mb-4">Distribuição de sentimento</h3>
              <div className="space-y-3">
                <SentimentRow color="#10b981" label="Positivo" value={sentiment.tone === "positive" ? 62 : 18} />
                <SentimentRow color="#9ca3af" label="Neutro" value={sentiment.tone === "neutral" ? 62 : 24} />
                <SentimentRow color="#ef4444" label="Negativo" value={sentiment.tone === "negative" ? 62 : 14} />
              </div>
              <div className="mt-5 p-4 rounded-xl bg-muted/50">
                <div className="text-xs text-muted-foreground mb-1">Recomendação de analistas</div>
                <div className="text-lg font-bold">{recBadge.label}</div>
                <div className="text-xs text-muted-foreground mt-1">
                  {info?.number_of_analysts ? `${info.number_of_analysts} analistas acompanhando` : "Sem dados de analistas"}
                </div>
              </div>

              <div className="mt-5">
                <label className="text-xs text-muted-foreground">Pergunta à IA sobre notícias</label>
                <div className="flex gap-2 mt-1.5">
                  <input
                    value={aiQuestion}
                    onChange={(e) => setAiQuestion(e.target.value)}
                    placeholder="Ex: impacto das últimas notícias?"
                    className="flex-1 bg-muted rounded-lg px-3 py-2 text-sm outline-none border border-border focus:border-primary"
                  />
                  <button
                    onClick={() => {
                      if (!aiQuestion.trim()) return;
                      onSwitchView?.("chat");
                    }}
                    className="px-3 py-2 rounded-lg bg-primary text-primary-foreground"
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
      className={`px-4 py-3 text-sm font-medium border-b-2 transition whitespace-nowrap ${
        active ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:text-foreground"
      }`}
    >
      {label}
    </button>
  );
}

function Kpi({ label, value }: { label: string; value?: string | number }) {
  return (
    <div className="p-3 rounded-xl bg-muted/50">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="text-base font-semibold mt-0.5">{value ?? "—"}</div>
    </div>
  );
}

function AiInsight({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div className="flex gap-3">
      <div className="mt-0.5 text-primary">{icon}</div>
      <div>
        <div className="text-xs text-muted-foreground">{label}</div>
        <div className="text-sm font-medium leading-snug">{value}</div>
      </div>
    </div>
  );
}

function TechRow({ label, value }: { label: string; value?: string | number }) {
  return (
    <div className="flex items-center justify-between py-1.5 border-b border-border/40 last:border-0">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium">{value ?? "—"}</span>
    </div>
  );
}

function SentimentRow({ color, label, value }: { color: string; label: string; value: number }) {
  return (
    <div className="flex items-center gap-3">
      <span className="w-3 h-3 rounded-full" style={{ background: color }} />
      <span className="text-sm text-muted-foreground flex-1">{label}</span>
      <span className="text-sm font-semibold">{value}%</span>
    </div>
  );
}
