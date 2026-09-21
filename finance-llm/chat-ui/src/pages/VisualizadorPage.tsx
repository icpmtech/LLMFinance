/**
 * Visualizador — aplicação de BI do IQ OS.
 *
 * Junta tudo o que a plataforma tem indexado (contratos, mercados, marcas,
 * CRM, Office, recolha) num modelo semântico com dimensões, medidas e fórmulas:
 * escolhe-se um dataset, arrastam-se (clicam-se) campos para um visual, filtram-se
 * os dados e guardam-se dashboards — como no Power BI, mas sobre os dados da casa.
 *
 * A página é o "ecrã de trabalho": a coluna esquerda é o painel de campos e
 * filtros, o centro é a grelha de visuais. Cada visual faz a sua própria consulta
 * ao backend (`/visualizador/query`), pelo que um visual lento nunca bloqueia os
 * outros.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  BarChart3,
  Bookmark,
  FolderOpen,
  Layers,
  LayoutGrid,
  Loader2,
  Plus,
  Printer,
  Save,
  Trash2,
  TriangleAlert,
  X,
} from "lucide-react";
import { FieldPanel } from "../components/visualizador/FieldPanel";
import { VisualCard, specKey } from "../components/visualizador/VisualCard";
import { formatCell } from "../components/visualizador/VisualChart";
import { exportDashboardCsv, printVisualizador } from "../visualizadorExport";
import {
  persistDatasetId,
  persistWorkspace,
  readPendingWorkspace,
  storedDatasetId,
  useDashboardHandoff,
  type VisualizadorWorkspace,
} from "../visualizadorHandoff";
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

/** Alias local ao formato partilhado com a galeria de dashboards. */
type Workspace = VisualizadorWorkspace;

function initialDatasetId(): string {
  return storedDatasetId();
}

function emptyWorkspace(): Workspace {
  return { name: "Análise sem título", dashboardId: null, dataset: storedDatasetId(), filters: {}, search: "", visuals: [] };
}

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

