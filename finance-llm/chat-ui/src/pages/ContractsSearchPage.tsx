import { useState, useEffect, useMemo, useRef } from "react";
import {
  ArrowLeft,
  Search,
  FileText,
  MessageSquare,
  Loader2,
  Frown,
  Database,
  Filter,
  X,
  ChevronDown,
  ChevronUp,
  Sparkles,
} from "lucide-react";
import {
  getContractStatus,
  getContractYears,
  searchContracts,
  autocompleteContracts,
  chatContracts,
  ingestContracts,
} from "../api";
import type {
  ContractItem,
  ContractSearchRequest,
  ContractAutocompleteSuggestion,
  ContractChatSource,
} from "../types";

interface ContractsSearchPageProps {
  onSwitchView: () => void;
  onSwitchDashboard?: () => void;
}

function formatPrice(n?: number) {
  if (n === undefined || n === null) return "—";
  return n.toLocaleString("pt-PT", { style: "currency", currency: "EUR" });
}

function formatDate(d?: string) {
  if (!d) return "—";
  return new Date(d).toLocaleDateString("pt-PT");
}

function normalizeParties(parties: ContractItem["adjudicantes"]): { nome?: string; nif?: string }[] {
  if (!parties) return [];
  const list = Array.isArray(parties) ? parties : [parties];
  return list.reduce<{ nome?: string; nif?: string }[]>((acc, p: any) => {
    if (p?.parsed && Array.isArray(p.parsed)) acc.push(...p.parsed);
    else if (Array.isArray(p?.raw)) {
      acc.push(...p.raw.map((r: any) => (typeof r === "string" ? { nome: r.trim() } : r)).filter((r: any) => r?.nome || r?.nif));
    } else if (typeof p?.raw === "string") {
      acc.push(...p.raw.split(",").map((s: string) => ({ nome: s.trim() })));
    }
    return acc;
  }, []);
}

function partyNames(parties: ContractItem["adjudicantes"]): string {
  return (
    normalizeParties(parties)
      .map((p) => p.nome)
      .filter(Boolean)
      .join(", ") || "—"
  );
}

function firstNif(parties: ContractItem["adjudicantes"]): string {
  return normalizeParties(parties).map((p) => p.nif).filter(Boolean)[0] || "";
}

