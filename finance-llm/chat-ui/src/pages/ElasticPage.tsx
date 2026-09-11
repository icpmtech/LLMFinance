import { useEffect, useMemo, useState } from "react";
import {
  ArrowLeft,
  Database,
  Search,
  Trash2,
  Upload,
  Activity,
  Network,
  Filter,
  X,
  ChevronLeft,
  ChevronRight,
  Sparkles,
  BarChart3,
  Calendar,
} from "lucide-react";
import {
  getElasticStatus,
  ingestElasticPrices,
  ingestElasticNews,
  ingestElasticTicker,
  searchElasticPrices,
  searchElasticNews,
  listElasticTickers,
  deleteElasticTicker,
  analyzeElasticNews,
  getElasticNewsGraph,
} from "../api";
import type {
  ElasticStatus,
  ElasticSearchPoint,
  ElasticSearchNewsItem,
  ElasticNewsGraphResponse,
} from "../types";

interface ElasticPageProps {
  onSwitchView: () => void;
}

const formatDate = (d?: string) => {
  if (!d) return "-";
  try {
    return new Date(d).toLocaleDateString();
  } catch {
    return d;
  }
};

const sentimentOrder: Record<string, number> = { negativo: 0, neutro: 1, positivo: 2 };

const sortNews = (
  items: ElasticSearchNewsItem[],
  by: "published" | "relevance" | "sentiment",
) => {
  const copy = [...items];
  if (by === "published") {
    copy.sort((a, b) => new Date(b.published || 0).getTime() - new Date(a.published || 0).getTime());
  } else if (by === "sentiment") {
    copy.sort((a, b) => {
      const sa = sentimentOrder[a.sentiment || "neutro"] ?? 1;
      const sb = sentimentOrder[b.sentiment || "neutro"] ?? 1;
      if (sa !== sb) return sb - sa;
      return new Date(b.published || 0).getTime() - new Date(a.published || 0).getTime();
    });
  }
  return copy;
};

