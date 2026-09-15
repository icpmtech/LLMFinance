import { useState, useEffect, useRef } from "react";
import {
  ArrowLeft,
  Search,
  Building2,
  Loader2,
  Frown,
  Filter,
  X,
  ChevronDown,
  ChevronUp,
  BarChart3,
  Sparkles,
  Briefcase,
  HandCoins,
} from "lucide-react";
import { searchCompanies } from "../api";
import type { CompanySummary, CompanySearchRequest } from "../types";

interface CompanyDirectoryPageProps {
  onSwitchView: () => void;
  onSwitchDashboard?: () => void;
  onSelectCompany: (nif: string) => void;
}

function formatPrice(n?: number) {
  if (n === undefined || n === null) return "—";
  return n.toLocaleString("pt-PT", { style: "currency", currency: "EUR" });
}

export function CompanyDirectoryPage({
  onSwitchView,
  onSwitchDashboard,
  onSelectCompany,
}: CompanyDirectoryPageProps) {
  const [query, setQuery] = useState("");
  const [role, setRole] = useState<CompanySearchRequest["role"]>("all");
  const [minContracts, setMinContracts] = useState<string>("1");
  const [minValue, setMinValue] = useState<string>("");
  const [maxValue, setMaxValue] = useState<string>("");
  const [year, setYear] = useState<string>("");
  const [from, setFrom] = useState(0);
  const size = 20;
  const [results, setResults] = useState<CompanySummary[]>([]);
  const [total, setTotal] = useState(0);
  const [totalValue, setTotalValue] = useState(0);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const loadMoreRef = useRef<HTMLDivElement>(null);

  const buildRequest = (): CompanySearchRequest => ({
    q: query.trim() || undefined,
    role: role || "all",
    min_contracts: minContracts ? parseInt(minContracts, 10) : 1,
    min_value: minValue ? parseFloat(minValue) : undefined,
    max_value: maxValue ? parseFloat(maxValue) : undefined,
    year: year ? parseInt(year, 10) : undefined,
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
      const data = await searchCompanies(req);
      const items = data.items ?? [];
      setResults((prev) => (resetFrom ? items : [...prev, ...items]));
      setTotal(data.total ?? 0);
      setFrom(nextFrom + items.length);
      const valueSum = items.reduce((acc, c) => acc + (c.total_value || 0), 0);
      setTotalValue((prev) => (resetFrom ? valueSum : prev + valueSum));
      if (data.error) setError(data.error);
    } catch (err) {
      if (resetFrom) {
        setResults([]);
        setTotal(0);
        setTotalValue(0);
      }
      setError(err instanceof Error ? err.message : "Erro na pesquisa");
    } finally {
      setLoading(false);
      setLoadingMore(false);
    }
  };

  useEffect(() => {
    doSearch(true);
  }, []);

  useEffect(() => {
    const el = loadMoreRef.current;
    if (!el) return;
    const observer = new IntersectionObserver(
      (entries) => {
        const first = entries[0];
        if (first.isIntersecting && results.length < total && !loading && !loadingMore) {
          doSearch(false);
        }
      },
      { rootMargin: "200px" },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [results.length, total, loading, loadingMore]);

  const activeFiltersCount = [role !== "all", minContracts !== "1", minValue, maxValue, year].filter(Boolean).length;

  const clearFilters = () => {
    setQuery("");
    setRole("all");
    setMinContracts("1");
    setMinValue("");
    setMaxValue("");
    setYear("");
    setFrom(0);
    doSearch(true);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      setFrom(0);
      doSearch(true);
    }
  };

  const companyIdentifier = (c: CompanySummary) => c.nif || c.normalized_name || c.name;

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
                <BarChart3 size={18} className="text-amber-400" />
                Dashboard
              </button>
            )}
            <button
              onClick={() => {
                setFrom(0);
                doSearch(true);
              }}
              disabled={loading}
              className="flex items-center gap-2 px-5 py-2 rounded-xl bg-primary text-primary-foreground hover:opacity-90 transition text-sm font-medium shadow-lg shadow-primary/20 disabled:opacity-50"
            >
              {loading ? <Loader2 size={18} className="animate-spin" /> : <Search size={18} />}
              Pesquisar
            </button>
          </div>
        </div>

        {/* Hero title + metrics */}
        <div className="mb-8">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full glass-card text-xs text-teal-300 mb-3">
            <Sparkles size={14} />
            Diretório de entidades públicas
          </div>
          <h1 className="text-3xl md:text-4xl font-bold flex items-center gap-3 mb-2">
            <span className="p-2 rounded-2xl bg-gradient-to-br from-teal-500/20 to-blue-500/20 border border-white/10">
              <Building2 size={32} className="text-teal-400" />
            </span>
            Diretório de Empresas
          </h1>
          <p className="text-muted-foreground max-w-2xl">
            Pesquisa, analisa e explora as entidades adjudicantes e adjudicatárias dos contratos públicos.
          </p>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-8">
          <div className="glass-card gradient-border rounded-2xl p-5 glow-teal">
            <p className="text-xs text-muted-foreground uppercase tracking-wider">Entidades encontradas</p>
            <p className="text-3xl font-bold stat-value text-glow-teal mt-1">{total.toLocaleString("pt-PT")}</p>
          </div>
          <div className="glass-card gradient-border rounded-2xl p-5 glow-amber">
            <p className="text-xs text-muted-foreground uppercase tracking-wider">Valor agregado</p>
            <p className="text-3xl font-bold stat-value text-glow-amber mt-1">{formatPrice(totalValue)}</p>
          </div>
          <div className="glass-card gradient-border rounded-2xl p-5 glow-blue">
            <p className="text-xs text-muted-foreground uppercase tracking-wider">Papéis</p>
            <div className="flex items-center gap-4 mt-2">
              <div className="flex items-center gap-2 text-sm">
                <Briefcase size={16} className="text-blue-400" />
                Adjudicantes
              </div>
              <div className="flex items-center gap-2 text-sm">
                <HandCoins size={16} className="text-emerald-400" />
                Adjudicatários
              </div>
            </div>
          </div>
        </div>

        {/* Search + filters */}
        <div className="glass-card rounded-2xl p-4 mb-8">
          <div className="flex flex-col md:flex-row gap-3">
            <div className="relative flex-1">
              <Search className="absolute left-4 top-1/2 -translate-y-1/2 text-muted-foreground" size={18} />
              <input
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Nome ou NIF da entidade..."
                className="w-full pl-11 pr-4 py-3 rounded-xl bg-background/60 border border-border focus:outline-none focus:ring-2 focus:ring-primary/60 text-foreground placeholder:text-muted-foreground"
              />
            </div>
            <select
              value={role}
              onChange={(e) => setRole(e.target.value as CompanySearchRequest["role"])}
              className="px-4 py-3 rounded-xl bg-background/60 border border-border focus:outline-none focus:ring-2 focus:ring-primary/60"
            >
              <option value="all">Todos os papéis</option>
              <option value="adjudicante">Adjudicante</option>
              <option value="adjudicatario">Adjudicatário</option>
            </select>
            <button
              onClick={() => setAdvancedOpen((v) => !v)}
              className="flex items-center gap-2 px-4 py-3 rounded-xl bg-background/60 border border-border hover:bg-white/5 transition text-sm"
            >
              <Filter size={18} />
              Filtros
              {activeFiltersCount > 0 && (
                <span className="bg-primary text-primary-foreground text-xs rounded-full px-2 py-0.5">{activeFiltersCount}</span>
              )}
              {advancedOpen ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
            </button>
          </div>

          {advancedOpen && (
            <div className="grid grid-cols-1 md:grid-cols-4 gap-3 pt-4 mt-4 border-t border-border/50">
              <div>
                <label className="block text-xs text-muted-foreground mb-1">Mín. contratos</label>
                <input
                  type="number"
                  min={1}
                  value={minContracts}
                  onChange={(e) => setMinContracts(e.target.value)}
                  className="w-full px-3 py-2 rounded-xl bg-background/60 border border-border focus:outline-none focus:ring-2 focus:ring-primary/60"
                />
              </div>
              <div>
                <label className="block text-xs text-muted-foreground mb-1">Valor mínimo (€)</label>
                <input
                  type="number"
                  min={0}
                  value={minValue}
                  onChange={(e) => setMinValue(e.target.value)}
                  className="w-full px-3 py-2 rounded-xl bg-background/60 border border-border focus:outline-none focus:ring-2 focus:ring-primary/60"
                />
              </div>
              <div>
                <label className="block text-xs text-muted-foreground mb-1">Valor máximo (€)</label>
                <input
                  type="number"
                  min={0}
                  value={maxValue}
                  onChange={(e) => setMaxValue(e.target.value)}
                  className="w-full px-3 py-2 rounded-xl bg-background/60 border border-border focus:outline-none focus:ring-2 focus:ring-primary/60"
                />
              </div>
              <div>
                <label className="block text-xs text-muted-foreground mb-1">Ano</label>
                <input
                  type="number"
                  value={year}
                  onChange={(e) => setYear(e.target.value)}
                  placeholder="Ex: 2024"
                  className="w-full px-3 py-2 rounded-xl bg-background/60 border border-border focus:outline-none focus:ring-2 focus:ring-primary/60"
                />
              </div>
              <div className="md:col-span-4 flex justify-end">
                <button
                  onClick={clearFilters}
                  className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground transition"
                >
                  <X size={14} />
                  Limpar filtros
                </button>
              </div>
            </div>
          )}
        </div>

        {error && !loading && (
          <div className="mb-6 p-4 rounded-2xl bg-rose-500/10 border border-rose-500/20 text-rose-300 flex items-center gap-3">
            <Frown size={22} />
            {error}
          </div>
        )}

        {/* Results grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {results.map((company, idx) => {
            const id = companyIdentifier(company);
            return (
              <button
                key={id}
                onClick={() => id && onSelectCompany(company.nif || id)}
                className="group text-left glass-card gradient-border rounded-2xl p-5 hover:bg-white/[0.04] hover:-translate-y-1 transition-all duration-300 fade-in"
                style={{ animationDelay: `${Math.min(idx * 40, 600)}ms` }}
              >
                <div className="flex items-start justify-between gap-3 mb-3">
                  <div className="min-w-0">
                    <h3 className="font-semibold text-lg leading-tight truncate-2-lines group-hover:text-teal-300 transition-colors">
                      {company.name}
                    </h3>
                    {company.nif && (
                      <p className="text-xs text-muted-foreground mt-1">NIF {company.nif}</p>
                    )}
                  </div>
                  <div className="shrink-0 text-right">
                    <p className="text-lg font-bold stat-value text-glow-amber">{formatPrice(company.total_value)}</p>
                    <p className="text-xs text-muted-foreground">{company.contracts_total} contratos</p>
                  </div>
                </div>
                <div className="flex flex-wrap gap-2 mt-auto">
                  {company.adjudicante && company.adjudicante.contracts_count > 0 && (
                    <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs bg-blue-500/10 text-blue-300 border border-blue-500/20">
                      <Briefcase size={12} />
                      Adjudicante {company.adjudicante.contracts_count}
                    </span>
                  )}
                  {company.adjudicatario && company.adjudicatario.contracts_count > 0 && (
                    <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs bg-emerald-500/10 text-emerald-300 border border-emerald-500/20">
                      <HandCoins size={12} />
                      Adjudicatário {company.adjudicatario.contracts_count}
                    </span>
                  )}
                </div>
              </button>
            );
          })}
        </div>

        {results.length === 0 && !loading && !error && (
          <div className="text-center py-20 text-muted-foreground fade-in">
            <div className="inline-flex p-5 rounded-3xl glass-card mb-5">
              <Building2 size={48} className="opacity-60" />
            </div>
            <p className="text-lg">Sem resultados.</p>
            <p className="text-sm mt-1">Ajusta os filtros ou a pesquisa.</p>
          </div>
        )}

        <div ref={loadMoreRef} className="py-8 flex justify-center">
          {loadingMore && <Loader2 size={28} className="animate-spin text-teal-400" />}
        </div>
      </div>
    </div>
  );
}
