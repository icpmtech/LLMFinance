/**
 * Área de quadros de análise do CRM.
 *
 * O utilizador compõe os seus próprios quadros: escolhe o **conjunto de dados**
 * (vendas por utilizador, encomendas, compras, operação…), a **métrica** e o
 * **tipo de gráfico** de cada widget. Os quadros ficam gravados no CRM (módulo
 * `dashboards`, com visibilidade privada, de equipa ou da organização) e podem
 * ser reabertos, duplicados ou eliminados.
 *
 * Os números vêm sempre de `GET /crm/analytics/datasets/{id}`, calculados sobre
 * os registos reais e dentro do âmbito do perfil.
 */
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import {
  AlertTriangle,
  BarChart3,
  Check,
  Copy,
  LayoutDashboard,
  Loader2,
  Pencil,
  Plus,
  RefreshCw,
  Settings2,
  Table2,
  Trash2,
  X,
} from "lucide-react";

import { Button } from "../components/ui/Button";
import {
  createCrmModuleRecord,
  deleteCrmModuleRecord,
  getCrmDatasetCatalogue,
  getCrmDatasetRows,
  listCrmModule,
  updateCrmModuleRecord,
  type CrmChartKind,
  type CrmDashboard,
  type CrmDashboardWidget,
  type CrmDataset,
  type CrmDatasetCatalogue,
  type CrmDatasetResult,
} from "../crmSuiteApi";
import { CHART_LABELS, CHART_OPTIONS, CrmChart, formatMetric } from "./CrmCharts";

const DASHBOARD_SLUG = "dashboards";

const inputClass =
  "w-full rounded-lg border border-white/10 bg-white/[0.04] px-2.5 py-1.5 text-[12.5px] text-foreground outline-none transition placeholder:text-muted-foreground/60 focus:border-teal-300/40 focus:bg-white/[0.07]";

const cardClass = "rounded-xl border border-white/8 bg-white/[0.03] p-3";

/* ------------------------------------------------------------------ primitivas */

function Field({ label, hint, children, wide = false }: { label: string; hint?: string; children: ReactNode; wide?: boolean }) {
  return (
    <label className={["flex flex-col gap-1", wide ? "sm:col-span-2" : ""].join(" ")}>
      <span className="text-[11.5px] font-medium text-muted-foreground">{label}</span>
      {children}
      {hint && <span className="text-[10.5px] leading-snug text-muted-foreground/80">{hint}</span>}
    </label>
  );
}

function Modal({
  title,
  subtitle,
  onClose,
  children,
  footer,
  wide = true,
}: {
  title: string;
  subtitle?: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  wide?: boolean;
}) {
  return (
    <div className="fixed inset-0 z-[120] flex items-start justify-center overflow-y-auto bg-black/60 p-4 pb-32 backdrop-blur-sm">
      <div
        className={[
          "mt-6 flex max-h-[82vh] w-full flex-col overflow-hidden rounded-2xl border border-white/12 bg-[#08181f] shadow-2xl",
          wide ? "max-w-5xl" : "max-w-2xl",
        ].join(" ")}
      >
        <header className="flex items-start gap-3 border-b border-white/8 px-4 py-3">
          <div className="min-w-0 flex-1">
            <h2 className="truncate text-[14px] font-semibold text-foreground">{title}</h2>
            {subtitle && <p className="truncate text-[11.5px] text-muted-foreground">{subtitle}</p>}
          </div>
          <button type="button" onClick={onClose} className="rounded-lg p-1 text-muted-foreground transition hover:bg-white/10 hover:text-foreground">
            <X size={15} />
          </button>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">{children}</div>
        {footer && <footer className="flex flex-wrap items-center justify-end gap-2 border-t border-white/8 px-4 py-3">{footer}</footer>}
      </div>
    </div>
  );
}

