/**
 * Dashboard de entidades por papel — adjudicantes, adjudicatários e empresas.
 *
 * O mesmo ecrã serve os três papéis (`role`): muda apenas o título, o recorte
 * das agregações (feito no backend, em `/companies/role-summary`) e as métricas
 * em destaque. Cada entidade pode ser aberta na ficha, adicionada à comparação
 * ou vista no diretório.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  ArrowLeft,
  BarChart3,
  Briefcase,
  Building2,
  Euro,
  FileText,
  Filter,
  Frown,
  GitCompare,
  HandCoins,
  Landmark,
  Layers,
  Loader2,
  MapPin,
  Percent,
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
import { getEntityRoleSummary, getContractYears, getContractRegionalAnalytics } from "../api";
import type {
  ContractAnalyticsRow,
  ContractRegionalRow,
  CompanySummary,
  EntityRole,
  EntityRoleSummaryRequest,
  EntityRoleSummaryResponse,
} from "../types";
import { MAX_COMPARE, useCompare } from "../compare";

interface EntityDashboardPageProps {
  role: EntityRole;
  onSwitchView?: () => void;
  onSwitchRole?: (role: EntityRole) => void;
  onSelectEntity: (nif: string) => void;
  onOpenCompare?: () => void;
}

const CHART_COLORS = ["#10a37f", "#3b82f6", "#f59e0b", "#ef4444", "#8b5cf6", "#ec4899", "#06b6d4", "#6366f1"];

const ROLE_COPY: Record<EntityRole, { label: string; plural: string; title: string; hint: string; icon: React.ElementType; accent: string }> = {
  all: {
    label: "Empresas",
    plural: "empresas",
    title: "Dashboard de Empresas",
    hint: "Entidades que contratam e são contratadas (papéis somados)",
    icon: Building2,
    accent: "from-emerald-500/20 to-teal-500/15",
  },
  adjudicante: {
    label: "Adjudicantes",
    plural: "adjudicantes",
    title: "Dashboard de Adjudicantes",
    hint: "Entidades que adjudicam: volume, valor e concentração da procura",
    icon: Landmark,
    accent: "from-blue-500/20 to-indigo-500/15",
  },
  adjudicatario: {
    label: "Adjudicatários",
    plural: "adjudicatários",
    title: "Dashboard de Adjudicatários",
    hint: "Entidades fornecedoras: quem ganha os contratos e quanto",
    icon: Briefcase,
    accent: "from-amber-500/20 to-rose-500/15",
  },
};

interface Filters {
  q: string;
  year: number | "";
  region: string;
  minValue: string;
  maxValue: string;
  minContracts: string;
}

const EMPTY_FILTERS: Filters = {
  q: "",
  year: "",
  region: "",
  minValue: "",
  maxValue: "",
  minContracts: "",
};

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

function formatPercent(share?: number | null) {
  if (share === undefined || share === null || Number.isNaN(share)) return "—";
  return `${(share * 100).toLocaleString("pt-PT", { maximumFractionDigits: 1 })}%`;
}

const countFormatter: RechartsFormatter = (value) => [formatNumber(Number(value)), "Contratos"];
const euroFormatter: RechartsFormatter = (value) => [formatPrice(Number(value), 0), "Valor"];

const tooltipStyle = {
  backgroundColor: "#16181d",
  borderColor: "#2e323b",
  color: "#e8e9ec",
} as const;

const inputClass =
  "w-full px-3 py-2 rounded-xl bg-background/60 border border-border text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/60";

function MiniBar({ value, max, color = "bg-teal-400" }: { value: number; max: number; color?: string }) {
  const pct = Math.min(100, Math.round((value / Math.max(max, 1)) * 100));
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

/** Linha do ranking: abre a ficha, mostra papéis e alterna a comparação. */
function EntityRow({
  entity,
  rank,
  max,
  role,
  onSelectEntity,
}: {
  entity: CompanySummary;
  rank: number;
  max: number;
  role: EntityRole;
  onSelectEntity: (nif: string) => void;
}) {
  const { has, toggle, full } = useCompare();
  const id = entity.nif || entity.normalized_name || entity.name;
  const item = { kind: "entity" as const, id, name: entity.name, subtitle: entity.nif ? `NIF ${entity.nif}` : undefined };
  const selected = has(item);

  const roleBits: string[] = [];
  if (entity.adjudicante) roleBits.push(`Adjudicante ${formatCompactPrice(entity.adjudicante.total_value)}`);
  if (entity.adjudicatario) roleBits.push(`Adjudicatário ${formatCompactPrice(entity.adjudicatario.total_value)}`);

  const primaryValue =
    role === "adjudicante"
      ? entity.adjudicante?.total_value ?? 0
      : role === "adjudicatario"
        ? entity.adjudicatario?.total_value ?? 0
        : entity.total_value;

  return (
    <div className="flex items-center gap-2 p-3 rounded-xl bg-white/[0.03] border border-white/5 hover:bg-white/[0.06] transition">
      <button
        type="button"
        onClick={() => entity.nif && onSelectEntity(entity.nif)}
        disabled={!entity.nif}
        title={entity.nif ? `Ver ficha de ${entity.name}` : "Entidade sem NIF — sem ficha"}
        className="flex flex-1 min-w-0 items-center gap-3 text-left disabled:opacity-60 disabled:cursor-not-allowed"
      >
        <span className="w-7 h-7 rounded-full flex items-center justify-center shrink-0 text-xs font-bold bg-amber-500/15 text-amber-300">
          {rank}
        </span>
        <span className="flex-1 min-w-0">
          <span className="flex items-center justify-between gap-3 mb-1">
            <span className="text-sm font-medium truncate">{entity.name}</span>
            <span className="text-sm font-bold stat-value whitespace-nowrap">{formatPrice(primaryValue, 0)}</span>
          </span>
          <MiniBar value={primaryValue} max={max} color="bg-amber-400" />
          <span className="flex items-center justify-between gap-2 mt-1">
            <span className="text-xs text-muted-foreground truncate">
              {formatNumber(entity.contracts_total)} contratos
              {entity.nif ? ` · NIF ${entity.nif}` : ""}
            </span>
            {roleBits.length > 0 && (
              <span className="text-xs text-muted-foreground truncate max-w-[50%]" title={roleBits.join(" · ")}>
                {roleBits.join(" · ")}
              </span>
            )}
          </span>
        </span>
      </button>
      <button
        type="button"
        onClick={() => toggle(item)}
        disabled={!selected && full}
        aria-pressed={selected}
        title={selected ? "Remover da comparação" : `Adicionar ${entity.name} à comparação`}
        className={`shrink-0 rounded-lg border px-2 py-1.5 text-[11px] transition disabled:opacity-40 ${
          selected
            ? "border-teal-400/40 bg-teal-400/15 text-teal-200"
            : "border-white/10 bg-white/[0.05] hover:bg-white/[0.1]"
        }`}
      >
        <GitCompare size={13} />
      </button>
    </div>
  );
}

