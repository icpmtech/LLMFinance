import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowLeft, FileText, TrendingUp, BarChart3, PieChart, Activity, Euro, Database, RefreshCw, Filter, Download, FileSpreadsheet, Sparkles, LayoutGrid, Plus, Save, Bookmark, FolderOpen, Loader2, Trash2, X, Printer, TriangleAlert } from "lucide-react";
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
import { FieldPanel } from "../components/visualizador/FieldPanel";
import { VisualCard } from "../components/visualizador/VisualCard";
import { formatCell } from "../components/visualizador/VisualChart";
import { exportDashboardCsv, printVisualizador } from "../visualizadorExport";
import {
  deleteVisualizadorDashboard,
  duplicateVisualizadorDashboard,
  getVisualizadorDashboard,
  getVisualizadorDataset,
  getVisualizadorMeta,
  getVisualRecords,
  listVisualizadorDashboards,
  saveVisualizadorDashboard,
  type DashboardList,
  type DatasetDetail,
  type QueryRow,
  type VisualConfig,
  type VisualSuggestion,
  type VisualizadorMeta,
} from "../visualizadorApi";

interface ContractsDashboardPageProps {
  onSwitchView: () => void;
  onSwitchSearch?: () => void;
}

/** Larguras de grelha disponíveis para os visuais dinâmicos. */
const WIDTH_OPTIONS = [
  { id: 12, label: "1/1", className: "lg:col-span-12" },
  { id: 8, label: "2/3", className: "lg:col-span-8" },
  { id: 6, label: "1/2", className: "lg:col-span-6" },
  { id: 4, label: "1/3", className: "lg:col-span-4" },
];

function spanClass(width: number): string {
  return (WIDTH_OPTIONS.find((option) => option.id === width) ?? WIDTH_OPTIONS[2]).className;
}

/** Quantas dimensões o tipo de gráfico usa. */
function dimensionSlots(chart: string): number {
  if (chart === "kpi") return 0;
  if (chart === "stacked" || chart === "matrix" || chart === "treemap") return 2;
  return 1;
}

/** Cria um visual por omissão para o dataset corrente. */
function newVisual(detail: DatasetDetail | null, title?: string): VisualConfig {
  const defaults = detail?.defaults ?? {};
  const dimensionId = defaults.dimension ?? detail?.dimensions[0]?.id ?? "";
  const dimension = detail?.dimensions.find((entry) => entry.id === dimensionId);
  const catalog = detail?.measures ?? [];
  const measureId = defaults.measure
    || catalog.find((measure) => measure.kind === "soma")?.id
    || catalog[0]?.id
    || "contagem";
  return {
    id: `v${Date.now().toString(36)}${Math.floor(Math.random() * 1000)}`,
    title: title || "Novo visual",
    chart: "bar",
    dimensions: dimensionId ? [{ id: dimensionId, interval: dimension?.type === "date" ? defaults.dimension_interval || "ano" : undefined }] : [],
    measures: [measureId],
    formulas: [],
    limit: 25,
    top_n: 0,
    others: false,
    sort: { by: "", order: "desc" },
    width: 6,
  };
}

