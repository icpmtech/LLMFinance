/**
 * Visualizador — **Dashboards** (galeria, templates e modo apresentação).
 *
 * Esta página é o "índice" do Visualizador:
 *
 * - **Modelos prontos** (templates) — dashboards completos por domínio; podem ser
 *   criados como dashboard próprio (fica guardado na conta) ou abertos no editor
 *   para ajustar antes de guardar. Cada modelo sabe quantos registos a fonte tem,
 *   para não prometer um ecrã cheio de dados que ainda não existem.
 * - **Os meus dashboards** — lista do que está guardado, com apresentação,
 *   abertura no editor, duplicação, remoção e exportação.
 * - **Modo apresentação** — o dashboard em ecrã cheio, sem painéis de edição, com
 *   navegação entre dashboards e impressão/PDF.
 *
 * A passagem para o editor é feita pelo mesmo `localStorage` que o editor usa
 * para retomar o trabalho (`visualizador:workspace` + `visualizador:dataset`),
 * pelo que abrir um dashboard não precisa de estado partilhado entre páginas.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  BarChart3,
  BookOpen,
  BadgeCheck,
  Copy,
  Database,
  Eye,
  FileText,
  FolderOpen,
  Layers,
  LayoutGrid,
  Loader2,
  Newspaper,
  Pencil,
  Plus,
  Printer,
  RefreshCw,
  ScrollText,
  Sparkles,
  Tags,
  Target,
  Telescope,
  Trash2,
  TrendingUp,
  TriangleAlert,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { VisualChart } from "../components/visualizador/VisualChart";
import { exportDashboardCsv, printVisualizador } from "../visualizadorExport";
import { openDashboardInEditor } from "../visualizadorHandoff";
import {
  buildQuery,
  createDashboardFromTemplate,
  deleteVisualizadorDashboard,
  duplicateVisualizadorDashboard,
  getVisualizadorDashboard,
  getVisualizadorTemplates,
  listVisualizadorDashboards,
  runVisualQuery,
  type Dashboard,
  type DashboardList,
  type DashboardSummary,
  type QueryResult,
  type TemplateList,
  type VisualConfig,
  type VisualTemplate,
} from "../visualizadorApi";

const ICONS: Record<string, LucideIcon> = {
  "file-text": FileText,
  tags: Tags,
  newspaper: Newspaper,
  "trending-up": TrendingUp,
  "badge-check": BadgeCheck,
  "scroll-text": ScrollText,
  target: Target,
  database: Database,
  "book-open": BookOpen,
  telescope: Telescope,
};

const WIDTH_CLASS: Record<number, string> = {
  12: "lg:col-span-12",
  8: "lg:col-span-8",
  6: "lg:col-span-6",
  4: "lg:col-span-4",
};

/** Entrega um dashboard ao editor (localStorage + evento, ver `visualizadorHandoff`). */
const handoffToEditor = openDashboardInEditor;

function templateToDashboard(template: VisualTemplate): Dashboard {
  return {
    id: undefined,
    name: template.name,
    description: template.description ?? undefined,
    dataset: template.dataset,
    filters: template.filters ?? {},
    visuals: template.visuals ?? [],
    tags: template.tags ?? [],
  };
}

