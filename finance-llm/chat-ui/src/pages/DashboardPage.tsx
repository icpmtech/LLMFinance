import { useEffect, useState } from "react";
import {
  ArrowUpRight,
  ArrowDownRight,
  TrendingUp,
  Newspaper,
  Search,
  Bell,
  Zap,
  BarChart3,
  PieChart,
  Activity,
  RefreshCw,
  ChevronRight,
  Home,
  LineChart,
  FolderOpen,
  Database,
  MessageSquare,
} from "lucide-react";
import {
  Area,
  AreaChart,
  ResponsiveContainer,
  XAxis,
  YAxis,
} from "recharts";
import {
  getTickerHistory,
  getTickerInfo,
  getTickerNews,
  searchYahooTickers,
} from "../api";
import type { HistoryPoint, News, NewsItem, TickerHistory, TickerInfo } from "../types";

type MarketSnapshot = {
  ticker: string;
  name?: string;
  price?: number;
  change?: number;
  changePct?: number;
  currency?: string;
};

const DEFAULT_INDICES = [
  { ticker: "^GSPC", label: "S&P 500" },
  { ticker: "^IXIC", label: "NASDAQ" },
  { ticker: "BTC-USD", label: "BTC" },
];

const WATCHLIST = [
  { ticker: "AAPL", name: "Apple Inc." },
  { ticker: "MSFT", name: "Microsoft" },
  { ticker: "TSLA", name: "Tesla" },
  { ticker: "NVDA", name: "NVIDIA" },
  { ticker: "AMZN", name: "Amazon" },
];

