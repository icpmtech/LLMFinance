/**
 * Cartão de um visual do Visualizador.
 *
 * Cada cartão é autónomo: guarda a sua configuração (tipo de gráfico, dimensões,
 * medidas, fórmulas, top-N), pede a agregação ao backend e desenha-a. Clicar num
 * ponto/linha abre a lista de registos (drill-through) que a página mostra.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import {
  ChevronDown,
  ChevronUp,
  Copy,
  Download,
  FileSpreadsheet,
  Image as ImageIcon,
  Loader2,
  Play,
  Table2,
  Target,
  TriangleAlert,
  X,
} from "lucide-react";
import type {
  ChartTypeInfo,
  DatasetDetail,
  QueryResult,
  QueryRow,
  VisualConfig,
  VisualFormula,
  VisualMeasureKind,
  VisualMeasureSpec,
} from "../../visualizadorApi";
import { buildQuery, runVisualQuery } from "../../visualizadorApi";
import { downloadChartPng, exportVisual } from "../../visualizadorExport";
import { FormulaEditor } from "./FormulaEditor";
import { VisualChart } from "./VisualChart";

const MEASURE_KIND_LABELS: Record<VisualMeasureKind, string> = {
  contagem: "Contagem",
  soma: "Soma",
  media: "Média",
  minimo: "Mínimo",
  maximo: "Máximo",
  distintos: "Valores distintos",
  mediana: "Mediana",
  p90: "Percentil 90",
};

/** Chave estável de uma medida (id de catálogo ou `tipo_campo`). */
export function specKey(spec: VisualMeasureSpec): string {
  if (typeof spec === "string") return spec;
  return spec.id || `${spec.kind}_${spec.field}`;
}