function Notice({ text, tone = "info", onClose }: { text: string; tone?: "info" | "error"; onClose?: () => void }) {
  return (
    <div
      className={[
        "flex items-center gap-2 rounded-lg border px-3 py-2 text-[12px]",
        tone === "error" ? "border-rose-400/25 bg-rose-500/10 text-rose-200" : "border-teal-300/25 bg-teal-400/10 text-teal-100",
      ].join(" ")}
    >
      {tone === "error" ? <AlertTriangle size={13} /> : <Check size={13} />}
      <span className="min-w-0 flex-1">{text}</span>
      {onClose && (
        <button type="button" onClick={onClose} className="rounded p-0.5 text-muted-foreground hover:text-foreground">
          <X size={12} />
        </button>
      )}
    </div>
  );
}

const VISIBILITY_LABELS: Record<string, string> = {
  privado: "Privado",
  equipa: "Equipa",
  organizacao: "Organização",
};

/* --------------------------------------------------------------- dados (cache) */

/** Catálogo de datasets: carregado uma vez por sessão (é estável). */
let catalogueCache: CrmDatasetCatalogue | null = null;

export function useDatasetCatalogue(): { catalogue: CrmDatasetCatalogue | null; error: string | null } {
  const [catalogue, setCatalogue] = useState<CrmDatasetCatalogue | null>(catalogueCache);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (catalogueCache) return;
    let alive = true;
    getCrmDatasetCatalogue()
      .then((result) => {
        catalogueCache = result;
        if (alive) setCatalogue(result);
      })
      .catch((err: unknown) => alive && setError(err instanceof Error ? err.message : "Não foi possível obter os conjuntos de dados"));
    return () => {
      alive = false;
    };
  }, []);
  return { catalogue, error };
}

/** Linhas de um dataset (com recarregar manual). */
export function useDatasetRows(
  datasetId: string,
  months: number,
  limit?: number,
): { result: CrmDatasetResult | null; loading: boolean; error: string | null; reload: () => void } {
  const [result, setResult] = useState<CrmDatasetResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!datasetId) {
      setResult(null);
      return;
    }
    let alive = true;
    setLoading(true);
    getCrmDatasetRows(datasetId, { months, limit })
      .then((data) => {
        if (!alive) return;
        setResult(data);
        setError(null);
      })
      .catch((err: unknown) => alive && setError(err instanceof Error ? err.message : "Não foi possível calcular o gráfico"))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [datasetId, months, limit, tick]);

  return { result, loading, error, reload: () => setTick((value) => value + 1) };
}

/**
 * Um gráfico de um dataset: busca as linhas e desenha a métrica escolhida.
 * É a peça que serve tanto os quadros do utilizador como os gráficos fixos do
 * painel de Analytics.
 */
export function CrmDatasetChart({
  datasetId,
  metric,
  chart,
  months,
  title,
  limit,
  subtitle,
  actions,
}: {
  datasetId: string;
  metric: string;
  chart: CrmChartKind;
  months: number;
  title?: string;
  limit?: number;
  subtitle?: string;
  actions?: ReactNode;
}) {
  const { result, loading, error } = useDatasetRows(datasetId, months, limit);
  const spec = result?.metrics.find((item) => item.key === metric) ?? result?.metrics[0];

  const points = useMemo(() => {
    if (!result || !spec) return [];
    return result.rows.map((row) => ({
      label: String(row[result.dimension.key] ?? row.label ?? "—"),
      value: Number(row[spec.key] ?? 0),
    }));
  }, [result, spec]);

  if (error) {
    return (
      <div className={cardClass}>
        <Notice text={error} tone="error" />
      </div>
    );
  }
  if (!result || !spec) {
    return (
      <div className={cardClass}>
        <p className="flex items-center gap-2 py-6 text-[12px] text-muted-foreground">
          <Loader2 size={13} className="animate-spin" /> A calcular…
        </p>
      </div>
    );
  }

  return (
    <CrmChart
      kind={chart}
      points={points}
      format={(value) => formatMetric(spec.kind, value)}
      title={title || `${result.label} · ${spec.label}`}
      subtitle={subtitle ?? `${result.linhas_mostradas} de ${result.linhas_totais} linha(s) · ${result.filtros.meses} meses`}
      dimensionLabel={result.dimension.label}
      metricLabel={spec.label}
      actions={
        actions ?? (
          loading ? <Loader2 size={12} className="animate-spin text-muted-foreground" /> : undefined
        )
      }
    />
  );
}

