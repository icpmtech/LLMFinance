import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, FileText, TrendingUp, BarChart3, PieChart, Activity, Euro, Database, RefreshCw, Filter, Download, FileSpreadsheet } from "lucide-react";
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
const euroFormatter: RechartsFormatter = (value) => [formatEuro(Number(value)), "Valor"];
const percentPieLabel: PieLabel = (props) => {
  const p = props?.percent ?? 0;
  return `${((p) * 100).toFixed(0)}%`;
};
const cpvPieLabel: PieLabel = (props) => {
  const name = String(props?.name ?? "");
  const p = props?.percent ?? 0;
  return `${name} ${((p) * 100).toFixed(0)}%`;
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

function StatCard({ icon: Icon, label, value, sub }: { icon: any; label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-xl border border-border bg-card p-4 flex items-start gap-3">
      <div className="p-2 rounded-lg bg-primary/10 text-primary">
        <Icon size={20} />
      </div>
      <div>
        <p className="text-xs text-muted-foreground">{label}</p>
        <p className="text-xl font-bold text-foreground">{value}</p>
        {sub && <p className="text-xs text-muted-foreground mt-0.5">{sub}</p>}
      </div>
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

  return (
    <div className="min-h-screen w-full bg-background text-foreground">
      <div className="max-w-7xl mx-auto px-4 py-6">
        <button
          onClick={onSwitchView}
          className="mb-4 flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition"
        >
          <ArrowLeft size={16} />
          Voltar
        </button>

        <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4 mb-6">
          <div>
            <h1 className="text-2xl font-bold flex items-center gap-2">
              <BarChart3 size={28} />
              Dashboard de Contratos Públicos
            </h1>
            <p className="text-sm text-muted-foreground mt-1">
              {status ? `${formatNumber(status.total)} contratos indexados` : "A carregar..."}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <select
              value={year}
              onChange={(e) => setYear(e.target.value === "" ? "" : parseInt(e.target.value))}
              className="px-3 py-2 rounded-lg bg-muted border border-border text-foreground focus:outline-none focus:ring-2 focus:ring-primary"
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
              className="px-3 py-2 rounded-lg bg-secondary text-secondary-foreground hover:bg-accent transition disabled:opacity-50 flex items-center gap-2"
            >
              <RefreshCw size={16} className={loading ? "animate-spin" : ""} />
              <span className="hidden sm:inline">Atualizar</span>
            </button>
            <button
              onClick={() => setShowFilters((s) => !s)}
              className={`px-3 py-2 rounded-lg border border-border transition flex items-center gap-2 ${showFilters ? "bg-primary text-primary-foreground" : "bg-card hover:bg-muted"}`}
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
              className="px-3 py-2 rounded-lg bg-green-600 text-white hover:bg-green-700 transition disabled:opacity-50 flex items-center gap-2"
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
              className="px-3 py-2 rounded-lg bg-red-600 text-white hover:bg-red-700 transition disabled:opacity-50 flex items-center gap-2"
            >
              <Download size={16} />
              <span className="hidden sm:inline">PDF</span>
            </button>
            {onSwitchSearch && (
              <button
                onClick={onSwitchSearch}
                className="px-3 py-2 rounded-lg bg-primary text-primary-foreground hover:opacity-90 transition flex items-center gap-2"
              >
                <FileText size={16} />
                <span className="hidden sm:inline">Pesquisar</span>
              </button>
            )}
          </div>
        </div>

        {error && (
          <div className="mb-6 rounded-lg px-3 py-2 text-sm bg-destructive/10 text-destructive">
            {error}
          </div>
        )}

        {showFilters && (
          <div className="mb-6 rounded-xl border border-border bg-card p-4">
            <div className="flex items-center justify-between mb-3">
              <h2 className="font-semibold flex items-center gap-2">
                <Filter size={18} /> Filtros de pesquisa
              </h2>
              <span className="text-xs text-muted-foreground">
                Os mesmos parâmetros usados na pesquisa de contratos
              </span>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 mb-3">
              <input
                type="text"
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Texto livre (q)"
                className="px-3 py-2 rounded-lg bg-muted border border-border text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary"
              />
              <input
                type="text"
                value={entity}
                onChange={(e) => setEntity(e.target.value)}
                placeholder="Entidade adjudicante/ário"
                className="px-3 py-2 rounded-lg bg-muted border border-border text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary"
              />
              <input
                type="text"
                value={nif}
                onChange={(e) => setNif(e.target.value)}
                placeholder="NIF"
                className="px-3 py-2 rounded-lg bg-muted border border-border text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary"
              />
              <input
                type="text"
                value={cpvCode}
                onChange={(e) => setCpvCode(e.target.value)}
                placeholder="Código CPV"
                className="px-3 py-2 rounded-lg bg-muted border border-border text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary"
              />
              <select
                value={year}
                onChange={(e) => setYear(e.target.value === "" ? "" : parseInt(e.target.value))}
                className="px-3 py-2 rounded-lg bg-muted border border-border text-foreground focus:outline-none focus:ring-2 focus:ring-primary"
              >
                <option value="">Todos os anos</option>
                {years.map((y) => (
                  <option key={y} value={y}>
                    {y}
                  </option>
                ))}
              </select>
              <input
                type="number"
                value={minPrice}
                onChange={(e) => setMinPrice(e.target.value)}
                placeholder="Preço mínimo €"
                className="px-3 py-2 rounded-lg bg-muted border border-border text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary"
              />
              <input
                type="number"
                value={maxPrice}
                onChange={(e) => setMaxPrice(e.target.value)}
                placeholder="Preço máximo €"
                className="px-3 py-2 rounded-lg bg-muted border border-border text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary"
              />
              <input
                type="date"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
                placeholder="Data início"
                className="px-3 py-2 rounded-lg bg-muted border border-border text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary"
              />
              <input
                type="date"
                value={endDate}
                onChange={(e) => setEndDate(e.target.value)}
                placeholder="Data fim"
                className="px-3 py-2 rounded-lg bg-muted border border-border text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary"
              />
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={applyFilters}
                className="px-3 py-2 rounded-lg bg-primary text-primary-foreground hover:opacity-90 transition"
              >
                Aplicar filtros
              </button>
              <button
                onClick={resetFilters}
                className="px-3 py-2 rounded-lg bg-muted text-foreground hover:bg-accent transition"
              >
                Limpar
              </button>
            </div>
          </div>
        )}

        {Object.keys(filters).length > 2 && (
          <div className="mb-6 rounded-lg px-3 py-2 text-sm bg-muted/50 text-foreground flex flex-wrap gap-2 items-center">
            <span className="text-muted-foreground">Filtros activos:</span>
            {filters.q && <span className="px-2 py-1 rounded bg-primary/10 text-primary text-xs">q: {filters.q}</span>}
            {filters.year !== undefined && <span className="px-2 py-1 rounded bg-primary/10 text-primary text-xs">ano: {filters.year}</span>}
            {filters.entity && <span className="px-2 py-1 rounded bg-primary/10 text-primary text-xs">entidade: {filters.entity}</span>}
            {filters.nif && <span className="px-2 py-1 rounded bg-primary/10 text-primary text-xs">nif: {filters.nif}</span>}
            {filters.cpv_code && <span className="px-2 py-1 rounded bg-primary/10 text-primary text-xs">cpv: {filters.cpv_code}</span>}
            {filters.min_price !== undefined && <span className="px-2 py-1 rounded bg-primary/10 text-primary text-xs">min: {formatEuro(filters.min_price)}</span>}
            {filters.max_price !== undefined && <span className="px-2 py-1 rounded bg-primary/10 text-primary text-xs">max: {formatEuro(filters.max_price)}</span>}
            {filters.start_date && <span className="px-2 py-1 rounded bg-primary/10 text-primary text-xs">desde: {filters.start_date}</span>}
            {filters.end_date && <span className="px-2 py-1 rounded bg-primary/10 text-primary text-xs">até: {filters.end_date}</span>}
          </div>
        )}

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
          <StatCard icon={FileText} label="Total de contratos" value={formatNumber(data?.total_contracts)} />
          <StatCard icon={Euro} label="Valor total" value={formatEuro(data?.total_value)} />
          <StatCard icon={Activity} label="Valor médio" value={formatEuro(data?.avg_value)} sub={`Máx: ${formatEuro(data?.max_value)}`} />
          <StatCard icon={TrendingUp} label="Anos disponíveis" value={String(years.length)} />
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
          <div className="rounded-xl border border-border bg-card p-4">
            <h2 className="font-semibold mb-4 flex items-center gap-2">
              <BarChart3 size={18} /> Contratos por ano
            </h2>
            <div className="h-72">
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

          <div className="rounded-xl border border-border bg-card p-4">
            <h2 className="font-semibold mb-4 flex items-center gap-2">
              <Activity size={18} /> Contratos por mês
            </h2>
            <div className="h-72">
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

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
          <div className="rounded-xl border border-border bg-card p-4">
            <h2 className="font-semibold mb-4 flex items-center gap-2">
              <TrendingUp size={18} /> Top entidades por valor adjudicado
            </h2>
            <div className="h-80">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={topEntities} layout="vertical">
                  <CartesianGrid strokeDasharray="3 3" stroke="#2e323b" />
                  <XAxis type="number" stroke="#9aa0aa" tickFormatter={(v) => `€${(v / 1_000_000).toFixed(0)}M`} />
                  <YAxis type="category" dataKey="key" stroke="#9aa0aa" width={140} tick={{ fontSize: 11 }} />
                  <Tooltip
                    contentStyle={{ backgroundColor: "#16181d", borderColor: "#2e323b", color: "#e8e9ec" }}
                    formatter={euroFormatter}
                  />
                  <Bar dataKey="total_value" fill="#8b5cf6" radius={[0, 4, 4, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="rounded-xl border border-border bg-card p-4">
            <h2 className="font-semibold mb-4 flex items-center gap-2">
              <PieChart size={18} /> Top CPV
            </h2>
            <div className="h-80">
              <ResponsiveContainer width="100%" height="100%">
                <RePieChart>
                  <Pie
                    data={topCpv}
                    dataKey="count"
                    nameKey="key"
                    cx="50%"
                    cy="50%"
                    outerRadius={90}
                    label={cpvPieLabel}
                  >
                    {topCpv.map((_: ContractAnalyticsRow, i: number) => (
                      <Cell key={`cell-${i}`} fill={COLORS[i % COLORS.length]} />
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

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-6">
          <div className="rounded-xl border border-border bg-card p-4">
            <h2 className="font-semibold mb-4 flex items-center gap-2">
              <BarChart3 size={18} /> Distribuição de valores
            </h2>
            <div className="h-64">
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

          <div className="rounded-xl border border-border bg-card p-4">
            <h2 className="font-semibold mb-4 flex items-center gap-2">
              <PieChart size={18} /> Tipos de procedimento
            </h2>
            <div className="h-64">
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

          <div className="rounded-xl border border-border bg-card p-4">
            <h2 className="font-semibold mb-4 flex items-center gap-2">
              <PieChart size={18} /> Tipos de contrato
            </h2>
            <div className="h-64">
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

        <div className="rounded-xl border border-border bg-card p-4">
          <h2 className="font-semibold mb-3 flex items-center gap-2">
            <Database size={18} /> Tabelas resumo
          </h2>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div>
              <p className="text-sm font-medium mb-2 text-muted-foreground">Top entidades</p>
              <div className="overflow-auto max-h-64 rounded-lg border border-border">
                <table className="w-full text-sm text-left">
                  <thead className="bg-muted text-muted-foreground">
                    <tr>
                      <th className="px-3 py-2">Entidade</th>
                      <th className="px-3 py-2">Contratos</th>
                      <th className="px-3 py-2">Valor total</th>
                    </tr>
                  </thead>
                  <tbody>
                    {topEntities.map((e: ContractAnalyticsRow, i: number) => (
                      <tr key={i} className="border-t border-border">
                        <td className="px-3 py-2 max-w-[200px] truncate" title={e.key}>{e.key}</td>
                        <td className="px-3 py-2">{formatNumber(e.count)}</td>
                        <td className="px-3 py-2">{formatEuro(e.total_value)}</td>
                      </tr>
                    ))}
                    {topEntities.length === 0 && (
                      <tr><td colSpan={3} className="px-3 py-4 text-center text-muted-foreground">Sem dados</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
            <div>
              <p className="text-sm font-medium mb-2 text-muted-foreground">Top CPV</p>
              <div className="overflow-auto max-h-64 rounded-lg border border-border">
                <table className="w-full text-sm text-left">
                  <thead className="bg-muted text-muted-foreground">
                    <tr>
                      <th className="px-3 py-2">CPV</th>
                      <th className="px-3 py-2">Contratos</th>
                      <th className="px-3 py-2">Descrição</th>
                    </tr>
                  </thead>
                  <tbody>
                    {topCpv.map((c: ContractAnalyticsRow, i: number) => (
                      <tr key={i} className="border-t border-border">
                        <td className="px-3 py-2 font-mono">{c.key}</td>
                        <td className="px-3 py-2">{formatNumber(c.count)}</td>
                        <td className="px-3 py-2 max-w-[250px] truncate" title={c.description}>{c.description || "—"}</td>
                      </tr>
                    ))}
                    {topCpv.length === 0 && (
                      <tr><td colSpan={3} className="px-3 py-4 text-center text-muted-foreground">Sem dados</td></tr>
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