function newVisual(detail: DatasetDetail | null, title?: string): VisualConfig {
  const defaults = detail?.defaults ?? {};
  const dimensionId = defaults.dimension ?? detail?.dimensions[0]?.id ?? "";
  const dimension = detail?.dimensions.find((entry) => entry.id === dimensionId);
  const catalog = detail?.measures ?? [];
  // Sem medida predefinida, prefere-se a primeira medida de valor (soma/média) —
  // «contagem» é o último recurso, para o visual nunca abrir vazio.
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

function loadWorkspace(): Workspace {
  return readPendingWorkspace() ?? emptyWorkspace();
}

export default function VisualizadorPage({ onOpenDashboards }: { onOpenDashboards?: () => void } = {}) {
  const [meta, setMeta] = useState<VisualizadorMeta | null>(null);
  const [metaError, setMetaError] = useState<string | null>(null);
  const [datasetId, setDatasetId] = useState<string>(() => initialDatasetId());
  const [detail, setDetail] = useState<DatasetDetail | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [workspace, setWorkspace] = useState<Workspace>(() => {
    const stored = loadWorkspace();
    // O trabalho guardado só se restaura no dataset a que pertence: os ids dos
    // campos são específicos de cada dataset.
    if (stored.dataset && stored.dataset !== initialDatasetId()) return emptyWorkspace();
    return stored;
  });
  const datasetRef = useRef<string | null>(null);
  const [activeVisualId, setActiveVisualId] = useState<string | null>(null);
  const [dashboards, setDashboards] = useState<DashboardList | null>(null);
  const [showDashboards, setShowDashboards] = useState(false);
  const [status, setStatus] = useState<{ kind: "ok" | "error"; message: string } | null>(null);
  const [saving, setSaving] = useState(false);
  const [drill, setDrill] = useState<{ title: string; rows: QueryRow[]; loading: boolean; error?: string | null } | null>(null);

  // --- Catálogo -----------------------------------------------------------
  useEffect(() => {
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
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // --- Dataset escolhido --------------------------------------------------
  useEffect(() => {
    let cancelled = false;
    setLoadingDetail(true);
    getVisualizadorDataset(datasetId)
      .then((response) => {
        if (cancelled) return;
        setDetail(response);
        persistDatasetId(datasetId);
      })
      .catch((error) => {
        if (cancelled) return;
        setDetail(null);
        setMetaError(error instanceof Error ? error.message : "Não foi possível abrir o dataset.");
      })
      .finally(() => {
        if (!cancelled) setLoadingDetail(false);
      });
    return () => {
      cancelled = true;
    };
  }, [datasetId]);

  // --- Persistência local do trabalho ------------------------------------
  useEffect(() => {
    persistWorkspace({ ...workspace, dataset: datasetId });
  }, [workspace, datasetId]);

  // --- Dashboard aberto na galeria (editor já montado) --------------------
  const applyHandoff = useCallback((payload: VisualizadorWorkspace) => {
    // Marcar já o dataset evita que o efeito de troca de dataset limpe os
    // filtros que vieram com o dashboard.
    datasetRef.current = payload.dataset ?? datasetRef.current;
    if (payload.dataset) setDatasetId(payload.dataset);
    setWorkspace({
      name: payload.name,
      dashboardId: payload.dashboardId ?? null,
      dataset: payload.dataset,
      filters: payload.filters ?? {},
      search: payload.search ?? "",
      visuals: payload.visuals ?? [],
    });
    setStatus({ kind: "ok", message: `Dashboard «${payload.name}» aberto.` });
  }, []);

  useDashboardHandoff(applyHandoff);

  // --- Troca de dataset: ajustar campos e filtros ao novo conjunto --------
  useEffect(() => {
    if (!detail) return;
    const id = detail.dataset.id;
    const previous = datasetRef.current;
    datasetRef.current = id;
    const dimensionIds = new Set(detail.dimensions.map((entry) => entry.id));
    const measureIds = new Set(detail.measures.map((entry) => entry.id));
    const changed = previous !== null && previous !== id;
    setWorkspace((current) => {
      let adjusted = false;
      const visuals = current.visuals.map((visual) => {
        const dimensions = visual.dimensions.filter((entry) => entry.id && dimensionIds.has(entry.id));
        const measures = visual.measures.filter((spec) => measureIds.has(specKey(spec)));
        const hadDimensions = visual.dimensions.filter((entry) => entry.id).length;
        if (dimensions.length === hadDimensions && measures.length === visual.measures.length) return visual;
        adjusted = true;
        const fallback = newVisual(detail, visual.title);
        return {
          ...visual,
          // Só se repõem os campos que deixaram de existir: os restantes mantêm-se.
          dimensions: hadDimensions > 0 && dimensions.length === 0 ? fallback.dimensions : dimensions,
          measures: visual.measures.length > 0 && measures.length === 0 ? fallback.measures : measures,
          formulas: [],
        };
      });
      if (!adjusted && !changed) return current;
      return { ...current, visuals, filters: changed ? {} : current.filters, search: changed ? "" : current.search };
    });
    if (changed) {
      setStatus({ kind: "ok", message: `Dataset «${detail.dataset.label}»: campos e filtros ajustados ao novo conjunto de dados.` });
    }
  }, [detail]);

  // --- Primeiro visual quando o dataset abre -----------------------------
  useEffect(() => {
    if (!detail) return;
    setWorkspace((current) => {
      if (current.visuals.length > 0) return current;
      const visual = newVisual(detail);
      return { ...current, visuals: [visual] };
    });
  }, [detail]);

  const activeVisual = useMemo(
    () => workspace.visuals.find((visual) => visual.id === activeVisualId) ?? workspace.visuals[0] ?? null,
    [workspace.visuals, activeVisualId],
  );

  const patchWorkspace = useCallback((patch: Partial<Workspace>) => {
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

  /** Clique num campo: acrescenta ao visual ativo (ou cria um novo). */
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
      const entry = {
        id: fieldId,
        interval: dimension?.type === "date" ? "mes" : undefined,
      };
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

  // --- Drill-through ------------------------------------------------------
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

  // --- Dashboards ---------------------------------------------------------
  const refreshDashboards = useCallback(async () => {
    try {
      setDashboards(await listVisualizadorDashboards());
    } catch (error) {
      setStatus({ kind: "error", message: error instanceof Error ? error.message : "Não foi possível listar os dashboards." });
    }
  }, []);

  useEffect(() => {
    if (showDashboards) void refreshDashboards();
  }, [showDashboards, refreshDashboards]);

  const saveDashboard = useCallback(async () => {
    if (!detail) return;
    setSaving(true);
    setStatus(null);
    try {
      const saved = await saveVisualizadorDashboard({
        id: workspace.dashboardId ?? undefined,
        name: workspace.name,
        dataset: detail.dataset.id,
        filters: workspace.filters,
        visuals: workspace.visuals,
        description: `${detail.dataset.label} · ${workspace.visuals.length} visual(is)`,
        tags: [],
      });
      patchWorkspace({ dashboardId: saved.id, name: saved.name });
      setStatus({ kind: "ok", message: `Dashboard «${saved.name}» guardado.` });
      void refreshDashboards();
    } catch (error) {
      setStatus({ kind: "error", message: error instanceof Error ? error.message : "Não foi possível guardar." });
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
      setStatus({ kind: "ok", message: `Dashboard «${dashboard.name}» aberto.` });
    } catch (error) {
      setStatus({ kind: "error", message: error instanceof Error ? error.message : "Não foi possível abrir o dashboard." });
    }
  }, [datasetId]);

  const exportAllCsv = useCallback(async () => {
    if (!detail || workspace.visuals.length === 0) return;
    try {
      const exported = await exportDashboardCsv(workspace.name, workspace.visuals, detail.dataset.id,
                                                workspace.filters, workspace.search);
      setStatus({
        kind: exported > 0 ? "ok" : "error",
        message: exported > 0
          ? `${exported} visual(is) exportado(s) em CSV.`
          : "Não foi possível exportar: os visuais não devolveram dados.",
      });
    } catch (error) {
      setStatus({ kind: "error", message: error instanceof Error ? error.message : "A exportação falhou." });
    }
  }, [detail, workspace.visuals, workspace.filters, workspace.search, workspace.name]);

  const chartTypes = meta?.chart_types ?? [];

  return (
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
              Visualizador
            </h1>
            <p className="text-muted-foreground mt-2 max-w-2xl">
              Análises e visualizações sobre os dados da plataforma: escolha um dataset, clique nos campos para
              construir visuais, filtre, guarde dashboards e exporte (CSV, Excel, PNG ou PDF).
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
            <button type="button" onClick={onOpenDashboards} disabled={!onOpenDashboards}
                    className="flex items-center gap-1.5 px-3 py-2 rounded-xl glass-card text-sm hover:bg-white/5 disabled:opacity-40">
              <Layers size={14} /> Dashboards e modelos
            </button>
            <button type="button" onClick={addVisual} disabled={!detail}
                    className="flex items-center gap-1.5 px-3 py-2 rounded-xl glass-card text-sm hover:bg-white/5 disabled:opacity-50">
              <Plus size={14} /> Novo visual
            </button>
            <button type="button" onClick={printVisualizador}
                    className="flex items-center gap-1.5 px-3 py-2 rounded-xl glass-card text-sm hover:bg-white/5">
              <Printer size={14} /> PDF
            </button>
            <button type="button" onClick={exportAllCsv} disabled={workspace.visuals.length === 0}
                    className="flex items-center gap-1.5 px-3 py-2 rounded-xl glass-card text-sm hover:bg-white/5 disabled:opacity-50">
              <Bookmark size={14} /> CSV dos visuais
            </button>
          </div>
        </div>

        {(metaError || status) && (
          <div className={["mb-5 p-3 rounded-2xl flex items-center gap-2 text-sm",
            (status?.kind === "error" || metaError) ? "bg-rose-500/10 border border-rose-500/20 text-rose-300" : "bg-teal-500/10 border border-teal-500/20 text-teal-200"].join(" ")}>
            {(status?.kind === "error" || metaError) ? <TriangleAlert size={16} /> : <BarChart3 size={16} />}
            <span className="flex-1">{metaError ?? status?.message}</span>
            <button type="button" onClick={() => { setMetaError(null); setStatus(null); }} aria-label="Fechar aviso"
                    className="visualizador-noprint text-xs opacity-70 hover:opacity-100"><X size={13} /></button>
          </div>
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
                      {item.dataset ?? "—"} · {item.visuals} visual(is){item.mine ? "" : ` · ${item.owner_email ?? "equipa"}`}
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
                        setStatus({ kind: "error", message: error instanceof Error ? error.message : "Não foi possível duplicar." });
                      }
                    }} className="px-2 py-1 rounded-lg glass-card text-[11px] hover:bg-white/5">Duplicar</button>
                    {item.mine && (
                      <button type="button" onClick={async () => {
                        try {
                          await deleteVisualizadorDashboard(item.id);
                          if (workspace.dashboardId === item.id) patchWorkspace({ dashboardId: null });
                          void refreshDashboards();
                        } catch (error) {
                          setStatus({ kind: "error", message: error instanceof Error ? error.message : "Não foi possível remover." });
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
                    {(detail.dataset.notes ?? [])[0] ?? "É um dataset resolvido em memória a partir de várias fontes: os totais não seriam exatos. Use as listas do módulo respetivo."}
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
                  Ainda não há visuais. Clique em «Novo visual», numa sugestão do painel esquerdo, ou diretamente numa
                  dimensão/medida para começar.
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
                      <tr key={index} className="border-t border-border/40">
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
}