export function ContractsSearchPage({ onSwitchView, onSwitchDashboard }: ContractsSearchPageProps) {
  const [status, setStatus] = useState<{ total: number; years: number[] } | null>(null);
  const [years, setYears] = useState<{ available: number[]; indexed: { year: number; count: number }[] } | null>(null);
  const [query, setQuery] = useState("");
  const [year, setYear] = useState<number | "">("");
  const [entity, setEntity] = useState("");
  const [nif, setNif] = useState("");
  const [cpv, setCpv] = useState("");
  const [minPrice, setMinPrice] = useState<string>("");
  const [maxPrice, setMaxPrice] = useState<string>("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [from, setFrom] = useState(0);
  const size = 20;
  const [results, setResults] = useState<ContractItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [suggestions, setSuggestions] = useState<ContractAutocompleteSuggestion[]>([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const loadMoreRef = useRef<HTMLDivElement>(null);

  const [chatOpen, setChatOpen] = useState(false);
  const [chatQuestion, setChatQuestion] = useState("");
  const [chatAnswer, setChatAnswer] = useState<string | null>(null);
  const [chatSources, setChatSources] = useState<ContractChatSource[]>([]);
  const [chatLoading, setChatLoading] = useState(false);

  useEffect(() => {
    Promise.all([getContractStatus(), getContractYears()])
      .then(([s, y]) => {
        setStatus(s);
        setYears(y);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Erro ao carregar estado"));
  }, []);

  const buildRequest = (): ContractSearchRequest => ({
    q: query.trim() || undefined,
    year: year || undefined,
    entity: entity.trim() || undefined,
    nif: nif.trim() || undefined,
    cpv_code: cpv.trim() || undefined,
    min_price: minPrice ? parseFloat(minPrice) : undefined,
    max_price: maxPrice ? parseFloat(maxPrice) : undefined,
    start_date: startDate || undefined,
    end_date: endDate || undefined,
    size,
    from,
  });

  const doSearch = async (resetFrom = true) => {
    const nextFrom = resetFrom ? 0 : from;
    if (resetFrom) setLoading(true);
    else setLoadingMore(true);
    setError(null);
    try {
      const req = buildRequest();
      req.from = nextFrom;
      const data = await searchContracts(req);
      setResults((prev) => (resetFrom ? (data.items ?? []) : [...prev, ...(data.items ?? [])]));
      setTotal(data.total ?? 0);
      setFrom(nextFrom + (data.items ?? []).length);
      if (data.error) setError(data.error);
    } catch (err) {
      if (resetFrom) {
        setResults([]);
        setTotal(0);
      }
      setError(err instanceof Error ? err.message : "Erro na pesquisa");
    } finally {
      setLoading(false);
      setLoadingMore(false);
    }
  };

  useEffect(() => {
    const timer = setTimeout(() => {
      if (query.trim().length > 1) {
        autocompleteContracts(query.trim(), 8)
          .then((d) => {
            setSuggestions(d.suggestions ?? []);
            setShowSuggestions(true);
          })
          .catch(() => setShowSuggestions(false));
      } else {
        setShowSuggestions(false);
      }
    }, 250);
    return () => clearTimeout(timer);
  }, [query]);

  const handleIngest = async (ingestYear?: number) => {
    if (!ingestYear && !year) {
      setError("Escolhe um ano para indexar");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await ingestContracts({ year: ingestYear || (year as number) });
      setError(`Indexados ${res.indexed_count} contratos. ${res.message || ""}`);
      const [s, y] = await Promise.all([getContractStatus(), getContractYears()]);
      setStatus(s);
      setYears(y);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao indexar");
    } finally {
      setLoading(false);
    }
  };

  const handleChat = async () => {
    if (!chatQuestion.trim()) return;
    setChatLoading(true);
    setChatAnswer(null);
    setChatSources([]);
    try {
      const data = await chatContracts({ question: chatQuestion.trim() });
      setChatAnswer(data.answer);
      setChatSources(data.sources ?? []);
    } catch (err) {
      setChatAnswer(`❌ ${err instanceof Error ? err.message : "Erro no chat"}`);
    } finally {
      setChatLoading(false);
    }
  };

  const hasMore = results.length < total;

  const indexedYears = useMemo(() => new Set(years?.indexed.map((y) => y.year) ?? []), [years]);

  const activeFiltersCount = [year, entity, nif, cpv, minPrice, maxPrice, startDate, endDate].filter(Boolean).length;

  const resultsTotalValue = useMemo(
    () => results.reduce((acc, c) => acc + (c.precoContratual || 0), 0),
    [results],
  );

  const clearFilters = () => {
    setQuery("");
    setYear("");
    setEntity("");
    setNif("");
    setCpv("");
    setMinPrice("");
    setMaxPrice("");
    setStartDate("");
    setEndDate("");
    setFrom(0);
    doSearch(true);
  };

  useEffect(() => {
    const el = loadMoreRef.current;
    if (!el) return;
    const observer = new IntersectionObserver(
      (entries) => {
        const first = entries[0];
        if (first.isIntersecting && hasMore && !loading && !loadingMore) {
          doSearch(false);
        }
      },
      { rootMargin: "200px" },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [hasMore, loading, loadingMore]);

  return (
    <div className="min-h-screen w-full bg-background text-foreground orbit-bg">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 py-8">
        {/* Header */}
        <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4 mb-8">
          <button
            onClick={onSwitchView}
            className="self-start flex items-center gap-2 px-3 py-1.5 rounded-full glass-card text-sm text-muted-foreground hover:text-foreground transition"
          >
            <ArrowLeft size={16} />
            Voltar
          </button>
          <div className="flex items-center gap-3">
            {onSwitchDashboard && (
              <button
                onClick={onSwitchDashboard}
                className="flex items-center gap-2 px-4 py-2 rounded-xl glass-card hover:bg-white/5 transition text-sm"
              >
                <FileText size={18} className="text-amber-400" />
                <span className="hidden sm:inline">Dashboard</span>
              </button>
            )}
            <button
              onClick={() => setChatOpen((v) => !v)}
              className="flex items-center gap-2 px-5 py-2 rounded-xl bg-primary text-primary-foreground hover:opacity-90 transition text-sm font-medium shadow-lg shadow-primary/20"
            >
              <MessageSquare size={18} />
              {chatOpen ? "Fechar chat" : "Chat IA"}
            </button>
          </div>
        </div>

        {/* Hero */}
        <div className="mb-8">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full glass-card text-xs text-teal-300 mb-3">
            <Sparkles size={14} />
            Base contratual pública
          </div>
          <h1 className="text-3xl md:text-4xl font-bold flex items-center gap-3 mb-2">
            <span className="p-2 rounded-2xl bg-gradient-to-br from-teal-500/20 to-blue-500/20 border border-white/10">
              <Search size={32} className="text-teal-400" />
            </span>
            Pesquisa de Contratos
          </h1>
          <p className="text-muted-foreground max-w-2xl">
            {status
              ? `${status.total.toLocaleString("pt-PT")} contratos indexados. Explora por objeto, entidade, NIF, CPV, preço e datas.`
              : "A carregar estado..."}
          </p>
        </div>

        {/* Metrics */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-8">
          <div className="glass-card gradient-border rounded-2xl p-5 glow-teal">
            <p className="text-xs text-muted-foreground uppercase tracking-wider">Total de contratos</p>
            <p className="text-3xl font-bold stat-value text-glow-teal mt-1">
              {status ? status.total.toLocaleString("pt-PT") : "—"}
            </p>
          </div>
          <div className="glass-card gradient-border rounded-2xl p-5 glow-amber">
            <p className="text-xs text-muted-foreground uppercase tracking-wider">Total valor dos resultados</p>
            <p className="text-3xl font-bold stat-value text-glow-amber mt-1">
              {formatPrice(resultsTotalValue)}
            </p>
          </div>
          <div className="glass-card gradient-border rounded-2xl p-5 glow-blue">
            <p className="text-xs text-muted-foreground uppercase tracking-wider">Filtros ativos</p>
            <p className="text-3xl font-bold stat-value text-glow-blue mt-1">{activeFiltersCount}</p>
          </div>
        </div>

        {chatOpen && (
          <div className="glass-card rounded-2xl p-5 mb-8">
            <h2 className="font-semibold mb-3 flex items-center gap-2">
              <MessageSquare size={18} /> Perguntar sobre contratos
            </h2>
            <div className="flex gap-2 mb-3">
              <input
                value={chatQuestion}
                onChange={(e) => setChatQuestion(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && handleChat()}
                placeholder="Ex: quantos contratos foram atribuídos à Mota-Engil em 2024?"
                className="flex-1 min-w-0 px-3 py-2 rounded-xl bg-background/60 border border-border text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/60"
              />
              <button
                onClick={handleChat}
                disabled={chatLoading || !chatQuestion.trim()}
                className="px-4 py-2 rounded-xl bg-primary text-primary-foreground hover:opacity-90 transition disabled:opacity-50"
              >
                {chatLoading ? <Loader2 size={18} className="animate-spin" /> : "Perguntar"}
              </button>
            </div>
            {chatAnswer && (
              <div className="prose prose-sm max-w-none text-foreground">
                <p className="whitespace-pre-wrap">{chatAnswer}</p>
                {chatSources.length > 0 && (
                  <div className="mt-3">
                    <p className="text-xs text-muted-foreground mb-1">Fontes</p>
                    <div className="space-y-1">
                      {chatSources.map((s, i) => (
                        <div key={i} className="text-xs glass-card rounded-lg px-2 py-1">
                          {s.idcontrato} · {s.objectoContrato} · {formatPrice(s.precoContratual)}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {/* Search / filters */}
        <div className="glass-card rounded-2xl p-5 mb-8">
          <div className="relative">
            <div className="flex flex-col md:flex-row gap-3">
              <div className="relative flex-1">
                <Search size={18} className="absolute left-4 top-1/2 -translate-y-1/2 text-muted-foreground" />
                <input
                  ref={searchInputRef}
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  onFocus={() => query.trim().length > 1 && setShowSuggestions(true)}
                  placeholder="Pesquisar contratos por objeto, entidade, NIF, CPV..."
                  className="w-full pl-11 pr-3 py-3 rounded-xl bg-background/60 border border-border text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/60 text-base"
                />
                {showSuggestions && suggestions.length > 0 && (
                  <div className="absolute z-20 left-0 right-0 top-full mt-1 rounded-xl border border-border bg-card/95 backdrop-blur-md shadow-lg overflow-hidden">
                    {suggestions.map((s, i) => (
                      <button
                        key={i}
                        onClick={() => {
                          if (s.type === "cpv" && s.text.match(/^\d/)) {
                            setCpv(s.text);
                            setQuery("");
                          } else {
                            setEntity(s.text);
                            setQuery(s.text);
                          }
                          setShowSuggestions(false);
                          doSearch(true);
                        }}
                        className="w-full text-left px-3 py-2 text-sm hover:bg-white/5 transition flex items-center justify-between"
                      >
                        <span className="truncate">{s.text}</span>
                        <span className="text-xs text-muted-foreground ml-2 shrink-0">{s.type} · {s.count}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
              <button
                onClick={() => doSearch(true)}
                disabled={loading}
                className="px-5 py-3 rounded-xl bg-primary text-primary-foreground hover:opacity-90 transition disabled:opacity-50 flex items-center justify-center gap-2 font-medium shadow-lg shadow-primary/20"
              >
                {loading ? <Loader2 size={18} className="animate-spin" /> : <Search size={18} />}
                Pesquisar
              </button>
            </div>
          </div>

          <div className="mt-4 flex flex-wrap items-center gap-2">
            <button
              onClick={() => setAdvancedOpen((v) => !v)}
              className="flex items-center gap-2 px-4 py-3 rounded-xl bg-background/60 border border-border hover:bg-white/5 transition text-sm"
            >
              <Filter size={16} />
              Filtros avançados {activeFiltersCount > 0 && <span className="bg-primary text-primary-foreground rounded-full px-2 py-0.5 text-xs">{activeFiltersCount}</span>}
              {advancedOpen ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
            </button>
            {query && (
              <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full glass-card text-xs">
                Pesquisa: {query} <button onClick={() => { setQuery(""); searchInputRef.current?.focus(); }}><X size={12} /></button>
              </span>
            )}
            {year && (
              <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full glass-card text-xs">
                Ano: {year} <button onClick={() => setYear("")}><X size={12} /></button>
              </span>
            )}
            {entity && (
              <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full glass-card text-xs">
                Entidade: {entity} <button onClick={() => setEntity("")}><X size={12} /></button>
              </span>
            )}
            {nif && (
              <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full glass-card text-xs">
                NIF: {nif} <button onClick={() => setNif("")}><X size={12} /></button>
              </span>
            )}
            {cpv && (
              <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full glass-card text-xs">
                CPV: {cpv} <button onClick={() => setCpv("")}><X size={12} /></button>
              </span>
            )}
            {(minPrice || maxPrice) && (
              <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full glass-card text-xs">
                Preço: {minPrice || "0"} - {maxPrice || "∞"} <button onClick={() => { setMinPrice(""); setMaxPrice(""); }}><X size={12} /></button>
              </span>
            )}
            {activeFiltersCount > 0 && (
              <button
                onClick={clearFilters}
                className="text-xs text-muted-foreground hover:text-foreground underline ml-auto"
              >
                Limpar filtros
              </button>
            )}
          </div>

          {advancedOpen && (
            <div className="mt-4 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 pt-4 border-t border-border/50">
              <div>
                <label className="text-xs text-muted-foreground block mb-1">Ano</label>
                <select
                  value={year}
                  onChange={(e) => setYear(e.target.value === "" ? "" : parseInt(e.target.value))}
                  className="w-full px-3 py-2 rounded-xl bg-background/60 border border-border text-foreground focus:outline-none focus:ring-2 focus:ring-primary/60"
                >
                  <option value="">Todos</option>
                  {years?.available.map((y) => (
                    <option key={y} value={y}>
                      {y} {indexedYears.has(y) ? "✓" : ""}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-xs text-muted-foreground block mb-1">Entidade</label>
                <input
                  value={entity}
                  onChange={(e) => setEntity(e.target.value)}
                  placeholder="Nome da entidade"
                  className="w-full px-3 py-2 rounded-xl bg-background/60 border border-border text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/60"
                />
              </div>
              <div>
                <label className="text-xs text-muted-foreground block mb-1">NIF</label>
                <input
                  value={nif}
                  onChange={(e) => setNif(e.target.value)}
                  placeholder="NIF da entidade"
                  className="w-full px-3 py-2 rounded-xl bg-background/60 border border-border text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/60"
                />
              </div>
              <div>
                <label className="text-xs text-muted-foreground block mb-1">CPV</label>
                <input
                  value={cpv}
                  onChange={(e) => setCpv(e.target.value)}
                  placeholder="Código CPV"
                  className="w-full px-3 py-2 rounded-xl bg-background/60 border border-border text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/60"
                />
              </div>
              <div>
                <label className="text-xs text-muted-foreground block mb-1">Preço mín. (€)</label>
                <input
                  type="number"
                  value={minPrice}
                  onChange={(e) => setMinPrice(e.target.value)}
                  placeholder="0"
                  className="w-full px-3 py-2 rounded-xl bg-background/60 border border-border text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/60"
                />
              </div>
              <div>
                <label className="text-xs text-muted-foreground block mb-1">Preço máx. (€)</label>
                <input
                  type="number"
                  value={maxPrice}
                  onChange={(e) => setMaxPrice(e.target.value)}
                  placeholder="∞"
                  className="w-full px-3 py-2 rounded-xl bg-background/60 border border-border text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/60"
                />
              </div>
              <div>
                <label className="text-xs text-muted-foreground block mb-1">Data início</label>
                <input
                  type="date"
                  value={startDate}
                  onChange={(e) => setStartDate(e.target.value)}
                  className="w-full px-3 py-2 rounded-xl bg-background/60 border border-border text-foreground focus:outline-none focus:ring-2 focus:ring-primary/60"
                />
              </div>
              <div>
                <label className="text-xs text-muted-foreground block mb-1">Data fim</label>
                <input
                  type="date"
                  value={endDate}
                  onChange={(e) => setEndDate(e.target.value)}
                  className="w-full px-3 py-2 rounded-xl bg-background/60 border border-border text-foreground focus:outline-none focus:ring-2 focus:ring-primary/60"
                />
              </div>
              <div className="flex items-end gap-2 sm:col-span-2 lg:col-span-4">
                <button
                  onClick={() => handleIngest()}
                  disabled={loading || !year}
                  className="px-4 py-2 rounded-xl bg-secondary text-secondary-foreground hover:bg-accent transition disabled:opacity-50 flex items-center justify-center gap-2"
                >
                  <Database size={16} />
                  Indexar {year || "ano"}
                </button>
                <button
                  onClick={clearFilters}
                  className="px-4 py-2 rounded-xl border border-border hover:bg-white/5 transition"
                >
                  Limpar
                </button>
              </div>
            </div>
          )}

          {error && (
            <div className={`mt-4 rounded-xl px-3 py-2 text-sm ${error.startsWith("Indexados") ? "bg-primary/10 text-primary" : "bg-destructive/10 text-destructive"}`}>
              {error}
            </div>
          )}
        </div>

        {results.length > 0 && (
          <div className="mb-4 text-sm text-muted-foreground flex items-center justify-between">
            <span>
              A mostrar {results.length.toLocaleString("pt-PT")} de {total.toLocaleString("pt-PT")} resultado{total === 1 ? "" : "s"}
            </span>
          </div>
        )}

        {!loading && results.length === 0 && !error && (
          <div className="py-16 flex flex-col items-center gap-3 text-muted-foreground fade-in">
            <div className="inline-flex p-5 rounded-3xl glass-card mb-2">
              <Frown size={40} className="opacity-60" />
            </div>
            <p>Nenhum contrato encontrado.</p>
            <p className="text-sm">Experimenta pesquisar por objeto, entidade ou CPV.</p>
          </div>
        )}

        <div className="space-y-4">
          {results.map((c, i) => (
            <article
              key={`${c.idcontrato || i}-${i}`}
              className="glass-card gradient-border rounded-2xl p-5 hover:-translate-y-1 hover:bg-white/[0.04] transition-all duration-300 fade-in"
              style={{ animationDelay: `${Math.min(i * 40, 600)}ms` }}
            >
              <div className="flex flex-col md:flex-row md:items-start md:justify-between gap-3">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 text-xs text-muted-foreground mb-2 flex-wrap">
                    <span className="px-2 py-0.5 rounded-full glass-card">{c.Ano ?? "—"}</span>
                    <span>{Array.isArray(c.tipoContrato) ? c.tipoContrato.join(", ") : c.tipoContrato || c.TipoAnuncio || "Contrato"}</span>
                    {c.idcontrato && <span className="truncate">ID: {c.idcontrato}</span>}
                  </div>
                  <h3 className="font-semibold text-foreground leading-tight mb-1 truncate-2-lines">
                    {c.objectoContrato || "Sem objeto definido"}
                  </h3>
                  {c.descContrato && (
                    <p className="text-sm text-muted-foreground line-clamp-2">{c.descContrato}</p>
                  )}
                  <div className="mt-2 text-sm space-y-1">
                    <p><span className="text-muted-foreground">Adjudicante:</span> {partyNames(c.adjudicantes)} {firstNif(c.adjudicantes) && `(${firstNif(c.adjudicantes)})`}</p>
                    <p><span className="text-muted-foreground">Adjudicatário:</span> {partyNames(c.adjudicatarios)}</p>
                    {c.localExecucao && <p><span className="text-muted-foreground">Local:</span> {c.localExecucao}</p>}
                    {c.cpv && c.cpv.length > 0 && (
                      <p className="text-xs text-muted-foreground">
                        CPV: {c.cpv.map((x) => `${x.code} ${x.description}`).join("; ")}
                      </p>
                    )}
                  </div>
                </div>
                <div className="shrink-0 text-right">
                  <div className="text-lg font-bold stat-value text-glow-amber">{formatPrice(c.precoContratual)}</div>
                  <div className="text-xs text-muted-foreground">
                    Publicação {formatDate(c.dataPublicacao)} · Celebração {formatDate(c.dataCelebracaoContrato)}
                  </div>
                </div>
              </div>
            </article>
          ))}
        </div>

        <div ref={loadMoreRef} className="py-8 flex flex-col items-center justify-center text-muted-foreground">
          {loadingMore && (
            <div className="flex items-center gap-2 text-sm">
              <Loader2 size={18} className="animate-spin" />
              A carregar mais contratos...
            </div>
          )}
          {!loadingMore && hasMore && results.length > 0 && (
            <button
              onClick={() => doSearch(false)}
              disabled={loading || loadingMore}
              className="px-4 py-2 rounded-xl border border-border hover:bg-white/5 transition disabled:opacity-50 text-sm"
            >
              Carregar mais
            </button>
          )}
          {!loadingMore && !hasMore && results.length > 0 && (
            <span className="text-xs">Fim dos resultados</span>
          )}
        </div>
      </div>
    </div>
  );
}
