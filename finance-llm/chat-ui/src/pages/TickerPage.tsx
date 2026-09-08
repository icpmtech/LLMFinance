import { useEffect, useMemo, useState } from "react";
import {
  ArrowLeft,
  Building2,
  CalendarIcon,
  DollarSign,
  ExternalLink,
  Globe,
  LineChart,
  Plus,
  RefreshCcw,
  Search,
  TrendingUp,
  Users,
} from "lucide-react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  addTicker,
  getTickerActions,
  getTickerCalendar,
  getTickerFinancials,
  getTickerHolders,
  getTickerHistory,
  getTickerInfo,
  getTickerNews,
  getTickerOptions,
  getTickerRecommendations,
  getTickerSecFilings,
  getTickerSustainability,
  getTickerTechnical,
  getTickerTechnicalExplain,
  searchLocalTickers,
  searchYahooTickers,
} from "../api";
import type {
  Actions,
  AddTickerResponse,
  Calendar,
  Financials,
  HistoryPoint,
  Holders,
  News,
  Options,
  Recommendations,
  SecFilingsResponse,
  Sustainability,
  TechnicalAnalysis,
  TechnicalExplanation,
  TickerHistory,
  TickerInfo,
  YahooSearchResult,
} from "../types";

interface TickerPageProps {
  onSwitchView?: () => void;
}

type TabKey =
  | "overview"
  | "financials"
  | "filings"
  | "holders"
  | "esg"
  | "recommendations"
  | "calendar"
  | "news"
  | "options"
  | "actions"
  | "technical";

const ALL_TABS: TabKey[] = [
  "overview",
  "financials",
  "technical",
  "filings",
  "holders",
  "esg",
  "recommendations",
  "calendar",
  "news",
  "options",
  "actions",
];

const TAB_LABELS: Record<TabKey, string> = {
  overview: "Resumo",
  financials: "Financeiros",
  technical: "Técnica",
  filings: "SEC Filings",
  holders: "Holders",
  esg: "ESG",
  recommendations: "Análises",
  calendar: "Calendário",
  news: "Notícias",
  options: "Opções",
  actions: "Dividendos/Splits",
};

const PERIODS = [
  { value: "1mo", label: "1M" },
  { value: "3mo", label: "3M" },
  { value: "6mo", label: "6M" },
  { value: "1y", label: "1A" },
  { value: "2y", label: "2A" },
  { value: "5y", label: "5A" },
];

