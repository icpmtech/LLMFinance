import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, FileText, TrendingUp, BarChart3, PieChart, Activity, Euro, Database, RefreshCw, Filter, Download, FileSpreadsheet, Sparkles } from "lucide-react";
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
  LineChart,
  Line,
  Legend,
  type PieLabel,
} from "recharts";
import type { Formatter as RechartsFormatter } from "recharts/types/component/DefaultTooltipContent";
import { getContractAnalytics, getContractYears, getContractStatus, exportContractsExcel, exportContractsPdf } from "../api";
import type { ContractAnalyticsResponse, ContractAnalyticsFilters, ContractAnalyticsRow } from "../types";

interface ContractsDashboardPageProps {
  onSwitchView: () => void;
  onSwitchSearch?: () => void;
}

const countFormatter: RechartsFormatter = (value) => [formatNumber(Number(value)), "Contratos"];
const percentPieLabel: PieLabel = (props) => {
  const p = props?.percent ?? 0;
  return `${((p) * 100).toFixed(0)}%`;
};

/**
 * Percentagem dentro da fatia (o rótulo exterior ficava sobreposto com 8 CPV).
 * Fatias pequenas ficam sem rótulo para não colidirem.
 */
const insidePercentLabel: PieLabel = (props) => {
  const percent = props?.percent ?? 0;
  if (percent < 0.05) return null;
  const mid = Number(props?.midAngle ?? 0);
  const outer = Number(props?.outerRadius ?? 0);
  const cx = Number(props?.cx ?? 0);
  const cy = Number(props?.cy ?? 0);
  const radius = outer * 0.62;
  const x = cx + radius * Math.cos((-mid * Math.PI) / 180);
  const y = cy + radius * Math.sin((-mid * Math.PI) / 180);
  return (
    <text x={x} y={y} fill="#ffffff" textAnchor="middle" dominantBaseline="central" fontSize={11} fontWeight={600}>
      {`${(percent * 100).toFixed(0)}%`}
    </text>
  );
};

const COLORS = ["#10a37f", "#3b82f6", "#f59e0b", "#ef4444", "#8b5cf6", "#ec4899", "#06b6d4", "#6366f1"];

function formatEuro(n?: number | null) {
  if (n === undefined || n === null || Number.isNaN(n)) return "—";
  return n.toLocaleString("pt-PT", { style: "currency", currency: "EUR", maximumFractionDigits: 0 });
}

function formatNumber(n?: number | null) {
  if (n === undefined || n === null || Number.isNaN(n)) return "—";
  return n.toLocaleString("pt-PT");
}

function useDebounce<T>(value: T, delay = 300) {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(t);
  }, [value, delay]);
  return debounced;
}

function StatCard({
  icon: Icon,
  label,
  value,
  sub,
  color = "text-teal-400",
  glow = "glow-teal",
}: {
  icon: any;
  label: string;
  value: string;
  sub?: string;
  color?: string;
  glow?: string;
}) {
  return (
    <div className={`glass-card gradient-border rounded-2xl p-5 ${glow}`}>
      <div className="flex items-center gap-2 text-sm text-muted-foreground mb-2">
        <Icon size={18} className={color} />
        {label}
      </div>
      <p className="text-2xl md:text-3xl font-bold stat-value">{value}</p>
      {sub && <p className="text-xs text-muted-foreground mt-1">{sub}</p>}
    </div>
  );
}

