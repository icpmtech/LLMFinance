import { useState, useEffect, useCallback } from "react";
import {
  ArrowLeft,
  ExternalLink,
  Calendar,
  TrendingUp,
  Frown,
  ChevronLeft,
  ChevronRight,
  Sparkles,
  Search,
  SlidersHorizontal,
} from "lucide-react";
import { SearchBox } from "../components/SearchBox";
import { searchElasticGlobal } from "../api";
import type { ElasticSearchGlobalItem, ElasticSuggestion } from "../types";

interface GlobalSearchPageProps {
  onSwitchView: () => void;
  onSelectTicker: (ticker: string) => void;
  initialQuery?: string;
}

const PAGE_SIZE = 10;

const sentimentClass = (s?: string) => {
  if (!s) return "";
  const v = s.toLowerCase();
  if (v.includes("posit")) return "text-teal-400 text-glow-teal";
  if (v.includes("negat")) return "text-rose-400 text-glow-rose";
  return "text-amber-400 text-glow-amber";
};

export function GlobalSearchPage({
  onSwitchView,
  onSelectTicker,
  initialQuery = "",
}: GlobalSearchPageProps) {
  const [query, setQuery] = useState(initialQuery);
  const [results, setResults] = useState<ElasticSearchGlobalItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const [sourceFilter, setSourceFilter] = useState("");
  const [sentimentFilter, setSentimentFilter] = useState("");
  const [topicFilter, setTopicFilter] = useState("");

  const filters = {
    source: sourceFilter,
    sentiment: sentimentFilter,
    topic: topicFilter,
  };

  const doSearch = useCallback(async (term: string, from = 0) => {
    setQuery(term);
    setOffset(from);
    setLoading(true);
    setError(null);
    try {
      const data = await searchElasticGlobal(term, {
        from,
        size: PAGE_SIZE,
        ...filters,
      });
      setResults(data.items ?? []);
      setTotal(data.total ?? 0);
      if (data.error) setError(data.error);
    } catch (err) {
      setResults([]);
      setTotal(0);
      setError(err instanceof Error ? err.message : "Erro na pesquisa");
    } finally {
      setLoading(false);
    }
  }, [filters.source, filters.sentiment, filters.topic]);

  useEffect(() => {
    if (initialQuery) {
      doSearch(initialQuery);
    }
  }, [initialQuery]);

  const handleResult = (q: string, items: ElasticSearchGlobalItem[]) => {
    setQuery(q);
    setResults(items);
    setTotal(items.length);
    setError(null);
    setOffset(0);
  };

  const handleSuggestion = (s: ElasticSuggestion) => {
    if (s.type === "ticker") {
      onSelectTicker(s.text.toUpperCase());
      return;
    }
    doSearch(s.text);
  };

  const applyFilters = () => {
    doSearch(query, 0);
  };

  const canPrev = offset > 0;
  const canNext = offset + PAGE_SIZE < total;

  return (
    <div className="min-h-screen w-full bg-background text-foreground orbit-bg">
      <div className="max-w-5xl mx-auto px-4 sm:px-6 py-8">
        <button
          onClick={onSwitchView}
          className="mb-6 flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition"
        >
          <ArrowLeft size={16} />
          Voltar
        </button>

        <section className="mb-8 fade-in">
          <div className="flex items-start justify-between gap-4 flex-wrap">
            <div className="flex-1 min-w-0">
              <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full glass-card gradient-border text-xs font-medium text-teal-300 mb-4">
                <Search size={14} />
                <span>Pesquisa Avançada</span>
              </div>
              <h1 className="text-3xl md:text-4xl font-bold mb-2 tracking-tight">
                Pesquisa Elasticsearch
              </h1>
              <p className="text-base md:text-lg text-muted-foreground max-w-2xl">
                Resultados unificados de notícias, sentimento e tickers.
                <span className="inline-flex items-center gap-1 ml-2 text-teal-400">
                  <Sparkles size={16} />
                  <span className="text-glow-teal">Premium</span>
                </span>
              </p>
            </div>
          </div>
        </section>

        <div className="mb-6 fade-in">
          <SearchBox
            mode="full"
            initialQuery={query}
            onResult={handleResult}
            onSelectSuggestion={handleSuggestion}
            filters={filters}
          />
        </div>

        <div className="glass-card gradient-border rounded-2xl p-5 mb-8 fade-in">
          <div className="flex items-center gap-2 mb-4 text-sm font-medium text-muted-foreground">
            <SlidersHorizontal size={16} />
            Filtros
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <label className="flex flex-col gap-1.5 text-xs text-muted-foreground">
              Fonte
              <input
                type="text"
                value={sourceFilter}
                onChange={(e) => setSourceFilter(e.target.value)}
                placeholder="Fonte..."
                className="w-full rounded-xl border border-border bg-card/60 px-3 py-2 text-sm text-foreground outline-none focus:border-primary transition"
              />
            </label>
            <label className="flex flex-col gap-1.5 text-xs text-muted-foreground">
              Sentimento
              <select
                value={sentimentFilter}
                onChange={(e) => setSentimentFilter(e.target.value)}
                className="w-full rounded-xl border border-border bg-card/60 px-3 py-2 text-sm text-foreground outline-none focus:border-primary transition"
              >
                <option value="">Todos os sentimentos</option>
                <option value="positivo">Positivo</option>
                <option value="neutro">Neutro</option>
                <option value="negativo">Negativo</option>
              </select>
            </label>
            <label className="flex flex-col gap-1.5 text-xs text-muted-foreground">
              Tópico
              <input
                type="text"
                value={topicFilter}
                onChange={(e) => setTopicFilter(e.target.value)}
                placeholder="Tópico..."
                className="w-full rounded-xl border border-border bg-card/60 px-3 py-2 text-sm text-foreground outline-none focus:border-primary transition"
              />
            </label>
            <div className="flex flex-col justify-end">
              <button
                onClick={applyFilters}
                className="neumorphic-btn w-full px-4 py-2 rounded-xl text-sm font-semibold text-foreground hover:text-teal-300 transition flex items-center justify-center gap-2"
              >
                <Sparkles size={14} />
                Filtrar
              </button>
            </div>
          </div>
        </div>

        {loading && (
          <div className="py-12 text-center text-muted-foreground glass-card gradient-border rounded-2xl fade-in">
            A pesquisar...
          </div>
        )}

        {!loading && error && (
          <div className="rounded-2xl border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive mb-6">
            {error}
          </div>
        )}

        {!loading && !error && query && (
          <div className="text-sm text-muted-foreground mb-4 stat-value">
            {total} resultado{total === 1 ? "" : "s"} para &quot;{query}&quot; (página{" "}
            {Math.floor(offset / PAGE_SIZE) + 1} de{" "}
            {Math.max(1, Math.ceil(total / PAGE_SIZE))})
          </div>
        )}

        {!loading && results.length === 0 && query && !error && (
          <div className="py-16 flex flex-col items-center gap-3 text-muted-foreground glass-card gradient-border rounded-2xl fade-in">
            <Frown size={40} />
            <p>Nenhum resultado encontrado para &quot;{query}&quot;</p>
          </div>
        )}

        <div className="space-y-4">
          {results.map((item, i) => (
            <article
              key={`${item.ticker}-${item.published}-${i}`}
              className="glass-card gradient-border rounded-2xl p-4 hover:bg-white/[0.04] transition fade-in"
            >
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground mb-2">
                    <button
                      onClick={() => onSelectTicker(item.ticker.toUpperCase())}
                      className="inline-flex items-center gap-1 font-semibold text-teal-400 hover:text-teal-300 text-glow-teal transition"
                    >
                      <TrendingUp size={12} />
                      {item.ticker.toUpperCase()}
                    </button>
                    {item.publisher && <span>• {item.publisher}</span>}
                    {item.published && (
                      <span className="inline-flex items-center gap-1">
                        <Calendar size={12} />
                        {new Date(item.published).toLocaleDateString()}
                      </span>
                    )}
                  </div>

                  <h3 className="text-base md:text-lg font-semibold leading-snug mb-2">
                    {item.url ? (
                      <a
                        href={item.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-blue-400 hover:text-blue-300 text-glow-blue transition inline-flex items-center gap-1"
                      >
                        {item.title || "Notícia"}
                        <ExternalLink size={14} />
                      </a>
                    ) : (
                      <span className="text-foreground">
                        {item.title || "Notícia"}
                      </span>
                    )}
                  </h3>

                  {item.summary && (
                    <p className="text-sm text-muted-foreground line-clamp-3 mb-3">
                      {item.summary}
                    </p>
                  )}

                  <div className="flex flex-wrap items-center gap-2 mt-2">
                    {item.sentiment && (
                      <span
                        className={[
                          "px-2.5 py-1 rounded-full text-[11px] font-medium glass-card",
                          sentimentClass(item.sentiment),
                        ].join(" ")}
                      >
                        {item.sentiment}
                      </span>
                    )}
                    {item.topics?.slice(0, 4).map((topic) => (
                      <span
                        key={topic}
                        className="px-2.5 py-1 rounded-full text-[11px] bg-secondary/80 text-secondary-foreground border border-border"
                      >
                        {topic}
                      </span>
                    ))}
                    {item.score !== undefined && item.score !== null && (
                      <span className="text-[11px] text-muted-foreground stat-value">
                        score: {item.score.toFixed(2)}
                      </span>
                    )}
                  </div>
                </div>
              </div>
            </article>
          ))}
        </div>

        {!loading && results.length > 0 && (
          <div className="mt-8 flex items-center justify-between glass-card gradient-border rounded-2xl p-3">
            <button
              onClick={() => doSearch(query, offset - PAGE_SIZE)}
              disabled={!canPrev || loading}
              className="neumorphic-btn flex items-center gap-1 px-4 py-2 rounded-xl text-sm font-medium text-foreground disabled:opacity-40 hover:text-teal-300 transition"
            >
              <ChevronLeft size={16} /> Anterior
            </button>
            <span className="text-sm text-muted-foreground stat-value">
              {offset + 1}-{Math.min(offset + PAGE_SIZE, total)} de {total}
            </span>
            <button
              onClick={() => doSearch(query, offset + PAGE_SIZE)}
              disabled={!canNext || loading}
              className="neumorphic-btn flex items-center gap-1 px-4 py-2 rounded-xl text-sm font-medium text-foreground disabled:opacity-40 hover:text-teal-300 transition"
            >
              Próximo <ChevronRight size={16} />
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