/** Templates pré-configurados para o dataset de contratos (campos alinhados com a ontologia do Visualizador). */
const CONTRACTS_TEMPLATES: { id: string; label: string; description: string; visuals: Omit<VisualConfig, "id">[] }[] = [
  {
    id: "executive",
    label: "Visão executiva",
    description: "KPIs principais, evolução anual e top entidades/CPV.",
    visuals: [
      { title: "Total de contratos", chart: "kpi", dimensions: [], measures: ["contagem"], formulas: [], limit: 25, top_n: 0, others: false, sort: { by: "", order: "desc" }, width: 4 },
      { title: "Valor total adjudicado", chart: "kpi", dimensions: [], measures: ["soma_preco"], formulas: [], limit: 25, top_n: 0, others: false, sort: { by: "", order: "desc" }, width: 4 },
      { title: "Valor médio por contrato", chart: "kpi", dimensions: [], measures: ["media_preco"], formulas: [], limit: 25, top_n: 0, others: false, sort: { by: "", order: "desc" }, width: 4 },
      { title: "Contratos por ano", chart: "bar", dimensions: [{ id: "ano", interval: "ano" }], measures: ["contagem"], formulas: [], limit: 25, top_n: 0, others: false, sort: { by: "", order: "desc" }, width: 6 },
      { title: "Evolução por ano", chart: "area", dimensions: [{ id: "ano", interval: "ano" }], measures: ["soma_preco"], formulas: [], limit: 25, top_n: 0, others: false, sort: { by: "", order: "desc" }, width: 6 },
      { title: "Maiores adjudicatários", chart: "bar-h", dimensions: [{ id: "adjudicatario" }], measures: ["contagem", "soma_preco"], formulas: [], limit: 10, top_n: 10, others: true, sort: { by: "", order: "desc" }, width: 6 },
      { title: "Tipo de contrato", chart: "donut", dimensions: [{ id: "tipo_contrato" }], measures: ["contagem"], formulas: [], limit: 8, top_n: 8, others: true, sort: { by: "", order: "desc" }, width: 3 },
      { title: "Tipo de procedimento", chart: "donut", dimensions: [{ id: "procedimento" }], measures: ["contagem"], formulas: [], limit: 8, top_n: 8, others: true, sort: { by: "", order: "desc" }, width: 3 },
    ],
  },
  {
    id: "timeline",
    label: "Evolução temporal",
    description: "Tendências ao longo do tempo por mês, trimestre e ano.",
    visuals: [
      { title: "Contratos por mês", chart: "line", dimensions: [{ id: "data", interval: "mes" }], measures: ["contagem"], formulas: [], limit: 50, top_n: 0, others: false, sort: { by: "", order: "desc" }, width: 12 },
      { title: "Valor por mês", chart: "area", dimensions: [{ id: "data", interval: "mes" }], measures: ["soma_preco"], formulas: [], limit: 50, top_n: 0, others: false, sort: { by: "", order: "desc" }, width: 12 },
      { title: "Contratos por trimestre", chart: "bar", dimensions: [{ id: "data", interval: "trimestre" }], measures: ["contagem"], formulas: [], limit: 40, top_n: 0, others: false, sort: { by: "", order: "desc" }, width: 6 },
      { title: "Contratos por ano", chart: "bar", dimensions: [{ id: "ano", interval: "ano" }], measures: ["contagem"], formulas: [], limit: 25, top_n: 0, others: false, sort: { by: "", order: "desc" }, width: 6 },
    ],
  },
  {
    id: "entities",
    label: "Entidades",
    description: "Análise das entidades adjudicantes e adjudicatárias.",
    visuals: [
      { title: "Maiores adjudicantes", chart: "bar-h", dimensions: [{ id: "adjudicante" }], measures: ["contagem"], formulas: [], limit: 10, top_n: 10, others: true, sort: { by: "", order: "desc" }, width: 6 },
      { title: "Maiores adjudicatárias", chart: "bar-h", dimensions: [{ id: "adjudicatario" }], measures: ["contagem"], formulas: [], limit: 10, top_n: 10, others: true, sort: { by: "", order: "desc" }, width: 6 },
      { title: "Adjudicatárias por valor", chart: "bar-h", dimensions: [{ id: "adjudicatario" }], measures: ["soma_preco"], formulas: [], limit: 10, top_n: 10, others: true, sort: { by: "", order: "desc" }, width: 12 },
    ],
  },
  {
    id: "cpv",
    label: "CPV e categorias",
    description: "Distribuição por códigos CPV e descrições.",
    visuals: [
      { title: "Top CPV por contratos", chart: "bar-h", dimensions: [{ id: "cpv" }], measures: ["contagem"], formulas: [], limit: 10, top_n: 10, others: true, sort: { by: "", order: "desc" }, width: 6 },
      { title: "Top CPV por valor", chart: "bar-h", dimensions: [{ id: "cpv" }], measures: ["valor"], formulas: [], limit: 10, top_n: 10, others: true, sort: { by: "", order: "desc" }, width: 6 },
      { title: "Evolução CPV por ano", chart: "line", dimensions: [{ id: "ano", interval: "ano" }], measures: ["valor"], formulas: [], limit: 25, top_n: 0, others: false, sort: { by: "", order: "desc" }, width: 12 },
    ],
  },
];