export default function EntityDashboardPage({
  role,
  onSwitchView,
  onSwitchRole,
  onSelectEntity,
  onOpenCompare,
}: EntityDashboardPageProps) {
  const copy = ROLE_COPY[role];
  const RoleIcon = copy.icon;

  const [draft, setDraft] = useState<Filters>(EMPTY_FILTERS);
  const [applied, setApplied] = useState<Filters>(EMPTY_FILTERS);
  const [showFilters, setShowFilters] = useState(false);
  const [refreshTick, setRefreshTick] = useState(0);

  const [summary, setSummary] = useState<EntityRoleSummaryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const { items: compareItems } = useCompare();

  const [years, setYears] = useState<number[]>([]);
  const [regionOptions, setRegionOptions] = useState<ContractRegionalRow[]>([]);

  // Opções dos selects (universo completo, independente dos filtros ativos).
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

  const request = useMemo<EntityRoleSummaryRequest>(() => {
    const r: EntityRoleSummaryRequest = { role, top_n: 25, min_contracts: 1 };
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
  }, [applied, role]);

  const requestKey = JSON.stringify(request);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getEntityRoleSummary(request)
      .then((res) => {
        if (cancelled) return;
        if (res.error) {
          setError(res.error);
          setSummary(null);
        } else {
          setSummary(res);
        }
      })
      .catch((caught) => {
        if (!cancelled) setError(caught instanceof Error ? caught.message : "Erro ao carregar o dashboard.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requestKey, refreshTick]);

  const applyDraft = useCallback(() => setApplied({ ...draft }), [draft]);
  const resetFilters = useCallback(() => {
    setDraft(EMPTY_FILTERS);
    setApplied(EMPTY_FILTERS);
  }, []);

  const activeFilters = useMemo(
    () =>
      (Object.entries(applied) as [keyof Filters, string | number][]).filter(
        ([, value]) => value !== "" && value !== undefined && value !== null,
      ),
    [applied],
  );

  const removeFilter = (key: keyof Filters) => {
    setDraft((d) => ({ ...d, [key]: EMPTY_FILTERS[key] }));
    setApplied((a) => ({ ...a, [key]: EMPTY_FILTERS[key] }));
  };

  const byYear = useMemo(
    () => [...(summary?.by_year ?? [])].sort((a, b) => a.key.localeCompare(b.key)),
    [summary],
  );
  const topCpv = summary?.by_cpv ?? [];
  const topRegions = summary?.by_region ?? [];
  const topProcedures = summary?.by_procedure_type ?? [];
  const topContractTypes = summary?.by_contract_type ?? [];
  const topCounterparties = summary?.counterparties ?? [];
  const topEntities = summary?.top_entities ?? [];

  const maxEntityValue = useMemo(
    () =>
      Math.max(
        1,
        ...topEntities.map((entity) =>
          role === "adjudicante"
            ? entity.adjudicante?.total_value ?? 0
            : role === "adjudicatario"
              ? entity.adjudicatario?.total_value ?? 0
              : entity.total_value,
        ),
      ),
    [topEntities, role],
  );
  const maxCpvCount = useMemo(() => Math.max(1, ...topCpv.map((r) => r.count || 0)), [topCpv]);
  const maxRegionValue = useMemo(() => Math.max(1, ...topRegions.map((r) => r.total_value || 0)), [topRegions]);
  const maxCounterpartyValue = useMemo(
    () => Math.max(1, ...topCounterparties.map((r) => r.total_value || 0)),
    [topCounterparties],
  );

  const valueRangeRows: ContractAnalyticsRow[] = summary?.by_value_range ?? [];
  const yearsCovered = useMemo(() => {
    if (byYear.length === 0) return "";
    const first = byYear[0]?.key;
    const last = byYear[byYear.length - 1]?.key;
    return first === last ? first : `${first}–${last}`;
  }, [byYear]);

  const entityKpi =
    role === "adjudicante"
      ? summary?.unique_adjudicantes ?? 0
      : role === "adjudicatario"
        ? summary?.unique_adjudicatarios ?? 0
        : Math.max(summary?.unique_adjudicantes ?? 0, summary?.unique_adjudicatarios ?? 0);

  const counterpartyTitle =
    role === "adjudicante" ? "Quem mais contrata com estes adjudicantes" : "Quem mais contrata com estes adjudicatários";

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-[1500px] mx-auto px-4 md:px-6 py-6">
        {/* Barra superior */}
        <div className="flex flex-wrap items-center gap-2 mb-6">
          <div className="flex items-center gap-1 rounded-2xl glass-card p-1">
            {(Object.keys(ROLE_COPY) as EntityRole[]).map((candidate) => {
              const Icon = ROLE_COPY[candidate].icon;
              const active = candidate === role;
              return (
                <button
                  key={candidate}
                  type="button"
                  onClick={() => !active && onSwitchRole?.(candidate)}
                  aria-pressed={active}
                  className={`flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-sm transition ${
                    active ? "bg-primary/15 text-primary" : "hover:bg-white/5"
                  }`}
                >
                  <Icon size={15} />
                  {ROLE_COPY[candidate].label}
                </button>
              );
            })}
          </div>

          <button
            type="button"
            onClick={() => setShowFilters((s) => !s)}
            aria-expanded={showFilters}
            className={`px-3 py-2 rounded-xl glass-card transition flex items-center gap-2 text-sm ${
              showFilters ? "bg-primary/10 text-primary" : "hover:bg-white/5"
            }`}
          >
            <Filter size={16} />
            Filtros
            {activeFilters.length > 0 && (
              <span className="px-1.5 rounded-full bg-primary/20 text-[11px]">{activeFilters.length}</span>
            )}
          </button>

          <button
            type="button"
            onClick={applyDraft}
            className="px-3 py-2 rounded-xl glass-card bg-primary/10 text-primary border-primary/20 hover:bg-primary/15 transition flex items-center gap-2 text-sm"
          >
            <Search size={16} />
            Aplicar
          </button>

          <button
            type="button"
            onClick={() => setRefreshTick((t) => t + 1)}
            disabled={loading}
            aria-label="Atualizar dados"
            title="Atualizar dados"
            className="px-3 py-2 rounded-xl glass-card hover:bg-white/5 transition disabled:opacity-50 flex items-center gap-2 text-sm"
          >
            <RefreshCw size={16} className={loading ? "animate-spin" : ""} />
          </button>

          {onOpenCompare && (
            <button
              type="button"
              onClick={onOpenCompare}
              className="ml-auto px-3 py-2 rounded-xl glass-card hover:bg-white/5 transition flex items-center gap-2 text-sm"
            >
              <GitCompare size={16} className="text-violet-300" />
              Comparar
              {compareItems.length > 0 && (
                <span className="px-1.5 rounded-full bg-violet-500/25 text-[11px]">
                  {compareItems.length}/{MAX_COMPARE}
                </span>
              )}
            </button>
          )}
        </div>

        <div className="mb-6">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full glass-card text-xs text-amber-300 mb-3">
            <Sparkles size={14} />
            Métricas calculadas sobre todos os contratos indexados
          </div>
          <h1 className="text-3xl md:text-4xl font-bold flex items-center gap-3">
            <span className={`p-2 rounded-2xl bg-gradient-to-br ${copy.accent} border border-white/10`}>
              <RoleIcon size={32} className="text-teal-300" />
            </span>
            {copy.title}
          </h1>
          <p className="text-muted-foreground mt-2">
            {summary
              ? `${formatNumber(summary.total_contracts)} contratos${yearsCovered ? ` · ${yearsCovered}` : ""} · ${formatPrice(summary.total_value, 0)} · ${formatNumber(entityKpi)} ${copy.plural}`
              : `A carregar métricas de ${copy.plural}…`}
          </p>
          <p className="text-xs text-muted-foreground/80 mt-1">{copy.hint}</p>
        </div>

        {error && (
          <div className="mb-6 p-4 rounded-2xl bg-rose-500/10 border border-rose-500/20 text-rose-300 flex items-center gap-2">
            <Frown size={20} />
            {error}
          </div>
        )}

        {showFilters && (
          <div className="mb-6 glass-card rounded-2xl p-5 fade-in">
            <h2 className="font-semibold flex items-center gap-2 mb-4">
              <Filter size={18} /> Filtros
            </h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-3 mb-4">
              <FilterField label="Texto livre">
                <input
                  type="text"
                  value={draft.q}
                  onChange={(e) => setDraft((d) => ({ ...d, q: e.target.value }))}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") applyDraft();
                  }}
                  placeholder="Nome ou NIF da entidade"
                  className={inputClass}
                />
              </FilterField>
              <FilterField label="Ano">
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
              <FilterField label="Região NUTS">
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
              <FilterField label="Valor mínimo (€)">
                <input
                  type="number"
                  min={0}
                  value={draft.minValue}
                  onChange={(e) => setDraft((d) => ({ ...d, minValue: e.target.value }))}
                  placeholder="ex.: 100000"
                  className={inputClass}
                />
              </FilterField>
              <FilterField label="Valor máximo (€)">
                <input
                  type="number"
                  min={0}
                  value={draft.maxValue}
                  onChange={(e) => setDraft((d) => ({ ...d, maxValue: e.target.value }))}
                  placeholder="ex.: 5000000"
                  className={inputClass}
                />
              </FilterField>
              <FilterField label={`Contratos mínimos por entidade`}>
                <input
                  type="number"
                  min={1}
                  value={draft.minContracts}
                  onChange={(e) => setDraft((d) => ({ ...d, minContracts: e.target.value }))}
                  placeholder="ex.: 10"
                  className={inputClass}
                />
              </FilterField>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={applyDraft}
                className="px-4 py-2 rounded-xl glass-card bg-primary/10 text-primary border-primary/20 hover:bg-primary/15 transition text-sm"
              >
                Aplicar filtros
              </button>
              <button
                type="button"
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
                type="button"
                onClick={() => removeFilter(key)}
                title="Remover filtro"
                className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full bg-white/5 border border-white/10 text-xs hover:bg-white/10 transition"
              >
                {key}: {String(value)}
                <X size={12} />
              </button>
            ))}
            <button type="button" onClick={resetFilters} className="ml-auto text-xs text-primary hover:underline">
              Limpar tudo
            </button>
          </div>
        )}

        {/* Indicadores */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-4 mb-6 fade-in">
          <StatCard
            icon={FileText}
            label="Contratos"
            value={loading && !summary ? "…" : formatNumber(summary?.total_contracts)}
            sub={activeFilters.length > 0 ? "com os filtros aplicados" : "todo o universo"}
            color="text-teal-400"
            glow="glow-teal"
          />
          <StatCard
            icon={Euro}
            label="Valor contratado"
            value={loading && !summary ? "…" : formatPrice(summary?.total_value, 0)}
            color="text-amber-400"
            glow="glow-amber"
          />
          <StatCard
            icon={Activity}
            label="Valor médio por contrato"
            value={loading && !summary ? "…" : formatPrice(summary?.avg_value, 0)}
            sub={`Maior: ${formatPrice(summary?.max_value, 0)}`}
            color="text-rose-400"
            glow="glow-rose"
          />
          <StatCard
            icon={role === "adjudicante" ? Landmark : role === "adjudicatario" ? Briefcase : Layers}
            label={role === "all" ? "Entidades (papel dominante)" : `Nº de ${copy.plural}`}
            value={loading && !summary ? "…" : formatNumber(entityKpi)}
            sub={`NIF distintos${role === "all" ? " · adjudicantes e adjudicatários" : ""}`}
            color="text-blue-400"
            glow="glow-blue"
          />
          <StatCard
            icon={HandCoins}
            label="Valor médio por entidade"
            value={loading && !summary ? "…" : formatPrice(summary?.avg_value_per_entity, 0)}
            sub="valor contratado / entidade"
            color="text-violet-400"
            glow="glow-blue"
          />
          <StatCard
            icon={Percent}
            label="Concentração (top 10)"
            value={loading && !summary ? "…" : formatPercent(summary?.concentration?.top10)}
            sub={`Top 1: ${formatPercent(summary?.concentration?.top1)} · Top 5: ${formatPercent(summary?.concentration?.top5)}`}
            color="text-emerald-400"
            glow="glow-teal"
          />
        </div>

        {loading && !summary ? (
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
                hint={`${formatNumber(summary?.total_contracts)} contratos`}
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
                hint={`${formatPrice(summary?.total_value, 0)} no total`}
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

            {/* Ranking comparável */}
            <div className="mb-6">
              <CardShell
                icon={TrendingUp}
                iconClass="text-blue-400"
                iconBg="bg-blue-500/15 border border-blue-400/20"
                title={`Maiores ${copy.plural}`}
                hint={`Top ${topEntities.length} por valor · use o botão para comparar (máx. ${MAX_COMPARE})`}
                action={
                  onOpenCompare && compareItems.length > 0 ? (
                    <button
                      type="button"
                      onClick={onOpenCompare}
                      className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.05] px-2.5 py-1 text-[11.5px] transition hover:bg-white/[0.1]"
                    >
                      <GitCompare size={13} /> Abrir comparação ({compareItems.length})
                    </button>
                  ) : undefined
                }
              >
                {topEntities.length === 0 ? (
                  <p className="text-muted-foreground py-6">
                    Nenhuma entidade corresponde aos filtros aplicados.
                  </p>
                ) : (
                  <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
                    {topEntities.map((entity, index) => (
                      <EntityRow
                        key={entity.nif || entity.name}
                        entity={entity}
                        rank={index + 1}
                        max={maxEntityValue}
                        role={role}
                        onSelectEntity={onSelectEntity}
                      />
                    ))}
                  </div>
                )}
              </CardShell>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
              <CardShell
                icon={Tag}
                iconClass="text-emerald-400"
                iconBg="bg-emerald-500/15 border border-emerald-400/20"
                title="Top categorias CPV"
                hint="por valor contratado"
              >
                {topCpv.length === 0 ? (
                  <p className="text-muted-foreground">Sem dados para os filtros aplicados.</p>
                ) : (
                  <div className="space-y-4">
                    {topCpv.slice(0, 10).map((row) => (
                      <RankBar
                        key={row.key}
                        label={row.key}
                        sub={row.description || undefined}
                        value={row.total_value ?? row.count}
                        display={`${formatNumber(row.count)} · ${formatCompactPrice(row.total_value)}`}
                        max={maxCpvCount}
                        color="bg-emerald-400"
                      />
                    ))}
                  </div>
                )}
              </CardShell>

              <CardShell
                icon={MapPin}
                iconClass="text-sky-400"
                iconBg="bg-sky-500/15 border border-sky-400/20"
                title="Distribuição por região (NUTS)"
                hint="valor contratado por região"
              >
                {topRegions.length === 0 ? (
                  <p className="text-muted-foreground">Sem dados para os filtros aplicados.</p>
                ) : (
                  <>
                    <div className="h-56 mb-4">
                      <ResponsiveContainer width="100%" height="100%">
                        <RePieChart>
                          <Pie
                            data={topRegions.slice(0, 8)}
                            dataKey="total_value"
                            nameKey="key"
                            innerRadius={44}
                            outerRadius={78}
                            paddingAngle={2}
                          >
                            {topRegions.slice(0, 8).map((row, index) => (
                              <Cell key={row.key} fill={CHART_COLORS[index % CHART_COLORS.length]} />
                            ))}
                          </Pie>
                          <Tooltip contentStyle={tooltipStyle} formatter={euroFormatter} />
                        </RePieChart>
                      </ResponsiveContainer>
                    </div>
                    <div className="space-y-3">
                      {topRegions.slice(0, 5).map((row) => (
                        <RankBar
                          key={row.key}
                          label={row.key}
                          value={row.total_value ?? row.count}
                          display={`${formatNumber(row.count)} · ${formatCompactPrice(row.total_value)}`}
                          max={maxRegionValue}
                          color="bg-sky-400"
                        />
                      ))}
                    </div>
                  </>
                )}
              </CardShell>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-6">
              <CardShell
                icon={HandCoins}
                iconClass="text-violet-400"
                iconBg="bg-violet-500/15 border border-violet-400/20"
                title={counterpartyTitle}
                hint="por valor contratado"
              >
                {topCounterparties.length === 0 ? (
                  <p className="text-muted-foreground">Sem dados para os filtros aplicados.</p>
                ) : (
                  <div className="space-y-4">
                    {topCounterparties.slice(0, 8).map((row) => (
                      <RankBar
                        key={row.key}
                        label={row.description || row.key}
                        sub={`NIF ${row.key}`}
                        value={row.total_value ?? row.count}
                        display={`${formatNumber(row.count)} · ${formatCompactPrice(row.total_value)}`}
                        max={maxCounterpartyValue}
                        color="bg-violet-400"
                      />
                    ))}
                  </div>
                )}
              </CardShell>

              <CardShell
                icon={Layers}
                iconClass="text-indigo-400"
                iconBg="bg-indigo-500/15 border border-indigo-400/20"
                title="Tipo de procedimento"
                hint="contratos por procedimento"
              >
                {topProcedures.length === 0 ? (
                  <p className="text-muted-foreground">Sem dados para os filtros aplicados.</p>
                ) : (
                  <div className="space-y-4">
                    {topProcedures.slice(0, 8).map((row) => (
                      <RankBar
                        key={row.key}
                        label={row.key}
                        value={row.total_value ?? row.count}
                        display={`${formatNumber(row.count)} · ${formatCompactPrice(row.total_value)}`}
                        max={Math.max(1, ...topProcedures.map((r) => r.total_value || 0))}
                        color="bg-indigo-400"
                      />
                    ))}
                  </div>
                )}
              </CardShell>

              <CardShell
                icon={FileText}
                iconClass="text-rose-400"
                iconBg="bg-rose-500/15 border border-rose-400/20"
                title="Tipo de contrato e escalões"
                hint="distribuição por natureza e valor"
              >
                {topContractTypes.length === 0 && valueRangeRows.length === 0 ? (
                  <p className="text-muted-foreground">Sem dados para os filtros aplicados.</p>
                ) : (
                  <div className="space-y-5">
                    <div className="space-y-3">
                      {topContractTypes.slice(0, 5).map((row) => (
                        <RankBar
                          key={row.key}
                          label={row.key}
                          value={row.total_value ?? row.count}
                          display={`${formatNumber(row.count)} · ${formatCompactPrice(row.total_value)}`}
                          max={Math.max(1, ...topContractTypes.map((r) => r.total_value || 0))}
                          color="bg-rose-400"
                        />
                      ))}
                    </div>
                    {valueRangeRows.length > 1 && (
                      <div>
                        <p className="text-[10.5px] uppercase tracking-wide text-muted-foreground mb-2">
                          Escalões de valor
                        </p>
                        <ul className="space-y-1">
                          {valueRangeRows.map((row) => (
                            <li key={row.key} className="flex items-baseline justify-between gap-2 text-[11.5px]">
                              <span className="min-w-0 truncate">{row.description || row.key}</span>
                              <span className="shrink-0 tabular-nums text-muted-foreground">
                                {formatNumber(row.count)}
                              </span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                )}
              </CardShell>
            </div>

            <div className="mb-4 flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => onSwitchView?.()}
                className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.05] px-3 py-1.5 text-[12px] transition hover:bg-white/[0.1]"
              >
                <ArrowLeft size={13} /> Voltar ao inicio
              </button>
              <button
                type="button"
                onClick={() => onSwitchRole?.("all")}
                className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.05] px-3 py-1.5 text-[12px] transition hover:bg-white/[0.1]"
              >
                <Building2 size={13} /> Ver todas as empresas
              </button>
              {onOpenCompare && (
                <button
                  type="button"
                  onClick={onOpenCompare}
                  className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.05] px-3 py-1.5 text-[12px] transition hover:bg-white/[0.1]"
                >
                  <GitCompare size={13} /> Comparar {copy.plural}
                </button>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
