import { useState, useEffect, useCallback } from "react";
import { ArrowLeft, ExternalLink, Calendar, TrendingUp, Frown, ChevronLeft, ChevronRight } from "lucide-react";
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
  if (v.includes("posit")) return "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200";
  if (v.includes("negat")) return "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200";
  return "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200";
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
    <div className="min-h-screen w-full bg-background text-foreground">
      <div className="max-w-4xl mx-auto px-3 md:px-4 py-4 md:py-6">
        <button
          onClick={onSwitchView}
          className="mb-3 md:mb-4 flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition"
        >
          <ArrowLeft size={16} />
          Voltar
        </button>

        <div className="mb-4 md:mb-6">
          <h1 className="text-xl md:text-2xl font-bold mb-3 md:mb-4">Pesquisa Elasticsearch</h1>
          <SearchBox
            mode="full"
            initialQuery={query}
            onResult={handleResult}
            onSelectSuggestion={handleSuggestion}
            filters={filters}
          />
        </div>

        <div className="flex flex-col md:flex-row gap-2 md:gap-3 mb-4 md:mb-6">
          <input
            type="text"
            value={sourceFilter}
            onChange={(e) => setSourceFilter(e.target.value)}
            placeholder="Fonte..."
            className="flex-1 rounded-lg border border-border bg-card px-3 py-2 text-sm outline-none focus:border-primary"
          />
          <select
            value={sentimentFilter}
            onChange={(e) => setSentimentFilter(e.target.value)}
            className="flex-1 rounded-lg border border-border bg-card px-3 py-2 text-sm outline-none focus:border-primary"
          >
            <option value="">Todos os sentimentos</option>
            <option value="positivo">Positivo</option>
            <option value="neutro">Neutro</option>
            <option value="negativo">Negativo</option>
          </select>
          <input
            type="text"
            value={topicFilter}
            onChange={(e) => setTopicFilter(e.target.value)}
            placeholder="Tópico..."
            className="flex-1 rounded-lg border border-border bg-card px-3 py-2 text-sm outline-none focus:border-primary"
          />
          <button
            onClick={applyFilters}
            className="px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 transition"
          >
            Filtrar
          </button>
        </div>

        {loading && (
          <div className="py-12 text-center text-muted-foreground">
            A pesquisar...
          </div>
        )}

        {!loading && error && (
          <div className="rounded-xl border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
            {error}
          </div>
        )}

        {!loading && !error && query && (
          <div className="text-xs md:text-sm text-muted-foreground mb-3 md:mb-4">
            {total} resultado{total === 1 ? "" : "s"} para "{query}" (página {Math.floor(offset / PAGE_SIZE) + 1} de {Math.max(1, Math.ceil(total / PAGE_SIZE))})
          </div>
        )}

        {!loading && results.length === 0 && query && !error && (
          <div className="py-16 flex flex-col items-center gap-3 text-muted-foreground">
            <Frown size={40} />
            <p>Nenhum resultado encontrado para "{query}"</p>
          </div>
        )}

        <div className="space-y-3 md:space-y-4">
          {results.map((item, i) => (
            <article
              key={`${item.ticker}-${item.published}-${i}`}
              className="rounded-xl border border-border bg-card p-3 md:p-4 shadow-sm hover:shadow-md transition"
            >
              <div className="flex items-start justify-between gap-3 md:gap-4">
                <div className="flex-1 min-w-0">
                  <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] md:text-xs text-muted-foreground mb-1">
                    <button
                      onClick={() => onSelectTicker(item.ticker.toUpperCase())}
                      className="inline-flex items-center gap-1 font-semibold text-primary hover:underline"
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

                  <h3 className="text-sm md:text-lg font-semibold leading-snug mb-1">
                    {item.url ? (
                      <a
                        href={item.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-primary hover:underline inline-flex items-center gap-1"
                      >
                        {item.title || "Notícia"}
                        <ExternalLink size={14} />
                      </a>
                    ) : (
                      item.title || "Notícia"
                    )}
                  </h3>

                  {item.summary && (
                    <p className="text-xs md:text-sm text-muted-foreground line-clamp-3 mb-2">
                      {item.summary}
                    </p>
                  )}

                  <div className="flex flex-wrap items-center gap-1.5 md:gap-2 mt-2">
                    {item.sentiment && (
                      <span
                        className={[
                          "px-2 py-0.5 rounded-full text-[10px] md:text-xs font-medium",
                          sentimentClass(item.sentiment),
                        ].join(" ")}
                      >
                        {item.sentiment}
                      </span>
                    )}
                    {item.topics?.slice(0, 4).map((topic) => (
                      <span
                        key={topic}
                        className="px-2 py-0.5 rounded-full text-[10px] md:text-xs bg-secondary text-secondary-foreground"
                      >
                        {topic}
                      </span>
                    ))}
                    {item.score !== undefined && item.score !== null && (
                      <span className="text-[10px] md:text-xs text-muted-foreground">
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
          <div className="mt-6 flex items-center justify-between">
            <button
              onClick={() => doSearch(query, offset - PAGE_SIZE)}
              disabled={!canPrev || loading}
              className="flex items-center gap-1 px-3 py-2 rounded-lg border border-border bg-card text-sm disabled:opacity-40 hover:bg-accent transition"
            >
              <ChevronLeft size={16} /> Anterior
            </button>
            <span className="text-xs md:text-sm text-muted-foreground">
              {offset + 1}-{Math.min(offset + PAGE_SIZE, total)} de {total}
            </span>
            <button
              onClick={() => doSearch(query, offset + PAGE_SIZE)}
              disabled={!canNext || loading}
              className="flex items-center gap-1 px-3 py-2 rounded-lg border border-border bg-card text-sm disabled:opacity-40 hover:bg-accent transition"
            >
              Próximo <ChevronRight size={16} />
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
