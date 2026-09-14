import { useCallback, useEffect, useRef, useState } from "react";
import { Search, X, TrendingUp, Newspaper, Tag, Building } from "lucide-react";
import { autocompleteElastic, searchElasticGlobal } from "../api";
import type { ElasticSuggestion, ElasticSearchGlobalItem } from "../types";

interface SearchBoxProps {
  mode?: "compact" | "full";
  onResult?: (query: string, results: ElasticSearchGlobalItem[]) => void;
  onSelectSuggestion?: (suggestion: ElasticSuggestion) => void;
  initialQuery?: string;
  filters?: { source?: string; sentiment?: string; topic?: string };
}

const ICONS: Record<ElasticSuggestion["type"], React.ReactNode> = {
  ticker: <TrendingUp size={14} />,
  title: <Newspaper size={14} />,
  publisher: <Building size={14} />,
  topic: <Tag size={14} />,
};

const TYPE_LABEL: Record<ElasticSuggestion["type"], string> = {
  ticker: "Ticker",
  title: "Notícia",
  publisher: "Fonte",
  topic: "Tópico",
};

export function SearchBox({
  mode = "compact",
  onResult,
  onSelectSuggestion,
  initialQuery = "",
  filters = {},
}: SearchBoxProps) {
  const [query, setQuery] = useState(initialQuery);
  const [suggestions, setSuggestions] = useState<ElasticSuggestion[]>([]);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const containerRef = useRef<HTMLDivElement>(null);
  const debounceRef = useRef<number | undefined>(undefined);

  const fetchSuggestions = useCallback(async (term: string) => {
    if (!term.trim()) {
      setSuggestions([]);
      setOpen(false);
      return;
    }
    setLoading(true);
    try {
      const data = await autocompleteElastic(term.trim(), 10);
      setSuggestions(data.suggestions ?? []);
      setOpen((data.suggestions ?? []).length > 0);
      setActiveIndex(-1);
    } catch {
      setSuggestions([]);
      setOpen(false);
    } finally {
      setLoading(false);
    }
  }, []);

  const handleChange = (value: string) => {
    setQuery(value);
    window.clearTimeout(debounceRef.current);
    debounceRef.current = window.setTimeout(() => {
      fetchSuggestions(value);
    }, 250);
  };

  const handleSubmit = async (term: string) => {
    const trimmed = term.trim();
    if (!trimmed) return;
    setOpen(false);
    setLoading(true);
    setQuery(trimmed);
    try {
      const data = await searchElasticGlobal(trimmed, { size: 20, ...filters });
      onResult?.(trimmed, data.items ?? []);
    } finally {
      setLoading(false);
    }
  };

  const handleSelect = (s: ElasticSuggestion) => {
    setQuery(s.text);
    setOpen(false);
    setActiveIndex(-1);
    onSelectSuggestion?.(s);
    if (s.type === "ticker" || s.type === "title") {
      handleSubmit(s.text);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (!open) {
      if (e.key === "Enter") {
        e.preventDefault();
        handleSubmit(query);
      }
      return;
    }
    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        setActiveIndex((prev) => (prev + 1) % suggestions.length);
        break;
      case "ArrowUp":
        e.preventDefault();
        setActiveIndex((prev) => (prev - 1 + suggestions.length) % suggestions.length);
        break;
      case "Enter":
        e.preventDefault();
        if (activeIndex >= 0) {
          handleSelect(suggestions[activeIndex]);
        } else {
          handleSubmit(query);
        }
        break;
      case "Escape":
        setOpen(false);
        break;
    }
  };

  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  useEffect(() => {
    setQuery(initialQuery);
  }, [initialQuery]);

  const showClear = query.length > 0;

  return (
    <div ref={containerRef} className="relative w-full max-w-2xl">
      <div
        className={[
          "flex items-center gap-2 w-full rounded-full border border-border bg-card shadow-sm transition focus-within:ring-2 focus-within:ring-ring focus-within:border-primary",
          mode === "full" ? "px-5 py-3" : "px-4 py-2",
        ].join(" ")}
      >
        <Search className="text-muted-foreground shrink-0" size={mode === "full" ? 20 : 16} />
        <input
          type="text"
          value={query}
          onChange={(e) => handleChange(e.target.value)}
          onKeyDown={handleKeyDown}
          onFocus={() => {
            if (suggestions.length > 0) setOpen(true);
          }}
          placeholder="Pesquisar notícias, tickers, tópicos..."
          className="flex-1 bg-transparent outline-none text-foreground placeholder:text-muted-foreground"
          aria-label="Pesquisa global Elasticsearch"
          aria-autocomplete="list"
          aria-expanded={open}
          aria-activedescendant={activeIndex >= 0 ? `search-suggest-${activeIndex}` : undefined}
        />
        {showClear && (
          <button
            type="button"
            onClick={() => {
              setQuery("");
              setSuggestions([]);
              setOpen(false);
              setActiveIndex(-1);
            }}
            className="text-muted-foreground hover:text-foreground p-1 rounded-full"
            aria-label="Limpar"
          >
            <X size={mode === "full" ? 18 : 14} />
          </button>
        )}
        {mode === "full" && (
          <button
            type="button"
            onClick={() => handleSubmit(query)}
            disabled={loading || !query.trim()}
            className="px-4 py-1.5 rounded-full bg-primary text-primary-foreground text-sm font-medium disabled:opacity-50"
          >
            {loading ? "..." : "Pesquisar"}
          </button>
        )}
      </div>

      {open && (
        <ul
          className="absolute z-50 mt-2 w-full rounded-xl border border-border bg-card shadow-lg overflow-hidden"
          role="listbox"
        >
          {suggestions.length === 0 ? (
            <li className="px-4 py-3 text-sm text-muted-foreground">Sem sugestões</li>
          ) : (
            suggestions.map((s, i) => (
              <li
                key={`${s.type}-${s.text}-${i}`}
                id={`search-suggest-${i}`}
                role="option"
                aria-selected={i === activeIndex}
                onClick={() => handleSelect(s)}
                onMouseEnter={() => setActiveIndex(i)}
                className={[
                  "flex items-center gap-3 px-4 py-2.5 cursor-pointer transition",
                  i === activeIndex ? "bg-accent" : "hover:bg-accent/50",
                ].join(" ")}
              >
                <span className="text-muted-foreground shrink-0">{ICONS[s.type]}</span>
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-foreground truncate">{s.text}</p>
                  <p className="text-xs text-muted-foreground">{TYPE_LABEL[s.type]}</p>
                </div>
                {s.count !== undefined && (
                  <span className="text-xs text-muted-foreground shrink-0">{s.count}</span>
                )}
              </li>
            ))
          )}
        </ul>
      )}
    </div>
  );
}
