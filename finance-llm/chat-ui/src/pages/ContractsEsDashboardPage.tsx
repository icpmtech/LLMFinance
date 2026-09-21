/**
 * Dashboard de contratos públicos de Espanha (PLACSP) — `/contratos-es/dashboard`.
 *
 * Modelado no dashboard de contratos portugueses (`ContractsDashboardPage`), mas
 * adaptado aos campos espanhóis: `organo_nombre`, `adjudicatario_nombre`,
 * `procedimiento_label`, `tipo_contrato_label`, `cpv.nombre`, `valor_adjudicado`.
 */
import { useEffect, useMemo, useState } from "react";
import {
  ArrowLeft,
  BarChart3,
  FileText,
  Filter,
  Landmark,
  RefreshCw,
  Search,
  Sparkles,
  TrendingUp,
  Activity,
  PieChart,
  Euro,
  Database,
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
  LineChart,
  Line,
  Legend,
  type PieLabel,
} from "recharts";
import type { Formatter as RechartsFormatter } from "recharts/types/component/DefaultTooltipContent";
import {
  getContratosEsAnalytics,
  getContratosEsStatus,
} from "../contratosEsApi";
import type {
  ContratoEsAnalyticsRequest,
  ContratoEsAnalyticsResponse,
  ContratoEsAnalyticsRow,
} from "../contratosEsApi";

interface ContractsEsDashboardPageProps {
  onSwitchView: () => void;
  onSwitchSearch?: () => void;
}

const countFormatter: RechartsFormatter = (value) => [
  formatNumber(Number(value)),
  "Contratos",
];

const percentPieLabel: PieLabel = (props) => {
  const p = props?.percent ?? 0;
  return `${((p) * 100).toFixed(0)}%`;
};

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
    <text
      x={x}
      y={y}
      fill="#ffffff"
      textAnchor="middle"
      dominantBaseline="central"
      fontSize={11}
      fontWeight={600}
    >
      {`${(percent * 100).toFixed(0)}%`}
    </text>
  );
};

const COLORS = [
  "#10a37f",
  "#3b82f6",
  "#f59e0b",
  "#ef4444",
  "#8b5cf6",
  "#ec4899",
  "#06b6d4",
  "#6366f1",
];