export function TickerPage({ onSwitchView }: TickerPageProps) {
  const [query, setQuery] = useState("");
  const [searching, setSearching] = useState(false);
  const [localResults, setLocalResults] = useState<string[]>([]);
  const [yahooResults, setYahooResults] = useState<YahooSearchResult[]>([]);
  const [selected, setSelected] = useState<string>("");

  const [info, setInfo] = useState<TickerInfo | null>(null);
  const [history, setHistory] = useState<TickerHistory | null>(null);
  const [financials, setFinancials] = useState<Financials | null>(null);
  const [filings, setFilings] = useState<SecFilingsResponse | null>(null);
  const [holders, setHolders] = useState<Holders | null>(null);
  const [sustainability, setSustainability] = useState<Sustainability | null>(null);
  const [recommendations, setRecommendations] = useState<Recommendations | null>(null);
  const [calendar, setCalendar] = useState<Calendar | null>(null);
  const [news, setNews] = useState<News | null>(null);
  const [options, setOptions] = useState<Options | null>(null);
  const [actions, setActions] = useState<Actions | null>(null);
  const [technical, setTechnical] = useState<TechnicalAnalysis | null>(null);
  const [technicalExplanation, setTechnicalExplanation] = useState<TechnicalExplanation | null>(null);
  const [explainLoading, setExplainLoading] = useState(false);
  const [addResult, setAddResult] = useState<AddTickerResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [period, setPeriod] = useState("1y");
  const [activeTab, setActiveTab] = useState<TabKey>("overview");
  const [error, setError] = useState<string | null>(null);

  const hasSecTab = useMemo(() => showSecFilingsTab(info, selected), [info, selected]);

  const availableTabs: TabKey[] = useMemo(() => {
    return ALL_TABS.filter((tab: TabKey) => tab !== "filings" || hasSecTab);
  }, [hasSecTab]);

  useEffect(() => {
    const timer = setTimeout(() => {
      if (query.trim().length >= 2) runSearch(query);
      else {
        setLocalResults([]);
        setYahooResults([]);
      }
    }, 250);
    return () => clearTimeout(timer);
  }, [query]);

  useEffect(() => {
    if (selected) loadTicker(selected);
  }, [selected, period]);

  useEffect(() => {
    if (!availableTabs.includes(activeTab)) {
      setActiveTab("overview");
    }
  }, [activeTab, availableTabs]);

  async function runSearch(q: string) {
    setSearching(true);
    setError(null);
    try {
      const [local, yahoo] = await Promise.all([
        searchLocalTickers(q),
        searchYahooTickers(q),
      ]);
      setLocalResults(local.slice(0, 20));
      setYahooResults(yahoo.yahoo_results || []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro na pesquisa");
    } finally {
      setSearching(false);
    }
  }

  async function loadTicker(ticker: string) {
    setLoading(true);
    setError(null);
    try {
      const [i, h, f, s, holdersData, sustData, recData, calData, newsData, optData, actData, techData] = await Promise.all([
        getTickerInfo(ticker),
        getTickerHistory(ticker, period),
        getTickerFinancials(ticker),
        getTickerSecFilings(ticker, 365),
        getTickerHolders(ticker),
        getTickerSustainability(ticker),
        getTickerRecommendations(ticker),
        getTickerCalendar(ticker),
        getTickerNews(ticker, 12),
        getTickerOptions(ticker),
        getTickerActions(ticker),
        getTickerTechnical(ticker, period),
      ]);
      setInfo(i);
      setHistory(h);
      setFinancials(f);
      setFilings(s);
      setHolders(holdersData);
      setSustainability(sustData);
      setRecommendations(recData);
      setCalendar(calData);
      setNews(newsData);
      setOptions(optData);
      setActions(actData);
      setTechnical(techData);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao carregar ticker");
    } finally {
      setLoading(false);
    }
  }

  async function handleAddTicker(ticker: string) {
    try {
      const res = await addTicker(ticker);
      setAddResult(res);
      if (res.added) setSelected(ticker);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao adicionar ticker");
    }
  }

  async function handleExplainTechnical() {
    if (!selected) return;
    setExplainLoading(true);
    setError(null);
    try {
      const exp = await getTickerTechnicalExplain(selected, period);
      setTechnicalExplanation(exp);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao explicar gráficos");
    } finally {
      setExplainLoading(false);
    }
  }

  const chartData = useMemo(() => {
    if (!history?.points) return [];
    return history.points.map((p: HistoryPoint) => ({
      date: p.date,
      Fechamento: p.close ?? null,
      Abertura: p.open ?? null,
      Máxima: p.high ?? null,
      Mínima: p.low ?? null,
      Volume: p.volume ?? null,
    }));
  }, [history]);

  const sortedStatements = useMemo(() => {
    if (!financials) return [];
    return [
      { key: "income_statement" as const, title: "Income Statement (Anual)" },
      { key: "balance_sheet" as const, title: "Balance Sheet (Anual)" },
      { key: "cash_flow" as const, title: "Cash Flow (Anual)" },
    ];
  }, [financials]);

  const sortedQuarterlyStatements = useMemo(() => {
    if (!financials) return [];
    return [
      { key: "quarterly_income_statement" as const, title: "Income Statement (Trimestral)" },
      { key: "quarterly_balance_sheet" as const, title: "Balance Sheet (Trimestral)" },
      { key: "quarterly_cash_flow" as const, title: "Cash Flow (Trimestral)" },
    ];
  }, [financials]);

  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="sticky top-0 z-20 border-b border-border bg-card/90 backdrop-blur px-6 py-3 flex items-center justify-between">
        <div className="flex items-center gap-3">
          {onSwitchView && (
            <button
              onClick={onSwitchView}
              className="p-2 rounded-lg hover:bg-accent transition"
              title="Voltar ao chat"
            >
              <ArrowLeft size={18} />
            </button>
          )}
          <h1 className="text-lg font-semibold flex items-center gap-2">
            <LineChart size={20} />
            Explorar Ticker
          </h1>
        </div>
        <div className="text-sm text-muted-foreground hidden sm:block">
          Pesquisa Yahoo Finance: dados históricos, fundamentais, ESG, analistas, notícias e mais.
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 py-6 space-y-6">
        {/* Search */}
        <section className="relative">
          <div className="flex items-center gap-2 rounded-xl border border-border bg-card px-4 py-2 shadow-sm">
            <Search size={18} className="text-muted-foreground" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Pesquisar ticker/empresa (ex: Apple, EDP, BCP...)"
              className="flex-1 bg-transparent outline-none placeholder:text-muted-foreground"
            />
            {searching && <RefreshCcw size={16} className="animate-spin text-muted-foreground" />}
          </div>

          {/* Search results */}
          {(localResults.length > 0 || yahooResults.length > 0 || query.trim().length >= 2) && (
            <div className="absolute z-10 mt-2 w-full rounded-xl border border-border bg-card shadow-lg max-h-[28rem] overflow-auto">
              {localResults.length === 0 && yahooResults.length === 0 && !searching && (
                <div className="p-4 space-y-3">
                  <div className="text-sm text-muted-foreground">
                    Nenhum resultado local nem Yahoo. Podes tentar adicionar o ticker manualmente.
                  </div>
                  {query.trim().length >= 1 && (
                    <button
                      onClick={() => handleAddTicker(query.trim().toUpperCase())}
                      className="w-full text-left px-3 py-2 rounded-lg hover:bg-accent flex items-center gap-2 text-sm border border-border"
                    >
                      <Plus size={16} />
                      Adicionar "{query.trim().toUpperCase()}" e tentar previsão
                    </button>
                  )}
                </div>
              )}

              {localResults.length > 0 && (
                <div className="p-2">
                  <div className="px-2 py-1 text-xs font-semibold uppercase text-muted-foreground tracking-wider">
                    Locais
                  </div>
                  {localResults.map((t) => (
                    <button
                      key={t}
                      onClick={() => {
                        setSelected(t);
                        setQuery("");
                      }}
                      className="w-full text-left px-3 py-2 rounded-lg hover:bg-accent flex items-center justify-between"
                    >
                      <span className="font-medium">{t}</span>
                      <TrendingUp size={14} className="text-muted-foreground" />
                    </button>
                  ))}
                </div>
              )}

              {yahooResults.length > 0 && (
                <div className="p-2 border-t border-border">
                  <div className="px-2 py-1 text-xs font-semibold uppercase text-muted-foreground tracking-wider">
                    Yahoo Finance
                  </div>
                  {yahooResults.map((r) => (
                    <button
                      key={r.symbol}
                      onClick={() => {
                        setSelected(r.symbol);
                        setQuery("");
                      }}
                      className="w-full text-left px-3 py-2 rounded-lg hover:bg-accent"
                    >
                      <div className="flex items-center justify-between">
                        <span className="font-medium">{r.symbol}</span>
                        <span className="text-xs text-muted-foreground">{r.exchange}</span>
                      </div>
                      <div className="text-sm text-muted-foreground truncate">
                        {r.name}
                        {r.sector && ` · ${r.sector}`}
                      </div>
                    </button>
                  ))}
                </div>
              )}

              {query.trim().length >= 1 && localResults.length + yahooResults.length > 0 && (
                <div className="p-2 border-t border-border">
                  <button
                    onClick={() => handleAddTicker(query.trim().toUpperCase())}
                    className="w-full text-left px-3 py-2 rounded-lg hover:bg-accent flex items-center gap-2 text-sm"
                  >
                    <Plus size={16} />
                    Adicionar "{query.trim().toUpperCase()}" e tentar previsão
                  </button>
                </div>
              )}
            </div>
          )}
        </section>

        {addResult && (
          <div
            className={`rounded-lg px-4 py-2 text-sm border ${
              addResult.added
                ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-700"
                : "bg-amber-500/10 border-amber-500/30 text-amber-700"
            }`}
          >
            {addResult.added ? "✅" : "ℹ️"} {addResult.message}
          </div>
        )}

        {error && (
          <div className="rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
            ❌ {error}
          </div>
        )}

        {selected && (
          <>
            {/* Info cards */}
            {info && (
              <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <InfoCard icon={<Building2 size={18} />} label="Empresa" value={info.name || info.ticker} sub={info.sector} />
                <InfoCard
                  icon={<DollarSign size={18} />}
                  label="Preço"
                  value={info.price != null ? `${info.price.toFixed(2)} ${info.currency || ""}` : "N/A"}
                  sub={info.market_cap != null ? `MCap ${formatMktCap(info.market_cap)}` : undefined}
                />
                <InfoCard icon={<TrendingUp size={18} />} label="P/E" value={info.pe != null ? info.pe.toFixed(2) : "N/A"} sub={info.eps != null ? `EPS ${info.eps.toFixed(2)}` : undefined} />
                <InfoCard
                  icon={<Globe size={18} />}
                  label="País"
                  value={info.country || "N/A"}
                  sub={info.industry}
                />
                <InfoCard
                  icon={<LineChart size={18} />}
                  label="Beta"
                  value={info.beta != null ? info.beta.toFixed(2) : "N/A"}
                  sub={info.exchange}
                />
                <InfoCard
                  icon={<TrendingUp size={18} />}
                  label="ROE"
                  value={info.roe != null ? `${(info.roe * 100).toFixed(1)}%` : "N/A"}
                  sub={info.recommendation}
                />
                <InfoCard
                  icon={<DollarSign size={18} />}
                  label="Yield"
                  value={info.dividend_yield != null ? `${(info.dividend_yield * 100).toFixed(2)}%` : "N/A"}
                  sub={info.quote_type}
                />
                <InfoCard
                  icon={<Users size={18} />}
                  label="Analistas"
                  value={info.number_of_analysts != null ? String(info.number_of_analysts) : "N/A"}
                  sub={info.target_mean_price != null ? `target ${info.target_mean_price.toFixed(2)}` : undefined}
                />
              </section>
            )}

            {info?.summary && (
              <section className="rounded-xl border border-border bg-card p-4 text-sm leading-relaxed">
                {info.summary}
              </section>
            )}

            {/* KPI badges */}
            {info?.kpis && Object.keys(info.kpis).length > 0 && (
              <section className="flex flex-wrap gap-2">
                {Object.entries(info.kpis).map(([k, v]) => (
                  <div key={k} className="rounded-lg border border-border bg-card px-3 py-1.5 text-xs">
                    <span className="text-muted-foreground">{k.replace(/_/g, " ")}:</span>{" "}
                    <span className="font-medium">{fmtPctOrNumber(v)}</span>
                  </div>
                ))}
              </section>
            )}

            {/* Tabs */}
            <div className="flex flex-wrap gap-2 border-b border-border">
              {availableTabs.map((t) => {
                return (
                  <button
                    key={t}
                    onClick={() => setActiveTab(t)}
                    className={`px-4 py-2 text-sm font-medium border-b-2 transition ${
                      activeTab === t
                        ? "border-primary text-primary"
                        : "border-transparent text-muted-foreground hover:text-foreground"
                    }`}
                    aria-pressed={activeTab === t}
                  >
                    {TAB_LABELS[t]}
                  </button>
                );
              })}
            </div>

            {activeTab === "overview" && (
              <section className="space-y-4">
                <div className="flex items-center gap-2">
                  {PERIODS.map((p) => (
                    <button
                      key={p.value}
                      onClick={() => setPeriod(p.value)}
                      className={`px-3 py-1 text-xs rounded-full border transition ${
                        period === p.value
                          ? "bg-primary text-primary-foreground border-primary"
                          : "border-border hover:bg-accent"
                      }`}
                    >
                      {p.label}
                    </button>
                  ))}
                </div>

                {loading && <p className="text-sm text-muted-foreground">A carregar...</p>}

                {!loading && chartData.length > 0 && (
                  <div className="rounded-xl border border-border bg-card p-4 h-96">
                    <ResponsiveContainer width="100%" height="100%">
                      <AreaChart data={chartData} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
                        <defs>
                          <linearGradient id="colorClose" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="5%" stopColor="#10b981" stopOpacity={0.3} />
                            <stop offset="95%" stopColor="#10b981" stopOpacity={0} />
                          </linearGradient>
                        </defs>
                        <CartesianGrid strokeDasharray="3 3" stroke="currentColor" className="opacity-10" />
                        <XAxis dataKey="date" tick={{ fontSize: 12 }} minTickGap={30} />
                        <YAxis domain={["auto", "auto"]} tick={{ fontSize: 12 }} width={60} />
                        <Tooltip
                          contentStyle={{ background: "var(--card)", borderColor: "var(--border)" }}
                          labelStyle={{ color: "var(--foreground)" }}
                        />
                        <Legend />
                        <Area type="monotone" dataKey="Fechamento" stroke="#10b981" fillOpacity={1} fill="url(#colorClose)" strokeWidth={2} dot={false} />
                        <Line type="monotone" dataKey="Máxima" stroke="#3b82f6" strokeWidth={1.5} dot={false} />
                        <Line type="monotone" dataKey="Mínima" stroke="#ef4444" strokeWidth={1.5} dot={false} />
                      </AreaChart>
                    </ResponsiveContainer>
                  </div>
                )}

                {!loading && chartData.length === 0 && (
                  <p className="text-sm text-muted-foreground">Sem dados de histórico disponíveis.</p>
                )}

                {history && (
                  <div className="rounded-xl border border-border bg-card overflow-auto max-h-80">
                    <table className="w-full text-sm">
                      <thead className="bg-muted sticky top-0">
                        <tr>
                          <th className="text-left px-3 py-2">Data</th>
                          <th className="text-right px-3 py-2">Abertura</th>
                          <th className="text-right px-3 py-2">Máxima</th>
                          <th className="text-right px-3 py-2">Mínima</th>
                          <th className="text-right px-3 py-2">Fechamento</th>
                          <th className="text-right px-3 py-2">Volume</th>
                        </tr>
                      </thead>
                      <tbody>
                        {[...history.points].reverse().slice(0, 30).map((p) => (
                          <tr key={p.date} className="border-t border-border hover:bg-accent/40">
                            <td className="px-3 py-2">{p.date}</td>
                            <td className="text-right px-3 py-2">{fmt(p.open)}</td>
                            <td className="text-right px-3 py-2">{fmt(p.high)}</td>
                            <td className="text-right px-3 py-2">{fmt(p.low)}</td>
                            <td className="text-right px-3 py-2 font-medium">{fmt(p.close)}</td>
                            <td className="text-right px-3 py-2">{formatVolume(p.volume)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>
            )}

            {activeTab === "financials" && (
              <section className="space-y-6">
                {!financials && <p className="text-sm text-muted-foreground">A carregar fundamentais...</p>}
                {financials?.income_statement && Object.keys(financials.income_statement).length === 0 && (
                  <p className="text-sm text-muted-foreground">Dados fundamentais não disponíveis para este ticker.</p>
                )}
                {sortedStatements.map(({ key, title }) => (
                  <StatementTable key={key} title={title} data={financials?.[key as Exclude<keyof Financials, 'ticker'>]} />
                ))}
                {sortedQuarterlyStatements.map(({ key, title }) => (
                  <StatementTable key={key} title={title} data={financials?.[key as Exclude<keyof Financials, 'ticker'>]} />
                ))}
              </section>
            )}

            {activeTab === "filings" && (
              <section>
                {!filings && <p className="text-sm text-muted-foreground">A carregar SEC filings...</p>}
                {filings && filings.filings.length === 0 && (
                  <p className="text-sm text-muted-foreground">Nenhum SEC filing disponível para este ticker.</p>
                )}
                <div className="space-y-2">
                  {filings?.filings.map((f) => (
                    <div key={`${f.date}-${f.type}`} className="rounded-lg border border-border bg-card p-3 flex items-start gap-3">
                      <CalendarIcon size={16} className="mt-0.5 text-muted-foreground" />
                      <div className="flex-1 min-w-0">
                        <div className="text-sm font-medium">{f.type}</div>
                        <div className="text-xs text-muted-foreground">{f.date}</div>
                        <div className="text-sm mt-1 truncate">{f.title}</div>
                      </div>
                      {f.url && (
                        <a
                          href={f.url}
                          target="_blank"
                          rel="noreferrer"
                          className="p-2 rounded-lg hover:bg-accent text-muted-foreground"
                          title="Abrir documento"
                        >
                          <ExternalLink size={16} />
                        </a>
                      )}
                    </div>
                  ))}
                </div>
              </section>
            )}

            {activeTab === "holders" && (
              <section className="space-y-6">
                {!holders && <p className="text-sm text-muted-foreground">A carregar holders...</p>}
                {holders?.error && <p className="text-sm text-red-500">Erro: {holders.error}</p>}

                {holders && !holders.error && (
                  <>
                    <HoldersSection
                      title="Institucionais"
                      data={holders.institutional}
                      nameKey="Holder"
                      valueKey="pctHeld"
                    />
                    <HoldersSection
                      title="Fundos Mútuos"
                      data={holders.mutual_fund}
                      nameKey="Holder"
                      valueKey="pctHeld"
                    />
                    <MajorHoldersCard data={holders.major} />
                    <InsiderTransactionsTable data={holders.insider_transactions} />
                    <InsiderPurchasesTable data={holders.insider_purchases} />
                  </>
                )}
              </section>
            )}

            {activeTab === "esg" && (
              <section className="space-y-4">
                <RecordCard title="ESG (Sustainability)" data={sustainability?.esg} />
              </section>
            )}

            {activeTab === "recommendations" && (
              <section className="space-y-4">
                <RecordCard title="Recomendações" data={recommendations?.recommendations} />
                <RecordCard title="Resumo de Recomendações" data={recommendations?.recommendations_summary} />
                <RecordCard title="Upgrades / Downgrades" data={recommendations?.upgrades_downgrades} />
              </section>
            )}

            {activeTab === "calendar" && (
              <section className="space-y-4">
                <RecordCard title="Calendário" data={calendar?.calendar} />
                <RecordCard title="Datas de Earnings" data={calendar?.earnings_dates} />
              </section>
            )}

            {activeTab === "news" && (
              <section className="space-y-3">
                {!news && <p className="text-sm text-muted-foreground">A carregar notícias...</p>}
                {news?.error && <p className="text-sm text-red-500">Erro: {news.error}</p>}
                {!news?.error && news?.news?.length === 0 && (
                  <p className="text-sm text-muted-foreground">Nenhuma notícia disponível.</p>
                )}
                {news?.news.map((item, idx) => {
                  const publisherText = typeof item.publisher === "string" ? item.publisher : (item.publisher as any)?.displayName || "";
                  return (
                    <article key={idx} className="rounded-xl border border-border bg-card p-4">
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <h3 className="text-sm font-semibold">{item.title || "Sem título"}</h3>
                          <div className="text-xs text-muted-foreground mt-1">
                            {publisherText}
                            {item.published && publisherText && " · "}
                            {item.published}
                          </div>
                          {item.summary && <p className="text-sm text-muted-foreground mt-2 line-clamp-3">{item.summary}</p>}
                        </div>
                        {item.url && (
                          <a
                            href={item.url}
                            target="_blank"
                            rel="noreferrer"
                            className="p-2 rounded-lg hover:bg-accent text-muted-foreground shrink-0"
                            title="Abrir notícia"
                          >
                            <ExternalLink size={16} />
                          </a>
                        )}
                      </div>
                    </article>
                  );
                })}
              </section>
            )}

            {activeTab === "options" && (
              <section className="space-y-4">
                <div className="flex flex-wrap gap-2">
                  <span className="text-sm text-muted-foreground">Expiration dates:</span>
                  {options?.expiration_dates.map((d) => (
                    <span key={d} className="text-sm border border-border rounded px-2 py-0.5 bg-card">{d}</span>
                  ))}
                </div>
                <RecordCard title="Opções" data={options?.chains} />
              </section>
            )}

            {activeTab === "actions" && (
              <section className="space-y-6">
                <ActionsSection actions={actions} />
              </section>
            )}

            {activeTab === "technical" && (
              <section className="space-y-6">
                {technical?.error ? (
                  <p className="text-sm text-muted-foreground">Erro na análise técnica: {technical.error}</p>
                ) : technical?.points && technical.points.length > 0 ? (
                  <>
                    <div className="flex items-center justify-between gap-3">
                      <p className="text-sm text-muted-foreground">
                        Indicadores calculados sobre {technical.points.length} sessões.
                      </p>
                      <button
                        onClick={handleExplainTechnical}
                        disabled={explainLoading}
                        className="inline-flex items-center gap-2 px-3 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 disabled:opacity-60 transition"
                        title="Analisar gráficos com IA"
                      >
                        {explainLoading ? (
                          <RefreshCcw size={16} className="animate-spin" />
                        ) : (
                          <TrendingUp size={16} />
                        )}
                        {explainLoading ? "A analisar..." : "Analisar gráficos com IA"}
                      </button>
                    </div>

                    {technicalExplanation && !technicalExplanation.error && (
                      <div className="rounded-xl border border-border bg-card p-4 space-y-4">
                        <div className="flex items-start gap-3">
                          <div className="p-2 rounded-lg bg-primary/10 text-primary">
                            <TrendingUp size={18} />
                          </div>
                          <div>
                            <div className="text-sm font-semibold">Resumo da análise</div>
                            <p className="text-sm text-muted-foreground mt-1 leading-relaxed">
                              {technicalExplanation.summary}
                            </p>
                          </div>
                        </div>
                        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                          <ExplainCard label="Tendência de preço" value={technicalExplanation.price_trend} />
                          <ExplainCard label="Médias móveis" value={technicalExplanation.sma_analysis} />
                          <ExplainCard label="RSI" value={technicalExplanation.rsi_analysis} />
                          <ExplainCard label="MACD" value={technicalExplanation.macd_analysis} />
                          <ExplainCard label="Bandas de Bollinger" value={technicalExplanation.bb_analysis} />
                          <ExplainCard label="ATR / Volatilidade" value={technicalExplanation.atr_analysis} />
                          <ExplainCard label="OBV / Volume" value={technicalExplanation.obv_analysis} />
                          <ExplainCard label="Sinal combinado" value={technicalExplanation.combined_signal} highlight />
                        </div>
                      </div>
                    )}

                    {technicalExplanation?.error && (
                      <p className="text-sm text-destructive">Erro na explicação: {technicalExplanation.error}</p>
                    )}

                    <div className="rounded-xl border border-border bg-card p-4 h-96">
                      <ResponsiveContainer width="100%" height="100%">
                        <AreaChart data={technical.points} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
                          <defs>
                            <linearGradient id="techPrice" x1="0" y1="0" x2="0" y2="1">
                              <stop offset="5%" stopColor="#10b981" stopOpacity={0.3} />
                              <stop offset="95%" stopColor="#10b981" stopOpacity={0} />
                            </linearGradient>
                          </defs>
                          <CartesianGrid strokeDasharray="3 3" stroke="currentColor" className="opacity-10" />
                          <XAxis dataKey="date" tick={{ fontSize: 12 }} minTickGap={30} />
                          <YAxis domain={["auto", "auto"]} tick={{ fontSize: 12 }} width={60} />
                          <Tooltip contentStyle={{ background: "var(--card)", borderColor: "var(--border)" }} labelStyle={{ color: "var(--foreground)" }} />
                          <Legend />
                          <Area type="monotone" dataKey="price" name="Preço" stroke="#10b981" fillOpacity={1} fill="url(#techPrice)" strokeWidth={2} dot={false} />
                          <Line type="monotone" dataKey="sma20" name="SMA 20" stroke="#f59e0b" strokeWidth={1.5} dot={false} />
                          <Line type="monotone" dataKey="sma50" name="SMA 50" stroke="#8b5cf6" strokeWidth={1.5} dot={false} />
                          <Line type="monotone" dataKey="sma200" name="SMA 200" stroke="#ec4899" strokeWidth={1.5} dot={false} />
                          <Line type="monotone" dataKey="bb_upper" name="BB Upper" stroke="#60a5fa" strokeDasharray="4 4" strokeWidth={1} dot={false} />
                          <Line type="monotone" dataKey="bb_lower" name="BB Lower" stroke="#60a5fa" strokeDasharray="4 4" strokeWidth={1} dot={false} />
                        </AreaChart>
                      </ResponsiveContainer>
                    </div>

                    <div className="grid gap-4 md:grid-cols-2">
                      <div className="rounded-xl border border-border bg-card p-4 h-72">
                        <div className="text-sm font-semibold mb-2">RSI (14)</div>
                        <ResponsiveContainer width="100%" height="85%">
                          <AreaChart data={technical.points} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
                            <defs>
                              <linearGradient id="rsiFill" x1="0" y1="0" x2="0" y2="1">
                                <stop offset="0%" stopColor="#3b82f6" stopOpacity={0.3} />
                                <stop offset="100%" stopColor="#3b82f6" stopOpacity={0} />
                              </linearGradient>
                            </defs>
                            <CartesianGrid strokeDasharray="3 3" stroke="currentColor" className="opacity-10" />
                            <XAxis dataKey="date" tick={{ fontSize: 11 }} minTickGap={40} />
                            <YAxis domain={[0, 100]} tick={{ fontSize: 11 }} width={35} />
                            <Tooltip contentStyle={{ background: "var(--card)", borderColor: "var(--border)" }} />
                            <Area type="monotone" dataKey="rsi14" name="RSI" stroke="#3b82f6" fill="url(#rsiFill)" strokeWidth={2} dot={false} />
                            <Line dataKey={() => 70} name="Sobrecompra" stroke="#ef4444" strokeDasharray="3 3" dot={false} />
                            <Line dataKey={() => 30} name="Sobrevenda" stroke="#10b981" strokeDasharray="3 3" dot={false} />
                          </AreaChart>
                        </ResponsiveContainer>
                      </div>

                      <div className="rounded-xl border border-border bg-card p-4 h-72">
                        <div className="text-sm font-semibold mb-2">MACD</div>
                        <ResponsiveContainer width="100%" height="85%">
                          <AreaChart data={technical.points} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
                            <CartesianGrid strokeDasharray="3 3" stroke="currentColor" className="opacity-10" />
                            <XAxis dataKey="date" tick={{ fontSize: 11 }} minTickGap={40} />
                            <YAxis domain={["auto", "auto"]} tick={{ fontSize: 11 }} width={55} />
                            <Tooltip contentStyle={{ background: "var(--card)", borderColor: "var(--border)" }} />
                            <Legend />
                            <Line type="monotone" dataKey="macd" name="MACD" stroke="#3b82f6" strokeWidth={1.5} dot={false} />
                            <Line type="monotone" dataKey="macd_signal" name="Sinal" stroke="#f59e0b" strokeWidth={1.5} dot={false} />
                            <Area type="monotone" dataKey="macd_histogram" name="Histograma" stroke="#10b981" fill="#10b981" fillOpacity={0.3} strokeWidth={1} dot={false} />
                          </AreaChart>
                        </ResponsiveContainer>
                      </div>

                      <div className="rounded-xl border border-border bg-card p-4 h-72">
                        <div className="text-sm font-semibold mb-2">ATR (14)</div>
                        <ResponsiveContainer width="100%" height="85%">
                          <AreaChart data={technical.points} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
                            <defs>
                              <linearGradient id="atrFill" x1="0" y1="0" x2="0" y2="1">
                                <stop offset="0%" stopColor="#f97316" stopOpacity={0.3} />
                                <stop offset="100%" stopColor="#f97316" stopOpacity={0} />
                              </linearGradient>
                            </defs>
                            <CartesianGrid strokeDasharray="3 3" stroke="currentColor" className="opacity-10" />
                            <XAxis dataKey="date" tick={{ fontSize: 11 }} minTickGap={40} />
                            <YAxis domain={["auto", "auto"]} tick={{ fontSize: 11 }} width={55} />
                            <Tooltip contentStyle={{ background: "var(--card)", borderColor: "var(--border)" }} />
                            <Area type="monotone" dataKey="atr14" name="ATR" stroke="#f97316" fill="url(#atrFill)" strokeWidth={2} dot={false} />
                          </AreaChart>
                        </ResponsiveContainer>
                      </div>

                      <div className="rounded-xl border border-border bg-card p-4 h-72">
                        <div className="text-sm font-semibold mb-2">OBV</div>
                        <ResponsiveContainer width="100%" height="85%">
                          <AreaChart data={technical.points} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
                            <defs>
                              <linearGradient id="obvFill" x1="0" y1="0" x2="0" y2="1">
                                <stop offset="0%" stopColor="#8b5cf6" stopOpacity={0.3} />
                                <stop offset="100%" stopColor="#8b5cf6" stopOpacity={0} />
                              </linearGradient>
                            </defs>
                            <CartesianGrid strokeDasharray="3 3" stroke="currentColor" className="opacity-10" />
                            <XAxis dataKey="date" tick={{ fontSize: 11 }} minTickGap={40} />
                            <YAxis domain={["auto", "auto"]} tick={{ fontSize: 11 }} width={55} />
                            <Tooltip contentStyle={{ background: "var(--card)", borderColor: "var(--border)" }} />
                            <Area type="monotone" dataKey="obv" name="OBV" stroke="#8b5cf6" fill="url(#obvFill)" strokeWidth={2} dot={false} />
                          </AreaChart>
                        </ResponsiveContainer>
                      </div>
                    </div>
                  </>
                ) : (
                  <p className="text-sm text-muted-foreground">Dados técnicos não disponíveis.</p>
                )}
              </section>
            )}
          </>
        )}

        {!selected && !error && (
          <div className="rounded-xl border border-dashed border-border bg-card p-8 text-center text-muted-foreground">
            <Search size={40} className="mx-auto mb-3 opacity-50" />
            <p className="text-sm">Pesquisa um ticker ou empresa para começar.</p>
          </div>
        )}
      </main>
    </div>
  );
}

function dictToRows(data?: Record<string, unknown> | null): Record<string, unknown>[] {
  if (!data || Object.keys(data).length === 0) return [];
  const keys = Object.keys(data);
  const len = Math.max(0, ...keys.map((k) => {
    const v = data[k];
    return typeof v === "object" && v !== null && !Array.isArray(v) ? Object.keys(v).length : 0;
  }));
  const rows: Record<string, unknown>[] = [];
  for (let i = 0; i < len; i++) {
    const row: Record<string, unknown> = {};
    keys.forEach((k) => {
      const v = data[k];
      if (typeof v === "object" && v !== null && !Array.isArray(v)) {
        row[k] = (v as Record<string, unknown>)[String(i)];
      } else {
        row[k] = v;
      }
    });
    rows.push(row);
  }
  return rows;
}

function parseActionsSeries(
  obj?: unknown,
  kind?: "dividends" | "splits"
): { date: string; value: number }[] {
  if (!obj || typeof obj !== "object") return [];
  let inner: Record<string, unknown> | undefined;
  if (Array.isArray(obj)) {
    return obj
      .filter((o) => o && typeof o === "object")
      .map((o) => ({
        date: String((o as Record<string, unknown>).date ?? ""),
        value: num((o as Record<string, unknown>).value) ?? 0,
      }))
      .filter((d) => d.date)
      .sort((a, b) => a.date.localeCompare(b.date));
  }
  const outer = obj as Record<string, unknown>;
  if (kind === "dividends") {
    inner =
      (outer.dividend as Record<string, unknown>) ??
      (outer.Dividends as Record<string, unknown>) ??
      outer;
  } else if (kind === "splits") {
    inner =
      (outer.split as Record<string, unknown>) ??
      (outer["Stock Splits"] as Record<string, unknown>) ??
      outer;
  } else {
    if ("Dividends" in outer) inner = outer.Dividends as Record<string, unknown>;
    else if ("Stock Splits" in outer) inner = outer["Stock Splits"] as Record<string, unknown>;
    else if ("dividend" in outer) inner = outer.dividend as Record<string, unknown>;
    else if ("split" in outer) inner = outer.split as Record<string, unknown>;
    else inner = outer;
  }
  if (!inner || typeof inner !== "object") return [];
  return Object.entries(inner as Record<string, unknown>)
    .map(([date, value]) => ({ date, value: num(value) ?? 0 }))
    .filter((d) => d.value !== 0)
    .sort((a, b) => a.date.localeCompare(b.date));
}

function fmtSplit(value: number): string {
  if (!isFinite(value) || value === 0) return "—";
  if (value >= 1) return `${value.toFixed(0)}:1`;
  const inverse = Math.round(1 / value);
  return `1:${inverse}`;
}

function ActionsSection({ actions }: { actions?: Actions | null }) {
  const dividends = useMemo(
    () => parseActionsSeries(actions?.dividends ?? actions?.actions, "dividends").slice(-50),
    [actions]
  );

  const splits = useMemo(
    () => parseActionsSeries(actions?.splits ?? actions?.actions, "splits").slice(-50),
    [actions]
  );

  return (
    <div className="space-y-8">
      <div className="rounded-xl border border-border bg-card p-4">
        <h3 className="text-lg font-semibold mb-4">Dividendos</h3>
        {dividends.length === 0 ? (
          <p className="text-sm text-muted-foreground">Sem dados de dividendos disponíveis.</p>
        ) : (
          <div className="space-y-6">
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={dividends}>
                  <defs>
                    <linearGradient id="dividendFill" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="var(--color-primary)" stopOpacity={0.3} />
                      <stop offset="95%" stopColor="var(--color-primary)" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
                  <XAxis
                    dataKey="date"
                    tick={{ fontSize: 12 }}
                    tickFormatter={(d) => d.slice(0, 7)}
                    angle={-30}
                    textAnchor="end"
                    height={50}
                    minTickGap={20}
                  />
                  <YAxis tick={{ fontSize: 12 }} width={60} />
                  <Tooltip
                    contentStyle={{ backgroundColor: "var(--color-card)", borderColor: "var(--color-border)" }}
                    labelFormatter={(d) => `Data: ${d}`}
                    formatter={(v) => [Number(v ?? 0).toFixed(4), "Dividendo"]}
                  />
                  <Area
                    type="stepAfter"
                    dataKey="value"
                    stroke="var(--color-primary)"
                    fill="url(#dividendFill)"
                    strokeWidth={2}
                    dot={false}
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-muted/50 text-muted-foreground">
                  <tr>
                    <th className="px-3 py-2 text-left font-medium">Data</th>
                    <th className="px-3 py-2 text-right font-medium">Valor</th>
                  </tr>
                </thead>
                <tbody>
                  {[...dividends].reverse().map((d, i) => (
                    <tr key={d.date} className={i % 2 === 1 ? "bg-muted/30" : ""}>
                      <td className="px-3 py-2">{d.date}</td>
                      <td className="px-3 py-2 text-right">{d.value.toFixed(4)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      <div className="rounded-xl border border-border bg-card p-4">
        <h3 className="text-lg font-semibold mb-4">Stock Splits</h3>
        {splits.length === 0 ? (
          <p className="text-sm text-muted-foreground">Sem dados de stock splits disponíveis.</p>
        ) : (
          <div className="space-y-6">
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={splits}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
                  <XAxis
                    dataKey="date"
                    tick={{ fontSize: 12 }}
                    tickFormatter={(d) => d.slice(0, 7)}
                    angle={-30}
                    textAnchor="end"
                    height={50}
                    minTickGap={20}
                  />
                  <YAxis tick={{ fontSize: 12 }} width={60} />
                  <Tooltip
                    contentStyle={{ backgroundColor: "var(--color-card)", borderColor: "var(--color-border)" }}
                    labelFormatter={(d) => `Data: ${d}`}
                    formatter={(v) => [fmtSplit(Number(v ?? 0)), "Split"]}
                  />
                  <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                    {splits.map((_entry, index) => (
                      <Cell key={`cell-${index}`} fill="var(--color-primary)" />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-muted/50 text-muted-foreground">
                  <tr>
                    <th className="px-3 py-2 text-left font-medium">Data</th>
                    <th className="px-3 py-2 text-right font-medium">Razão</th>
                  </tr>
                </thead>
                <tbody>
                  {[...splits].reverse().map((d, i) => (
                    <tr key={d.date} className={i % 2 === 1 ? "bg-muted/30" : ""}>
                      <td className="px-3 py-2">{d.date}</td>
                      <td className="px-3 py-2 text-right">{fmtSplit(d.value)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function HoldersSection({
  title,
  data,
  nameKey = "Holder",
  valueKey = "pctHeld",
}: {
  title: string;
  data?: Record<string, unknown> | null;
  nameKey?: string;
  valueKey?: string;
}) {
  const rows = useMemo(() => {
    const list = dictToRows(data);
    return list
      .filter((r) => r[nameKey])
      .map((r) => ({
        name: String(r[nameKey]),
        shares: num(r["Shares"]),
        value: num(r["Value"]),
        pct: num(r[valueKey]),
        date: String(r["Date Reported"] || "").split("T")[0],
        change: num(r["pctChange"]),
      }))
      .sort((a, b) => (b.pct || 0) - (a.pct || 0));
  }, [data, nameKey, valueKey]);

  if (rows.length === 0) return null;
  const chartData = rows.slice(0, 10);
  const COLORS = ["#2563eb", "#059669", "#d97706", "#dc2626", "#7c3aed", "#0891b2", "#ea580c", "#65a30d", "#9333ea", "#db2777"];

  return (
    <div className="rounded-xl border border-border bg-card overflow-hidden">
      <div className="bg-muted px-4 py-2 font-semibold text-sm">{title}</div>
      <div className="grid md:grid-cols-2 gap-4 p-4">
        <div className="overflow-auto max-h-80">
          <table className="w-full text-sm">
            <thead className="bg-muted/50 sticky top-0">
              <tr>
                <th className="text-left px-3 py-2">Holder</th>
                <th className="text-right px-3 py-2">% Detido</th>
                <th className="text-right px-3 py-2">Ações</th>
                <th className="text-right px-3 py-2">Valor</th>
                <th className="text-right px-3 py-2">% Var</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i} className="border-t border-border hover:bg-accent/40">
                  <td className="px-3 py-2 font-medium">{r.name}</td>
                  <td className="text-right px-3 py-2 tabular-nums">{fmtPct(r.pct)}</td>
                  <td className="text-right px-3 py-2 tabular-nums">{fmtBigNumber(r.shares)}</td>
                  <td className="text-right px-3 py-2 tabular-nums">{fmtBigNumber(r.value)}</td>
                  <td className={`text-right px-3 py-2 tabular-nums ${(r.change ?? 0) > 0 ? 'text-emerald-600' : (r.change ?? 0) < 0 ? 'text-red-600' : ''}`}>
                    {fmtPct(r.change)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chartData} layout="vertical" margin={{ left: 16, right: 16 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis type="number" domain={[0, "auto"]} tickFormatter={(v) => `${(Number(v) * 100).toFixed(0)}%`} />
              <YAxis type="category" dataKey="name" width={120} tick={{ fontSize: 11 }} />
              <Tooltip formatter={(v: any) => fmtPct(Number(v))} />
              <Bar dataKey="pct" radius={[0, 4, 4, 0]}>
                {chartData.map((_, i) => (
                  <Cell key={i} fill={COLORS[i % COLORS.length]} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}

function MajorHoldersCard({ data }: { data?: Record<string, unknown> | null }) {
  if (!data) return null;
  const value =
    "Value" in data && typeof data["Value"] === "object" && data["Value"] !== null
      ? (data["Value"] as Record<string, unknown>)
      : data;
  const insiders = num(value["insidersPercentHeld"]);
  const institutions = num(value["institutionsPercentHeld"]);
  const float = num(value["institutionsFloatPercentHeld"]);
  const count = num(value["institutionsCount"]);

  const pieData = [
    { name: "Insiders", value: insiders || 0 },
    { name: "Instituições", value: institutions || 0 },
    { name: "Outros", value: Math.max(0, 1 - (insiders || 0) - (institutions || 0)) },
  ].filter((d) => d.value > 0);
  const COLORS = ["#2563eb", "#059669", "#9ca3af"];

  return (
    <div className="rounded-xl border border-border bg-card overflow-hidden">
      <div className="bg-muted px-4 py-2 font-semibold text-sm">Maiores Holders</div>
      <div className="grid md:grid-cols-2 gap-4 p-4 items-center">
        <div className="h-56">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie data={pieData} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={80} label={(d: any) => `${d.name}: ${fmtPct(d.value)}`}>
                {pieData.map((_, i) => (
                  <Cell key={i} fill={COLORS[i % COLORS.length]} />
                ))}
              </Pie>
              <Tooltip formatter={(v: any) => fmtPct(Number(v))} />
              <Legend />
            </PieChart>
          </ResponsiveContainer>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div className="rounded-lg border border-border bg-background p-3">
            <div className="text-xs text-muted-foreground">Insiders</div>
            <div className="text-lg font-semibold">{fmtPct(insiders)}</div>
          </div>
          <div className="rounded-lg border border-border bg-background p-3">
            <div className="text-xs text-muted-foreground">Instituições</div>
            <div className="text-lg font-semibold">{fmtPct(institutions)}</div>
          </div>
          <div className="rounded-lg border border-border bg-background p-3">
            <div className="text-xs text-muted-foreground">Float Institucional</div>
            <div className="text-lg font-semibold">{fmtPct(float)}</div>
          </div>
          <div className="rounded-lg border border-border bg-background p-3">
            <div className="text-xs text-muted-foreground">Nº Instituições</div>
            <div className="text-lg font-semibold">{fmtBigNumber(count)}</div>
          </div>
        </div>
      </div>
    </div>
  );
}

function InsiderTransactionsTable({ data }: { data?: Record<string, unknown> | null }) {
  const rows = useMemo(() => {
    return dictToRows(data)
      .filter((r) => r["Insider"])
      .map((r) => ({
        insider: String(r["Insider"]),
        position: String(r["Position"] || ""),
        start: String(r["Start Date"] || "").split(" ")[0].split("T")[0],
        text: String(r["Text"] || ""),
        shares: num(r["Shares"]),
        value: num(r["Value"]),
        url: String(r["URL"] || ""),
      }))
      .slice(0, 50);
  }, [data]);

  if (rows.length === 0) return null;
  return (
    <div className="rounded-xl border border-border bg-card overflow-hidden">
      <div className="bg-muted px-4 py-2 font-semibold text-sm">Transações de Insiders</div>
      <div className="overflow-auto max-h-80">
        <table className="w-full text-sm">
          <thead className="bg-muted/50 sticky top-0">
            <tr>
              <th className="text-left px-3 py-2">Insider</th>
              <th className="text-left px-3 py-2">Cargo</th>
              <th className="text-left px-3 py-2">Data</th>
              <th className="text-left px-3 py-2">Descrição</th>
              <th className="text-right px-3 py-2">Ações</th>
              <th className="text-right px-3 py-2">Valor</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} className="border-t border-border hover:bg-accent/40">
                <td className="px-3 py-2 font-medium">{r.insider}</td>
                <td className="px-3 py-2">{r.position}</td>
                <td className="px-3 py-2 tabular-nums">{r.start}</td>
                <td className="px-3 py-2">{r.text}</td>
                <td className="text-right px-3 py-2 tabular-nums">{fmtBigNumber(r.shares)}</td>
                <td className="text-right px-3 py-2 tabular-nums">{fmtBigNumber(r.value)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function InsiderPurchasesTable({ data }: { data?: Record<string, unknown> | null }) {
  const rows = useMemo(() => {
    const raw = dictToRows(data);
    if (!raw.length && data && "Insider Purchases Last 6m" in data) {
      // yfinance devolve coluna única com chave literal; convertemos manualmente.
      const col = data["Insider Purchases Last 6m"] as Record<string, unknown>;
      const shares = data["Shares"] as Record<string, unknown>;
      const trans = data["Trans"] as Record<string, unknown>;
      return Object.keys(col).map((k) => ({
        label: String(col[k]),
        shares: num(shares?.[k]),
        trans: num(trans?.[k]),
      }));
    }
    return raw.map((r) => ({
      label: String(r["Insider Purchases Last 6m"] || r["label"] || ""),
      shares: num(r["Shares"]),
      trans: num(r["Trans"]),
    }));
  }, [data]);

  if (rows.length === 0) return null;
  return (
    <div className="rounded-xl border border-border bg-card overflow-hidden">
      <div className="bg-muted px-4 py-2 font-semibold text-sm">Compras de Insiders (últimos 6 meses)</div>
      <div className="overflow-auto">
        <table className="w-full text-sm">
          <thead className="bg-muted/50 sticky top-0">
            <tr>
              <th className="text-left px-3 py-2">Tipo</th>
              <th className="text-right px-3 py-2">Ações</th>
              <th className="text-right px-3 py-2">Transações</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} className="border-t border-border hover:bg-accent/40">
                <td className="px-3 py-2 font-medium">{r.label}</td>
                <td className="text-right px-3 py-2 tabular-nums">{fmtBigNumber(r.shares)}</td>
                <td className="text-right px-3 py-2 tabular-nums">{fmtBigNumber(r.trans)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="h-56 px-4 pb-4">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={rows} margin={{ left: 8, right: 16 }}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="label" tick={{ fontSize: 10 }} interval={0} />
            <YAxis yAxisId="left" orientation="left" tickFormatter={(v) => fmtBigNumber(Number(v))} />
            <YAxis yAxisId="right" orientation="right" tickFormatter={(v) => fmtBigNumber(Number(v))} />
            <Tooltip
              formatter={(v: any, name: any) => [fmtBigNumber(Number(v)), name === "shares" ? "Ações" : "Transações"]}
              labelFormatter={(l) => String(l)}
            />
            <Bar yAxisId="left" dataKey="shares" name="Ações" fill="#2563eb" radius={[4, 4, 0, 0]} />
            <Bar yAxisId="right" dataKey="trans" name="Transações" fill="#059669" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function num(v: unknown): number | undefined {
  if (v == null || v === "" || v === "—" || Number.isNaN(v)) return undefined;
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : undefined;
}

function fmtPct(n?: number | null) {
  if (n == null || Number.isNaN(n)) return "—";
  return `${(n * 100).toFixed(2)}%`;
}

function ExplainCard({ label, value, highlight }: { label: string; value?: string; highlight?: boolean }) {
  if (!value) return null;
  return (
    <div className={`rounded-lg border p-3 ${highlight ? "border-primary/40 bg-primary/5" : "border-border bg-background"}`}>
      <div className={`text-xs uppercase tracking-wider ${highlight ? "text-primary" : "text-muted-foreground"}`}>{label}</div>
      <div className={`text-sm mt-1 leading-snug ${highlight ? "font-medium text-foreground" : "text-muted-foreground"}`}>{value}</div>
    </div>
  );
}

function InfoCard({ icon, label, value, sub }: { icon: React.ReactNode; label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-xl border border-border bg-card p-4 flex items-start gap-3">
      <div className="p-2 rounded-lg bg-accent text-foreground">{icon}</div>
      <div className="min-w-0">
        <div className="text-xs text-muted-foreground uppercase tracking-wider">{label}</div>
        <div className="text-base font-semibold truncate">{value}</div>
        {sub && <div className="text-xs text-muted-foreground truncate">{sub}</div>}
      </div>
    </div>
  );
}

function StatementTable({
  title,
  data,
}: {
  title: string;
  data?: Record<string, Record<string, number>>;
}) {
  if (!data || Object.keys(data).length === 0) return null;
  const periods = Object.keys(data);
  const rows = Object.keys(data[periods[0]] || {});
  return (
    <div className="rounded-xl border border-border bg-card overflow-hidden">
      <div className="bg-muted px-4 py-2 font-semibold text-sm">{title}</div>
      <div className="overflow-auto max-h-96">
        <table className="w-full text-sm">
          <thead className="bg-muted/50 sticky top-0">
            <tr>
              <th className="text-left px-3 py-2">Métrica</th>
              {periods.map((p) => (
                <th key={p} className="text-right px-3 py-2">{p}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row} className="border-t border-border hover:bg-accent/40">
                <td className="px-3 py-2 font-medium">{row}</td>
                {periods.map((p) => (
                  <td key={p} className="text-right px-3 py-2 tabular-nums">
                    {fmtBigNumber(data[p]?.[row])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function RecordCard({ title, data }: { title: string; data?: Record<string, unknown> | unknown }) {
  if (!data) return null;
  let entries: [string, unknown][] = [];
  if (Array.isArray(data)) {
    entries = data.slice(0, 30).map((d, i) => [`${i + 1}`, d]);
  } else if (typeof data === "object" && data !== null) {
    entries = Object.entries(data as Record<string, unknown>).slice(0, 30);
  } else {
    return null;
  }
  return (
    <div className="rounded-xl border border-border bg-card overflow-hidden">
      <div className="bg-muted px-4 py-2 font-semibold text-sm">{title}</div>
      <div className="overflow-auto max-h-80">
        <table className="w-full text-sm">
          <tbody>
            {entries.map(([k, v]) => (
              <tr key={k} className="border-t border-border hover:bg-accent/40">
                <td className="px-3 py-2 font-medium align-top">{k}</td>
                <td className="px-3 py-2 text-muted-foreground break-all">{renderValue(v)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function renderValue(v: unknown): React.ReactNode {
  if (v == null) return "—";
  if (typeof v === "boolean") return v ? "Sim" : "Não";
  if (typeof v === "number") return fmt(v);
  if (typeof v === "string" && (v.startsWith("http://") || v.startsWith("https://"))) {
    return (
      <a href={v} target="_blank" rel="noreferrer" className="text-primary hover:underline">
        {v}
      </a>
    );
  }
  if (typeof v === "object") return <pre className="text-xs">{JSON.stringify(v, null, 2)}</pre>;
  return String(v);
}

function fmt(n?: number | null) {
  if (n == null || Number.isNaN(n)) return "—";
  return n.toLocaleString("pt-PT", { minimumFractionDigits: 2, maximumFractionDigits: 4 });
}

function fmtPctOrNumber(n?: number | null) {
  if (n == null || Number.isNaN(n)) return "—";
  if (Math.abs(n) < 100 && (n < 0 || n > 1 || n === 0 || n === 1)) {
    return `${(n * 100).toFixed(2)}%`;
  }
  return fmtBigNumber(n);
}

function fmtBigNumber(n?: number | null) {
  if (n == null || Number.isNaN(n)) return "—";
  const abs = Math.abs(n);
  if (abs >= 1e12) return `${(n / 1e12).toFixed(2)}T`;
  if (abs >= 1e9) return `${(n / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${(n / 1e6).toFixed(2)}M`;
  if (abs >= 1e3) return `${(n / 1e3).toFixed(2)}k`;
  return n.toLocaleString("pt-PT", { maximumFractionDigits: 2 });
}

function formatMktCap(n: number) {
  return fmtBigNumber(n);
}

function formatVolume(n?: number | null) {
  if (n == null || Number.isNaN(n)) return "—";
  return n.toLocaleString("pt-PT", { maximumFractionDigits: 0 });
}

function showSecFilingsTab(info: TickerInfo | null, ticker: string) {
  if (!info && !ticker) return false;
  const symbol = (ticker || info?.ticker || "").toUpperCase();
  const country = (info?.country || "").toLowerCase();
  // Mostrar SEC Filings apenas para tickers tipicamente US ou quando explicitamente indicado.
  return symbol.endsWith(".US") || country.includes("united states") || country.includes("estados unidos") || country === "us" || country === "usa";
}
