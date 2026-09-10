import { useState, useEffect } from "react";
import { ArrowLeft, ExternalLink, Calendar, TrendingUp, Frown } from "lucide-react";
import { SearchBox } from "../components/SearchBox";
import { searchElasticGlobal } from "../api";
import type { ElasticSearchGlobalItem, ElasticSuggestion } from "../types";

interface GlobalSearchPageProps {
  onSwitchView: () => void;
  onSelectTicker: (ticker: string) => void;
  initialQuery?: string;
}

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

  useEffect(() => {
    if (initialQuery) {
      doSearch(initialQuery);
    }
  }, [initialQuery]);

  const doSearch = async (term: string) => {
    setQuery(term);
    setLoading(true);
    setError(null);
    try {
      const data = await searchElasticGlobal(term, 20);
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
  };

  const handleResult = (q: string, items: ElasticSearchGlobalItem[]) => {
    setQuery(q);
    setResults(items);
    setTotal(items.length);
    setError(null);
  };

  const handleSuggestion = (s: ElasticSuggestion) => {
    if (s.type === "ticker") {
      onSelectTicker(s.text.toUpperCase());
      return;
    }
    doSearch(s.text);
  };

  return (
    <div className="min-h-screen w-full bg-background text-foreground">
      <div className="max-w-4xl mx-auto px-4 py-6">
        <button
          onClick={onSwitchView}
          className="mb-4 flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition"
        >
          <ArrowLeft size={16} />
          Voltar
        </button>

        <div className="mb-6">
          <h1 className="text-2xl font-bold mb-4">Pesquisa Elasticsearch</h1>
          <SearchBox
            mode="full"
            initialQuery={query}
            onResult={handleResult}
            onSelectSuggestion={handleSuggestion}
          />
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
          <div className="text-sm text-muted-foreground mb-4">
            {total} resultado{total === 1 ? "" : "s"} para "{query}"
          </div>
        )}

        {!loading && results.length === 0 && query && !error && (
          <div className="py-16 flex flex-col items-center gap-3 text-muted-foreground">
            <Frown size={40} />
            <p>Nenhum resultado encontrado para "{query}"</p>
          </div>
        )}

        <div className="space-y-4">
          {results.map((item, i) => (
            <article
              key={`${item.ticker}-${item.published}-${i}`}
              className="rounded-xl border border-border bg-card p-4 shadow-sm hover:shadow-md transition"
            >
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 text-xs text-muted-foreground mb-1">
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

                  <h3 className="text-lg font-semibold leading-snug mb-1">
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
                    <p className="text-sm text-muted-foreground line-clamp-3 mb-2">
                      {item.summary}
                    </p>
                  )}

                  <div className="flex flex-wrap items-center gap-2 mt-2">
                    {item.sentiment && (
                      <span
                        className={[
                          "px-2 py-0.5 rounded-full text-xs font-medium",
                          sentimentClass(item.sentiment),
                        ].join(" ")}
                      >
                        {item.sentiment}
                      </span>
                    )}
                    {item.topics?.map((topic) => (
                      <span
                        key={topic}
                        className="px-2 py-0.5 rounded-full text-xs bg-secondary text-secondary-foreground"
                      >
                        {topic}
                      </span>
                    ))}
                    {item.score !== undefined && item.score !== null && (
                      <span className="text-xs text-muted-foreground">
                        score: {item.score.toFixed(2)}
                      </span>
                    )}
                  </div>
                </div>
              </div>
            </article>
          ))}
        </div>
      </div>
    </div>
  );
}
