import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  ArrowLeft,
  BarChart3,
  Briefcase,
  Building2,
  ChevronLeft,
  ChevronRight,
  Euro,
  FileText,
  Filter,
  Frown,
  HandCoins,
  Loader2,
  MapPin,
  RefreshCw,
  Search,
  Sparkles,
  Tag,
  TrendingUp,
  X,
} from "lucide-react";
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  PieChart as RePieChart,
  Pie,
  Cell,
} from "recharts";
import type { Formatter as RechartsFormatter } from "recharts/types/component/DefaultTooltipContent";
import {
  getContractAnalytics,
  getContractRegionalAnalytics,
  getContractYears,
  searchCompanies,
} from "../api";
import type {
  CompanySearchRequest,
  CompanySummary,
  ContractAnalyticsFilters,
  ContractAnalyticsResponse,
  ContractAnalyticsRow,
  ContractRegionalRow,
} from "../types";

interface CompanyDashboardPageProps {
  onSwitchView: () => void;
  onSwitchSearch?: () => void;
  onSelectCompany: (nif: string) => void;
}

const PAGE_SIZE = 10;
const CHART_COLORS = ["#10a37f", "#3b82f6", "#f59e0b", "#ef4444", "#8b5cf6", "#ec4899", "#06b6d4", "#6366f1"];

type RoleValue = NonNullable<CompanySearchRequest["role"]>;

interface Filters {
  q: string;
  year: number | "";
  region: string;
  role: RoleValue;
  minValue: string;
  maxValue: string;
  minContracts: string;
  cpvCode: string;
  startDate: string;
  endDate: string;
}

const EMPTY_FILTERS: Filters = {
  q: "",
  year: "",
  region: "",
  role: "all",
  minValue: "",
  maxValue: "",
  minContracts: "",
  cpvCode: "",
  startDate: "",
  endDate: "",
};

const ROLE_OPTIONS: { value: RoleValue; label: string }[] = [
  { value: "all", label: "Todos os papéis" },
  { value: "adjudicante", label: "Apenas adjudicantes" },
  { value: "adjudicatario", label: "Apenas adjudicatários" },
];

function toNumber(value: string): number | undefined {
  const trimmed = value.trim();
  if (!trimmed) return undefined;
  const n = Number(trimmed);
  return Number.isFinite(n) ? n : undefined;
}

function formatNumber(n?: number | null) {
  if (n === undefined || n === null || Number.isNaN(n)) return "—";
  return n.toLocaleString("pt-PT");
}

