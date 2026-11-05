import { useEffect, useRef, useState } from "react";
import { Search, Loader2, X } from "lucide-react";
import { searchTickers, type TickerSearchItem } from "../../portfolioApi";

/** Caixa de pesquisa de tickers (Yahoo Finance) com resultados clicáveis. */
export function TickerPicker({
  onPick,
  placeholder = "Pesquisar ticker ou empresa (ex.: AAPL, Apple)",
  autoFocus = false,
}: {
  onPick: (item: TickerSearchItem) => void;
  placeholder?: string;
  autoFocus?: boolean;
}) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<TickerSearchItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const boxRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const term = query.trim();
    if (term.length < 1) {
      setResults([]);
      setError(null);
      return;
    }
    let cancelled = false;
    const timer = window.setTimeout(async () => {
      setLoading(true);
      setError(null);
      try {
        const items = await searchTickers(term, 10);
        if (!cancelled) {
          setResults(items);
          setOpen(true);
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Falha na pesquisa");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }, 320);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [query]);

  useEffect(() => {
    const handler = (event: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const pick = (item: TickerSearchItem) => {
    onPick(item);
    setQuery("");
    setResults([]);
    setOpen(false);
  };

  return (
    <div ref={boxRef} className="relative">
      <div className="flex items-center gap-2 rounded-md border border-slate-700 bg-slate-900 px-3 py-2">
        <Search className="h-4 w-4 text-slate-500" />
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onFocus={() => results.length && setOpen(true)}
          placeholder={placeholder}
          autoFocus={autoFocus}
          className="w-full bg-transparent text-sm text-slate-200 placeholder:text-slate-600 focus:outline-none"
        />
        {loading && <Loader2 className="h-4 w-4 animate-spin text-slate-500" />}
        {query && !loading && (
          <button type="button" onClick={() => setQuery("")} aria-label="Limpar">
            <X className="h-4 w-4 text-slate-500 hover:text-slate-300" />
          </button>
        )}
      </div>

      {error && <div className="mt-1 text-xs text-rose-400">{error}</div>}

      {open && results.length > 0 && (
        <div className="absolute z-30 mt-1 max-h-80 w-full overflow-auto rounded-md border border-slate-700 bg-slate-900 shadow-xl">
          {results.map((item) => (
            <button
              key={`${item.ticker}-${item.exchange}`}
              type="button"
              onClick={() => pick(item)}
              className="flex w-full items-start justify-between gap-3 border-b border-slate-800 px-3 py-2 text-left last:border-0 hover:bg-slate-800"
            >
              <span className="min-w-0">
                <span className="block text-sm font-medium text-slate-100">{item.ticker}</span>
                <span className="block truncate text-xs text-slate-500">{item.name}</span>
              </span>
              <span className="shrink-0 text-right text-[11px] uppercase text-slate-500">
                {item.exchange || item.type}
                {item.sector ? <span className="block normal-case text-slate-600">{item.sector}</span> : null}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