export function ElasticPage({ onSwitchView }: ElasticPageProps) {
  const [status, setStatus] = useState<ElasticStatus | null>(null);
  const [tickers, setTickers] = useState<string[]>([]);
  const [ticker, setTicker] = useState("");
  const [period, setPeriod] = useState("1y");
  const [interval, setInterval] = useState("1d");
  const [query, setQuery] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [prices, setPrices] = useState<ElasticSearchPoint[]>([]);
  const [news, setNews] = useState<ElasticSearchNewsItem[]>([]);
  const [analyzedNews, setAnalyzedNews] = useState<ElasticSearchNewsItem[]>([]);
  const [analyzedCount, setAnalyzedCount] = useState<{ total: number; analyzed: number; errors?: number } | null>(null);
  const [graph, setGraph] = useState<ElasticNewsGraphResponse | null>(null);
  const [graphLoading, setGraphLoading] = useState(false);
  const [activeTab, setActiveTab] = useState<"prices" | "news" | "analyzed" | "graph">("prices");
  const [analysisBackend, setAnalysisBackend] = useState<"heuristic" | "gpt2" | "mistral">("heuristic");
  const [sortBy, setSortBy] = useState<"published" | "relevance" | "sentiment">("published");
  const [showAnalyzedOnly, setShowAnalyzedOnly] = useState(false);
  const [newsPage, setNewsPage] = useState(1);
  const [expandedNews, setExpandedNews] = useState<Set<number>>(new Set());
  const newsPageSize = 10;

  const displayedNews = useMemo(() => {
    let list = activeTab === "analyzed" ? analyzedNews : news;
    if (activeTab === "analyzed" && showAnalyzedOnly) {
      list = list.filter((n) => n.analyzed_at || n.sentiment || n.entities?.length || n.topics?.length);
    }
    const sorted = sortNews(list, sortBy);
    return sorted;
  }, [activeTab, analyzedNews, news, showAnalyzedOnly, sortBy]);

  const totalNews = displayedNews.length;
  const newsTotalPages = Math.max(1, Math.ceil(totalNews / newsPageSize));
  const newsSlice = displayedNews.slice((newsPage - 1) * newsPageSize, newsPage * newsPageSize);

  const show = (msg: string) => {
    setMessage(msg);
    setTimeout(() => setMessage(null), 5000);
  };

  const refreshStatus = async () => {
    try {
      const s = await getElasticStatus();
      setStatus(s);
    } catch (err) {
      setStatus({
        available: false,
        message: err instanceof Error ? err.message : "Erro desconhecido",
      });
    }
  };

  const refreshTickers = async () => {
    try {
      const t = await listElasticTickers();
      setTickers(t.tickers);
    } catch {
      setTickers([]);
    }
  };

  useEffect(() => {
    refreshStatus();
    refreshTickers();
  }, []);

  const handleIngestPrices = async () => {
    if (!ticker.trim()) return;
    setLoading(true);
    try {
      const res = await ingestElasticPrices(ticker.trim().toUpperCase(), period, interval);
      show(`Preços: ${res.indexed_count}/${res.total_points} indexados`);
      await refreshTickers();
    } catch (err) {
      show(err instanceof Error ? err.message : "Erro ao indexar preços");
    } finally {
      setLoading(false);
    }
  };

  const handleIngestNews = async () => {
    if (!ticker.trim()) return;
    setLoading(true);
    try {
      const res = await ingestElasticNews(ticker.trim().toUpperCase());
      show(`Notícias: ${res.indexed_count}/${res.total_items} indexadas`);
      await refreshTickers();
    } catch (err) {
      show(err instanceof Error ? err.message : "Erro ao indexar notícias");
    } finally {
      setLoading(false);
    }
  };

  const handleIngestAll = async () => {
    if (!ticker.trim()) return;
    setLoading(true);
    try {
      const res = await ingestElasticTicker(ticker.trim().toUpperCase(), { period, interval });
      show(
        `Indexado ${res.ticker}: ${res.prices.indexed_count} preços, ${res.news.indexed_count} notícias`,
      );
      await refreshTickers();
    } catch (err) {
      show(err instanceof Error ? err.message : "Erro ao indexar ticker");
    } finally {
      setLoading(false);
    }
  };

  const handleSearchPrices = async () => {
    if (!ticker.trim()) return;
    setLoading(true);
    try {
      const res = await searchElasticPrices(
        ticker.trim().toUpperCase(),
        startDate || undefined,
        endDate || undefined,
      );
      setPrices(res.points);
      setActiveTab("prices");
    } catch (err) {
      show(err instanceof Error ? err.message : "Erro ao pesquisar preços");
    } finally {
      setLoading(false);
    }
  };

  const handleSearchNews = async (tab = true) => {
    if (!ticker.trim()) return;
    setLoading(true);
    try {
      const res = await searchElasticNews(
        ticker.trim().toUpperCase(),
        query || undefined,
        startDate || undefined,
        endDate || undefined,
        200,
      );
      setNews(res.items);
      setNewsPage(1);
      if (tab) setActiveTab("news");
    } catch (err) {
      show(err instanceof Error ? err.message : "Erro ao pesquisar notícias");
    } finally {
      setLoading(false);
    }
  };

  const clearFilters = () => {
    setQuery("");
    setStartDate("");
    setEndDate("");
    setSortBy("published");
    setShowAnalyzedOnly(false);
    setNewsPage(1);
  };

  const activeFiltersCount = [query, startDate, endDate].filter(Boolean).length + (sortBy !== "published" ? 1 : 0);

  const handleDelete = async () => {
    if (!ticker.trim()) return;
    if (!window.confirm(`Apagar todos os dados Elasticsearch para ${ticker.trim().toUpperCase()}?`)) return;
    setLoading(true);
    try {
      const res = await deleteElasticTicker(ticker.trim().toUpperCase());
      show(
        `Apagado ${res.ticker}: ${res.prices_deleted ?? 0} preços, ${res.news_deleted ?? 0} notícias`,
      );
      setPrices([]);
      setNews([]);
      setAnalyzedNews([]);
      setGraph(null);
      await refreshTickers();
    } catch (err) {
      show(err instanceof Error ? err.message : "Erro ao apagar dados");
    } finally {
      setLoading(false);
    }
  };

  const handleAnalyzeNews = async () => {
    if (!ticker.trim()) return;
    setLoading(true);
    try {
      const res = await analyzeElasticNews(
        ticker.trim().toUpperCase(),
        query || undefined,
        startDate || undefined,
        endDate || undefined,
        50,
        analysisBackend,
      );
      setAnalyzedCount({ total: res.total_items, analyzed: res.analyzed_count, errors: res.errors });
      const searchRes = await searchElasticNews(
        ticker.trim().toUpperCase(),
        query || undefined,
        startDate || undefined,
        endDate || undefined,
        200,
      );
      setNews(searchRes.items);
      setAnalyzedNews(searchRes.items);
      setActiveTab("analyzed");
      setShowAnalyzedOnly(false);
      show(res.message || `Analisadas ${res.analyzed_count}/${res.total_items} notícias`);
      // Recarrega grafo atualizado após análise.
      await handleLoadGraph("build");
    } catch (err) {
      show(err instanceof Error ? err.message : "Erro ao analisar notícias");
    } finally {
      setLoading(false);
    }
  };

  const handleLoadGraph = async (source: "es" | "build" = "es") => {
    if (!ticker.trim()) return;
    setGraphLoading(true);
    try {
      const res = await getElasticNewsGraph(ticker.trim().toUpperCase(), source);
      setGraph(res);
      setActiveTab("graph");
    } catch (err) {
      show(err instanceof Error ? err.message : "Erro ao carregar grafo");
    } finally {
      setGraphLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-background text-foreground p-6">
      <div className="max-w-6xl mx-auto space-y-6">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <button
              onClick={onSwitchView}
              className="flex items-center gap-2 px-4 py-2 rounded-lg bg-card border border-border hover:bg-accent transition"
            >
              <ArrowLeft size={18} /> Voltar
            </button>
            <h1 className="text-2xl font-bold flex items-center gap-2">
              <Database size={28} /> Elasticsearch
            </h1>
          </div>
          <button
            onClick={() => {
              refreshStatus();
              refreshTickers();
            }}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 transition"
          >
            <Activity size={18} /> Atualizar estado
          </button>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="p-4 rounded-xl bg-card border border-border">
            <h2 className="font-semibold mb-2 flex items-center gap-2">
              <Activity size={18} /> Estado
            </h2>
            <p>
              <span className={status?.available ? "text-green-500" : "text-red-500"}>
                {status?.available ? "Disponível" : "Indisponível"}
              </span>
            </p>
            <p className="text-sm text-muted-foreground">{status?.message}</p>
            {status?.version && <p className="text-sm">v{status.version}</p>}
          </div>

          <div className="p-4 rounded-xl bg-card border border-border">
            <h2 className="font-semibold mb-2 flex items-center gap-2">
              <Database size={18} /> Tickers indexados
            </h2>
            <p className="text-2xl font-bold">{tickers.length}</p>
            <p className="text-sm text-muted-foreground truncate">
              {tickers.slice(0, 6).join(", ")}
              {tickers.length > 6 ? "..." : ""}
            </p>
          </div>

          <div className="p-4 rounded-xl bg-card border border-border">
            <h2 className="font-semibold mb-2">Ações rápidas</h2>
            <p className="text-sm text-muted-foreground">
              Use o formulário abaixo para indexar preços, notícias e pesquisar por ticker.
            </p>
          </div>
        </div>

        {message && (
          <div className="p-3 rounded-lg bg-accent border border-border text-sm">{message}</div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="space-y-4 p-4 rounded-xl bg-card border border-border">
            <h2 className="font-semibold flex items-center gap-2">
              <Upload size={18} /> Ingestão
            </h2>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <input
                value={ticker}
                onChange={(e) => setTicker(e.target.value)}
                placeholder="Ticker (ex: AAPL)"
                className="px-3 py-2 rounded-lg bg-background border border-border focus:outline-none focus:ring-2 focus:ring-ring"
              />
              <select
                value={period}
                onChange={(e) => setPeriod(e.target.value)}
                className="px-3 py-2 rounded-lg bg-background border border-border"
              >
                <option value="1mo">1 mês</option>
                <option value="3mo">3 meses</option>
                <option value="6mo">6 meses</option>
                <option value="1y">1 ano</option>
                <option value="2y">2 anos</option>
                <option value="5y">5 anos</option>
                <option value="10y">10 anos</option>
                <option value="max">Máximo</option>
              </select>
              <select
                value={interval}
                onChange={(e) => setInterval(e.target.value)}
                className="px-3 py-2 rounded-lg bg-background border border-border"
              >
                <option value="1d">Diário</option>
                <option value="1wk">Semanal</option>
                <option value="1mo">Mensal</option>
              </select>
            </div>

            <div className="flex flex-wrap gap-2">
              <button
                onClick={handleIngestPrices}
                disabled={loading || !ticker.trim()}
                className="flex items-center gap-2 px-4 py-2 rounded-lg bg-primary text-primary-foreground disabled:opacity-50 hover:bg-primary/90 transition"
              >
                <Upload size={16} /> Indexar preços
              </button>
              <button
                onClick={handleIngestNews}
                disabled={loading || !ticker.trim()}
                className="flex items-center gap-2 px-4 py-2 rounded-lg bg-primary text-primary-foreground disabled:opacity-50 hover:bg-primary/90 transition"
              >
                <Upload size={16} /> Indexar notícias
              </button>
              <button
                onClick={handleIngestAll}
                disabled={loading || !ticker.trim()}
                className="flex items-center gap-2 px-4 py-2 rounded-lg bg-primary text-primary-foreground disabled:opacity-50 hover:bg-primary/90 transition"
              >
                <Upload size={16} /> Indexar tudo
              </button>
            </div>
          </div>

          <div className="space-y-4 p-4 rounded-xl bg-card border border-border">
            <div className="flex items-center justify-between">
              <h2 className="font-semibold flex items-center gap-2">
                <Search size={18} /> Pesquisa de notícias
              </h2>
              {activeFiltersCount > 0 && (
                <button
                  onClick={clearFilters}
                  className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition"
                >
                  <X size={14} /> Limpar filtros
                </button>
              )}
            </div>

            <form
              onSubmit={(e) => {
                e.preventDefault();
                handleSearchNews(true);
              }}
              className="space-y-3"
            >
              <div className="flex gap-2">
                <div className="relative flex-1">
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" size={18} />
                  <input
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    placeholder="Pesquisar palavras no título ou resumo..."
                    className="w-full pl-10 pr-3 py-2 rounded-lg bg-background border border-border focus:outline-none focus:ring-2 focus:ring-ring"
                  />
                </div>
                <button
                  type="submit"
                  disabled={loading || !ticker.trim()}
                  className="flex items-center gap-2 px-4 py-2 rounded-lg bg-secondary text-secondary-foreground disabled:opacity-50 hover:bg-secondary/90 transition"
                >
                  {loading ? <Activity size={16} className="animate-spin" /> : <Search size={16} />}
                  <span className="hidden sm:inline">Pesquisar</span>
                </button>
              </div>

              <div className="flex flex-wrap items-end gap-3">
                <div className="space-y-1">
                  <label className="text-xs text-muted-foreground flex items-center gap-1">
                    <Calendar size={12} /> De
                  </label>
                  <input
                    type="date"
                    value={startDate}
                    onChange={(e) => setStartDate(e.target.value)}
                    className="px-3 py-2 rounded-lg bg-background border border-border text-sm"
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-xs text-muted-foreground flex items-center gap-1">
                    <Calendar size={12} /> Até
                  </label>
                  <input
                    type="date"
                    value={endDate}
                    onChange={(e) => setEndDate(e.target.value)}
                    className="px-3 py-2 rounded-lg bg-background border border-border text-sm"
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-xs text-muted-foreground flex items-center gap-1">
                    <Filter size={12} /> Ordenar
                  </label>
                  <select
                    value={sortBy}
                    onChange={(e) => setSortBy(e.target.value as "published" | "relevance" | "sentiment")}
                    className="px-3 py-2 rounded-lg bg-background border border-border text-sm"
                  >
                    <option value="published">Mais recentes</option>
                    <option value="relevance">Relevância</option>
                    <option value="sentiment">Sentimento</option>
                  </select>
                </div>
                {activeTab === "analyzed" && (
                  <label className="flex items-center gap-2 text-sm cursor-pointer select-none">
                    <input
                      type="checkbox"
                      checked={showAnalyzedOnly}
                      onChange={(e) => setShowAnalyzedOnly(e.target.checked)}
                      className="rounded border-border"
                    />
                    Só analisadas
                  </label>
                )}
              </div>
            </form>

            <div className="flex flex-wrap items-center gap-2 pt-1 border-t border-border">
              <span className="text-xs text-muted-foreground">Ações:</span>
              <button
                onClick={() => handleSearchNews(false)}
                disabled={loading || !ticker.trim()}
                className="flex items-center gap-1 px-3 py-1.5 rounded-md bg-primary/10 text-primary text-sm hover:bg-primary/20 transition disabled:opacity-50"
              >
                <Search size={14} /> Notícias
              </button>
              <button
                onClick={handleSearchPrices}
                disabled={loading || !ticker.trim()}
                className="flex items-center gap-1 px-3 py-1.5 rounded-md bg-primary/10 text-primary text-sm hover:bg-primary/20 transition disabled:opacity-50"
              >
                <BarChart3 size={14} /> Preços
              </button>
              <button
                onClick={handleAnalyzeNews}
                disabled={loading || !ticker.trim()}
                className="flex items-center gap-1 px-3 py-1.5 rounded-md bg-accent text-accent-foreground text-sm hover:bg-accent/80 transition disabled:opacity-50"
              >
                <Sparkles size={14} /> Analisar NLP
              </button>
              <div className="flex items-center gap-1 ml-auto">
                <span className="text-xs text-muted-foreground hidden sm:inline">Backend:</span>
                <select
                  value={analysisBackend}
                  onChange={(e) => setAnalysisBackend(e.target.value as "heuristic" | "gpt2" | "mistral")}
                  className="px-2 py-1.5 rounded-md bg-background border border-border text-sm"
                  title="Modelo usado no Analisar NLP"
                >
                  <option value="heuristic">Heurística (rápido)</option>
                  <option value="gpt2">GPT-2</option>
                  <option value="mistral">Mistral</option>
                </select>
              </div>
              <button
                onClick={() => handleLoadGraph("build")}
                disabled={loading || graphLoading || !ticker.trim()}
                className="flex items-center gap-1 px-3 py-1.5 rounded-md bg-primary/10 text-primary text-sm hover:bg-primary/20 transition disabled:opacity-50"
              >
                <Network size={14} /> Grafo
              </button>
              <button
                onClick={handleDelete}
                disabled={loading || !ticker.trim()}
                className="flex items-center gap-1 px-3 py-1.5 rounded-md bg-destructive/10 text-destructive text-sm hover:bg-destructive/20 transition disabled:opacity-50"
              >
                <Trash2 size={14} /> Apagar
              </button>
            </div>
          </div>
        </div>

        <div className="rounded-xl bg-card border border-border overflow-hidden">
          <div className="flex border-b border-border flex-wrap">
            <button
              onClick={() => setActiveTab("prices")}
              className={`px-4 py-2 text-sm font-medium ${
                activeTab === "prices" ? "bg-accent text-foreground" : "text-muted-foreground"
              }`}
            >
              Preços ({prices.length})
            </button>
            <button
              onClick={() => setActiveTab("news")}
              className={`px-4 py-2 text-sm font-medium ${
                activeTab === "news" ? "bg-accent text-foreground" : "text-muted-foreground"
              }`}
            >
              Notícias ({news.length})
            </button>
            <button
              onClick={() => setActiveTab("analyzed")}
              className={`px-4 py-2 text-sm font-medium ${
                activeTab === "analyzed" ? "bg-accent text-foreground" : "text-muted-foreground"
              }`}
            >
              Notícias Analisadas ({analyzedNews.length})
            </button>
            <button
              onClick={() => setActiveTab("graph")}
              className={`px-4 py-2 text-sm font-medium ${
                activeTab === "graph" ? "bg-accent text-foreground" : "text-muted-foreground"
              }`}
            >
              Grafo {graph ? `(${graph.node_count})` : ""}
            </button>
          </div>

          <div className="p-4 max-h-[600px] overflow-auto">
            {activeTab === "prices" ? (
              prices.length === 0 ? (
                <p className="text-muted-foreground text-sm">Sem preços para mostrar.</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="text-left text-muted-foreground border-b border-border">
                      <tr>
                        <th className="pb-2">Data</th>
                        <th className="pb-2">Abertura</th>
                        <th className="pb-2">Máxima</th>
                        <th className="pb-2">Mínima</th>
                        <th className="pb-2">Fecho</th>
                        <th className="pb-2">Volume</th>
                      </tr>
                    </thead>
                    <tbody>
                      {prices.map((p, idx) => (
                        <tr key={idx} className="border-b border-border last:border-0">
                          <td className="py-2">{formatDate(p.date)}</td>
                          <td className="py-2">{p.open?.toFixed(2)}</td>
                          <td className="py-2">{p.high?.toFixed(2)}</td>
                          <td className="py-2">{p.low?.toFixed(2)}</td>
                          <td className="py-2">{p.close?.toFixed(2)}</td>
                          <td className="py-2">{p.volume?.toLocaleString()}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )
            ) : activeTab === "news" || activeTab === "analyzed" ? (
              totalNews === 0 ? (
                <div className="text-center py-8 space-y-3">
                  <Search className="mx-auto text-muted-foreground" size={40} />
                  <p className="text-muted-foreground text-sm">
                    {activeTab === "analyzed"
                      ? "Sem notícias analisadas para este filtro. Use 'Analisar NLP' para enriquecer as notícias."
                      : "Nenhuma notícia encontrada para este ticker e filtro. Experimenta indexar notícias ou limpar os filtros."}
                  </p>
                  {activeTab !== "analyzed" && (
                    <button
                      onClick={clearFilters}
                      className="px-4 py-2 rounded-lg bg-accent text-accent-foreground text-sm hover:bg-accent/80 transition"
                    >
                      Limpar filtros
                    </button>
                  )}
                </div>
              ) : (
                <div className="space-y-4">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <p className="text-sm text-muted-foreground">
                      {totalNews} {totalNews === 1 ? "resultado" : "resultados"}
                      {query && <span className="ml-1">• pesquisa por "{query}"</span>}
                    </p>
                    <div className="flex items-center gap-1 text-sm">
                      <button
                        onClick={() => setNewsPage((p) => Math.max(1, p - 1))}
                        disabled={newsPage <= 1}
                        className="px-2 py-1 rounded-md bg-accent disabled:opacity-50"
                      >
                        <ChevronLeft size={16} />
                      </button>
                      <span className="px-2 text-muted-foreground text-xs">
                        {newsPage}/{newsTotalPages}
                      </span>
                      <button
                        onClick={() => setNewsPage((p) => Math.min(newsTotalPages, p + 1))}
                        disabled={newsPage >= newsTotalPages}
                        className="px-2 py-1 rounded-md bg-accent disabled:opacity-50"
                      >
                        <ChevronRight size={16} />
                      </button>
                    </div>
                  </div>

                  {activeTab === "analyzed" && analyzedCount && (
                    <p className="text-sm text-muted-foreground">
                      Última análise: {analyzedCount.analyzed}/{analyzedCount.total} enriquecidas
                      {analyzedCount.errors ? ` (${analyzedCount.errors} erros)` : ""}
                    </p>
                  )}

                  {newsSlice.map((n, idx) => {
                    const realIdx = (newsPage - 1) * newsPageSize + idx;
                    const isExpanded = expandedNews.has(realIdx);
                    const sentiment = n.sentiment || "neutro";
                    return (
                      <article
                        key={realIdx}
                        className="p-4 rounded-lg bg-background border border-border hover:border-ring/50 transition"
                      >
                        <div className="flex flex-wrap items-start justify-between gap-2 mb-1">
                          <h3 className="font-medium leading-snug">
                            {n.translated_title || n.title || "Sem título"}
                          </h3>
                          {sentiment && (
                            <span
                              className={`text-xs px-2 py-0.5 rounded-full font-medium whitespace-nowrap ${
                                sentiment === "positivo"
                                  ? "bg-emerald-500/15 text-emerald-400"
                                  : sentiment === "negativo"
                                  ? "bg-red-500/15 text-red-400"
                                  : "bg-amber-500/15 text-amber-400"
                              }`}
                            >
                              {sentiment}
                            </span>
                          )}
                        </div>

                        <p className="text-sm text-muted-foreground mb-2">
                          {isExpanded
                            ? n.summary_pt || n.translated_summary || n.summary || "Sem resumo"
                            : (n.summary_pt || n.translated_summary || n.summary || "Sem resumo").slice(0, 220)}
                          {!isExpanded && (n.summary_pt || n.translated_summary || n.summary || "").length > 220 && "…"}
                          {(n.summary_pt || n.translated_summary || n.summary || "").length > 220 && (
                            <button
                              onClick={() => {
                                const next = new Set(expandedNews);
                                if (next.has(realIdx)) next.delete(realIdx);
                                else next.add(realIdx);
                                setExpandedNews(next);
                              }}
                              className="ml-1 text-xs text-primary hover:underline"
                            >
                              {isExpanded ? "Mostrar menos" : "Mostrar mais"}
                            </button>
                          )}
                        </p>

                        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground mb-2">
                          <span>{n.publisher}</span>
                          <span>{formatDate(n.published)}</span>
                          {n.language && <span>idioma: {n.language}</span>}
                          {n.analyzed_at && <span>analisada: {formatDate(n.analyzed_at)}</span>}
                        </div>

                        {(n.entities?.length || n.topics?.length) ? (
                          <div className="flex flex-wrap gap-1">
                            {n.entities?.map((e, eidx) => (
                              <span
                                key={`e-${eidx}`}
                                className="text-xs px-2 py-0.5 rounded-full bg-muted text-muted-foreground border border-border"
                              >
                                {e.name} ({e.type})
                              </span>
                            ))}
                            {n.topics?.map((t, tidx) => (
                              <span
                                key={`t-${tidx}`}
                                className="text-xs px-2 py-0.5 rounded-full bg-sky-500/15 text-sky-400 border border-sky-500/30"
                              >
                                {t}
                              </span>
                            ))}
                          </div>
                        ) : null}

                        {n.url && (
                          <a
                            href={n.url}
                            target="_blank"
                            rel="noreferrer"
                            className="text-xs text-blue-500 hover:underline mt-2 inline-block"
                          >
                            Ver fonte
                          </a>
                        )}
                      </article>
                    );
                  })}

                  {newsTotalPages > 1 && (
                    <div className="flex items-center justify-end gap-1 pt-2 text-sm">
                      <button
                        onClick={() => setNewsPage((p) => Math.max(1, p - 1))}
                        disabled={newsPage <= 1}
                        className="px-2 py-1 rounded-md bg-accent disabled:opacity-50"
                      >
                        <ChevronLeft size={16} />
                      </button>
                      <span className="px-2 text-muted-foreground text-xs">
                        {newsPage}/{newsTotalPages}
                      </span>
                      <button
                        onClick={() => setNewsPage((p) => Math.min(newsTotalPages, p + 1))}
                        disabled={newsPage >= newsTotalPages}
                        className="px-2 py-1 rounded-md bg-accent disabled:opacity-50"
                      >
                        <ChevronRight size={16} />
                      </button>
                    </div>
                  )}
                </div>
              )
            ) : graph && graph.nodes.length === 0 ? (
              <div className="p-4 text-center">
                <p className="text-muted-foreground text-sm">Grafo vazio. Analise notícias primeiro.</p>
                <button
                  onClick={() => handleLoadGraph("build")}
                  disabled={graphLoading || !ticker.trim()}
                  className="mt-2 flex items-center gap-2 px-4 py-2 rounded-lg bg-primary text-primary-foreground disabled:opacity-50 hover:bg-primary/90 transition mx-auto"
                >
                  {graphLoading ? "A construir..." : "Reconstruir grafo"}
                </button>
              </div>
            ) : graph ? (
              <NewsGraphView graph={graph} />
            ) : (
              <p className="text-muted-foreground text-sm">Carrega no botão "Grafo" para visualizar notícias e entidades.</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function NewsGraphView({ graph }: { graph: ElasticNewsGraphResponse }) {
  const nodes = graph.nodes || [];
  const edges = graph.edges || [];
  const count = nodes.length;
  const radius = Math.max(160, Math.min(360, count * 22));
  const cx = 400;
  const cy = 300;
  const positions: Record<string, { x: number; y: number }> = {};
  nodes.forEach((node, i) => {
    const angle = (2 * Math.PI * i) / Math.max(1, count) - Math.PI / 2;
    positions[node.id] = {
      x: cx + radius * Math.cos(angle),
      y: cy + radius * Math.sin(angle),
    };
  });

  const [hover, setHover] = useState<string | null>(null);
  const [scale, setScale] = useState(1);

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <span className="font-medium text-foreground">{graph.node_count}</span> nós •{" "}
        <span className="font-medium text-foreground">{graph.edge_count}</span> ligações
        <button
          onClick={() => setScale((s) => Math.min(3, s + 0.2))}
          className="ml-auto px-2 py-1 rounded bg-accent text-foreground"
        >
          Zoom +
        </button>
        <button
          onClick={() => setScale(1)}
          className="px-2 py-1 rounded bg-accent text-foreground"
        >
          Centrar
        </button>
      </div>
      <div className="overflow-auto border border-border rounded-xl bg-background">
        <svg
          className="w-full min-w-[800px] h-[500px]"
          viewBox="0 0 800 600"
          preserveAspectRatio="xMidYMid meet"
          style={{ transform: `scale(${scale})`, transformOrigin: "center" }}
        >
          {edges.map((edge, i) => {
            const a = positions[edge.source];
            const b = positions[edge.target];
            if (!a || !b) return null;
            return (
              <line
                key={i}
                x1={a.x}
                y1={a.y}
                x2={b.x}
                y2={b.y}
                stroke="#64748b"
                strokeOpacity={0.25}
                strokeWidth={Math.max(0.5, (edge.weight || 1) * 1.2)}
              />
            );
          })}
          {nodes.map((node) => {
            const p = positions[node.id];
            if (!p) return null;
            const isHover = hover === node.id;
            const color =
              node.type === "entidade"
                ? "#f59e0b"
                : node.sentiment === "positivo"
                ? "#10b981"
                : node.sentiment === "negativo"
                ? "#ef4444"
                : "#10a37f";
            return (
              <g
                key={node.id}
                transform={`translate(${p.x}, ${p.y})`}
                className="cursor-pointer"
                onMouseEnter={() => setHover(node.id)}
                onMouseLeave={() => setHover(null)}
              >
                <circle
                  r={isHover ? 12 : 7}
                  fill={color}
                  stroke="#ffffff"
                  strokeWidth={1.5}
                  className="transition-all"
                />
                {isHover && (
                  <foreignObject x={20} y={-60} width={340} height={120}>
                    <div className="bg-card border border-border rounded-xl p-3 text-xs shadow-lg">
                      <p className="font-medium mb-1">{node.label}</p>
                      {node.entity_type && (
                        <p className="text-muted-foreground">Tipo: {node.entity_type}</p>
                      )}
                      {node.sentiment && (
                        <p className="text-muted-foreground">Sentimento: {node.sentiment}</p>
                      )}
                      {node.published && (
                        <p className="text-muted-foreground">{formatDate(node.published)}</p>
                      )}
                    </div>
                  </foreignObject>
                )}
              </g>
            );
          })}
        </svg>
      </div>
    </div>
  );
}
