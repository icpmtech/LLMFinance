import { useState, useRef, useEffect, useCallback, useMemo } from "react";
import { X, Search, Check, ChevronDown, Briefcase } from "lucide-react";

const API_BASE = import.meta.env.VITE_API_URL || "http://127.0.0.1:8002";

export interface CaeEntry {
  code: string;
  name: string;
  level: string;
  section: string;
  path: string;
}

interface CaeMultiSelectProps {
  selected: string[];
  onChange: (codes: string[]) => void;
  placeholder?: string;
  id?: string;
  disabled?: boolean;
  /** Número máximo de sugestões no dropdown. */
  limit?: number;
  /** Estilo compacto para cabeçalhos de filtro. */
  compact?: boolean;
  className?: string;
}

function normalizeCaeCode(value: string): string {
  return value.replace(/\D/g, "").slice(0, 5);
}

async function fetchCaeSuggestions(q: string, limit = 50): Promise<CaeEntry[]> {
  const res = await fetch(
    `${API_BASE}/cae/autocomplete?q=${encodeURIComponent(q)}&limit=${limit}`,
  );
  if (!res.ok) return [];
  const data = (await res.json()) as { items?: CaeEntry[] };
  return data.items ?? [];
}

export function CaeMultiSelect({
  selected,
  onChange,
  placeholder = "Pesquisar CAE por código ou descrição…",
  id,
  disabled,
  limit = 50,
  compact,
  className,
}: CaeMultiSelectProps) {
  const [query, setQuery] = useState("");
  const [suggestions, setSuggestions] = useState<CaeEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const debounceRef = useRef<number | null>(null);

  const selectedSet = useMemo(() => new Set(selected), [selected]);

  const load = useCallback(
    async (text: string) => {
      if (!text.trim()) {
        setSuggestions([]);
        setLoading(false);
        return;
      }
      abortRef.current?.abort();
      abortRef.current = new AbortController();
      setLoading(true);
      try {
        const items = await fetchCaeSuggestions(text, limit);
        const deduped = items.filter((it) => !selectedSet.has(it.code));
        setSuggestions(deduped);
        setActiveIndex(-1);
      } catch {
        setSuggestions([]);
      } finally {
        setLoading(false);
      }
    },
    [limit, selectedSet],
  );

  useEffect(() => {
    if (debounceRef.current) window.clearTimeout(debounceRef.current);
    debounceRef.current = window.setTimeout(() => load(query), 180);
    return () => {
      if (debounceRef.current) window.clearTimeout(debounceRef.current);
    };
  }, [query, load]);

  useEffect(() => {
    function onClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
        setSuggestions([]);
      }
    }
    if (open) document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, [open]);

  const addCode = useCallback(
    (code: string) => {
      const clean = normalizeCaeCode(code);
      if (!clean || selectedSet.has(clean)) return;
      onChange([...selected, clean]);
      setQuery("");
      setSuggestions([]);
      setActiveIndex(-1);
      inputRef.current?.focus();
    },
    [onChange, selected, selectedSet],
  );

  const removeCode = useCallback(
    (code: string) => {
      onChange(selected.filter((c) => c !== code));
    },
    [onChange, selected],
  );

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (!open && suggestions.length === 0 && e.key !== "Enter" && e.key !== "Backspace") {
      return;
    }
    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        setActiveIndex((prev) => Math.min(prev + 1, suggestions.length - 1));
        break;
      case "ArrowUp":
        e.preventDefault();
        setActiveIndex((prev) => Math.max(prev - 1, -1));
        break;
      case "Enter":
        e.preventDefault();
        if (activeIndex >= 0 && suggestions[activeIndex]) {
          addCode(suggestions[activeIndex].code);
        } else if (query.trim()) {
          addCode(query);
        }
        break;
      case "Escape":
        setOpen(false);
        setSuggestions([]);
        break;
      case "Backspace":
        if (!query && selected.length) {
          removeCode(selected[selected.length - 1]);
        }
        break;
    }
  };

  const inputHeight = compact ? "py-1.5" : "py-2";
  const textSize = compact ? "text-xs" : "text-sm";

  return (
    <div ref={containerRef} className={`relative w-full ${className ?? ""}`} id={id}>
      <div
        onClick={() => inputRef.current?.focus()}
        className={[
          "flex flex-wrap items-center gap-1.5 rounded-xl border border-white/10 bg-white/[0.04]",
          "px-2.5 focus-within:border-teal-400/50 focus-within:ring-1 focus-within:ring-teal-400/30",
          inputHeight,
        ].join(" ")}
      >
        <Briefcase size={compact ? 12 : 14} className="shrink-0 text-slate-400" />
        {selected.map((code) => (
          <span
            key={code}
            className="inline-flex items-center gap-1 rounded-md bg-teal-500/20 px-1.5 py-0.5 text-xs text-teal-100"
          >
            {code}
            <button
              type="button"
              onClick={() => removeCode(code)}
              className="rounded p-0.5 hover:bg-teal-500/30"
              aria-label={`Remover CAE ${code}`}
            >
              <X size={10} />
            </button>
          </span>
        ))}
        <input
          ref={inputRef}
          type="text"
          value={query}
          disabled={disabled}
          onChange={(e) => {
            setQuery(e.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={handleKeyDown}
          placeholder={selected.length ? "" : placeholder}
          className={[
            "min-w-[120px] flex-1 bg-transparent outline-none placeholder:text-slate-500",
            textSize,
          ].join(" ")}
        />
        {loading && <Search size={compact ? 12 : 14} className="spin shrink-0 text-slate-400" />}
        {!loading && (
          <ChevronDown
            size={compact ? 12 : 14}
            className="shrink-0 text-slate-400"
            onClick={() => setOpen((v) => !v)}
          />
        )}
      </div>

      {open && suggestions.length > 0 && (
        <div className="absolute z-50 mt-1 max-h-72 w-full overflow-y-auto rounded-xl border border-white/10 bg-[#0f172a] shadow-xl">
          {suggestions.map((item, idx) => {
            const highlighted = idx === activeIndex;
            const isSelected = selectedSet.has(item.code);
            return (
              <button
                key={`${item.code}-${idx}`}
                type="button"
                onClick={() => addCode(item.code)}
                className={[
                  "w-full px-3 py-2 text-left transition-colors",
                  highlighted ? "bg-teal-500/15" : "hover:bg-white/5",
                ].join(" ")}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-medium text-teal-100">{item.code}</span>
                  {isSelected ? (
                    <Check size={14} className="text-teal-400" />
                  ) : (
                    <span className="text-[10px] text-slate-400">{item.level}</span>
                  )}
                </div>
                <div className="text-xs text-slate-300">{item.name}</div>
                {item.path && (
                  <div className="text-[10px] text-slate-500">{item.path}</div>
                )}
              </button>
            );
          })}
        </div>
      )}

      {open && !loading && query.trim() && suggestions.length === 0 && (
        <div className="absolute z-50 mt-1 w-full rounded-xl border border-white/10 bg-[#0f172a] px-3 py-2 text-xs text-slate-400 shadow-xl">
          Sem resultados. Tente outro código ou designação.
        </div>
      )}
    </div>
  );
}

export function CaeDescription({ code, className }: { code: string; className?: string }) {
  const [entry, setEntry] = useState<CaeEntry | null>(null);
  useEffect(() => {
    if (!code) return;
    fetch(`${API_BASE}/cae/${encodeURIComponent(code)}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => setEntry(d))
      .catch(() => setEntry(null));
  }, [code]);
  if (!entry) return null;
  return <span className={className}>{entry.name}</span>;
}