export function VisualCard({
  config,
  dataset,
  chartTypes,
  filters,
  search,
  active,
  onActivate,
  onChange,
  onRemove,
  onDuplicate,
  onDrill,
}: {
  config: VisualConfig;
  dataset: DatasetDetail | null;
  chartTypes: ChartTypeInfo[];
  filters: Record<string, unknown>;
  search: string;
  active: boolean;
  onActivate: () => void;
  onChange: (patch: Partial<VisualConfig>) => void;
  onRemove: () => void;
  onDuplicate: () => void;
  onDrill: (row: QueryRow) => void;
}) {
  const [result, setResult] = useState<QueryResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [showConfig, setShowConfig] = useState(false);
  const [showMeasures, setShowMeasures] = useState(false);
  const [customKind, setCustomKind] = useState<VisualMeasureKind>("distintos");
  const [customField, setCustomField] = useState("");
  const [refreshTick, setRefreshTick] = useState(0);
  const chartRef = useRef<HTMLDivElement | null>(null);

  const payload = useMemo(
    () => (dataset ? buildQuery(config, dataset.dataset.id, filters, search) : null),
    [config, dataset, filters, search],
  );
  const payloadKey = payload ? JSON.stringify(payload) : "";

  useEffect(() => {
    if (!payload) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    runVisualQuery(payload)
      .then((response) => {
        if (cancelled) return;
        setResult(response);
        if (response.error && (response.rows ?? []).length === 0) setError(response.error);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Erro ao consultar os dados.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [payloadKey, refreshTick]);

  const selectedMeasures = useMemo(() => new Set(config.measures.map(specKey)), [config.measures]);
  const measureNames = useMemo(() => {
    const names = (result?.measures ?? []).map((measure) => measure.label || measure.id);
    return [...names, ...(result?.formulas ?? []).map((formula) => formula.label)];
  }, [result]);

  const toggleMeasure = (id: string) => {
    const exists = config.measures.some((spec) => specKey(spec) === id);
    onChange({
      measures: exists ? config.measures.filter((spec) => specKey(spec) !== id) : [...config.measures, { id }],
    });
  };

  const addCustomMeasure = () => {
    if (!customField) return;
    const id = `${customKind}_${customField}`;
    if (config.measures.some((spec) => specKey(spec) === id)) return;
    onChange({ measures: [...config.measures, { id, kind: customKind, field: customField }] });
    setShowMeasures(false);
  };

  const setDimension = (position: number, id: string) => {
    const next = [...config.dimensions];
    while (next.length <= position) next.push({ id: "" });
    if (!id) {
      next[position] = { id: "" };
    } else {
      const entry = dataset?.dimensions.find((dimension) => dimension.id === id);
      next[position] = { id, interval: entry?.type === "date" ? next[position]?.interval || "mes" : undefined };
    }
    onChange({ dimensions: next.slice(0, Math.max(1, position + 1)) });
  };

  const doExport = async (format: "csv" | "xlsx") => {
    if (!payload) return;
    setBusy(format);
    setError(null);
    try {
      await exportVisual(format, payload);
    } catch (err) {
      setError(err instanceof Error ? err.message : "A exportação falhou.");
    } finally {
      setBusy(null);
    }
  };

  const doPng = async () => {
    setBusy("png");
    try {
      await downloadChartPng(chartRef.current, config.title);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Não foi possível guardar a imagem.");
    } finally {
      setBusy(null);
    }
  };

  const notes = result?.meta?.notes ?? [];
  const truncated = Boolean(result?.meta?.truncated);

  return (
    <div
      onMouseDown={onActivate}
      onFocus={onActivate}
      className={[
        "glass-card gradient-border rounded-2xl p-4 flex flex-col gap-3 fade-in",
        active ? "ring-1 ring-primary/50" : "",
      ].join(" ")}
    >
      <div className="flex items-start gap-2">
        <input
          value={config.title}
          onChange={(event) => onChange({ title: event.target.value })}
          aria-label="Título do visual"
          className="flex-1 min-w-0 bg-transparent text-sm font-semibold focus:outline-none focus:ring-2 focus:ring-primary/40 rounded-lg px-1 py-0.5"
        />
        <select
          value={config.chart}
          onChange={(event) => onChange({ chart: event.target.value })}
          aria-label="Tipo de gráfico"
          className="px-2 py-1 rounded-lg glass-card text-xs"
        >
          {chartTypes.map((chart) => (
            <option key={chart.id} value={chart.id}>{chart.label}</option>
          ))}
        </select>
        <button type="button" onClick={onActivate} title="Tornar este visual o ativo"
                className={["p-1.5 rounded-lg glass-card", active ? "text-primary" : "text-muted-foreground hover:text-foreground"].join(" ")}
                aria-label="Tornar este visual o ativo">
          <Target size={13} />
        </button>
        <button type="button" onClick={() => setShowConfig((value) => !value)} title="Configurar visual"
                aria-label="Configurar visual" aria-expanded={showConfig}
                className="p-1.5 rounded-lg glass-card text-muted-foreground hover:text-foreground">
          {showConfig ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
        </button>
        <button type="button" onClick={onDuplicate} title="Duplicar visual" aria-label="Duplicar visual"
                className="p-1.5 rounded-lg glass-card text-muted-foreground hover:text-foreground">
          <Copy size={13} />
        </button>
        <button type="button" onClick={onRemove} title="Remover visual" aria-label="Remover visual"
                className="p-1.5 rounded-lg glass-card text-muted-foreground hover:text-rose-300">
          <X size={13} />
        </button>
      </div>

      {showConfig && dataset && (
        <div className="rounded-xl border border-border/60 bg-background/30 p-3 space-y-3">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
            {[0, 1, 2].slice(0, config.chart === "kpi" ? 0 : config.chart === "stacked" || config.chart === "matrix" || config.chart === "treemap" ? 2 : 1).map((position) => {
              const current = config.dimensions[position]?.id ?? "";
              const entry = dataset.dimensions.find((dimension) => dimension.id === current);
              return (
                <div key={position} className="space-y-1">
                  <label className="text-[11px] text-muted-foreground">{position === 0 ? "Dimensão" : `Dimensão ${position + 1}`}</label>
                  <div className="flex gap-1.5">
                    <select
                      value={current}
                      onChange={(event) => setDimension(position, event.target.value)}
                      aria-label={position === 0 ? "Dimensão" : `Dimensão ${position + 1}`}
                      className="flex-1 min-w-0 px-2 py-1.5 rounded-lg glass-card text-xs"
                    >
                      <option value="">— escolher —</option>
                      {dataset.dimensions.map((dimension) => (
                        <option key={dimension.id} value={dimension.id}>{dimension.label}</option>
                      ))}
                    </select>
                    {entry?.type === "date" && (
                      <select
                        value={config.dimensions[position]?.interval || "mes"}
                        onChange={(event) => {
                          const next = [...config.dimensions];
                          next[position] = { id: current, interval: event.target.value };
                          onChange({ dimensions: next });
                        }}
                        aria-label="Intervalo temporal"
                        className="px-2 py-1.5 rounded-lg glass-card text-xs"
                      >
                        {["dia", "semana", "mes", "trimestre", "ano"].map((interval) => (
                          <option key={interval} value={interval}>{interval}</option>
                        ))}
                      </select>
                    )}
                  </div>
                </div>
              );
            })}
          </div>

          <div className="space-y-1">
            <div className="flex items-center justify-between">
              <span className="text-[11px] text-muted-foreground">Medidas</span>
              <button type="button" onClick={() => setShowMeasures((value) => !value)}
                      className="text-[11px] text-primary hover:underline">
                {showMeasures ? "Fechar" : "Escolher / medida personalizada"}
              </button>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {config.measures.length === 0 && <span className="text-[11px] text-amber-300">Sem medidas — o visual ficará vazio.</span>}
              {config.measures.map((spec) => {
                const key = specKey(spec);
                const column = (result?.columns ?? []).find((item) => item.key === key);
                return (
                  <span key={key} className="flex items-center gap-1 px-2 py-1 rounded-full glass-card text-[11px]">
                    {column?.label ?? (typeof spec === "string" ? spec : spec.label ?? key)}
                    <button type="button" onClick={() => onChange({ measures: config.measures.filter((item) => specKey(item) !== key) })}
                            aria-label="Remover medida" className="text-muted-foreground hover:text-rose-300">
                      <X size={10} />
                    </button>
                  </span>
                );
              })}
            </div>
            {showMeasures && (
              <div className="rounded-xl border border-border/60 bg-background/50 p-2 space-y-2 max-h-56 overflow-y-auto">
                {dataset.measures.map((measure) => (
                  <label key={measure.id} className="flex items-center gap-2 text-xs cursor-pointer hover:bg-white/5 rounded-lg px-1.5 py-1">
                    <input type="checkbox" checked={selectedMeasures.has(measure.id)} onChange={() => toggleMeasure(measure.id)}
                           className="accent-[var(--color-primary)]" />
                    <span className="truncate">{measure.label || measure.id}</span>
                    <span className="ml-auto text-[10px] text-muted-foreground">{MEASURE_KIND_LABELS[measure.kind] ?? measure.kind}</span>
                  </label>
                ))}
                <div className="pt-2 border-t border-border/60 space-y-1.5">
                  <p className="text-[11px] font-semibold">Medida personalizada sobre qualquer campo</p>
                  <div className="flex gap-1.5">
                    <select value={customKind} onChange={(event) => setCustomKind(event.target.value as VisualMeasureKind)}
                            aria-label="Tipo de medida personalizada" className="px-2 py-1 rounded-lg glass-card text-xs">
                      {(Object.keys(MEASURE_KIND_LABELS) as VisualMeasureKind[]).map((kind) => (
                        <option key={kind} value={kind}>{MEASURE_KIND_LABELS[kind]}</option>
                      ))}
                    </select>
                    <select value={customField} onChange={(event) => setCustomField(event.target.value)}
                            aria-label="Campo da medida personalizada" className="flex-1 min-w-0 px-2 py-1 rounded-lg glass-card text-xs">
                      <option value="">— campo —</option>
                      {dataset.dimensions.map((dimension) => (
                        <option key={dimension.id} value={dimension.id}>{dimension.label}</option>
                      ))}
                    </select>
                    <button type="button" onClick={addCustomMeasure} disabled={!customField || customKind === "contagem"}
                            className="px-2 py-1 rounded-lg glass-card text-xs disabled:opacity-40">
                      Adicionar
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>

          <FormulaEditor formulas={config.formulas} names={measureNames} max={12}
                         onChange={(formulas: VisualFormula[]) => onChange({ formulas })} />

          <div className="flex flex-wrap items-center gap-2 text-xs">
            <label className="flex items-center gap-1.5">
              <span className="text-muted-foreground">Grupos</span>
              <input type="number" min={1} max={500} value={config.limit}
                     onChange={(event) => onChange({ limit: Number(event.target.value) || 25 })}
                     className="w-16 px-2 py-1 rounded-lg glass-card text-xs" aria-label="Número de grupos" />
            </label>
            <label className="flex items-center gap-1.5">
              <span className="text-muted-foreground">Top</span>
              <input type="number" min={0} max={500} value={config.top_n}
                     onChange={(event) => onChange({ top_n: Number(event.target.value) || 0 })}
                     className="w-16 px-2 py-1 rounded-lg glass-card text-xs" aria-label="Top N" />
            </label>
            <label className="flex items-center gap-1.5">
              <input type="checkbox" checked={config.others} onChange={(event) => onChange({ others: event.target.checked })}
                     className="accent-[var(--color-primary)]" />
              <span className="text-muted-foreground">Agrupar restantes em «Outros»</span>
            </label>
            <label className="flex items-center gap-1.5">
              <span className="text-muted-foreground">Ordenar por</span>
              <select value={config.sort.by} onChange={(event) => onChange({ sort: { ...config.sort, by: event.target.value } })}
                      aria-label="Ordenar por" className="px-2 py-1 rounded-lg glass-card text-xs">
                <option value="">— predefinido —</option>
                {(result?.columns ?? []).filter((column) => column.type !== "dimension").map((column) => (
                  <option key={column.key} value={column.key}>{column.label}</option>
                ))}
              </select>
              <select value={config.sort.order} onChange={(event) => onChange({ sort: { ...config.sort, order: event.target.value as "asc" | "desc" } })}
                      aria-label="Sentido da ordenação" className="px-2 py-1 rounded-lg glass-card text-xs">
                <option value="desc">↓</option>
                <option value="asc">↑</option>
              </select>
            </label>
          </div>
        </div>
      )}

      <div ref={chartRef} className="h-64 md:h-72 relative">
        {loading && !result && (
          <div className="absolute inset-0 flex items-center justify-center">
            <Loader2 size={24} className="animate-spin text-teal-400" />
          </div>
        )}
        {error && !result && (
          <div className="h-full flex items-center justify-center gap-2 text-sm text-rose-300 px-6 text-center">
            <TriangleAlert size={16} /> {error}
          </div>
        )}
        {result && !error && <VisualChart result={result} config={config} onSelectRow={onDrill} />}
      </div>

      <div className="flex items-center gap-2 flex-wrap text-[10px] text-muted-foreground">
        <button type="button" onClick={() => setRefreshTick((value) => value + 1)} title="Atualizar dados"
                aria-label="Atualizar dados" className="p-1 rounded-lg glass-card hover:text-foreground">
          <Play size={11} />
        </button>
        <button type="button" onClick={() => doExport("csv")} disabled={busy !== null} title="Exportar CSV"
                aria-label="Exportar CSV" className="p-1 rounded-lg glass-card hover:text-foreground disabled:opacity-40">
          <Download size={11} />
        </button>
        <button type="button" onClick={() => doExport("xlsx")} disabled={busy !== null} title="Exportar Excel"
                aria-label="Exportar Excel" className="p-1 rounded-lg glass-card hover:text-foreground disabled:opacity-40">
          <FileSpreadsheet size={11} />
        </button>
        <button type="button" onClick={doPng} disabled={busy !== null} title="Guardar imagem (PNG)"
                aria-label="Guardar imagem" className="p-1 rounded-lg glass-card hover:text-foreground disabled:opacity-40">
          <ImageIcon size={11} />
        </button>
        {config.chart !== "matrix" && (
          <button type="button" onClick={() => onChange({ chart: "matrix" })} title="Ver como tabela"
                  aria-label="Ver como tabela" className="p-1 rounded-lg glass-card hover:text-foreground">
            <Table2 size={11} />
          </button>
        )}
        {loading && <Loader2 size={11} className="animate-spin" />}
        <span className="ml-auto">
          {result?.meta?.documents !== undefined ? `${Number(result.meta.documents).toLocaleString("pt-PT")} registos` : ""}
          {result?.meta?.groups !== undefined ? ` · ${result.meta.groups} grupos` : ""}
          {result?.meta?.elapsed_ms !== undefined ? ` · ${result.meta.elapsed_ms} ms` : ""}
        </span>
      </div>

      {truncated && (
        <p className="text-[11px] text-amber-300 flex items-start gap-1.5">
          <TriangleAlert size={12} className="mt-0.5 shrink-0" />
          Resultado truncado: há mais grupos do que os mostrados. Aumente «Grupos», filtre ou use Top-N.
        </p>
      )}
      {notes.length > 0 && (
        <ul className="text-[10px] text-muted-foreground space-y-0.5">
          {notes.slice(0, 3).map((note, index) => (
            <li key={index}>· {note}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