function fmt(n?: number | null) {
  if (n == null || Number.isNaN(n)) return "—";
  return n.toLocaleString("pt-PT", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function pct(n?: number | null) {
  if (n == null || Number.isNaN(n)) return "—";
  const sign = n > 0 ? "+" : "";
  return `${sign}${(n * 100).toFixed(2)}%`;
}

function sparkData(history?: TickerHistory | null) {
  if (!history?.points?.length) return [];
  return history.points.map((p: HistoryPoint) => ({ date: p.date, value: p.close ?? p.open }));
}

export function DashboardPage({
  onSwitchView,
  onSelectTicker,
}: {
  onSwitchView?: (view: string) => void;
  onSelectTicker?: (ticker: string) => void;
}) {
  const [indices, setIndices] = useState<MarketSnapshot[]>([]);
  const [watchlist, setWatchlist] = useState<MarketSnapshot[]>([]);
  const [historyMap, setHistoryMap] = useState<Record<string, TickerHistory>>({});
  const [news, setNews] = useState<NewsItem[]>([]);
  const [search, setSearch] = useState("");
  const [searchResults, setSearchResults] = useState<{ symbol: string; name?: string }[]>([]);
  const [loading, setLoading] = useState(false);
  const [sentiment] = useState({ positive: 62, neutral: 24, negative: 14 });
  const [, setSelectedTicker] = useState<string | null>(null);

  async function loadSnapshot(ticker: string): Promise<MarketSnapshot> {
    try {
      const info: TickerInfo = await getTickerInfo(ticker);
      const hist: TickerHistory = await getTickerHistory(ticker, "1mo");
      const first = hist?.points?.[0]?.close ?? info.price ?? 0;
      const last = hist?.points?.[hist.points.length - 1]?.close ?? info.price ?? 0;
      const change = first && last ? last - first : undefined;
      const changePct = first && last ? (last - first) / first : undefined;
      return {
        ticker: info.ticker || ticker,
        name: info.name,
        price: info.price ?? last,
        change,
        changePct,
        currency: info.currency,
      };
    } catch (e) {
      return { ticker, name: ticker };
    }
  }

  async function loadEverything() {
    setLoading(true);
    try {
      const idx = await Promise.all(DEFAULT_INDICES.map((i) => loadSnapshot(i.ticker)));
      setIndices(idx);
      const wl = await Promise.all(WATCHLIST.map((w) => loadSnapshot(w.ticker)));
      setWatchlist(wl);

      const histMap: Record<string, TickerHistory> = {};
      await Promise.all(
        wl.map(async (s) => {
          try {
            const h = await getTickerHistory(s.ticker, "1mo");
            histMap[s.ticker] = h;
          } catch {}
        })
      );
      setHistoryMap(histMap);

      const allNews: NewsItem[] = [];
      await Promise.all(
        wl.slice(0, 3).map(async (s) => {
          try {
            const n: News = await getTickerNews(s.ticker, 4);
            allNews.push(...(n.news || []).map((item) => ({ ...item, ticker: s.ticker })));
          } catch {}
        })
      );
      setNews(allNews.slice(0, 6));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadEverything();
  }, []);

  useEffect(() => {
    const timer = setTimeout(async () => {
      if (search.trim().length < 2) {
        setSearchResults([]);
        return;
      }
      try {
        const res = await searchYahooTickers(search.trim());
        setSearchResults((res.yahoo_results || []).slice(0, 6));
      } catch {
        setSearchResults([]);
      }
    }, 300);
    return () => clearTimeout(timer);
  }, [search]);

  function handleSelect(symbol: string) {
    setSelectedTicker(symbol);
    if (onSelectTicker) {
      onSelectTicker(symbol);
    } else if (onSwitchView) {
      onSwitchView("ticker-detail");
    }
  }

  const sentimentColor =
    sentiment.positive >= sentiment.neutral + sentiment.negative ? "text-emerald-400" : "text-amber-400";

  return (
    <div className="min-h-screen bg-[#0b0d12] text-foreground">
      {/* Topbar */}
      <header className="sticky top-0 z-30 border-b border-border/60 bg-[#0b0d12]/90 backdrop-blur px-4 sm:px-6 py-3 flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 text-primary">
            <BarChart3 size={28} strokeWidth={2.5} />
          </div>
          <div>
            <h1 className="text-lg font-bold tracking-tight">Sentiment Market</h1>
          </div>
        </div>
        <div className="flex-1 max-w-xl relative hidden sm:block">
          <div className="flex items-center gap-2 rounded-xl border border-border bg-card px-3 py-2">
            <Search size={16} className="text-muted-foreground" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Pesquisar empresa, ticker ou tema..."
              className="flex-1 bg-transparent outline-none text-sm placeholder:text-muted-foreground"
            />
          </div>
          {searchResults.length > 0 && (
            <div className="absolute mt-2 w-full rounded-xl border border-border bg-card shadow-xl overflow-hidden">
              {searchResults.map((r) => (
                <button
                  key={r.symbol}
                  onClick={() => {
                    setSearch("");
                    setSearchResults([]);
                    handleSelect(r.symbol);
                  }}
                  className="w-full text-left px-4 py-2 hover:bg-accent transition text-sm"
                >
                  <span className="font-semibold">{r.symbol}</span>
                  <span className="text-muted-foreground ml-2">{r.name}</span>
                </button>
              ))}
            </div>
          )}
        </div>
        <div className="flex items-center gap-3">
          <button className="relative p-2 rounded-full hover:bg-accent transition">
            <Bell size={20} />
            <span className="absolute top-1.5 right-1.5 w-2 h-2 rounded-full bg-primary" />
          </button>
          <div className="w-9 h-9 rounded-full bg-gradient-to-br from-primary to-emerald-300 flex items-center justify-center text-xs font-bold text-black">
            PM
          </div>
        </div>
      </header>

      <div className="flex">
        {/* Left rail */}
        <nav className="w-16 sm:w-56 shrink-0 border-r border-border/60 bg-[#0b0d12] flex flex-col h-[calc(100vh-64px)] sticky top-16">
          <div className="p-3 space-y-1">
            <NavItem icon={<Home size={18} />} label="Início" active />
            <NavItem icon={<LineChart size={18} />} label="Mercados" onClick={() => onSwitchView?.("tickers")} />
            <NavItem icon={<Zap size={18} />} label="Análise de IA" onClick={() => onSwitchView?.("chat")} />
            <NavItem icon={<Newspaper size={18} />} label="Relatórios" onClick={() => onSwitchView?.("rag")} />
            <NavItem icon={<PieChart size={18} />} label="Portfólio" onClick={() => onSwitchView?.("forecast")} />
            <NavItem icon={<FolderOpen size={18} />} label="Favoritos" />
            <NavItem icon={<Database size={18} />} label="Elasticsearch" onClick={() => onSwitchView?.("elastic")} />
          </div>
          <div className="mt-auto p-3 border-t border-border/60">
            <NavItem icon={<MessageSquare size={18} />} label="Ajuda" />
            <NavItem icon={<Activity size={18} />} label="Definições" />
          </div>
        </nav>

        {/* Main content */}
        <main className="flex-1 p-4 sm:p-6 lg:p-8 overflow-x-hidden">
          <div className="max-w-7xl mx-auto space-y-6">
            {/* Welcome */}
            <section>
              <h2 className="text-2xl sm:text-3xl font-bold">Olá, Pedro</h2>
              <p className="text-muted-foreground text-sm mt-1">Aqui está o resumo do mercado e as principais oportunidades.</p>
            </section>

            {/* Indices */}
            <section className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              {indices.map((idx) => {
                const positive = (idx.changePct ?? 0) >= 0;
                return (
                  <div
                    key={idx.ticker}
                    className="rounded-2xl border border-border bg-card p-5 hover:border-primary/40 transition cursor-pointer"
                    onClick={() => handleSelect(idx.ticker)}
                  >
                    <div className="text-xs text-muted-foreground uppercase tracking-wide">{idx.name || idx.ticker}</div>
                    <div className="flex items-end justify-between mt-2">
                      <div className="text-2xl font-bold">{fmt(idx.price)}</div>
                      <div className={`flex items-center gap-1 text-sm font-medium ${positive ? "text-emerald-400" : "text-red-400"}`}>
                        {positive ? <ArrowUpRight size={16} /> : <ArrowDownRight size={16} />}
                        {pct(idx.changePct)}
                      </div>
                    </div>
                    <div className="mt-4 h-12">
                      <Sparkline data={sparkData(historyMap[idx.ticker])} positive={positive} />
                    </div>
                  </div>
                );
              })}
              {loading && indices.length === 0 &&
                Array.from({ length: 3 }).map((_, i) => (
                  <div key={i} className="rounded-2xl border border-border bg-card p-5 animate-pulse h-32" />
                ))}
            </section>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              {/* Market sentiment */}
              <div className="rounded-2xl border border-border bg-card p-5">
                <div className="flex items-center justify-between mb-4">
                  <h3 className="font-semibold flex items-center gap-2">
                    <Activity size={18} className="text-primary" />
                    Sentimento do Mercado
                  </h3>
                  <button onClick={loadEverything} className="p-2 rounded-lg hover:bg-accent transition" title="Atualizar">
                    <RefreshCw size={16} className={loading ? "animate-spin" : ""} />
                  </button>
                </div>
                <div className="flex items-center gap-6">
                  <div className="relative w-28 h-28">
                    <svg viewBox="0 0 36 36" className="w-full h-full -rotate-90">
                      <path
                        d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
                        fill="none"
                        stroke="#1e2128"
                        strokeWidth="4"
                      />
                      <path
                        d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
                        fill="none"
                        stroke="#10b981"
                        strokeDasharray={`${sentiment.positive}, 100`}
                        strokeWidth="4"
                        strokeLinecap="round"
                      />
                    </svg>
                    <div className="absolute inset-0 flex flex-col items-center justify-center">
                      <span className="text-2xl font-bold">{sentiment.positive}%</span>
                      <span className={`text-xs font-medium ${sentimentColor}`}>Positivo</span>
                    </div>
                  </div>
                  <div className="flex-1 space-y-3">
                    <SentimentRow color="#10b981" label="Positivo" value={sentiment.positive} />
                    <SentimentRow color="#9ca3af" label="Neutro" value={sentiment.neutral} />
                    <SentimentRow color="#ef4444" label="Negativo" value={sentiment.negative} />
                  </div>
                </div>
              </div>

              {/* Watchlist */}
              <div className="lg:col-span-2 rounded-2xl border border-border bg-card p-5">
                <div className="flex items-center justify-between mb-4">
                  <h3 className="font-semibold flex items-center gap-2">
                    <TrendingUp size={18} className="text-primary" />
                    Top Movimentações
                  </h3>
                  <button className="text-xs text-primary hover:underline flex items-center gap-1">
                    Ver todos <ChevronRight size={14} />
                  </button>
                </div>
                <div className="space-y-2">
                  {watchlist.map((item) => {
                    const positive = (item.changePct ?? 0) >= 0;
                    const hist = historyMap[item.ticker];
                    return (
                      <button
                        key={item.ticker}
                        onClick={() => handleSelect(item.ticker)}
                        className="w-full flex items-center gap-4 p-3 rounded-xl hover:bg-accent/50 transition"
                      >
                        <div className="w-10 h-10 rounded-xl bg-muted flex items-center justify-center text-sm font-bold shrink-0">
                          {item.ticker.slice(0, 1)}
                        </div>
                        <div className="flex-1 text-left">
                          <div className="font-semibold">{item.name || item.ticker}</div>
                          <div className="text-xs text-muted-foreground">{item.ticker}</div>
                        </div>
                        <div className="hidden sm:block w-24 h-10">
                          <Sparkline data={sparkData(hist)} positive={positive} />
                        </div>
                        <div className="text-right">
                          <div className="font-semibold">{fmt(item.price)}</div>
                          <div className={`text-xs font-medium ${positive ? "text-emerald-400" : "text-red-400"}`}>
                            {pct(item.changePct)}
                          </div>
                        </div>
                      </button>
                    );
                  })}
                  {loading && watchlist.length === 0 &&
                    Array.from({ length: 5 }).map((_, i) => (
                      <div key={i} className="h-14 rounded-xl bg-muted animate-pulse" />
                    ))}
                </div>
              </div>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              {/* News */}
              <div className="rounded-2xl border border-border bg-card p-5 lg:col-span-2">
                <div className="flex items-center justify-between mb-4">
                  <h3 className="font-semibold flex items-center gap-2">
                    <Newspaper size={18} className="text-primary" />
                    Últimas Notícias
                  </h3>
                  <button className="text-xs text-primary hover:underline flex items-center gap-1">
                    Ver todos <ChevronRight size={14} />
                  </button>
                </div>
                <div className="space-y-3">
                  {news.map((item, i) => (
                    <a
                      key={i}
                      href={item.url || "#"}
                      target="_blank"
                      rel="noreferrer"
                      className="flex items-start gap-4 p-3 rounded-xl hover:bg-accent/40 transition group"
                    >
                      <div className="w-10 h-10 rounded-xl bg-muted flex items-center justify-center shrink-0">
                        {(item.ticker)?.slice(0, 1) || "N"}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="text-xs font-semibold text-primary">{item.ticker || "Mercado"}</span>
                          <span className="text-xs text-muted-foreground">{item.published || item.publisher}</span>
                        </div>
                        <div className="text-sm font-medium mt-0.5 group-hover:text-primary transition line-clamp-2">
                          {item.title || "Sem título"}
                        </div>
                      </div>
                      <div className="hidden sm:flex items-center gap-2 shrink-0">
                        <span className="text-xs px-2 py-1 rounded-full bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
                          Positivo
                        </span>
                      </div>
                    </a>
                  ))}
                  {loading && news.length === 0 &&
                    Array.from({ length: 4 }).map((_, i) => (
                      <div key={i} className="h-16 rounded-xl bg-muted animate-pulse" />
                    ))}
                </div>
              </div>

              {/* AI insight card */}
              <div className="rounded-2xl border border-border bg-gradient-to-br from-card to-muted p-5 flex flex-col justify-between">
                <div>
                  <div className="flex items-center gap-2 mb-3">
                    <Zap size={20} className="text-primary" />
                    <h3 className="font-semibold">IA a trabalhar para ti</h3>
                  </div>
                  <p className="text-sm text-muted-foreground leading-relaxed">
                    Analisamos milhares de fontes para te dar os melhores insights. Faz uma pergunta sobre mercados, notícias ou previsões.
                  </p>
                </div>
                <button
                  onClick={() => onSwitchView?.("chat")}
                  className="mt-5 w-full py-3 rounded-xl bg-primary text-primary-foreground font-medium hover:bg-primary/90 transition flex items-center justify-center gap-2"
                >
                  <MessageSquare size={18} />
                  Começar conversa
                </button>
              </div>
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}

function NavItem({
  icon,
  label,
  active,
  onClick,
}: {
  icon: React.ReactNode;
  label: string;
  active?: boolean;
  onClick?: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-xl transition text-sm font-medium ${
        active
          ? "bg-primary/15 text-primary"
          : "text-muted-foreground hover:text-foreground hover:bg-accent/50"
      }`}
    >
      {icon}
      <span className="hidden sm:inline">{label}</span>
    </button>
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

function Sparkline({ data, positive }: { data: { date: string; value?: number }[]; positive: boolean }) {
  const valid = data.filter((d) => typeof d.value === "number");
  if (valid.length < 2) {
    return <div className="w-full h-full bg-muted/30 rounded" />;
  }
  const color = positive ? "#10b981" : "#ef4444";
  return (
    <ResponsiveContainer width="100%" height="100%">
      <AreaChart data={valid} margin={{ top: 2, right: 2, left: 2, bottom: 2 }}>
        <defs>
          <linearGradient id={`spark-${positive ? "up" : "down"}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.25} />
            <stop offset="100%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <XAxis dataKey="date" hide />
        <YAxis domain={["auto", "auto"]} hide />
        <Area
          type="monotone"
          dataKey="value"
          stroke={color}
          strokeWidth={2}
          fill={`url(#spark-${positive ? "up" : "down"})`}
          dot={false}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