export function ContractsDashboardPage({ onSwitchView, onSwitchSearch }: ContractsDashboardPageProps) {
  const [filters, setFilters] = useState<ContractAnalyticsFilters>({});
  const [q, setQ] = useState("");
  const [year, setYear] = useState<number | "">("");
  const [entity, setEntity] = useState("");
  const [nif, setNif] = useState("");
  const [cpvCode, setCpvCode] = useState("");
  const [minPrice, setMinPrice] = useState<string>("");
  const [maxPrice, setMaxPrice] = useState<string>("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [showFilters, setShowFilters] = useState(false);

  const [data, setData] = useState<ContractAnalyticsResponse | null>(null);
  const [years, setYears] = useState<number[]>([]);
  const [status, setStatus] = useState<{ total: number; years: number[] } | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [exporting, setExporting] = useState<"excel" | "pdf" | null>(null);

  const debouncedFilters = useDebounce(filters, 500);

  useEffect(() => {
    Promise.all([getContractStatus(), getContractYears()])
      .then(([s, y]) => {
        setStatus(s);
        setYears(y.available ?? []);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Erro ao carregar anos"));
  }, []);

  const buildFilters = (): ContractAnalyticsFilters => {
    const f: ContractAnalyticsFilters = { top_entities: 8, top_cpv: 8 };
    if (q.trim()) f.q = q.trim();
    if (year !== "") f.year = year;
    if (entity.trim()) f.entity = entity.trim();
    if (nif.trim()) f.nif = nif.trim();
    if (cpvCode.trim()) f.cpv_code = cpvCode.trim();
    if (minPrice.trim() && !Number.isNaN(Number(minPrice))) f.min_price = Number(minPrice);
    if (maxPrice.trim() && !Number.isNaN(Number(maxPrice))) f.max_price = Number(maxPrice);
    if (startDate) f.start_date = startDate;
    if (endDate) f.end_date = endDate;
    return f;
  };

  const applyFilters = () => setFilters(buildFilters());

  const resetFilters = () => {
    setQ("");
    setYear("");
    setEntity("");
    setNif("");
    setCpvCode("");
    setMinPrice("");
    setMaxPrice("");
    setStartDate("");
    setEndDate("");
    setFilters({ top_entities: 8, top_cpv: 8 });
  };

  const loadAnalytics = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getContractAnalytics(debouncedFilters);
      setData(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao carregar analytics");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadAnalytics();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedFilters]);

  const byYearSorted = useMemo(() => [...(data?.by_year ?? [])].sort((a, b) => (a.key < b.key ? -1 : 1)), [data]);
  const byMonthSorted = useMemo(() => [...(data?.by_month ?? [])].sort((a, b) => (a.key < b.key ? -1 : 1)), [data]);
  const topEntities = data?.top_entities ?? [];
  const topCpv = data?.top_cpv ?? [];
  const procedureTypes = data?.procedure_types ?? [];
  const contractTypes = data?.contract_types ?? [];
  const valueDistribution = data?.value_distribution ?? [];
  const cpvTotal = useMemo(
    () => topCpv.reduce((acc, row) => acc + (row.count || 0), 0) || 1,
    [topCpv],
  );

  return (
    <div className="@container min-h-screen w-full bg-background text-foreground orbit-bg">
        <div className="mx-auto max-w-7xl px-4 py-8 @2xl:px-6">
        <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4 mb-8">
          <button
            onClick={onSwitchView}
            className="self-start flex items-center gap-2 px-3 py-1.5 rounded-full glass-card text-sm text-muted-foreground hover:text-foreground transition"
          >
            <ArrowLeft size={16} />
            Voltar
          </button>
          <div className="flex items-center gap-2 flex-wrap">
            <select
              value={year}
              onChange={(e) => setYear(e.target.value === "" ? "" : parseInt(e.target.value))}
              className="px-3 py-2 rounded-xl bg-background/60 border border-border text-foreground focus:outline-none focus:ring-2 focus:ring-primary/60"
            >
              <option value="">Todos os anos</option>
              {years.map((y) => (
                <option key={y} value={y}>
                  {y}
                </option>
              ))}
            </select>
            <button
              onClick={loadAnalytics}
              disabled={loading}
              className="px-3 py-2 rounded-xl glass-card hover:bg-white/5 transition disabled:opacity-50 flex items-center gap-2 text-sm"
            >
              <RefreshCw size={16} className={loading ? "animate-spin" : ""} />
              <span className="hidden sm:inline">Atualizar</span>
            </button>
            <button
              onClick={() => setShowFilters((s) => !s)}
              className={`px-3 py-2 rounded-xl transition flex items-center gap-2 text-sm ${showFilters ? "glass-card bg-primary/10 text-primary border-primary/20" : "glass-card hover:bg-white/5"}`}
            >
              <Filter size={16} />
              <span className="hidden sm:inline">Filtros</span>
            </button>
            <button
              onClick={async () => {
                setExporting("excel");
                try {
                  const blob = await exportContractsExcel(filters);
                  const url = URL.createObjectURL(blob);
                  const a = document.createElement("a");
                  a.href = url;
                  a.download = `contratos_${new Date().toISOString().slice(0, 10)}.xlsx`;
                  a.click();
                  URL.revokeObjectURL(url);
                } catch (err) {
                  setError(err instanceof Error ? err.message : "Erro ao exportar Excel");
                } finally {
                  setExporting(null);
                }
              }}
              disabled={exporting !== null}
              className="px-3 py-2 rounded-xl glass-card text-emerald-400 border-emerald-400/20 hover:bg-emerald-400/10 transition disabled:opacity-50 flex items-center gap-2 text-sm"
            >
              <FileSpreadsheet size={16} />
              <span className="hidden sm:inline">Excel</span>
            </button>
            <button
              onClick={async () => {
                setExporting("pdf");
                try {
                  const blob = await exportContractsPdf(filters);
                  const url = URL.createObjectURL(blob);
                  const a = document.createElement("a");
                  a.href = url;
                  a.download = `contratos_${new Date().toISOString().slice(0, 10)}.pdf`;
                  a.click();
                  URL.revokeObjectURL(url);
                } catch (err) {
                  setError(err instanceof Error ? err.message : "Erro ao exportar PDF");
                } finally {
                  setExporting(null);
                }
              }}
              disabled={exporting !== null}
              className="px-3 py-2 rounded-xl glass-card text-rose-400 border-rose-400/20 hover:bg-rose-400/10 transition disabled:opacity-50 flex items-center gap-2 text-sm"
            >
              <Download size={16} />
              <span className="hidden sm:inline">PDF</span>
            </button>
            {onSwitchSearch && (
              <button
                onClick={onSwitchSearch}
                className="px-3 py-2 rounded-xl glass-card bg-primary/10 text-primary border-primary/20 hover:bg-primary/15 transition flex items-center gap-2 text-sm"
              >
                <FileText size={16} />
                <span className="hidden sm:inline">Pesquisar</span>
              </button>
            )}
          </div>
        </div>

        <div className="mb-8 fade-in">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full glass-card text-xs text-amber-300 mb-3">
            <Sparkles size={14} />
            Visão agregada da contratação pública
          </div>
          <h1 className="text-3xl md:text-4xl font-bold flex items-center gap-3 mb-2">
            <span className="p-2 rounded-2xl bg-gradient-to-br from-amber-500/20 to-rose-500/15 border border-white/10">
              <BarChart3 size={32} className="text-amber-400" />
            </span>
            Dashboard de Contratos Públicos
          </h1>
          <p className="text-muted-foreground max-w-2xl">
            {status ? `${formatNumber(status.total)} contratos indexados` : "A carregar..."}
          </p>
        </div>

        {error && (
          <div className="mb-6 rounded-2xl px-4 py-3 text-sm bg-rose-500/10 border border-rose-500/20 text-rose-300 flex items-center gap-2">
            {error}
          </div>
        )}

        {showFilters && (
          <div className="mb-8 glass-card rounded-2xl p-5 fade-in">
            <div className="flex items-center justify-between mb-4">
              <h2 className="font-semibold flex items-center gap-2">
                <Filter size={18} /> Filtros de pesquisa
              </h2>
              <span className="text-xs text-muted-foreground">
                Os mesmos parâmetros usados na pesquisa de contratos
              </span>
            </div>
            <div className="grid grid-cols-1 @lg:grid-cols-2 @5xl:grid-cols-4 gap-3 mb-4">
              <div className="@lg:col-span-2 @5xl:col-span-4">
                <label className="text-xs text-muted-foreground block mb-1">Texto livre</label>
                <input
                  type="text"
                  value={q}
                  onChange={(e) => setQ(e.target.value)}
                  placeholder="Texto livre (q)"
                  className="w-full px-3 py-2 rounded-xl bg-background/60 border border-border text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/60"
                />
              </div>
              <div>
                <label className="text-xs text-muted-foreground block mb-1">Entidade</label>
                <input
                  type="text"
                  value={entity}
                  onChange={(e) => setEntity(e.target.value)}
                  placeholder="Entidade adjudicante/ário"
                  className="w-full px-3 py-2 rounded-xl bg-background/60 border border-border text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/60"
                />
              </div>
              <div>
                <label className="text-xs text-muted-foreground block mb-1">NIF</label>
                <input
                  type="text"
                  value={nif}
                  onChange={(e) => setNif(e.target.value)}
                  placeholder="NIF"
                  className="w-full px-3 py-2 rounded-xl bg-background/60 border border-border text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/60"
                />
              </div>
              <div>
                <label className="text-xs text-muted-foreground block mb-1">Código CPV</label>
                <input
                  type="text"
                  value={cpvCode}
                  onChange={(e) => setCpvCode(e.target.value)}
                  placeholder="Código CPV"
                  className="w-full px-3 py-2 rounded-xl bg-background/60 border border-border text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/60"
                />
              </div>
              <div>
                <label className="text-xs text-muted-foreground block mb-1">Ano</label>
                <select
                  value={year}
                  onChange={(e) => setYear(e.target.value === "" ? "" : parseInt(e.target.value))}
                  className="w-full px-3 py-2 rounded-xl bg-background/60 border border-border text-foreground focus:outline-none focus:ring-2 focus:ring-primary/60"
                >
                  <option value="">Todos os anos</option>
                  {years.map((y) => (
                    <option key={y} value={y}>
                      {y}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-xs text-muted-foreground block mb-1">Preço mínimo €</label>
                <input
                  type="number"
                  value={minPrice}
                  onChange={(e) => setMinPrice(e.target.value)}
                  placeholder="Preço mínimo €"
                  className="w-full px-3 py-2 rounded-xl bg-background/60 border border-border text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/60"
                />
              </div>
              <div>
                <label className="text-xs text-muted-foreground block mb-1">Preço máximo €</label>
                <input
                  type="number"
                  value={maxPrice}
                  onChange={(e) => setMaxPrice(e.target.value)}
                  placeholder="Preço máximo €"
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
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={applyFilters}
                className="px-4 py-2 rounded-xl glass-card bg-primary/10 text-primary border-primary/20 hover:bg-primary/15 transition"
              >
                Aplicar filtros
              </button>
              <button
                onClick={resetFilters}
                className="px-4 py-2 rounded-xl glass-card hover:bg-white/5 transition"
              >
                Limpar
              </button>
            </div>
          </div>
        )}

        {Object.keys(filters).length > 2 && (
          <div className="mb-8 rounded-2xl px-4 py-3 text-sm glass-card flex flex-wrap gap-2 items-center">
            <span className="text-muted-foreground">Filtros activos:</span>
            {filters.q && <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full glass-card text-xs">q: {filters.q}</span>}
            {filters.year !== undefined && <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full glass-card text-xs">ano: {filters.year}</span>}
            {filters.entity && <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full glass-card text-xs">entidade: {filters.entity}</span>}
            {filters.nif && <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full glass-card text-xs">nif: {filters.nif}</span>}
            {filters.cpv_code && <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full glass-card text-xs">cpv: {filters.cpv_code}</span>}
            {filters.min_price !== undefined && <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full glass-card text-xs">min: {formatEuro(filters.min_price)}</span>}
            {filters.max_price !== undefined && <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full glass-card text-xs">max: {formatEuro(filters.max_price)}</span>}
            {filters.start_date && <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full glass-card text-xs">desde: {filters.start_date}</span>}
            {filters.end_date && <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full glass-card text-xs">até: {filters.end_date}</span>}
          </div>
        )}

        <div className="grid grid-cols-1 @lg:grid-cols-2 @5xl:grid-cols-4 gap-4 mb-8 fade-in">
          <StatCard
            icon={FileText}
            label="Total de contratos"
            value={formatNumber(data?.total_contracts)}
            color="text-teal-400"
            glow="glow-teal"
          />
          <StatCard
            icon={Euro}
            label="Valor total"
            value={formatEuro(data?.total_value)}
            color="text-amber-400"
            glow="glow-amber"
          />
          <StatCard
            icon={Activity}
            label="Valor médio"
            value={formatEuro(data?.avg_value)}
            sub={`Máx: ${formatEuro(data?.max_value)}`}
            color="text-rose-400"
            glow="glow-rose"
          />
          <StatCard
            icon={TrendingUp}
            label="Anos disponíveis"
            value={String(years.length)}
            color="text-blue-400"
            glow="glow-blue"
          />
        </div>

        <div className="grid grid-cols-1 @4xl:grid-cols-2 gap-6 mb-8">
          <div className="glass-card gradient-border rounded-2xl p-5">
            <div className="flex items-center gap-2 mb-5">
              <div className="p-2 rounded-xl bg-teal-500/15 border border-teal-400/20">
                <BarChart3 size={20} className="text-teal-400" />
              </div>
              <h2 className="text-xl font-semibold">Contratos por ano</h2>
            </div>
            <div className="h-56 overflow-hidden @3xl:h-72">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={byYearSorted}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#2e323b" />
                  <XAxis dataKey="key" stroke="#9aa0aa" />
                  <YAxis stroke="#9aa0aa" />
                  <Tooltip
                    contentStyle={{ backgroundColor: "#16181d", borderColor: "#2e323b", color: "#e8e9ec" }}
                    formatter={countFormatter}
                  />
                  <Bar dataKey="count" fill="#10a37f" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="glass-card gradient-border rounded-2xl p-5">
            <div className="flex items-center gap-2 mb-5">
              <div className="p-2 rounded-xl bg-blue-500/15 border border-blue-400/20">
                <Activity size={20} className="text-blue-400" />
              </div>
              <h2 className="text-xl font-semibold">Contratos por mês</h2>
            </div>
            <div className="h-56 overflow-hidden @3xl:h-72">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={byMonthSorted}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#2e323b" />
                  <XAxis dataKey="key" stroke="#9aa0aa" angle={-45} textAnchor="end" height={60} />
                  <YAxis stroke="#9aa0aa" />
                  <Tooltip
                    contentStyle={{ backgroundColor: "#16181d", borderColor: "#2e323b", color: "#e8e9ec" }}
                    formatter={countFormatter}
                  />
                  <Line type="monotone" dataKey="count" stroke="#3b82f6" strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>

        <div className="grid grid-cols-1 @4xl:grid-cols-2 gap-6 mb-8">
          <div className="glass-card gradient-border rounded-2xl p-5">
            <div className="flex items-center gap-2 mb-5">
              <div className="p-2 rounded-xl bg-amber-500/15 border border-amber-400/20">
                <TrendingUp size={20} className="text-amber-400" />
              </div>
              <h2 className="text-xl font-semibold">Top entidades por valor adjudicado</h2>
            </div>
            <div className="space-y-3.5">
              {topEntities.length === 0 && (
                <p className="py-10 text-center text-sm text-muted-foreground">Sem dados para os filtros atuais.</p>
              )}
              {topEntities.map((row: ContractAnalyticsRow, i: number) => (
                <div key={`${row.key}-${i}`}>
                  <div className="flex items-baseline justify-between gap-3 text-sm">
                    <span className="min-w-0 truncate" title={row.description || row.key}>
                      {row.description || row.key}
                    </span>
                    <span className="shrink-0 whitespace-nowrap tabular-nums text-muted-foreground">
                      {formatEuro(row.total_value)}
                    </span>
                  </div>
                  <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-white/10">
                    <div
                      className="h-full rounded-full bg-violet-400"
                      style={{ width: `${Math.max(2, ((row.total_value || 0) / (topEntities[0]?.total_value || 1)) * 100)}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="glass-card gradient-border rounded-2xl p-5">
            <div className="flex items-center gap-2 mb-5">
              <div className="p-2 rounded-xl bg-rose-500/15 border border-rose-400/20">
                <PieChart size={20} className="text-rose-400" />
              </div>
              <h2 className="text-xl font-semibold">Top CPV</h2>
            </div>
            {topCpv.length === 0 ? (
              <p className="py-10 text-center text-sm text-muted-foreground">Sem dados para os filtros atuais.</p>
            ) : (
              <div className="grid gap-4 @2xl:grid-cols-[minmax(0,200px)_minmax(0,1fr)] @2xl:items-center">
                <div className="h-48 overflow-hidden @2xl:h-56">
                  <ResponsiveContainer width="100%" height="100%">
                    <RePieChart>
                      <Pie
                        data={topCpv}
                        dataKey="count"
                        nameKey="description"
                        cx="50%"
                        cy="50%"
                        innerRadius={42}
                        outerRadius={78}
                        paddingAngle={2}
                        labelLine={false}
                        label={insidePercentLabel}
                      >
                        {topCpv.map((_: ContractAnalyticsRow, i: number) => (
                          <Cell key={`cell-${i}`} fill={COLORS[i % COLORS.length]} />
                        ))}
                      </Pie>
                      <Tooltip
                        contentStyle={{ backgroundColor: "#16181d", borderColor: "#2e323b", color: "#e8e9ec" }}
                        formatter={(value, _name, entry) => [
                          formatNumber(Number(value)),
                          String((entry?.payload as ContractAnalyticsRow | undefined)?.description || "Contratos"),
                        ]}
                      />
                    </RePieChart>
                  </ResponsiveContainer>
                </div>
                {/* Legenda própria: mostra código + descrição e sobrevive a janelas estreitas. */}
                <ul className="min-w-0 space-y-1.5">
                  {topCpv.map((row: ContractAnalyticsRow, i: number) => (
                    <li key={row.key} className="flex min-w-0 items-center gap-2 text-[12px]">
                      <span
                        className="h-2.5 w-2.5 shrink-0 rounded-full"
                        style={{ backgroundColor: COLORS[i % COLORS.length] }}
                      />
                      <span className="shrink-0 font-mono text-[11px] text-muted-foreground">{row.key}</span>
                      <span className="min-w-0 flex-1 truncate" title={row.description || row.key}>
                        {row.description || "Sem descrição"}
                      </span>
                      <span className="shrink-0 whitespace-nowrap tabular-nums text-muted-foreground">
                        {formatNumber(row.count)} · {(((row.count || 0) / cpvTotal) * 100).toFixed(1)}%
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </div>

        <div className="grid grid-cols-1 @2xl:grid-cols-2 @6xl:grid-cols-3 gap-6 mb-8">
          <div className="glass-card gradient-border rounded-2xl p-5">
            <div className="flex items-center gap-2 mb-5">
              <div className="p-2 rounded-xl bg-amber-500/15 border border-amber-400/20">
                <BarChart3 size={20} className="text-amber-400" />
              </div>
              <h2 className="text-xl font-semibold">Distribuição de valores</h2>
            </div>
            <div className="h-56 overflow-hidden @3xl:h-64">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={valueDistribution}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#2e323b" />
                  <XAxis dataKey="key" stroke="#9aa0aa" tickFormatter={(v) => `€${v}`} />
                  <YAxis stroke="#9aa0aa" />
                  <Tooltip
                    contentStyle={{ backgroundColor: "#16181d", borderColor: "#2e323b", color: "#e8e9ec" }}
                    formatter={countFormatter}
                  />
                  <Bar dataKey="count" fill="#f59e0b" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="glass-card gradient-border rounded-2xl p-5">
            <div className="flex items-center gap-2 mb-5">
              <div className="p-2 rounded-xl bg-teal-500/15 border border-teal-400/20">
                <PieChart size={20} className="text-teal-400" />
              </div>
              <h2 className="text-xl font-semibold">Tipos de procedimento</h2>
            </div>
            <div className="h-56 overflow-hidden @3xl:h-64">
              <ResponsiveContainer width="100%" height="100%">
                <RePieChart>
                  <Pie
                    data={procedureTypes}
                    dataKey="count"
                    nameKey="key"
                    cx="50%"
                    cy="50%"
                    outerRadius={75}
                    label={percentPieLabel}
                  >
                    {procedureTypes.map((_: ContractAnalyticsRow, i: number) => (
                      <Cell key={`cell-proc-${i}`} fill={COLORS[i % COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip
                    contentStyle={{ backgroundColor: "#16181d", borderColor: "#2e323b", color: "#e8e9ec" }}
                  />
                  <Legend />
                </RePieChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="glass-card gradient-border rounded-2xl p-5">
            <div className="flex items-center gap-2 mb-5">
              <div className="p-2 rounded-xl bg-blue-500/15 border border-blue-400/20">
                <PieChart size={20} className="text-blue-400" />
              </div>
              <h2 className="text-xl font-semibold">Tipos de contrato</h2>
            </div>
            <div className="h-56 overflow-hidden @3xl:h-64">
              <ResponsiveContainer width="100%" height="100%">
                <RePieChart>
                  <Pie
                    data={contractTypes}
                    dataKey="count"
                    nameKey="key"
                    cx="50%"
                    cy="50%"
                    outerRadius={75}
                    label={percentPieLabel}
                  >
                    {contractTypes.map((_: ContractAnalyticsRow, i: number) => (
                      <Cell key={`cell-type-${i}`} fill={COLORS[(i + 3) % COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip
                    contentStyle={{ backgroundColor: "#16181d", borderColor: "#2e323b", color: "#e8e9ec" }}
                  />
                  <Legend />
                </RePieChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>

        <div className="glass-card rounded-2xl p-5">
          <div className="flex items-center gap-2 mb-5">
            <div className="p-2 rounded-xl bg-primary/15 border border-primary/20">
              <Database size={20} className="text-primary" />
            </div>
            <h2 className="text-xl font-semibold">Tabelas resumo</h2>
          </div>
          <div className="grid grid-cols-1 @4xl:grid-cols-2 gap-6">
            <div className="overflow-hidden rounded-xl border border-white/5">
              <p className="text-sm font-medium px-4 py-3 bg-white/5 text-muted-foreground border-b border-white/5">Top entidades</p>
              <div className="overflow-auto max-h-64">
                <table className="w-full text-sm text-left">
                  <thead className="bg-white/[0.03] text-muted-foreground text-xs uppercase tracking-wider">
                    <tr>
                      <th className="px-4 py-2.5">Entidade</th>
                      <th className="px-4 py-2.5">Contratos</th>
                      <th className="px-4 py-2.5">Valor total</th>
                    </tr>
                  </thead>
                  <tbody>
                    {topEntities.map((e: ContractAnalyticsRow, i: number) => (
                      <tr key={i} className="border-t border-white/5 hover:bg-white/[0.03] transition">
                        <td className="px-4 py-2.5 max-w-[220px] truncate" title={e.description || e.key}>
                          {e.description || e.key}
                        </td>
                        <td className="px-4 py-2.5">{formatNumber(e.count)}</td>
                        <td className="px-4 py-2.5">{formatEuro(e.total_value)}</td>
                      </tr>
                    ))}
                    {topEntities.length === 0 && (
                      <tr><td colSpan={3} className="px-4 py-8 text-center text-muted-foreground">Sem dados</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
            <div className="overflow-hidden rounded-xl border border-white/5">
              <p className="text-sm font-medium px-4 py-3 bg-white/5 text-muted-foreground border-b border-white/5">Top CPV</p>
              <div className="overflow-auto max-h-64">
                <table className="w-full text-sm text-left">
                  <thead className="bg-white/[0.03] text-muted-foreground text-xs uppercase tracking-wider">
                    <tr>
                      <th className="px-4 py-2.5">CPV</th>
                      <th className="px-4 py-2.5">Contratos</th>
                      <th className="px-4 py-2.5">Descrição</th>
                    </tr>
                  </thead>
                  <tbody>
                    {topCpv.map((c: ContractAnalyticsRow, i: number) => (
                      <tr key={i} className="border-t border-white/5 hover:bg-white/[0.03] transition">
                        <td className="px-4 py-2.5 font-mono">{c.key}</td>
                        <td className="px-4 py-2.5">{formatNumber(c.count)}</td>
                        <td className="px-4 py-2.5 max-w-[250px] truncate" title={c.description}>{c.description || "—"}</td>
                      </tr>
                    ))}
                    {topCpv.length === 0 && (
                      <tr><td colSpan={3} className="px-4 py-8 text-center text-muted-foreground">Sem dados</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