function makeTemplateVisuals(templates: Omit<VisualConfig, "id">[]): VisualConfig[] {
  return templates.map((template) => ({ ...template, id: `v${Date.now().toString(36)}${Math.floor(Math.random() * 1000)}${Math.random().toString(36).slice(2, 5)}` }));
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

  // ---------------------------------------------------------------------------
  // Modo dinâmico — Visualizador embutido para contratos
  // ---------------------------------------------------------------------------
  const [dynamicMode, setDynamicMode] = useState(false);
  const [meta, setMeta] = useState<VisualizadorMeta | null>(null);
  const [metaError, setMetaError] = useState<string | null>(null);
  const [datasetId, setDatasetId] = useState<string>("contrato");
  const [detail, setDetail] = useState<DatasetDetail | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [workspace, setWorkspace] = useState<{
    name: string;
    dashboardId: string | null;
    dataset: string;
    filters: Record<string, unknown>;
    search: string;
    visuals: VisualConfig[];
  }>({ name: "Dashboard de contratos", dashboardId: null, dataset: "contrato", filters: {}, search: "", visuals: [] });
  const [activeVisualId, setActiveVisualId] = useState<string | null>(null);
  const [dashboards, setDashboards] = useState<DashboardList | null>(null);
  const [showDashboards, setShowDashboards] = useState(false);
  const [showTemplates, setShowTemplates] = useState(false);
  const [dynamicStatus, setDynamicStatus] = useState<{ kind: "ok" | "error"; message: string } | null>(null);
  const [saving, setSaving] = useState(false);
  const [drill, setDrill] = useState<{ title: string; rows: QueryRow[]; loading: boolean; error?: string | null } | null>(null);

  useEffect(() => {
    if (!dynamicMode) return;
    let cancelled = false;
    getVisualizadorMeta()
      .then((response) => {
        if (cancelled) return;
        setMeta(response);
        if (!response.datasets.some((dataset) => dataset.id === datasetId)) {
          const first = response.datasets.find((dataset) => dataset.available);
          if (first) setDatasetId(first.id);
        }
      })
      .catch((error) => {
        if (!cancelled) setMetaError(error instanceof Error ? error.message : "Não foi possível carregar o catálogo.");
      });
    return () => { cancelled = true; };
  }, [dynamicMode]);

  useEffect(() => {
    if (!dynamicMode) return;
    let cancelled = false;
    setLoadingDetail(true);
    getVisualizadorDataset(datasetId)
      .then((response) => {
        if (cancelled) return;
        setDetail(response);
      })
      .catch((error) => {
        if (cancelled) return;
        setDetail(null);
        setMetaError(error instanceof Error ? error.message : "Não foi possível abrir o dataset.");
      })
      .finally(() => {
        if (!cancelled) setLoadingDetail(false);
      });
    return () => { cancelled = true; };
  }, [dynamicMode, datasetId]);

  useEffect(() => {
    if (!dynamicMode || !detail) return;
    if (workspace.visuals.length > 0) return;
    const visual = newVisual(detail);
    setWorkspace((current) => ({ ...current, visuals: [visual] }));
  }, [dynamicMode, detail, workspace.visuals.length]);

  const activeVisual = useMemo(
    () => workspace.visuals.find((visual) => visual.id === activeVisualId) ?? workspace.visuals[0] ?? null,
    [workspace.visuals, activeVisualId],
  );

  const patchWorkspace = useCallback((patch: Partial<typeof workspace>) => {
    setWorkspace((current) => ({ ...current, ...patch }));
  }, []);

  const updateVisual = useCallback((id: string, patch: Partial<VisualConfig>) => {
    setWorkspace((current) => ({
      ...current,
      visuals: current.visuals.map((visual) => (visual.id === id ? { ...visual, ...patch } : visual)),
    }));
  }, []);

  const addVisual = useCallback(() => {
    if (!detail) return;
    const visual = newVisual(detail);
    setWorkspace((current) => ({ ...current, visuals: [...current.visuals, visual] }));
    setActiveVisualId(visual.id);
  }, [detail]);

  const removeVisual = useCallback((id: string) => {
    setWorkspace((current) => ({ ...current, visuals: current.visuals.filter((visual) => visual.id !== id) }));
  }, []);

  const duplicateVisual = useCallback((id: string) => {
    setWorkspace((current) => {
      const source = current.visuals.find((visual) => visual.id === id);
      if (!source) return current;
      const copy: VisualConfig = { ...source, id: `v${Date.now().toString(36)}`, title: `${source.title} (cópia)` };
      return { ...current, visuals: [...current.visuals, copy] };
    });
  }, []);

  const addField = useCallback(
    (kind: "dimension" | "measure", fieldId: string) => {
      if (!detail) return;
      const target = activeVisual;
      if (!target) {
        const visual = newVisual(detail);
        visual.dimensions = kind === "dimension"
          ? [{ id: fieldId, interval: detail.dimensions.find((entry) => entry.id === fieldId)?.type === "date" ? "mes" : undefined }]
          : [];
        visual.measures = kind === "measure" ? [fieldId] : ["contagem"];
        setWorkspace((current) => ({ ...current, visuals: [...current.visuals, visual] }));
        setActiveVisualId(visual.id);
        return;
      }
      if (kind === "measure") {
        if (target.measures.some((spec) => (typeof spec === "string" ? spec : spec.id) === fieldId)) return;
        updateVisual(target.id, { measures: [...target.measures, { id: fieldId }] });
        return;
      }
      const dimension = detail.dimensions.find((entry) => entry.id === fieldId);
      const slots = Math.max(1, dimensionSlots(target.chart));
      const dimensions = [...target.dimensions];
      const emptySlot = dimensions.findIndex((entry) => !entry.id);
      const position = emptySlot >= 0 ? emptySlot : dimensions.length;
      const entry = { id: fieldId, interval: dimension?.type === "date" ? "mes" : undefined };
      if (position < slots) dimensions[position] = entry;
      else if (dimensions.length < 3) dimensions.push(entry);
      else dimensions[slots - 1] = entry;
      const chart = target.chart === "kpi" ? "bar" : target.chart;
      updateVisual(target.id, { dimensions, chart });
    },
    [activeVisual, detail, updateVisual],
  );

  const applySuggestion = useCallback(
    (suggestion: VisualSuggestion) => {
      if (!detail) return;
      const visual: VisualConfig = {
        ...newVisual(detail, suggestion.title),
        chart: suggestion.chart,
        dimensions: [{ id: suggestion.dimension, interval: suggestion.interval || undefined }],
        measures: [suggestion.measure],
        top_n: suggestion.chart === "bar-h" ? 10 : 0,
        others: false,
      };
      setWorkspace((current) => ({ ...current, visuals: [...current.visuals, visual] }));
      setActiveVisualId(visual.id);
    },
    [detail],
  );

  const applyTemplate = useCallback(
    (templateId: string) => {
      if (!detail) return;
      const template = CONTRACTS_TEMPLATES.find((t) => t.id === templateId);
      if (!template) return;
      const visuals = makeTemplateVisuals(template.visuals);
      setWorkspace((current) => ({
        ...current,
        name: `${template.label} — ${current.name || "Dashboard de contratos"}`,
        dataset: detail.dataset.id,
        visuals,
      }));
      setActiveVisualId(visuals[0]?.id ?? null);
      setShowTemplates(false);
      setDynamicStatus({ kind: "ok", message: `Template «${template.label}» aplicado com ${visuals.length} visuais.` });
    },
    [detail],
  );

  const openDrill = useCallback(
    async (row: QueryRow, visual: VisualConfig) => {
      if (!detail) return;
      const extra: Record<string, unknown> = {};
      for (const dimension of visual.dimensions) {
        if (!dimension.id) continue;
        const value = row[dimension.id];
        if (value === null || value === undefined || value === "" || value === "Outros") continue;
        if (row._key === "__outros__") continue;
        extra[dimension.id] = value;
      }
      setDrill({ title: `${visual.title} — registos`, rows: [], loading: true, error: null });
      try {
        const records = await getVisualRecords({
          dataset: detail.dataset.id,
          filters: { ...workspace.filters, ...extra },
          search: workspace.search || null,
          size: 40,
        });
        setDrill({ title: `${visual.title} — ${records.total.toLocaleString("pt-PT")} registos`, rows: records.items as QueryRow[], loading: false, error: records.error ?? null });
      } catch (error) {
        setDrill({ title: `${visual.title} — registos`, rows: [], loading: false, error: error instanceof Error ? error.message : "Não foi possível abrir os registos." });
      }
    },
    [detail, workspace.filters, workspace.search],
  );

  const refreshDashboards = useCallback(async () => {
    try {
      setDashboards(await listVisualizadorDashboards());
    } catch (error) {
      setDynamicStatus({ kind: "error", message: error instanceof Error ? error.message : "Não foi possível listar os dashboards." });
    }
  }, []);

  useEffect(() => {
    if (dynamicMode && showDashboards) void refreshDashboards();
  }, [dynamicMode, showDashboards, refreshDashboards]);

  const saveDashboard = useCallback(async () => {
    if (!detail) return;
    setSaving(true);
    setDynamicStatus(null);
    try {
      const tags = new Set(["contracts-dashboard", ...(detail.dataset.id === "contrato" ? [] : [detail.dataset.id])]);
      const saved = await saveVisualizadorDashboard({
        id: workspace.dashboardId ?? undefined,
        name: workspace.name,
        dataset: detail.dataset.id,
        filters: workspace.filters,
        visuals: workspace.visuals,
        description: `${detail.dataset.label} · ${workspace.visuals.length} visual(is)`,
        tags: Array.from(tags),
      });
      patchWorkspace({ dashboardId: saved.id, name: saved.name });
      setDynamicStatus({ kind: "ok", message: `Dashboard «${saved.name}» guardado.` });
      void refreshDashboards();
    } catch (error) {
      setDynamicStatus({ kind: "error", message: error instanceof Error ? error.message : "Não foi possível guardar." });
    } finally {
      setSaving(false);
    }
  }, [detail, workspace, patchWorkspace, refreshDashboards]);

  const openDashboard = useCallback(async (id: string) => {
    try {
      const dashboard = await getVisualizadorDashboard(id);
      if (dashboard.dataset) setDatasetId(dashboard.dataset);
      setWorkspace({
        name: dashboard.name,
        dashboardId: dashboard.id ?? null,
        dataset: dashboard.dataset ?? datasetId,
        filters: dashboard.filters ?? {},
        search: "",
        visuals: dashboard.visuals ?? [],
      });
      setShowDashboards(false);
      setDynamicStatus({ kind: "ok", message: `Dashboard «${dashboard.name}» aberto.` });
    } catch (error) {
      setDynamicStatus({ kind: "error", message: error instanceof Error ? error.message : "Não foi possível abrir o dashboard." });
    }
  }, [datasetId]);

  const exportAllCsv = useCallback(async () => {
    if (!detail || workspace.visuals.length === 0) return;
    try {
      const exported = await exportDashboardCsv(workspace.name, workspace.visuals, detail.dataset.id, workspace.filters, workspace.search);
      setDynamicStatus({
        kind: exported > 0 ? "ok" : "error",
        message: exported > 0 ? `${exported} visual(is) exportado(s) em CSV.` : "Não foi possível exportar: os visuais não devolveram dados.",
      });
    } catch (error) {
      setDynamicStatus({ kind: "error", message: error instanceof Error ? error.message : "A exportação falhou." });
    }
  }, [detail, workspace.visuals, workspace.filters, workspace.search, workspace.name]);

  const chartTypes = meta?.chart_types ?? [];

  // --- Render helpers do modo dinâmico --------------------------------------
  const dynamicBodyElement = (
    <div className="visualizador-root min-h-screen w-full bg-background text-foreground orbit-bg">
      <style>{`
@media print {
  body.visualizador-printing { background: #ffffff !important; }
  body.visualizador-printing .visualizador-root { background: #ffffff !important; color: #111827 !important; }
  body.visualizador-printing .visualizador-noprint { display: none !important; }
  body.visualizador-printing .glass-card,
  body.visualizador-printing .glass-panel,
  body.visualizador-printing .glass-modal {
    background: #ffffff !important; backdrop-filter: none !important; box-shadow: none !important;
    border: 1px solid #d1d5db !important;
  }
  body.visualizador-printing .gradient-border::before { display: none !important; }
  body.visualizador-printing .text-muted-foreground { color: #4b5563 !important; }
  body.visualizador-printing .orbit-bg::before { display: none !important; }
  body.visualizador-printing .fade-in { animation: none !important; }
  body.visualizador-printing .visualizador-grid > * { break-inside: avoid; page-break-inside: avoid; }
}
      `}</style>

      <div className="max-w-[1700px] mx-auto px-4 sm:px-6 py-8">
        <div className="flex flex-col lg:flex-row lg:items-end lg:justify-between gap-4 mb-6">
          <div>
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full glass-card text-xs text-teal-300 mb-3">
              <LayoutGrid size={14} /> {meta ? `${meta.datasets.length} datasets · ${meta.datasets.filter((item) => item.aggregation).length} analisáveis` : "a carregar catálogo…"}
            </div>
            <h1 className="text-3xl md:text-4xl font-bold flex items-center gap-3">
              <span className="p-2 rounded-2xl bg-gradient-to-br from-teal-500/25 to-blue-500/20 border border-white/10">
                <BarChart3 size={30} className="text-teal-300" />
              </span>
              Dashboard dinâmico de contratos
            </h1>
            <p className="text-muted-foreground mt-2 max-w-2xl">
              Escolha dimensões e medidas do catálogo de contratos, construa visuais, filtre os dados e guarde dashboards personalizados.
            </p>
          </div>

          <div className="visualizador-noprint flex flex-wrap items-center gap-2">
            <input
              value={workspace.name}
              onChange={(event) => patchWorkspace({ name: event.target.value })}
              aria-label="Nome do dashboard"
              className="px-3 py-2 rounded-xl glass-card text-sm w-56"
              placeholder="Nome do dashboard"
            />
            <button type="button" onClick={saveDashboard} disabled={saving}
                    className="flex items-center gap-1.5 px-3 py-2 rounded-xl glass-card text-sm hover:bg-white/5 disabled:opacity-50">
              {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />} Guardar
            </button>
            <button type="button" onClick={() => setShowDashboards((value) => !value)}
                    className={["flex items-center gap-1.5 px-3 py-2 rounded-xl text-sm", showDashboards ? "glass-card bg-primary/10 text-primary" : "glass-card hover:bg-white/5"].join(" ")}>
              <Bookmark size={14} /> Guardados
            </button>
            <button type="button" onClick={addVisual} disabled={!detail}
                    className="flex items-center gap-1.5 px-3 py-2 rounded-xl glass-card text-sm hover:bg-white/5 disabled:opacity-50"
                    title="Adicionar um visual em branco">
              <Plus size={14} /> Novo visual
            </button>
            <button type="button" onClick={() => setShowTemplates((v) => !v)}
                    className={["flex items-center gap-1.5 px-3 py-2 rounded-xl text-sm", showTemplates ? "glass-card bg-primary/10 text-primary" : "glass-card hover:bg-white/5"].join(" ")}
                    title="Escolher um template pré-configurado">
              <LayoutGrid size={14} /> Templates
            </button>
            <button type="button" onClick={printVisualizador}
                    className="flex items-center gap-1.5 px-3 py-2 rounded-xl glass-card text-sm hover:bg-white/5">
              <Printer size={14} /> PDF
            </button>
            <button type="button" onClick={exportAllCsv} disabled={workspace.visuals.length === 0}
                    className="flex items-center gap-1.5 px-3 py-2 rounded-xl glass-card text-sm hover:bg-white/5 disabled:opacity-50">
              <FolderOpen size={14} /> CSV dos visuais
            </button>
            <button type="button" onClick={() => setDynamicMode(false)}
                    className="flex items-center gap-1.5 px-3 py-2 rounded-xl glass-card text-sm hover:bg-white/5">
              <X size={14} /> Sair
            </button>
          </div>
        </div>

        {(metaError || dynamicStatus) && (
          <div className={["mb-5 p-3 rounded-2xl flex items-center gap-2 text-sm",
            (dynamicStatus?.kind === "error" || metaError) ? "bg-rose-500/10 border border-rose-500/20 text-rose-300" : "bg-teal-500/10 border border-teal-500/20 text-teal-200"].join(" ")}>
            {(dynamicStatus?.kind === "error" || metaError) ? <TriangleAlert size={16} /> : <BarChart3 size={16} />}
            <span className="flex-1">{metaError ?? dynamicStatus?.message}</span>
            <button type="button" onClick={() => { setMetaError(null); setDynamicStatus(null); }} aria-label="Fechar aviso"
                    className="visualizador-noprint text-xs opacity-70 hover:opacity-100"><X size={13} /></button>
          </div>
        )}

        {showTemplates && (
          <section className="visualizador-noprint glass-card gradient-border rounded-2xl p-4 mb-5">
            <div className="flex items-center justify-between gap-3 mb-3">
              <h2 className="text-sm font-semibold flex items-center gap-2"><LayoutGrid size={15} /> Templates</h2>
              <button type="button" onClick={() => setShowTemplates(false)} className="text-[11px] text-muted-foreground hover:text-foreground">Fechar</button>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3">
              {CONTRACTS_TEMPLATES.map((template) => (
                <div key={template.id} className="glass-card rounded-xl p-3 flex flex-col gap-2 hover:bg-white/[0.03] transition">
                  <div className="min-w-0">
                    <p className="text-sm font-medium truncate">{template.label}</p>
                    <p className="text-[11px] text-muted-foreground">{template.description}</p>
                    <p className="text-[10px] text-teal-300 mt-1">{template.visuals.length} visual(is)</p>
                  </div>
                  <button
                    type="button"
                    onClick={() => applyTemplate(template.id)}
                    disabled={!detail}
                    className="mt-auto px-2 py-1.5 rounded-lg glass-card text-[11px] hover:bg-white/5 disabled:opacity-50"
                  >
                    Aplicar template
                  </button>
                </div>
              ))}
            </div>
          </section>
        )}

        {showDashboards && (
          <section className="visualizador-noprint glass-card gradient-border rounded-2xl p-4 mb-5">
            <div className="flex items-center justify-between gap-3 mb-3">
              <h2 className="text-sm font-semibold flex items-center gap-2"><FolderOpen size={15} /> Dashboards guardados</h2>
              {dashboards?.stats && (
                <span className="text-[11px] text-muted-foreground">
                  {dashboards.stats.dashboards} dashboard(s) · {dashboards.stats.visuals} visual(is)
                </span>
              )}
            </div>
            {dashboards?.note && <p className="text-xs text-amber-300">{dashboards.note}</p>}
            {dashboards && dashboards.items.length === 0 && !dashboards.note && (
              <p className="text-xs text-muted-foreground">Ainda não há dashboards guardados. Configure os visuais e clique em «Guardar».</p>
            )}
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-2">
              {(dashboards?.items ?? []).map((item) => (
                <div key={item.id} className="glass-card rounded-xl p-3 flex flex-col gap-2">
                  <div className="min-w-0">
                    <p className="text-sm font-medium truncate">{item.name}</p>
                    <p className="text-[11px] text-muted-foreground truncate">
                      {item.dataset ?? "—"} · {item.visuals} visual(is) · {item.tags.join(", ")}
                    </p>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <button type="button" onClick={() => void openDashboard(item.id)}
                            className="px-2 py-1 rounded-lg glass-card text-[11px] hover:bg-white/5">Abrir</button>
                    <button type="button" onClick={async () => {
                      try {
                        await duplicateVisualizadorDashboard(item.id);
                        void refreshDashboards();
                      } catch (error) {
                        setDynamicStatus({ kind: "error", message: error instanceof Error ? error.message : "Não foi possível duplicar." });
                      }
                    }} className="px-2 py-1 rounded-lg glass-card text-[11px] hover:bg-white/5">Duplicar</button>
                    {item.mine && (
                      <button type="button" onClick={async () => {
                        try {
                          await deleteVisualizadorDashboard(item.id);
                          if (workspace.dashboardId === item.id) patchWorkspace({ dashboardId: null });
                          void refreshDashboards();
                        } catch (error) {
                          setDynamicStatus({ kind: "error", message: error instanceof Error ? error.message : "Não foi possível remover." });
                        }
                      }} className="p-1 rounded-lg glass-card text-muted-foreground hover:text-rose-300" aria-label="Remover dashboard">
                        <Trash2 size={12} />
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}

        <div className="grid grid-cols-1 xl:grid-cols-[330px_minmax(0,1fr)] gap-6">
          <div className="visualizador-noprint">
            <FieldPanel
              meta={meta}
              detail={detail}
              datasetId={datasetId}
              onSelectDataset={setDatasetId}
              filters={workspace.filters}
              onFiltersChange={(filters) => patchWorkspace({ filters })}
              search={workspace.search}
              onSearchChange={(search) => patchWorkspace({ search })}
              onAddField={addField}
              onApplySuggestion={applySuggestion}
              onNewVisual={addVisual}
            />
          </div>

          <main className="space-y-4">
            {loadingDetail && !detail && (
              <div className="flex justify-center py-16"><Loader2 size={26} className="animate-spin text-teal-400" /></div>
            )}

            {detail && !detail.dataset.aggregation && (
              <div className="glass-card gradient-border rounded-2xl p-5 text-sm text-amber-300 flex items-start gap-2">
                <TriangleAlert size={16} className="mt-0.5" />
                <div>
                  <p className="font-semibold">Este dataset não suporta agregações.</p>
                  <p className="text-muted-foreground text-xs mt-1">
                    {(detail.dataset.notes ?? [])[0] ?? "É um dataset resolvido em memória a partir de várias fontes: os totais não seriam exatos."}
                  </p>
                </div>
              </div>
            )}

            {detail && workspace.visuals.length > 0 && (
              <div className="visualizador-noprint flex items-center gap-2 flex-wrap text-xs text-muted-foreground">
                <span>Visual ativo: <strong className="text-foreground">{activeVisual?.title ?? "—"}</strong></span>
                <span className="mx-1">·</span>
                <span>Largura</span>
                {WIDTH_OPTIONS.map((option) => (
                  <button key={option.id} type="button"
                          onClick={() => activeVisual && updateVisual(activeVisual.id, { width: option.id })}
                          className={["px-2 py-0.5 rounded-lg glass-card", activeVisual?.width === option.id ? "text-primary bg-primary/10" : "hover:bg-white/5"].join(" ")}>
                    {option.label}
                  </button>
                ))}
                {!activeVisual?.measures.length && <span className="text-amber-300">· sem medidas</span>}
              </div>
            )}

            <div className="visualizador-grid grid grid-cols-1 lg:grid-cols-12 gap-4">
              {detail && workspace.visuals.map((visual) => (
                <div key={visual.id} className={spanClass(visual.width)}>
                  <VisualCard
                    config={visual}
                    dataset={detail}
                    chartTypes={chartTypes}
                    filters={workspace.filters}
                    search={workspace.search}
                    active={activeVisual?.id === visual.id}
                    onActivate={() => setActiveVisualId(visual.id)}
                    onChange={(patch) => updateVisual(visual.id, patch)}
                    onRemove={() => removeVisual(visual.id)}
                    onDuplicate={() => duplicateVisual(visual.id)}
                    onDrill={(row) => void openDrill(row, visual)}
                  />
                </div>
              ))}
            </div>

            {detail && workspace.visuals.length === 0 && (
              <div className="glass-card gradient-border rounded-2xl p-8 text-center space-y-3">
                <BarChart3 size={28} className="mx-auto text-teal-400" />
                <p className="text-sm text-muted-foreground">
                  Ainda não há visuais. Clique em «Novo visual», numa sugestão do painel esquerdo, ou diretamente numa dimensão/medida para começar.
                </p>
                <button type="button" onClick={addVisual}
                        className="px-4 py-2 rounded-xl glass-card text-sm hover:bg-white/5 inline-flex items-center gap-1.5">
                  <Plus size={14} /> Criar o primeiro visual
                </button>
              </div>
            )}
          </main>
        </div>
      </div>

      {drill && (
        <div className="visualizador-noprint fixed inset-0 z-50 bg-black/50 backdrop-blur-sm flex items-center justify-center p-4"
             onClick={() => setDrill(null)} role="dialog" aria-modal="true">
          <div className="glass-modal rounded-2xl border border-white/10 w-full max-w-6xl max-h-[85vh] flex flex-col"
               onClick={(event) => event.stopPropagation()}>
            <div className="flex items-center justify-between gap-3 p-4 border-b border-white/10">
              <h3 className="text-sm font-semibold truncate">{drill.title}</h3>
              <button type="button" onClick={() => setDrill(null)} aria-label="Fechar"
                      className="p-1.5 rounded-lg glass-card text-muted-foreground hover:text-foreground"><X size={14} /></button>
            </div>
            <div className="p-4 overflow-auto">
              {drill.loading && <div className="flex justify-center py-10"><Loader2 size={22} className="animate-spin text-teal-400" /></div>}
              {drill.error && <p className="text-sm text-rose-300">{drill.error}</p>}
              {!drill.loading && !drill.error && drill.rows.length === 0 && (
                <p className="text-sm text-muted-foreground">Sem registos para este ponto.</p>
              )}
              {!drill.loading && drill.rows.length > 0 && (
                <table className="w-full text-xs">
                  <thead className="sticky top-0 bg-card/95">
                    <tr>
                      {Object.keys(drill.rows[0]).filter((key) => !key.startsWith("_")).map((key) => (
                        <th key={key} className="text-left px-2 py-1.5 font-semibold text-muted-foreground whitespace-nowrap">{key}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {drill.rows.map((row, index) => (
                      <tr key={index} className="border-t border-white/5 hover:bg-white/[0.03]">
                        {Object.keys(drill.rows[0]).filter((key) => !key.startsWith("_")).map((key) => (
                          <td key={key} className="px-2 py-1.5 align-top max-w-[22rem] truncate" title={String(row[key] ?? "")}>
                            {typeof row[key] === "number" ? formatCell(row[key] as number) : String(row[key] ?? "—")}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );

  // ---------------------------------------------------------------------------
  // JSX principal
  // ---------------------------------------------------------------------------
  const dynamicBody = dynamicBodyElement;

  const staticBody = (
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
            <button
              onClick={() => setDynamicMode(true)}
              className="px-3 py-2 rounded-xl glass-card bg-primary/10 text-primary border-primary/20 hover:bg-primary/15 transition flex items-center gap-2 text-sm"
            >
              <LayoutGrid size={16} />
              <span className="hidden sm:inline">Modo dinâmico</span>
            </button>
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

  return dynamicMode ? dynamicBody : staticBody;
}