function formatPrice(n?: number | null, digits = 2) {
  if (n === undefined || n === null || Number.isNaN(n)) return "—";
  return n.toLocaleString("pt-PT", {
    style: "currency",
    currency: "EUR",
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function formatCompactPrice(n?: number | null) {
  if (n === undefined || n === null || Number.isNaN(n)) return "—";
  const abs = Math.abs(n);
  if (abs >= 1_000_000_000) return `${(n / 1_000_000_000).toLocaleString("pt-PT", { maximumFractionDigits: 2 })} mM€`;
  if (abs >= 1_000_000) return `${(n / 1_000_000).toLocaleString("pt-PT", { maximumFractionDigits: 1 })} M€`;
  if (abs >= 1_000) return `${(n / 1_000).toLocaleString("pt-PT", { maximumFractionDigits: 0 })} mil€`;
  return formatPrice(n, 0);
}

function maxCount(rows: ContractAnalyticsRow[]) {
  return Math.max(...rows.map((r) => r.count || 0), 1);
}

const countFormatter: RechartsFormatter = (value) => [formatNumber(Number(value)), "Contratos"];
const euroFormatter: RechartsFormatter = (value) => [formatPrice(Number(value), 0), "Valor"];

const tooltipStyle = {
  backgroundColor: "#16181d",
  borderColor: "#2e323b",
  color: "#e8e9ec",
} as const;

function MiniBar({ value, max, color = "bg-teal-400" }: { value: number; max: number; color?: string }) {
  const pct = Math.min(100, Math.round((value / max) * 100));
  return (
    <div className="w-full h-1.5 bg-white/10 rounded-full overflow-hidden">
      <div className={`h-full ${color} rounded-full`} style={{ width: `${pct}%` }} />
    </div>
  );
}

function StatCard({
  icon: Icon,
  label,
  value,
  sub,
  color,
  glow,
}: {
  icon: React.ElementType;
  label: string;
  value: string | number;
  sub?: string;
  color: string;
  glow: string;
}) {
  return (
    <div className={`glass-card gradient-border rounded-2xl p-5 ${glow}`}>
      <div className="flex items-center gap-2 text-sm text-muted-foreground mb-2">
        <Icon size={18} className={color} />
        {label}
      </div>
      <p className="text-2xl md:text-3xl font-bold stat-value truncate">{value}</p>
      {sub && <p className="text-xs text-muted-foreground mt-1 truncate">{sub}</p>}
    </div>
  );
}

function CardShell({
  icon: Icon,
  iconClass,
  iconBg,
  title,
  hint,
  action,
  children,
}: {
  icon: React.ElementType;
  iconClass: string;
  iconBg: string;
  title: string;
  hint?: string;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="glass-card gradient-border rounded-2xl p-5">
      <div className="flex items-start justify-between gap-3 mb-4">
        <div className="flex items-center gap-2 min-w-0">
          <div className={`p-2 rounded-xl ${iconBg} shrink-0`}>
            <Icon size={18} className={iconClass} />
          </div>
          <div className="min-w-0">
            <h2 className="text-base font-semibold truncate">{title}</h2>
            {hint && <p className="text-xs text-muted-foreground truncate">{hint}</p>}
          </div>
        </div>
        {action}
      </div>
      {children}
    </div>
  );
}

function RankBar({
  label,
  sub,
  value,
  display,
  max,
  color,
}: {
  label: string;
  sub?: string;
  value: number;
  display: string;
  max: number;
  color: string;
}) {
  return (
    <div>
      <div className="flex items-start justify-between gap-3 mb-1">
        <div className="min-w-0">
          <p className="text-sm font-medium truncate" title={label}>
            {label}
          </p>
          {sub && <p className="text-xs text-muted-foreground truncate">{sub}</p>}
        </div>
        <span className="text-sm stat-value whitespace-nowrap">{display}</span>
      </div>
      <MiniBar value={value} max={max} color={color} />
    </div>
  );
}

function CompanyRow({
  company,
  rank,
  max,
  color,
  onSelectCompany,
}: {
  company: CompanySummary;
  rank: number;
  max: number;
  color: string;
  onSelectCompany: (nif: string) => void;
}) {
  const id = company.nif || company.normalized_name || company.name;
  const roles: string[] = [];
  if (company.adjudicante) roles.push(`Adjudicante ${formatCompactPrice(company.adjudicante.total_value)}`);
  if (company.adjudicatario) roles.push(`Adjudicatário ${formatCompactPrice(company.adjudicatario.total_value)}`);

  return (
    <button
      onClick={() => onSelectCompany(company.nif || id)}
      disabled={!company.nif}
      title={company.nif ? `Ver detalhe de ${company.name}` : "Entidade sem NIF — sem página de detalhe"}
      className="w-full text-left p-3 rounded-xl bg-white/[0.03] border border-white/5 hover:bg-white/[0.06] transition group disabled:opacity-60 disabled:cursor-not-allowed"
    >
      <div className="flex items-center gap-3">
        <div className={`w-7 h-7 rounded-full flex items-center justify-center shrink-0 text-xs font-bold ${color}`}>
          {rank}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between gap-3 mb-1">
            <span className="text-sm font-medium truncate group-hover:text-teal-300 transition" title={company.name}>
              {company.name}
            </span>
            <span className="text-sm font-bold stat-value whitespace-nowrap">{formatPrice(company.total_value, 0)}</span>
          </div>
          <MiniBar value={company.total_value || 0} max={max} color="bg-amber-400" />
          <div className="flex items-center justify-between gap-2 mt-1">
            <p className="text-xs text-muted-foreground">
              {formatNumber(company.contracts_total)} contratos
              {company.nif ? ` · NIF ${company.nif}` : ""}
            </p>
            {roles.length > 0 && (
              <p className="text-xs text-muted-foreground truncate max-w-[45%]" title={roles.join(" · ")}>
                {roles.join(" · ")}
              </p>
            )}
          </div>
        </div>
      </div>
    </button>
  );
}

function FilterField({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="flex items-center gap-1 text-xs text-muted-foreground mb-1">
        {label}
        {hint && (
          <span className="px-1.5 py-px rounded-full bg-white/5 border border-white/10 text-[10px] uppercase tracking-wide">
            {hint}
          </span>
        )}
      </label>
      {children}
    </div>
  );
}

const inputClass =
  "w-full px-3 py-2 rounded-xl bg-background/60 border border-border text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/60";

export default function CompanyDashboardPage({
  onSwitchView,
  onSwitchSearch,
  onSelectCompany,
}: CompanyDashboardPageProps) {
  const [draft, setDraft] = useState<Filters>(EMPTY_FILTERS);
  const [applied, setApplied] = useState<Filters>(EMPTY_FILTERS);
  const [page, setPage] = useState(0);
  const [showFilters, setShowFilters] = useState(true);

  const [analytics, setAnalytics] = useState<ContractAnalyticsResponse | null>(null);
  const [loadingAnalytics, setLoadingAnalytics] = useState(true);
  const [analyticsError, setAnalyticsError] = useState<string | null>(null);

  const [companies, setCompanies] = useState<CompanySummary[]>([]);
  const [companiesTotal, setCompaniesTotal] = useState(0);
  const [uniqueAdjudicantes, setUniqueAdjudicantes] = useState(0);
  const [uniqueAdjudicatarios, setUniqueAdjudicatarios] = useState(0);
  const [loadingCompanies, setLoadingCompanies] = useState(true);
  const [companiesError, setCompaniesError] = useState<string | null>(null);

  const [years, setYears] = useState<number[]>([]);
  const [regionOptions, setRegionOptions] = useState<ContractRegionalRow[]>([]);
  const [regionStats, setRegionStats] = useState<ContractRegionalRow[]>([]);
  const [refreshTick, setRefreshTick] = useState(0);

  // Opções de ano e região (universo completo, para os selects).
  useEffect(() => {
    let cancelled = false;
    Promise.all([getContractYears(), getContractRegionalAnalytics()])
      .then(([yearsRes, regionsRes]) => {
        if (cancelled) return;
        setYears(yearsRes.available ?? []);
        setRegionOptions(regionsRes.regions ?? []);
      })
      .catch(() => {
        /* os selects ficam apenas com a opção "todos" */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Regiões respeitam apenas o filtro de ano (endpoint regional não aceita mais filtros).
  useEffect(() => {
    let cancelled = false;
    getContractRegionalAnalytics(applied.year === "" ? undefined : applied.year)
      .then((res) => {
        if (!cancelled) setRegionStats(res.regions ?? []);
      })
      .catch(() => {
        if (!cancelled) setRegionStats([]);
      });
    return () => {
      cancelled = true;
    };
  }, [applied.year, refreshTick]);

  const analyticsFilters = useMemo<ContractAnalyticsFilters>(() => {
    const f: ContractAnalyticsFilters = { top_entities: 10, top_cpv: 10 };
    if (applied.q.trim()) f.q = applied.q.trim();
    if (applied.year !== "") f.year = applied.year;
    if (applied.region) f.region = applied.region;
    if (applied.cpvCode.trim()) f.cpv_code = applied.cpvCode.trim();
    if (applied.startDate) f.start_date = applied.startDate;
    if (applied.endDate) f.end_date = applied.endDate;
    const min = toNumber(applied.minValue);
    const max = toNumber(applied.maxValue);
    if (min !== undefined) f.min_price = min;
    if (max !== undefined) f.max_price = max;
    return f;
  }, [applied]);

  const companyRequest = useMemo<CompanySearchRequest>(() => {
    const r: CompanySearchRequest = {
      role: applied.role,
      min_contracts: 1,
      size: PAGE_SIZE,
      from: page * PAGE_SIZE,
    };
    if (applied.q.trim()) r.q = applied.q.trim();
    if (applied.year !== "") r.year = applied.year;
    if (applied.region) r.region = applied.region;
    const min = toNumber(applied.minValue);
    const max = toNumber(applied.maxValue);
    const minContracts = toNumber(applied.minContracts);
    if (min !== undefined) r.min_value = min;
    if (max !== undefined) r.max_value = max;
    if (minContracts !== undefined) r.min_contracts = minContracts;
    return r;
  }, [applied, page]);

  const analyticsKey = JSON.stringify(analyticsFilters);
  const companyKey = JSON.stringify(companyRequest);

  useEffect(() => {
    let cancelled = false;
    setLoadingAnalytics(true);
    setAnalyticsError(null);
    getContractAnalytics(analyticsFilters)
      .then((res) => {
        if (cancelled) return;
        if (res.error) throw new Error(res.error);
        setAnalytics(res);
      })
      .catch((err) => {
        if (cancelled) return;
        setAnalyticsError(err instanceof Error ? err.message : "Erro ao carregar métricas dos contratos");
      })
      .finally(() => {
        if (!cancelled) setLoadingAnalytics(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [analyticsKey, refreshTick]);

  useEffect(() => {
    let cancelled = false;
    setLoadingCompanies(true);
    setCompaniesError(null);
    searchCompanies(companyRequest)
      .then((res) => {
        if (cancelled) return;
        if (res.error) throw new Error(res.error);
        setCompanies(res.items ?? []);
        setCompaniesTotal(res.total ?? 0);
        setUniqueAdjudicantes(res.unique_adjudicantes ?? 0);
        setUniqueAdjudicatarios(res.unique_adjudicatarios ?? 0);
      })
      .catch((err) => {
        if (cancelled) return;
        setCompaniesError(err instanceof Error ? err.message : "Erro ao carregar entidades");
      })
      .finally(() => {
        if (!cancelled) setLoadingCompanies(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyKey, refreshTick]);

  const byYear = useMemo(
    () => [...(analytics?.by_year ?? [])].sort((a, b) => a.key.localeCompare(b.key)),
    [analytics],
  );
  const topCpv = analytics?.top_cpv ?? [];
  const procedureTypes = analytics?.procedure_types ?? [];
  const contractTypes = analytics?.contract_types ?? [];
  const valueDistribution = analytics?.value_distribution ?? [];

  const maxCpvCount = maxCount(topCpv);
  const maxContractTypeCount = maxCount(contractTypes);
  const totalForPies = Math.max(
    procedureTypes.reduce((acc, r) => acc + (r.count || 0), 0),
    1,
  );

  const procedureData = useMemo(() => {
    const sorted = [...procedureTypes].sort((a, b) => (b.count || 0) - (a.count || 0));
    const head = sorted.slice(0, 6);
    const restCount = sorted.slice(6).reduce((acc, r) => acc + (r.count || 0), 0);
    const rows = restCount > 0 ? [...head, { key: "Outros", count: restCount }] : head;
    return rows.map((r, i) => ({ ...r, fill: CHART_COLORS[i % CHART_COLORS.length] }));
  }, [procedureTypes]);

  const yearsCovered = byYear.length > 0 ? `${byYear[0].key} — ${byYear[byYear.length - 1].key}` : "";
  const maxCompanyValue = useMemo(
    () => Math.max(...companies.map((c) => c.total_value || 0), 1),
    [companies],
  );
  const maxRegionCount = useMemo(
    () => Math.max(...regionStats.map((r) => r.count || 0), 1),
    [regionStats],
  );
  const totalPages = Math.max(1, Math.ceil(companiesTotal / PAGE_SIZE));
  const activeFilters = useMemo(
    () => Object.entries(applied).filter(([, v]) => v !== "" && v !== "all"),
    [applied],
  );

  const applyDraft = () => {
    setApplied(draft);
    setPage(0);
  };

  const resetFilters = () => {
    setDraft(EMPTY_FILTERS);
    setApplied(EMPTY_FILTERS);
    setPage(0);
  };

  const removeFilter = (key: keyof Filters) => {
    const next = { ...applied, [key]: EMPTY_FILTERS[key] };
    setDraft(next);
    setApplied(next);
    setPage(0);
  };

  const filterChipValue = (key: keyof Filters, raw: string | number): string => {
    if (key === "minValue" || key === "maxValue") return formatPrice(Number(raw), 0);
    if (key === "role") return ROLE_OPTIONS.find((o) => o.value === raw)?.label ?? String(raw);
    if (key === "region") return String(raw).split(" - ")[0];
    if (key === "minContracts") return `${raw}+ contratos`;
    return String(raw);
  };

  return (
    <div className="min-h-screen w-full bg-background text-foreground orbit-bg">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 py-8">
        <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4 mb-6">
          <button
            onClick={onSwitchView}
            className="self-start flex items-center gap-2 px-3 py-1.5 rounded-full glass-card text-sm text-muted-foreground hover:text-foreground transition"
          >
            <ArrowLeft size={16} />
            Voltar
          </button>

          <div className="flex flex-wrap items-center gap-2">
            <div className="relative flex-1 min-w-[200px] sm:min-w-[260px]">
              <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
              <input
                type="search"
                value={draft.q}
                onChange={(e) => setDraft((d) => ({ ...d, q: e.target.value }))}
                onKeyDown={(e) => {
                  if (e.key === "Enter") applyDraft();
                }}
                placeholder="Pesquisar entidade, contrato ou CPV…"
                aria-label="Pesquisar entidade, contrato ou CPV"
                className="w-full pl-9 pr-3 py-2 rounded-xl glass-card text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/60"
              />
            </div>

            <select
              value={draft.year}
              onChange={(e) => setDraft((d) => ({ ...d, year: e.target.value === "" ? "" : Number(e.target.value) }))}
              aria-label="Ano"
              className="px-3 py-2 rounded-xl glass-card text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-primary/60"
            >
              <option value="">Todos os anos</option>
              {years.map((y) => (
                <option key={y} value={y}>
                  {y}
                </option>
              ))}
            </select>

            <select
              value={draft.region}
              onChange={(e) => setDraft((d) => ({ ...d, region: e.target.value }))}
              aria-label="Região"
              className="px-3 py-2 rounded-xl glass-card text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-primary/60 max-w-[240px]"
            >
              <option value="">Todas as regiões</option>
              {regionOptions.map((r) => (
                <option key={r.key} value={r.key}>
                  {r.key.split(" - ")[0]}
                </option>
              ))}
            </select>

            <button
              onClick={applyDraft}
              className="px-3 py-2 rounded-xl glass-card bg-primary/10 text-primary border-primary/20 hover:bg-primary/15 transition flex items-center gap-2 text-sm"
            >
              <Search size={16} />
              Aplicar
            </button>

            <button
              onClick={() => setShowFilters((s) => !s)}
              aria-expanded={showFilters}
              className={`px-3 py-2 rounded-xl transition flex items-center gap-2 text-sm ${showFilters ? "glass-card bg-primary/10 text-primary" : "glass-card hover:bg-white/5"}`}
            >
              <Filter size={16} />
              Filtros
              {activeFilters.length > 0 && (
                <span className="px-1.5 rounded-full bg-primary/20 text-[11px]">{activeFilters.length}</span>
              )}
            </button>

            <button
              onClick={() => setRefreshTick((t) => t + 1)}
              disabled={loadingAnalytics || loadingCompanies}
              aria-label="Atualizar dados"
              title="Atualizar dados"
              className="px-3 py-2 rounded-xl glass-card hover:bg-white/5 transition disabled:opacity-50 flex items-center gap-2 text-sm"
            >
              <RefreshCw size={16} className={loadingAnalytics || loadingCompanies ? "animate-spin" : ""} />
            </button>

            {onSwitchSearch && (
              <button
                onClick={onSwitchSearch}
                className="px-3 py-2 rounded-xl glass-card hover:bg-white/5 transition flex items-center gap-2 text-sm"
              >
                <Building2 size={16} className="text-teal-400" />
                <span className="hidden sm:inline">Diretório</span>
              </button>
            )}
          </div>
        </div>

        <div className="mb-6">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full glass-card text-xs text-amber-300 mb-3">
            <Sparkles size={14} />
            Métricas calculadas sobre todos os contratos indexados
          </div>
          <h1 className="text-3xl md:text-4xl font-bold flex items-center gap-3">
            <span className="p-2 rounded-2xl bg-gradient-to-br from-amber-500/20 to-rose-500/15 border border-white/10">
              <BarChart3 size={32} className="text-amber-400" />
            </span>
            Dashboard de Empresas
          </h1>
          <p className="text-muted-foreground mt-2">
            {formatNumber(analytics?.total_contracts)} contratos
            {yearsCovered && ` · ${yearsCovered}`}
            {analytics?.total_value ? ` · ${formatPrice(analytics.total_value, 0)}` : ""}
          </p>
        </div>

        {(analyticsError || companiesError) && (
          <div className="mb-6 p-4 rounded-2xl bg-rose-500/10 border border-rose-500/20 text-rose-300 flex items-center gap-2">
            <Frown size={20} />
            {analyticsError || companiesError}
          </div>
        )}

        {showFilters && (
          <div className="mb-6 glass-card rounded-2xl p-5 fade-in">
            <div className="flex flex-wrap items-center justify-between gap-2 mb-4">
              <h2 className="font-semibold flex items-center gap-2">
                <Filter size={18} /> Filtros
              </h2>
              <p className="text-xs text-muted-foreground">
                <span className="px-1.5 py-px rounded-full bg-white/5 border border-white/10 uppercase tracking-wide mr-1">contratos</span>
                aplica-se às métricas ·{" "}
                <span className="px-1.5 py-px rounded-full bg-white/5 border border-white/10 uppercase tracking-wide mr-1">entidades</span>
                aplica-se à lista de empresas
              </p>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
              <FilterField label="Texto livre" hint="ambos">
                <input
                  type="text"
                  value={draft.q}
                  onChange={(e) => setDraft((d) => ({ ...d, q: e.target.value }))}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") applyDraft();
                  }}
                  placeholder="Objeto, entidade, CPV…"
                  className={inputClass}
                />
              </FilterField>
              <FilterField label="Ano" hint="ambos">
                <select
                  value={draft.year}
                  onChange={(e) => setDraft((d) => ({ ...d, year: e.target.value === "" ? "" : Number(e.target.value) }))}
                  className={inputClass}
                >
                  <option value="">Todos os anos</option>
                  {years.map((y) => (
                    <option key={y} value={y}>
                      {y}
                    </option>
                  ))}
                </select>
              </FilterField>
              <FilterField label="Região NUTS" hint="ambos">
                <select
                  value={draft.region}
                  onChange={(e) => setDraft((d) => ({ ...d, region: e.target.value }))}
                  className={inputClass}
                >
                  <option value="">Todas as regiões</option>
                  {regionOptions.map((r) => (
                    <option key={r.key} value={r.key}>
                      {r.key}
                    </option>
                  ))}
                </select>
              </FilterField>
              <FilterField label="Papel da entidade" hint="entidades">
                <select
                  value={draft.role}
                  onChange={(e) => setDraft((d) => ({ ...d, role: e.target.value as RoleValue }))}
                  className={inputClass}
                >
                  {ROLE_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </select>
              </FilterField>
              <FilterField label="Valor mínimo (€)" hint="ambos">
                <input
                  type="number"
                  min={0}
                  value={draft.minValue}
                  onChange={(e) => setDraft((d) => ({ ...d, minValue: e.target.value }))}
                  placeholder="ex.: 100000"
                  className={inputClass}
                />
              </FilterField>
              <FilterField label="Valor máximo (€)" hint="ambos">
                <input
                  type="number"
                  min={0}
                  value={draft.maxValue}
                  onChange={(e) => setDraft((d) => ({ ...d, maxValue: e.target.value }))}
                  placeholder="ex.: 5000000"
                  className={inputClass}
                />
              </FilterField>
              <FilterField label="Contratos mínimos" hint="entidades">
                <input
                  type="number"
                  min={1}
                  value={draft.minContracts}
                  onChange={(e) => setDraft((d) => ({ ...d, minContracts: e.target.value }))}
                  placeholder="ex.: 10"
                  className={inputClass}
                />
              </FilterField>
              <FilterField label="Código CPV" hint="contratos">
                <input
                  type="text"
                  value={draft.cpvCode}
                  onChange={(e) => setDraft((d) => ({ ...d, cpvCode: e.target.value }))}
                  placeholder="ex.: 45233"
                  className={inputClass}
                />
              </FilterField>
              <FilterField label="Data de publicação — desde" hint="contratos">
                <input
                  type="date"
                  value={draft.startDate}
                  onChange={(e) => setDraft((d) => ({ ...d, startDate: e.target.value }))}
                  className={inputClass}
                />
              </FilterField>
              <FilterField label="Data de publicação — até" hint="contratos">
                <input
                  type="date"
                  value={draft.endDate}
                  onChange={(e) => setDraft((d) => ({ ...d, endDate: e.target.value }))}
                  className={inputClass}
                />
              </FilterField>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <button
                onClick={applyDraft}
                className="px-4 py-2 rounded-xl glass-card bg-primary/10 text-primary border-primary/20 hover:bg-primary/15 transition text-sm"
              >
                Aplicar filtros
              </button>
              <button
                onClick={resetFilters}
                disabled={activeFilters.length === 0}
                className="px-4 py-2 rounded-xl glass-card hover:bg-white/5 transition text-sm disabled:opacity-50"
              >
                Repor filtros
              </button>
            </div>
          </div>
        )}

        {activeFilters.length > 0 && (
          <div className="mb-6 glass-card rounded-2xl px-4 py-3 flex flex-wrap items-center gap-2 text-sm">
            <span className="text-muted-foreground">Filtros ativos:</span>
            {activeFilters.map(([key, value]) => (
              <button
                key={key}
                onClick={() => removeFilter(key as keyof Filters)}
                title="Remover filtro"
                className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full bg-white/5 border border-white/10 text-xs hover:bg-white/10 transition"
              >
                {filterChipValue(key as keyof Filters, value as string | number)}
                <X size={12} />
              </button>
            ))}
            <button onClick={resetFilters} className="ml-auto text-xs text-primary hover:underline">
              Limpar tudo
            </button>
          </div>
        )}

        {/* KPIs globais */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4 mb-6 fade-in">
          <StatCard
            icon={FileText}
            label="Contratos indexados"
            value={loadingAnalytics && !analytics ? "…" : formatNumber(analytics?.total_contracts)}
            sub={activeFilters.length > 0 ? "com os filtros aplicados" : "todo o universo indexado"}
            color="text-teal-400"
            glow="glow-teal"
          />
          <StatCard
            icon={Euro}
            label="Valor total"
            value={loadingAnalytics && !analytics ? "…" : formatPrice(analytics?.total_value, 0)}
            color="text-amber-400"
            glow="glow-amber"
          />
          <StatCard
            icon={Activity}
            label="Valor médio"
            value={loadingAnalytics && !analytics ? "…" : formatPrice(analytics?.avg_value, 0)}
            sub={`Máximo: ${formatPrice(analytics?.max_value, 0)}`}
            color="text-rose-400"
            glow="glow-rose"
          />
          <StatCard
            icon={Building2}
            label="Entidades adjudicantes"
            value={loadingCompanies && uniqueAdjudicantes === 0 ? "…" : formatNumber(uniqueAdjudicantes)}
            sub="NIF distintos nos contratos filtrados"
            color="text-blue-400"
            glow="glow-blue"
          />
          <StatCard
            icon={Briefcase}
            label="Entidades adjudicatárias"
            value={loadingCompanies && uniqueAdjudicatarios === 0 ? "…" : formatNumber(uniqueAdjudicatarios)}
            sub="NIF distintos nos contratos filtrados"
            color="text-violet-400"
            glow="glow-blue"
          />
        </div>

        {loadingAnalytics && !analytics ? (
          <div className="flex justify-center py-16">
            <Loader2 size={44} className="animate-spin text-teal-400" />
          </div>
        ) : (
          <>
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
              <CardShell
                icon={BarChart3}
                iconClass="text-teal-400"
                iconBg="bg-teal-500/15 border border-teal-400/20"
                title="Contratos por ano"
                hint={`${formatNumber(analytics?.total_contracts)} contratos`}
              >
                <div className="h-72">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={byYear}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#2e323b" />
                      <XAxis dataKey="key" stroke="#9aa0aa" />
                      <YAxis stroke="#9aa0aa" tickFormatter={(v) => formatNumber(Number(v))} />
                      <Tooltip contentStyle={tooltipStyle} formatter={countFormatter} />
                      <Bar dataKey="count" fill="#10a37f" radius={[4, 4, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </CardShell>

              <CardShell
                icon={Euro}
                iconClass="text-amber-400"
                iconBg="bg-amber-500/15 border border-amber-400/20"
                title="Valor por ano"
                hint={`${formatPrice(analytics?.total_value, 0)} no total`}
              >
                <div className="h-72">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={byYear}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#2e323b" />
                      <XAxis dataKey="key" stroke="#9aa0aa" />
                      <YAxis stroke="#9aa0aa" tickFormatter={(v) => formatCompactPrice(Number(v))} />
                      <Tooltip contentStyle={tooltipStyle} formatter={euroFormatter} />
                      <Bar dataKey="total_value" fill="#f59e0b" radius={[4, 4, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </CardShell>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
              <CardShell
                icon={TrendingUp}
                iconClass="text-blue-400"
                iconBg="bg-blue-500/15 border border-blue-400/20"
                title="Entidades com mais contratos"
                hint={`${formatNumber(companiesTotal)} entidades · página ${page + 1} de ${totalPages}`}
                action={
                  <div className="flex items-center gap-1">
                    <button
                      onClick={() => setPage((p) => Math.max(0, p - 1))}
                      disabled={page === 0 || loadingCompanies}
                      aria-label="Página anterior"
                      title="Página anterior"
                      className="p-1.5 rounded-lg glass-card hover:bg-white/5 transition disabled:opacity-40"
                    >
                      <ChevronLeft size={16} />
                    </button>
                    <button
                      onClick={() => setPage((p) => (p + 1 < totalPages ? p + 1 : p))}
                      disabled={page + 1 >= totalPages || loadingCompanies}
                      aria-label="Página seguinte"
                      title="Página seguinte"
                      className="p-1.5 rounded-lg glass-card hover:bg-white/5 transition disabled:opacity-40"
                    >
                      <ChevronRight size={16} />
                    </button>
                  </div>
                }
              >
                {loadingCompanies ? (
                  <div className="flex justify-center py-10">
                    <Loader2 size={28} className="animate-spin text-teal-400" />
                  </div>
                ) : companies.length === 0 ? (
                  <p className="text-muted-foreground py-6">
                    Nenhuma entidade corresponde aos filtros aplicados.
                  </p>
                ) : (
                  <div className="space-y-3">
                    {companies.map((c, i) => (
                      <CompanyRow
                        key={c.nif || c.name}
                        company={c}
                        rank={page * PAGE_SIZE + i + 1}
                        max={maxCompanyValue}
                        color="bg-amber-500/15 text-amber-300"
                        onSelectCompany={onSelectCompany}
                      />
                    ))}
                  </div>
                )}
              </CardShell>

              <CardShell
                icon={Tag}
                iconClass="text-emerald-400"
                iconBg="bg-emerald-500/15 border border-emerald-400/20"
                title="Top categorias CPV"
                hint="por número de contratos"
              >
                {topCpv.length === 0 ? (
                  <p className="text-muted-foreground">Sem dados para os filtros aplicados.</p>
                ) : (
                  <div className="space-y-4">
                    {topCpv.map((row) => (
                      <RankBar
                        key={row.key}
                        label={row.key}
                        sub={row.description || undefined}
                        value={row.count}
                        display={`${formatNumber(row.count)} · ${formatCompactPrice(row.total_value)}`}
                        max={maxCpvCount}
                        color="bg-emerald-400"
                      />
                    ))}
                  </div>
                )}
              </CardShell>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-6">
              <CardShell
                icon={Briefcase}
                iconClass="text-violet-400"
                iconBg="bg-violet-500/15 border border-violet-400/20"
                title="Tipo de procedimento"
                hint={`${formatNumber(totalForPies)} contratos`}
              >
                {procedureData.length === 0 ? (
                  <p className="text-muted-foreground">Sem dados para os filtros aplicados.</p>
                ) : (
                  <>
                    <div className="h-56">
                      <ResponsiveContainer width="100%" height="100%">
                        <RePieChart>
                          <Pie data={procedureData} dataKey="count" nameKey="key" innerRadius={45} outerRadius={80}>
                            {procedureData.map((entry) => (
                              <Cell key={entry.key} fill={entry.fill} />
                            ))}
                          </Pie>
                          <Tooltip contentStyle={tooltipStyle} formatter={countFormatter} />
                        </RePieChart>
                      </ResponsiveContainer>
                    </div>
                    <ul className="mt-3 space-y-1.5">
                      {procedureData.map((row) => (
                        <li key={row.key} className="flex items-center gap-2 text-xs">
                          <span className="w-2.5 h-2.5 rounded-sm shrink-0" style={{ backgroundColor: row.fill }} />
                          <span className="truncate flex-1" title={row.key}>
                            {row.key}
                          </span>
                          <span className="text-muted-foreground stat-value">{formatNumber(row.count)}</span>
                        </li>
                      ))}
                    </ul>
                  </>
                )}
              </CardShell>

              <CardShell
                icon={FileText}
                iconClass="text-teal-400"
                iconBg="bg-teal-500/15 border border-teal-400/20"
                title="Tipo de contrato"
                hint="por número de contratos"
              >
                {contractTypes.length === 0 ? (
                  <p className="text-muted-foreground">Sem dados para os filtros aplicados.</p>
                ) : (
                  <div className="space-y-4">
                    {contractTypes.slice(0, 8).map((row) => (
                      <RankBar
                        key={row.key}
                        label={row.key || "N/A"}
                        value={row.count}
                        display={formatNumber(row.count)}
                        max={maxContractTypeCount}
                        color="bg-teal-400"
                      />
                    ))}
                  </div>
                )}
              </CardShell>

              <CardShell
                icon={HandCoins}
                iconClass="text-rose-400"
                iconBg="bg-rose-500/15 border border-rose-400/20"
                title="Distribuição por valor"
                hint="contratos por escalão (50 mil €)"
              >
                {valueDistribution.length === 0 ? (
                  <p className="text-muted-foreground">Sem dados para os filtros aplicados.</p>
                ) : (
                  <div className="h-72">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart
                        data={valueDistribution.map((r) => ({
                          ...r,
                          short: `${formatCompactPrice(Number(r.key.split(" - ")[0]))}`,
                        }))}
                      >
                        <CartesianGrid strokeDasharray="3 3" stroke="#2e323b" />
                        <XAxis dataKey="short" stroke="#9aa0aa" />
                        <YAxis stroke="#9aa0aa" tickFormatter={(v) => formatNumber(Number(v))} />
                        <Tooltip contentStyle={tooltipStyle} formatter={countFormatter} />
                        <Bar dataKey="count" fill="#f43f5e" radius={[4, 4, 0, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                )}
              </CardShell>
            </div>

            <div className="glass-card gradient-border rounded-2xl p-5 mb-6">
              <div className="flex items-center justify-between gap-2 mb-3">
                <h2 className="font-semibold flex items-center gap-2">
                  <MapPin size={18} className="text-amber-400" /> Regiões (NUTS)
                </h2>
                <p className="text-xs text-muted-foreground">
                  {applied.year === "" ? "Todos os anos" : `Ano ${applied.year}`} · sem filtros de texto/valor
                </p>
              </div>
              {regionStats.length === 0 ? (
                <p className="text-muted-foreground">Sem dados regionais para o ano selecionado.</p>
              ) : (
                <div className="space-y-3">
                  {regionStats.slice(0, 8).map((row) => (
                    <RankBar
                      key={row.key}
                      label={row.key}
                      value={row.count}
                      display={`${formatNumber(row.count)} · ${formatCompactPrice(row.total_value)}`}
                      max={maxRegionCount}
                      color="bg-amber-400"
                    />
                  ))}
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
