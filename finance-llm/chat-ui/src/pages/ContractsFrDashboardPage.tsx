/**
 * Dashboard de contratos públicos de França (DECP) — `/contratos-fr/dashboard`.
 *
 * Modelado no dashboard de contratos espanhóis, adaptado aos campos franceses:
 * `acheteur_nom`, `adjudicatario_nom`, `procedure`, `nature`, `cpv.nom`, `montant`.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowLeft,
  BarChart3,
  FileText,
  Filter,
  Landmark,
  Loader2,
  MapPin,
  RefreshCw,
  Search,
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
  Legend,
  type PieLabel,
} from "recharts";
import type { Formatter as RechartsFormatter } from "recharts/types/component/DefaultTooltipContent";
import {
  getContratosFrAnalytics,
  getContratosFrStatus,
} from "../contratosFrApi";
import type {
  ContratoFrAnalyticsRequest,
  ContratoFrAnalyticsResponse,
} from "../contratosFrApi";

interface ContractsFrDashboardPageProps {
  onSwitchView: () => void;
  onSwitchSearch?: () => void;
}

const countFormatter: RechartsFormatter = (value) => [
  formatNumber(Number(value)),
  "Contrats",
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

export function ContractsFrDashboardPage({
  onSwitchView,
  onSwitchSearch,
}: ContractsFrDashboardPageProps) {
  const [filters, setFilters] = useState<ContratoFrAnalyticsRequest>({});
  const [q, setQ] = useState("");
  const [ano, setAno] = useState<number | "">("");
  const [acheteurId, setAcheteurId] = useState("");
  const [adjudicatarioId, setAdjudicatarioId] = useState("");
  const [cpvCode, setCpvCode] = useState("");
  const [minValue, setMinValue] = useState("");
  const [maxAmount, setMaxAmount] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [dateField, setDateField] = useState("date_publication");
  const [nature, setNature] = useState("");
  const [procedure, setProcedure] = useState("");
  const [lieuExecutionCode, setLieuExecutionCode] = useState("");
  const [showFilters, setShowFilters] = useState(false);

  const [data, setData] = useState<ContratoFrAnalyticsResponse | null>(null);
  const [years, setYears] = useState<number[]>([]);
  const [status, setStatus] = useState<{ total: number; years: number[] } | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const debouncedFilters = useDebounce(filters, 500);

  useEffect(() => {
    getContratosFrStatus()
      .then((s) => {
        setStatus({ total: s.total, years: s.years ?? [] });
        setYears(s.years ?? []);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Erro ao carregar estado"));
  }, []);

  const buildFilters = (): ContratoFrAnalyticsRequest => {
    const f: ContratoFrAnalyticsRequest = {};
    if (q.trim()) f.q = q.trim();
    if (ano !== "") f.ano = ano;
    if (nature.trim()) f.nature = nature.trim();
    if (procedure.trim()) f.procedure = procedure.trim();
    if (acheteurId.trim()) f.acheteur_id = acheteurId.trim();
    if (cpvCode.trim()) f.cpv_code = cpvCode.trim();
    if (lieuExecutionCode.trim()) f.lieu_execution_code = lieuExecutionCode.trim();
    if (minValue.trim()) f.min_value = Number(minValue);
    if (maxAmount.trim()) f.max_value = Number(maxAmount);
    if (startDate) f.start_date = startDate;
    if (endDate) f.end_date = endDate;
    if (dateField) f.date_field = dateField;
    return f;
  };

  const fetchData = useCallback(
    async (f: ContratoFrAnalyticsRequest) => {
      setLoading(true);
      setError(null);
      try {
        const d = await getContratosFrAnalytics(f);
        setData(d);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Erro ao carregar analytics");
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  useEffect(() => {
    fetchData(debouncedFilters);
  }, [debouncedFilters, fetchData]);

  useEffect(() => {
    setFilters(buildFilters());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    q,
    ano,
    nature,
    procedure,
    acheteurId,
    adjudicatarioId,
    cpvCode,
    lieuExecutionCode,
    minValue,
    maxAmount,
    startDate,
    endDate,
    dateField,
  ]);

  const byYear = useMemo(
    () => (data?.by_year ?? []).map((r) => ({ name: r.key, contrats: r.count, value: r.total_value ?? 0 })),
    [data],
  );
  const byProcedure = useMemo(
    () => (data?.procedures ?? []).slice(0, 8).map((r) => ({ name: r.key, value: r.count })),
    [data],
  );
  const byFormePrix = useMemo(
    () => (data?.formes_prix ?? []).slice(0, 8).map((r) => ({ name: r.key, value: r.count })),
    [data],
  );

  const topCpv = useMemo(
    () => (data?.top_cpv ?? []).slice(0, 10).map((r) => ({ name: r.description ?? r.key, value: r.count })),
    [data],
  );
  const topEntities = useMemo(
    () =>
      (data?.top_entities ?? [])
        .filter((r) => r.key)
        .slice(0, 10)
        .map((r) => ({ name: r.key, value: r.count })),
    [data],
  );

  const localizacaoTypes = useMemo(
    () => (data?.localizacao?.types ?? []).slice(0, 8).map((r) => ({ name: r.key, value: r.count })),
    [data],
  );
  const localizacaoCodes = useMemo(
    () => (data?.localizacao?.codes ?? []).slice(0, 10).map((r) => ({ name: r.key, value: r.count })),
    [data],
  );

  const totalValue = (data?.total_value ?? null) as number | null;
  const avgValue = (data?.avg_value ?? null) as number | null;
  const maxValue = (data?.max_value ?? null) as number | null;

  return (
    <div className="mx-auto max-w-7xl px-4 py-6 md:px-8 fade-in">
      <header className="mb-6 flex flex-col md:flex-row md:items-end md:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-foreground flex items-center gap-2">
            <Landmark size={22} className="text-amber-400" />
            Análise — Contratos França
          </h1>
          <p className="text-sm text-muted-foreground">
            Dashboard dos contratos públicos franceses indexados (DECP)
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            onClick={() => void fetchData(filters)}
            className="px-3 py-2 rounded-xl border border-border hover:bg-white/5 transition text-sm flex items-center gap-2"
          >
            <RefreshCw size={15} /> Atualizar
          </button>
          <button
            onClick={() => setShowFilters((v) => !v)}
            className={`px-3 py-2 rounded-xl border border-border hover:bg-white/5 transition text-sm flex items-center gap-2 ${showFilters ? "bg-white/10" : ""}`}
          >
            <Filter size={15} /> Filtros
          </button>
          {onSwitchSearch && (
            <button
              onClick={onSwitchSearch}
              className="px-3 py-2 rounded-xl bg-primary text-primary-foreground hover:bg-primary/90 transition text-sm flex items-center gap-2"
            >
              <Search size={15} /> Pesquisa
            </button>
          )}
          {onSwitchView && (
            <button
              onClick={onSwitchView}
              className="px-3 py-2 rounded-xl border border-border hover:bg-white/5 transition text-sm flex items-center gap-2"
            >
              <ArrowLeft size={15} /> Fechar
            </button>
          )}
        </div>
      </header>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        <StatCard
          icon={Database}
          label="Contratos indexados"
          value={status ? formatNumber(status.total) : "—"}
          sub={status?.years?.length ? `Anos: ${status.years.slice(0, 8).join(", ")}` : undefined}
          color="text-blue-400"
          glow="glow-blue"
        />
        <StatCard
          icon={Euro}
          label="Valor total"
          value={formatEuro(totalValue)}
          sub={`Média ${formatEuro(avgValue)}`}
          color="text-amber-400"
          glow="glow-amber"
        />
        <StatCard
          icon={TrendingUp}
          label="Maior contrato"
          value={formatEuro(maxValue)}
          color="text-emerald-400"
          glow="glow-teal"
        />
        <StatCard
          icon={FileText}
          label="Procedimentos distintos"
          value={formatNumber((data?.procedures ?? []).length)}
          color="text-violet-400"
          glow="glow-violet"
        />
      </div>

      {showFilters && (
        <div className="glass-card rounded-2xl p-4 mb-6 grid grid-cols-1 md:grid-cols-3 lg:grid-cols-4 gap-3">
          <div>
            <label className="text-xs text-muted-foreground">Texto</label>
            <input
              type="text"
              className="w-full bg-background border border-border rounded-lg px-2 py-1.5 text-sm mt-1"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Objeto, CPV..."
            />
          </div>
          <div>
            <label className="text-xs text-muted-foreground">Ano</label>
            <select
              className="w-full bg-background border border-border rounded-lg px-2 py-1.5 text-sm mt-1"
              value={ano}
              onChange={(e) => setAno(e.target.value === "" ? "" : Number(e.target.value))}
            >
              <option value="">Todos</option>
              {years.map((y) => (
                <option key={y} value={y}>{y}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-xs text-muted-foreground">Natureza</label>
            <input
              type="text"
              className="w-full bg-background border border-border rounded-lg px-2 py-1.5 text-sm mt-1"
              value={nature}
              onChange={(e) => setNature(e.target.value)}
            />
          </div>
          <div>
            <label className="text-xs text-muted-foreground">Procedimento</label>
            <input
              type="text"
              className="w-full bg-background border border-border rounded-lg px-2 py-1.5 text-sm mt-1"
              value={procedure}
              onChange={(e) => setProcedure(e.target.value)}
            />
          </div>
          <div>
            <label className="text-xs text-muted-foreground">ID acheteur</label>
            <input
              type="text"
              className="w-full bg-background border border-border rounded-lg px-2 py-1.5 text-sm mt-1"
              value={acheteurId}
              onChange={(e) => setAcheteurId(e.target.value)}
              placeholder="SIRET/SIREN"
            />
          </div>
          <div>
            <label className="text-xs text-muted-foreground">ID adjudicatário</label>
            <input
              type="text"
              className="w-full bg-background border border-border rounded-lg px-2 py-1.5 text-sm mt-1"
              value={adjudicatarioId}
              onChange={(e) => setAdjudicatarioId(e.target.value)}
              placeholder="SIRET"
            />
          </div>
          <div>
            <label className="text-xs text-muted-foreground">CPV</label>
            <input
              type="text"
              className="w-full bg-background border border-border rounded-lg px-2 py-1.5 text-sm mt-1"
              value={cpvCode}
              onChange={(e) => setCpvCode(e.target.value)}
            />
          </div>
          <div>
            <label className="text-xs text-muted-foreground">Código local</label>
            <input
              type="text"
              className="w-full bg-background border border-border rounded-lg px-2 py-1.5 text-sm mt-1"
              value={lieuExecutionCode}
              onChange={(e) => setLieuExecutionCode(e.target.value)}
            />
          </div>
          <div>
            <label className="text-xs text-muted-foreground">Valor ≥</label>
            <input
              type="number"
              className="w-full bg-background border border-border rounded-lg px-2 py-1.5 text-sm mt-1"
              value={minValue}
              onChange={(e) => setMinValue(e.target.value)}
            />
          </div>
          <div>
            <label className="text-xs text-muted-foreground">Valor ≤</label>
            <input
              type="number"
              className="w-full bg-background border border-border rounded-lg px-2 py-1.5 text-sm mt-1"
              value={maxAmount}
              onChange={(e) => setMaxAmount(e.target.value)}
            />
          </div>
          <div>
            <label className="text-xs text-muted-foreground">Data de</label>
            <input
              type="date"
              className="w-full bg-background border border-border rounded-lg px-2 py-1.5 text-sm mt-1"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
            />
          </div>
          <div>
            <label className="text-xs text-muted-foreground">Data até</label>
            <input
              type="date"
              className="w-full bg-background border border-border rounded-lg px-2 py-1.5 text-sm mt-1"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
            />
          </div>
          <div>
            <label className="text-xs text-muted-foreground">Campo data</label>
            <select
              className="w-full bg-background border border-border rounded-lg px-2 py-1.5 text-sm mt-1"
              value={dateField}
              onChange={(e) => setDateField(e.target.value)}
            >
              <option value="date_publication">Publicação</option>
              <option value="date_notification">Notificação</option>
            </select>
          </div>
        </div>
      )}

      {loading && (
        <div className="flex items-center justify-center py-16">
          <Loader2 size={32} className="animate-spin text-primary" />
        </div>
      )}

      {error && (
        <div className="glass-card rounded-2xl p-4 mb-4 border-red-400/30 text-sm text-red-300">
          {error}
        </div>
      )}

      {!loading && data && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="glass-card rounded-2xl p-5">
            <h3 className="text-sm font-semibold mb-4 flex items-center gap-2">
              <TrendingUp size={16} /> Contratos por ano
            </h3>
            <div className="h-72">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={byYear}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                  <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => formatNumber(v)} />
                  <Tooltip formatter={countFormatter} />
                  <Bar dataKey="contrats" fill="#3b82f6" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="glass-card rounded-2xl p-5">
            <h3 className="text-sm font-semibold mb-4 flex items-center gap-2">
              <PieChart size={16} /> Procedimentos
            </h3>
            <div className="h-72">
              <ResponsiveContainer width="100%" height="100%">
                <RePieChart>
                  <Pie
                    data={byProcedure}
                    dataKey="value"
                    nameKey="name"
                    innerRadius={60}
                    outerRadius={100}
                    paddingAngle={2}
                    label={insidePercentLabel}
                  >
                    {byProcedure.map((_, i) => (
                      <Cell key={`cell-${i}`} fill={COLORS[i % COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip formatter={countFormatter} />
                  <Legend verticalAlign="bottom" height={24} />
                </RePieChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="glass-card rounded-2xl p-5">
            <h3 className="text-sm font-semibold mb-4 flex items-center gap-2">
              <Activity size={16} /> Forma de preço
            </h3>
            <div className="h-72">
              <ResponsiveContainer width="100%" height="100%">
                <RePieChart>
                  <Pie
                    data={byFormePrix}
                    dataKey="value"
                    nameKey="name"
                    outerRadius={100}
                    label={percentPieLabel}
                  >
                    {byFormePrix.map((_, i) => (
                      <Cell key={`cell-fp-${i}`} fill={COLORS[i % COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip formatter={countFormatter} />
                  <Legend verticalAlign="bottom" height={24} />
                </RePieChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="glass-card rounded-2xl p-5">
            <h3 className="text-sm font-semibold mb-4 flex items-center gap-2">
              <BarChart3 size={16} /> Top CPV
            </h3>
            <div className="h-72">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={topCpv} layout="vertical">
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                  <XAxis type="number" tick={{ fontSize: 11 }} />
                  <YAxis type="category" dataKey="name" width={160} tick={{ fontSize: 10 }} interval={0} />
                  <Tooltip formatter={countFormatter} />
                  <Bar dataKey="value" fill="#10a37f" radius={[0, 4, 4, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          {topEntities.length > 0 && (
            <div className="glass-card rounded-2xl p-5">
              <h3 className="text-sm font-semibold mb-4 flex items-center gap-2">
                <BarChart3 size={16} /> Top entidades
              </h3>
              <div className="h-72">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={topEntities}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                    <XAxis dataKey="name" tick={{ fontSize: 11 }} angle={-30} textAnchor="end" height={60} />
                    <YAxis tick={{ fontSize: 11 }} />
                    <Tooltip formatter={countFormatter} />
                    <Bar dataKey="value" fill="#8b5cf6" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}

          {localizacaoTypes.length > 0 && (
            <div className="glass-card rounded-2xl p-5">
              <h3 className="text-sm font-semibold mb-4 flex items-center gap-2">
                <MapPin size={16} /> Tipos de localização
              </h3>
              <div className="h-72">
                <ResponsiveContainer width="100%" height="100%">
                  <RePieChart>
                    <Pie
                      data={localizacaoTypes}
                      dataKey="value"
                      nameKey="name"
                      outerRadius={100}
                      label={percentPieLabel}
                    >
                      {localizacaoTypes.map((_, i) => (
                        <Cell key={`cell-loc-${i}`} fill={COLORS[i % COLORS.length]} />
                      ))}
                    </Pie>
                    <Tooltip formatter={countFormatter} />
                    <Legend verticalAlign="bottom" height={24} />
                  </RePieChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}

          {localizacaoCodes.length > 0 && (
            <div className="glass-card rounded-2xl p-5">
              <h3 className="text-sm font-semibold mb-4 flex items-center gap-2">
                <MapPin size={16} /> Códigos de execução
              </h3>
              <div className="h-72">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={localizacaoCodes} layout="vertical">
                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                    <XAxis type="number" tick={{ fontSize: 11 }} />
                    <YAxis type="category" dataKey="name" width={120} tick={{ fontSize: 10 }} interval={0} />
                    <Tooltip formatter={countFormatter} />
                    <Bar dataKey="value" fill="#06b6d4" radius={[0, 4, 4, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