/* ------------------------------------------------------------------ construtor */

const newWidget = (dataset: string, metric: string, chart: CrmChartKind, limit?: number): CrmDashboardWidget => ({
  id: `w${Math.random().toString(36).slice(2, 8)}`,
  dataset,
  metric,
  chart,
  limit,
});

function defaultMetric(dataset: CrmDataset | undefined): string {
  return dataset?.metrics[0]?.key ?? "";
}

/** Editor de um quadro: metadados + widgets (com pré-visualização). */
function DashboardEditor({
  dashboard,
  catalogue,
  months,
  onClose,
  onSaved,
  onDeleted,
}: {
  dashboard: CrmDashboard | null;
  catalogue: CrmDatasetCatalogue;
  months: number;
  onClose: () => void;
  onSaved: (dashboard: CrmDashboard) => void;
  onDeleted?: () => void;
}) {
  const [name, setName] = useState(String(dashboard?.name ?? ""));
  const [description, setDescription] = useState(String(dashboard?.description ?? ""));
  const [visibility, setVisibility] = useState(String(dashboard?.visibility ?? "privado"));
  const [category, setCategory] = useState(String(dashboard?.category ?? "geral"));
  const [period, setPeriod] = useState(Number(dashboard?.period_months ?? months));
  const [widgets, setWidgets] = useState<CrmDashboardWidget[]>(() => (Array.isArray(dashboard?.widgets) ? (dashboard?.widgets as CrmDashboardWidget[]) : []));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<Record<string, CrmDatasetResult | null>>({});

  const byId = useMemo(() => new Map(catalogue.datasets.map((item) => [item.id, item])), [catalogue.datasets]);
  const first = catalogue.datasets[0];
  const usedDatasets = useMemo(() => Array.from(new Set(widgets.map((widget) => widget.dataset))), [widgets]);

  // Pré-visualização: um pedido por dataset usado, quando o período muda.
  useEffect(() => {
    let alive = true;
    if (usedDatasets.length === 0) {
      setPreview({});
      return;
    }
    Promise.all(
      usedDatasets.map(async (datasetId) => {
        try {
          return [datasetId, await getCrmDatasetRows(datasetId, { months: period })] as const;
        } catch {
          return [datasetId, null] as const;
        }
      }),
    ).then((entries) => {
      if (alive) setPreview(Object.fromEntries(entries));
    });
    return () => {
      alive = false;
    };
  }, [usedDatasets, period]);

  const update = (id: string, patch: Partial<CrmDashboardWidget>) =>
    setWidgets((current) => current.map((widget) => (widget.id === id ? { ...widget, ...patch } : widget)));

  const add = () => {
    if (!first) return;
    setWidgets((current) => [...current, newWidget(first.id, defaultMetric(first), first.chart, first.limit)]);
  };

  const addAll = () => {
    setWidgets(
      catalogue.datasets.slice(0, 4).map((dataset) => newWidget(dataset.id, defaultMetric(dataset), dataset.chart, dataset.limit)),
    );
  };

  const save = async () => {
    if (!name.trim()) {
      setError("Dê um nome ao quadro.");
      return;
    }
    setBusy(true);
    setError(null);
    const labels = Array.from(new Set(widgets.map((widget) => byId.get(widget.dataset)?.label || widget.dataset)));
    const body: Record<string, unknown> = {
      name: name.trim(),
      description: description.trim(),
      visibility,
      category,
      period_months: period,
      datasets: labels.join(", "),
      widgets: widgets.map((widget) => ({
        id: widget.id,
        dataset: widget.dataset,
        metric: widget.metric,
        chart: widget.chart,
        title: widget.title || "",
        limit: widget.limit ?? 0,
      })),
    };
    try {
      const saved = dashboard?.id
        ? await updateCrmModuleRecord<CrmDashboard>(DASHBOARD_SLUG, String(dashboard.id), body)
        : await createCrmModuleRecord<CrmDashboard>(DASHBOARD_SLUG, body);
      onSaved({ ...(saved.item || {}), ...body, id: String(dashboard?.id ?? saved.item?.id ?? "") });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Não foi possível gravar o quadro");
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!dashboard?.id) return;
    setBusy(true);
    try {
      await deleteCrmModuleRecord(DASHBOARD_SLUG, String(dashboard.id));
      onDeleted?.();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Não foi possível eliminar o quadro");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      title={dashboard?.id ? `Editar «${dashboard.name}»` : "Novo quadro de análise"}
      subtitle="Escolha os conjuntos de dados, a métrica e o tipo de gráfico de cada widget."
      onClose={onClose}
      footer={
        <>
          {dashboard?.id && (
            <Button size="sm" variant="outline" icon={<Trash2 size={13} />} onClick={() => void remove()} loading={busy}>
              Eliminar
            </Button>
          )}
          <div className="min-w-0 flex-1" />
          <Button size="sm" variant="outline" onClick={onClose}>
            Cancelar
          </Button>
          <Button size="sm" icon={<Check size={13} />} onClick={() => void save()} loading={busy}>
            Guardar quadro
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        {error && <Notice text={error} tone="error" onClose={() => setError(null)} />}

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Field label="Nome" wide>
            <input className={inputClass} value={name} onChange={(event) => setName(event.target.value)} placeholder="Ex.: Vendas da equipa comercial" />
          </Field>
          <Field label="Descrição" wide>
            <input className={inputClass} value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Para que serve este quadro" />
          </Field>
          <Field label="Visibilidade">
            <select className={inputClass} value={visibility} onChange={(event) => setVisibility(event.target.value)}>
              <option value="privado">Privado (só eu)</option>
              <option value="equipa">Equipa</option>
              <option value="organizacao">Toda a organização</option>
            </select>
          </Field>
          <Field label="Área">
            <select className={inputClass} value={category} onChange={(event) => setCategory(event.target.value)}>
              <option value="vendas">Vendas</option>
              <option value="clientes">Clientes</option>
              <option value="encomendas">Encomendas</option>
              <option value="operacao">Operação</option>
              <option value="compras">Compras</option>
              <option value="comercial">Comercial</option>
              <option value="geral">Geral</option>
            </select>
          </Field>
          <Field label="Período" hint="Janela de análise usada nos gráficos.">
            <select className={inputClass} value={period} onChange={(event) => setPeriod(Number(event.target.value))}>
              <option value={3}>3 meses</option>
              <option value={6}>6 meses</option>
              <option value={12}>12 meses</option>
              <option value={24}>24 meses</option>
            </select>
          </Field>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <p className="text-[12px] font-medium text-foreground">Widgets ({widgets.length})</p>
          <div className="min-w-0 flex-1" />
          <Button size="sm" variant="outline" icon={<Table2 size={13} />} onClick={addAll}>
            Sugestão (4)
          </Button>
          <Button size="sm" icon={<Plus size={13} />} onClick={add}>
            Adicionar gráfico
          </Button>
        </div>

        {catalogue.datasets.length === 0 && (
          <Notice text="O seu perfil não tem acesso a nenhum conjunto de dados analíticos." tone="error" />
        )}

        {widgets.length === 0 && catalogue.datasets.length > 0 && (
          <p className="rounded-xl border border-dashed border-white/12 px-3 py-6 text-center text-[12px] text-muted-foreground">
            Ainda não há gráficos. Use «Adicionar gráfico» para escolher um conjunto de dados.
          </p>
        )}

        <div className="flex flex-col gap-3">
          {widgets.map((widget, index) => {
            const dataset = byId.get(widget.dataset);
            const data = preview[widget.dataset] ?? null;
            const spec = data?.metrics.find((item) => item.key === widget.metric) ?? dataset?.metrics.find((item) => item.key === widget.metric);
            const points =
              data && spec
                ? data.rows.map((row) => ({ label: String(row[data.dimension.key] ?? row.label ?? "—"), value: Number(row[spec.key] ?? 0) }))
                : [];
            return (
              <div key={widget.id} className="rounded-xl border border-white/10 bg-white/[0.02] p-3">
                <div className="mb-2 flex items-center gap-2">
                  <span className="flex h-5 w-5 items-center justify-center rounded-md bg-white/10 text-[10.5px] text-muted-foreground">{index + 1}</span>
                  <select
                    className={inputClass}
                    value={widget.dataset}
                    onChange={(event) => {
                      const next = byId.get(event.target.value);
                      update(widget.id, { dataset: event.target.value, metric: defaultMetric(next), chart: next?.chart ?? "barras" });
                    }}
                    style={{ width: "auto", minWidth: 210 }}
                  >
                    {catalogue.groups.map((group) => (
                      <optgroup key={group} label={group}>
                        {catalogue.datasets
                          .filter((item) => item.group === group)
                          .map((item) => (
                            <option key={item.id} value={item.id}>
                              {item.label}
                            </option>
                          ))}
                      </optgroup>
                    ))}
                  </select>
                  <select
                    className={inputClass}
                    value={widget.metric}
                    onChange={(event) => update(widget.id, { metric: event.target.value })}
                    style={{ width: "auto", minWidth: 150 }}
                  >
                    {(dataset?.metrics ?? []).map((item) => (
                      <option key={item.key} value={item.key}>
                        {item.label}
                      </option>
                    ))}
                  </select>
                  <select
                    className={inputClass}
                    value={widget.chart}
                    onChange={(event) => update(widget.id, { chart: event.target.value as CrmChartKind })}
                    style={{ width: "auto", minWidth: 140 }}
                  >
                    {CHART_OPTIONS.map((kind) => (
                      <option key={kind} value={kind}>
                        {CHART_LABELS[kind]}
                      </option>
                    ))}
                  </select>
                  <select
                    className={inputClass}
                    value={widget.limit ?? 12}
                    onChange={(event) => update(widget.id, { limit: Number(event.target.value) })}
                    style={{ width: "auto", minWidth: 110 }}
                    title="Número de linhas no gráfico"
                  >
                    {[5, 8, 10, 12, 20, 30, 50].map((value) => (
                      <option key={value} value={value}>
                        Top {value}
                      </option>
                    ))}
                  </select>
                  <div className="min-w-0 flex-1" />
                  <button
                    type="button"
                    onClick={() => setWidgets((current) => current.filter((item) => item.id !== widget.id))}
                    className="rounded-lg p-1 text-muted-foreground transition hover:bg-white/10 hover:text-rose-200"
                  >
                    <Trash2 size={13} />
                  </button>
                </div>
                <p className="mb-2 text-[10.5px] text-muted-foreground/80">{dataset?.description}</p>
                {data === null && <p className="py-4 text-center text-[11.5px] text-muted-foreground">Sem pré-visualização para este conjunto de dados.</p>}
                {data && spec && (
                  <CrmChart
                    kind={widget.chart}
                    points={points}
                    format={(value) => formatMetric(spec.kind, value)}
                    title={widget.title || `Pré-visualização · ${spec.label}`}
                    subtitle={data ? `${data.linhas_mostradas} linha(s) · ${data.filtros.meses} meses` : undefined}
                    dimensionLabel={data.dimension.label}
                    metricLabel={spec.label}
                  />
                )}
              </div>
            );
          })}
        </div>
      </div>
    </Modal>
  );
}

/* --------------------------------------------------------------------- painel */

/** Um quadro gravado, em modo de leitura. */
export function CrmDashboardView({ dashboard, months }: { dashboard: CrmDashboard; months: number }) {
  const widgets = Array.isArray(dashboard.widgets) ? (dashboard.widgets as CrmDashboardWidget[]) : [];
  const period = Number(dashboard.period_months || months);
  if (widgets.length === 0) {
    return <p className="py-8 text-center text-[12px] text-muted-foreground">Este quadro ainda não tem gráficos.</p>;
  }
  return (
    <div className="grid grid-cols-1 gap-3 lg:grid-cols-2 xl:grid-cols-3">
      {widgets.map((widget) => (
        <CrmDatasetChart
          key={widget.id}
          datasetId={widget.dataset}
          metric={widget.metric}
          chart={widget.chart}
          months={period}
          limit={widget.limit || undefined}
          title={widget.title || undefined}
        />
      ))}
    </div>
  );
}

/**
 * Área de quadros: listagem, criação, edição e leitura.
 *
 * `compact` mostra só a lista (usado dentro do painel de Analytics, onde o espaço
 * é menor); sem `compact` acrescenta o cabeçalho de gestão.
 */
export function CrmDashboardsPanel({ months = 12 }: { months?: number }) {
  const { catalogue, error: catalogueError } = useDatasetCatalogue();
  const [dashboards, setDashboards] = useState<CrmDashboard[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [open, setOpen] = useState<CrmDashboard | null>(null);
  const [editing, setEditing] = useState<CrmDashboard | null | undefined>(undefined);
  const [period, setPeriod] = useState(months);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const result = await listCrmModule(DASHBOARD_SLUG, { size: 100 });
      const items = (result.items as CrmDashboard[]) ?? [];
      setDashboards(items);
      setError(null);
      setOpen((current) => (current ? items.find((item) => String(item.id) === String(current.id)) ?? items[0] ?? null : items[0] ?? null));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Não foi possível carregar os quadros");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    setPeriod(months);
  }, [months]);

  const datasetCount = catalogue?.total ?? 0;

  const duplicate = async (dashboard: CrmDashboard) => {
    try {
      const created = await createCrmModuleRecord<CrmDashboard>(DASHBOARD_SLUG, {
        name: `${dashboard.name} (cópia)`,
        description: dashboard.description ?? "",
        visibility: "privado",
        category: dashboard.category ?? "geral",
        period_months: dashboard.period_months ?? period,
        datasets: dashboard.datasets ?? "",
        widgets: dashboard.widgets ?? [],
      });
      setNotice(`Quadro duplicado: ${created.item?.name ?? ""}`);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Não foi possível duplicar o quadro");
    }
  };

  const remove = async (dashboard: CrmDashboard) => {
    try {
      await deleteCrmModuleRecord(DASHBOARD_SLUG, String(dashboard.id));
      setNotice(`Quadro «${dashboard.name}» eliminado.`);
      setOpen(null);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Não foi possível eliminar o quadro");
    }
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="inline-flex items-center gap-1.5 rounded-lg bg-white/[0.08] px-2.5 py-1 text-[12px] text-foreground">
          <LayoutDashboard size={13} /> Quadros
        </span>
        <span className="text-[11.5px] text-muted-foreground">
          {datasetCount} conjunto(s) de dados disponíveis
        </span>
        <div className="min-w-0 flex-1" />
        <select className={inputClass} value={period} onChange={(event) => setPeriod(Number(event.target.value))} style={{ width: 130 }}>
          <option value={3}>3 meses</option>
          <option value={6}>6 meses</option>
          <option value={12}>12 meses</option>
          <option value={24}>24 meses</option>
        </select>
        <Button size="sm" variant="outline" icon={<RefreshCw size={13} />} loading={loading} onClick={() => void load()}>
          Actualizar
        </Button>
        <Button size="sm" icon={<Plus size={13} />} onClick={() => setEditing(null)} disabled={!catalogue}>
          Novo quadro
        </Button>
      </div>

      {(error || catalogueError) && <Notice text={error || catalogueError || ""} tone="error" onClose={() => setError(null)} />}
      {notice && <Notice text={notice} onClose={() => setNotice(null)} />}

      {loading && dashboards.length === 0 && (
        <p className="flex items-center gap-2 py-8 text-[12.5px] text-muted-foreground">
          <Loader2 size={14} className="animate-spin" /> A carregar os quadros…
        </p>
      )}

      {!loading && dashboards.length === 0 && (
        <div className="rounded-xl border border-dashed border-white/12 px-4 py-10 text-center">
          <BarChart3 size={22} className="mx-auto mb-2 text-muted-foreground" />
          <p className="text-[13px] text-foreground">Ainda não criou quadros de análise.</p>
          <p className="mx-auto mt-1 max-w-lg text-[11.5px] text-muted-foreground">
            Um quadro junta vários gráficos — vendas por utilizador, encomendas, compras, operação — escolhendo o conjunto de dados,
            a métrica e o tipo de gráfico de cada um.
          </p>
          <div className="mt-3 flex justify-center">
            <Button size="sm" icon={<Plus size={13} />} onClick={() => setEditing(null)} disabled={!catalogue}>
              Criar o primeiro quadro
            </Button>
          </div>
        </div>
      )}

      {dashboards.length > 0 && (
        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap gap-2">
            {dashboards.map((dashboard) => {
              const active = open && String(open.id) === String(dashboard.id);
              return (
                <button
                  key={String(dashboard.id)}
                  type="button"
                  onClick={() => setOpen(dashboard)}
                  className={[
                    "flex max-w-[280px] flex-col items-start gap-0.5 rounded-xl border px-3 py-2 text-left transition",
                    active ? "border-teal-300/40 bg-teal-400/10" : "border-white/10 bg-white/[0.03] hover:bg-white/[0.06]",
                  ].join(" ")}
                >
                  <span className="flex items-center gap-1.5 text-[12.5px] font-medium text-foreground">
                    <LayoutDashboard size={13} /> {String(dashboard.name ?? "Quadro")}
                  </span>
                  <span className="text-[10.5px] text-muted-foreground">
                    {VISIBILITY_LABELS[String(dashboard.visibility)] ?? "Privado"} ·{" "}
                    {Array.isArray(dashboard.widgets) ? dashboard.widgets.length : 0} gráfico(s) · {Number(dashboard.period_months ?? 12)} meses
                  </span>
                </button>
              );
            })}
          </div>

          {open && (
            <div className="flex flex-col gap-2">
              <div className="flex flex-wrap items-center gap-2">
                <div className="min-w-0">
                  <p className="truncate text-[13.5px] font-semibold text-foreground">{String(open.name ?? "")}</p>
                  <p className="truncate text-[11px] text-muted-foreground">
                    {String(open.description || "Sem descrição")} · {String(open.datasets || "—")}
                  </p>
                </div>
                <div className="min-w-0 flex-1" />
                <Button size="sm" variant="outline" icon={<Pencil size={13} />} onClick={() => setEditing(open)}>
                  Editar
                </Button>
                <Button size="sm" variant="outline" icon={<Copy size={13} />} onClick={() => void duplicate(open)}>
                  Duplicar
                </Button>
                <Button size="sm" variant="outline" icon={<Trash2 size={13} />} onClick={() => void remove(open)}>
                  Eliminar
                </Button>
              </div>
              <CrmDashboardView dashboard={open} months={period} />
            </div>
          )}
        </div>
      )}

      {editing !== undefined && catalogue && (
        <DashboardEditor
          dashboard={editing}
          catalogue={catalogue}
          months={period}
          onClose={() => setEditing(undefined)}
          onSaved={(saved) => {
            setNotice(`Quadro «${saved.name}» gravado.`);
            setEditing(undefined);
            void load().then(() => setOpen(saved));
          }}
          onDeleted={() => setNotice("Quadro eliminado.")}
        />
      )}
    </div>
  );
}

/** Catálogo de datasets, para consulta rápida (área de quadros). */
export function CrmDatasetCatalogueList() {
  const { catalogue } = useDatasetCatalogue();
  if (!catalogue) return null;
  return (
    <div className="grid grid-cols-1 gap-2 lg:grid-cols-2">
      {catalogue.datasets.map((dataset) => (
        <div key={dataset.id} className={cardClass}>
          <p className="flex items-center gap-1.5 text-[12.5px] font-medium text-foreground">
            <Settings2 size={12} /> {dataset.label}
            <span className="rounded bg-white/10 px-1.5 text-[10px] text-muted-foreground">{dataset.group}</span>
          </p>
          <p className="mt-0.5 text-[11px] text-muted-foreground">{dataset.description}</p>
          <p className="mt-1 text-[10.5px] text-muted-foreground/80">
            Dimensão: {dataset.dimension.label} · Métricas: {dataset.metrics.map((metric) => metric.label).join(", ")}
          </p>
        </div>
      ))}
    </div>
  );
}