function formatEuro(n?: number | null) {
  if (n === undefined || n === null || Number.isNaN(n)) return "—";
  return n.toLocaleString("pt-PT", {
    style: "currency",
    currency: "EUR",
    maximumFractionDigits: 0,
  });
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

export function ContractsEsDashboardPage({
  onSwitchView,
  onSwitchSearch,
}: ContractsEsDashboardPageProps) {
  const [filters, setFilters] = useState<ContratoEsAnalyticsRequest>({});
  const [q, setQ] = useState("");
  const [ano, setAno] = useState<number | "">("");
  const [organo, setOrgano] = useState("");
  const [organismoId, setOrganismoId] = useState("");
  const [adjudicatario, setAdjudicatario] = useState("");
  const [adjudicatarioNif, setAdjudicatarioNif] = useState("");
  const [cpvCode, setCpvCode] = useState("");
  const [minValue, setMinValue] = useState("");
  const [maxValue, setMaxValue] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [dateField, setDateField] = useState("fecha_publicacion");
  const [fonte, setFonte] = useState("");
  const [tipo, setTipo] = useState("");
  const [estado, setEstado] = useState("");
  const [procedimiento, setProcedimiento] = useState("");
  const [localidad, setLocalidad] = useState("");
  const [nuts, setNuts] = useState("");
  const [showFilters, setShowFilters] = useState(false);

  const [data, setData] = useState<ContratoEsAnalyticsResponse | null>(null);
  const [years, setYears] = useState<number[]>([]);
  const [status, setStatus] = useState<{ total: number; years: number[] } | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const debouncedFilters = useDebounce(filters, 500);

  useEffect(() => {
    getContratosEsStatus()
      .then((s) => {
        setStatus({ total: s.total, years: s.years ?? [] });
        setYears(s.years ?? []);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Erro ao carregar estado"));
  }, []);

  const buildFilters = (): ContratoEsAnalyticsRequest => {
    const f: ContratoEsAnalyticsRequest = {};
    if (q.trim()) f.q = q.trim();
    if (ano !== "") f.ano = ano;
    if (fonte.trim()) f.fonte = fonte.trim();
    if (tipo.trim()) f.tipo = tipo.trim();
    if (estado.trim()) f.estado = estado.trim();
    if (procedimiento.trim()) f.procedimiento = procedimiento.trim();
    if (organo.trim()) f.organo = organo.trim();
    if (organismoId.trim()) f.organismo_id = organismoId.trim();
    if (adjudicatario.trim()) f.adjudicatario = adjudicatario.trim();
    if (adjudicatarioNif.trim()) f.adjudicatario_nif = adjudicatarioNif.trim();
    if (localidad.trim()) f.localidad = localidad.trim();
    if (nuts.trim()) f.nuts = nuts.trim();
    if (cpvCode.trim()) f.cpv_code = cpvCode.trim();
    if (minValue.trim() && !Number.isNaN(Number(minValue))) f.min_value = Number(minValue);
    if (maxValue.trim() && !Number.isNaN(Number(maxValue))) f.max_value = Number(maxValue);
    if (startDate) f.start_date = startDate;
    if (endDate) f.end_date = endDate;
    if (dateField) f.date_field = dateField;
    return f;
  };

  const applyFilters = () => setFilters(buildFilters());

  const resetFilters = () => {
    setQ("");
    setAno("");
    setFonte("");
    setTipo("");
    setEstado("");
    setProcedimiento("");
    setOrgano("");
    setOrganismoId("");
    setAdjudicatario("");
    setAdjudicatarioNif("");
    setLocalidad("");
    setNuts("");
    setCpvCode("");
    setMinValue("");
    setMaxValue("");
    setStartDate("");
    setEndDate("");
    setDateField("fecha_publicacion");
    setFilters({});
  };

  const loadAnalytics = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getContratosEsAnalytics(debouncedFilters);
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

  const byYearSorted = useMemo(
    () => [...(data?.by_year ?? [])].sort((a, b) => (a.key < b.key ? -1 : 1)),
    [data]
  );
  const byMonthSorted = useMemo(
    () => [...(data?.by_month ?? [])].sort((a, b) => (a.key < b.key ? -1 : 1)),
    [data]
  );
  const topEntities = data?.top_entities ?? [];
  const topCpv = data?.top_cpv ?? [];
  const procedureTypes = data?.procedure_types ?? [];
  const contractTypes = data?.contract_types ?? [];
  const valueDistribution = data?.value_distribution ?? [];
  const cpvTotal = useMemo(
    () => topCpv.reduce((acc, row) => acc + (row.count || 0), 0) || 1,
    [topCpv]
  );

  const activeFilterPills = useMemo(() => {
    const pills: { label: string; onRemove: () => void }[] = [];
    if (filters.q) pills.push({ label: `q: ${filters.q}`, onRemove: () => setQ("") });
    if (filters.ano !== undefined) pills.push({ label: `ano: ${filters.ano}`, onRemove: () => setAno("") });
    if (filters.fonte) pills.push({ label: `fonte: ${filters.fonte}`, onRemove: () => setFonte("") });
    if (filters.organo) pills.push({ label: `órgão: ${filters.organo}`, onRemove: () => setOrgano("") });
    if (filters.adjudicatario) pills.push({ label: `adjudicatário: ${filters.adjudicatario}`, onRemove: () => setAdjudicatario("") });
    if (filters.cpv_code) pills.push({ label: `cpv: ${filters.cpv_code}`, onRemove: () => setCpvCode("") });
    if (filters.min_value !== undefined) pills.push({ label: `min: ${formatEuro(filters.min_value)}`, onRemove: () => setMinValue("") });
    if (filters.max_value !== undefined) pills.push({ label: `max: ${formatEuro(filters.max_value)}`, onRemove: () => setMaxValue("") });
    if (filters.start_date) pills.push({ label: `desde: ${filters.start_date}`, onRemove: () => setStartDate("") });
    if (filters.end_date) pills.push({ label: `até: ${filters.end_date}`, onRemove: () => setEndDate("") });
    return pills;
  }, [filters]);

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
              value={ano}
              onChange={(e) => setAno(e.target.value === "" ? "" : parseInt(e.target.value))}
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
              className={`px-3 py-2 rounded-xl transition flex items-center gap-2 text-sm ${
                showFilters
                  ? "glass-card bg-primary/10 text-primary border-primary/20"
                  : "glass-card hover:bg-white/5"
              }`}
            >
              <Filter size={16} />
              <span className="hidden sm:inline">Filtros</span>
            </button>
            {onSwitchSearch && (
              <button
                onClick={onSwitchSearch}
                className="px-3 py-2 rounded-xl glass-card bg-primary/10 text-primary border-primary/20 hover:bg-primary/15 transition flex items-center gap-2 text-sm"
              >
                <Search size={16} />
                <span className="hidden sm:inline">Pesquisar</span>
              </button>
            )}
          </div>
        </div>

        <div className="mb-8 fade-in">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full glass-card text-xs text-amber-300 mb-3">
            <Sparkles size={14} />
            Visão agregada da contratação pública espanhola
          </div>
          <h1 className="text-3xl md:text-4xl font-bold flex items-center gap-3 mb-2">
            <span className="p-2 rounded-2xl bg-gradient-to-br from-amber-500/20 to-rose-500/15 border border-white/10">
              <BarChart3 size={32} className="text-amber-400" />
            </span>
            Dashboard de Contratos Públicos — Espanha
          </h1>
          <p className="text-muted-foreground max-w-2xl">
            {status
              ? `${formatNumber(status.total)} contratos indexados (PLACSP)`
              : "A carregar..."}
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
                Os mesmos parâmetros usados na pesquisa de contratos espanhóis
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
                <label className="text-xs text-muted-foreground block mb-1">Órgão</label>
                <input
                  type="text"
                  value={organo}
                  onChange={(e) => setOrgano(e.target.value)}
                  placeholder="Nome do órgão adjudicante"
                  className="w-full px-3 py-2 rounded-xl bg-background/60 border border-border text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/60"
                />
              </div>
              <div>
                <label className="text-xs text-muted-foreground block mb-1">ID órgão (DIR3)</label>
                <input
                  type="text"
                  value={organismoId}
                  onChange={(e) => setOrganismoId(e.target.value)}
                  placeholder="Código DIR3"
                  className="w-full px-3 py-2 rounded-xl bg-background/60 border border-border text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/60"
                />
              </div>
              <div>
                <label className="text-xs text-muted-foreground block mb-1">Adjudicatário</label>
                <input
                  type="text"
                  value={adjudicatario}
                  onChange={(e) => setAdjudicatario(e.target.value)}
                  placeholder="Nome do adjudicatário"
                  className="w-full px-3 py-2 rounded-xl bg-background/60 border border-border text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/60"
                />
              </div>
              <div>
                <label className="text-xs text-muted-foreground block mb-1">NIF adjudicatário</label>
                <input
                  type="text"
                  value={adjudicatarioNif}
                  onChange={(e) => setAdjudicatarioNif(e.target.value)}
                  placeholder="NIF/CIF"
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
                  value={ano}
                  onChange={(e) => setAno(e.target.value === "" ? "" : parseInt(e.target.value))}
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
                <label className="text-xs text-muted-foreground block mb-1">Fonte</label>
                <select
                  value={fonte}
                  onChange={(e) => setFonte(e.target.value)}
                  className="w-full px-3 py-2 rounded-xl bg-background/60 border border-border text-foreground focus:outline-none focus:ring-2 focus:ring-primary/60"
                >
                  <option value="">Todas</option>
                  <option value="licitaciones">Licitações</option>
                  <option value="menores">Contratos menores</option>
                </select>
              </div>
              <div>
                <label className="text-xs text-muted-foreground block mb-1">Tipo</label>
                <input
                  type="text"
                  value={tipo}
                  onChange={(e) => setTipo(e.target.value)}
                  placeholder="Tipo de contrato"
                  className="w-full px-3 py-2 rounded-xl bg-background/60 border border-border text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/60"
                />
              </div>
              <div>
                <label className="text-xs text-muted-foreground block mb-1">Estado</label>
                <input
                  type="text"
                  value={estado}
                  onChange={(e) => setEstado(e.target.value)}
                  placeholder="Estado"
                  className="w-full px-3 py-2 rounded-xl bg-background/60 border border-border text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/60"
                />
              </div>
              <div>
                <label className="text-xs text-muted-foreground block mb-1">Procedimento</label>
                <input
                  type="text"
                  value={procedimiento}
                  onChange={(e) => setProcedimiento(e.target.value)}
                  placeholder="Procedimento"
                  className="w-full px-3 py-2 rounded-xl bg-background/60 border border-border text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/60"
                />
              </div>
              <div>
                <label className="text-xs text-muted-foreground block mb-1">Localidade</label>
                <input
                  type="text"
                  value={localidad}
                  onChange={(e) => setLocalidad(e.target.value)}
                  placeholder="Localidade"
                  className="w-full px-3 py-2 rounded-xl bg-background/60 border border-border text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/60"
                />
              </div>
              <div>
                <label className="text-xs text-muted-foreground block mb-1">NUTS</label>
                <input
                  type="text"
                  value={nuts}
                  onChange={(e) => setNuts(e.target.value)}
                  placeholder="Código NUTS"
                  className="w-full px-3 py-2 rounded-xl bg-background/60 border border-border text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/60"
                />
              </div>
              <div>
                <label className="text-xs text-muted-foreground block mb-1">Valor mínimo €</label>
                <input
                  type="number"
                  value={minValue}
                  onChange={(e) => setMinValue(e.target.value)}
                  placeholder="Valor mínimo €"
                  className="w-full px-3 py-2 rounded-xl bg-background/60 border border-border text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/60"
                />
              </div>
              <div>
                <label className="text-xs text-muted-foreground block mb-1">Valor máximo €</label>
                <input
                  type="number"
                  value={maxValue}
                  onChange={(e) => setMaxValue(e.target.value)}
                  placeholder="Valor máximo €"
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
              <div>
                <label className="text-xs text-muted-foreground block mb-1">Campo data</label>
                <select
                  value={dateField}
                  onChange={(e) => setDateField(e.target.value)}
                  className="w-full px-3 py-2 rounded-xl bg-background/60 border border-border text-foreground focus:outline-none focus:ring-2 focus:ring-primary/60"
                >
                  <option value="fecha_publicacion">Publicação</option>
                  <option value="fecha_adjudicacion">Adjudicação</option>
                  <option value="fecha_actualizacion">Atualização</option>
                </select>
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

        {activeFilterPills.length > 0 && (
          <div className="mb-8 rounded-2xl px-4 py-3 text-sm glass-card flex flex-wrap gap-2 items-center">
            <span className="text-muted-foreground">Filtros activos:</span>
            {activeFilterPills.map((pill) => (
              <button
                key={pill.label}
                onClick={() => {
                  pill.onRemove();
                  setFilters(buildFilters());
                }}
                className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full glass-card text-xs hover:bg-white/5 transition"
                title="Remover filtro"
              >
                {pill.label}
                <XIcon />
              </button>
            ))}
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
            icon={Landmark}
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
                <p className="py-10 text-center text-sm text-muted-foreground">
                  Sem dados para os filtros atuais.
                </p>
              )}
              {topEntities.map((row: ContratoEsAnalyticsRow, i: number) => (
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
                      style={{
                        width: `${Math.max(
                          2,
                          ((row.total_value || 0) / (topEntities[0]?.total_value || 1)) * 100
                        )}%`,
                      }}
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
              <p className="py-10 text-center text-sm text-muted-foreground">
                Sem dados para os filtros atuais.
              </p>
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
                        {topCpv.map((_: ContratoEsAnalyticsRow, i: number) => (
                          <Cell key={`cell-${i}`} fill={COLORS[i % COLORS.length]} />
                        ))}
                      </Pie>
                      <Tooltip
                        contentStyle={{ backgroundColor: "#16181d", borderColor: "#2e323b", color: "#e8e9ec" }}
                        formatter={(value, _name, entry) => [
                          formatNumber(Number(value)),
                          String(
                            (entry?.payload as ContratoEsAnalyticsRow | undefined)?.description || "Contratos"
                          ),
                        ]}
                      />
                    </RePieChart>
                  </ResponsiveContainer>
                </div>
                <ul className="min-w-0 space-y-1.5">
                  {topCpv.map((row: ContratoEsAnalyticsRow, i: number) => (
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
                  <XAxis dataKey="key" stroke="#9aa0aa" tickFormatter={() => "€"} />
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
                    {procedureTypes.map((_: ContratoEsAnalyticsRow, i: number) => (
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
                    {contractTypes.map((_: ContratoEsAnalyticsRow, i: number) => (
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
              <p className="text-sm font-medium px-4 py-3 bg-white/5 text-muted-foreground border-b border-white/5">
                Top entidades
              </p>
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
                    {topEntities.map((e: ContratoEsAnalyticsRow, i: number) => (
                      <tr key={i} className="border-t border-white/5 hover:bg-white/[0.03] transition">
                        <td className="px-4 py-2.5 max-w-[220px] truncate" title={e.description || e.key}>
                          {e.description || e.key}
                        </td>
                        <td className="px-4 py-2.5">{formatNumber(e.count)}</td>
                        <td className="px-4 py-2.5">{formatEuro(e.total_value)}</td>
                      </tr>
                    ))}
                    {topEntities.length === 0 && (
                      <tr>
                        <td colSpan={3} className="px-4 py-8 text-center text-muted-foreground">
                          Sem dados
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
            <div className="overflow-hidden rounded-xl border border-white/5">
              <p className="text-sm font-medium px-4 py-3 bg-white/5 text-muted-foreground border-b border-white/5">
                Top CPV
              </p>
              <div className="overflow-auto max-h-64">
                <table className="w-full text-sm text-left">
                  <thead className="bg-white/[0.03] text-muted-foreground text-xs uppercase tracking-wider">
                    <tr>
                      <th className="px-4 py-2.5">CPV</th>
                      <th className="px-4 py-2.5">Contratos</th>
                      <th className="px-4 py-2.5">Valor total</th>
                    </tr>
                  </thead>
                  <tbody>
                    {topCpv.map((e: ContratoEsAnalyticsRow, i: number) => (
                      <tr key={i} className="border-t border-white/5 hover:bg-white/[0.03] transition">
                        <td className="px-4 py-2.5 max-w-[220px] truncate" title={e.description || e.key}>
                          {e.key}
                        </td>
                        <td className="px-4 py-2.5">{formatNumber(e.count)}</td>
                        <td className="px-4 py-2.5">{formatEuro(e.total_value)}</td>
                      </tr>
                    ))}
                    {topCpv.length === 0 && (
                      <tr>
                        <td colSpan={3} className="px-4 py-8 text-center text-muted-foreground">
                          Sem dados
                        </td>
                      </tr>
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

function XIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M18 6 6 18M6 6l12 12" />
    </svg>
  );
}