function formatDate(value?: string | null): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "—";
  return parsed.toLocaleString("pt-PT", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

function formatRecords(value?: number | null): string {
  if (value === null || value === undefined) return "volumetria desconhecida";
  return `${value.toLocaleString("pt-PT")} registos`;
}

/** Um visual de um dashboard em modo apresentação (só leitura). */
function DashboardVisual({
  config,
  datasetId,
  filters,
  height = "h-56 md:h-64",
}: {
  config: VisualConfig;
  datasetId: string;
  filters: Record<string, unknown>;
  height?: string;
}) {
  const [result, setResult] = useState<QueryResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const payload = useMemo(() => buildQuery(config, datasetId, filters, ""), [config, datasetId, filters]);
  const key = JSON.stringify(payload);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    runVisualQuery(payload)
      .then((response) => {
        if (cancelled) return;
        setResult(response);
        if (response.error && (response.rows ?? []).length === 0) setError(response.error);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Erro ao consultar os dados.");
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  return (
    <div className="glass-card gradient-border rounded-2xl p-4 flex flex-col gap-2">
      <div className="flex items-start justify-between gap-2">
        <h3 className="text-sm font-semibold truncate">{config.title}</h3>
        <span className="text-[10px] text-muted-foreground whitespace-nowrap">
          {result?.meta?.documents !== undefined ? formatRecords(result.meta.documents) : ""}
        </span>
      </div>
      <div className={height}>
        {!result && !error && (
          <div className="h-full flex items-center justify-center">
            <Loader2 size={22} className="animate-spin text-teal-400" />
          </div>
        )}
        {error && (
          <div className="h-full flex items-center justify-center gap-2 text-xs text-rose-300 px-4 text-center">
            <TriangleAlert size={14} /> {error}
          </div>
        )}
        {result && !error && <VisualChart result={result} config={config} />}
      </div>
      {result?.meta?.truncated && (
        <p className="text-[10px] text-amber-300">Resultado truncado pelo número de grupos (use o editor para afinar a Top-N).</p>
      )}
    </div>
  );
}

export default function VisualizadorDashboardsPage({
  onOpenEditor,
}: {
  /** Navega para o editor do Visualizador (o dashboard vai no `localStorage`). */
  onOpenEditor: () => void;
}) {
  const [templates, setTemplates] = useState<TemplateList | null>(null);
  const [dashboards, setDashboards] = useState<DashboardList | null>(null);
  const [domain, setDomain] = useState<string>("");
  const [status, setStatus] = useState<{ kind: "ok" | "error"; message: string } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [presenting, setPresenting] = useState<Dashboard | null>(null);
  const [refreshTick, setRefreshTick] = useState(0);

  // --- Carregamento -------------------------------------------------------
  useEffect(() => {
    let cancelled = false;
    getVisualizadorTemplates()
      .then((response) => {
        if (!cancelled) setTemplates(response);
      })
      .catch((error) => {
        if (!cancelled) setStatus({ kind: "error", message: error instanceof Error ? error.message : "Não foi possível carregar os modelos." });
      });
    listVisualizadorDashboards()
      .then((response) => {
        if (!cancelled) setDashboards(response);
      })
      .catch((error) => {
        if (!cancelled) setStatus({ kind: "error", message: error instanceof Error ? error.message : "Não foi possível listar os dashboards." });
      });
    return () => {
      cancelled = true;
    };
  }, [refreshTick]);

  const reload = useCallback(() => setRefreshTick((value) => value + 1), []);

  const visibleTemplates = useMemo(() => {
    const items = templates?.items ?? [];
    if (!domain) return items;
    return items.filter((item) => item.domain === domain);
  }, [templates, domain]);

  const domainOptions = useMemo(() => {
    const items = templates?.items ?? [];
    const seen = new Map<string, string>();
    for (const item of items) {
      const key = item.domain || "outros";
      if (!seen.has(key)) seen.set(key, templates?.domains.find((entry) => entry.id === key)?.label ?? key);
    }
    return [...seen.entries()].map(([id, label]) => ({ id, label }));
  }, [templates]);

  // --- Ações --------------------------------------------------------------
  const openBlank = useCallback(() => {
    handoffToEditor({ name: "Análise sem título", dataset: "contrato", filters: {}, visuals: [] });
    onOpenEditor();
  }, [onOpenEditor]);

  const openTemplateInEditor = useCallback(
    (template: VisualTemplate) => {
      handoffToEditor(templateToDashboard(template));
      onOpenEditor();
    },
    [onOpenEditor],
  );

  const createFromTemplate = useCallback(
    async (template: VisualTemplate) => {
      setBusy(`create:${template.id}`);
      setStatus(null);
      try {
        const created = await createDashboardFromTemplate(template.id, template.name);
        handoffToEditor(created.dashboard);
        setStatus({ kind: "ok", message: `Dashboard «${created.dashboard.name}» criado a partir do modelo.` });
        onOpenEditor();
      } catch (error) {
        setStatus({
          kind: "error",
          message: error instanceof Error
            ? `${error.message} — para guardar dashboards é preciso ter sessão iniciada; use «Pré-visualizar» para abrir o modelo no editor.`
            : "Não foi possível criar o dashboard.",
        });
      } finally {
        setBusy(null);
      }
    },
    [onOpenEditor],
  );

  const openSaved = useCallback(
    async (id: string, mode: "edit" | "present") => {
      setBusy(`open:${id}`);
      setStatus(null);
      try {
        const dashboard = await getVisualizadorDashboard(id);
        if (mode === "present") {
          setPresenting(dashboard);
        } else {
          handoffToEditor(dashboard);
          onOpenEditor();
        }
      } catch (error) {
        setStatus({ kind: "error", message: error instanceof Error ? error.message : "Não foi possível abrir o dashboard." });
      } finally {
        setBusy(null);
      }
    },
    [onOpenEditor],
  );

  const removeSaved = useCallback(async (item: DashboardSummary) => {
    setBusy(`delete:${item.id}`);
    try {
      await deleteVisualizadorDashboard(item.id);
      if (presenting?.id === item.id) setPresenting(null);
      setStatus({ kind: "ok", message: `Dashboard «${item.name}» removido.` });
      reload();
    } catch (error) {
      setStatus({ kind: "error", message: error instanceof Error ? error.message : "Não foi possível remover." });
    } finally {
      setBusy(null);
    }
  }, [presenting, reload]);

  const duplicateSaved = useCallback(async (item: DashboardSummary) => {
    setBusy(`duplicate:${item.id}`);
    try {
      const copy = await duplicateVisualizadorDashboard(item.id);
      setStatus({ kind: "ok", message: `Cópia «${copy.name}» criada.` });
      reload();
    } catch (error) {
      setStatus({ kind: "error", message: error instanceof Error ? error.message : "Não foi possível duplicar." });
    } finally {
      setBusy(null);
    }
  }, [reload]);

  const exportSaved = useCallback(async (dashboard: Dashboard) => {
    if (!dashboard.dataset) {
      setStatus({ kind: "error", message: "Este dashboard não tem dataset definido." });
      return;
    }
    setBusy(`export:${dashboard.id ?? "present"}`);
    try {
      const exported = await exportDashboardCsv(dashboard.name, dashboard.visuals ?? [], dashboard.dataset, dashboard.filters ?? {}, "");
      setStatus({
        kind: exported > 0 ? "ok" : "error",
        message: exported > 0 ? `${exported} visual(is) exportado(s) em CSV.` : "Nenhum visual devolveu dados para exportar.",
      });
    } catch (error) {
      setStatus({ kind: "error", message: error instanceof Error ? error.message : "A exportação falhou." });
    } finally {
      setBusy(null);
    }
  }, []);

  // --- Modo apresentação --------------------------------------------------
  if (presenting) {
    const items = dashboards?.items ?? [];
    const position = items.findIndex((item) => item.id === presenting.id);
    const previous = position > 0 ? items[position - 1] : null;
    const next = position >= 0 && position < items.length - 1 ? items[position + 1] : null;
    return (
      <div className="visualizador-root min-h-screen w-full bg-background text-foreground orbit-bg">
        <div className="max-w-[1700px] mx-auto px-4 sm:px-6 py-8">
          <div className="visualizador-noprint flex flex-col lg:flex-row lg:items-end lg:justify-between gap-4 mb-6">
            <div>
              <button type="button" onClick={() => setPresenting(null)}
                      className="flex items-center gap-2 px-3 py-1.5 rounded-full glass-card text-xs text-muted-foreground hover:text-foreground mb-3">
                <ArrowLeft size={14} /> Voltar aos dashboards
              </button>
              <h1 className="text-3xl md:text-4xl font-bold flex items-center gap-3">
                <span className="p-2 rounded-2xl bg-gradient-to-br from-teal-500/25 to-blue-500/20 border border-white/10">
                  <LayoutGrid size={28} className="text-teal-300" />
                </span>
                {presenting.name}
              </h1>
              <p className="text-muted-foreground mt-2">
                {presenting.description || "Dashboard"} · {presenting.dataset ?? "—"} · {(presenting.visuals ?? []).length} visual(is)
              </p>
            </div>
            <div className="visualizador-noprint flex flex-wrap items-center gap-2">
              <button type="button" disabled={!previous} onClick={() => previous && void openSaved(previous.id, "present")}
                      className="flex items-center gap-1.5 px-3 py-2 rounded-xl glass-card text-sm hover:bg-white/5 disabled:opacity-40">
                <ArrowLeft size={14} /> Anterior
              </button>
              <button type="button" disabled={!next} onClick={() => next && void openSaved(next.id, "present")}
                      className="flex items-center gap-1.5 px-3 py-2 rounded-xl glass-card text-sm hover:bg-white/5 disabled:opacity-40">
                Seguinte <ArrowRight size={14} />
              </button>
              <button type="button" onClick={() => { handoffToEditor(presenting); onOpenEditor(); }}
                      className="flex items-center gap-1.5 px-3 py-2 rounded-xl glass-card text-sm hover:bg-white/5">
                <Pencil size={14} /> Abrir no editor
              </button>
              <button type="button" onClick={() => void exportSaved(presenting)}
                      className="flex items-center gap-1.5 px-3 py-2 rounded-xl glass-card text-sm hover:bg-white/5">
                <FolderOpen size={14} /> CSV
              </button>
              <button type="button" onClick={printVisualizador}
                      className="flex items-center gap-1.5 px-3 py-2 rounded-xl glass-card text-sm hover:bg-white/5">
                <Printer size={14} /> PDF
              </button>
            </div>
          </div>

          {status && (
            <div className={["visualizador-noprint mb-5 p-3 rounded-2xl text-sm flex items-center gap-2", status.kind === "error" ? "bg-rose-500/10 border border-rose-500/20 text-rose-300" : "bg-teal-500/10 border border-teal-500/20 text-teal-200"].join(" ")}>
              <TriangleAlert size={16} /> {status.message}
            </div>
          )}

          <div className="visualizador-grid grid grid-cols-1 lg:grid-cols-12 gap-4">
            {(presenting.visuals ?? []).map((visual) => (
              <div key={visual.id} className={WIDTH_CLASS[visual.width] ?? "lg:col-span-6"}>
                <DashboardVisual config={visual} datasetId={presenting.dataset ?? "contrato"} filters={presenting.filters ?? {}} />
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  // --- Galeria ------------------------------------------------------------
  return (
    <div className="visualizador-root min-h-screen w-full bg-background text-foreground orbit-bg">
      <div className="max-w-[1700px] mx-auto px-4 sm:px-6 py-8">
        <div className="flex flex-col lg:flex-row lg:items-end lg:justify-between gap-4 mb-6">
          <div>
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full glass-card text-xs text-teal-300 mb-3">
              <Layers size={14} />
              {templates ? `${templates.total} modelos · ${dashboards?.total ?? 0} dashboards` : "a carregar…"}
            </div>
            <h1 className="text-3xl md:text-4xl font-bold flex items-center gap-3">
              <span className="p-2 rounded-2xl bg-gradient-to-br from-teal-500/25 to-blue-500/20 border border-white/10">
                <LayoutGrid size={30} className="text-teal-300" />
              </span>
              Dashboards
            </h1>
            <p className="text-muted-foreground mt-2 max-w-3xl">
              Comece por um modelo pronto (contratos, mercados, CRM, Office, recolha…) ou abra um dashboard guardado.
              Qualquer dashboard pode ser apresentado em ecrã cheio, exportado para CSV e impresso em PDF.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button type="button" onClick={openBlank}
                    className="flex items-center gap-1.5 px-3 py-2 rounded-xl glass-card text-sm hover:bg-white/5">
              <Plus size={14} /> Dashboard em branco
            </button>
            <button type="button" onClick={reload}
                    className="flex items-center gap-1.5 px-3 py-2 rounded-xl glass-card text-sm hover:bg-white/5">
              <RefreshCw size={14} /> Atualizar
            </button>
          </div>
        </div>

        {status && (
          <div className={["mb-5 p-3 rounded-2xl text-sm flex items-center gap-2", status.kind === "error" ? "bg-rose-500/10 border border-rose-500/20 text-rose-300" : "bg-teal-500/10 border border-teal-500/20 text-teal-200"].join(" ")}>
            <TriangleAlert size={16} /> {status.message}
          </div>
        )}

        <section className="mb-8">
          <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
            <h2 className="text-base font-semibold flex items-center gap-2">
              <Sparkles size={16} className="text-teal-300" /> Modelos prontos
            </h2>
            <div className="flex flex-wrap gap-1.5">
              <button type="button" onClick={() => setDomain("")}
                      className={["px-2.5 py-1 rounded-full text-[11px]", domain === "" ? "glass-card bg-primary/10 text-primary" : "glass-card text-muted-foreground hover:text-foreground"].join(" ")}>
                Todos
              </button>
              {domainOptions.map((option) => (
                <button key={option.id} type="button" onClick={() => setDomain(option.id)}
                        className={["px-2.5 py-1 rounded-full text-[11px]", domain === option.id ? "glass-card bg-primary/10 text-primary" : "glass-card text-muted-foreground hover:text-foreground"].join(" ")}>
                  {option.label}
                </button>
              ))}
            </div>
          </div>

          {!templates && <div className="flex justify-center py-10"><Loader2 size={24} className="animate-spin text-teal-400" /></div>}

          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
            {visibleTemplates.map((template) => {
              const Icon = ICONS[template.icon ?? ""] ?? BarChart3;
              const creating = busy === `create:${template.id}`;
              return (
                <div key={template.id} className="glass-card gradient-border rounded-2xl p-4 flex flex-col gap-3">
                  <div className="flex items-start gap-3">
                    <span className="p-2 rounded-xl bg-teal-500/10 border border-white/10 shrink-0">
                      <Icon size={18} className="text-teal-300" />
                    </span>
                    <div className="min-w-0">
                      <h3 className="text-sm font-semibold">{template.name}</h3>
                      <p className="text-[11px] text-muted-foreground mt-0.5 line-clamp-3">{template.description}</p>
                    </div>
                  </div>

                  <div className="flex flex-wrap gap-1.5 text-[10px]">
                    <span className="px-2 py-0.5 rounded-full glass-card">{template.dataset_label}</span>
                    <span className="px-2 py-0.5 rounded-full glass-card">{template.visuals.length} visuais</span>
                    <span className={["px-2 py-0.5 rounded-full glass-card", template.sparse ? "text-amber-300" : ""].join(" ")}>
                      {formatRecords(template.records)}
                    </span>
                    {template.requires_session && <span className="px-2 py-0.5 rounded-full bg-amber-500/10 text-amber-300">privado</span>}
                    {(template.tags ?? []).slice(0, 2).map((tag) => (
                      <span key={tag} className="px-2 py-0.5 rounded-full glass-card text-muted-foreground">#{tag}</span>
                    ))}
                  </div>

                  {(template.data_note || template.warnings.length > 0 || template.note) && (
                    <div className="text-[10px] text-amber-300 space-y-1">
                      {template.data_note && <p className="flex items-start gap-1.5"><TriangleAlert size={11} className="mt-0.5 shrink-0" /> {template.data_note}</p>}
                      {template.note && <p>· {template.note}</p>}
                      {template.warnings.slice(0, 2).map((warning, index) => <p key={index}>· {warning}</p>)}
                    </div>
                  )}

                  <div className="mt-auto flex items-center gap-1.5">
                    <button type="button" onClick={() => void createFromTemplate(template)} disabled={!template.available || creating}
                            className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-xl glass-card text-xs hover:bg-white/5 disabled:opacity-40">
                      {creating ? <Loader2 size={12} className="animate-spin" /> : <Plus size={12} />} Criar dashboard
                    </button>
                    <button type="button" onClick={() => openTemplateInEditor(template)} disabled={!template.available}
                            className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-xl glass-card text-xs hover:bg-white/5 disabled:opacity-40"
                            title="Abrir no editor sem guardar">
                      <Eye size={12} /> Pré-visualizar
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        </section>

        <section>
          <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
            <h2 className="text-base font-semibold flex items-center gap-2">
              <FolderOpen size={16} className="text-teal-300" /> Os meus dashboards
            </h2>
            {dashboards?.stats && (
              <span className="text-[11px] text-muted-foreground">
                {dashboards.stats.visuals} visual(is) em {dashboards.stats.dashboards} dashboard(s)
              </span>
            )}
          </div>

          {dashboards?.note && (
            <div className="glass-card rounded-2xl p-4 text-sm text-amber-300 mb-3">{dashboards.note}</div>
          )}

          {dashboards && dashboards.items.length === 0 && (
            <div className="glass-card gradient-border rounded-2xl p-8 text-center space-y-2">
              <FolderOpen size={26} className="mx-auto text-teal-400" />
              <p className="text-sm text-muted-foreground">
                Ainda não há dashboards guardados. Crie um a partir de um modelo acima ou comece do zero.
              </p>
            </div>
          )}

          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
            {(dashboards?.items ?? []).map((item) => (
              <div key={item.id} className="glass-card rounded-2xl p-4 flex flex-col gap-3">
                <div className="min-w-0">
                  <h3 className="text-sm font-semibold truncate">{item.name}</h3>
                  <p className="text-[11px] text-muted-foreground truncate">
                    {item.dataset ?? "—"} · {item.visuals} visual(is){item.mine ? "" : ` · ${item.owner_email ?? "equipa"}`}
                  </p>
                  {item.description && <p className="text-[11px] text-muted-foreground mt-1 line-clamp-2">{item.description}</p>}
                  <p className="text-[10px] text-muted-foreground mt-1">Atualizado em {formatDate(item.updated_at)}</p>
                </div>
                <div className="mt-auto flex flex-wrap items-center gap-1.5">
                  <button type="button" onClick={() => void openSaved(item.id, "present")} disabled={busy === `open:${item.id}`}
                          className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-xl glass-card text-xs hover:bg-white/5 disabled:opacity-40">
                    {busy === `open:${item.id}` ? <Loader2 size={12} className="animate-spin" /> : <Eye size={12} />} Apresentar
                  </button>
                  <button type="button" onClick={() => void openSaved(item.id, "edit")}
                          className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-xl glass-card text-xs hover:bg-white/5">
                    <Pencil size={12} /> Editar
                  </button>
                  <button type="button" onClick={() => void duplicateSaved(item)} disabled={busy === `duplicate:${item.id}`}
                          className="p-1.5 rounded-xl glass-card text-muted-foreground hover:text-foreground disabled:opacity-40"
                          aria-label="Duplicar dashboard" title="Duplicar">
                    <Copy size={12} />
                  </button>
                  {item.mine && (
                    <button type="button" onClick={() => void removeSaved(item)} disabled={busy === `delete:${item.id}`}
                            className="p-1.5 rounded-xl glass-card text-muted-foreground hover:text-rose-300 disabled:opacity-40"
                            aria-label="Remover dashboard" title="Remover">
                      <Trash2 size={12} />
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
